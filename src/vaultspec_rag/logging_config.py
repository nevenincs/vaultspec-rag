"""Logging configuration for vaultspec-rag.

Thin wrapper over :mod:`vaultspec_core.logging_config`. RAG previously held a
near-verbatim copy of core's implementation; it now delegates so the two
packages cannot silently diverge. The only RAG-specific behavior preserved
here is the env-var override (``VAULTSPEC_RAG_LOG_LEVEL``) and RAG's
``WARNING`` default when no explicit level is supplied.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict, cast, override

from vaultspec_core.logging_config import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    configure_logging as _core_configure_logging,
)
from vaultspec_core.logging_config import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    get_console,
    reset_logging,
)

__all__ = [
    "DEFAULT_MANAGED_LOG_LINES",
    "MANAGED_LOG_TRUNCATION_MARKER",
    "MAX_MANAGED_LOG_LINES",
    "MAX_MANAGED_LOG_RECORD_BYTES",
    "MAX_MANAGED_LOG_SOURCE_BYTES",
    "DaemonRotatingFileHandler",
    "InvalidManagedLogSourceError",
    "ManagedLogGroup",
    "ManagedLogSource",
    "clamp_managed_log_lines",
    "configure_logging",
    "get_console",
    "install_daemon_log_rotation",
    "log_event",
    "managed_log_filters",
    "query_managed_logs",
    "read_managed_logs",
    "render_managed_log_groups",
    "reset_logging",
    "validate_managed_log_payload",
]

logger = logging.getLogger(__name__)
_daemon_logging_install_lock = threading.RLock()

if TYPE_CHECKING:
    from collections.abc import Mapping
    from io import TextIOWrapper

_EVENT_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_FIELD_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BARE_VALUE_RE = re.compile(r"^[A-Za-z0-9_./:@\\-]+$")

type ManagedLogSource = Literal["service", "qdrant", "all"]
type ManagedLogGroupSource = Literal["service", "qdrant"]


class ManagedLogGroup(TypedDict):
    """One source's raw records, ordered only within that source."""

    source: ManagedLogGroupSource
    lines: list[str]
    truncated: NotRequired[bool]
    marker: NotRequired[str]
    truncation: NotRequired[dict[str, int | bool]]


class InvalidManagedLogSourceError(ValueError):
    """Raised when a managed-log source selector is not supported."""


_MANAGED_LOG_SOURCES: tuple[ManagedLogGroupSource, ...] = ("service", "qdrant")
_QDRANT_LOG_NAME = "qdrant.log"
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
    *,
    severity: int = logging.INFO,
    exc_info: Any = None,
    fields: Mapping[str, object] | None = None,
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
    from .config import get_config

    cfg = get_config()
    return Path(cfg.status_dir).expanduser()


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
        return _QDRANT_LOG_NAME
    from .config import get_config

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


