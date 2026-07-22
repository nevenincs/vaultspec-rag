"""In-flight activity registry and background task worker for index/reindex jobs.

A thread-safe, bounded record of every index/reindex activity the service performs,
along with async task execution helpers for background reindexing.
"""

from __future__ import annotations

import getpass
import logging
import os
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from anyio.to_thread import run_sync as _run_in_thread

from ._job_errors import classify_error_text
from .job_manager import (
    MAX_RECORDS,
    JobAttemptContext,
    JobExecutionResult,
    JobManager,
)
from .job_models import (
    DesiredJobState,
    JobAttempt,
    JobCapabilities,
    JobInitiator,
    JobMode,
    JobOperation,
    JobOutcome,
    JobOutcomeStatus,
    JobProgress,
    JobResourceSnapshot,
    JobRuntimeSnapshot,
    JobSnapshot,
    JobSource,
    JobSpec,
    JobState,
    JobTimestamps,
    ProcessResourceSnapshot,
    ResumeStrategy,
)
from .logging_config import log_event
from .registry import get_registry

if TYPE_CHECKING:
    from collections.abc import Callable

    from .indexer._codebase_indexer import ContentScanResult
    from .service import ServiceRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_RECORDS",
    "DesiredJobState",
    "JobAttempt",
    "JobAttemptContext",
    "JobCapabilities",
    "JobExecutionResult",
    "JobInitiator",
    "JobManager",
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
    "activate_index_job",
    "get_job_manager",
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
]


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

_lock = threading.Lock()
_records: deque[dict[str, object]] = deque(maxlen=MAX_RECORDS)
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
                manager = JobManager()
                _job_manager = manager
    return manager


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
            "vault" if source is JobSource.VAULT else "code",
            "tool",
            project_root=resolved_root,
            command=command,
            initiator_kind=initiator_kind,
            _record_id=job_id,
        )
        record_progress(job_id, "queued")
    return manager, job_id, created


def validate_code_index_policy(root: Path) -> None:
    """Resolve the default code policy before a job can mutate durable state."""
    from .indexer._content_policy import RootContentPolicy, SourceProfileVersion
    from .indexer._resolved_policy import resolve_index_policy

    resolve_index_policy(
        root.resolve(),
        content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1),
    )


def scan_code_index_preflight(root: Path) -> ContentScanResult:
    """Return bounded admission from the production structured scanner."""
    from .api import scan_codebase

    return scan_codebase(root)


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
            preprocess_ok=result.preprocess_ok if result is not None else 0,
            preprocess_skipped=(result.preprocess_skipped if result is not None else 0),
            preprocess_failures=(
                list(result.preprocess_failures) if result is not None else None
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
    registry: ServiceRegistry | None = None,
) -> JobOutcome:
    """Attach one logical job to the production indexing implementation."""
    from .job_dispatch import bind_index_job

    return bind_index_job(
        manager,
        job_id,
        registry=get_registry() if registry is None else registry,
        on_started=_sync_legacy_started,
        on_finished=_sync_legacy_finished,
    )


def _prepare_index_job_activation(
    manager: JobManager,
    snapshot: JobSnapshot,
    registry: ServiceRegistry | None,
) -> JobOutcome:
    """Publish legacy observability and bind execution outside the event loop."""
    root = Path(snapshot.spec.project_root) if snapshot.spec.project_root else None
    if snapshot.spec.source is JobSource.CODE and root is not None:
        validate_code_index_policy(root)
    source = "vault" if snapshot.spec.source is JobSource.VAULT else "code"
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
    return _bind_index_dispatch(manager, snapshot.id, registry=registry)


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
    registry: ServiceRegistry | None = None,
) -> JobOutcome:
    """Bind and dispatch one newly admitted job without blocking its event loop.

    Replayed or deduplicated creation outcomes already refer to an activated
    resource and are returned unchanged. Newly created paused jobs are bound
    but remain inert until their desired state changes to ``running``.
    """
    snapshot = outcome.job
    if (
        outcome.status is JobOutcomeStatus.ERROR
        or snapshot is None
        or outcome.code not in {"job_created", "job_retry_created"}
    ):
        return outcome

    manager = get_job_manager()
    bound = await _run_in_thread(
        _prepare_index_job_activation,
        manager,
        snapshot,
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
        if (
            snapshot.spec.source is JobSource.CODE
            and snapshot.spec.project_root is not None
        ):
            validate_code_index_policy(Path(snapshot.spec.project_root))
        bound = _bind_index_dispatch(manager, snapshot.id, registry=registry)
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

    bound = _bind_index_dispatch(manager, job_id)
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
    validate_code_index_policy(root)
    manager, job_id, created = _admit_index_job(
        root,
        source=JobSource.CODE,
        clean=clean,
        initiator_kind=initiator_kind,
    )
    if not created:
        return job_id

    bound = _bind_index_dispatch(manager, job_id)
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
