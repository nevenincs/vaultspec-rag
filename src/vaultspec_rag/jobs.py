"""In-flight activity registry and background task worker for index/reindex jobs.

A thread-safe, bounded record of every index/reindex activity the service performs,
along with async task execution helpers for background reindexing.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Any, Literal, cast, get_args

from anyio.to_thread import run_sync as _run_in_thread

from ._job_errors import STALL_THRESHOLD_SECONDS, classify_error_text
from ._runtime_identity import process_identity_fields
from .config._settings import managed_status_dir
from .job_control import NO_RUN_CONTROL
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

    import psutil

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
    from .job_manager.manager import JobManager
    from .service import ServiceRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "TERMINAL_PHASES",
    "DegradationInputs",
    "JobProgressReporter",
    "activate_index_job",
    "active_index_support_profiles",
    "count",
    "degradation_evidence",
    "delete_job",
    "find_job",
    "flag",
    "get_job_manager",
    "gpu_pressure_snapshot",
    "index_job_status",
    "machine_pressure",
    "mapping",
    "measurement",
    "progress_rates",
    "record_encode_bucket",
    "record_encode_oom",
    "record_finish",
    "record_forward_entry",
    "record_forward_exit",
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
    "start_reindex_documents",
    "start_reindex_vault",
    "telemetry_block",
    "text",
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
    from .config._settings import get_config
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
# Run-spanning throughput baseline. The window above answers "how fast right
# now" and, by construction, holds only the last seconds of a fast step: a run
# whose throughput collapses refills it with the collapsed rate within
# seconds, after which nothing on the record remembers the run was ever
# faster. The baseline is the second reading that keeps a collapse visible.
# The window rate is retained at a coarse interval across the step, so the
# median of what the run has actually sustained survives long after the
# window has moved on. Derived from the samples already taken - no second
# sampler - and bounded by both count and spacing, so an hour of history
# costs one small deque of floats per job.
_PROGRESS_RATE_HISTORY_KEY = "progress_rate_history"
_PROGRESS_RATE_HISTORY_SAMPLES = 120
_PROGRESS_RATE_HISTORY_MIN_INTERVAL_SECONDS = 30.0
# A median over a handful of observations describes a moment, not a run.
# Eight spaced observations are four minutes of sustained reporting, which is
# the point at which comparing the current rate against the run's own history
# says something an operator can act on instead of flapping on one slow slice.
_PROGRESS_RATE_HISTORY_MIN_OBSERVATIONS = 8
# Mid-step progress writes are throttled per output, never gated on the step
# name changing: a step-name gate admits exactly one write per phase, at the
# instant the counter is zero by construction, so no advancing count ever
# reaches the log or the durable snapshot. The two outputs want different
# rates. The log line is one formatted string and ticks every few seconds,
# giving a minutes-long phase a continuous signal at a bounded volume
# (~12 lines/minute regardless of how fast the step reports). The snapshot
# is an fsynced atomic file write, so it earns a longer interval: half a
# minute bounds how much restored progress a daemon death can lose while
# capping durable writes at two per minute per job. A step transition still
# writes both immediately.
_PROGRESS_LOG_MIN_INTERVAL_SECONDS = 5.0
_PROGRESS_PERSIST_MIN_INTERVAL_SECONDS = 30.0
# Last write times for the throttles above. Rides on the record like the
# rate window, and is dropped from every copied projection the same way.
_PROGRESS_EMIT_KEY = "progress_emitted"
# Bounded backend-liveness probe for degradation evidence. The count runs on
# its own daemon thread and the caller waits at most the timeout, so a dead or
# wedged backend can never wedge the jobs surface that is reporting on it. The
# short cache keeps a polling operator view (the TUI refreshes every couple of
# seconds) from stacking one probe thread per poll against a backend that has
# stopped answering.
_BACKEND_PROBE_TIMEOUT_SECONDS = 2.0
_BACKEND_PROBE_CACHE_SECONDS = 5.0
_backend_probe_lock = threading.Lock()
_backend_probe_cache: dict[tuple[str, str], tuple[float, dict[str, object]]] = {}
# The whole-machine GPU pressure reading served on the jobs listing, held a
# few seconds so a polling operator view does not pay the probe per poll.
_GPU_SNAPSHOT_CACHE_SECONDS = 5.0
_gpu_snapshot_lock = threading.Lock()
_gpu_snapshot_cache: tuple[float, dict[str, object]] | None = None
# The device-load admission reading served on the jobs listing, held the same
# few seconds and by the same rationale: the same open operator views poll
# this route at the same cadence as the GPU pressure block above, and a
# per-poll device read is exactly the cost that block's own cache exists to
# avoid.
_DEVICE_LOAD_SNAPSHOT_CACHE_SECONDS = 5.0
_device_load_snapshot_lock = threading.Lock()
_device_load_snapshot_cache: tuple[float, dict[str, object] | None] | None = None
# Service-process CPU utilisation for degradation evidence. ``cpu_percent``
# measures the interval since its own previous call, so one persistent
# process handle is kept and the reading is cached for a few seconds: polls
# inside the window reuse the reading, and the gap between real samples is
# what gives the measurement a meaningful span.
_CPU_SNAPSHOT_CACHE_SECONDS = 5.0
_cpu_snapshot_lock = threading.Lock()
_cpu_snapshot_cache: tuple[float, dict[str, object]] | None = None
_cpu_probe_process: psutil.Process | None = None
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
                manager = get_registry().create_job_manager()
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
                "pid": cast("dict[str, object]", runtime).get("pid")
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
        # The record answers "why did this stop" and "who started it"; the
        # log line must too, or the operator reading the log sees a bare
        # interruption with no cause, no attribution, and no sense of how
        # far the job had come or how long it had been running.
        initiator = (
            cast("dict[str, object]", raw_initiator)
            if isinstance(raw_initiator := record.get("initiator"), dict)
            else {}
        )
        progress = (
            cast("dict[str, object]", raw_progress)
            if isinstance(raw_progress := record.get("progress"), dict)
            else {}
        )
        log_event(
            logger,
            "service.job",
            "interrupted",
            severity=logging.WARNING,
            job_id=str(record["id"]),
            source=record.get("source"),
            trigger=record.get("trigger"),
            phase="interrupted",
            result=record.get("result"),
            initiator_kind=initiator.get("kind"),
            command=initiator.get("command"),
            project_root=initiator.get("project_root"),
            started_at=record.get("started_at"),
            step=progress.get("step"),
            completed=progress.get("completed"),
            total=progress.get("total"),
        )
    # The prior life's snapshot is consumed; persist the (empty) current
    # running set so a second restart does not re-restore the same jobs.
    _persist_active_snapshot()
    return restored


def resource_snapshot() -> dict[str, object]:
    """Return a best-effort current resource snapshot for the service process."""
    from .memory_probe import current_cuda_mib, current_rss_mib

    cuda_allocated_mib, cuda_reserved_mib = current_cuda_mib()
    return {
        "rss_mib": round(current_rss_mib(), 1),
        "cuda_allocated_mib": round(cuda_allocated_mib, 1),
        "cuda_reserved_mib": round(cuda_reserved_mib, 1),
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
    samples: deque[tuple[float, int]] = (
        cast("deque[tuple[float, int]]", window)
        if isinstance(window, deque)
        else deque(maxlen=_PROGRESS_WINDOW_SAMPLES)
    )
    if previous_step != step or (samples and completed < samples[-1][1]):
        samples.clear()
        # The baseline describes one step's sustained throughput, so it is
        # discarded wherever the window is: a rate carried across a step
        # change or a replay reset would be a baseline for different work.
        record.pop(_PROGRESS_RATE_HISTORY_KEY, None)
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
    _retain_rate_observation(record, at=at)


def _retain_rate_observation(record: dict[str, object], *, at: float) -> None:
    """Retain the current window rate as one run-baseline observation.

    Reads the window the caller has just updated, so the baseline costs no
    second measurement. Observations are spaced by interval rather than by
    report, so a step reporting hundreds of times a second contributes at the
    same cadence as one reporting every few seconds, and the deque bounds how
    much of the run is remembered.
    """
    window = record.get(_PROGRESS_WINDOW_KEY)
    if not isinstance(window, deque):
        return
    rate = _window_rate(cast("deque[tuple[float, int]]", window))
    if rate is None:
        return
    raw_history = record.get(_PROGRESS_RATE_HISTORY_KEY)
    history: deque[tuple[float, float]] = (
        cast("deque[tuple[float, float]]", raw_history)
        if isinstance(raw_history, deque)
        else deque(maxlen=_PROGRESS_RATE_HISTORY_SAMPLES)
    )
    if history and at - history[-1][0] < _PROGRESS_RATE_HISTORY_MIN_INTERVAL_SECONDS:
        return
    history.append((at, rate))
    record[_PROGRESS_RATE_HISTORY_KEY] = history


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


def _record_window_rate(record: dict[str, object]) -> float | None:
    """The windowed completion rate *record* holds (caller holds the lock)."""
    window = record.get(_PROGRESS_WINDOW_KEY)
    if not isinstance(window, deque):
        return None
    return _window_rate(cast("deque[tuple[float, int]]", window))


def _record_baseline_rate(record: dict[str, object]) -> float | None:
    """The median of *record*'s retained observations (caller holds the lock).

    The run's own baseline, against which the windowed rate says whether
    throughput has collapsed. The median rather than the mean because a run
    passes through regimes and a single stalled window must not move the
    reference.
    """
    history = record.get(_PROGRESS_RATE_HISTORY_KEY)
    if not isinstance(history, deque):
        return None
    rates = [rate for _at, rate in cast("deque[tuple[float, float]]", history)]
    if len(rates) < _PROGRESS_RATE_HISTORY_MIN_OBSERVATIONS:
        return None
    return median(rates)


def progress_rates(record_id: str) -> tuple[float | None, float | None]:
    """Return one job's windowed rate and its own baseline, under one read.

    What the job is achieving now and the median of what it has sustained on
    this step are two readings of the same record, written by the same
    reporter thread. Taken under one lock acquisition they describe one
    moment, so the ratio between them is a number the record actually held;
    taken separately they can straddle a write, and the comparison would then
    describe no state the job was ever in.

    Either member is ``None`` where the service declines to state it: the job
    is unknown, has not reported twice within one step, has not advanced, or
    has not yet spaced enough observations for a median to describe a run
    rather than a moment. Neither ever means zero.
    """
    with _lock:
        for record in reversed(_records):
            if record["id"] != record_id:
                continue
            return _record_window_rate(record), _record_baseline_rate(record)
    return None, None


def record_progress(
    record_id: str,
    step: str,
    completed: int = 0,
    total: int | None = None,
    *,
    now: float | None = None,
) -> None:
    """Update progress for an active running job.

    Every call updates the in-memory record. The log line and the durable
    snapshot are written immediately on a step transition and are otherwise
    rate-limited independently, so an advancing counter stays visible in the
    log and survives a daemon death without paying an fsync per batch.

    Args:
        record_id: The id returned by :func:`record_start`.
        step: Name of the current phase/step (e.g. "queued", "discover", "embed").
        completed: Count of items processed so far in this step.
        total: Total number of items to process, if known.
        now: The moment the write throttles are judged against; defaults to
            the wall clock. Injectable so throttling is testable without
            sleeping.
    """
    log_fields: dict[str, object] | None = None
    persist = False
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                progress = record.get("progress")
                progress_step = None
                if isinstance(progress, dict):
                    progress_data = cast("dict[str, object]", progress)
                    progress_step = progress_data.get("step")
                moment = time.time() if now is None else now
                record["progress"] = {
                    "step": step,
                    "completed": completed,
                    "total": total,
                    "last_updated": moment,
                }
                _sample_progress(
                    record,
                    step=step,
                    previous_step=progress_step,
                    completed=completed,
                    at=moment,
                )
                step_changed = progress_step != step
                raw_emitted = record.get(_PROGRESS_EMIT_KEY)
                emitted = (
                    cast("dict[str, float]", raw_emitted)
                    if isinstance(raw_emitted, dict)
                    else {}
                )
                last_logged = emitted.get("logged_at")
                if (
                    step_changed
                    or last_logged is None
                    or moment - last_logged >= _PROGRESS_LOG_MIN_INTERVAL_SECONDS
                ):
                    emitted["logged_at"] = moment
                    log_fields = {
                        "job_id": record_id,
                        "source": record.get("source"),
                        "trigger": record.get("trigger"),
                        "phase": record.get("phase"),
                        "step": step,
                        "completed": completed,
                        "total": total,
                    }
                last_persisted = emitted.get("persisted_at")
                persist = (
                    step_changed
                    or last_persisted is None
                    or moment - last_persisted >= _PROGRESS_PERSIST_MIN_INTERVAL_SECONDS
                )
                if persist:
                    emitted["persisted_at"] = moment
                record[_PROGRESS_EMIT_KEY] = emitted
                break
    if persist:
        _persist_active_snapshot()
    if log_fields is not None:
        log_event(logger, "service.job", "progress", fields=log_fields)


def record_forward_entry(record_id: str, *, ordinal: int, items: int) -> None:
    """Publish that the encode thread is entering one model forward pass.

    Written before the forward begins, so a pass that runs for minutes under
    GPU contention is visible as an in-flight forward (``exited_at`` still
    ``None``) rather than as silence. Progress only ticks at slice
    boundaries; this is the only signal inside one. The calling thread's
    identity is recorded so the read surface can report whether the encode
    thread is still alive while the pass looks stuck.

    *items* is the slice's own item count, and means the same thing at
    every boundary the window is reopened at, so a reader who finds the
    window open never has to ask which moment the number was written at.
    Sub-slice progress through those items is a different quantity and is
    published as its own pair on the encode block.
    """
    now = time.time()
    thread = threading.current_thread()
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                record["forward"] = {
                    "entered_at": now,
                    "exited_at": None,
                    "slice_ordinal": ordinal,
                    "items": items,
                    "thread_ident": thread.ident,
                    "thread_name": thread.name,
                }
                break


def record_forward_exit(record_id: str, *, ordinal: int, items: int) -> None:
    """Close the in-flight forward window ``record_forward_entry`` opened."""
    now = time.time()
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                forward = record.get("forward")
                if isinstance(forward, dict):
                    data = cast("dict[str, object]", forward)
                    data["exited_at"] = now
                    data["slice_ordinal"] = ordinal
                    data["items"] = items
                break


def _encode_block(record: dict[str, object]) -> dict[str, object]:
    """Return one record's encode state, creating it absent (caller locked).

    Every member starts absent rather than at a plausible-looking value: a
    budget of zero and a budget nobody has reported are different findings,
    and only the retry count has a truthful starting value.
    """
    existing = record.get("encode")
    if isinstance(existing, dict):
        return cast("dict[str, object]", existing)
    block: dict[str, object] = {
        "token_budget": None,
        "bucket_items": None,
        "items_done": None,
        "items_total": None,
        "oom_count": 0,
    }
    record["encode"] = block
    return block


def record_encode_bucket(
    record_id: str,
    *,
    token_budget: int | None,
    bucket_items: int | None,
    items_done: int | None,
    items_total: int | None,
) -> None:
    """Publish what one encode-bucket boundary observed.

    *token_budget* is the current per-batch token ceiling and *bucket_items*
    the size of the batch it most recently produced. Together they are what
    turns a collapsed throughput reading into an attributable cause: a run
    encoding a handful of items per batch is bounded by its own memory
    ceiling, not by a stuck forward pass.

    *items_done* and *items_total* are the encode call's own sub-slice
    progress, and are published as a pair because neither means anything
    alone: a lone completed count reads as a size to whoever renders it,
    which is the ambiguity that put the climb here instead of on the
    forward window's slice-scoped item count.
    """
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                block = _encode_block(record)
                block["token_budget"] = token_budget
                block["bucket_items"] = bucket_items
                block["items_done"] = items_done
                block["items_total"] = items_total
                break


def record_encode_oom(record_id: str) -> None:
    """Count one out-of-memory encode retry against this job.

    The count is per job and never resets within a run: a ceiling that
    collides repeatedly is the finding, and a gauge that forgets the earlier
    collisions cannot show it.
    """
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                block = _encode_block(record)
                count = block.get("oom_count")
                block["oom_count"] = (
                    count + 1
                    if isinstance(count, int) and not isinstance(count, bool)
                    else 1
                )
                break


def telemetry_block(record_id: str, name: str) -> dict[str, object] | None:
    """Return a detached copy of one job's newest *name* telemetry block.

    ``forward`` is the newest forward-pass window, ``encode`` the budget,
    sub-slice progress and retry state the encode stage is working under.
    Both are read the same way, so they are read by the same code: a
    hardening applied to one block that skipped the other would be a
    difference nothing in the record justifies.

    ``None`` means the job is unknown or its run never reported that block.
    The read surface treats that as no signal at all - never as a stall, and
    never as a budget of nothing.
    """
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                block = record.get(name)
                if isinstance(block, dict):
                    return dict(cast("dict[str, object]", block))
                return None
    return None


def _finish_record(
    record: dict[str, object],
    *,
    target_phase: str,
    summary: str | None,
    error: str | None,
    details: FinishDetails,
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
class FinishDetails:
    preprocess_ok: int = 0
    preprocess_skipped: int = 0
    preprocess_failures: list[str] | None = None
    reuse: dict[str, object] | None = None
    drift: dict[str, object] | None = None


_DEFAULT_FINISH_DETAILS = FinishDetails()


def record_finish(
    record_id: str,
    *,
    result: str | None = None,
    error: str | None = None,
    phase: Phase | None = None,
    details: FinishDetails = _DEFAULT_FINISH_DETAILS,
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
    # Sampling and write-throttle state back the rate estimate and the
    # progress write cadence; neither is part of the job resource. Dropping
    # them in the shared copier keeps them off every projection built from a
    # record, rather than relying on each caller to remember to exclude them.
    item.pop(_PROGRESS_WINDOW_KEY, None)
    item.pop(_PROGRESS_RATE_HISTORY_KEY, None)
    item.pop(_PROGRESS_EMIT_KEY, None)
    prog = record.get("progress")
    if isinstance(prog, dict):
        item["progress"] = dict(cast("dict[str, object]", prog))
    forward = record.get("forward")
    if isinstance(forward, dict):
        item["forward"] = dict(cast("dict[str, object]", forward))
    encode = record.get("encode")
    if isinstance(encode, dict):
        item["encode"] = dict(cast("dict[str, object]", encode))
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


def _forward_evidence(
    forward: dict[str, object] | None,
    *,
    now: float,
) -> dict[str, object]:
    """Shape one job's forward telemetry into its evidence block.

    ``age_seconds`` is how long the current forward has been running when one
    is in flight, otherwise how long ago the last one finished. Thread
    liveness distinguishes a starved-but-alive encode (thread alive, forward
    in flight) from a genuinely dead worker.
    """
    if forward is None:
        return {
            "in_flight": False,
            "age_seconds": None,
            "slice_ordinal": None,
            "items": None,
            "thread_alive": None,
        }
    entered = forward.get("entered_at")
    exited = forward.get("exited_at")
    entered_at = float(entered) if isinstance(entered, int | float) else None
    exited_at = float(exited) if isinstance(exited, int | float) else None
    in_flight = entered_at is not None and exited_at is None
    reference = entered_at if in_flight else exited_at
    ident = forward.get("thread_ident")
    thread_alive = (
        any(thread.ident == ident for thread in threading.enumerate())
        if isinstance(ident, int) and not isinstance(ident, bool)
        else None
    )
    return {
        "in_flight": in_flight,
        "age_seconds": max(0.0, now - reference) if reference is not None else None,
        "slice_ordinal": forward.get("slice_ordinal"),
        "items": forward.get("items"),
        "thread_alive": thread_alive,
    }


def gpu_pressure_snapshot(*, now: float | None = None) -> dict[str, object]:
    """The machine-wide GPU pressure block, cached for a few seconds.

    The jobs listing is polled every couple of seconds by every open operator
    view, and each poll would otherwise pay the probe again for a reading
    that cannot meaningfully change between polls. The block is the same
    shape the degradation evidence carries, sampled through the same
    read-only probe, so a header and an evidence block can never disagree
    about what was measured.

    Args:
        now: The moment cache freshness is judged against; defaults to the
            wall clock. Injectable so freshness is testable without sleeping.

    Returns:
        ``{"available", "utilization_percent", "memory_used_mib",
        "memory_total_mib"}``, every measurement ``None`` where this host
        cannot measure it. Callers receive a copy; mutating it cannot
        poison the cache.
    """
    global _gpu_snapshot_cache
    moment = time.time() if now is None else now
    with _gpu_snapshot_lock:
        cached = _gpu_snapshot_cache
        if (
            cached is not None
            and 0.0 <= moment - cached[0] < _GPU_SNAPSHOT_CACHE_SECONDS
        ):
            return dict(cached[1])
    snapshot = _gpu_evidence()
    with _gpu_snapshot_lock:
        _gpu_snapshot_cache = (moment, snapshot)
    return dict(snapshot)


def device_load_snapshot(*, now: float | None = None) -> dict[str, object] | None:
    """The device-load admission verdict, cached the same way as the GPU block.

    A different fact from :func:`gpu_pressure_snapshot`: that block reports
    utilization and memory *usage*, sampled purely for display and for the
    hysteresis-folded ``pressure`` tier beside it - nothing acts on either.
    This is the synchronous, fail-fast predicate a model load is actually
    admitted or refused against right now, against the configured floor. The
    two must stay visibly distinct so a later reader does not collapse a
    display reading into the load-bearing gate, or vice versa.

    Cached rather than read fresh per poll for the same reason
    :func:`gpu_pressure_snapshot` is: the jobs listing is polled every couple
    of seconds by every open operator view, and this route must not turn each
    of those polls into its own device probe.

    Args:
        now: The moment cache freshness is judged against; defaults to the
            wall clock. Injectable so freshness is testable without sleeping.

    Returns:
        The ``device_load`` wire shape (``free_mib``, ``total_mib``,
        ``floor_mib``, ``admitted``, ``reason``), or ``None`` when this host's
        reading could not be taken - absent, never raised, so an older reader
        expecting no such key is unaffected. Callers receive a copy; mutating
        it cannot poison the cache.
    """
    global _device_load_snapshot_cache
    moment = time.time() if now is None else now
    with _device_load_snapshot_lock:
        cached = _device_load_snapshot_cache
        if (
            cached is not None
            and 0.0 <= moment - cached[0] < _DEVICE_LOAD_SNAPSHOT_CACHE_SECONDS
        ):
            return dict(cached[1]) if cached[1] is not None else None
    from ._gpu_admission import device_load_reading

    reading = device_load_reading()
    with _device_load_snapshot_lock:
        _device_load_snapshot_cache = (moment, reading)
    return dict(reading) if reading is not None else None


def _gpu_evidence() -> dict[str, object]:
    """Sample machine-wide GPU pressure through the read-only probe.

    ``available`` is ``False`` on a torch-free host, a CPU-only build, or a
    process whose CUDA context is not initialized - the probe reports absence
    rather than raising or initializing anything.
    """
    from .memory_probe import cuda_pressure

    utilization, used_mib, total_mib = cuda_pressure()
    return {
        "available": total_mib is not None,
        "utilization_percent": utilization,
        "memory_used_mib": round(used_mib, 1) if used_mib is not None else None,
        "memory_total_mib": round(total_mib, 1) if total_mib is not None else None,
    }


def _process_cpu_evidence(*, now: float | None = None) -> dict[str, object]:
    """Sample this process's CPU utilisation for the evidence block.

    A CPU- or I/O-bound step runs no forward pass, so during one the encode
    window is structurally silent and its absence proves nothing. The service
    process burning CPU is the liveness signal that is valid in every step,
    and this is where it is measured. ``utilization_percent`` is relative to
    one core and exceeds 100 when the process uses several. The first sample
    only primes the counter and reports no reading rather than a fabricated
    zero; ``available`` is ``False`` only when the process cannot be probed
    at all.

    Args:
        now: The moment cache freshness is judged against; defaults to the
            wall clock. Injectable so freshness is testable without sleeping.
    """
    global _cpu_snapshot_cache, _cpu_probe_process
    moment = time.time() if now is None else now
    with _cpu_snapshot_lock:
        cached = _cpu_snapshot_cache
        if (
            cached is not None
            and 0.0 <= moment - cached[0] < _CPU_SNAPSHOT_CACHE_SECONDS
        ):
            return dict(cached[1])
        import psutil

        reading: dict[str, object]
        try:
            process = _cpu_probe_process
            primed = process is not None
            if process is None:
                process = psutil.Process()
                _cpu_probe_process = process
            percent = process.cpu_percent(interval=None)
        except Exception:
            reading = {"available": False, "utilization_percent": None}
        else:
            reading = {
                "available": True,
                "utilization_percent": round(float(percent), 1) if primed else None,
            }
        _cpu_snapshot_cache = (moment, reading)
        return dict(reading)


def _forward_pass_expected(step: str | None) -> bool | None:
    """Whether the reported step runs model forward passes at all.

    Encoding steps carry "embed" in their published names; every other step
    is CPU- or I/O-bound work (scanning, hashing, purging, metadata writes)
    in which an absent forward pass is the expected shape of the phase, not
    evidence of a stall. ``None`` when the job has not reported a step, so a
    renderer keeps the conservative reading rather than suppressing the
    signal on no information.
    """
    if not isinstance(step, str) or not step.strip():
        return None
    return "embed" in step


def _probe_backend_once(root: Path, source: str) -> dict[str, object]:
    """Run one time-bounded store count against *root*'s backend.

    The count is the cheapest read that proves the whole write path's
    substrate is answering: it reaches the same client, collection, and
    retry policy the indexer writes through. A warm project slot's store is
    reused; the probe never runs on the caller's thread past the bound.
    """
    outcome: dict[str, object] = {}
    started = time.perf_counter()

    def _count() -> None:
        try:
            with get_registry().lease_store(root) as store:
                if source == "code":
                    store.count_code()
                elif source == "document":
                    store.count_document()
                else:
                    store.count()
        except Exception as exc:  # any backend failure is the finding itself
            outcome["alive"] = False
            outcome["detail"] = str(exc) or type(exc).__name__
        else:
            outcome["alive"] = True
            outcome["detail"] = None
        outcome["latency_seconds"] = round(time.perf_counter() - started, 3)

    probe = threading.Thread(target=_count, name="jobs-backend-probe", daemon=True)
    probe.start()
    probe.join(_BACKEND_PROBE_TIMEOUT_SECONDS)
    if probe.is_alive():
        # The thread may still settle later; never read its dict again. An
        # unanswered probe is reported as unknown, not dead: the backend may
        # be alive but blocked behind a long write.
        return {
            "alive": None,
            "latency_seconds": round(time.perf_counter() - started, 3),
            "detail": (f"no response within {_BACKEND_PROBE_TIMEOUT_SECONDS:.1f}s"),
        }
    return outcome


def _backend_evidence(project_root: str | None, source: str) -> dict[str, object]:
    """Return cached-or-fresh backend liveness for one job's store."""
    if not project_root:
        return {
            "alive": None,
            "latency_seconds": None,
            "detail": "the job records no project root to probe",
        }
    key = (os.path.normcase(project_root), source)
    now = time.monotonic()
    with _backend_probe_lock:
        cached = _backend_probe_cache.get(key)
        if cached is not None and now - cached[0] < _BACKEND_PROBE_CACHE_SECONDS:
            return dict(cached[1])
    result = _probe_backend_once(Path(project_root), source)
    with _backend_probe_lock:
        _backend_probe_cache[key] = (time.monotonic(), result)
    return dict(result)