def _read_managed_source(
    status_dir: Path,
    source: ManagedLogGroupSource,
    lines: int,
) -> ManagedLogGroup:
    remaining = max(0, lines)
    newest_chunks: list[list[str]] = []
    remaining_bytes = MAX_MANAGED_LOG_SOURCE_BYTES
    scanned_bytes = 0
    omitted_bytes = 0
    record_truncations = 0
    source_budget_exhausted = False
    paths = list(reversed(_rotated_log_paths(status_dir, _managed_log_name(source))))
    # Paths are chronological; read them newest-first so older generations are
    # never touched after the requested per-source record bound is satisfied.
    for index, path in enumerate(paths):
        if remaining <= 0:
            break
        if remaining_bytes <= 0:
            older_bytes = sum(_path_size(candidate) for candidate in paths[index:])
            if older_bytes:
                source_budget_exhausted = True
                omitted_bytes += older_bytes
            break
        window = _tail_file_window(path, remaining, remaining_bytes)
        chunk = window["lines"]
        scanned_bytes += window["scanned_bytes"]
        remaining_bytes -= window["scanned_bytes"]
        omitted_bytes += window["omitted_bytes"]
        record_truncations += window["record_truncations"]
        if window["source_budget_exhausted"]:
            source_budget_exhausted = True
            omitted_bytes += sum(
                _path_size(candidate) for candidate in paths[index + 1 :]
            )
            if chunk:
                newest_chunks.append(chunk)
                remaining -= len(chunk)
            break
        if not chunk:
            continue
        newest_chunks.append(chunk)
        remaining -= len(chunk)

    source_lines = [line for chunk in reversed(newest_chunks) for line in chunk]
    group: ManagedLogGroup = {"source": source, "lines": source_lines}
    if source_budget_exhausted or record_truncations:
        group["truncated"] = True
        group["marker"] = MANAGED_LOG_TRUNCATION_MARKER
        group["truncation"] = {
            "record_limit_bytes": MAX_MANAGED_LOG_RECORD_BYTES,
            "source_limit_bytes": MAX_MANAGED_LOG_SOURCE_BYTES,
            "scanned_bytes": scanned_bytes,
            "returned_content_bytes": 0,
            "omitted_bytes_at_least": omitted_bytes,
            "record_truncations": record_truncations,
            "source_budget_exhausted": source_budget_exhausted,
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
) -> dict[str, object]:
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
    if any(not _is_nonnegative_int(details.get(key)) for key in required_ints):
        return None
    if details.get("record_limit_bytes") != MAX_MANAGED_LOG_RECORD_BYTES:
        return None
    if details.get("source_limit_bytes") != MAX_MANAGED_LOG_SOURCE_BYTES:
        return None
    scanned = cast("int", details["scanned_bytes"])
    returned = cast("int", details["returned_content_bytes"])
    if (
        scanned > MAX_MANAGED_LOG_SOURCE_BYTES
        or returned > MAX_MANAGED_LOG_SOURCE_BYTES
    ):
        return None
    if not isinstance(details.get("source_budget_exhausted"), bool):
        return None
    if not isinstance(details.get("response_budget_exhausted"), bool):
        return None
    content_bytes = _managed_log_content_bytes(lines, marker=True)
    if not _managed_log_lines_fit_bounds(lines, marker=True):
        return None
    if returned != content_bytes:
        return None
    return cast("dict[str, int | bool]", details)


