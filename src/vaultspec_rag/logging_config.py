"""The one logging backend for vaultspec-rag.

Console configuration delegates to :mod:`vaultspec_core.logging_config`, which
owns it for every vaultspec package; RAG held a near-verbatim copy once and no
longer does, so the two cannot diverge. What RAG adds on top has no counterpart
in core and lives only here:

* ``log_event`` - the canonical ``namespace event=name key=value`` record shape
  every producer in this package emits through.
* ``DaemonLogCapture`` - the daemon's single-writer pipeline. Root logging,
  Uvicorn, ``print``, and native stdout/stderr all enter one pipe, so every
  byte the service emits participates in rotation.
* ``PolledAccessFilter`` and the third-party level table - what keeps the
  managed log carrying signal rather than timer polls and library chatter.
* The bounded managed-log reader every operator surface adapts to.

Producers do not configure logging themselves. A module that installs its own
handler, opens its own file, or renders progress into the stream writes bytes
that nothing here formats, bounds, rotates, or can read back.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict, cast

from vaultspec_core.logging_config import (
    configure_logging as _core_configure_logging,
)

from ._managed_log_sink import RawRotatingLogSink
from ._test_isolation import enforce_pytest_singleton_containment
from .config._settings import managed_status_dir

__all__ = [
    "DEFAULT_MANAGED_LOG_LINES",
    "MANAGED_LOG_TRUNCATION_MARKER",
    "MAX_MANAGED_LOG_LINES",
    "MAX_MANAGED_LOG_RECORD_BYTES",
    "MAX_MANAGED_LOG_SOURCE_BYTES",
    "POLLED_ROUTES",
    "QDRANT_LOG_NAME",
    "DaemonLogCapture",
    "InvalidManagedLogSourceError",
    "ManagedLogGroup",
    "ManagedLogSource",
    "ManagedLogsResult",
    "PolledAccessFilter",
    "clamp_managed_log_lines",
    "configure_logging",
    "install_daemon_log_capture",
    "log_event",
    "managed_log_filters",
    "query_managed_logs",
    "read_managed_logs",
    "render_managed_log_groups",
    "validate_managed_log_payload",
]

logger = logging.getLogger(__name__)
_daemon_logging_install_lock = threading.RLock()

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType
    from typing import TextIO

_EVENT_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_FIELD_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BARE_VALUE_RE = re.compile(r"^[A-Za-z0-9_./:@\\-]+$")

#: A plain alias, not a ``type`` statement: Typer resolves the Literal
#: object but cannot unwrap a TypeAliasType, and the log verb annotates
#: its --source option with this.
ManagedLogSource = Literal["service", "qdrant", "all"]
type ManagedLogGroupSource = Literal["service", "qdrant"]


class ManagedLogGroup(TypedDict):
    """One source's raw records, ordered only within that source."""

    source: ManagedLogGroupSource
    lines: list[str]
    truncated: NotRequired[bool]
    marker: NotRequired[str]
    truncation: NotRequired[dict[str, int | bool]]


class ManagedLogsResult(TypedDict):
    """The bounded managed-log outcome :func:`query_managed_logs` returns."""

    source: str
    limit: int
    groups: list[ManagedLogGroup]
    filters: dict[str, str]


class InvalidManagedLogSourceError(ValueError):
    """Raised when a managed-log source selector is not supported."""


_MANAGED_LOG_SOURCES: tuple[ManagedLogGroupSource, ...] = ("service", "qdrant")
#: The vector backend's managed log filename. Public because the supervisor
#: that writes this file and the reader below must name it identically; two
#: literals desync silently the moment either is renamed.
QDRANT_LOG_NAME = "qdrant.log"
DEFAULT_MANAGED_LOG_LINES = 200
MAX_MANAGED_LOG_LINES = 5_000
MAX_MANAGED_LOG_RECORD_BYTES = 64 * 1024
MAX_MANAGED_LOG_SOURCE_BYTES = 2 * 1024 * 1024
MANAGED_LOG_TRUNCATION_MARKER = (
    "[vaultspec-rag: managed log output truncated by byte budget]"
)
_RECORD_TRUNCATION_MARKER = "...[vaultspec-rag record truncated]..."
_RECORD_PREFIX_OMITTED_MARKER = "[...vaultspec-rag record prefix omitted...]"


class _TailFileWindow(TypedDict):
    lines: list[str]
    scanned_bytes: int
    omitted_bytes: int
    record_truncations: int
    source_budget_exhausted: bool


def _format_event_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Path):
        value = str(value)

    rendered = str(value)
    if _BARE_VALUE_RE.fullmatch(rendered):
        return rendered
    return json.dumps(rendered, ensure_ascii=True)


