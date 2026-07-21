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
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, cast

from anyio.to_thread import run_sync as _run_in_thread

from ._job_errors import classify_error_text
from .concurrency import get_index_limiter
from .job_control import RunControlToken
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
    "get_job_manager",
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


@dataclass(frozen=True, slots=True)
class _IdempotencyRecord:
    """Bounded replay identity for one retained create outcome."""

    job_id: str
    spec: JobSpec
    initiator: JobInitiator
    start_paused: bool


@dataclass(slots=True)
class _RuntimeOwnership:
    """Strong references owned by the manager for one active job."""

    control: RunControlToken
    task: asyncio.Task[Any] | None = None
    worker_active: bool = False


_ActiveWorkKey = tuple[JobOperation, JobSource, str | None]
_MAX_IDEMPOTENCY_KEY_LENGTH = 256
# Terminal-history cap retained from the legacy bounded operator registry.
MAX_RECORDS = 256


class JobManager:
    """Thread-safe authority for retained job resources and live runtimes.

    Nonterminal resources live in an exact-ID map and are never evicted.
    Admission fails explicitly at ``max_nonterminal``. Terminal resources use
    a separate bounded history, so operator history cannot displace work that
    is still controllable. Equivalent active specifications share one logical
    job, while bounded idempotency records replay a prior create outcome.

    This Step establishes ownership and admission only. Revisioned lifecycle
    transitions, durable persistence, and attempt dispatch are added by the
    following plan Steps.
    """

    def __init__(
        self,
        *,
        max_nonterminal: int | None = None,
        terminal_history_limit: int = MAX_RECORDS,
    ) -> None:
        if max_nonterminal is None:
            from .config import get_config

            max_nonterminal = get_config().job_max_nonterminal
        if type(max_nonterminal) is not int or max_nonterminal < 1:
            raise ValueError("max_nonterminal must be a positive integer")
        if type(terminal_history_limit) is not int or terminal_history_limit < 1:
            raise ValueError("terminal_history_limit must be a positive integer")

        self._lock = threading.RLock()
        self._max_nonterminal = max_nonterminal
        self._terminal_history_limit = terminal_history_limit
        self._idempotency_limit = max_nonterminal + terminal_history_limit
        self._active: dict[str, JobSnapshot] = {}
        self._active_work: dict[_ActiveWorkKey, str] = {}
        self._active_keys_by_id: dict[str, _ActiveWorkKey] = {}
        self._runtimes: dict[str, _RuntimeOwnership] = {}
        self._terminal: deque[JobSnapshot] = deque()
        self._terminal_by_id: dict[str, JobSnapshot] = {}
        self._idempotency: OrderedDict[str, _IdempotencyRecord] = OrderedDict()

    @property
    def max_nonterminal(self) -> int:
        """Return the configured non-evictable admission bound."""
        return self._max_nonterminal

    def create(
        self,
        spec: JobSpec,
        initiator: JobInitiator,
        *,
        idempotency_key: str | None = None,
        start_paused: bool = False,
    ) -> JobOutcome:
        """Admit or deduplicate one immutable logical job resource."""
        request_error = _create_request_error(
            spec,
            initiator,
            idempotency_key=idempotency_key,
            start_paused=start_paused,
        )
        if request_error is not None:
            return request_error
        # Resolve filesystem identity before taking the manager lock: aliases
        # must converge on one slot, but a slow junction/network resolution
        # must not block exact-ID reads or unrelated admissions.
        active_key_or_error = _resolved_active_work_key(spec)
        if isinstance(active_key_or_error, JobOutcome):
            return active_key_or_error
        active_key = active_key_or_error

        with self._lock:
            replay_outcome = self._idempotency_replay_locked(
                idempotency_key,
                spec=spec,
                initiator=initiator,
                start_paused=start_paused,
            )
            if replay_outcome is not None:
                return replay_outcome

            existing_id = self._active_work.get(active_key)
            if existing_id is not None:
                existing = self._active.get(existing_id)
                if existing is not None:
                    requested_desired = (
                        DesiredJobState.PAUSED
                        if start_paused
                        else DesiredJobState.RUNNING
                    )
                    if (
                        existing.spec.mode is not spec.mode
                        or existing.desired_state is not requested_desired
                    ):
                        return JobOutcome(
                            command="create_job",
                            status=JobOutcomeStatus.ERROR,
                            code="active_job_conflict",
                            message=(
                                "the root and source already have non-equivalent "
                                "active work"
                            ),
                            job=existing,
                        )
                    if idempotency_key is not None:
                        self._remember_idempotency_locked(
                            idempotency_key,
                            _IdempotencyRecord(
                                job_id=existing.id,
                                spec=spec,
                                initiator=initiator,
                                start_paused=start_paused,
                            ),
                        )
                    return JobOutcome(
                        command="create_job",
                        status=JobOutcomeStatus.OK,
                        code="active_job_exists",
                        message="equivalent active work already owns this job slot",
                        job=existing,
                    )
                del self._active_work[active_key]

            if len(self._active) >= self._max_nonterminal:
                return _job_outcome_error(
                    "job_capacity_exceeded",
                    "nonterminal job admission is at its configured bound",
                )

            job_id = self._new_job_id_locked()
            now = time.time()
            state = JobState.PAUSED if start_paused else JobState.QUEUED
            desired = (
                DesiredJobState.PAUSED if start_paused else DesiredJobState.RUNNING
            )
            job = JobSnapshot(
                id=job_id,
                revision=1,
                spec=spec,
                state=state,
                desired_state=desired,
                capabilities=_capabilities_for(spec, state),
                attempt=JobAttempt(number=1),
                timestamps=JobTimestamps(
                    created_at=now,
                    state_changed_at=now,
                ),
                progress=None,
                result=None,
                error_kind=None,
                initiator=initiator,
                runtime=_runtime_snapshot(task_active=False, worker_active=False),
                resources=JobResourceSnapshot(started=None, finished=None),
            )
            self._active[job_id] = job
            self._active_work[active_key] = job_id
            self._active_keys_by_id[job_id] = active_key
            self._runtimes[job_id] = _RuntimeOwnership(control=RunControlToken())
            if idempotency_key is not None:
                self._remember_idempotency_locked(
                    idempotency_key,
                    _IdempotencyRecord(
                        job_id=job_id,
                        spec=spec,
                        initiator=initiator,
                        start_paused=start_paused,
                    ),
                )
            return JobOutcome(
                command="create_job",
                status=JobOutcomeStatus.ACCEPTED,
                code="job_created",
                message="job was admitted",
                job=job,
            )

    def _idempotency_replay_locked(
        self,
        idempotency_key: str | None,
        *,
        spec: JobSpec,
        initiator: JobInitiator,
        start_paused: bool,
    ) -> JobOutcome | None:
        if idempotency_key is None:
            return None
        replay = self._idempotency.get(idempotency_key)
        if replay is None:
            return None
        self._idempotency.move_to_end(idempotency_key)
        existing = self._snapshot_locked(replay.job_id)
        if existing is None:
            # Defensive cleanup if a future retention change removes a
            # resource before its bounded replay entry.
            del self._idempotency[idempotency_key]
            return None
        if (
            replay.spec != spec
            or replay.initiator != initiator
            or replay.start_paused is not start_paused
        ):
            return JobOutcome(
                command="create_job",
                status=JobOutcomeStatus.ERROR,
                code="idempotency_key_conflict",
                message="idempotency key was already used for another request",
                job=existing,
            )
        return JobOutcome(
            command="create_job",
            status=JobOutcomeStatus.OK,
            code="idempotent_replay",
            message="the original create outcome was replayed",
            job=existing,
        )

    def get(self, job_id: str) -> JobSnapshot | None:
        """Return one exact-ID resource; prefixes are never resolved here."""
        with self._lock:
            return self._snapshot_locked(job_id)

    def active_snapshots(self) -> list[JobSnapshot]:
        """Return every nonterminal resource, newest first."""
        with self._lock:
            return sorted(
                self._active.values(),
                key=lambda job: job.timestamps.created_at,
                reverse=True,
            )

    def terminal_snapshots(self) -> list[JobSnapshot]:
        """Return the bounded terminal history, newest first."""
        with self._lock:
            return list(reversed(self._terminal))

    def snapshots(self) -> list[JobSnapshot]:
        """Return the bounded retained resource view, newest first."""
        with self._lock:
            retained = [*self._active.values(), *self._terminal]
            return sorted(
                retained,
                key=lambda job: job.timestamps.created_at,
                reverse=True,
            )

    def control_for(self, job_id: str) -> RunControlToken | None:
        """Return the manager-owned token for an exact active job ID."""
        with self._lock:
            runtime = self._runtimes.get(job_id)
            return runtime.control if runtime is not None else None

    def task_for(self, job_id: str) -> asyncio.Task[Any] | None:
        """Return the strongly held task for an exact active job ID."""
        with self._lock:
            runtime = self._runtimes.get(job_id)
            return runtime.task if runtime is not None else None

    def claim_runtime(
        self,
        job_id: str,
        task: asyncio.Task[Any],
    ) -> RunControlToken:
        """Bind one exact task to an active job and return its control token."""
        with self._lock:
            runtime = self._runtimes.get(job_id)
            if runtime is None:
                raise KeyError(job_id)
            if runtime.task is not None and runtime.task is not task:
                raise RuntimeError(f"job {job_id} already owns another runtime task")
            if runtime.task is None:
                runtime.task = task
                self._set_runtime_flags_locked(job_id, task_active=True)
            return runtime.control

    def release_runtime(self, job_id: str, task: asyncio.Task[Any]) -> bool:
        """Release a task only when the exact active job owns that object."""
        with self._lock:
            runtime = self._runtimes.get(job_id)
            if runtime is None:
                return False
            if runtime.task is not task:
                if runtime.task is None:
                    return False
                raise RuntimeError(f"job {job_id} does not own this runtime task")
            if runtime.worker_active:
                raise RuntimeError(f"job {job_id} still owns an active worker")
            runtime.task = None
            self._set_runtime_flags_locked(job_id, task_active=False)
            return True

    def set_worker_active(self, job_id: str, active: bool) -> bool:
        """Record exact worker ownership without exposing mutable internals."""
        with self._lock:
            runtime = self._runtimes.get(job_id)
            if runtime is None:
                return False
            if active and runtime.task is None:
                raise RuntimeError(f"job {job_id} has no task to own a worker")
            if runtime.worker_active is active:
                return False
            runtime.worker_active = active
            self._set_runtime_flags_locked(job_id, worker_active=active)
            return True

    def _snapshot_locked(self, job_id: str) -> JobSnapshot | None:
        return self._active.get(job_id) or self._terminal_by_id.get(job_id)

    def _new_job_id_locked(self) -> str:
        while True:
            job_id = uuid.uuid4().hex
            if self._snapshot_locked(job_id) is None:
                return job_id

    def _set_runtime_flags_locked(
        self,
        job_id: str,
        *,
        task_active: bool | None = None,
        worker_active: bool | None = None,
    ) -> None:
        job = self._active[job_id]
        runtime = replace(
            job.runtime,
            task_active=(
                job.runtime.task_active if task_active is None else task_active
            ),
            worker_active=(
                job.runtime.worker_active if worker_active is None else worker_active
            ),
        )
        self._active[job_id] = replace(
            job,
            revision=job.revision + 1,
            runtime=runtime,
        )

    def _remember_idempotency_locked(
        self,
        key: str,
        record: _IdempotencyRecord,
    ) -> None:
        self._idempotency[key] = record
        self._idempotency.move_to_end(key)
        while len(self._idempotency) > self._idempotency_limit:
            self._idempotency.popitem(last=False)

    def _retain_terminal_locked(self, job: JobSnapshot) -> None:
        """Move a fully released terminal resource into bounded history."""
        if not job.state.is_terminal:
            raise ValueError("only terminal jobs may enter terminal history")
        if job.id in self._terminal_by_id:
            if self._terminal_by_id[job.id] == job:
                return
            raise RuntimeError("terminal job IDs are immutable")
        runtime = self._runtimes.get(job.id)
        if runtime is not None and (runtime.task is not None or runtime.worker_active):
            raise RuntimeError(
                "cannot retain a terminal job with live runtime ownership"
            )
        if job.runtime.task_active or job.runtime.worker_active:
            raise RuntimeError(
                "terminal snapshot still reports active runtime ownership"
            )
        if (
            job.resources.index_capacity_held
            or job.resources.project_lease_held
            or job.resources.writer_lock_held
            or job.resources.pipeline_active
        ):
            raise RuntimeError(
                "terminal snapshot still reports held execution resources"
            )

        self._active.pop(job.id, None)
        active_key = self._active_keys_by_id.pop(job.id, None)
        if active_key is not None and self._active_work.get(active_key) == job.id:
            del self._active_work[active_key]
        self._runtimes.pop(job.id, None)
        self._terminal.append(job)
        self._terminal_by_id[job.id] = job

        while len(self._terminal) > self._terminal_history_limit:
            evicted = self._terminal.popleft()
            self._terminal_by_id.pop(evicted.id, None)
            stale_keys = [
                key
                for key, replay in self._idempotency.items()
                if replay.job_id == evicted.id
            ]
            for key in stale_keys:
                del self._idempotency[key]


