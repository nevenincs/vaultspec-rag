"""In-flight activity registry and background task worker for index/reindex jobs.

A thread-safe, bounded record of every index/reindex activity the service performs,
along with async task execution helpers for background reindexing.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import logging
import math
import os
import sys
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from anyio.to_thread import run_sync as _run_in_thread

from ._job_errors import classify_error_text
from .concurrency import get_index_limiter
from .config import get_config
from .logging_config import log_event
from .registry import get_registry

if TYPE_CHECKING:
    from collections.abc import Callable

    from .job_control import RunControlToken

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
    "JobRuntimeOwner",
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
_ATOMIC_REPLACE_ATTEMPTS = 8
_ATOMIC_REPLACE_RETRY_SECONDS = 0.005
_MANAGED_STATE_FILENAME = "jobs-state.json"
_MAX_IDEMPOTENCY_KEY_LENGTH = 256


class _ConfiguredStatePath:
    __slots__ = ()


_CONFIGURED_STATE_PATH = _ConfiguredStatePath()


@dataclass(frozen=True, slots=True)
class JobRuntimeOwner:
    """Strong references to the live execution for one exact job ID."""

    task: asyncio.Task[Any] | None
    control: RunControlToken | None
    worker_active: bool = False


@dataclass(slots=True)
class _ManagedJob:
    snapshot: JobSnapshot
    runtime: JobRuntimeOwner


@dataclass(frozen=True, slots=True)
class _IdempotencyBinding:
    signature: tuple[JobSpec, JobInitiator, bool]
    job_id: str


@dataclass(slots=True)
class _ManagerStateBackup:
    active: dict[str, _ManagedJob]
    terminal: deque[_ManagedJob]
    snapshots: dict[str, JobSnapshot]
    runtimes: dict[str, JobRuntimeOwner]
    idempotency: OrderedDict[str, _IdempotencyBinding]
    job_idempotency_keys: dict[str, set[str]]


class JobManager:
    """Own canonical job resources and their exact live runtime handles.

    Nonterminal jobs are never evicted. Terminal records have an independent
    retention bound, so operator history cannot displace controllable work.
    """

    def __init__(
        self,
        *,
        max_nonterminal: int | None = None,
        max_terminal_history: int = MAX_RECORDS,
        state_path: (
            str | os.PathLike[str] | None | _ConfiguredStatePath
        ) = _CONFIGURED_STATE_PATH,
    ) -> None:
        resolved_max = (
            get_config().job_max_nonterminal
            if max_nonterminal is None
            else max_nonterminal
        )
        if isinstance(resolved_max, bool) or resolved_max < 1:
            raise ValueError("max_nonterminal must be at least 1")
        if isinstance(max_terminal_history, bool) or max_terminal_history < 1:
            raise ValueError("max_terminal_history must be at least 1")

        self._max_nonterminal = resolved_max
        self._max_terminal_history = max_terminal_history
        self._max_idempotency = resolved_max + max_terminal_history
        if state_path is _CONFIGURED_STATE_PATH:
            self._state_path = (
                Path(str(get_config().status_dir)) / _MANAGED_STATE_FILENAME
            )
        else:
            resolved_path = cast("str | os.PathLike[str] | None", state_path)
            self._state_path = (
                Path(resolved_path) if resolved_path is not None else None
            )
        self._lock = threading.RLock()
        self._active: dict[str, _ManagedJob] = {}
        self._terminal: deque[_ManagedJob] = deque()
        self._idempotency: OrderedDict[str, _IdempotencyBinding] = OrderedDict()
        self._job_idempotency_keys: dict[str, set[str]] = {}

    @property
    def max_nonterminal(self) -> int:
        """Configured admission bound for exact-addressable active work."""
        return self._max_nonterminal

    @property
    def max_terminal_history(self) -> int:
        """Retention bound for completed job resources."""
        return self._max_terminal_history

    @property
    def state_path(self) -> Path | None:
        """Atomic state-file path, or ``None`` for an in-memory manager."""
        return self._state_path

    def create(  # noqa: PLR0912 - admission/replay matrix
        self,
        spec: JobSpec,
        initiator: JobInitiator,
        *,
        idempotency_key: str | None = None,
        start_paused: bool = False,
        job_id: str | None = None,
    ) -> JobOutcome:
        """Admit one logical job, or replay/deduplicate an existing resource."""
        spec_error = _job_spec_error(spec)
        if spec_error is not None:
            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.ERROR,
                code="invalid_job_spec",
                message=spec_error,
            )
        try:
            normalized_key = self._normalize_idempotency_key(idempotency_key)
        except ValueError as exc:
            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.ERROR,
                code="invalid_idempotency_key",
                message=str(exc),
            )
        signature = (spec, initiator, start_paused)

        with self._lock:
            backup = self._capture_state_locked()
            if normalized_key is not None:
                binding = self._idempotency.get(normalized_key)
                if binding is not None:
                    self._idempotency.move_to_end(normalized_key)
                    existing = self._get_locked(binding.job_id)
                    if binding.signature != signature:
                        return JobOutcome(
                            command="create",
                            status=JobOutcomeStatus.ERROR,
                            code="idempotency_key_conflict",
                            message=(
                                "The idempotency key is already bound to a different "
                                "job request."
                            ),
                            job=existing,
                        )
                    if existing is not None:
                        return JobOutcome(
                            command="create",
                            status=JobOutcomeStatus.OK,
                            code="idempotency_replayed",
                            message="The original job creation result was replayed.",
                            job=existing,
                        )
                    self._idempotency.pop(normalized_key, None)

            equivalent = self._find_equivalent_active_locked(spec)
            if equivalent is not None:
                if normalized_key is not None:
                    self._bind_idempotency_locked(
                        normalized_key,
                        signature,
                        equivalent.id,
                    )
                    persistence_error = self._persist_locked()
                    if persistence_error is not None:
                        self._restore_state_locked(backup)
                        return self._persistence_error(
                            "create",
                            persistence_error,
                            equivalent,
                        )
                return JobOutcome(
                    command="create",
                    status=JobOutcomeStatus.OK,
                    code="active_job_exists",
                    message="Equivalent active work is already registered.",
                    job=equivalent,
                )

            if len(self._active) >= self._max_nonterminal:
                return JobOutcome(
                    command="create",
                    status=JobOutcomeStatus.ERROR,
                    code="job_capacity_exceeded",
                    message=(
                        "The service has reached its configured nonterminal job "
                        f"capacity ({self._max_nonterminal})."
                    ),
                )

            resolved_id = job_id or str(uuid.uuid4())
            if self._get_locked(resolved_id) is not None:
                return JobOutcome(
                    command="create",
                    status=JobOutcomeStatus.ERROR,
                    code="job_id_conflict",
                    message=f"Job ID {resolved_id!r} is already registered.",
                    job=self._get_locked(resolved_id),
                )

            now = time.time()
            state = JobState.PAUSED if start_paused else JobState.QUEUED
            desired_state = (
                DesiredJobState.PAUSED if start_paused else DesiredJobState.RUNNING
            )
            created = JobSnapshot(
                id=resolved_id,
                revision=1,
                spec=spec,
                state=state,
                desired_state=desired_state,
                capabilities=self._capabilities_for(spec, state),
                attempt=JobAttempt(number=1),
                timestamps=JobTimestamps(
                    created_at=now,
                    state_changed_at=now,
                    control_acknowledged_at=now if start_paused else None,
                ),
                progress=None,
                result=None,
                error_kind=None,
                initiator=initiator,
                runtime=self._process_runtime_snapshot(),
                resources=JobResourceSnapshot(started=None, finished=None),
            )
            self._active[resolved_id] = _ManagedJob(
                snapshot=created,
                runtime=JobRuntimeOwner(task=None, control=None),
            )
            if normalized_key is not None:
                self._bind_idempotency_locked(
                    normalized_key,
                    signature,
                    resolved_id,
                )

            persistence_error = self._persist_locked()
            if persistence_error is not None:
                self._restore_state_locked(backup)
                return self._persistence_error("create", persistence_error)

            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.ACCEPTED,
                code="job_created",
                message="The job was admitted.",
                job=created,
            )

    def get(self, job_id: str) -> JobSnapshot | None:
        """Return an immutable snapshot for one full, exact job ID."""
        with self._lock:
            return self._get_locked(job_id)

    def list_jobs(self) -> list[JobSnapshot]:
        """Return active work first, then separately bounded terminal history."""
        with self._lock:
            active = sorted(
                (self._snapshot_locked(job) for job in self._active.values()),
                key=lambda job: job.timestamps.created_at,
                reverse=True,
            )
            terminal = [self._snapshot_locked(job) for job in reversed(self._terminal)]
            return [*active, *terminal]

    def active(self) -> list[JobSnapshot]:
        """Return every nonterminal job without eviction or prefix matching."""
        with self._lock:
            return [self._snapshot_locked(job) for job in self._active.values()]

    def terminal(self) -> list[JobSnapshot]:
        """Return retained terminal history newest first."""
        with self._lock:
            return [self._snapshot_locked(job) for job in reversed(self._terminal)]

    def runtime_owner(self, job_id: str) -> JobRuntimeOwner | None:
        """Return exact-ID runtime ownership without resolving prefixes."""
        with self._lock:
            managed = self._active.get(job_id)
            return managed.runtime if managed is not None else None

    def start_attempt(
        self,
        job_id: str,
        *,
        task: asyncio.Task[Any],
        control: RunControlToken,
    ) -> JobOutcome:
        """Atomically claim and start the queued attempt for one exact job."""
        command = "start_attempt"
        with self._lock:
            backup = self._capture_state_locked()
            managed = self._active.get(job_id)
            if managed is None:
                return self._error(command, "job_not_found", "The job was not found.")
            if (
                managed.snapshot.state is not JobState.QUEUED
                or managed.snapshot.desired_state is not DesiredJobState.RUNNING
            ):
                return self._error(
                    command,
                    "invalid_transition",
                    "Only queued work with running desired state can start.",
                    managed,
                )
            if managed.runtime.task is not None:
                return self._error(
                    command,
                    "runtime_already_owned",
                    "The current attempt already has a runtime owner.",
                    managed,
                )

            managed.runtime = JobRuntimeOwner(task=task, control=control)
            now = time.time()
            self._replace_snapshot_locked(
                managed,
                state=JobState.RUNNING,
                desired_state=DesiredJobState.RUNNING,
                now=now,
                started_at=now,
            )
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                self._restore_state_locked(backup)
                return self._persistence_error(
                    command,
                    persistence_error,
                    managed.snapshot,
                )
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="attempt_started",
                message="The queued attempt acquired its runtime.",
                job=self._snapshot_locked(managed),
            )

    def set_worker_active(
        self,
        job_id: str,
        *,
        task: asyncio.Task[Any],
        active: bool,
    ) -> bool:
        """Update worker ownership only for the currently attached attempt."""
        with self._lock:
            backup = self._capture_state_locked()
            managed = self._active.get(job_id)
            if managed is None or managed.runtime.task is not task:
                return False
            managed.runtime = replace(managed.runtime, worker_active=active)
            if self._persist_locked() is not None:
                self._restore_state_locked(backup)
                return False
            return True

    def set_execution_resources(
        self,
        job_id: str,
        *,
        task: asyncio.Task[Any],
        resources: JobResourceSnapshot,
    ) -> bool:
        """Publish resource ownership for the exact currently running attempt."""
        with self._lock:
            backup = self._capture_state_locked()
            managed = self._active.get(job_id)
            if managed is None or managed.runtime.task is not task:
                return False
            managed.snapshot = replace(managed.snapshot, resources=resources)
            if self._persist_locked() is not None:
                self._restore_state_locked(backup)
                return False
            return True

    def set_desired_state(  # noqa: PLR0912 - explicit lifecycle matrix
        self,
        job_id: str,
        desired_state: DesiredJobState,
        *,
        expected_revision: int | None = None,
        mode: Literal["graceful", "force"] = "graceful",
    ) -> JobOutcome:
        """Set operator intent for one exact job and request cooperative control.

        Replays of the current desired state are successful even when the supplied
        revision is stale. This lets clients safely retry a request whose response
        was lost without weakening optimistic concurrency for real state changes.
        """
        command = "set_desired_state"
        with self._lock:
            backup = self._capture_state_locked()
            managed = self._active.get(job_id)
            terminal = (
                None if managed is not None else self._get_terminal_locked(job_id)
            )
            if managed is None and terminal is None:
                return self._error(command, "job_not_found", "The job was not found.")
            target = managed if managed is not None else terminal
            if mode == "force":
                return self._error(
                    command,
                    "force_termination_unavailable",
                    "Per-job force termination is unavailable for this runtime.",
                    target,
                )
            if mode != "graceful":
                return self._error(
                    command,
                    "invalid_control_mode",
                    f"Unsupported control mode {mode!r}.",
                    target,
                )
            if managed is None:
                assert terminal is not None
                if (
                    terminal.snapshot.state is JobState.CANCELLED
                    and desired_state is DesiredJobState.CANCELLED
                ):
                    return self._already_satisfied(command, terminal)
                return self._error(
                    command,
                    "invalid_transition",
                    "A terminal job cannot change desired state.",
                    terminal,
                )
            if managed.snapshot.desired_state is desired_state:
                return self._already_satisfied(command, managed)
            if (
                expected_revision is not None
                and expected_revision != managed.snapshot.revision
            ):
                return self._error(
                    command,
                    "revision_conflict",
                    (
                        f"Expected revision {expected_revision}, but the job is at "
                        f"revision {managed.snapshot.revision}."
                    ),
                    managed,
                )

            state = managed.snapshot.state
            if desired_state is DesiredJobState.PAUSED:
                outcome = self._request_pause_locked(command, managed, state)
            elif desired_state is DesiredJobState.RUNNING:
                outcome = self._request_resume_locked(command, managed, state)
            else:
                outcome = self._request_cancel_locked(command, managed, state)
            if outcome.status is JobOutcomeStatus.ERROR:
                return outcome

            persistence_error = self._persist_locked()
            if persistence_error is not None:
                self._restore_state_locked(backup)
                if (
                    outcome.code == "pause_withdrawn"
                    and managed.runtime.control is not None
                ):
                    managed.runtime.control.request_pause()
                return self._persistence_error(
                    command,
                    persistence_error,
                    self._get_locked(job_id),
                )
            owner = managed.runtime
            if outcome.code == "pause_requested" and owner.control is not None:
                owner.control.request_pause()
            elif outcome.code == "cancellation_requested" and owner.control is not None:
                owner.control.request_cancel()
            return outcome

    def acknowledge_control(
        self,
        job_id: str,
        *,
        attempt: int,
        task: asyncio.Task[Any],
    ) -> JobOutcome:
        """Acknowledge safe attempt unwind without accepting stale callbacks."""
        command = "acknowledge_control"
        with self._lock:
            managed = self._active.get(job_id)
            if managed is None:
                terminal = self._get_terminal_locked(job_id)
                if terminal is not None:
                    return JobOutcome(
                        command=command,
                        status=JobOutcomeStatus.OK,
                        code="terminal_state_preserved",
                        message=(
                            "The job is already terminal; its first outcome was kept."
                        ),
                        job=self._snapshot_locked(terminal),
                    )
                return self._error(command, "job_not_found", "The job was not found.")
            if (
                managed.snapshot.attempt.number != attempt
                or managed.runtime.task is not task
            ):
                return JobOutcome(
                    command=command,
                    status=JobOutcomeStatus.OK,
                    code="stale_attempt_ignored",
                    message="A stale attempt acknowledgement was ignored.",
                    job=self._snapshot_locked(managed),
                )

            resources = managed.snapshot.resources
            if managed.runtime.worker_active or any(
                (
                    resources.index_capacity_held,
                    resources.project_lease_held,
                    resources.writer_lock_held,
                    resources.pipeline_active,
                )
            ):
                return self._error(
                    command,
                    "resources_still_owned",
                    (
                        "The attempt cannot acknowledge control before releasing "
                        "resources."
                    ),
                    managed,
                )

            state = managed.snapshot.state
            if state not in {JobState.PAUSING, JobState.CANCELLING}:
                return JobOutcome(
                    command=command,
                    status=JobOutcomeStatus.OK,
                    code="control_acknowledgement_ignored",
                    message="The job no longer has a pending control acknowledgement.",
                    job=self._snapshot_locked(managed),
                )

            now = time.time()
            managed.runtime = JobRuntimeOwner(task=None, control=None)
            if (
                state is JobState.PAUSING
                and managed.snapshot.desired_state is DesiredJobState.RUNNING
            ):
                self._queue_resumed_attempt_locked(managed, now=now)
                persistence_error = self._persist_locked()
                if persistence_error is not None:
                    return self._persistence_error(
                        command,
                        persistence_error,
                        self._snapshot_locked(managed),
                    )
                return JobOutcome(
                    command=command,
                    status=JobOutcomeStatus.ACCEPTED,
                    code="resume_requeued",
                    message="The unwound job queued a new reconciliation attempt.",
                    job=self._snapshot_locked(managed),
                )

            acknowledged_state = (
                JobState.PAUSED if state is JobState.PAUSING else JobState.CANCELLED
            )
            self._replace_snapshot_locked(
                managed,
                state=acknowledged_state,
                desired_state=(
                    DesiredJobState.PAUSED
                    if acknowledged_state is JobState.PAUSED
                    else DesiredJobState.CANCELLED
                ),
                now=now,
                control_acknowledged_at=now,
                finished_at=now if acknowledged_state.is_terminal else None,
            )
            if acknowledged_state.is_terminal:
                self._archive_terminal_locked(managed)
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                return self._persistence_error(
                    command,
                    persistence_error,
                    self._snapshot_locked(managed),
                )
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="control_acknowledged",
                message=f"The job acknowledged {acknowledged_state.value}.",
                job=self._snapshot_locked(managed),
            )

    def finish_attempt(
        self,
        job_id: str,
        *,
        attempt: int,
        task: asyncio.Task[Any],
        state: JobState,
        result: str | None = None,
        error_kind: str | None = None,
    ) -> JobOutcome:
        """Commit one attempt's terminal outcome with first-writer-wins semantics."""
        command = "finish_attempt"
        if not state.is_terminal:
            raise ValueError("attempt completion requires a terminal state")
        with self._lock:
            managed = self._active.get(job_id)
            if managed is None:
                terminal = self._get_terminal_locked(job_id)
                if terminal is not None:
                    return JobOutcome(
                        command=command,
                        status=JobOutcomeStatus.OK,
                        code="terminal_state_preserved",
                        message="The first terminal outcome was preserved.",
                        job=self._snapshot_locked(terminal),
                    )
                return self._error(command, "job_not_found", "The job was not found.")
            if (
                managed.snapshot.attempt.number != attempt
                or managed.runtime.task is not task
            ):
                return JobOutcome(
                    command=command,
                    status=JobOutcomeStatus.OK,
                    code="stale_attempt_ignored",
                    message="A stale attempt completion was ignored.",
                    job=self._snapshot_locked(managed),
                )

            now = time.time()
            managed.runtime = JobRuntimeOwner(task=None, control=None)
            self._replace_snapshot_locked(
                managed,
                state=state,
                desired_state=(
                    DesiredJobState.CANCELLED
                    if state is JobState.CANCELLED
                    else managed.snapshot.desired_state
                ),
                now=now,
                finished_at=now,
                result=result,
                error_kind=error_kind,
            )
            self._archive_terminal_locked(managed)
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                return self._persistence_error(
                    command,
                    persistence_error,
                    self._snapshot_locked(managed),
                )
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="job_finished",
                message=f"The job finished as {state.value}.",
                job=self._snapshot_locked(managed),
            )

    def retry(
        self,
        job_id: str,
        *,
        initiator: JobInitiator | None = None,
    ) -> JobOutcome:
        """Create a new job linked to one retryable terminal resource."""
        command = "retry"
        with self._lock:
            backup = self._capture_state_locked()
            parent = self._get_terminal_locked(job_id)
            if parent is None:
                active = self._active.get(job_id)
                if active is not None:
                    return self._error(
                        command,
                        "job_not_terminal",
                        "Only terminal jobs can be retried.",
                        active,
                    )
                return self._error(command, "job_not_found", "The job was not found.")
            if parent.snapshot.state not in {
                JobState.FAILED,
                JobState.CANCELLED,
                JobState.INTERRUPTED,
            }:
                return self._error(
                    command,
                    "job_not_retryable",
                    "Succeeded jobs are recreated through ordinary job creation.",
                    parent,
                )
            if len(self._active) >= self._max_nonterminal:
                return self._error(
                    command,
                    "job_capacity_exceeded",
                    (
                        "The service has reached its configured nonterminal job "
                        f"capacity ({self._max_nonterminal})."
                    ),
                    parent,
                )
            equivalent = self._find_equivalent_active_locked(parent.snapshot.spec)
            if equivalent is not None:
                return JobOutcome(
                    command=command,
                    status=JobOutcomeStatus.ERROR,
                    code="active_job_exists",
                    message="Equivalent active work is already registered.",
                    job=equivalent,
                )

            now = time.time()
            new_id = str(uuid.uuid4())
            retried = JobSnapshot(
                id=new_id,
                revision=1,
                spec=parent.snapshot.spec,
                state=JobState.QUEUED,
                desired_state=DesiredJobState.RUNNING,
                capabilities=self._capabilities_for(
                    parent.snapshot.spec,
                    JobState.QUEUED,
                ),
                attempt=JobAttempt(number=1, parent_job_id=parent.snapshot.id),
                timestamps=JobTimestamps(created_at=now, state_changed_at=now),
                progress=None,
                result=None,
                error_kind=None,
                initiator=initiator or parent.snapshot.initiator,
                runtime=self._process_runtime_snapshot(),
                resources=JobResourceSnapshot(started=None, finished=None),
            )
            managed = _ManagedJob(
                snapshot=retried,
                runtime=JobRuntimeOwner(task=None, control=None),
            )
            self._active[new_id] = managed
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                self._restore_state_locked(backup)
                return self._persistence_error(
                    command,
                    persistence_error,
                    parent.snapshot,
                )
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.ACCEPTED,
                code="job_retry_created",
                message="A linked retry job was admitted.",
                job=retried,
            )

    def delete(self, job_id: str) -> JobOutcome:
        """Delete retained terminal history; never cancel nonterminal work."""
        command = "delete"
        with self._lock:
            backup = self._capture_state_locked()
            active = self._active.get(job_id)
            if active is not None:
                return self._error(
                    command,
                    "job_not_terminal",
                    "Nonterminal work must be cancelled before deletion.",
                    active,
                )
            terminal = self._get_terminal_locked(job_id)
            if terminal is None:
                return self._error(command, "job_not_found", "The job was not found.")
            self._terminal.remove(terminal)
            self._forget_idempotency_locked(job_id)
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                self._restore_state_locked(backup)
                return self._persistence_error(
                    command,
                    persistence_error,
                    self._get_locked(job_id),
                )
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="job_deleted",
                message="The terminal job history was deleted.",
                job=self._snapshot_locked(terminal),
            )

    def restore_persisted(self) -> JobOutcome:  # noqa: PLR0912 - recovery matrix
        """Restore durable jobs without partially applying an invalid state file."""
        command = "restore_jobs"
        path = self._state_path
        if path is None:
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="persistence_disabled",
                message="This job manager has no persistence path.",
            )
        try:
            payload: object = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="no_persisted_jobs",
                message="No persisted job state exists.",
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return self._persistence_error(command, str(exc), code="job_state_invalid")

        try:
            restored_jobs, restored_bindings = _parse_persisted_manager_state(payload)
        except (KeyError, TypeError, ValueError) as exc:
            return self._persistence_error(command, str(exc), code="job_state_invalid")

        active_count = sum(
            job.state in {JobState.QUEUED, JobState.PAUSED} for job in restored_jobs
        )
        if active_count > self._max_nonterminal:
            return self._persistence_error(
                command,
                (
                    f"persisted nonterminal count {active_count} exceeds configured "
                    f"capacity {self._max_nonterminal}"
                ),
                code="job_state_capacity_exceeded",
            )
        if len(restored_bindings) > self._max_idempotency:
            return self._persistence_error(
                command,
                (
                    f"persisted idempotency count {len(restored_bindings)} exceeds "
                    f"configured retention {self._max_idempotency}"
                ),
                code="job_state_capacity_exceeded",
            )

        with self._lock:
            if self._active or self._terminal:
                return self._error(
                    command,
                    "manager_not_empty",
                    "Persisted state can only be restored into an empty manager.",
                )
            backup = self._capture_state_locked()
            now = time.time()
            for snapshot in restored_jobs:
                managed = _ManagedJob(
                    snapshot=replace(
                        snapshot,
                        runtime=self._process_runtime_snapshot(),
                        resources=replace(
                            snapshot.resources,
                            index_capacity_held=False,
                            project_lease_held=False,
                            writer_lock_held=False,
                            pipeline_active=False,
                        ),
                    ),
                    runtime=JobRuntimeOwner(task=None, control=None),
                )
                if snapshot.state in {JobState.QUEUED, JobState.PAUSED}:
                    self._active[snapshot.id] = managed
                elif snapshot.state in {
                    JobState.RUNNING,
                    JobState.PAUSING,
                    JobState.CANCELLING,
                }:
                    self._active[snapshot.id] = managed
                    self._replace_snapshot_locked(
                        managed,
                        state=JobState.INTERRUPTED,
                        desired_state=snapshot.desired_state,
                        now=now,
                        finished_at=now,
                        result="The service stopped before the attempt acknowledged.",
                        error_kind="interrupted",
                    )
                    self._archive_terminal_locked(managed)
                else:
                    self._terminal.append(managed)

            retained_ids = {
                *self._active,
                *(managed.snapshot.id for managed in self._terminal),
            }
            for key, binding in restored_bindings:
                if binding.job_id in retained_ids:
                    self._bind_idempotency_locked(
                        key,
                        binding.signature,
                        binding.job_id,
                    )
            while len(self._terminal) > self._max_terminal_history:
                evicted = self._terminal.popleft()
                self._forget_idempotency_locked(evicted.snapshot.id)

            persistence_error = self._persist_locked()
            if persistence_error is not None:
                self._restore_state_locked(backup)
                return self._persistence_error(command, persistence_error)
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="job_state_restored",
                message=(
                    f"Restored {len(self._active)} nonterminal jobs and "
                    f"{len(self._terminal)} interrupted records."
                ),
            )

    def _request_pause_locked(
        self,
        command: str,
        managed: _ManagedJob,
        state: JobState,
    ) -> JobOutcome:
        if state is JobState.QUEUED:
            now = time.time()
            self._replace_snapshot_locked(
                managed,
                state=JobState.PAUSED,
                desired_state=DesiredJobState.PAUSED,
                now=now,
                control_requested_at=now,
                control_acknowledged_at=now,
            )
            code = "job_paused"
            status = JobOutcomeStatus.OK
        elif state is JobState.RUNNING:
            now = time.time()
            self._replace_snapshot_locked(
                managed,
                state=JobState.PAUSING,
                desired_state=DesiredJobState.PAUSED,
                now=now,
                control_requested_at=now,
            )
            code = "pause_requested"
            status = JobOutcomeStatus.ACCEPTED
        else:
            return self._error(
                command,
                "invalid_transition",
                f"A {state.value} job cannot be paused.",
                managed,
            )
        return JobOutcome(
            command=command,
            status=status,
            code=code,
            message="The pause request was applied.",
            job=self._snapshot_locked(managed),
        )

    def _request_resume_locked(
        self,
        command: str,
        managed: _ManagedJob,
        state: JobState,
    ) -> JobOutcome:
        now = time.time()
        code = "resume_requested"
        if state is JobState.PAUSED:
            self._queue_resumed_attempt_locked(managed, now=now)
        elif state is JobState.PAUSING:
            control = managed.runtime.control
            task = managed.runtime.task
            if task is None:
                self._queue_resumed_attempt_locked(managed, now=now)
            elif control is not None and control.request_resume():
                self._replace_snapshot_locked(
                    managed,
                    state=JobState.RUNNING,
                    desired_state=DesiredJobState.RUNNING,
                    now=now,
                    control_requested_at=None,
                    control_acknowledged_at=None,
                )
                code = "pause_withdrawn"
            else:
                # The old attempt has crossed its safe unwind boundary. Keep
                # its pause request armed until cleanup acknowledges release,
                # then queue a new convergence attempt without exposing a
                # transient paused state.
                self._replace_snapshot_locked(
                    managed,
                    state=JobState.PAUSING,
                    desired_state=DesiredJobState.RUNNING,
                    now=now,
                )
        else:
            return self._error(
                command,
                "invalid_transition",
                f"A {state.value} job cannot be resumed.",
                managed,
            )
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.ACCEPTED,
            code=code,
            message="The job was queued to reconcile.",
            job=self._snapshot_locked(managed),
        )

    def _queue_resumed_attempt_locked(
        self,
        managed: _ManagedJob,
        *,
        now: float,
    ) -> None:
        previous_attempt = managed.snapshot.attempt.number
        self._replace_snapshot_locked(
            managed,
            state=JobState.QUEUED,
            desired_state=DesiredJobState.RUNNING,
            now=now,
            attempt=JobAttempt(
                number=previous_attempt + 1,
                parent_job_id=managed.snapshot.attempt.parent_job_id,
                resumed_from_attempt=previous_attempt,
                resume_strategy=ResumeStrategy.RECONCILE,
            ),
            started_at=None,
            control_requested_at=None,
            control_acknowledged_at=None,
        )

    def _request_cancel_locked(
        self,
        command: str,
        managed: _ManagedJob,
        state: JobState,
    ) -> JobOutcome:
        now = time.time()
        if state in {JobState.QUEUED, JobState.PAUSED}:
            self._replace_snapshot_locked(
                managed,
                state=JobState.CANCELLED,
                desired_state=DesiredJobState.CANCELLED,
                now=now,
                control_requested_at=now,
                control_acknowledged_at=now,
                finished_at=now,
            )
            self._archive_terminal_locked(managed)
            status = JobOutcomeStatus.OK
            code = "job_cancelled"
        elif state in {JobState.RUNNING, JobState.PAUSING}:
            self._replace_snapshot_locked(
                managed,
                state=JobState.CANCELLING,
                desired_state=DesiredJobState.CANCELLED,
                now=now,
                control_requested_at=now,
            )
            status = JobOutcomeStatus.ACCEPTED
            code = "cancellation_requested"
        else:
            return self._error(
                command,
                "invalid_transition",
                f"A {state.value} job cannot be cancelled.",
                managed,
            )
        return JobOutcome(
            command=command,
            status=status,
            code=code,
            message="The cancellation request was applied.",
            job=self._snapshot_locked(managed),
        )

    def _replace_snapshot_locked(
        self,
        managed: _ManagedJob,
        *,
        state: JobState,
        desired_state: DesiredJobState,
        now: float,
        attempt: JobAttempt | None = None,
        started_at: float | None | object = ...,
        control_requested_at: float | None | object = ...,
        control_acknowledged_at: float | None | object = ...,
        finished_at: float | None | object = ...,
        result: str | None | object = ...,
        error_kind: str | None | object = ...,
    ) -> None:
        previous = managed.snapshot
        timestamps = previous.timestamps
        managed.snapshot = replace(
            previous,
            revision=previous.revision + 1,
            state=state,
            desired_state=desired_state,
            capabilities=self._capabilities_for(previous.spec, state),
            attempt=attempt or previous.attempt,
            timestamps=replace(
                timestamps,
                state_changed_at=now,
                started_at=(
                    timestamps.started_at
                    if started_at is ...
                    else cast("float | None", started_at)
                ),
                control_requested_at=(
                    timestamps.control_requested_at
                    if control_requested_at is ...
                    else cast("float | None", control_requested_at)
                ),
                control_acknowledged_at=(
                    timestamps.control_acknowledged_at
                    if control_acknowledged_at is ...
                    else cast("float | None", control_acknowledged_at)
                ),
                finished_at=(
                    timestamps.finished_at
                    if finished_at is ...
                    else cast("float | None", finished_at)
                ),
            ),
            result=previous.result if result is ... else cast("str | None", result),
            error_kind=(
                previous.error_kind
                if error_kind is ...
                else cast("str | None", error_kind)
            ),
        )

    def _get_terminal_locked(self, job_id: str) -> _ManagedJob | None:
        for managed in reversed(self._terminal):
            if managed.snapshot.id == job_id:
                return managed
        return None

    def _already_satisfied(
        self,
        command: str,
        managed: _ManagedJob,
    ) -> JobOutcome:
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.OK,
            code="already_satisfied",
            message="The requested desired state is already set.",
            job=self._snapshot_locked(managed),
        )

    def _capture_state_locked(self) -> _ManagerStateBackup:
        managed_jobs = [*self._active.values(), *self._terminal]
        return _ManagerStateBackup(
            active=dict(self._active),
            terminal=deque(self._terminal),
            snapshots={job.snapshot.id: job.snapshot for job in managed_jobs},
            runtimes={job.snapshot.id: job.runtime for job in managed_jobs},
            idempotency=OrderedDict(self._idempotency),
            job_idempotency_keys={
                job_id: set(keys) for job_id, keys in self._job_idempotency_keys.items()
            },
        )

    def _restore_state_locked(self, backup: _ManagerStateBackup) -> None:
        for managed in [*backup.active.values(), *backup.terminal]:
            job_id = managed.snapshot.id
            snapshot = backup.snapshots.get(job_id)
            runtime = backup.runtimes.get(job_id)
            if snapshot is not None:
                managed.snapshot = snapshot
            if runtime is not None:
                managed.runtime = runtime
        self._active = backup.active
        self._terminal = backup.terminal
        self._idempotency = OrderedDict(backup.idempotency)
        self._job_idempotency_keys = backup.job_idempotency_keys

    def _persist_locked(self) -> str | None:
        path = self._state_path
        if path is None:
            return None
        active_ids = set(self._active)
        payload = {
            "schema": "vaultspec.rag.jobs",
            "version": 1,
            "jobs": [
                self._snapshot_locked(managed).to_dict()
                for managed in self._active.values()
            ],
            "idempotency": [
                _idempotency_binding_to_dict(key, binding)
                for key, binding in self._idempotency.items()
                if binding.job_id in active_ids
            ],
        }
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            _atomic_replace(temporary, path)
        except (OSError, TypeError, ValueError) as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.debug(
                    "could not remove failed job-state temp file", exc_info=True
                )
            logger.error("job state persistence failed: %s", exc)
            return str(exc)
        return None

    @staticmethod
    def _persistence_error(
        command: str,
        detail: str,
        job: JobSnapshot | None = None,
        *,
        code: str = "job_persistence_failed",
    ) -> JobOutcome:
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.ERROR,
            code=code,
            message=f"Job state could not be persisted: {detail}",
            job=job,
        )

    def _error(
        self,
        command: str,
        code: str,
        message: str,
        managed: _ManagedJob | None = None,
    ) -> JobOutcome:
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.ERROR,
            code=code,
            message=message,
            job=self._snapshot_locked(managed) if managed is not None else None,
        )

    def _get_locked(self, job_id: str) -> JobSnapshot | None:
        active = self._active.get(job_id)
        if active is not None:
            return self._snapshot_locked(active)
        terminal = self._get_terminal_locked(job_id)
        return self._snapshot_locked(terminal) if terminal is not None else None

    def _find_equivalent_active_locked(self, spec: JobSpec) -> JobSnapshot | None:
        identity = _active_work_identity(spec)
        for managed in self._active.values():
            if _active_work_identity(managed.snapshot.spec) == identity:
                return self._snapshot_locked(managed)
        return None

    def _archive_terminal_locked(self, managed: _ManagedJob) -> None:
        """Move one terminal resource into bounded history.

        Transition methods call this while holding ``self._lock``. Keeping the
        retention operation here makes it impossible for terminal eviction to
        touch the nonterminal ownership map.
        """
        if not managed.snapshot.state.is_terminal:
            raise ValueError("only terminal jobs may enter terminal history")
        self._active.pop(managed.snapshot.id, None)
        managed.runtime = JobRuntimeOwner(task=None, control=None)
        self._terminal.append(managed)
        while len(self._terminal) > self._max_terminal_history:
            evicted = self._terminal.popleft()
            self._forget_idempotency_locked(evicted.snapshot.id)

    def _snapshot_locked(self, managed: _ManagedJob) -> JobSnapshot:
        owner = managed.runtime
        task_active = owner.task is not None and not owner.task.done()
        runtime = replace(
            managed.snapshot.runtime,
            task_active=task_active,
            worker_active=owner.worker_active,
        )
        return replace(managed.snapshot, runtime=runtime)

    def _bind_idempotency_locked(
        self,
        key: str,
        signature: tuple[JobSpec, JobInitiator, bool],
        job_id: str,
    ) -> None:
        previous = self._idempotency.pop(key, None)
        if previous is not None:
            previous_keys = self._job_idempotency_keys.get(previous.job_id)
            if previous_keys is not None:
                previous_keys.discard(key)
                if not previous_keys:
                    self._job_idempotency_keys.pop(previous.job_id, None)
        self._idempotency[key] = _IdempotencyBinding(signature, job_id)
        self._job_idempotency_keys.setdefault(job_id, set()).add(key)
        while len(self._idempotency) > self._max_idempotency:
            evicted_key, evicted = self._idempotency.popitem(last=False)
            job_keys = self._job_idempotency_keys.get(evicted.job_id)
            if job_keys is not None:
                job_keys.discard(evicted_key)
                if not job_keys:
                    self._job_idempotency_keys.pop(evicted.job_id, None)

    def _forget_idempotency_locked(self, job_id: str) -> None:
        for key in self._job_idempotency_keys.pop(job_id, set()):
            binding = self._idempotency.get(key)
            if binding is not None and binding.job_id == job_id:
                self._idempotency.pop(key, None)

    @staticmethod
    def _normalize_idempotency_key(key: str | None) -> str | None:
        if key is None:
            return None
        normalized = key.strip()
        if not normalized:
            raise ValueError("idempotency_key must not be empty")
        if len(normalized) > _MAX_IDEMPOTENCY_KEY_LENGTH:
            raise ValueError(
                "idempotency_key must not exceed "
                f"{_MAX_IDEMPOTENCY_KEY_LENGTH} characters"
            )
        return normalized

    @staticmethod
    def _capabilities_for(spec: JobSpec, state: JobState) -> JobCapabilities:
        return _capabilities_for_state(spec, state)

    @staticmethod
    def _process_runtime_snapshot() -> JobRuntimeSnapshot:
        return JobRuntimeSnapshot(
            pid=os.getpid(),
            parent_pid=os.getppid(),
            user=getpass.getuser(),
            executable=sys.executable,
            prefix=sys.prefix,
            base_prefix=sys.base_prefix,
            virtual_env=os.environ.get("VIRTUAL_ENV"),
        )