def log_event(
    target_logger: logging.Logger,
    namespace: str,
    event: str,
    **extra_fields: object,
) -> None:
    """Emit a parseable service event through the configured logger.

    Events use a stable ``namespace event=name key=value`` message shape
    so CLI log filtering, MCP adapters, and external collectors can
    consume the same stream without depending on human-facing formatting.
    Values containing whitespace or shell-significant punctuation are
    JSON-quoted; common identifiers and paths remain bare for greppability.
    """
    if not _EVENT_TOKEN_RE.fullmatch(namespace):
        msg = f"invalid log event namespace: {namespace!r}"
        raise ValueError(msg)
    if not _EVENT_TOKEN_RE.fullmatch(event):
        msg = f"invalid log event name: {event!r}"
        raise ValueError(msg)

    severity = cast("int", extra_fields.pop("severity", logging.INFO))
    exc_info = cast(
        "EventExcInfo",
        extra_fields.pop("exc_info", None),
    )
    fields = cast("Mapping[str, object] | None", extra_fields.pop("fields", None))
    combined_fields: dict[str, object] = {}
    if fields is not None:
        combined_fields.update(fields)
    combined_fields.update(extra_fields)

    parts = [namespace, f"event={event}"]
    for key, value in combined_fields.items():
        if not _FIELD_TOKEN_RE.fullmatch(key):
            msg = f"invalid log event field: {key!r}"
            raise ValueError(msg)
        parts.append(f"{key}={_format_event_value(value)}")

    target_logger.log(
        severity,
        "%s",
        " ".join(parts),
        exc_info=exc_info,
        extra={
            "vaultspec_event_namespace": namespace,
            "vaultspec_event": event,
            "vaultspec_event_fields": dict(combined_fields),
        },
    )


def _resolve_status_dir(status_dir: Path | None) -> Path:
    """Resolve the service status directory for the log reader.

    Mirrors the CLI's ``_status_dir`` / the daemon's
    ``_resolve_log_path`` resolution (``cfg.status_dir`` with env-var
    and CLI overrides) so the reader walks the same directory the
    daemon rotates into. An explicit *status_dir* (used by tests)
    short-circuits config resolution.
    """
    if status_dir is not None:
        return status_dir

    return managed_status_dir()


def _managed_log_source(raw: str) -> ManagedLogSource:
    if raw == "service":
        return "service"
    if raw == "qdrant":
        return "qdrant"
    if raw == "all":
        return "all"
    msg = "source must be one of service, qdrant, all."
    raise InvalidManagedLogSourceError(msg)


def _managed_log_name(source: ManagedLogGroupSource) -> str:
    if source == "qdrant":
        return QDRANT_LOG_NAME
    from .config._settings import get_config

    return str(get_config().log_file)


def _rotated_log_paths(status_dir: Path, log_name: str) -> list[Path]:
    """Return sparse generations oldest-first, followed by the active file."""
    suffix_re = re.compile(rf"^{re.escape(log_name)}\.(\d+)$")
    generations: list[tuple[int, Path]] = []
    try:
        entries = status_dir.iterdir()
        for entry in entries:
            match = suffix_re.fullmatch(entry.name)
            if match is None:
                continue
            generation = int(match.group(1))
            if generation > 0:
                generations.append((generation, entry))
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.debug("managed log directory %s unreadable: %s", status_dir, exc)

    generations.sort(key=lambda item: item[0], reverse=True)
    return [*(path for _generation, path in generations), status_dir / log_name]


def clamp_managed_log_lines(raw: object) -> int:
    """Parse and clamp an operator-requested per-source record count."""
    if raw is None:
        return DEFAULT_MANAGED_LOG_LINES
    try:
        value = int(cast("Any", raw))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_MANAGED_LOG_LINES
    if value <= 0:
        return DEFAULT_MANAGED_LOG_LINES
    return min(value, MAX_MANAGED_LOG_LINES)


def managed_log_filters(
    *,
    job_id: str | None = None,
    contains: str | None = None,
) -> dict[str, str]:
    """Return the non-empty filters accepted by the managed-log contract."""
    filters: dict[str, str] = {}
    if job_id and job_id.strip():
        filters["job_id"] = job_id.strip()
    if contains and contains.strip():
        filters["contains"] = contains.strip()
    return filters


def _truncate_record(raw: bytes, *, prefix_omitted: bool = False) -> tuple[str, int]:
    """Decode one physical record within the finite per-record response budget."""
    raw = raw[:-1] if raw.endswith(b"\r") else raw
    text = raw.decode("utf-8", errors="replace")
    encoded = text.encode("utf-8")
    marker = (
        _RECORD_PREFIX_OMITTED_MARKER if prefix_omitted else _RECORD_TRUNCATION_MARKER
    )
    marker_bytes = marker.encode("utf-8")
    if not prefix_omitted and len(encoded) <= MAX_MANAGED_LOG_RECORD_BYTES:
        return text, 0

    content_budget = max(0, MAX_MANAGED_LOG_RECORD_BYTES - len(marker_bytes))
    if prefix_omitted:
        tail = encoded[-content_budget:] if content_budget else b""
        rendered = marker + tail.decode("utf-8", errors="ignore")
    else:
        head_budget = content_budget // 2
        tail_budget = content_budget - head_budget
        head = encoded[:head_budget].decode("utf-8", errors="ignore")
        tail = (
            encoded[-tail_budget:].decode("utf-8", errors="ignore")
            if tail_budget
            else ""
        )
        rendered = head + marker + tail
    retained = max(0, len(rendered.encode("utf-8")) - len(marker_bytes))
    return rendered, max(0, len(raw) - retained)


