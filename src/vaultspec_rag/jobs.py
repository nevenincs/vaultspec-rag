"""In-flight activity registry and background task worker for index/reindex jobs.

A thread-safe, bounded record of every index/reindex activity the service performs,
along with async task execution helpers for background reindexing.
"""

from __future__ import annotations

import asyncio
import getpass
import logging
import os
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, cast

from anyio.to_thread import run_sync as _run_in_thread

from ._job_errors import classify_error_text
from .concurrency import get_index_limiter
from .logging_config import log_event
from .registry import get_registry

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_RECORDS",
    "DesiredJobState",
    "JobAttempt",
    "JobCapabilities",
    "JobInitiator",
    "JobMode",
    "JobOperation",
    "JobOutcome",
    "JobOutcomeStatus",
    "JobProgress",
    "JobProgressReporter",
    "JobResourceSnapshot",
    "JobRuntimeSnapshot",
    "JobSnapshot",
    "JobSource",
    "JobSpec",
    "JobState",
    "JobTimestamps",
    "ProcessResourceSnapshot",
    "ResumeStrategy",
    "record_finish",
    "record_progress",
    "record_start",
    "register_on_job_complete",
    "reset",
    "resource_snapshot",
    "restore_interrupted",
    "snapshot",
    "start_reindex_codebase",
    "start_reindex_vault",
]


class JobOperation(StrEnum):
    """Stable service-domain operation vocabulary."""

    INDEX = "index"
    MAINTENANCE = "maintenance"


class JobSource(StrEnum):
    """Corpus or service resource acted on by a job."""

    VAULT = "vault"
    CODE = "code"
    MAINTENANCE = "maintenance"


class JobMode(StrEnum):
    """Requested indexing convergence mode."""

    INCREMENTAL = "incremental"
    REBUILD = "rebuild"