def _idempotency_binding_to_dict(
    key: str,
    binding: _IdempotencyBinding,
) -> dict[str, object]:
    spec, initiator, start_paused = binding.signature
    return {
        "key": key,
        "job_id": binding.job_id,
        "spec": {
            "operation": spec.operation.value,
            "source": spec.source.value,
            "project_root": spec.project_root,
            "mode": spec.mode.value if spec.mode is not None else None,
        },
        "initiator": {
            "kind": initiator.kind,
            "command": initiator.command,
            "project_root": initiator.project_root,
        },
        "start_paused": start_paused,
    }


def _atomic_replace(source: Path, destination: Path) -> None:
    """Replace one state file, tolerating bounded Windows reader contention."""
    for attempt in range(_ATOMIC_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt + 1 == _ATOMIC_REPLACE_ATTEMPTS:
                raise
            time.sleep(_ATOMIC_REPLACE_RETRY_SECONDS * (attempt + 1))


def _job_spec_error(spec: JobSpec) -> str | None:
    if spec.operation is not JobOperation.INDEX:
        return "Only indexing operations are managed by the controllable job runtime."
    if spec.source not in {JobSource.VAULT, JobSource.CODE}:
        return "Indexing jobs require a vault or code source."
    if spec.mode is None:
        return "Indexing jobs require an incremental or rebuild mode."
    if spec.project_root is not None and not spec.project_root.strip():
        return "project_root must be omitted or a non-empty path."
    return None


def _active_work_identity(
    spec: JobSpec,
) -> tuple[JobOperation, JobSource, JobMode | None, str | None]:
    root = spec.project_root
    normalized_root = (
        None
        if root is None
        else os.path.normcase(
            os.path.realpath(os.path.abspath(os.path.expanduser(root)))
        )
    )
    return spec.operation, spec.source, spec.mode, normalized_root


def _capabilities_for_state(spec: JobSpec, state: JobState) -> JobCapabilities:
    if spec.operation is not JobOperation.INDEX or spec.source is JobSource.MAINTENANCE:
        return JobCapabilities(
            pausable=False,
            resumable=False,
            cancellable=False,
            retryable=False,
            deletable=False,
        )
    return JobCapabilities(
        pausable=state in {JobState.QUEUED, JobState.RUNNING},
        resumable=state in {JobState.PAUSING, JobState.PAUSED},
        cancellable=not state.is_terminal,
        retryable=state in {JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED},
        deletable=state.is_terminal,
    )


def _parse_persisted_manager_state(
    payload: object,
) -> tuple[list[JobSnapshot], list[tuple[str, _IdempotencyBinding]]]:
    root = _required_mapping(payload, "job state")
    if root.get("schema") != "vaultspec.rag.jobs" or root.get("version") != 1:
        raise ValueError("unsupported job-state schema or version")
    raw_jobs = _required_list(root.get("jobs"), "jobs")
    jobs = [_job_snapshot_from_dict(item) for item in raw_jobs]
    ids = [job.id for job in jobs]
    if len(ids) != len(set(ids)):
        raise ValueError("persisted job IDs must be unique")

    raw_bindings = _required_list(root.get("idempotency"), "idempotency")
    bindings: list[tuple[str, _IdempotencyBinding]] = []
    keys: set[str] = set()
    for item in raw_bindings:
        record = _required_mapping(item, "idempotency entry")
        key = _required_str(record.get("key"), "idempotency key")
        if len(key) > _MAX_IDEMPOTENCY_KEY_LENGTH:
            raise ValueError("persisted idempotency key exceeds the supported length")
        if key in keys:
            raise ValueError("persisted idempotency keys must be unique")
        keys.add(key)
        job_id = _required_str(record.get("job_id"), "idempotency job_id")
        spec = _job_spec_from_dict(record.get("spec"))
        initiator = _job_initiator_from_dict(record.get("initiator"))
        start_paused = record.get("start_paused")
        if not isinstance(start_paused, bool):
            raise TypeError("idempotency start_paused must be boolean")
        bindings.append(
            (
                key,
                _IdempotencyBinding(
                    signature=(spec, initiator, start_paused),
                    job_id=job_id,
                ),
            )
        )
    _validate_persisted_generation(jobs, bindings)
    return jobs, bindings


def _validate_persisted_generation(
    jobs: list[JobSnapshot],
    bindings: list[tuple[str, _IdempotencyBinding]],
) -> None:
    by_id = {job.id: job for job in jobs}
    active_identities: set[
        tuple[JobOperation, JobSource, JobMode | None, str | None]
    ] = set()
    for job in jobs:
        _validate_persisted_job(job)
        if not job.state.is_terminal:
            identity = _active_work_identity(job.spec)
            if identity in active_identities:
                raise ValueError("persisted active jobs contain equivalent work")
            active_identities.add(identity)

    for key, binding in bindings:
        referenced = by_id.get(binding.job_id)
        if referenced is None:
            raise ValueError(f"idempotency key {key!r} references a missing job")
        spec, initiator, _start_paused = binding.signature
        if spec != referenced.spec or initiator != referenced.initiator:
            raise ValueError(
                f"idempotency key {key!r} does not match its referenced job"
            )


def _validate_persisted_job(job: JobSnapshot) -> None:
    spec_error = _job_spec_error(job.spec)
    if spec_error is not None:
        raise ValueError(f"job {job.id}: {spec_error}")
    _validate_persisted_timestamps(job)
    _validate_persisted_lifecycle(job)
    _validate_persisted_attempt(job)
    if (
        job.progress is not None
        and job.progress.total is not None
        and job.progress.completed > job.progress.total
    ):
        raise ValueError(f"job {job.id}: progress exceeds total")


def _validate_persisted_timestamps(job: JobSnapshot) -> None:
    timestamps = job.timestamps
    if timestamps.state_changed_at < timestamps.created_at:
        raise ValueError(f"job {job.id}: state change predates creation")
    for name, value in (
        ("started_at", timestamps.started_at),
        ("finished_at", timestamps.finished_at),
        ("control_requested_at", timestamps.control_requested_at),
        ("control_acknowledged_at", timestamps.control_acknowledged_at),
    ):
        if value is not None and value < timestamps.created_at:
            raise ValueError(f"job {job.id}: {name} predates creation")
    if (
        timestamps.control_requested_at is not None
        and timestamps.control_acknowledged_at is not None
        and timestamps.control_acknowledged_at < timestamps.control_requested_at
    ):
        raise ValueError(f"job {job.id}: control acknowledgement predates request")
    if job.state.is_terminal != (timestamps.finished_at is not None):
        raise ValueError(f"job {job.id}: terminal state and finish time disagree")


def _validate_persisted_lifecycle(job: JobSnapshot) -> None:
    expected_desired: dict[JobState, set[DesiredJobState]] = {
        JobState.QUEUED: {DesiredJobState.RUNNING},
        JobState.RUNNING: {DesiredJobState.RUNNING},
        JobState.PAUSING: {DesiredJobState.PAUSED, DesiredJobState.RUNNING},
        JobState.PAUSED: {DesiredJobState.PAUSED},
        JobState.CANCELLING: {DesiredJobState.CANCELLED},
        JobState.CANCELLED: {DesiredJobState.CANCELLED},
    }
    allowed_desired = expected_desired.get(job.state)
    if allowed_desired is not None and job.desired_state not in allowed_desired:
        raise ValueError(f"job {job.id}: observed and desired states disagree")
    if job.state not in {JobState.QUEUED, JobState.PAUSED}:
        return
    resources = job.resources
    if (
        job.runtime.task_active
        or job.runtime.worker_active
        or any(
            (
                resources.index_capacity_held,
                resources.project_lease_held,
                resources.writer_lock_held,
                resources.pipeline_active,
            )
        )
    ):
        raise ValueError(f"job {job.id}: inactive state retains live resources")


def _validate_persisted_attempt(job: JobSnapshot) -> None:
    attempt = job.attempt
    if attempt.resumed_from_attempt is None:
        if attempt.resume_strategy is not None:
            raise ValueError(f"job {job.id}: resume strategy lacks prior attempt")
    elif (
        attempt.resume_strategy is not ResumeStrategy.RECONCILE
        or attempt.number != attempt.resumed_from_attempt + 1
    ):
        raise ValueError(f"job {job.id}: invalid resume attempt lineage")
    if attempt.parent_job_id == job.id:
        raise ValueError(f"job {job.id}: retry parent cannot reference itself")


def _job_snapshot_from_dict(value: object) -> JobSnapshot:
    raw = _required_mapping(value, "job")
    spec = _job_spec_from_dict(raw.get("spec"))
    state = JobState(_required_str(raw.get("state"), "job state"))
    desired_state = DesiredJobState(
        _required_str(raw.get("desired_state"), "job desired_state")
    )
    attempt_number = _required_int(raw.get("attempt"), "job attempt", minimum=1)
    resumed_from = _optional_int(
        raw.get("resumed_from_attempt"),
        "job resumed_from_attempt",
        minimum=1,
    )
    resume_raw = _optional_str(raw.get("resume_strategy"), "job resume_strategy")
    progress_raw = raw.get("progress")
    progress = None if progress_raw is None else _job_progress_from_dict(progress_raw)
    return JobSnapshot(
        id=_required_str(raw.get("id"), "job id"),
        revision=_required_int(raw.get("revision"), "job revision", minimum=1),
        spec=spec,
        state=state,
        desired_state=desired_state,
        capabilities=_capabilities_for_state(spec, state),
        attempt=JobAttempt(
            number=attempt_number,
            parent_job_id=_optional_str(raw.get("parent_job_id"), "parent_job_id"),
            resumed_from_attempt=resumed_from,
            resume_strategy=ResumeStrategy(resume_raw)
            if resume_raw is not None
            else None,
        ),
        timestamps=JobTimestamps(
            created_at=_required_float(raw.get("created_at"), "created_at"),
            state_changed_at=_required_float(
                raw.get("state_changed_at"), "state_changed_at"
            ),
            started_at=_optional_float(raw.get("started_at"), "started_at"),
            finished_at=_optional_float(raw.get("finished_at"), "finished_at"),
            control_requested_at=_optional_float(
                raw.get("control_requested_at"), "control_requested_at"
            ),
            control_acknowledged_at=_optional_float(
                raw.get("control_acknowledged_at"), "control_acknowledged_at"
            ),
        ),
        progress=progress,
        result=_optional_str(raw.get("result"), "job result"),
        error_kind=_optional_str(raw.get("error_kind"), "job error_kind"),
        initiator=_job_initiator_from_dict(raw.get("initiator")),
        runtime=_job_runtime_from_dict(raw.get("runtime")),
        resources=_job_resources_from_dict(raw.get("resources")),
    )


def _job_spec_from_dict(value: object) -> JobSpec:
    raw = _required_mapping(value, "job spec")
    mode = _optional_str(raw.get("mode"), "job mode")
    return JobSpec(
        operation=JobOperation(_required_str(raw.get("operation"), "job operation")),
        source=JobSource(_required_str(raw.get("source"), "job source")),
        project_root=_optional_str(raw.get("project_root"), "job project_root"),
        mode=JobMode(mode) if mode is not None else None,
    )


def _job_initiator_from_dict(value: object) -> JobInitiator:
    raw = _required_mapping(value, "job initiator")
    return JobInitiator(
        kind=_required_str(raw.get("kind"), "initiator kind"),
        command=_required_str(raw.get("command"), "initiator command"),
        project_root=_optional_str(raw.get("project_root"), "initiator project_root"),
    )


def _job_progress_from_dict(value: object) -> JobProgress:
    raw = _required_mapping(value, "job progress")
    return JobProgress(
        step=_required_str(raw.get("step"), "progress step"),
        completed=_required_int(raw.get("completed"), "progress completed", minimum=0),
        total=_optional_int(raw.get("total"), "progress total", minimum=0),
        last_updated=_required_float(raw.get("last_updated"), "progress last_updated"),
    )


def _job_runtime_from_dict(value: object) -> JobRuntimeSnapshot:
    raw = _required_mapping(value, "job runtime")
    task_active = raw.get("task_active")
    worker_active = raw.get("worker_active")
    if not isinstance(task_active, bool) or not isinstance(worker_active, bool):
        raise TypeError("runtime activity fields must be boolean")
    return JobRuntimeSnapshot(
        pid=_required_int(raw.get("pid"), "runtime pid", minimum=0),
        parent_pid=_required_int(
            raw.get("parent_pid"), "runtime parent_pid", minimum=0
        ),
        user=_required_str(raw.get("user"), "runtime user", allow_empty=True),
        executable=_required_str(
            raw.get("executable"), "runtime executable", allow_empty=True
        ),
        prefix=_required_str(raw.get("prefix"), "runtime prefix", allow_empty=True),
        base_prefix=_required_str(
            raw.get("base_prefix"), "runtime base_prefix", allow_empty=True
        ),
        virtual_env=_optional_str(raw.get("virtual_env"), "runtime virtual_env"),
        task_active=task_active,
        worker_active=worker_active,
    )


def _job_resources_from_dict(value: object) -> JobResourceSnapshot:
    raw = _required_mapping(value, "job resources")
    booleans: dict[str, bool] = {}
    for field in (
        "index_capacity_held",
        "project_lease_held",
        "writer_lock_held",
        "pipeline_active",
    ):
        field_value = raw.get(field)
        if not isinstance(field_value, bool):
            raise TypeError(f"resource {field} must be boolean")
        booleans[field] = field_value
    return JobResourceSnapshot(
        started=_process_resources_from_dict(raw.get("started")),
        finished=_process_resources_from_dict(raw.get("finished")),
        index_capacity_held=booleans["index_capacity_held"],
        project_lease_held=booleans["project_lease_held"],
        writer_lock_held=booleans["writer_lock_held"],
        pipeline_active=booleans["pipeline_active"],
    )


def _process_resources_from_dict(value: object) -> ProcessResourceSnapshot | None:
    if value is None:
        return None
    raw = _required_mapping(value, "process resources")
    return ProcessResourceSnapshot(
        rss_mb=_required_nonnegative_float(raw.get("rss_mb"), "resource rss_mb"),
        cuda_allocated_mb=_required_nonnegative_float(
            raw.get("cuda_allocated_mb"), "resource cuda_allocated_mb"
        ),
        cuda_reserved_mb=_required_nonnegative_float(
            raw.get("cuda_reserved_mb"), "resource cuda_reserved_mb"
        ),
    )


def _required_mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object with string keys")
    untyped = cast("dict[object, object]", value)
    if not all(isinstance(key, str) for key in untyped):
        raise TypeError(f"{name} must be an object with string keys")
    return cast("dict[str, object]", value)


def _required_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    return cast("list[object]", value)


def _required_str(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _optional_str(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _required_str(value, name, allow_empty=True)


def _required_int(value: object, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TypeError(f"{name} must be an integer of at least {minimum}")
    return value


def _optional_int(value: object, name: str, *, minimum: int) -> int | None:
    if value is None:
        return None
    return _required_int(value, name, minimum=minimum)


def _required_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError(f"{name} must be finite")
    return resolved


def _required_nonnegative_float(value: object, name: str) -> float:
    resolved = _required_float(value, name)
    if resolved < 0:
        raise ValueError(f"{name} must not be negative")
    return resolved


def _optional_float(value: object, name: str) -> float | None:
    if value is None:
        return None
    return _required_float(value, name)


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
