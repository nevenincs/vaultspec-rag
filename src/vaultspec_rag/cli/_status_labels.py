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
from typing import TYPE_CHECKING, NamedTuple, cast

from ._cli_format import NOT_REPORTED, _counted_unit

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "DOMAIN_INDEX_FAMILY",
    "FAILED_JOB_FAMILY",
    "DegradedFinding",
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
    "degradation_findings",
    "degradation_lines",
    "render_degradation",
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
    return NOT_REPORTED


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
        return NOT_REPORTED
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
            return NOT_REPORTED
        status = raw_status
        if status == "ready":
            return "ready for requests"
        if status == "starting":
            return "starting up"
        return status.replace("_", " ")
    return "not reachable" if port_listening else "not available"


class _JobCounts(NamedTuple):
    """The three counts every busy, queue, and processed row is derived from."""

    running: int
    queued: int
    active: int


def _job_counts(jobs: dict[str, object] | None) -> _JobCounts | None:
    """Read the job counts once for every row that reports on them.

    ``None`` means the service reported no jobs at all, which each caller
    renders as an absence rather than as an idle service - the distinction the
    availability flag exists to carry.
    """
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return None
    running = jobs.get("running")
    queued = jobs.get("queued")
    running_count = running if isinstance(running, int) else 0
    queued_count = queued if isinstance(queued, int) else 0
    return _JobCounts(
        running=running_count,
        queued=queued_count,
        active=max(0, running_count - queued_count),
    )


def _status_busy_label(jobs: dict[str, object] | None) -> str:
    counts = _job_counts(jobs)
    if counts is None:
        return NOT_REPORTED
    if counts.running <= 0:
        return "idle"
    # Nothing active while jobs are running means every one of them is queued
    # behind the writer, which is a wait rather than work in progress.
    if counts.active <= 0:
        return f"{_counted_unit(counts.queued, 'job')} waiting to write"
    processing = f"processing {_counted_unit(counts.active, 'job')}"
    if counts.queued > 0:
        return f"{processing}; {counts.queued} waiting"
    return processing


def _status_queue_label(jobs: dict[str, object] | None) -> str:
    counts = _job_counts(jobs)
    if counts is None:
        return NOT_REPORTED
    if counts.running <= 0:
        return "nothing waiting"
    if counts.queued > 0:
        return (
            f"{_counted_unit(counts.queued, 'waiting job')}; "
            f"{_counted_unit(counts.active, 'active job')}"
        )
    return f"nothing waiting; {_counted_unit(counts.running, 'active job')}"


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
    counts = _job_counts(jobs)
    if counts is None:
        return NOT_REPORTED
    done = _job_phase_counts(jobs).get("done")
    finished_count = done if isinstance(done, int) else 0
    return (
        f"{finished_count} finished, {counts.active} active, "
        f"{counts.queued} waiting, {_failed_job_total(jobs)} failed"
    )


def _status_uptime_label(health: dict[str, object] | None) -> str:
    if not isinstance(health, dict):
        return NOT_REPORTED
    return _format_status_duration(health.get("uptime_s"))


@dataclass(frozen=True)
class DegradedFinding:
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

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> DegradedFinding:
        """Rebuild a finding a caller carried through a JSON envelope."""

        def text(key: str) -> str:
            value = payload.get(key)
            return value if isinstance(value, str) else ""

        return cls(
            cause=text("cause"),
            detail=text("detail"),
            command=text("command"),
            family=text("family"),
        )


#: Health statuses that describe a service with nothing to explain. Anything
#: else - ``degraded``, ``error``, or a status this build has never seen - is
#: treated as a service that owes the operator a reason.
_UNDEGRADED_STATUSES = frozenset({"ready", "starting", "unknown"})

FAILED_JOB_FAMILY = "failed_job"
STALLED_JOBS_FAMILY = "stalled_jobs"
VECTOR_SERVICE_FAMILY = "vector_service"
MODELS_FAMILY = "models"
DOMAIN_INDEX_FAMILY = "domain_index"


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
) -> DegradedFinding | None:
    record = _last_failed_record(health)
    job_id = _last_failure_job_id(health)
    if not job_id:
        return None
    kind = _error_kind(record)
    return DegradedFinding(
        cause=f"an indexing job failed{f': {kind}' if kind else ''}",
        detail=_failed_job_identity(record, now=now, with_kind=False),
        command=f"vaultspec-rag server logs --job-id {job_id}",
        family=FAILED_JOB_FAMILY,
    )