class JobState(StrEnum):
    """Canonical observed lifecycle state."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

    @property
    def is_terminal(self) -> bool:
        """Return whether no transition may rewrite this job resource."""
        return self in {
            JobState.CANCELLED,
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.INTERRUPTED,
        }


class DesiredJobState(StrEnum):
    """Canonical operator intent, distinct from observed state."""

    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ResumeStrategy(StrEnum):
    """How a later attempt continues paused logical work."""

    RECONCILE = "reconcile"


class JobOutcomeStatus(StrEnum):
    """Stable disposition for service-domain command outcomes."""

    ACCEPTED = "accepted"
    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class JobSpec:
    """Immutable instructions for one logical job resource."""

    operation: JobOperation
    source: JobSource
    project_root: str | None
    mode: JobMode | None


@dataclass(frozen=True, slots=True)
class JobInitiator:
    """Immutable attribution retained across execution attempts."""

    kind: str
    command: str
    project_root: str | None


@dataclass(frozen=True, slots=True)
class JobCapabilities:
    """Actions currently supported for an exact job resource."""

    pausable: bool
    resumable: bool
    cancellable: bool
    retryable: bool
    deletable: bool
    force_killable: bool = False


@dataclass(frozen=True, slots=True)
class JobAttempt:
    """Attempt and retry lineage for one logical job resource."""

    number: int
    parent_job_id: str | None = None
    resumed_from_attempt: int | None = None
    resume_strategy: ResumeStrategy | None = None

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("job attempt number must be at least 1")
        if self.resumed_from_attempt is not None and self.resumed_from_attempt < 1:
            raise ValueError("resumed attempt number must be at least 1")


@dataclass(frozen=True, slots=True)
class JobTimestamps:
    """Lifecycle clocks carried by every canonical snapshot."""

    created_at: float
    state_changed_at: float
    started_at: float | None = None
    finished_at: float | None = None
    control_requested_at: float | None = None
    control_acknowledged_at: float | None = None


@dataclass(frozen=True, slots=True)
class JobProgress:
    """Immutable view of the canonical progress stream."""

    step: str
    completed: int
    total: int | None
    last_updated: float


@dataclass(frozen=True, slots=True)
class JobRuntimeSnapshot:
    """Process identity and live execution ownership for one snapshot."""

    pid: int
    parent_pid: int
    user: str
    executable: str
    prefix: str
    base_prefix: str
    virtual_env: str | None
    task_active: bool = False
    worker_active: bool = False


@dataclass(frozen=True, slots=True)
class ProcessResourceSnapshot:
    """Best-effort process memory readings at one lifecycle boundary."""

    rss_mb: float
    cuda_allocated_mb: float
    cuda_reserved_mb: float


@dataclass(frozen=True, slots=True)
class JobResourceSnapshot:
    """Execution-resource ownership and boundary memory readings."""

    started: ProcessResourceSnapshot | None
    finished: ProcessResourceSnapshot | None
    index_capacity_held: bool = False
    project_lease_held: bool = False
    writer_lock_held: bool = False
    pipeline_active: bool = False


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    """Immutable exact-ID view of one canonical job resource."""

    id: str
    revision: int
    spec: JobSpec
    state: JobState
    desired_state: DesiredJobState
    capabilities: JobCapabilities
    attempt: JobAttempt
    timestamps: JobTimestamps
    progress: JobProgress | None
    result: str | None
    error_kind: str | None
    initiator: JobInitiator
    runtime: JobRuntimeSnapshot
    resources: JobResourceSnapshot

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("job revision must be at least 1")

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON-ready resource representation."""
        return {
            "id": self.id,
            "revision": self.revision,
            "spec": {
                "operation": self.spec.operation.value,
                "source": self.spec.source.value,
                "project_root": self.spec.project_root,
                "mode": self.spec.mode.value if self.spec.mode is not None else None,
            },
            "state": self.state.value,
            "desired_state": self.desired_state.value,
            "capabilities": {
                "pausable": self.capabilities.pausable,
                "resumable": self.capabilities.resumable,
                "cancellable": self.capabilities.cancellable,
                "retryable": self.capabilities.retryable,
                "deletable": self.capabilities.deletable,
                "force_killable": self.capabilities.force_killable,
            },
            "attempt": self.attempt.number,
            "parent_job_id": self.attempt.parent_job_id,
            "resumed_from_attempt": self.attempt.resumed_from_attempt,
            "resume_strategy": (
                self.attempt.resume_strategy.value
                if self.attempt.resume_strategy is not None
                else None
            ),
            "created_at": self.timestamps.created_at,
            "state_changed_at": self.timestamps.state_changed_at,
            "started_at": self.timestamps.started_at,
            "finished_at": self.timestamps.finished_at,
            "control_requested_at": self.timestamps.control_requested_at,
            "control_acknowledged_at": self.timestamps.control_acknowledged_at,
            "progress": _progress_to_dict(self.progress),
            "result": self.result,
            "error_kind": self.error_kind,
            "initiator": {
                "kind": self.initiator.kind,
                "command": self.initiator.command,
                "project_root": self.initiator.project_root,
            },
            "runtime": _runtime_to_dict(self.runtime),
            "resources": _resources_to_dict(self.resources),
        }


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """One structured service-domain result for a job command."""

    command: str
    status: JobOutcomeStatus
    code: str
    message: str
    job: JobSnapshot | None = None

    def to_dict(self) -> dict[str, object]:
        """Return one adapter-ready outcome envelope."""
        return {
            "command": self.command,
            "status": self.status.value,
            "code": self.code,
            "message": self.message,
            "job": self.job.to_dict() if self.job is not None else None,
        }


def _progress_to_dict(progress: JobProgress | None) -> dict[str, object] | None:
    if progress is None:
        return None
    return {
        "step": progress.step,
        "completed": progress.completed,
        "total": progress.total,
        "last_updated": progress.last_updated,
    }


def _runtime_to_dict(runtime: JobRuntimeSnapshot) -> dict[str, object]:
    return {
        "pid": runtime.pid,
        "parent_pid": runtime.parent_pid,
        "user": runtime.user,
        "executable": runtime.executable,
        "prefix": runtime.prefix,
        "base_prefix": runtime.base_prefix,
        "virtual_env": runtime.virtual_env,
        "task_active": runtime.task_active,
        "worker_active": runtime.worker_active,
    }


def _process_resources_to_dict(
    resources: ProcessResourceSnapshot | None,
) -> dict[str, object] | None:
    if resources is None:
        return None
    return {
        "rss_mb": resources.rss_mb,
        "cuda_allocated_mb": resources.cuda_allocated_mb,
        "cuda_reserved_mb": resources.cuda_reserved_mb,
    }