def _tail_file_window(path: Path, lines: int, byte_budget: int) -> _TailFileWindow:
    """Read one file's newest records with a hard backward-read byte ceiling."""
    empty: _TailFileWindow = {
        "lines": [],
        "scanned_bytes": 0,
        "omitted_bytes": 0,
        "record_truncations": 0,
        "source_budget_exhausted": False,
    }
    if lines <= 0 or byte_budget <= 0:
        return empty
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            scan_bytes = min(size, byte_budget)
            start = size - scan_bytes
            # Read one preceding byte solely to decide whether *start* is a
            # physical-record boundary. The retained scan window never exceeds
            # byte_budget, including for a newline-free multi-gigabyte file.
            probe_start = max(0, start - 1)
            stream.seek(probe_start)
            data = stream.read(size - probe_start)
    except FileNotFoundError as exc:
        logger.debug("managed log %s vanished mid-read: %s", path, exc)
        return empty
    except OSError as exc:
        logger.debug("managed log %s unreadable: %s", path, exc)
        return empty

    if not data:
        return empty
    prefix_is_partial = False
    if probe_start < start:
        prefix_is_partial = data[:1] != b"\n"
        data = data[1:]

    omitted_bytes = start
    record_truncations = 0
    if prefix_is_partial:
        first_newline = data.find(b"\n")
        if first_newline < 0:
            rendered, record_omitted = _truncate_record(data, prefix_omitted=True)
            return {
                "lines": [rendered],
                "scanned_bytes": scan_bytes,
                "omitted_bytes": omitted_bytes + record_omitted,
                "record_truncations": 1,
                "source_budget_exhausted": True,
            }
        omitted_bytes += first_newline + 1
        data = data[first_newline + 1 :]

    raw_lines = data.split(b"\n")
    if data.endswith(b"\n"):
        raw_lines.pop()
    raw_lines = raw_lines[-lines:]
    rendered_lines: list[str] = []
    for raw_line in raw_lines:
        rendered, record_omitted = _truncate_record(raw_line)
        rendered_lines.append(rendered)
        if record_omitted:
            record_truncations += 1
            omitted_bytes += record_omitted
    return {
        "lines": rendered_lines,
        "scanned_bytes": scan_bytes,
        "omitted_bytes": omitted_bytes,
        "record_truncations": record_truncations,
        "source_budget_exhausted": start > 0,
    }


def _path_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


@dataclass
class _ManagedSourceProgress:
    """Running per-source tally threaded through the newest-first scan."""

    remaining: int
    remaining_bytes: int
    scanned_bytes: int = 0
    omitted_bytes: int = 0
    record_truncations: int = 0
    source_budget_exhausted: bool = False
    newest_chunks: list[list[str]] = field(default_factory=list)


def _consume_managed_source_path(
    progress: _ManagedSourceProgress,
    path: Path,
    paths: list[Path],
    index: int,
) -> bool:
    """Fold one rotated-log path's window into *progress*.

    Returns True when the scan must stop: either the byte budget was already
    spent before this path, or this path's read exhausted it.
    """
    if progress.remaining_bytes <= 0:
        older_bytes = sum(_path_size(candidate) for candidate in paths[index:])
        if older_bytes:
            progress.source_budget_exhausted = True
            progress.omitted_bytes += older_bytes
        return True
    window = _tail_file_window(path, progress.remaining, progress.remaining_bytes)
    chunk = window["lines"]
    progress.scanned_bytes += window["scanned_bytes"]
    progress.remaining_bytes -= window["scanned_bytes"]
    progress.omitted_bytes += window["omitted_bytes"]
    progress.record_truncations += window["record_truncations"]
    if window["source_budget_exhausted"]:
        progress.source_budget_exhausted = True
        progress.omitted_bytes += sum(
            _path_size(candidate) for candidate in paths[index + 1 :]
        )
        if chunk:
            progress.newest_chunks.append(chunk)
            progress.remaining -= len(chunk)
        return True
    if chunk:
        progress.newest_chunks.append(chunk)
        progress.remaining -= len(chunk)
    return False


def _read_managed_source(
    status_dir: Path,
    source: ManagedLogGroupSource,
    lines: int,
) -> ManagedLogGroup:
    paths = list(reversed(_rotated_log_paths(status_dir, _managed_log_name(source))))
    progress = _ManagedSourceProgress(
        remaining=max(0, lines),
        remaining_bytes=MAX_MANAGED_LOG_SOURCE_BYTES,
    )
    # Paths are chronological; read them newest-first so older generations are
    # never touched after the requested per-source record bound is satisfied.
    for index, path in enumerate(paths):
        if progress.remaining <= 0:
            break
        if _consume_managed_source_path(progress, path, paths, index):
            break

    source_lines = [
        line for chunk in reversed(progress.newest_chunks) for line in chunk
    ]
    group: ManagedLogGroup = {"source": source, "lines": source_lines}
    if progress.source_budget_exhausted or progress.record_truncations:
        group["truncated"] = True
        group["marker"] = MANAGED_LOG_TRUNCATION_MARKER
        group["truncation"] = {
            "record_limit_bytes": MAX_MANAGED_LOG_RECORD_BYTES,
            "source_limit_bytes": MAX_MANAGED_LOG_SOURCE_BYTES,
            "scanned_bytes": progress.scanned_bytes,
            "returned_content_bytes": 0,
            "omitted_bytes_at_least": progress.omitted_bytes,
            "record_truncations": progress.record_truncations,
            "source_budget_exhausted": progress.source_budget_exhausted,
            "response_budget_exhausted": False,
            "omitted_response_records": 0,
        }
    return group


