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

from .._job_errors import STALL_THRESHOLD_SECONDS, remediation
from ..job_models import JobState
from . import _jobs

__all__ = [
    "_clamp_limit",
    "_job_matches",
    "_job_number",
    "_job_resilience",
    "_job_stalled",
    "_job_summary",
    "_job_with_liveness",
    "_normalise_filter_value",
    "_normalise_job_source_filter",
    "_parse_since_seconds",
    "_prioritise_running_jobs",
    "job_state",
    "job_updated_timestamp",
]

_CANONICAL_STATES = frozenset(state.value for state in JobState)
_TRANSITIONAL_STATES = frozenset({JobState.PAUSING.value, JobState.CANCELLING.value})
_TERMINAL_STATES = frozenset(state.value for state in JobState if state.is_terminal)
_LEGACY_TERMINAL_PHASES = {
    "done": JobState.SUCCEEDED.value,
    "error": JobState.FAILED.value,
    "failed": JobState.FAILED.value,
    "cancelled": JobState.CANCELLED.value,
    "interrupted": JobState.INTERRUPTED.value,
    "skipped": JobState.SUCCEEDED.value,
    "superseded": JobState.SUCCEEDED.value,
}


def _job_mapping(record: dict[str, object], key: str) -> dict[str, object]:
    value = record.get(key)
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def _job_number(record: dict[str, object], key: str) -> float | None:
    """Read *key* as a float, or ``None`` when absent or non-numeric.

    Job records arrive as untyped mappings decoded from persisted JSON, so
    every timestamp read has to tolerate a missing or malformed field. This is
    the single reader for that; combine it with :func:`_job_mapping` to reach a
    timestamp nested inside a sub-mapping.
    """
    value = record.get(key)
    return float(value) if isinstance(value, int | float) else None


def _age_seconds(timestamp: float | None, now: float) -> float | None:
    """Return the elapsed time since *timestamp*, clamped at zero.

    Clock adjustments and out-of-order stamps can put a timestamp ahead of
    *now*; an age is never negative, so it floors rather than reporting the
    future. ``None`` propagates for an unreadable timestamp.
    """
    return None if timestamp is None else max(0.0, now - timestamp)


def job_state(record: dict[str, object]) -> str:
    raw_state = record.get("state")
    if isinstance(raw_state, str):
        state = raw_state.strip().lower()
        if state:
            return state
    phase = str(record.get("phase", "")).strip().lower()
    progress_step = _job_progress_step(record)
    if phase == JobState.RUNNING.value and progress_step in {
        JobState.QUEUED.value,
        JobState.PAUSED.value,
    }:
        return progress_step
    return _LEGACY_TERMINAL_PHASES.get(phase, phase or "unknown")


def _job_phase(record: dict[str, object], state: str) -> str:
    """Return the truthful lifecycle phase with legacy terminal aliases."""
    phase = str(record.get("phase", "")).strip().lower()
    if state == JobState.SUCCEEDED.value:
        return phase if phase in {"done", "skipped", "superseded"} else "done"
    if state == JobState.FAILED.value:
        return phase if phase in {"error", "failed"} else "failed"
    if state in _CANONICAL_STATES:
        return state
    return phase or state


def _job_spec_value(record: dict[str, object], key: str) -> object | None:
    return _job_mapping(record, "spec").get(key)


def _job_source(record: dict[str, object]) -> str:
    source = _job_spec_value(record, "source")
    if source is None:
        source = record.get("source")
    value = str(source).strip().lower() if source is not None else ""
    return "code" if value == "codebase" else value or "unknown"


def _job_trigger(record: dict[str, object]) -> str:
    trigger = record.get("trigger")
    if trigger is not None and str(trigger).strip():
        return str(trigger).strip().lower()
    initiator = _job_mapping(record, "initiator")
    kind = str(initiator.get("kind", "")).strip().lower()
    if kind in {"watcher", "schedule"}:
        return kind
    return "tool" if kind else "unknown"


def _job_project_root(record: dict[str, object]) -> str | None:
    project_root = _job_spec_value(record, "project_root")
    if project_root is None:
        project_root = _job_mapping(record, "initiator").get("project_root")
    if project_root is None:
        project_root = record.get("project_root")
    return str(project_root) if project_root is not None else None