def count(value: object) -> int | None:
    """Read one published value as a whole, non-negative count.

    The counted-work half of the reader pair :func:`measurement` completes,
    and it carries the same contract: a count is a published *quantity*, so
    ``bool`` and a negative are both malformed rather than readings. A
    ``float`` is refused outright rather than truncated, because a
    fractional count is a malformed reading and not a rounding question - a
    cap of ``3.7`` is a broken field, not "3".
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def measurement(value: object) -> float | None:
    """Read one published value as a NON-NEGATIVE measured quantity.

    The one reader every surface uses for a numeric field the service may
    not have measured: the evidence blocks here, the jobs presentation, the
    status pane, and the route projection all narrow the same way, so a
    value one of them would refuse can never read as a number in another.

    The contract is deliberately narrower than "a number", and the boundary
    is worth naming because this reader is general enough to reach for
    anywhere. It reads a quantity the service *measured and published*: a
    percentage, a size, an age, a duration, a rate, a tally, a timestamp.
    Every such quantity is non-negative, so a negative is a corrupt field
    and is refused. Do NOT route a signed figure through here - a delta
    between two readings, a clock offset, a drift, or anything else whose
    sign carries meaning - because this reader would silently discard the
    negative half of its range.

    A quantity *derived* by subtracting two of these readings is a separate
    case and is not this reader's job: it can legitimately come out negative
    from clock skew or an out-of-order stamp, and the treatment there is to
    clamp at zero, not to refuse. :func:`._routes_jobs._age_seconds` is that
    pattern.

    ``nan`` and the infinities are refused too, and they are the one shape
    that fails silently rather than loudly. A ``nan`` compares ``False``
    against every threshold, so a ``nan`` rate ratio would read as "not
    collapsed" and quietly suppress a degradation verdict instead of
    reporting an unreadable field; an infinity reaches the operator
    formatters, which convert to ``int`` and raise. JSON has no syntax for
    either, but Python's ``json`` both emits and accepts them by default, so
    a persisted job record can carry one.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return numeric