def _validated_managed_log_group(
    raw: object,
    *,
    expected_source: ManagedLogGroupSource,
    limit: int,
) -> ManagedLogGroup | None:
    """Validate one exact source group from the live response."""
    if not isinstance(raw, dict):
        return None
    data = cast("dict[str, object]", raw)
    if data.get("source") != expected_source:
        return None
    lines = _validated_managed_log_lines(data.get("lines"), limit=limit)
    if lines is None:
        return None
    group: ManagedLogGroup = {"source": expected_source, "lines": lines}
    metadata_present = any(
        data.get(key) is not None for key in ("truncated", "marker", "truncation")
    )
    if not metadata_present:
        return group if _managed_log_lines_fit_bounds(lines, marker=False) else None
    if data.get("truncated") is not True:
        return None
    if data.get("marker") != MANAGED_LOG_TRUNCATION_MARKER:
        return None
    details = _validated_managed_log_truncation(
        data.get("truncation"),
        lines=lines,
    )
    if details is None:
        return None
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

    Honors the RAG-specific ``VAULTSPEC_RAG_LOG_LEVEL`` env var with a
    ``WARNING`` default when no explicit ``level``/``debug``/``quiet`` is
    provided, then delegates to :func:`vaultspec_core.logging_config.configure_logging`.

    Args:
        level: Explicit log level (e.g. ``logging.INFO`` or ``"DEBUG"``).
        debug: When ``True``, forces level to ``DEBUG`` and enables rich
            tracebacks with local variables.
        quiet: When ``True``, forces level to ``WARNING``.
    """
    if level is None and not debug and not quiet:
        from .config import EnvVar

        env_level = os.environ.get(EnvVar.LOG_LEVEL, "WARNING").upper()
        level = getattr(logging, env_level, logging.INFO)

    _core_configure_logging(level=level, debug=debug, quiet=quiet)


def _enforce_daemon_log_containment(
    path: str | os.PathLike[str],
    *,
    operation: str,
) -> None:
    """Fail before a daemon-log filesystem effect escapes pytest isolation."""
    from ._test_isolation import enforce_pytest_singleton_containment

    enforce_pytest_singleton_containment(path, operation=operation)


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
    _enforce_daemon_log_containment(path, operation=operation)
    return _canonical_daemon_log_path(path)


def _validate_daemon_rotation_settings(max_bytes: int, backup_count: int) -> None:
    """Reject rotation settings that the handler cannot apply consistently."""
    if (
        isinstance(max_bytes, bool)
        or not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            max_bytes, int
        )
        or max_bytes < 0
    ):
        raise ValueError("max_bytes must be a non-negative integer")
    if (
        isinstance(backup_count, bool)
        or not isinstance(backup_count, int)  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
        or backup_count < 0
    ):
        raise ValueError("backup_count must be a non-negative integer")


class DaemonRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that re-``dup2``s stdout/stderr after rollover.

    The daemon is spawned with its ``stdout``/``stderr`` already ``dup2``'d
    onto the open ``service.log`` FD by the parent CLI.  On first rotation,
    :class:`RotatingFileHandler` renames the log file and opens a fresh
    stream - but fds 1/2 still reference the *original* kernel inode,
    which ``os.rename`` has just moved to ``service.log.1``.  Without a
    re-``dup2``, stdout/stderr get stuck writing to the rotated file
    forever and the backup-count accounting silently goes wrong.

    This subclass overrides :meth:`doRollover` to ``os.dup2`` the
    freshly-opened stream's FD onto both 1 and 2 immediately after
    :meth:`RotatingFileHandler.doRollover` swaps the stream.  Python's
    :class:`logging.Handler` acquires a reentrant lock
    (``threading.RLock``) around every :meth:`emit` call, so the
    acquire/release inside :meth:`doRollover` is a defensive no-op in
    the common path and safe against reentrant calls.
    """

    @override
    def __init__(
        self,
        filename: str | os.PathLike[str],
        mode: str = "a",
        maxBytes: int = 0,
        backupCount: int = 0,
        encoding: str | None = None,
        delay: bool = False,
        errors: str | None = None,
    ) -> None:
        """Guard the active filename before ``FileHandler`` can open it."""
        _enforce_daemon_log_containment(
            filename,
            operation="open daemon log",
        )
        super().__init__(
            filename,
            mode=mode,
            maxBytes=maxBytes,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
            errors=errors,
        )

    def _contained_base_filename(self, *, operation: str) -> Path:
        """Validate and canonicalize the handler's current active filename."""
        return _contained_daemon_log_path(
            self.baseFilename,
            operation=operation,
        )

    @override
    def _open(self) -> TextIOWrapper:
        """Guard delayed and rollover reopens at the actual effect boundary."""
        self._contained_base_filename(operation="open daemon log")
        return super()._open()

    @override
    def rotation_filename(self, default_name: str) -> str:
        """Require custom-namer output to remain in pytest containment."""
        rotated = super().rotation_filename(default_name)
        _enforce_daemon_log_containment(
            rotated,
            operation="resolve rotated daemon log",
        )
        return rotated

    @override
    def rotate(self, source: str, dest: str) -> None:
        """Guard both sides of the rollover filesystem mutation."""
        _enforce_daemon_log_containment(
            source,
            operation="rotate daemon log source",
        )
        _enforce_daemon_log_containment(
            dest,
            operation="rotate daemon log destination",
        )
        super().rotate(source, dest)

    @override
    def shouldRollover(self, record: logging.LogRecord) -> int:
        """Decide rollover from on-disk file size, not the handler's own writes.

        :class:`RotatingFileHandler.shouldRollover` measures
        ``self.stream.tell()`` which only reflects bytes the handler itself
        wrote. In the daemon, raw ``print()`` calls and third-party writes to
        redirected stdout/stderr bypass the handler's stream and grow the file
        directly. Without this override, the handler under-counts the file size
        and never triggers rollover after the on-disk log passes ``maxBytes``.
        """
        if self.stream is None:
            self.stream = self._open()
        if self.maxBytes > 0:
            size = self._safe_stream_size()
            msg = f"{self.format(record)}\n"
            if size + len(msg) >= self.maxBytes:
                return 1
        return 0

    def _safe_stream_size(self) -> int:
        """Best-effort current size of the active log file.

        ``shouldRollover`` is called from inside ``emit`` and must never
        propagate an exception, otherwise the handler's error path
        triggers and the rollover never fires.  Both ``fileno()`` and
        ``tell()`` raise ``ValueError`` on a closed stream, and ``fstat``
        can fail with ``OSError`` on some platforms - fall back through
        all three to ``0`` rather than letting any of them escape.
        """
        if self.stream is None:
            return 0
        try:
            return os.fstat(self.stream.fileno()).st_size
        except (OSError, ValueError) as exc:
            logger.debug("log fstat fell through to tell(): %s", exc)
        try:
            return self.stream.tell()
        except (OSError, ValueError) as exc:
            logger.debug("log tell() fell through to 0: %s", exc)
            return 0

    @override
    def doRollover(self) -> None:
        """Rotate the log file, then re-``dup2`` fds 1 and 2 onto the stream.

        On Windows, any open handle to the active log file blocks the
        rename inside :meth:`RotatingFileHandler.doRollover`.  Because
        the daemon has ``dup2``'d fds 1 and 2 onto the log file during
        :func:`install_daemon_log_rotation`, those fds would otherwise
        pin the file open.  The fix is to redirect fds 1 and 2 to
        ``os.devnull`` for the duration of the rename, then re-``dup2``
        them onto the freshly-opened stream once the parent class has
        swapped files.

        If anything in the rollover sequence raises (e.g. transient
        Windows file-lock conflict, or ``self.stream is None`` because
        the handler is in ``delay=True`` mode), fds 1 and 2 are
        restored to *whatever ``self.baseFilename`` currently points
        at* by opening it fresh and ``dup2``-ing the new fd onto 1 and
        2.  This prevents the silent-log-loss failure mode where a
        partial rollover leaves stdout/stderr permanently pinned to
        ``/dev/null``.  Note that we do **not** save the original fds
        1 / 2 before redirecting to ``/dev/null`` because those fds
        point at the active log file and would themselves block the
        Windows rename inside ``super().doRollover()``.
        """
        self._contained_base_filename(operation="rotate daemon log")
        # logging.Handler.acquire() returns a reentrant RLock so it is
        # safe even when emit() already holds it on our behalf.
        self.acquire()
        try:
            devnull_fd = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(devnull_fd, 1)
                os.dup2(devnull_fd, 2)
            finally:
                os.close(devnull_fd)
            try:
                super().doRollover()
            except PermissionError:
                if os.name != "nt":
                    self._rebind_fds_to_basefile()
                    raise
                self._copytruncate_rollover()
            except Exception:
                self._rebind_fds_to_basefile()
                raise
            # ``self.stream is None`` is the expected state when
            # ``delay=True`` is configured: the parent class defers the
            # next ``_open()`` until the following emit().  Treat it as
            # a valid no-op and rebind fds 1/2 to the (newly empty)
            # ``baseFilename`` so subsequent stdout/stderr writes still
            # land in the active log file rather than ``/dev/null``.
            if self.stream is None:
                self._rebind_fds_to_basefile()
                return
            fd = self.stream.fileno()
            os.dup2(fd, 1)
            os.dup2(fd, 2)
        finally:
            self.release()

    def _copytruncate_rollover(self) -> None:
        """Rotate by copying and truncating when Windows blocks rename.

        Some Windows handles inherited by the detached service can keep
        the active log path non-renamable even after fds 1 and 2 are
        redirected.  In that case, preserve the normal bounded-backup
        contract by shifting existing backups, copying the active file
        into ``.1``, and truncating the active file in place.
        """
        self._contained_base_filename(operation="copy-truncate daemon log")
        if self.stream is not None:
            self.stream.close()
            self.stream = None

        if self.backupCount > 0:
            self._shift_backups()
            self._copy_base_to_first_backup()

        with open(self.baseFilename, "w", encoding=self.encoding):
            pass

        if not self.delay:
            self.stream = self._open()

    def _shift_backups(self) -> None:
        self._contained_base_filename(operation="shift daemon log backups")
        for i in range(self.backupCount - 1, 0, -1):
            src = self.rotation_filename(f"{self.baseFilename}.{i}")
            dst = self.rotation_filename(f"{self.baseFilename}.{i + 1}")
            if os.path.exists(src):
                if os.path.exists(dst):
                    os.remove(dst)
                os.replace(src, dst)

    def _copy_base_to_first_backup(self) -> None:
        self._contained_base_filename(operation="copy daemon log backup")
        first_backup = self.rotation_filename(f"{self.baseFilename}.1")
        if os.path.exists(first_backup):
            os.remove(first_backup)
        if os.path.exists(self.baseFilename):
            shutil.copyfile(self.baseFilename, first_backup)

    def _rebind_fds_to_basefile(self) -> None:
        """Best-effort: re-``dup2`` fds 1 and 2 onto ``self.baseFilename``.

        Used by :meth:`doRollover`'s recovery path and the ``delay=True``
        no-op path.  Failures are swallowed because the caller is
        already mid-recovery - the original error (if any) still
        propagates with its traceback intact.
        """
        self._contained_base_filename(operation="rebind daemon log file descriptors")
        try:
            recovery_fd = os.open(
                self.baseFilename,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                0o644,
            )
        except OSError as exc:
            logger.debug(
                "fd rebind: log open(%s) failed: %s",
                self.baseFilename,
                exc,
            )
            return
        try:
            with contextlib.suppress(OSError):
                os.dup2(recovery_fd, 1)
                os.dup2(recovery_fd, 2)
        finally:
            with contextlib.suppress(OSError):
                os.close(recovery_fd)


