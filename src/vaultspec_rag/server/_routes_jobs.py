"""Job-snapshot filtering and shaping helpers for the ``/jobs`` route.

Pure, GPU-free transforms over the :mod:`._jobs` registry snapshot: query
filter normalisation, per-record liveness enrichment, predicate matching,
aggregate summary, and the running-first ordering. The ``jobs_route`` handler
in :mod:`._routes` composes these; they are factored out here to keep the route
module bounded. Bounded/filterable operator-view semantics
(``operator-views-are-bounded``) live in the handler, which applies the clamp
and predicate this module provides.
"""

from __future__ import annotations

from typing import cast

from .._job_errors import STALL_THRESHOLD_SECONDS
from . import _jobs

__all__ = [
    "_clamp_limit",
    "_job_matches",
    "_job_summary",
    "_job_with_liveness",
    "_normalise_filter_value",
    "_normalise_job_source_filter",
    "_parse_since_seconds",
    "_prioritise_running_jobs",
]


def _clamp_limit(raw: str | None) -> int | None:
    """Parse the ``?limit=`` query parameter; ``None`` when absent/invalid.

    Returns ``None`` (no cap) when the parameter is missing or
    non-integer, so the full bounded snapshot is returned.
    """
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_since_seconds(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _normalise_filter_value(raw: str | None) -> str | None:
    """Return a stripped lower-case query filter or ``None`` when absent."""
    if raw is None:
        return None
    value = raw.strip().lower()
    return value or None


def _normalise_job_source_filter(raw: str | None) -> str | None:
    value = _normalise_filter_value(raw)
    if value == "codebase":
        return "code"
    return value


def _job_progress_text(record: dict[str, object]) -> str:
    progress = record.get("progress")
    if not isinstance(progress, dict):
        return ""
    progress_map = cast("dict[str, object]", progress)
    step = progress_map.get("step")
    completed = progress_map.get("completed")
    total = progress_map.get("total")
    parts = [str(step)] if step else []
    if total is not None:
        parts.append(f"{completed}/{total}")
    elif completed is not None:
        parts.append(str(completed))
    return " ".join(parts)


def _job_updated_timestamp(record: dict[str, object]) -> float | None:
    progress = record.get("progress")
    if isinstance(progress, dict):
        last_updated = cast("dict[str, object]", progress).get("last_updated")
        if isinstance(last_updated, int | float):
            return float(last_updated)
    timestamp = record.get("finished_at") or record.get("started_at")
    if isinstance(timestamp, int | float):
        return float(timestamp)
    return None


def _job_runtime_seconds(record: dict[str, object], now: float) -> float | None:
    started_at = record.get("started_at")
    if not isinstance(started_at, int | float):
        return None
    finished_at = record.get("finished_at")
    end = float(finished_at) if isinstance(finished_at, int | float) else now
    return max(0.0, end - float(started_at))


def _job_last_progress_age_seconds(
    record: dict[str, object],
    now: float,
) -> float | None:
    progress = record.get("progress")
    if not isinstance(progress, dict):
        return None
    last_updated = cast("dict[str, object]", progress).get("last_updated")
    if not isinstance(last_updated, int | float):
        return None
    return max(0.0, now - float(last_updated))


def _job_is_waiting(record: dict[str, object]) -> bool:
    progress = record.get("progress")
    return (
        isinstance(progress, dict)
        and cast("dict[str, object]", progress).get("step") == "queued"
    )


def _job_stalled(record: dict[str, object], now: float) -> bool:
    """Service-domain stall signal: running, working, no progress.

    A running, non-waiting job whose last progress update is older than
    :data:`STALL_THRESHOLD_SECONDS` is flagged so every adapter (CLI,
    MCP, HTTP consumers) sees the same "something is wrong" signal the
    human jobs feed used to compute locally.
    """
    if record.get("phase") != "running" or _job_is_waiting(record):
        return False
    age = _job_last_progress_age_seconds(record, now)
    return age is not None and age >= STALL_THRESHOLD_SECONDS


def _job_with_liveness(
    record: dict[str, object],
    *,
    now: float,
) -> dict[str, object]:
    enriched = dict(record)
    enriched["runtime_seconds"] = _job_runtime_seconds(record, now)
    enriched["last_progress_age_seconds"] = _job_last_progress_age_seconds(record, now)
    enriched["stalled"] = _job_stalled(record, now)
    resources = record.get("resources")
    if isinstance(resources, dict):
        resources_map = cast("dict[str, object]", resources)
        enriched_resources: dict[str, object] = {
            str(key): dict(cast("dict[str, object]", value))
            if isinstance(value, dict)
            else value
            for key, value in resources_map.items()
        }
        if record.get("phase") == "running":
            enriched_resources["current"] = _jobs.resource_snapshot()
        enriched["resources"] = enriched_resources
    return enriched


def _job_id_matches(record: dict[str, object], job_id: str | None) -> bool:
    if job_id is None:
        return True
    return str(record.get("id", "")).startswith(job_id)


def _job_matches(
    record: dict[str, object],
    *,
    phase: str | None,
    source: str | None,
    trigger: str | None,
    query: str | None,
    failed: bool,
    job_id: str | None,
    since_seconds: float | None,
    now: float,
) -> bool:
    if not _job_id_matches(record, job_id):
        return False
    if failed and str(record.get("phase", "")).lower() not in ("error", "failed"):
        return False
    if since_seconds is not None:
        timestamp = _job_updated_timestamp(record)
        if timestamp is None or timestamp < now - since_seconds:
            return False
    if phase is not None and str(record.get("phase", "")).lower() != phase:
        return False
    if source is not None and str(record.get("source", "")).lower() != source:
        return False
    if trigger is not None and str(record.get("trigger", "")).lower() != trigger:
        return False
    if query is None:
        return True
    haystack = " ".join(
        [
            str(record.get("id", "")),
            str(record.get("source", "")),
            str(record.get("trigger", "")),
            str(record.get("phase", "")),
            str(record.get("result", "")),
            _job_progress_text(record),
            *_job_nested_values(record.get("initiator")),
            *_job_nested_values(record.get("runtime")),
        ]
    ).lower()
    return query in haystack


def _job_nested_values(raw: object) -> list[str]:
    if not isinstance(raw, dict):
        return []
    raw_map = cast("dict[str, object]", raw)
    return [str(value) for value in raw_map.values() if value is not None]


def _job_summary(
    records: list[dict[str, object]],
    *,
    now: float,
) -> dict[str, object]:
    phases: dict[str, int] = {}
    sources: dict[str, int] = {}
    triggers: dict[str, int] = {}
    initiators: dict[str, int] = {}
    active_initiators: dict[str, int] = {}
    users: dict[str, int] = {}
    stalled = 0
    error_kinds: dict[str, int] = {}
    for record in records:
        if _job_stalled(record, now):
            stalled += 1
        kind = record.get("error_kind")
        if isinstance(kind, str) and kind:
            error_kinds[kind] = error_kinds.get(kind, 0) + 1
        phase = str(record.get("phase", "unknown"))
        source = str(record.get("source", "unknown"))
        trigger = str(record.get("trigger", "unknown"))
        phases[phase] = phases.get(phase, 0) + 1
        sources[source] = sources.get(source, 0) + 1
        triggers[trigger] = triggers.get(trigger, 0) + 1
        initiator = record.get("initiator")
        if isinstance(initiator, dict):
            kind = str(cast("dict[str, object]", initiator).get("kind", "unknown"))
            initiators[kind] = initiators.get(kind, 0) + 1
            if phase == "running":
                active_initiators[kind] = active_initiators.get(kind, 0) + 1
        runtime = record.get("runtime")
        if isinstance(runtime, dict):
            user = str(cast("dict[str, object]", runtime).get("user", "unknown"))
            users[user] = users.get(user, 0) + 1
    return {
        "phases": phases,
        "sources": sources,
        "triggers": triggers,
        "initiators": initiators,
        "active_initiators": active_initiators,
        "users": users,
        "running": phases.get("running", 0),
        "stalled": stalled,
        "error_kinds": error_kinds,
    }


def _prioritise_running_jobs(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep running and failed work visible before completed history."""

    def priority(record: dict[str, object]) -> int:
        phase = record.get("phase")
        if phase == "running":
            return 0
        if phase in ("error", "failed"):
            return 1
        return 2

    return sorted(
        records,
        key=priority,
    )