def mapping(value: object) -> dict[str, object]:
    """Read one published value as a sub-mapping, or an empty one.

    The structural member of the reader family: a job record arrives as an
    untyped mapping decoded from persisted JSON, and reaching a field nested
    inside it means narrowing the container first. Compose it with the
    scalar readers - ``measurement(mapping(record.get("progress")).get(key))``
    - so a malformed container reads as absent rather than raising.

    An absent or non-mapping value reads as an empty mapping rather than
    ``None``, so a caller can always ``.get`` the field it came for. A
    caller that has to tell "absent" from "present but empty" needs its own
    reader; this one deliberately cannot express that difference.
    """
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def flag(value: object) -> bool | None:
    """Read one published value as a signal; anything else is unreported.

    The three-state reader beside :func:`measurement` and :func:`count`:
    yes, no, and never reported stay distinct, so a signal the service
    never sent can never read as a denial.
    """
    return value if isinstance(value, bool) else None


def text(value: object) -> str:
    """Read one published value as a string, or as the empty string.

    The two-state member of the family, and deliberately so: an identity, a
    cause or a command that the service did not publish as a string cannot
    be shown, addressed or compared, and every caller already treats the
    empty string as that. Distinguishing "absent" from "published empty"
    would need a caller's own reader; nothing here needs the difference.

    Never reach for this to render a number. ``str(value)`` on a raw field
    would print ``True`` as a value; the numeric readers exist to refuse it.
    """
    return value if isinstance(value, str) else ""