def _stalled_jobs_finding(
    health: dict[str, object] | None,
    now: float,
) -> DegradedFinding | None:
    _ = now
    stalled = _health_jobs(health).get("stalled")
    if not isinstance(stalled, int) or stalled <= 0:
        return None
    return DegradedFinding(
        cause=f"{_counted_unit(stalled, 'indexing job')} stopped reporting progress",
        command="vaultspec-rag server jobs --state active",
        family=STALLED_JOBS_FAMILY,
    )


def _vector_service_finding(
    health: dict[str, object] | None,
    now: float,
) -> DegradedFinding | None:
    _ = now
    if not isinstance(health, dict):
        return None
    qdrant = health.get("qdrant")
    if not isinstance(qdrant, dict):
        return None
    if cast("dict[str, object]", qdrant).get("alive") is not False:
        return None
    return DegradedFinding(
        cause="the vector storage service is not live",
        command="vaultspec-rag server qdrant status",
        family=VECTOR_SERVICE_FAMILY,
    )


def _models_finding(
    health: dict[str, object] | None,
    now: float,
) -> DegradedFinding | None:
    _ = now
    if not isinstance(health, dict) or health.get("models_loaded") is not False:
        return None
    return DegradedFinding(
        cause="the embedding models are not loaded",
        detail="run server warmup when the model files are missing",
        command="vaultspec-rag server doctor",
        family=MODELS_FAMILY,
    )


#: Degradation families in resolution order, each pairing the distinctive stem
#: of the prose it explains with the structured signal that proves it. Reasons
#: are claimed on one stem rather than a whole sentence so that rewording a
#: reason downgrades it to the unpaired sweep below - which still emits the
#: command - instead of silently losing the remediation.
_DEGRADED_FAMILIES: tuple[
    tuple[str, Callable[[dict[str, object] | None, float], DegradedFinding | None]],
    ...,
] = (
    ("stall", _stalled_jobs_finding),
    ("fail", _failed_job_finding),
    ("vector", _vector_service_finding),
    ("model", _models_finding),
)


def _reported_degradations(payload: dict[str, object]) -> list[object]:
    """Return the reported degradation entries under either accepted key.

    Entry types are preserved rather than coerced to text: the index status
    payload reports structured per-domain records, and stringifying one turns
    an operator-facing cause into a container repr.
    """
    reasons = payload.get("degraded_reasons", payload.get("degraded"))
    return cast("list[object]", reasons) if isinstance(reasons, list) else []


def _health_is_degraded(payload: dict[str, object]) -> bool:
    status = payload.get("status")
    return isinstance(status, str) and status not in _UNDEGRADED_STATUSES


#: Operator vocabulary for a per-domain index degradation: the phrasing and the
#: inspecting verb for each stable reason token the job registry records. A
#: token with no entry is still rendered, quoted verbatim inside the phrase, and
#: falls back to the log filter for the named job.
_DOMAIN_REASONS = {
    "stalled": ("is stalled", "vaultspec-rag server jobs --state active"),
    "failed": ("failed", ""),
    "interrupted": ("was interrupted", ""),
}


def _domain_cause(record: dict[str, object]) -> str:
    """Compose the cause sentence for a structured per-domain record.

    A record this build cannot phrase is flattened to its own fields, never
    rendered as a container: a repr in front of an operator is the defect this
    renderer exists to remove.
    """
    reason = record.get("reason")
    if not isinstance(reason, str) or not reason:
        return ", ".join(f"{key}: {value}" for key, value in record.items() if value)
    source = record.get("source")
    domain = (
        f"the {source} index job"
        if isinstance(source, str) and source
        else "an index job"
    )
    phrase, _ = _DOMAIN_REASONS.get(reason, (f"reported {reason}", ""))
    kind = _error_kind(record)
    return f"{domain} {phrase}{f': {kind}' if kind else ''}"