def _resources_to_dict(resources: JobResourceSnapshot) -> dict[str, object]:
    return {
        "started": _process_resources_to_dict(resources.started),
        "finished": _process_resources_to_dict(resources.finished),
        "index_capacity_held": resources.index_capacity_held,
        "project_lease_held": resources.project_lease_held,
        "writer_lock_held": resources.writer_lock_held,
        "pipeline_active": resources.pipeline_active,
    }


# Source of an activity: the documentation vault, the source codebase, or
# the service's own scheduled storage maintenance.
Source = Literal["vault", "code", "maintenance"]
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

# Bounded ring buffer cap. Generous enough to retain a meaningful recent
# history without unbounded growth; the oldest record is evicted past this.
MAX_RECORDS = 256

_lock = threading.Lock()
_records: deque[dict[str, object]] = deque(maxlen=MAX_RECORDS)
_background_tasks: set[asyncio.Task[Any]] = set()
_on_job_complete_callbacks: list[Callable[[float], None]] = []


# Persisted active-jobs snapshot, under the managed status dir. Written on
# every job start/finish and step change; read once at daemon startup to
# re-register jobs a dead daemon left running as ``interrupted``.
_ACTIVE_SNAPSHOT_FILENAME = "jobs-active.json"


def _active_snapshot_path() -> object:
    """Resolve the active-jobs snapshot path from the managed status dir."""
    from pathlib import Path

    from .config import get_config

    return Path(str(get_config().status_dir)).expanduser() / _ACTIVE_SNAPSHOT_FILENAME