def _job_desired_state(record: dict[str, object]) -> str:
    desired_state = record.get("desired_state")
    if not isinstance(desired_state, str):
        return "unknown"
    normalized = desired_state.strip().lower()
    return normalized or "unknown"


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


def _job_progress_step(record: dict[str, object]) -> str:
    progress = _job_mapping(record, "progress")
    return str(progress.get("step", "")).strip().lower()


def _job_progress_timestamp(record: dict[str, object]) -> float | None:
    return _job_number(_job_mapping(record, "progress"), "last_updated")


def job_updated_timestamp(record: dict[str, object]) -> float | None:
    candidates = [
        timestamp
        for timestamp in (
            _job_progress_timestamp(record),
            _job_number(record, "state_changed_at"),
            _job_number(record, "finished_at"),
            _job_number(record, "started_at"),
            _job_number(record, "created_at"),
        )
        if timestamp is not None
    ]
    return max(candidates) if candidates else None


def _job_runtime_seconds(record: dict[str, object], now: float) -> float | None:
    started_at = _job_number(record, "started_at")
    if started_at is None:
        return None
    state = job_state(record)
    if state == JobState.QUEUED.value:
        return None
    finished_at = _job_number(record, "finished_at")
    if finished_at is not None:
        end = finished_at
    elif state == JobState.PAUSED.value:
        state_changed_at = _job_number(record, "state_changed_at")
        if state_changed_at is None:
            return None
        end = state_changed_at
    else:
        end = now
    return max(0.0, end - started_at)


def _job_last_progress_age_seconds(
    record: dict[str, object],
    now: float,
) -> float | None:
    return _age_seconds(_job_progress_timestamp(record), now)


def _timestamp_age_seconds(
    record: dict[str, object],
    key: str,
    now: float,
) -> float | None:
    return _age_seconds(_job_number(record, key), now)


def _control_acknowledgement_seconds(record: dict[str, object]) -> float | None:
    requested = _job_number(record, "control_requested_at")
    acknowledged = _job_number(record, "control_acknowledged_at")
    if requested is None or acknowledged is None:
        return None
    duration = acknowledged - requested
    return duration if duration >= 0 else None


def _control_pending_age_seconds(
    record: dict[str, object],
    now: float,
) -> float | None:
    if job_state(record) not in _TRANSITIONAL_STATES:
        return None
    requested = _job_number(record, "control_requested_at")
    if requested is None:
        return None
    acknowledged = _job_number(record, "control_acknowledged_at")
    if acknowledged is not None and acknowledged >= requested:
        return None
    return _age_seconds(requested, now)


def _job_is_waiting(record: dict[str, object]) -> bool:
    return _job_progress_step(record) == JobState.QUEUED.value


def _job_stalled(record: dict[str, object], now: float) -> bool:
    """Return the truthful service-domain stall signal.

    Running work is stalled only when real work has stopped reporting progress.
    Queued and paused work are intentionally inert. Transitional work is stalled
    only when its cooperative acknowledgement itself exceeds the threshold.
    """
    state = job_state(record)
    if state in _TRANSITIONAL_STATES:
        control_age = _control_pending_age_seconds(record, now)
        return control_age is not None and control_age >= STALL_THRESHOLD_SECONDS
    if state != "running" or _job_is_waiting(record):
        return False
    age = _job_last_progress_age_seconds(record, now)
    return age is not None and age >= STALL_THRESHOLD_SECONDS