def _matching_daemon_handler(
    root: logging.Logger,
    *,
    requested_log_path: Path,
    max_bytes: int,
    backup_count: int,
) -> DaemonRotatingFileHandler | None:
    """Return the one open handler that exactly matches an install request."""
    for handler in tuple(root.handlers):
        if not isinstance(handler, DaemonRotatingFileHandler):
            continue
        stream = handler.stream
        if stream is None or stream.closed:
            continue
        if _canonical_daemon_log_path(handler.baseFilename) != requested_log_path:
            continue
        if handler.maxBytes == max_bytes and handler.backupCount == backup_count:
            return handler
    return None


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
    daemon_handler: DaemonRotatingFileHandler,
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
    daemon_handler: DaemonRotatingFileHandler,
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


def install_daemon_log_rotation(
    log_path: Path,
    *,
    max_bytes: int,
    backup_count: int,
) -> DaemonRotatingFileHandler:
    """Install the daemon's single canonical root logging sink.

    Idempotent when the attached handler is open and its path and rotation
    settings exactly match this request. A closed or stale handler is replaced.
    Every other root handler is atomically detached before close callbacks run;
    the final ``finally`` postcondition restores exactly one canonical sink even
    if a hostile or failing ``close()`` mutates ``root.handlers``. Stdout and
    stderr are then rebound to the canonical handler's live stream.

    Args:
        log_path: Absolute path to the active ``service.log`` file.
            The parent directory is created if missing.
        max_bytes: Rollover threshold in bytes.  ``0`` disables
            rotation (handler still installs but never rolls).
        backup_count: Number of rotated backups to keep.  ``0`` rolls
            and truncates without keeping history.

    Returns:
        The installed (or pre-existing)
        :class:`DaemonRotatingFileHandler` instance.
    """
    _validate_daemon_rotation_settings(max_bytes, backup_count)
    requested_log_path = _contained_daemon_log_path(
        log_path,
        operation="install daemon log rotation",
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    with _daemon_logging_install_lock:
        root = logging.getLogger()
        daemon_handler = _matching_daemon_handler(
            root,
            requested_log_path=requested_log_path,
            max_bytes=max_bytes,
            backup_count=backup_count,
        )

        if daemon_handler is None:
            requested_log_path.parent.mkdir(parents=True, exist_ok=True)
            daemon_handler = DaemonRotatingFileHandler(
                str(requested_log_path),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
        daemon_handler.setFormatter(formatter)

        close_failures = _replace_root_handlers(root, daemon_handler)

        # Routine Qdrant HTTP requests are already represented by the service's
        # structured operation summaries. Keeping client wire chatter at INFO
        # obscures those summaries and creates disproportionate managed-log I/O.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

        stream = daemon_handler.stream
        if stream is None or stream.closed:
            # A handler retained above must be open; a newly constructed handler
            # is non-delayed. Treat any contrary state as a failed install.
            raise RuntimeError("canonical daemon log handler has no live stream")
        fd = stream.fileno()
        os.dup2(fd, 1)
        os.dup2(fd, 2)

        _report_handler_close_failures(close_failures)

        return daemon_handler