def _persist_active_snapshot() -> None:
    """Write the currently-running jobs to the status dir, atomically.

    Best-effort durability for the in-memory ring: if this daemon dies,
    the next startup reads the file and surfaces the jobs as
    ``interrupted`` instead of letting them vanish. Never raises - jobs
    bookkeeping must not fail a job.
    """
    import json as _json

    with _lock:
        active = [
            {
                "id": record.get("id"),
                "source": record.get("source"),
                "trigger": record.get("trigger"),
                "started_at": record.get("started_at"),
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
        path = cast("Path", _active_snapshot_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(_json.dumps({"active": active}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logger.debug("could not persist active-jobs snapshot", exc_info=True)


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
            "initiator": data.get("initiator"),
            "runtime": _runtime_context(),
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


def _runtime_context() -> dict[str, object]:
    return {
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "user": getpass.getuser(),
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "virtual_env": os.environ.get("VIRTUAL_ENV"),
    }


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
    source: Source,
    trigger: Trigger,
    *,
    project_root: Path | None = None,
    command: str | None = None,
    initiator_kind: str | None = None,
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
    record_id = uuid.uuid4().hex
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
        # only a summary count (preprocess-sandbox ADR D9), and how many files
        # rules actually fed, so a missing rule-fed corpus is diagnosable from
        # the job record alone. Populated at finish.
        "preprocess_ok": 0,
        "preprocess_skipped": 0,
        "preprocess_failures": [],
        "initiator": {
            "kind": initiator_kind or trigger,
            "command": command or f"{trigger}_{source}_index",
            "project_root": str(project_root) if project_root is not None else None,
        },
        "runtime": _runtime_context(),
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
                record["progress"] = {
                    "step": step,
                    "completed": completed,
                    "total": total,
                    "last_updated": time.time(),
                }
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
    preprocess_ok: int,
    preprocess_skipped: int,
    preprocess_failures: list[str] | None,
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
    record["preprocess_ok"] = preprocess_ok
    record["preprocess_skipped"] = preprocess_skipped
    record["preprocess_failures"] = list(preprocess_failures or [])
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


def record_finish(
    record_id: str,
    *,
    result: str | None = None,
    error: str | None = None,
    phase: Phase | None = None,
    preprocess_ok: int = 0,
    preprocess_skipped: int = 0,
    preprocess_failures: list[str] | None = None,
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
            skipped this run, threaded onto the record so /jobs can surface it
            (preprocess-sandbox ADR D9).
        preprocess_failures: ``"rel_path: reason"`` per skipped file, threaded
            onto the record so a client sees which files failed extraction and
            why - not just a count.
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
                    preprocess_ok=preprocess_ok,
                    preprocess_skipped=preprocess_skipped,
                    preprocess_failures=preprocess_failures,
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
            item = dict(record)
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
            copied.append(item)
        return copied


def reset() -> None:
    """Clear all recorded in-memory activity (test-only).

    Deliberately leaves the persisted active-jobs snapshot alone so tests
    can simulate a daemon death (records gone, snapshot intact) and then
    exercise :func:`restore_interrupted`.
    """
    with _lock:
        _records.clear()


class JobProgressReporter:
    """ProgressReporter that updates a specific in-flight job's progress."""

    def __init__(self, record_id: str) -> None:
        self.record_id = record_id
        self._step_name: str | None = None
        self._completed: int = 0
        self._total: int | None = None

    def phase_start(self, name: str, total: int | None) -> None:
        self._step_name = name
        self._total = total
        self._completed = 0
        record_progress(self.record_id, step=name, completed=0, total=total)

    def advance(self, n: int = 1) -> None:
        self._completed += n
        if self._step_name:
            record_progress(
                self.record_id,
                step=self._step_name,
                completed=self._completed,
                total=self._total,
            )

    def phase_end(self) -> None:
        pass

    def log(self, message: str) -> None:
        pass


def start_reindex_vault(
    root: Path, clean: bool, *, initiator_kind: str = "service"
) -> str:
    """Start a background vault reindexing task and return the job_id."""
    job_id = record_start(
        "vault",
        "tool",
        project_root=root,
        command="reindex_vault",
        initiator_kind=initiator_kind,
    )
    record_progress(job_id, "queued")

    async def run_indexing_bg() -> None:
        try:
            started = time.perf_counter()

            def _bg_run() -> None:
                try:
                    get_registry().load_model()
                    with get_registry().lease(root) as slot:
                        if clean:
                            result = slot.vault_indexer.full_index(
                                clean=True,
                                reporter=JobProgressReporter(job_id),
                            )
                        else:
                            result = slot.vault_indexer.incremental_index(
                                reporter=JobProgressReporter(job_id)
                            )
                        record_finish(
                            job_id,
                            result=(
                                f"+{result.added} /{result.updated} "
                                f"-{result.removed} ({result.duration_ms}ms)"
                            ),
                        )
                        slot.graph_cache.invalidate()
                except Exception as exc:
                    record_finish(job_id, error=str(exc))
                    logger.exception("Background vault re-indexing failed")

            await _run_in_thread(_bg_run, limiter=get_index_limiter())
            duration = time.perf_counter() - started
            for cb in _on_job_complete_callbacks:
                try:
                    cb(duration)
                except Exception as e:
                    logger.exception("Error in job complete callback: %s", e)
        except Exception:
            logger.exception("Failed to launch background vault re-indexing task")

    task = asyncio.create_task(run_indexing_bg())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return job_id


def start_reindex_codebase(
    root: Path,
    clean: bool,
    *,
    initiator_kind: str = "service",
) -> str:
    """Start a background codebase reindexing task and return the job_id."""
    job_id = record_start(
        "code",
        "tool",
        project_root=root,
        command="reindex_codebase",
        initiator_kind=initiator_kind,
    )
    record_progress(job_id, "queued")

    async def run_indexing_bg() -> None:
        try:
            started = time.perf_counter()

            def _bg_run() -> None:
                try:
                    get_registry().load_model()
                    with get_registry().lease(root) as slot:
                        if clean:
                            result = slot.code_indexer.full_index(
                                clean=True,
                                reporter=JobProgressReporter(job_id),
                            )
                        else:
                            result = slot.code_indexer.incremental_index(
                                reporter=JobProgressReporter(job_id)
                            )
                        skipped_suffix = (
                            f" ~{result.preprocess_skipped}"
                            if result.preprocess_skipped
                            else ""
                        )
                        record_finish(
                            job_id,
                            result=(
                                f"+{result.added} /{result.updated} "
                                f"-{result.removed} ({result.duration_ms}ms)"
                                f"{skipped_suffix}"
                            ),
                            preprocess_ok=result.preprocess_ok,
                            preprocess_skipped=result.preprocess_skipped,
                            preprocess_failures=result.preprocess_failures,
                        )
                except Exception as exc:
                    record_finish(job_id, error=str(exc))
                    logger.exception("Background codebase re-indexing failed")

            await _run_in_thread(_bg_run, limiter=get_index_limiter())
            duration = time.perf_counter() - started
            for cb in _on_job_complete_callbacks:
                try:
                    cb(duration)
                except Exception as e:
                    logger.exception("Error in job complete callback: %s", e)
        except Exception:
            logger.exception("Failed to launch background codebase re-indexing task")

    task = asyncio.create_task(run_indexing_bg())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return job_id