#: The conditional evidence sections, each as the readers its members are
#: narrowed through. Encode state is counted work and rate readings are
#: measurements, which is the whole of the difference between them.
_ENCODE_EVIDENCE_READERS: dict[str, Callable[[object], object]] = {
    "token_budget": count,
    "bucket_items": count,
    "items_done": count,
    "items_total": count,
    "oom_count": count,
}
_RATE_EVIDENCE_READERS: dict[str, Callable[[object], object]] = {
    "recent_per_second": measurement,
    "median_per_second": measurement,
    "ratio": measurement,
}


def _conditional_evidence(
    block: dict[str, object] | None,
    readers: dict[str, Callable[[object], object]],
) -> dict[str, object] | None:
    """Shape one conditional evidence section, or ``None`` when unreported.

    The encode section says what bounds the encode stage rather than only
    that it is slow: a run planning tiny batches under a clamped token
    budget, with a retry count that keeps climbing, is bounded by its own
    memory ceiling - a different finding, and a different remedy, from a
    starved card or a stalled store. The rate section is the finding that
    names a collapse: what the job is doing now against what it has proved
    it can do, and the factor between them.

    A section whose every member is unreadable is returned as ``None``, so a
    renderer is never handed a block of nulls to caption.
    """
    if block is None:
        return None
    section: dict[str, object] = {
        key: read(block.get(key)) for key, read in readers.items()
    }
    return section if any(value is not None for value in section.values()) else None