def read_managed_logs(
    lines: int,
    *,
    source: str = "all",
    status_dir: Path | None = None,
) -> list[ManagedLogGroup]:
    """Return bounded raw records grouped by managed producer.

    ``all`` returns the service group followed by the Qdrant group. That is a
    stable display order only: no chronology is inferred across producers.
    Within each group, records are oldest-first and span any sparse numeric
    backup generations plus the active file. Missing or concurrently rotated
    files are skipped without failing the whole operator view.

    Args:
        lines: Maximum records returned for each selected source. Non-positive
            values retain the selected empty group or groups.
        source: ``service``, ``qdrant``, or ``all`` (the default).
        status_dir: Explicit managed-log directory, primarily for offline use
            and tests. Defaults to the configured status directory.

    Raises:
        InvalidManagedLogSourceError: When *source* is not supported.
    """
    selected = _managed_log_source(source)
    selected_sources = _MANAGED_LOG_SOURCES if selected == "all" else (selected,)
    base = _resolve_status_dir(status_dir)
    return [
        _read_managed_source(base, managed_source, lines)
        for managed_source in selected_sources
    ]


def _filter_managed_log_groups(
    groups: list[ManagedLogGroup],
    *,
    job_id: str | None = None,
    contains: str | None = None,
) -> None:
    """Apply case-insensitive AND filters in place without losing metadata."""
    job_filter = job_id.strip().lower() if job_id else None
    contains_filter = contains.strip().lower() if contains else None
    if not job_filter and not contains_filter:
        return
    for group in groups:
        filtered: list[str] = []
        for line in group["lines"]:
            lowered = line.lower()
            if job_filter and job_filter not in lowered:
                continue
            if contains_filter and contains_filter not in lowered:
                continue
            filtered.append(line)
        group["lines"] = filtered


def _json_line_bytes(line: str) -> int:
    return len(json.dumps(line, ensure_ascii=True).encode("utf-8")) + 1


def _fit_newest_lines(lines: list[str], byte_budget: int) -> tuple[list[str], int]:
    kept_newest: list[str] = []
    used = 0
    for line in reversed(lines):
        cost = _json_line_bytes(line)
        if used + cost > byte_budget:
            break
        kept_newest.append(line)
        used += cost
    kept_newest.reverse()
    return kept_newest, used


def _bound_managed_group_response(group: ManagedLogGroup, limit: int) -> None:
    """Apply the final line and encoded-byte response bounds to one source."""
    selected = group["lines"][-limit:] if limit > 0 else []
    already_truncated = bool(group.get("truncated"))
    marker_cost = _json_line_bytes(MANAGED_LOG_TRUNCATION_MARKER)
    available = MAX_MANAGED_LOG_SOURCE_BYTES - (marker_cost if already_truncated else 0)
    fitted, used = _fit_newest_lines(selected, max(0, available))
    response_omitted = len(selected) - len(fitted)
    if response_omitted and not already_truncated:
        already_truncated = True
        available = MAX_MANAGED_LOG_SOURCE_BYTES - marker_cost
        fitted, used = _fit_newest_lines(selected, max(0, available))
        response_omitted = len(selected) - len(fitted)

    group["lines"] = fitted
    if not already_truncated:
        return
    existing = group.get("truncation")
    truncation = (
        dict(existing)
        if existing is not None
        else {
            "record_limit_bytes": MAX_MANAGED_LOG_RECORD_BYTES,
            "source_limit_bytes": MAX_MANAGED_LOG_SOURCE_BYTES,
            "scanned_bytes": 0,
            "omitted_bytes_at_least": 0,
            "record_truncations": 0,
            "source_budget_exhausted": False,
        }
    )
    # Exact UTF-8 byte cost of the JSON-encoded line values plus the visible
    # marker. Envelope keys and fixed metadata are deliberately not included.
    truncation["returned_content_bytes"] = used + marker_cost
    truncation["response_budget_exhausted"] = response_omitted > 0
    truncation["omitted_response_records"] = response_omitted
    group["truncated"] = True
    group["marker"] = MANAGED_LOG_TRUNCATION_MARKER
    group["truncation"] = truncation