def _create_request_error(
    spec: JobSpec,
    initiator: JobInitiator,
    *,
    idempotency_key: str | None,
    start_paused: bool,
) -> JobOutcome | None:
    validation_error = _job_spec_error(spec)
    if validation_error is not None:
        return _job_outcome_error("invalid_job_spec", validation_error)
    if not initiator.kind.strip() or not initiator.command.strip():
        return _job_outcome_error(
            "invalid_initiator",
            "job initiator kind and command must be non-empty",
        )
    if spec.operation is JobOperation.MAINTENANCE and start_paused:
        return _job_outcome_error(
            "invalid_start_state",
            "maintenance jobs cannot start paused",
        )
    key_error = _idempotency_key_error(idempotency_key)
    if key_error is not None:
        return _job_outcome_error("invalid_idempotency_key", key_error)
    return None


def _job_spec_error(spec: JobSpec) -> str | None:
    root = spec.project_root
    if root is not None and (not root.strip() or not _project_root_is_absolute(root)):
        return "project_root must be an absolute path when supplied"
    if spec.operation is JobOperation.INDEX:
        if spec.source not in {JobSource.VAULT, JobSource.CODE}:
            return "index jobs require vault or code source"
        if root is None:
            return "index jobs require an absolute project_root"
        if spec.mode is None:
            return "index jobs require incremental or rebuild mode"
        return None
    if spec.source is not JobSource.MAINTENANCE or spec.mode is not None:
        return "maintenance jobs require maintenance source and no index mode"
    return None