@dataclass(frozen=True, slots=True)
class DegradationInputs:
    """One job's record-side facts, read at one moment, for its evidence.

    Carried as one value rather than re-listed at every call: they are all
    reads of the same record, and the evidence block gains a finding
    whenever the service learns to measure one.
    """

    source: str
    project_root: str | None = None
    step: str | None = None
    forward: dict[str, object] | None = None
    encode: dict[str, object] | None = None
    rate_baseline: dict[str, object] | None = None


def degradation_evidence(
    *,
    now: float,
    inputs: DegradationInputs,
) -> dict[str, object]:
    """Attach sampled cause attribution to one unhealthy job verdict.

    Four findings are always present: the forward-pass window and encode
    thread (is the work alive), the service process's own CPU utilisation
    (is anything running at all), machine-wide GPU pressure (is the card
    starved), and a bounded backend probe (is the store answering). Each
    degrades to explicit absence on hosts or processes that cannot answer it,
    so those four keep a stable shape for every renderer.

    Two findings are conditional, because they describe work not every job
    performs: the encode budget and retry count, and the run's throughput
    against its own baseline. Both are omitted rather than nulled - a job
    that never encoded published no budget, which is a different statement
    from a budget of nothing, and an omitted section costs a renderer no line.

    The forward section is phase-aware: ``expected`` says whether the
    reported step performs forward passes at all, so a CPU-bound phase is
    never judged by the absence of a signal it structurally cannot produce -
    the CPU section is the liveness reading that remains valid there.
    """
    evidence: dict[str, object] = {
        "forward": {
            **_forward_evidence(inputs.forward, now=now),
            "expected": _forward_pass_expected(inputs.step),
        },
        "cpu": _process_cpu_evidence(now=now),
        "gpu": _gpu_evidence(),
        "backend": _backend_evidence(inputs.project_root, inputs.source),
    }
    encode_section = _conditional_evidence(inputs.encode, _ENCODE_EVIDENCE_READERS)
    if encode_section is not None:
        evidence["encode"] = encode_section
    rate_section = _conditional_evidence(inputs.rate_baseline, _RATE_EVIDENCE_READERS)
    if rate_section is not None:
        evidence["rate"] = rate_section
    return evidence