def query_managed_logs(
    lines: object = None,
    *,
    source: str = "all",
    job_id: str | None = None,
    contains: str | None = None,
    status_dir: Path | None = None,
) -> ManagedLogsResult:
    """Return the canonical bounded managed-log outcome for every adapter."""
    limit = clamp_managed_log_lines(lines)
    filters = managed_log_filters(job_id=job_id, contains=contains)
    read_limit = MAX_MANAGED_LOG_LINES if filters else limit
    groups = read_managed_logs(read_limit, source=source, status_dir=status_dir)
    if filters:
        _filter_managed_log_groups(groups, **filters)
    for group in groups:
        _bound_managed_group_response(group, limit)
    return {
        "source": source,
        "limit": limit,
        "groups": groups,
        "filters": filters,
    }


def render_managed_log_groups(groups: list[ManagedLogGroup]) -> str:
    """Render labeled source sections and visible truncation markers."""
    rendered: list[str] = []
    for group in groups:
        rendered.append(f"[{group['source']}]")
        marker = group.get("marker")
        if marker:
            rendered.append(marker)
        rendered.extend(group["lines"])
    return "\n".join(rendered)


def _validated_managed_log_lines(raw: object, *, limit: int) -> list[str] | None:
    """Return bounded string records, or reject the live payload value."""
    if not isinstance(raw, list) or len(cast("list[object]", raw)) > limit:
        return None
    values = cast("list[object]", raw)
    if any(not isinstance(line, str) for line in values):
        return None
    return cast("list[str]", values)


def _managed_log_content_bytes(lines: list[str], *, marker: bool) -> int:
    """Return the canonical encoded-content cost for one response group."""
    content_bytes = sum(_json_line_bytes(line) for line in lines)
    if marker:
        content_bytes += _json_line_bytes(MANAGED_LOG_TRUNCATION_MARKER)
    return content_bytes


def _managed_log_lines_fit_bounds(lines: list[str], *, marker: bool) -> bool:
    """Return whether records fit both per-record and per-source budgets."""
    return (
        all(len(line.encode("utf-8")) <= MAX_MANAGED_LOG_RECORD_BYTES for line in lines)
        and _managed_log_content_bytes(lines, marker=marker)
        <= MAX_MANAGED_LOG_SOURCE_BYTES
    )


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validated_managed_log_truncation(
    raw: object,
    *,
    lines: list[str],
) -> dict[str, int | bool] | None:
    """Validate structured truncation metadata against the returned content."""
    if not isinstance(raw, dict):
        return None
    details = cast("dict[str, object]", raw)
    required_ints = (
        "record_limit_bytes",
        "source_limit_bytes",
        "scanned_bytes",
        "returned_content_bytes",
        "omitted_bytes_at_least",
        "record_truncations",
        "omitted_response_records",
    )
    scanned = details.get("scanned_bytes")
    returned = details.get("returned_content_bytes")
    content_bytes = _managed_log_content_bytes(lines, marker=True)
    has_valid_details = (
        all(_is_nonnegative_int(details.get(key)) for key in required_ints)
        and details.get("record_limit_bytes") == MAX_MANAGED_LOG_RECORD_BYTES
        and details.get("source_limit_bytes") == MAX_MANAGED_LOG_SOURCE_BYTES
        and cast("int", scanned) <= MAX_MANAGED_LOG_SOURCE_BYTES
        and cast("int", returned) <= MAX_MANAGED_LOG_SOURCE_BYTES
        and isinstance(details.get("source_budget_exhausted"), bool)
        and isinstance(details.get("response_budget_exhausted"), bool)
        and _managed_log_lines_fit_bounds(lines, marker=True)
        and cast("int", returned) == content_bytes
    )
    if not has_valid_details:
        return None
    return cast("dict[str, int | bool]", details)


def _validated_managed_log_group(
    raw: object,
    *,
    expected_source: ManagedLogGroupSource,
    limit: int,
) -> ManagedLogGroup | None:
    """Validate one exact source group from the live response."""
    data = cast("dict[str, object]", raw) if isinstance(raw, dict) else None
    lines = (
        _validated_managed_log_lines(data.get("lines"), limit=limit) if data else None
    )
    if data is None or data.get("source") != expected_source or lines is None:
        return None
    group: ManagedLogGroup = {"source": expected_source, "lines": lines}
    metadata_present = any(
        data.get(key) is not None for key in ("truncated", "marker", "truncation")
    )
    if not metadata_present:
        return group if _managed_log_lines_fit_bounds(lines, marker=False) else None
    details = _validated_managed_log_truncation(
        data.get("truncation"),
        lines=lines,
    )
    has_valid_metadata = (
        data.get("truncated") is True
        and data.get("marker") == MANAGED_LOG_TRUNCATION_MARKER
        and details is not None
    )
    if not has_valid_metadata:
        return None
    assert details is not None
    group["truncated"] = True
    group["marker"] = MANAGED_LOG_TRUNCATION_MARKER
    group["truncation"] = details
    return group