def _project_root_is_absolute(root: str) -> bool:
    from pathlib import Path

    return Path(root).expanduser().is_absolute()


def _active_work_key(spec: JobSpec) -> _ActiveWorkKey:
    from pathlib import Path

    root = spec.project_root
    if root is None:
        canonical_root = None
    else:
        raw = os.path.expanduser(root)
        if raw.startswith("\\\\?\\UNC\\"):
            raw = "\\\\" + raw[8:]
        elif raw.startswith("\\\\?\\"):
            raw = raw[4:]
        canonical_root = os.path.normcase(str(Path(raw).resolve()))
    return (spec.operation, spec.source, canonical_root)


def _resolved_active_work_key(spec: JobSpec) -> _ActiveWorkKey | JobOutcome:
    try:
        return _active_work_key(spec)
    except (OSError, RuntimeError, ValueError) as exc:
        return _job_outcome_error(
            "invalid_project_root",
            f"project_root cannot be resolved: {exc}",
        )


def _idempotency_key_error(key: str | None) -> str | None:
    if key is None:
        return None
    if not key.strip():
        return "idempotency key must not be empty"
    if len(key) > _MAX_IDEMPOTENCY_KEY_LENGTH:
        return f"idempotency key exceeds {_MAX_IDEMPOTENCY_KEY_LENGTH} characters"
    return None