def _domain_degradation(record: dict[str, object]) -> DegradedFinding:
    """Turn one structured per-domain index degradation into a finding."""
    raw_job_id = record.get("job_id")
    job_id = raw_job_id.strip() if isinstance(raw_job_id, str) else ""
    _, command = _DOMAIN_REASONS.get(str(record.get("reason")), ("", ""))
    if not command and job_id:
        command = f"vaultspec-rag server logs --job-id {job_id}"
    return DegradedFinding(
        cause=_domain_cause(record),
        detail=f"job {_short_job_id(job_id)}" if job_id else "",
        command=command,
        family=DOMAIN_INDEX_FAMILY,
    )


def degradation_findings(
    payload: dict[str, object] | None,
    *,
    now: float | None = None,
) -> list[DegradedFinding]:
    """Pair every reported degradation cause with the verb that inspects it.

    This is the one place that turns a degradation report into operator-facing
    causes and remedies - extend it rather than adding a second renderer. It
    accepts any payload carrying ``degraded_reasons`` (or the legacy
    ``degraded``): the service health payload, whose entries are prose backed by
    structured signals in the same payload, and the index status payload, whose
    entries are structured per-domain records.

    The reported entries are the authority on what is wrong, so each is rendered
    whether or not it can be paired. The structured signals are the authority on
    where to look, so the remediation is derived from them rather than parsed
    out of the prose - a reworded reason loses its pairing, never its
    visibility, and a proven signal no entry claimed is reported anyway.

    A service that reports no problem gets no findings even when a failed job
    sits in its history: history is reported elsewhere and is not a verdict on
    the running process.
    """
    if not isinstance(payload, dict):
        return []
    reported = _reported_degradations(payload)
    if not reported and not _health_is_degraded(payload):
        return []
    unclaimed = _proven_findings(payload, time.time() if now is None else now)
    findings = [_reported_finding(entry, unclaimed) for entry in reported]
    findings.extend(unclaimed.values())
    return [finding for finding in findings if finding.cause]


def _reported_finding(
    entry: object,
    unclaimed: dict[str, DegradedFinding],
) -> DegradedFinding:
    """Render one reported entry, claiming the signal that explains it."""
    if isinstance(entry, dict):
        return _domain_degradation(cast("dict[str, object]", entry))
    reason = str(entry).strip()
    stem = next((known for known in unclaimed if known in reason.lower()), None)
    if not reason or stem is None:
        return DegradedFinding(cause=reason)
    evidence = unclaimed.pop(stem)
    return DegradedFinding(
        cause=reason,
        detail=evidence.detail,
        command=evidence.command,
        family=evidence.family,
    )


def _proven_findings(
    payload: dict[str, object],
    now: float,
) -> dict[str, DegradedFinding]:
    """Build the finding for every family whose structured signal fires."""
    return {
        stem: finding
        for stem, builder in _DEGRADED_FAMILIES
        if (finding := builder(payload, now)) is not None
    }


def degradation_lines(
    findings: list[DegradedFinding],
    *,
    header: str,
    remediation: bool = True,
    port_arg: str = "",
) -> list[str]:
    """Shape findings into operator lines under ``header``.

    With ``remediation`` each cause is followed by its indented detail and the
    command that inspects it. Without it only the causes are listed, which is
    the compact shape for a surface that already states its own next action.
    """
    if not findings:
        return []
    lines = [header]
    for finding in findings:
        lines.append(f"  - {finding.cause}")
        if not remediation:
            continue
        if finding.detail:
            lines.append(f"    {finding.detail}")
        if finding.command:
            lines.append(f"    {finding.command}{port_arg}")
    return lines


def render_degradation(
    payload: dict[str, object] | None,
    *,
    header: str,
    remediation: bool = True,
    port_arg: str = "",
    now: float | None = None,
) -> list[str]:
    """Render a payload's degradation report as operator lines.

    The single entry point for any surface that shows why something is
    degraded. A caller that also needs the findings themselves - to choose a
    next action, or to put them in a JSON envelope - composes
    :func:`degradation_findings` with :func:`degradation_lines` instead of
    re-deriving either half.
    """
    return degradation_lines(
        degradation_findings(payload, now=now),
        header=header,
        remediation=remediation,
        port_arg=port_arg,
    )


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
    return NOT_REPORTED