def validate_managed_log_payload(
    payload: dict[str, object],
    *,
    source: ManagedLogSource,
    limit: int,
    filters: dict[str, str],
) -> list[ManagedLogGroup] | None:
    """Validate the exact live response contract before CLI rendering."""
    if payload.get("source") != source or payload.get("limit") != limit:
        return None
    if payload.get("filters") != filters:
        return None
    raw_groups = payload.get("groups")
    expected_sources: tuple[ManagedLogGroupSource, ...] = (
        _MANAGED_LOG_SOURCES if source == "all" else (source,)
    )
    if not isinstance(raw_groups, list) or len(cast("list[object]", raw_groups)) != len(
        expected_sources
    ):
        return None
    raw_group_values = cast("list[object]", raw_groups)
    groups: list[ManagedLogGroup] = []
    for expected_source, raw_group in zip(
        expected_sources, raw_group_values, strict=True
    ):
        group = _validated_managed_log_group(
            raw_group,
            expected_source=expected_source,
            limit=limit,
        )
        if group is None:
            return None
        groups.append(group)
    return groups


def configure_logging(
    level: str | int | None = None,
    debug: bool = False,
    quiet: bool = False,
) -> None:
    """Configure the root logger via core's RichHandler setup.

    Honors the configured ``log_level`` setting (``WARNING`` by default) when
    no explicit ``level``/``debug``/``quiet`` is provided, then delegates to
    :func:`vaultspec_core.logging_config.configure_logging`. An unrecognised
    level name degrades to the shipped default rather than raising, and says
    so, so a typo never makes the process quietly noisier than requested.

    Args:
        level: Explicit log level (e.g. ``logging.INFO`` or ``"DEBUG"``).
        debug: When ``True``, forces level to ``DEBUG`` and enables rich
            tracebacks with local variables.
        quiet: When ``True``, forces level to ``WARNING``.
    """
    if level is None and not debug and not quiet:
        from .config._settings import get_config, rag_default

        configured = str(get_config().log_level).upper()
        level = getattr(logging, configured, None)
        if not isinstance(level, int):
            # Degrade to the shipped default, not to something noisier. An
            # unreadable level name is a typo, and the surprising outcome is
            # a quiet service that suddenly logs more than it was asked to -
            # the operator sees new output and reads it as a change in
            # behaviour rather than as a rejected setting. Say what happened
            # and use the default the documentation promises.
            fallback = str(rag_default("log_level")).upper()
            level = getattr(logging, fallback, logging.WARNING)
            logging.getLogger(__name__).warning(
                "ignoring unrecognised log level %r; using %s", configured, fallback
            )

    _core_configure_logging(level=level, debug=debug, quiet=quiet)


def _canonical_daemon_log_path(path: str | os.PathLike[str]) -> Path:
    """Return one comparison spelling for a guarded daemon log path."""
    resolved = Path(path).expanduser().resolve(strict=False)
    return Path(os.path.normcase(os.path.normpath(str(resolved))))


def _contained_daemon_log_path(
    path: str | os.PathLike[str],
    *,
    operation: str,
) -> Path:
    """Validate a daemon-log path and return its canonical spelling."""
    enforce_pytest_singleton_containment(path, operation=operation)
    return _canonical_daemon_log_path(path)


def _close_detached_handler(
    handler: logging.Handler,
    failures: list[tuple[logging.Handler, Exception]],
) -> None:
    """Close one detached sink and contain a hostile close failure."""
    try:
        handler.close()
    except Exception as exc:
        failures.append((handler, exc))
        stream = getattr(handler, "stream", None)
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.close()


def _queue_injected_handlers(
    root: logging.Logger,
    *,
    daemon_handler: logging.Handler,
    pending: list[logging.Handler],
    closed_ids: set[int],
) -> None:
    """Detach and queue handlers injected by a close callback."""
    injected = tuple(root.handlers)
    root.handlers.clear()
    for candidate in injected:
        if candidate is daemon_handler or id(candidate) in closed_ids:
            continue
        if candidate not in pending:
            pending.append(candidate)


def _replace_root_handlers(
    root: logging.Logger,
    daemon_handler: logging.Handler,
) -> list[tuple[logging.Handler, Exception]]:
    """Make the daemon handler authoritative despite hostile close callbacks."""
    pending = [
        handler for handler in tuple(root.handlers) if handler is not daemon_handler
    ]
    root.handlers.clear()
    failures: list[tuple[logging.Handler, Exception]] = []
    closed_ids: set[int] = set()
    try:
        while pending:
            handler = pending.pop()
            if id(handler) in closed_ids:
                continue
            closed_ids.add(id(handler))
            _close_detached_handler(handler, failures)
            _queue_injected_handlers(
                root,
                daemon_handler=daemon_handler,
                pending=pending,
                closed_ids=closed_ids,
            )
    finally:
        root.handlers.clear()
        root.addHandler(daemon_handler)
    return failures


def _report_handler_close_failures(
    failures: list[tuple[logging.Handler, Exception]],
) -> None:
    for handler, exc in failures:
        logger.warning(
            "detached root handler %r failed to close: %s",
            handler,
            exc,
        )


_SERVICE_LOG_DRAIN_CHUNK_BYTES = 64 * 1024
_SERVICE_LOG_DRAIN_JOIN_SECONDS = 3.0
_active_daemon_capture: DaemonLogCapture | None = None