def _runtime_snapshot(*, task_active: bool, worker_active: bool) -> JobRuntimeSnapshot:
    return JobRuntimeSnapshot(
        pid=os.getpid(),
        parent_pid=os.getppid(),
        user=getpass.getuser(),
        executable=sys.executable,
        prefix=sys.prefix,
        base_prefix=sys.base_prefix,
        virtual_env=os.environ.get("VIRTUAL_ENV"),
        task_active=task_active,
        worker_active=worker_active,
    )


def _capabilities_for(spec: JobSpec, state: JobState) -> JobCapabilities:
    if spec.operation is JobOperation.MAINTENANCE:
        return JobCapabilities(
            pausable=False,
            resumable=False,
            cancellable=False,
            retryable=False,
            deletable=state.is_terminal,
        )
    return JobCapabilities(
        pausable=state in {JobState.QUEUED, JobState.RUNNING},
        resumable=state in {JobState.PAUSING, JobState.PAUSED},
        cancellable=state
        in {JobState.QUEUED, JobState.RUNNING, JobState.PAUSING, JobState.PAUSED},
        retryable=state in {JobState.CANCELLED, JobState.FAILED, JobState.INTERRUPTED},
        deletable=state.is_terminal,
    )


def _job_outcome_error(code: str, message: str) -> JobOutcome:
    return JobOutcome(
        command="create_job",
        status=JobOutcomeStatus.ERROR,
        code=code,
        message=message,
    )


_job_manager_lock = threading.Lock()
_job_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    """Return the process-wide service-domain job manager."""
    global _job_manager
    with _job_manager_lock:
        if _job_manager is None:
            _job_manager = JobManager()
        return _job_manager


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