def _round_measure(value: object) -> float | None:
    """Round a megabyte or second measure to operator precision, or drop it."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 1)


def _job_resilience(record: dict[str, object]) -> dict[str, object] | None:
    """Project the canonical resilience snapshot into a bounded response shape.

    The raw snapshot is not passed through. Each field is named explicitly, so
    a field added to the snapshot later cannot leak to a broker without a
    deliberate change here; the megabyte and second measures are rounded to the
    same one-decimal operator precision the CLI renders; and a remediation hint
    is derived from the terminal outcome so a broker reading the response can
    act on a failure without re-deriving it. This is the REST peer of the
    health rollup and the CLI render, which expose the same resilience state.
    """
    resilience = record.get("resilience")
    if not isinstance(resilience, dict):
        return None
    data = cast("dict[str, object]", resilience)
    terminal = data.get("terminal_outcome")
    return {
        "generation_id": data.get("generation_id"),
        "committed_units": data.get("committed_units"),
        "replayed_units": data.get("replayed_units"),
        "checkpoint_compatible": data.get("checkpoint_compatible"),
        "last_durable_progress_at": data.get("last_durable_progress_at"),
        "no_progress_timeout_seconds": _round_measure(
            data.get("no_progress_timeout_seconds")
        ),
        "no_progress_remaining_seconds": _round_measure(
            data.get("no_progress_remaining_seconds")
        ),
        "circuit_state": data.get("circuit_state"),
        "next_retry_at": data.get("next_retry_at"),
        "peak_rss_mb": _round_measure(data.get("peak_rss_mb")),
        "rss_ceiling_mb": _round_measure(data.get("rss_ceiling_mb")),
        "peak_cuda_allocated_mb": _round_measure(data.get("peak_cuda_allocated_mb")),
        "peak_cuda_reserved_mb": _round_measure(data.get("peak_cuda_reserved_mb")),
        "cuda_ceiling_mb": _round_measure(data.get("cuda_ceiling_mb")),
        "support_profile": data.get("support_profile"),
        "terminal_outcome": terminal,
        "remediation": remediation(terminal) if isinstance(terminal, str) else None,
    }


def _job_with_liveness(
    record: dict[str, object],
    *,
    now: float,
) -> dict[str, object]:
    enriched = dict(record)
    shaped_resilience = _job_resilience(record)
    if shaped_resilience is not None:
        enriched["resilience"] = shaped_resilience
    else:
        enriched.pop("resilience", None)
    state = job_state(record)
    enriched["state"] = state
    enriched["phase"] = _job_phase(record, state)
    enriched["source"] = _job_source(record)
    enriched["trigger"] = _job_trigger(record)
    enriched["runtime_seconds"] = _job_runtime_seconds(record, now)
    enriched["last_progress_age_seconds"] = _job_last_progress_age_seconds(record, now)
    enriched["control_request_age_seconds"] = _timestamp_age_seconds(
        record,
        "control_requested_at",
        now,
    )
    enriched["control_acknowledged_age_seconds"] = _timestamp_age_seconds(
        record,
        "control_acknowledged_at",
        now,
    )
    enriched["control_acknowledgement_seconds"] = _control_acknowledgement_seconds(
        record
    )
    enriched["control_pending_age_seconds"] = _control_pending_age_seconds(record, now)
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
        legacy_running = (
            "state" not in record
            and state == JobState.RUNNING.value
            and str(record.get("phase", "")).strip().lower() == JobState.RUNNING.value
        )
        if legacy_running:
            enriched_resources["current"] = _jobs.resource_snapshot()
        else:
            enriched_resources.pop("current", None)
        enriched["resources"] = enriched_resources
    return enriched


def _job_id_matches(record: dict[str, object], job_id: str | None) -> bool:
    if job_id is None:
        return True
    return str(record.get("id", "")).startswith(job_id)


def _job_updated_since(
    record: dict[str, object],
    *,
    since_seconds: float | None,
    now: float,
) -> bool:
    if since_seconds is None:
        return True
    timestamp = job_updated_timestamp(record)
    return timestamp is not None and timestamp >= now - since_seconds


def _job_search_text(record: dict[str, object]) -> str:
    return " ".join(
        [
            str(record.get("id", "")),
            _job_source(record),
            _job_trigger(record),
            _job_phase(record, job_state(record)),
            _job_desired_state(record),
            str(record.get("operation", "")),
            str(record.get("mode", "")),
            str(_job_project_root(record) or ""),
            str(record.get("result", "")),
            _job_progress_text(record),
            *_job_nested_values(record.get("spec")),
            *_job_nested_values(record.get("capabilities")),
            *_job_nested_values(record.get("initiator")),
            *_job_nested_values(record.get("runtime")),
        ]
    ).lower()


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
    state: str | None = None,
    desired_state: str | None = None,
    controllable: bool | None = None,
) -> bool:
    record_state = job_state(record)
    matches_filters = all(
        (
            _job_id_matches(record, job_id),
            not failed or record_state == JobState.FAILED.value,
            _job_updated_since(record, since_seconds=since_seconds, now=now),
            phase is None or _job_phase(record, record_state) == phase,
            state is None or record_state == state,
            desired_state is None or _job_desired_state(record) == desired_state,
            controllable is None or _job_controllable(record) is controllable,
            source is None or _job_source(record) == source,
            trigger is None or _job_trigger(record) == trigger,
        )
    )
    return matches_filters and (query is None or query in _job_search_text(record))


def _job_nested_values(raw: object) -> list[str]:
    if not isinstance(raw, dict):
        return []
    raw_map = cast("dict[str, object]", raw)
    return [str(value) for value in raw_map.values() if value is not None]


def _job_controllable(record: dict[str, object]) -> bool:
    capability_map = _job_mapping(record, "capabilities")
    return any(
        capability_map.get(key) is True
        for key in ("pausable", "resumable", "cancellable")
    )


def _job_capability(record: dict[str, object], key: str) -> bool:
    return _job_mapping(record, "capabilities").get(key) is True


def _increment(counts: dict[str, int], value: str) -> None:
    counts[value] = counts.get(value, 0) + 1


def _job_summary(
    records: list[dict[str, object]],
    *,
    now: float,
) -> dict[str, object]:
    phases: dict[str, int] = {}
    states: dict[str, int] = {}
    desired_states: dict[str, int] = {}
    sources: dict[str, int] = {}
    triggers: dict[str, int] = {}
    initiators: dict[str, int] = {}
    active_initiators: dict[str, int] = {}
    users: dict[str, int] = {}
    stalled = 0
    controllable = 0
    control_pending = 0
    retryable = 0
    error_kinds: dict[str, int] = {}
    for record in records:
        if _job_stalled(record, now):
            stalled += 1
        if _job_controllable(record):
            controllable += 1
        if _control_pending_age_seconds(record, now) is not None:
            control_pending += 1
        if _job_capability(record, "retryable"):
            retryable += 1
        kind = record.get("error_kind")
        if isinstance(kind, str) and kind:
            error_kinds[kind] = error_kinds.get(kind, 0) + 1
        state = job_state(record)
        phase = _job_phase(record, state)
        desired_state = _job_desired_state(record)
        source = _job_source(record)
        trigger = _job_trigger(record)
        _increment(phases, phase)
        _increment(states, state)
        _increment(desired_states, desired_state)
        _increment(sources, source)
        _increment(triggers, trigger)
        initiator = record.get("initiator")
        if isinstance(initiator, dict):
            kind = str(cast("dict[str, object]", initiator).get("kind", "unknown"))
            _increment(initiators, kind)
            if state not in _TERMINAL_STATES:
                _increment(active_initiators, kind)
        runtime = record.get("runtime")
        if isinstance(runtime, dict):
            user = str(cast("dict[str, object]", runtime).get("user", "unknown"))
            _increment(users, user)
    return {
        "phases": phases,
        "states": states,
        "desired_states": desired_states,
        "sources": sources,
        "triggers": triggers,
        "initiators": initiators,
        "active_initiators": active_initiators,
        "users": users,
        # ``phases`` remains the compatibility aggregation; lifecycle rollups
        # are always derived from canonical states.
        "running": states.get("running", 0),
        "queued": states.get("queued", 0),
        "paused": states.get("paused", 0),
        "transitional": sum(states.get(state, 0) for state in _TRANSITIONAL_STATES),
        "active": sum(
            count for state, count in states.items() if state not in _TERMINAL_STATES
        ),
        "terminal": sum(states.get(state, 0) for state in _TERMINAL_STATES),
        "succeeded": states.get("succeeded", 0),
        "failed": states.get("failed", 0),
        "cancelled": states.get("cancelled", 0),
        "interrupted": states.get("interrupted", 0),
        "stalled": stalled,
        "control_pending": control_pending,
        "controllable": controllable,
        "retryable": retryable,
        "error_kinds": error_kinds,
    }


def _prioritise_running_jobs(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep actionable lifecycle states visible before completed history."""

    def priority(record: dict[str, object]) -> int:
        state = job_state(record)
        if state in _TRANSITIONAL_STATES:
            return 0
        if state == "running":
            return 1
        if state == "queued":
            return 2
        if state == "paused":
            return 3
        if state in ("failed", "interrupted"):
            return 4
        if state == "cancelled":
            return 5
        if state == "succeeded":
            return 6
        return 7

    return sorted(
        records,
        key=priority,
    )