class DaemonLogCapture:
    """Lifecycle owner for the daemon's single-writer stdio log pipeline."""

    def __init__(
        self,
        log_path: Path,
        *,
        max_bytes: int,
        backup_count: int,
        handler: logging.StreamHandler[TextIO],
    ) -> None:
        self.log_path = log_path
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.handler = handler
        self._read_fd = -1
        self._drain_thread: threading.Thread | None = None
        self._close_lock = threading.Lock()
        self._closed = False
        self._persistence_error: BaseException | None = None

    @property
    def persistence_error(self) -> BaseException | None:
        """Return the first sink/drain failure without logging recursively."""
        return self._persistence_error

    @property
    def drain_alive(self) -> bool:
        """Return whether the sole file-writer thread is still running."""
        thread = self._drain_thread
        return thread is not None and thread.is_alive()

    def _record_drain_error(self, exc: BaseException) -> None:
        if self._persistence_error is None:
            self._persistence_error = exc

    def _discard_remaining_pipe(self, read_size: int) -> None:
        """Keep draining a failed sink's pipe so producers cannot deadlock."""
        while True:
            try:
                if not os.read(self._read_fd, read_size):
                    return
            except OSError:
                return

    def _drain(self) -> None:
        """Copy fixed-size raw pipe chunks into the sole rotating file sink."""
        sink = RawRotatingLogSink(
            self.log_path,
            max_bytes=self.max_bytes,
            backup_count=self.backup_count,
        )
        read_size = min(_SERVICE_LOG_DRAIN_CHUNK_BYTES, self.max_bytes)
        try:
            while True:
                try:
                    payload = os.read(self._read_fd, read_size)
                except OSError as exc:
                    self._record_drain_error(exc)
                    break
                if not payload:
                    break
                try:
                    sink.write(payload)
                except (OSError, ValueError) as exc:
                    self._record_drain_error(exc)
                    with contextlib.suppress(OSError, ValueError):
                        sink.close()
                    # Persistence is degraded, but the pipe must keep draining
                    # so noisy producers cannot deadlock the service.
                    self._discard_remaining_pipe(read_size)
                    break
        finally:
            with contextlib.suppress(OSError, ValueError):
                sink.close()
            read_fd = self._read_fd
            self._read_fd = -1
            if read_fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(read_fd)

    def start(self) -> None:
        """Create the pipe, start its drain, and atomically replace fds 1/2."""
        read_fd, write_fd = os.pipe()
        saved_stdout = os.dup(1)
        saved_stderr = os.dup(2)
        self._read_fd = read_fd
        thread = threading.Thread(
            target=self._drain,
            name="service-log-drain",
            daemon=True,
        )
        self._drain_thread = thread
        thread.start()
        try:
            os.dup2(write_fd, 1)
            os.dup2(write_fd, 2)
        except BaseException:
            with contextlib.suppress(OSError):
                os.dup2(saved_stdout, 1)
            with contextlib.suppress(OSError):
                os.dup2(saved_stderr, 2)
            raise
        finally:
            os.close(write_fd)
            os.close(saved_stdout)
            os.close(saved_stderr)

    @staticmethod
    def _flush_producers() -> None:
        """Flush Python producers before their pipe writers are detached."""
        root = logging.getLogger()
        for handler in tuple(root.handlers):
            with contextlib.suppress(Exception):
                handler.flush()
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                stream.flush()

    @staticmethod
    def _detach_stdio() -> None:
        """Close both pipe writers by rebinding stdout/stderr to null."""
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, 1)
            os.dup2(devnull_fd, 2)
        finally:
            os.close(devnull_fd)

    def close(self, *, timeout: float = _SERVICE_LOG_DRAIN_JOIN_SECONDS) -> bool:
        """Flush producers, detach writers, and join the sole sink owner."""
        global _active_daemon_capture

        with self._close_lock:
            if self._closed:
                return not self.drain_alive
            self._flush_producers()
            root = logging.getLogger()
            if self.handler in root.handlers:
                root.removeHandler(self.handler)
            with contextlib.suppress(Exception):
                self.handler.close()
            self._detach_stdio()
            thread = self._drain_thread
            if thread is not None:
                thread.join(timeout=max(0.0, timeout))
            completed = thread is None or not thread.is_alive()
            if completed:
                self._drain_thread = None
                self._closed = True
                with _daemon_logging_install_lock:
                    if _active_daemon_capture is self:
                        _active_daemon_capture = None
            return completed


#: Routes the operator surfaces refresh on a timer. A successful GET reflected
#: back from one of these tells an operator nothing the caller did not already
#: have on screen, and at observed refresh rates it crowds every other record
#: out of the bounded log. Mutations, failures, and every other route stay.
POLLED_ROUTES: tuple[str, ...] = (
    "/jobs",
    "/logs",
    "/health",
    "/metrics",
    "/projects",
    "/watcher",
    "/storage/survey",
)

#: Positional arguments Uvicorn's access logger carries:
#: ``(client_addr, method, path_with_query, http_version, status)``.
_ACCESS_RECORD_ARITY = 5
_ACCESS_METHOD_INDEX = 1
_ACCESS_PATH_INDEX = 2
_ACCESS_STATUS_INDEX = 4
_FIRST_ERROR_STATUS = 400