def _worst_forward_evidence(
    forwards: list[dict[str, object] | None],
    *,
    now: float,
) -> dict[str, object]:
    """Shape and pick the machine's worst forward window.

    A dead encode thread under an open window outranks everything; among
    live in-flight forwards the oldest wins; a machine with no in-flight
    forward reports the newest exit it has. One job's block is chosen whole
    rather than merged, so the evidence stays a real observation.
    """
    worst = _forward_evidence(None, now=now)
    worst_rank = (-1, -1.0)
    for forward in forwards:
        evidence = _forward_evidence(forward, now=now)
        in_flight = evidence["in_flight"] is True
        dead = in_flight and evidence["thread_alive"] is False
        age = measurement(evidence["age_seconds"])
        rank = (2 if dead else 1 if in_flight else 0, age if age is not None else -1.0)
        if rank > worst_rank:
            worst_rank, worst = rank, evidence
    return worst


def machine_pressure(
    *,
    now: float,
    forwards: list[dict[str, object] | None],
    project_root: str | None,
    source: str,
    store_failures: tuple[str, ...] = (),
) -> dict[str, object]:
    """The machine-wide pressure block served on the jobs envelope.

    Samples the same seams the degradation evidence reads - the forward
    window, the cached read-only GPU probe, the bounded backend probe -
    plus the encode-admission queue and the typed failures of jobs that
    died recently, and folds them through the hysteresis evaluator into one
    tier. The backend is probed only when running work names a store
    (*project_root*), so an idle machine pays no probe and an unprobed
    store reads as absence, never as a verdict. Surfacing only: nothing
    consumes the tier to defer, shrink, or refuse work.
    """
    from .concurrency import limiter_stats
    from .pressure import MachinePressureSignals, get_pressure_evaluator

    forward_block = _worst_forward_evidence(forwards, now=now)
    gpu = gpu_pressure_snapshot(now=now)
    probed = bool(project_root)
    backend: dict[str, object] = {
        "probed": probed,
        **_backend_evidence(project_root, source),
    }
    if not probed:
        # The declined-probe reading is shaped by the same reader, so only
        # the reason differs: on this axis no job named a store, rather than
        # one job having failed to record one.
        backend["detail"] = "no running index job names a store to probe"
    raw_waiting = limiter_stats()["encode"].get("waiting")
    waiting = (
        raw_waiting
        if isinstance(raw_waiting, int) and not isinstance(raw_waiting, bool)
        else None
    )
    signals = MachinePressureSignals(
        forward_in_flight=forward_block["in_flight"] is True,
        forward_age_seconds=measurement(forward_block["age_seconds"]),
        forward_thread_alive=flag(forward_block["thread_alive"]),
        gpu_utilization_percent=measurement(gpu.get("utilization_percent")),
        gpu_memory_used_mib=measurement(gpu.get("memory_used_mib")),
        gpu_memory_total_mib=measurement(gpu.get("memory_total_mib")),
        backend_probed=probed,
        backend_alive=flag(backend.get("alive")),
        backend_latency_seconds=measurement(backend.get("latency_seconds")),
        backend_probe_bound_seconds=_BACKEND_PROBE_TIMEOUT_SECONDS if probed else None,
        encode_waiters=waiting,
        store_failures=store_failures,
    )
    verdict = get_pressure_evaluator().observe(signals, now=now)
    return {
        "tier": verdict["tier"],
        "entered_at": verdict["entered_at"],
        "evidence": {
            "forward": forward_block,
            "gpu": gpu,
            "backend": backend,
            "encode_waiters": waiting,
            "store_failures": list(store_failures),
        },
    }


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
    # A serve-time shrunken verdict degrades a domain even when its latest job
    # is green: the loss happened to the collection, not to a run. Carrying the
    # repair job id (or the disabled state) here is what turns "mystery
    # reindex" into "shrunken, repair in flight" for an operator.
    from ._integrity_remediation import shrunken_observations

    for source_name, observation in shrunken_observations(root).items():
        degraded.append(
            {
                "source": source_name,
                "job_id": observation["repair_job_id"],
                "reason": "shrunken",
                "error_kind": None,
                "auto_repair": observation["auto_repair"],
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
    with _backend_probe_lock:
        _backend_probe_cache.clear()
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

    def forward_started(self, *, ordinal: int, items: int) -> None:
        record_forward_entry(self.record_id, ordinal=ordinal, items=items)

    def forward_finished(self, *, ordinal: int, items: int) -> None:
        record_forward_exit(self.record_id, ordinal=ordinal, items=items)

    def encode_bucket_observed(
        self,
        *,
        token_budget: int | None,
        bucket_items: int | None,
        items_done: int | None,
        items_total: int | None,
    ) -> None:
        record_encode_bucket(
            self.record_id,
            token_budget=token_budget,
            bucket_items=bucket_items,
            items_done=items_done,
            items_total=items_total,
        )

    def encode_oom(self) -> None:
        record_encode_oom(self.record_id)

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
    commands = {
        JobSource.VAULT: "reindex_vault",
        JobSource.CODE: "reindex_codebase",
        JobSource.DOCUMENT: "reindex_documents",
    }
    command = commands[source]
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
    from .config._settings import get_config
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
    from .config._settings import get_config
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
            details=FinishDetails(
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


def _bind_and_dispatch_admitted(
    manager: JobManager,
    job_id: str,
    *,
    code_preflight: CodeIndexPreflight | None = None,
    document_preflight: DocumentIndexPreflight | None = None,
) -> str:
    """Bind one freshly created index job and dispatch it, failing it durably."""
    bound = _bind_index_dispatch(
        manager,
        job_id,
        code_preflight=code_preflight,
        document_preflight=document_preflight,
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
    return _bind_and_dispatch_admitted(manager, job_id)


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
    return _bind_and_dispatch_admitted(manager, job_id, code_preflight=code_preflight)


def start_reindex_documents(
    root: Path,
    clean: bool,
    *,
    initiator_kind: str = "service",
) -> str:
    """Start a background document reindexing task and return the job_id."""
    document_preflight = validate_document_job_admission(root)
    manager, job_id, created = _admit_index_job(
        root,
        source=JobSource.DOCUMENT,
        clean=clean,
        initiator_kind=initiator_kind,
    )
    if not created:
        return job_id
    return _bind_and_dispatch_admitted(
        manager, job_id, document_preflight=document_preflight
    )
