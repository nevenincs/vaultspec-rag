"""Pure label and duration formatting for the ``server status`` renderer.

Deterministic string producers extracted from ``_status_render``: they map raw
health/jobs signals to the operator-facing words (identity, network, model,
busy/queue/jobs) and format durations and timestamps. No console I/O and no
service probing - the renderer computes the signals and these turn them into
text, which keeps the render module focused on orchestration.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, cast

from ._cli_format import _counted_unit

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "_FAILED_JOB_FAMILY",
    "_DegradedFinding",
    "_degraded_findings",
    "_failed_job_total",
    "_format_started_label",
    "_format_status_duration",
    "_get_token_label",
    "_last_failure_job_id",
    "_last_failure_label",
    "_model_ready_label",
    "_network_label",
    "_plain_status_label",
    "_process_identity_label",
    "_status_busy_label",
    "_status_env_label",
    "_status_health_label",
    "_status_jobs_label",
    "_status_queue_label",
    "_status_uptime_label",
]


def _get_token_label(token_match: bool | None) -> str:
    if token_match is None:
        return "not verified by this status check"
    if token_match:
        return "verified"
    return "does not match the recorded service"


def _model_ready_label(value: object) -> str:
    if value is True:
        return "ready"
    if value is False:
        return "not ready"
    return "not reported by service"


def _process_identity_label(pid_alive: bool, pid_is_ours: bool) -> str:
    if pid_is_ours:
        return "verified"
    if pid_alive:
        return "does not match the recorded service"
    return "not verified because the process is not running"


def _network_label(port_listening: bool, pid_alive: bool) -> str:
    if port_listening:
        return "accepting connections"
    if pid_alive:
        return "not accepting connections"
    return "not accepting connections"


def _plain_status_label(state: str) -> str:
    return re.sub(r"\[[^]]*\]", "", state)


def _format_status_duration(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported by service"
    seconds = max(0, int(float(raw)))
    if seconds < 60:
        return _counted_unit(seconds, "second")
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        if seconds:
            return (
                f"{_counted_unit(minutes, 'minute')} {_counted_unit(seconds, 'second')}"
            )
        return _counted_unit(minutes, "minute")
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        if minutes:
            return f"{_counted_unit(hours, 'hour')} {_counted_unit(minutes, 'minute')}"
        return _counted_unit(hours, "hour")
    days, hours = divmod(hours, 24)
    if hours:
        return f"{_counted_unit(days, 'day')} {_counted_unit(hours, 'hour')}"
    return _counted_unit(days, "day")


def _format_started_label(raw: object) -> str:
    if not isinstance(raw, str) or not raw or raw == "unknown":
        return "not reported by local record"
    try:
        started = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    return f"{started.astimezone().strftime('%H:%M:%S')} local time"


def _status_health_label(
    health: dict[str, object] | None,
    *,
    port_listening: bool,
) -> str:
    if isinstance(health, dict):
        raw_status = health.get("status")
        if not isinstance(raw_status, str) or not raw_status or raw_status == "unknown":
            return "not reported by service"
        status = raw_status
        if status == "ready":
            return "ready for requests"
        if status == "starting":
            return "starting up"
        return status.replace("_", " ")
    return "not reachable" if port_listening else "not available"


def _status_busy_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "not reported by service"
    running = jobs.get("running")
    queued = jobs.get("queued")
    running_count = running if isinstance(running, int) else 0
    queued_count = queued if isinstance(queued, int) else 0
    if running_count <= 0:
        return "idle"
    active_count = max(0, running_count - queued_count)
    if active_count <= 0 and queued_count > 0:
        return (
            "1 job waiting to write"
            if queued_count == 1
            else f"{queued_count} jobs waiting to write"
        )
    if active_count > 0 and queued_count > 0:
        active_text = (
            "processing 1 job"
            if active_count == 1
            else f"processing {active_count} jobs"
        )
        waiting_text = "1 waiting" if queued_count == 1 else f"{queued_count} waiting"
        return f"{active_text}; {waiting_text}"
    if active_count == 1:
        return "processing 1 job"
    return f"processing {active_count} jobs"


def _status_queue_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "not reported by service"
    running = jobs.get("running")
    queued = jobs.get("queued")
    running_count = running if isinstance(running, int) else 0
    queued_count = queued if isinstance(queued, int) else 0
    if running_count <= 0:
        return "nothing waiting"
    active_count = max(0, running_count - queued_count)
    if queued_count > 0:
        active_text = (
            "1 active job" if active_count == 1 else f"{active_count} active jobs"
        )
        queued_text = (
            "1 waiting job" if queued_count == 1 else f"{queued_count} waiting jobs"
        )
        return f"{queued_text}; {active_text}"
    running_text = (
        "1 active job" if running_count == 1 else f"{running_count} active jobs"
    )
    return f"nothing waiting; {running_text}"


def _job_phase_counts(jobs: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return {}
    phases = jobs.get("phases")
    return cast("dict[str, object]", phases) if isinstance(phases, dict) else {}


def _failed_job_total(jobs: dict[str, object] | None) -> int:
    """Count the failed jobs the service reported, across both phase names."""
    phases = _job_phase_counts(jobs)
    total = 0
    for key in ("error", "failed"):
        count = phases.get(key)
        if isinstance(count, int):
            total += count
    return total


def _status_jobs_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "not reported by service"
    running = jobs.get("running")
    queued = jobs.get("queued")
    running_count = running if isinstance(running, int) else 0
    queued_count = queued if isinstance(queued, int) else 0
    active_count = max(0, running_count - queued_count)
    done = _job_phase_counts(jobs).get("done")
    finished_count = done if isinstance(done, int) else 0
    return (
        f"{finished_count} finished, {active_count} active, "
        f"{queued_count} waiting, {_failed_job_total(jobs)} failed"
    )


def _status_uptime_label(health: dict[str, object] | None) -> str:
    if not isinstance(health, dict):
        return "not reported by service"
    return _format_status_duration(health.get("uptime_s"))


@dataclass(frozen=True)
class _DegradedFinding:
    """One reported cause of degradation plus the verb that inspects it.

    ``cause`` is what the operator is told is wrong, ``detail`` narrows it to a
    specific job or subsystem, and ``command`` is a runnable next move. Only
    ``cause`` is guaranteed: a cause nothing could be paired with is still
    reported, because an unexplained problem the operator can see beats a
    problem silently dropped for want of a remedy.
    """

    cause: str
    detail: str = ""
    command: str = ""
    family: str = ""

    def as_dict(self, *, port_arg: str = "") -> dict[str, str]:
        payload = {"cause": self.cause}
        if self.detail:
            payload["detail"] = self.detail
        if self.command:
            payload["command"] = f"{self.command}{port_arg}"
        if self.family:
            payload["family"] = self.family
        return payload


#: Health statuses that describe a service with nothing to explain. Anything
#: else - ``degraded``, ``error``, or a status this build has never seen - is
#: treated as a service that owes the operator a reason.
_UNDEGRADED_STATUSES = frozenset({"ready", "starting", "unknown"})

_FAILED_JOB_FAMILY = "failed_job"
_STALLED_JOBS_FAMILY = "stalled_jobs"
_VECTOR_SERVICE_FAMILY = "vector_service"
_MODELS_FAMILY = "models"


def _health_jobs(health: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(health, dict):
        return {}
    jobs = health.get("jobs")
    return cast("dict[str, object]", jobs) if isinstance(jobs, dict) else {}


def _last_failed_record(health: dict[str, object] | None) -> dict[str, object]:
    record = _health_jobs(health).get("last_failed")
    return cast("dict[str, object]", record) if isinstance(record, dict) else {}


def _last_failure_job_id(health: dict[str, object] | None) -> str:
    job_id = _last_failed_record(health).get("id")
    return job_id.strip() if isinstance(job_id, str) else ""


def _short_job_id(job_id: str) -> str:
    """Shorten a long job id for prose; commands always carry the full id."""
    return job_id[:8] if len(job_id) > 12 else job_id


def _job_age_label(finished_at: object, *, now: float) -> str:
    if not isinstance(finished_at, int | float):
        return ""
    elapsed = now - float(finished_at)
    # A negative age means the clocks disagree, not that the job finishes in the
    # future. Saying nothing is better than an age no operator can act on.
    if elapsed < 0:
        return ""
    return f", {_format_status_duration(elapsed)} ago"


def _error_kind(record: dict[str, object]) -> str:
    kind = record.get("error_kind")
    return kind if isinstance(kind, str) and kind else ""


def _failed_job_identity(
    record: dict[str, object],
    *,
    now: float,
    with_kind: bool,
) -> str:
    """Name the failed job and how long ago it finished.

    ``with_kind`` is false wherever the error kind is already carried by the
    cause line above this one, so the same word never appears twice.
    """
    job_id = record.get("id")
    if not isinstance(job_id, str) or not job_id.strip():
        return ""
    kind = _error_kind(record)
    kind_text = f" ({kind})" if with_kind and kind else ""
    age = _job_age_label(record.get("finished_at"), now=now)
    return f"job {_short_job_id(job_id.strip())}{kind_text}{age}"


def _last_failure_label(
    health: dict[str, object] | None,
    *,
    now: float | None = None,
) -> str:
    """Describe the latest reported job failure, or return an empty string."""
    observed_at = time.time() if now is None else now
    return _failed_job_identity(
        _last_failed_record(health),
        now=observed_at,
        with_kind=True,
    )


def _failed_job_finding(
    health: dict[str, object] | None,
    now: float,
) -> _DegradedFinding | None:
    record = _last_failed_record(health)
    job_id = _last_failure_job_id(health)
    if not job_id:
        return None
    kind = _error_kind(record)
    return _DegradedFinding(
        cause=f"an indexing job failed{f': {kind}' if kind else ''}",
        detail=_failed_job_identity(record, now=now, with_kind=False),
        command=f"vaultspec-rag server logs --job-id {job_id}",
        family=_FAILED_JOB_FAMILY,
    )


def _stalled_jobs_finding(
    health: dict[str, object] | None,
    now: float,
) -> _DegradedFinding | None:
    _ = now
    stalled = _health_jobs(health).get("stalled")
    if not isinstance(stalled, int) or stalled <= 0:
        return None
    return _DegradedFinding(
        cause=f"{_counted_unit(stalled, 'indexing job')} stopped reporting progress",
        command="vaultspec-rag server jobs --state active",
        family=_STALLED_JOBS_FAMILY,
    )


def _vector_service_finding(
    health: dict[str, object] | None,
    now: float,
) -> _DegradedFinding | None:
    _ = now
    if not isinstance(health, dict):
        return None
    qdrant = health.get("qdrant")
    if not isinstance(qdrant, dict):
        return None
    if cast("dict[str, object]", qdrant).get("alive") is not False:
        return None
    return _DegradedFinding(
        cause="the vector storage service is not live",
        command="vaultspec-rag server qdrant status",
        family=_VECTOR_SERVICE_FAMILY,
    )


def _models_finding(
    health: dict[str, object] | None,
    now: float,
) -> _DegradedFinding | None:
    _ = now
    if not isinstance(health, dict) or health.get("models_loaded") is not False:
        return None
    return _DegradedFinding(
        cause="the embedding models are not loaded",
        detail="run server warmup when the model files are missing",
        command="vaultspec-rag server doctor",
        family=_MODELS_FAMILY,
    )


#: Degradation families in resolution order, each pairing the distinctive stem
#: of the prose it explains with the structured signal that proves it. Reasons
#: are claimed on one stem rather than a whole sentence so that rewording a
#: reason downgrades it to the unpaired sweep below - which still emits the
#: command - instead of silently losing the remediation.
_DEGRADED_FAMILIES: tuple[
    tuple[str, Callable[[dict[str, object] | None, float], _DegradedFinding | None]],
    ...,
] = (
    ("stall", _stalled_jobs_finding),
    ("fail", _failed_job_finding),
    ("vector", _vector_service_finding),
    ("model", _models_finding),
)


def _degraded_reason_texts(health: dict[str, object]) -> list[str]:
    reasons = health.get("degraded_reasons")
    if not isinstance(reasons, list):
        return []
    return [
        reason.strip()
        for reason in cast("list[object]", reasons)
        if isinstance(reason, str) and reason.strip()
    ]


def _health_is_degraded(health: dict[str, object]) -> bool:
    status = health.get("status")
    return isinstance(status, str) and status not in _UNDEGRADED_STATUSES


def _degraded_findings(
    health: dict[str, object] | None,
    *,
    now: float | None = None,
) -> list[_DegradedFinding]:
    """Pair every reported degradation cause with the verb that inspects it.

    The reported reasons are the authority on what is wrong, so each one is
    rendered whether or not it can be paired. The structured signals are the
    authority on where to look, so the remediation is derived from them rather
    than parsed out of the prose - a reworded reason loses its pairing, never
    its visibility, and a proven signal no reason claimed is reported anyway.

    A service that reports no problem gets no findings even when a failed job
    sits in its history: history is reported elsewhere and is not a verdict on
    the running process.
    """
    if not isinstance(health, dict):
        return []
    reasons = _degraded_reason_texts(health)
    if not reasons and not _health_is_degraded(health):
        return []
    unclaimed = _proven_findings(health, time.time() if now is None else now)
    findings: list[_DegradedFinding] = []
    for reason in reasons:
        lowered = reason.lower()
        stem = next((known for known in unclaimed if known in lowered), None)
        if stem is None:
            findings.append(_DegradedFinding(cause=reason))
            continue
        evidence = unclaimed.pop(stem)
        findings.append(
            _DegradedFinding(
                cause=reason,
                detail=evidence.detail,
                command=evidence.command,
                family=evidence.family,
            )
        )
    findings.extend(unclaimed.values())
    return findings


def _proven_findings(
    health: dict[str, object],
    now: float,
) -> dict[str, _DegradedFinding]:
    """Build the finding for every family whose structured signal fires."""
    return {
        stem: finding
        for stem, builder in _DEGRADED_FAMILIES
        if (finding := builder(health, now)) is not None
    }


def _status_env_label(health: dict[str, object] | None) -> str:
    """Return the daemon's python interpreter from /health, or a clear miss.

    The service runs in whatever interpreter launched ``server start`` (it does
    not provision its own python), so surfacing it makes the service<->env
    coupling visible at a glance.
    """
    if isinstance(health, dict):
        exe = health.get("executable")
        if isinstance(exe, str) and exe:
            return exe
    return "not reported by service"