def _is_polled_route(path: str) -> bool:
    base = path.partition("?")[0]
    return any(base == route or base.startswith(route + "/") for route in POLLED_ROUTES)


class PolledAccessFilter(logging.Filter):
    """Drop successful timer-poll reads from the access stream.

    Reads the access record's positional arguments rather than its rendered
    text: the formatted line is a presentation detail, and matching against it
    would re-derive the request from a string the emitter already had typed.
    A record whose shape is not the documented access tuple is passed through
    untouched, so an unrecognised producer is never silently discarded.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) != _ACCESS_RECORD_ARITY:
            return True
        method = args[_ACCESS_METHOD_INDEX]
        path = args[_ACCESS_PATH_INDEX]
        status = args[_ACCESS_STATUS_INDEX]
        if not isinstance(method, str) or not isinstance(path, str):
            return True
        if not isinstance(status, int) or isinstance(status, bool):
            return True
        if method != "GET" or status >= _FIRST_ERROR_STATUS:
            return True
        return not _is_polled_route(path)


#: Third-party loggers the daemon quiets, with the level each is held at.
#: Every entry states why in one clause; an entry without a reason is a
#: silenced symptom rather than a decision, and does not belong here.
_THIRD_PARTY_LOG_LEVELS: tuple[tuple[str, int], ...] = (
    # Routine Qdrant HTTP requests are already represented by the service's
    # structured operation summaries. Keeping client wire chatter at INFO
    # obscures those summaries and creates disproportionate managed-log I/O.
    ("httpx", logging.WARNING),
    ("httpcore", logging.WARNING),
    # One record per filesystem event, emitted for every change the watcher
    # already reports as a coalesced job outcome.
    ("watchfiles.main", logging.WARNING),
    # Model load and encode chatter, including progress rendering that keys
    # off its own effective level rather than any explicit request.
    ("sentence_transformers", logging.WARNING),
)


def _apply_third_party_log_levels() -> None:
    for name, level in _THIRD_PARTY_LOG_LEVELS:
        logging.getLogger(name).setLevel(level)


def _validate_daemon_capture_settings(max_bytes: int, backup_count: int) -> None:
    """Reject settings that cannot preserve bounded managed-log retention."""
    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
        or max_bytes <= 0
    ):
        raise ValueError("max_bytes must be a positive integer")
    if (
        isinstance(backup_count, bool)
        or not isinstance(backup_count, int)  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
        or backup_count < 0
    ):
        raise ValueError("backup_count must be a non-negative integer")


def install_daemon_log_capture(
    log_path: Path,
    *,
    max_bytes: int,
    backup_count: int,
) -> DaemonLogCapture:
    """Install the daemon's one pipe and one exclusive rotating-log writer.

    Root logging, Uvicorn stream handlers, ``print``, direct ``os.write`` calls,
    and native stdout/stderr all enter the same pipe. Only the bounded binary
    drain touches ``service.log``, so every byte participates in rollover.

    Args:
        log_path: Absolute path to the active ``service.log`` file.
            The parent directory is created if missing.
        max_bytes: Positive rollover threshold in bytes.
        backup_count: Number of rotated backups to keep.  ``0`` rolls
            and truncates without keeping history.

    Returns:
        An explicit lifecycle handle which must be closed after all producers.
    """
    global _active_daemon_capture

    _validate_daemon_capture_settings(max_bytes, backup_count)
    requested_log_path = _contained_daemon_log_path(
        log_path,
        operation="install daemon log capture",
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    with _daemon_logging_install_lock:
        if _active_daemon_capture is not None:
            raise RuntimeError("daemon log capture is already active")
        root = logging.getLogger()
        requested_log_path.parent.mkdir(parents=True, exist_ok=True)
        daemon_handler = logging.StreamHandler(sys.stderr)
        daemon_handler.setFormatter(formatter)
        capture = DaemonLogCapture(
            requested_log_path,
            max_bytes=max_bytes,
            backup_count=backup_count,
            handler=daemon_handler,
        )
        capture.start()
        try:
            close_failures = _replace_root_handlers(root, daemon_handler)
        except BaseException:
            capture.close()
            raise
        _active_daemon_capture = capture

        _apply_third_party_log_levels()
        _install_polled_access_filter()

        _report_handler_close_failures(close_failures)
        return capture


def _install_polled_access_filter() -> None:
    """Make the access stream carry signal only, exactly once.

    Uvicorn rebuilds its loggers on every start, so the filter is installed
    idempotently: a second daemon start in one interpreter must not stack a
    second copy that re-tests every record.
    """
    access_logger = logging.getLogger("uvicorn.access")
    if any(
        isinstance(existing, PolledAccessFilter) for existing in access_logger.filters
    ):
        return
    access_logger.addFilter(PolledAccessFilter())


type EventExcInfo = (
    bool
    | BaseException
    | tuple[type[BaseException], BaseException, TracebackType | None]
    | tuple[None, None, None]
    | None
)
