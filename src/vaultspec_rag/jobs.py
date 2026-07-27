"""In-flight activity registry and background task worker for index/reindex jobs.

A thread-safe, bounded record of every index/reindex activity the service performs,
along with async task execution helpers for background reindexing.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast, get_args

from anyio.to_thread import run_sync as _run_in_thread

from ._job_errors import STALL_THRESHOLD_SECONDS, classify_error_text
from ._runtime_identity import process_identity_fields
from .config import managed_status_dir
from .job_control import NO_RUN_CONTROL
from .job_manager.manager import JobManager
from .job_manager.models import MAX_RECORDS, JobAttemptContext, JobExecutionResult
from .job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobOutcome,
    JobOutcomeStatus,
    JobSnapshot,
    JobSource,
    JobSpec,
    JobState,
)
from .logging_config import log_event
from .registry import get_registry

if TYPE_CHECKING:
    from collections.abc import Callable

    from .index_profiles import SupportMeasurement
    from .indexer import CodebaseIndexer
    from .indexer._codebase_indexer import (
        CodeIndexPreflight,
        CodeScopedPreflight,
        ContentScanResult,
    )
    from .indexer._document_indexer import (
        DocumentIndexPreflight,
        DocumentScopedPreflight,
    )
    from .job_control import RunControl
    from .service import ServiceRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "TERMINAL_PHASES",
    "JobProgressReporter",
    "activate_index_job",
    "active_index_support_profiles",
    "delete_job",
    "find_job",
    "get_job_manager",
    "index_job_status",
    "progress_rate",
    "record_finish",
    "record_progress",
    "record_start",
    "register_on_job_complete",
    "reset",
    "resource_snapshot",
    "restore_interrupted",
    "restore_managed_jobs",
    "scan_code_index_preflight",
    "snapshot",
    "start_reindex_codebase",
    "start_reindex_vault",
    "validate_code_index_policy",
    "validate_code_job_admission",
    "validate_code_support_profile",
    "validate_document_index_policy",
    "validate_document_job_admission",
    "validate_document_support_profile",
    "validate_scoped_code_index_policy",
    "validate_scoped_document_index_policy",
]


def active_index_support_profiles() -> dict[str, object]:
    """Return the configured code and document ceilings for service status."""
    from .config import get_config
    from .index_profiles import index_support_profile_status

    return index_support_profile_status(get_config().index_support_profile)


# What initiated the activity: a reindex tool call, the filesystem watcher,
# or the daemon's periodic schedule.
Trigger = Literal["tool", "watcher", "schedule"]
# Lifecycle phase of a record. ``interrupted`` marks a job restored at
# daemon startup whose prior daemon life died mid-run - without it, a
# killed daemon silently erased every in-flight job from the in-memory
# ring and operators had no record the work ever died.
Phase = Literal[
    "running",
    "done",
    "error",
    "failed",
    "cancelled",
    "superseded",
    "skipped",
    "interrupted",
]
#: Phases a record can no longer leave. Every phase except ``running`` is
#: terminal, and this is the sole definition of that set: deletion, retention
#: and the read surface all have to agree on which records are finished.
TERMINAL_PHASES: frozenset[str] = frozenset(
    phase for phase in get_args(Phase) if phase != "running"
)

_lock = threading.Lock()
_records: deque[dict[str, object]] = deque(maxlen=MAX_RECORDS)
# Progress-rate sampling. The window rides on its own record, so it is
# evicted with that record by the ring and needs no second bound.
#
# The window is per-step and is discarded whenever the step changes,
# because an index job's steps have very different per-unit costs:
# a rate carried over from discovery into embedding predicts embedding
# badly, and a wrong estimate is worse than none.
_PROGRESS_WINDOW_KEY = "progress_window"
_PROGRESS_WINDOW_SAMPLES = 16
# Two samples milliseconds apart divide a small count by a smaller
# interval and yield a rate off by orders of magnitude. Refusing to
# answer until the window spans a real interval costs one refresh.
_MIN_RATE_SPAN_SECONDS = 1.0
# Retained samples are spaced by at least this interval. Chunk production
# reports per file and measures ~385 reports/second on a real tree, so a
# window bounded only by sample count holds ~40ms of history and can never
# satisfy the span guard above - the two bounds cancel and the rate is
# never available. Coalescing every report that lands inside the interval
# into the newest sample keeps the window bounded by count while still
# spanning a real interval, without discarding the current count: the
# newest sample always carries it.
_PROGRESS_SAMPLE_MIN_INTERVAL_SECONDS = 0.25
_on_job_complete_callbacks: list[Callable[[float], None]] = []
_manager_lock = threading.Lock()
_job_manager: JobManager | None = None


# Persisted active-jobs snapshot, under the managed status dir. Written on
# every job start/finish and step change; read once at daemon startup to
# re-register jobs a dead daemon left running as ``interrupted``.
_ACTIVE_SNAPSHOT_FILENAME = "jobs-active.json"


def get_job_manager() -> JobManager:
    """Return the lazily configured process-wide canonical job manager."""
    global _job_manager
    manager = _job_manager
    if manager is None:
        with _manager_lock:
            manager = _job_manager
            if manager is None:
                manager = JobManager(quiesce_gate=get_registry().quiesce_gate)
                _job_manager = manager
    return manager


def _active_snapshot_path() -> object:
    """Resolve the active-jobs snapshot path from the managed status dir."""

    return managed_status_dir() / _ACTIVE_SNAPSHOT_FILENAME


def _persist_active_snapshot() -> None:
    """Write the currently-running jobs to the status dir, atomically.

    Best-effort durability for the in-memory ring: if this daemon dies,
    the next startup reads the file and surfaces the jobs as
    ``interrupted`` instead of letting them vanish. Never raises - jobs
    bookkeeping must not fail a job.
    """

    from ._atomic_write import JsonWriteOptions, write_json_atomically

    with _lock:
        active = [
            {
                "id": record.get("id"),
                "source": record.get("source"),
                "trigger": record.get("trigger"),
                "started_at": record.get("started_at"),
                # Which process owns the run. The snapshot path is shared by
                # every process on the machine, so the reader needs this to
                # tell a job its own prior life abandoned from one still
                # running under somebody else.
                "pid": runtime.get("pid")
                if isinstance(runtime := record.get("runtime"), dict)
                else None,
                "progress": dict(cast("dict[str, object]", progress))
                if isinstance(progress := record.get("progress"), dict)
                else None,
                "initiator": dict(cast("dict[str, object]", initiator))
                if isinstance(initiator := record.get("initiator"), dict)
                else None,
            }
            for record in _records
            if record.get("phase") == "running"
        ]
    try:
        write_json_atomically(
            cast("Path", _active_snapshot_path()),
            {"active": active},
            JsonWriteOptions(durable=True),
        )
    except OSError:
        logger.debug("could not persist active-jobs snapshot", exc_info=True)


def _owned_by_live_process(pid: object) -> bool:
    """Return whether a snapshot entry is still owned by a running process.

    An unreadable or absent pid reports ``False`` so the entry is restored:
    a record that predates this field, or one written by a process that
    crashed mid-write, is exactly the interrupted work restoration exists to
    surface, and losing it silently is worse than an extra record.
    """
    if isinstance(pid, bool) or not isinstance(pid, int):
        return False
    from ._process_probe import pid_alive

    return pid_alive(pid)


def restore_interrupted() -> int:
    """Re-register jobs a prior daemon life left running as ``interrupted``.

    Called once at daemon startup. Each restored record keeps its original
    id, source/trigger, start time, last known progress, and initiator
    attribution, and carries an explanatory result so ``server jobs``
    shows what died instead of nothing. Returns the number restored.
    """
    import json as _json

    path = cast("Path", _active_snapshot_path())
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0
    except OSError:
        logger.debug("active-jobs snapshot unreadable", exc_info=True)
        return 0
    entries_obj: object = []
    try:
        entries_obj = cast("dict[str, object]", _json.loads(raw)).get("active", [])
    except (ValueError, AttributeError):
        logger.debug("active-jobs snapshot malformed", exc_info=True)
    entries = cast("list[object]", entries_obj) if isinstance(entries_obj, list) else []
    restored = 0
    now = time.time()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        data = cast("dict[str, object]", entry)
        if _owned_by_live_process(data.get("pid")):
            # Still running somewhere. Adopting it would publish a phantom
            # ``interrupted`` record for work that never stopped, under an id
            # this service cannot address.
            continue
        record: dict[str, object] = {
            "id": data.get("id") or uuid.uuid4().hex,
            "source": data.get("source"),
            "trigger": data.get("trigger"),
            "phase": "interrupted",
            "started_at": data.get("started_at"),
            "finished_at": now,
            "result": "daemon terminated while this job was running",
            "error_kind": None,
            "progress": data.get("progress"),
            "preprocess_ok": 0,
            "preprocess_skipped": 0,
            "preprocess_failures": [],
            "reuse": None,
            "drift": None,
            "initiator": data.get("initiator"),
            "runtime": process_identity_fields(),
            "resources": {"started": None, "finished": None},
        }
        with _lock:
            _records.append(record)
        restored += 1
        log_event(
            logger,
            "service.job",
            "interrupted",
            severity=logging.WARNING,
            job_id=str(record["id"]),
            source=record.get("source"),
            trigger=record.get("trigger"),
            phase="interrupted",
        )
    # The prior life's snapshot is consumed; persist the (empty) current
    # running set so a second restart does not re-restore the same jobs.
    _persist_active_snapshot()
    return restored


def resource_snapshot() -> dict[str, object]:
    """Return a best-effort current resource snapshot for the service process."""
    from .memory_probe import current_cuda_mb, current_rss_mb

    cuda_allocated_mb, cuda_reserved_mb = current_cuda_mb()
    return {
        "rss_mb": round(current_rss_mb(), 1),
        "cuda_allocated_mb": round(cuda_allocated_mb, 1),
        "cuda_reserved_mb": round(cuda_reserved_mb, 1),
    }


def register_on_job_complete(callback: Callable[[float], None]) -> None:
    """Register a callback to be run when a background job completes.

    The callback receives the duration of the job in seconds.
    """
    _on_job_complete_callbacks.append(callback)


def record_start(
    source: JobSource,
    trigger: Trigger,
    *,
    project_root: Path | None = None,
    command: str | None = None,
    initiator_kind: str | None = None,
    _record_id: str | None = None,
) -> str:
    """Append a new ``running`` activity record and return its stable id.

    Args:
        source: ``"vault"`` or ``"code"`` (the corpus being (re)indexed),
            or ``"maintenance"`` (the scheduled storage-maintenance cycle).
        trigger: ``"tool"`` (a reindex MCP tool call), ``"watcher"`` (the
            filesystem watcher reindex loop), or ``"schedule"`` (the
            daemon's periodic maintenance task).
        project_root: Optional workspace root the job acts on.
        command: Optional service-domain command name.
        initiator_kind: Optional caller identity, e.g. CLI, MCP, or watcher.

    Returns:
        The record's stable ``id`` (a uuid4 hex string) to pass to
        :func:`record_finish`.
    """
    record_id = _record_id or uuid.uuid4().hex
    record: dict[str, object] = {
        "id": record_id,
        "source": source,
        "trigger": trigger,
        "phase": "running",
        "started_at": time.time(),
        "finished_at": None,
        "result": None,
        # Stable failure classification: stamped by record_finish
        # from the error text so /jobs consumers and the CLI share one
        # taxonomy instead of per-surface string matching.
        "error_kind": None,
        "progress": None,
        # Document-preprocessing outcome, surfaced through /jobs so a
        # non-interactive client sees which files failed extraction rather than
        # only a summary count, and how many files
        # rules actually fed, so a missing rule-fed corpus is diagnosable from
        # the job record alone. Populated at finish.
        "preprocess_ok": 0,
        "preprocess_skipped": 0,
        "preprocess_failures": [],
        # Donor vector-reuse telemetry for the run (hit/miss counts, hit
        # rate, estimated GPU seconds saved, donor availability). ``None``
        # until finish, and stays ``None`` when reuse is disabled.
        "reuse": None,
        # Source-drift telemetry for the run: paths superseded because
        # their source moved while the run recorded them, and any left
        # stale for the next generation. Populated at finish.
        "drift": None,
        "initiator": {
            "kind": initiator_kind or trigger,
            "command": command or f"{trigger}_{source}_index",
            "project_root": str(project_root) if project_root is not None else None,
        },
        "runtime": process_identity_fields(),
        "resources": {
            "started": resource_snapshot(),
            "finished": None,
        },
    }
    with _lock:
        _records.append(record)
    _persist_active_snapshot()
    log_event(
        logger,
        "service.job",
        "started",
        job_id=record_id,
        source=source,
        trigger=trigger,
        phase="running",
        initiator_kind=initiator_kind or trigger,
        command=command or f"{trigger}_{source}_index",
        project_root=str(project_root) if project_root is not None else None,
    )
    return record_id


def _sample_progress(
    record: dict[str, object],
    *,
    step: str,
    previous_step: object,
    completed: int,
    at: float,
) -> None:
    """Record one progress observation on *record* (caller holds the lock).

    The window is discarded when the step changes, and when the count moves
    backwards - a resumed attempt replays committed units, so measuring
    across that reset would report a negative rate or a wildly low one.

    Reports arriving faster than
    :data:`_PROGRESS_SAMPLE_MIN_INTERVAL_SECONDS` are coalesced into the
    newest sample rather than appended, so a bounded window spans a real
    interval however fast the step reports.
    """
    window = record.get(_PROGRESS_WINDOW_KEY)
    samples = (
        cast("deque[tuple[float, int]]", window)
        if isinstance(window, deque)
        else deque(maxlen=_PROGRESS_WINDOW_SAMPLES)
    )
    if previous_step != step or (samples and completed < samples[-1][1]):
        samples.clear()
    # Measured against the last committed sample, never the newest one: the
    # newest is overwritten in place, so comparing against it would hold the
    # window open forever and turn the rate into a whole-step average that
    # cannot track a slowdown.
    if (
        len(samples) >= 2
        and at - samples[-2][0] < _PROGRESS_SAMPLE_MIN_INTERVAL_SECONDS
    ):
        samples[-1] = (at, completed)
    else:
        samples.append((at, completed))
    record[_PROGRESS_WINDOW_KEY] = samples


def _window_rate(samples: deque[tuple[float, int]]) -> float | None:
    """Return the completion rate per second across *samples*, or ``None``.

    Declines to answer rather than guessing: a single sample measures no
    interval, a short span divides by near-zero, and a flat count over a
    real span is a stall the caller should not convert into an estimate.
    """
    if len(samples) < 2:
        return None
    first_at, first_completed = samples[0]
    last_at, last_completed = samples[-1]
    span = last_at - first_at
    advanced = last_completed - first_completed
    if span < _MIN_RATE_SPAN_SECONDS or advanced <= 0:
        return None
    return advanced / span


def progress_rate(record_id: str) -> float | None:
    """Return the windowed completion rate for one job, or ``None``.

    ``None`` means the service declines to estimate - the job is unknown,
    has not reported twice within one step, or has not advanced. It never
    means zero.
    """
    with _lock:
        for record in reversed(_records):
            if record["id"] != record_id:
                continue
            window = record.get(_PROGRESS_WINDOW_KEY)
            if not isinstance(window, deque):
                return None
            return _window_rate(cast("deque[tuple[float, int]]", window))
    return None


def record_progress(
    record_id: str,
    step: str,
    completed: int = 0,
    total: int | None = None,
) -> None:
    """Update progress for an active running job.

    Args:
        record_id: The id returned by :func:`record_start`.
        step: Name of the current phase/step (e.g. "queued", "discover", "embed").
        completed: Count of items processed so far in this step.
        total: Total number of items to process, if known.
    """
    log_fields: dict[str, object] | None = None
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                progress = record.get("progress")
                progress_step = None
                if isinstance(progress, dict):
                    progress_data = cast("dict[str, object]", progress)
                    progress_step = progress_data.get("step")
                now = time.time()
                record["progress"] = {
                    "step": step,
                    "completed": completed,
                    "total": total,
                    "last_updated": now,
                }
                _sample_progress(
                    record,
                    step=step,
                    previous_step=progress_step,
                    completed=completed,
                    at=now,
                )
                if progress_step != step:
                    log_fields = {
                        "job_id": record_id,
                        "source": record.get("source"),
                        "trigger": record.get("trigger"),
                        "phase": record.get("phase"),
                        "step": step,
                        "completed": completed,
                        "total": total,
                    }
                break
    if log_fields is not None:
        # Step transitions are rare (a handful per run), so refreshing the
        # durable snapshot here keeps restored progress meaningful without
        # per-batch write churn.
        _persist_active_snapshot()
        log_event(logger, "service.job", "progress", fields=log_fields)


def _finish_record(
    record: dict[str, object],
    *,
    target_phase: str,
    summary: str | None,
    error: str | None,
    details: _FinishDetails,
) -> dict[str, object] | None:
    """Apply the terminal state to *record* in place (caller holds the lock).

    Returns the log fields for the finished event, or ``None`` when the
    record already reached a terminal state (idempotent: cancellation
    paths can race their cleanup; the first terminal state wins).
    """
    if record["finished_at"] is not None:
        logger.debug(
            "record_finish: job %s already finished; "
            "keeping its original terminal state",
            record.get("id"),
        )
        return None
    record["phase"] = target_phase
    record["finished_at"] = time.time()
    record["result"] = summary
    record["error_kind"] = classify_error_text(error) if error is not None else None
    record["preprocess_ok"] = details.preprocess_ok
    record["preprocess_skipped"] = details.preprocess_skipped
    record["preprocess_failures"] = list(details.preprocess_failures or [])
    record["reuse"] = dict(details.reuse) if details.reuse is not None else None
    record["drift"] = dict(details.drift) if details.drift is not None else None
    resources = record.get("resources")
    if isinstance(resources, dict):
        cast("dict[str, object]", resources)["finished"] = resource_snapshot()
    return {
        "job_id": record.get("id"),
        "source": record.get("source"),
        "trigger": record.get("trigger"),
        "phase": target_phase,
        "result": summary,
        "error_kind": record.get("error_kind"),
    }


@dataclass(frozen=True, slots=True)
class _FinishDetails:
    preprocess_ok: int = 0
    preprocess_skipped: int = 0
    preprocess_failures: list[str] | None = None
    reuse: dict[str, object] | None = None
    drift: dict[str, object] | None = None


_DEFAULT_FINISH_DETAILS = _FinishDetails()


def record_finish(
    record_id: str,
    *,
    result: str | None = None,
    error: str | None = None,
    phase: Phase | None = None,
    details: _FinishDetails = _DEFAULT_FINISH_DETAILS,
) -> None:
    """Mark the record with *record_id* finished, in place.

    Sets ``finished_at`` and transitions ``phase`` to the given *phase*, or
    to ``"error"`` when *error* is given, otherwise ``"done"``. The ``result``
    field holds a short human-readable summary (the *error* string when erroring,
    else *result*). A no-op if the id is unknown (e.g. evicted past the bound).

    Args:
        record_id: The id returned by :func:`record_start`.
        result: Optional success summary (ignored when *error* is set).
        error: Optional error summary; its presence flips the phase to
            ``"error"`` if *phase* is not explicitly provided.
        phase: Optional explicit target phase (e.g. ``"cancelled"``).
        preprocess_ok: Count of files a document-preprocessing rule fed into
            the index this run, threaded onto the record so a working
            preprocess pipeline is positively visible through /jobs.
        preprocess_skipped: Count of files a document-preprocessing rule
            skipped this run, threaded onto the record so /jobs can surface it.
        preprocess_failures: ``"rel_path: reason"`` per skipped file, threaded
            onto the record so a client sees which files failed extraction and
            why - not just a count.
        reuse: Donor vector-reuse telemetry block for the run, or ``None``
            when reuse was disabled or the run never reached the encode
            pipeline.
        drift: Source-drift telemetry block for the run, or ``None`` when
            the run never opened a generation. Threaded onto the record
            because a remediated run succeeds, so drift volume is
            invisible to the circuit breaker by design and /jobs is where
            an operator sees it.
    """
    if phase is not None:
        target_phase = phase
    else:
        target_phase = "error" if error is not None else "done"
    summary = error if error is not None else result
    log_fields: dict[str, object] | None = None
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                log_fields = _finish_record(
                    record,
                    target_phase=target_phase,
                    summary=summary,
                    error=error,
                    details=details,
                )
                if log_fields is None:
                    return
                break
    if log_fields is not None:
        _persist_active_snapshot()
        level = logging.ERROR if target_phase == "error" else logging.INFO
        log_event(
            logger,
            "service.job",
            "finished",
            severity=level,
            fields=log_fields,
        )


def _copied_record(record: dict[str, object]) -> dict[str, object]:
    """Return one detached copy of a stored activity record.

    Shallow-copies the record and every nested mapping a caller could reach,
    so no consumer can mutate live registry state through a returned view.
    """
    item = dict(record)
    # Sampling state backs the rate estimate and is not part of the job
    # resource. Dropping it in the shared copier keeps it off every
    # projection built from a record, rather than relying on each caller
    # to remember to exclude it.
    item.pop(_PROGRESS_WINDOW_KEY, None)
    prog = record.get("progress")
    if isinstance(prog, dict):
        item["progress"] = dict(cast("dict[str, object]", prog))
    failures = record.get("preprocess_failures")
    if isinstance(failures, list):
        item["preprocess_failures"] = list(cast("list[object]", failures))
    initiator = record.get("initiator")
    if isinstance(initiator, dict):
        item["initiator"] = dict(cast("dict[str, object]", initiator))
    runtime = record.get("runtime")
    if isinstance(runtime, dict):
        item["runtime"] = dict(cast("dict[str, object]", runtime))
    resources = record.get("resources")
    if isinstance(resources, dict):
        resource_data = cast("dict[str, object]", resources)
        item["resources"] = {
            str(key): dict(cast("dict[str, object]", value))
            if isinstance(value, dict)
            else value
            for key, value in resource_data.items()
        }
    return item


def snapshot() -> list[dict[str, object]]:
    """Return a newest-first list of copied activity records.

    Each entry is a shallow copy of the stored record, and any progress
    nested dictionary is also copied, so callers cannot mutate live state.

    Returns:
        Newest-first list of record dicts.
    """
    with _lock:
        copied: list[dict[str, object]] = []
        for record in reversed(_records):
            copied.append(_copied_record(record))
        return copied


def _find_activity_record(job_id: str) -> dict[str, object] | None:
    """Return the newest copied activity record for one exact id."""
    with _lock:
        for record in reversed(_records):
            if record.get("id") == job_id:
                return _copied_record(record)
    return None


def _purge_activity_record(job_id: str) -> bool:
    """Drop every activity record for one exact id; report whether any went.

    The durable running-jobs snapshot is rewritten afterwards so a purged
    record cannot be re-registered as ``interrupted`` by the next startup.
    """
    with _lock:
        surviving = [record for record in _records if record.get("id") != job_id]
        removed = len(surviving) != len(_records)
        if removed:
            _records.clear()
            _records.extend(surviving)
    if removed:
        _persist_active_snapshot()
    return removed


def find_job(job_id: str) -> dict[str, object] | None:
    """Return one exact job resource from either registry, or ``None``.

    The jobs list is the union of canonical manager history and the activity
    records that outlive it, so resolving one id has to read the same union.
    Reading only the canonical half is how a row an operator can see becomes a
    row they cannot address.
    """
    snapshot_job = get_job_manager().get(job_id)
    if snapshot_job is not None:
        return snapshot_job.to_dict()
    return _find_activity_record(job_id)


def delete_job(job_id: str) -> JobOutcome:
    """Delete one terminal job resource from every registry that retains it.

    Canonical history and the activity records are two stores holding the same
    job under one id. Deleting from one alone leaves the other to surface the
    job again on the next list, so this owns both halves and is the only
    supported deletion path.
    """
    command = "delete"
    outcome = get_job_manager().delete(job_id)
    if outcome.status is not JobOutcomeStatus.ERROR:
        _purge_activity_record(job_id)
        return outcome
    if outcome.code != "job_not_found":
        return outcome

    record = _find_activity_record(job_id)
    if record is None:
        return outcome
    if not _activity_record_terminal(record):
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.ERROR,
            code="job_not_terminal",
            message="Nonterminal work must be cancelled before deletion.",
        )
    _purge_activity_record(job_id)
    return JobOutcome(
        command=command,
        status=JobOutcomeStatus.OK,
        code="job_deleted",
        message="The terminal job history was deleted.",
    )


def _activity_record_terminal(record: dict[str, object]) -> bool:
    """Return whether an activity record has reached a terminal phase."""
    return str(record.get("phase", "")).strip().lower() in TERMINAL_PHASES


def _job_snapshot_stalled(job: JobSnapshot, *, now: float) -> bool:
    """Classify a canonical job with the shared service stall threshold."""
    timestamps = job.timestamps
    if job.state in {JobState.PAUSING, JobState.CANCELLING}:
        requested = timestamps.control_requested_at
        acknowledged = timestamps.control_acknowledged_at
        return (
            requested is not None
            and (acknowledged is None or acknowledged < requested)
            and now - requested >= STALL_THRESHOLD_SECONDS
        )
    progress = job.progress
    return (
        job.state is JobState.RUNNING
        and progress is not None
        and progress.step != JobState.QUEUED.value
        and now - progress.last_updated >= STALL_THRESHOLD_SECONDS
    )


def _domain_job_snapshot(job: JobSnapshot, *, now: float) -> dict[str, object]:
    """Project one immutable canonical job onto the read-only status surface."""
    raw = job.to_dict()
    return {
        "generation": job.attempt.number,
        "job_id": job.id,
        "state": job.state.value,
        "desired_state": job.desired_state.value,
        "attempt": {
            "number": job.attempt.number,
            "parent_job_id": raw["parent_job_id"],
            "resumed_from_attempt": raw["resumed_from_attempt"],
            "resume_strategy": raw["resume_strategy"],
        },
        "error_kind": job.error_kind,
        "progress": raw["progress"],
        "resilience": raw["resilience"],
        "timestamps": {
            key: raw[key]
            for key in (
                "created_at",
                "state_changed_at",
                "started_at",
                "finished_at",
                "control_requested_at",
                "control_acknowledged_at",
                "admission_acquired_at",
            )
        },
        "stalled": _job_snapshot_stalled(job, now=now),
    }


def index_job_status(
    root: Path,
    *,
    manager: JobManager | None = None,
    now: float | None = None,
) -> dict[str, object]:
    """Return the latest canonical indexing generation for each public domain."""
    canonical_root = os.path.normcase(str(root.resolve()))
    observed_at = time.time() if now is None else now
    owner = get_job_manager() if manager is None else manager
    domains = tuple(source for source in JobSource if source.is_corpus)
    latest: dict[JobSource, JobSnapshot] = {}
    for job in owner.list_jobs():
        project_root = job.spec.project_root
        if job.spec.operation is not JobOperation.INDEX or project_root is None:
            continue
        if os.path.normcase(str(Path(project_root).resolve())) != canonical_root:
            continue
        current = latest.get(job.spec.source)
        if current is None or job.timestamps.created_at > current.timestamps.created_at:
            latest[job.spec.source] = job

    sources: dict[str, object] = {}
    degraded: list[dict[str, object]] = []
    for source in domains:
        job = latest.get(source)
        if job is None:
            sources[source.value] = None
            continue
        projected = _domain_job_snapshot(job, now=observed_at)
        sources[source.value] = projected
        reason = _job_degraded_reason(job, stalled=projected["stalled"] is True)
        if reason is not None:
            degraded.append(
                {
                    "source": source.value,
                    "job_id": job.id,
                    "reason": reason,
                    "error_kind": job.error_kind,
                }
            )
    return {"sources": sources, "degraded_reasons": degraded}


def _job_degraded_reason(job: JobSnapshot, *, stalled: bool) -> str | None:
    """Return the stable degradation reason for one latest domain job.

    This answers one question: is this project's index complete and worth
    trusting. An interrupted run degrades it as surely as a failed one - the
    attempt stopped partway, so the index it was building is missing whatever
    it had not reached - which is why the set here is deliberately wider than
    a liveness verdict on the service process, something an interrupted run
    does not impair. Narrowing it to failures alone would leave an operator
    querying a half-built index with nothing telling them so.
    """
    if stalled:
        return "stalled"
    if job.state in {JobState.FAILED, JobState.INTERRUPTED}:
        return job.state.value
    return None


def reset() -> None:
    """Clear all recorded in-memory activity (test-only).

    Deliberately leaves the persisted active-jobs snapshot alone so tests
    can simulate a daemon death (records gone, snapshot intact) and then
    exercise :func:`restore_interrupted`.
    """
    global _job_manager
    with _lock:
        _records.clear()
    with _manager_lock:
        _job_manager = None


class JobProgressReporter:
    """ProgressReporter that updates a specific in-flight job's progress."""

    def __init__(
        self,
        record_id: str,
        *,
        context: JobAttemptContext | None = None,
    ) -> None:
        self.record_id = record_id
        self._context = context
        self._step_name: str | None = None
        self._completed: int = 0
        self._total: int | None = None

    def phase_start(self, name: str, total: int | None) -> None:
        self._step_name = name
        self._total = total
        self._completed = 0
        self._publish(name, completed=0, total=total)

    def advance(self, n: int = 1) -> None:
        self._completed += n
        if self._step_name:
            self._publish(
                self._step_name,
                completed=self._completed,
                total=self._total,
            )

    def phase_end(self) -> None:
        pass

    def log(self, message: str) -> None:
        pass

    def _publish(self, step: str, *, completed: int, total: int | None) -> None:
        context = self._context
        if context is not None:
            outcome = context.update_progress(step, completed=completed, total=total)
            if outcome.code == "stale_attempt_ignored":
                return
        record_progress(self.record_id, step=step, completed=completed, total=total)


def _admit_index_job(
    root: Path,
    *,
    source: JobSource,
    clean: bool,
    initiator_kind: str,
) -> tuple[JobManager, str, bool]:
    manager = get_job_manager()
    resolved_root = root.resolve()
    command = "reindex_vault" if source is JobSource.VAULT else "reindex_codebase"
    requested_id = uuid.uuid4().hex
    outcome = manager.create(
        JobSpec(
            operation=JobOperation.INDEX,
            source=source,
            project_root=str(resolved_root),
            mode=JobMode.REBUILD if clean else JobMode.INCREMENTAL,
        ),
        JobInitiator(
            kind=initiator_kind,
            command=command,
            project_root=str(resolved_root),
        ),
        job_id=requested_id,
    )
    if outcome.status is JobOutcomeStatus.ERROR or outcome.job is None:
        raise RuntimeError(outcome.message)
    job_id = outcome.job.id
    created = outcome.code == "job_created"
    if created:
        record_start(
            source,
            "tool",
            project_root=resolved_root,
            command=command,
            initiator_kind=initiator_kind,
            _record_id=job_id,
        )
        record_progress(job_id, "queued")
    return manager, job_id, created


def _code_policy_indexer(root: Path) -> CodebaseIndexer:
    """Build a model-free indexer used only for policy preflight."""
    from .indexer import CodebaseIndexer

    resolved_root = root.resolve()
    return CodebaseIndexer(
        resolved_root,
        model=cast("Any", None),
        store=cast("Any", None),
    )


def validate_scoped_code_index_policy(
    root: Path,
    changed_paths: tuple[Path, ...] | frozenset[Path],
) -> CodeScopedPreflight:
    """Validate one exact scoped path set without a full-tree discovery."""
    return _code_policy_indexer(root).preflight_changed_paths(changed_paths)


def validate_code_index_policy(root: Path) -> CodeIndexPreflight:
    """Resolve and discover code work before a job mutates durable state."""
    return _code_policy_indexer(root).preflight_content()


def validate_code_support_profile(
    root: Path,
    preflight: CodeIndexPreflight | CodeScopedPreflight,
) -> SupportMeasurement:
    """Enforce the named code profile before any model or mutable resource."""
    import psutil

    from ._store_writes import probe_store_volume, probe_workspace_volume
    from .config import get_config
    from .index_profiles import (
        AdmissionEnvironment,
        IndexDomain,
        validate_profile_admission,
    )
    from .indexer._codebase_indexer import CodeIndexPreflight

    discovered = (
        preflight.scan.measurement
        if isinstance(preflight, CodeIndexPreflight)
        else preflight.measurement
    )
    cfg = get_config()
    measurement = replace(
        discovered,
        queue_bytes=int(cfg.index_queue_max_bytes),
        rss_bytes=int(psutil.Process(os.getpid()).memory_info().rss),
    )
    validate_profile_admission(
        cfg.index_support_profile,
        IndexDomain.CODE,
        measurement,
        AdmissionEnvironment(
            backend="server" if cfg.effective_server_mode() else "local",
            available_ram_bytes=int(psutil.virtual_memory().total),
            store_volume=probe_store_volume(root),
            workspace_volume=probe_workspace_volume(root),
        ),
    )
    return measurement


def validate_code_job_admission(root: Path) -> CodeIndexPreflight:
    """Return code authority only after policy and profile admission."""
    preflight = validate_code_index_policy(root)
    measurement = validate_code_support_profile(root, preflight)
    return replace(
        preflight,
        scan=replace(preflight.scan, measurement=measurement),
    )


def _document_policy_indexer(root: Path):
    """Build a model-free document indexer used only for policy preflight."""
    from .indexer import DocumentIndexer

    return DocumentIndexer(
        root.resolve(),
        model=cast("Any", None),
        store=cast("Any", None),
    )


def validate_document_index_policy(
    root: Path,
    *,
    run_control: RunControl = NO_RUN_CONTROL,
) -> DocumentIndexPreflight:
    """Resolve and discover document work before durable mutation."""
    return _document_policy_indexer(root).preflight_content(run_control=run_control)


def validate_scoped_document_index_policy(
    root: Path,
    changed_paths: tuple[Path, ...] | frozenset[Path],
    *,
    run_control: RunControl = NO_RUN_CONTROL,
) -> DocumentScopedPreflight:
    """Validate one exact document watcher scope without full discovery."""
    return _document_policy_indexer(root).preflight_changed_paths(
        changed_paths,
        run_control=run_control,
    )


def validate_document_support_profile(
    root: Path,
    preflight: DocumentIndexPreflight | DocumentScopedPreflight,
    *,
    run_control: RunControl = NO_RUN_CONTROL,
) -> None:
    """Enforce the named document profile before any model or mutable resource."""
    import psutil

    from ._store_writes import probe_store_volume, probe_workspace_volume
    from .config import get_config
    from .index_profiles import (
        AdmissionEnvironment,
        IndexDomain,
        SupportMeasurement,
        validate_profile_admission,
    )
    from .indexer._document_indexer import DocumentIndexPreflight

    paths = (
        preflight.files
        if isinstance(preflight, DocumentIndexPreflight)
        else preflight.changed_paths
    )
    run_control.checkpoint()
    source_files = 0
    source_bytes = 0
    for path in paths:
        run_control.checkpoint()
        if path.is_file():
            source_files += 1
            source_bytes += path.stat().st_size
        run_control.checkpoint()
    run_control.checkpoint()
    cfg = get_config()
    measurement = SupportMeasurement(
        source_files=source_files,
        source_bytes=source_bytes,
        queue_bytes=int(cfg.index_queue_max_bytes),
        rss_bytes=int(psutil.Process(os.getpid()).memory_info().rss),
    )
    validate_profile_admission(
        cfg.index_support_profile,
        IndexDomain.DOCUMENT,
        measurement,
        AdmissionEnvironment(
            backend="server" if cfg.effective_server_mode() else "local",
            available_ram_bytes=int(psutil.virtual_memory().total),
            store_volume=probe_store_volume(root),
            workspace_volume=probe_workspace_volume(root),
        ),
    )


def validate_document_job_admission(
    root: Path,
    *,
    run_control: RunControl = NO_RUN_CONTROL,
) -> DocumentIndexPreflight:
    """Return document authority only after policy and profile admission."""
    preflight = validate_document_index_policy(root, run_control=run_control)
    validate_document_support_profile(root, preflight, run_control=run_control)
    return preflight


def scan_code_index_preflight(root: Path) -> ContentScanResult:
    """Return bounded admission from the production structured scanner."""
    return validate_code_index_policy(root).scan


def _sync_legacy_started(snapshot: JobSnapshot) -> None:
    with _lock:
        for record in reversed(_records):
            if record.get("id") != snapshot.id:
                continue
            record["phase"] = "running"
            record["started_at"] = snapshot.timestamps.started_at
            record["finished_at"] = None
            record["result"] = None
            record["error_kind"] = None
            break
    record_progress(snapshot.id, "queued")


def _sync_legacy_finished(
    snapshot: JobSnapshot,
    duration_seconds: float,
    result: JobExecutionResult | None,
    error: BaseException | None,
) -> None:
    if snapshot.state is JobState.SUCCEEDED:
        record_finish(
            snapshot.id,
            result=snapshot.result,
            details=_FinishDetails(
                preprocess_ok=result.preprocess_ok if result is not None else 0,
                preprocess_skipped=(
                    result.preprocess_skipped if result is not None else 0
                ),
                preprocess_failures=(
                    list(result.preprocess_failures) if result is not None else None
                ),
                reuse=result.reuse if result is not None else None,
                drift=result.drift if result is not None else None,
            ),
        )
    elif snapshot.state is JobState.FAILED:
        record_finish(snapshot.id, error=snapshot.result or str(error or "job failed"))
    elif snapshot.state is JobState.INTERRUPTED:
        record_finish(
            snapshot.id,
            result=snapshot.result,
            phase="interrupted",
        )
    elif snapshot.state is JobState.CANCELLED:
        record_finish(snapshot.id, result=snapshot.result, phase="cancelled")
    else:
        with _lock:
            for record in reversed(_records):
                if record.get("id") != snapshot.id:
                    continue
                record["phase"] = snapshot.state.value
                record["finished_at"] = None
                record["result"] = snapshot.result
                break
        _persist_active_snapshot()

    for callback in tuple(_on_job_complete_callbacks):
        try:
            callback(duration_seconds)
        except Exception:
            logger.exception("Error in job complete callback")


def _bind_index_dispatch(
    manager: JobManager,
    job_id: str,
    *,
    code_preflight: CodeIndexPreflight | None,
    document_preflight: DocumentIndexPreflight | None,
    registry: ServiceRegistry | None = None,
) -> JobOutcome:
    """Attach one logical job to the production indexing implementation."""
    from .job_dispatch import IndexJobBinding, bind_index_job

    return bind_index_job(
        IndexJobBinding(
            manager=manager,
            job_id=job_id,
            registry=get_registry() if registry is None else registry,
            code_preflight=code_preflight,
            document_preflight=document_preflight,
            on_started=_sync_legacy_started,
            on_finished=_sync_legacy_finished,
        )
    )


def _prepare_index_job_activation(
    manager: JobManager,
    snapshot: JobSnapshot,
    code_preflight: CodeIndexPreflight | None,
    document_preflight: DocumentIndexPreflight | None,
    registry: ServiceRegistry | None,
) -> JobOutcome:
    """Publish legacy observability and bind execution outside the event loop."""
    root = Path(snapshot.spec.project_root) if snapshot.spec.project_root else None
    source = snapshot.spec.source
    trigger: Trigger = (
        cast("Trigger", snapshot.initiator.kind)
        if snapshot.initiator.kind in {"watcher", "schedule"}
        else "tool"
    )
    record_start(
        source,
        trigger,
        project_root=root,
        command=snapshot.initiator.command,
        initiator_kind=snapshot.initiator.kind,
        _record_id=snapshot.id,
    )
    record_progress(snapshot.id, snapshot.state.value)
    return _bind_index_dispatch(
        manager,
        snapshot.id,
        code_preflight=code_preflight,
        document_preflight=document_preflight,
        registry=registry,
    )


def _fail_index_job_activation(
    manager: JobManager,
    job_id: str,
    message: str,
) -> None:
    """Durably fail an unstarted job and finish its legacy record off-loop."""
    manager.fail_unstarted(job_id, result=message)
    record_finish(job_id, error=message)


async def activate_index_job(
    outcome: JobOutcome,
    *,
    code_preflight: CodeIndexPreflight | None,
    document_preflight: DocumentIndexPreflight | None = None,
    registry: ServiceRegistry | None = None,
) -> JobOutcome:
    """Bind and dispatch one newly admitted job without blocking its event loop.

    Replayed or deduplicated creation outcomes already refer to an activated
    resource and are returned unchanged. Newly created paused jobs are bound
    but remain inert until their desired state changes to ``running``. Code
    admission must be validated before durable creation. Activation accepts the
    exact domain authority that admitted the resource; runnable attempts then
    rediscover so paused, retried, and restored work cannot use stale scope.
    """
    snapshot = outcome.job
    if (
        outcome.status is JobOutcomeStatus.ERROR
        or snapshot is None
        or outcome.code not in {"job_created", "job_retry_created"}
    ):
        return outcome

    if snapshot.spec.source is JobSource.CODE and code_preflight is None:
        raise RuntimeError("code job activation requires its validated preflight")
    if snapshot.spec.source is JobSource.DOCUMENT and document_preflight is None:
        raise RuntimeError("document job activation requires its validated preflight")
    manager = get_job_manager()
    bound = await _run_in_thread(
        _prepare_index_job_activation,
        manager,
        snapshot,
        code_preflight,
        document_preflight,
        registry,
    )
    if bound.status is JobOutcomeStatus.ERROR:
        await _run_in_thread(
            _fail_index_job_activation,
            manager,
            snapshot.id,
            bound.message,
        )
        return bound
    if snapshot.desired_state is DesiredJobState.PAUSED:
        return outcome

    dispatched = await manager.dispatch_async(snapshot.id)
    if dispatched.status is not JobOutcomeStatus.ERROR:
        return replace(outcome, job=dispatched.job)
    if dispatched.code == "dispatch_stopped":
        return outcome
    await _run_in_thread(
        _fail_index_job_activation,
        manager,
        snapshot.id,
        dispatched.message,
    )
    return dispatched


def restore_managed_jobs(*, registry: ServiceRegistry) -> tuple[int, int]:
    """Rebind durable indexing jobs and dispatch only runnable queued work.

    Returns:
        ``(bound, dispatched)`` counts for lifecycle diagnostics.
    """
    manager = get_job_manager()
    restored = manager.active()
    for snapshot in restored:
        code_preflight = None
        bound = _bind_index_dispatch(
            manager,
            snapshot.id,
            code_preflight=code_preflight,
            document_preflight=None,
            registry=registry,
        )
        if bound.status is JobOutcomeStatus.ERROR:
            raise RuntimeError(bound.message)
    dispatched = 0
    for snapshot in restored:
        if (
            snapshot.state is JobState.QUEUED
            and snapshot.desired_state is DesiredJobState.RUNNING
        ):
            outcome = manager.dispatch(snapshot.id)
            if outcome.status is JobOutcomeStatus.ERROR:
                raise RuntimeError(outcome.message)
            dispatched += 1
    return len(restored), dispatched


def start_reindex_vault(
    root: Path, clean: bool, *, initiator_kind: str = "service"
) -> str:
    """Start a background vault reindexing task and return the job_id."""
    manager, job_id, created = _admit_index_job(
        root,
        source=JobSource.VAULT,
        clean=clean,
        initiator_kind=initiator_kind,
    )
    if not created:
        return job_id

    bound = _bind_index_dispatch(
        manager,
        job_id,
        code_preflight=None,
        document_preflight=None,
    )
    if bound.status is JobOutcomeStatus.ERROR:
        manager.fail_unstarted(job_id, result=bound.message)
        record_finish(job_id, error=bound.message)
        raise RuntimeError(bound.message)
    dispatched = manager.dispatch(job_id)
    if dispatched.status is JobOutcomeStatus.ERROR:
        if dispatched.code == "dispatch_stopped":
            return job_id
        manager.fail_unstarted(job_id, result=dispatched.message)
        record_finish(job_id, error=dispatched.message)
        raise RuntimeError(dispatched.message)
    return job_id


def start_reindex_codebase(
    root: Path,
    clean: bool,
    *,
    initiator_kind: str = "service",
) -> str:
    """Start a background codebase reindexing task and return the job_id."""
    code_preflight = validate_code_job_admission(root)
    manager, job_id, created = _admit_index_job(
        root,
        source=JobSource.CODE,
        clean=clean,
        initiator_kind=initiator_kind,
    )
    if not created:
        return job_id

    bound = _bind_index_dispatch(
        manager,
        job_id,
        code_preflight=code_preflight,
        document_preflight=None,
    )
    if bound.status is JobOutcomeStatus.ERROR:
        manager.fail_unstarted(job_id, result=bound.message)
        record_finish(job_id, error=bound.message)
        raise RuntimeError(bound.message)
    dispatched = manager.dispatch(job_id)
    if dispatched.status is JobOutcomeStatus.ERROR:
        if dispatched.code == "dispatch_stopped":
            return job_id
        manager.fail_unstarted(job_id, result=dispatched.message)
        record_finish(job_id, error=dispatched.message)
        raise RuntimeError(dispatched.message)
    return job_id
