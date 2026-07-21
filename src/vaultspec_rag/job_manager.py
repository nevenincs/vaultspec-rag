"""Service-domain ownership and lifecycle orchestration for canonical jobs."""

from __future__ import annotations

import getpass
import logging
import os
import sys
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from . import job_persistence as _job_persistence
from .config import get_config
from .job_models import (
    DesiredJobState,
    JobAttempt,
    JobCapabilities,
    JobInitiator,
    JobOutcome,
    JobOutcomeStatus,
    JobProgress,
    JobResourceSnapshot,
    JobRuntimeSnapshot,
    JobSnapshot,
    JobSpec,
    JobState,
    JobTimestamps,
    ResumeStrategy,
)
from .job_models import (
    active_work_identity as _active_work_identity,
)
from .job_models import (
    capabilities_for_state as _capabilities_for_state,
)
from .job_models import (
    job_spec_error as _job_spec_error,
)

if TYPE_CHECKING:
    import asyncio

    from .job_control import RunControlToken

# Preserve the established logger surface while the compatibility module remains public.
logger = logging.getLogger(f"{__package__}.jobs")

__all__ = ["MAX_RECORDS", "JobManager"]

# Bounded ring buffer cap. Generous enough to retain a meaningful recent
# history without unbounded growth; the oldest record is evicted past this.
MAX_RECORDS = 256
_MANAGED_STATE_FILENAME = "jobs-state.json"


class _ConfiguredStatePath:
    __slots__ = ()


_CONFIGURED_STATE_PATH = _ConfiguredStatePath()


@dataclass(frozen=True, slots=True)
class _JobRuntimeOwner:
    """Strong references to the live execution for one exact job ID."""

    task: asyncio.Task[Any] | None
    control: RunControlToken | None
    worker_active: bool = False


@dataclass(slots=True)
class _ManagedJob:
    snapshot: JobSnapshot
    runtime: _JobRuntimeOwner


@dataclass(slots=True)
class _ManagerStateBackup:
    active: dict[str, _ManagedJob]
    terminal: deque[_ManagedJob]
    snapshots: dict[str, JobSnapshot]
    runtimes: dict[str, _JobRuntimeOwner]
    idempotency: OrderedDict[str, _job_persistence.IdempotencyBinding]
    job_idempotency_keys: dict[str, set[str]]
    persistence_dirty: bool


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
        self._idempotency: OrderedDict[str, _job_persistence.IdempotencyBinding] = (
            OrderedDict()
        )
        self._job_idempotency_keys: dict[str, set[str]] = {}
        self._persistence_dirty = False

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

    @property
    def persistence_dirty(self) -> bool:
        """Return whether the latest in-memory generation still needs flushing."""
        with self._lock:
            return self._persistence_dirty

    def create(  # noqa: C901, PLR0912 - admission/replay matrix
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
                        if not persistence_error.published:
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
                    control_requested_at=now if start_paused else None,
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
                runtime=_JobRuntimeOwner(task=None, control=None),
            )
            if normalized_key is not None:
                self._bind_idempotency_locked(
                    normalized_key,
                    signature,
                    resolved_id,
                )

            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                return self._persistence_error(
                    "create",
                    persistence_error,
                    self._get_locked(resolved_id),
                )

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

            managed.runtime = _JobRuntimeOwner(task=task, control=control)
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
                if not persistence_error.published:
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

    def update_progress(
        self,
        job_id: str,
        *,
        attempt: int,
        task: asyncio.Task[Any],
        step: str,
        completed: int = 0,
        total: int | None = None,
    ) -> JobOutcome:
        """Publish progress only from the exact task owning the current attempt."""
        command = "update_progress"
        raw_step = cast("object", step)
        raw_completed = cast("object", completed)
        raw_total = cast("object", total)
        if not isinstance(raw_step, str) or not raw_step.strip():
            return self._error(
                command, "invalid_progress", "Progress step is required."
            )
        if (
            not isinstance(raw_completed, int)
            or isinstance(raw_completed, bool)
            or raw_completed < 0
            or (
                raw_total is not None
                and (
                    not isinstance(raw_total, int)
                    or isinstance(raw_total, bool)
                    or raw_total < raw_completed
                )
            )
        ):
            return self._error(
                command,
                "invalid_progress",
                (
                    "Progress counts must satisfy 0 <= completed <= total when "
                    "total is set."
                ),
            )
        normalized_step = raw_step.strip()
        normalized_total = raw_total
        with self._lock:
            backup = self._capture_state_locked()
            managed = self._active.get(job_id)
            if managed is None:
                return self._error(command, "job_not_found", "The job was not found.")
            if (
                managed.snapshot.attempt.number != attempt
                or managed.runtime.task is not task
            ):
                return JobOutcome(
                    command=command,
                    status=JobOutcomeStatus.OK,
                    code="stale_attempt_ignored",
                    message="Progress from a stale attempt was ignored.",
                    job=self._snapshot_locked(managed),
                )
            if managed.snapshot.state not in {
                JobState.RUNNING,
                JobState.PAUSING,
                JobState.CANCELLING,
            }:
                return self._error(
                    command,
                    "invalid_transition",
                    "Only a live attempt can publish progress.",
                    managed,
                )
            previous = managed.snapshot
            managed.snapshot = replace(
                previous,
                revision=previous.revision + 1,
                progress=JobProgress(
                    step=normalized_step,
                    completed=raw_completed,
                    total=normalized_total,
                    last_updated=time.time(),
                ),
            )
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                return self._persistence_error(
                    command,
                    persistence_error,
                    self._get_locked(job_id),
                )
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="progress_updated",
                message="The current attempt progress was updated.",
                job=self._snapshot_locked(managed),
            )

    def flush_persistence(self) -> JobOutcome:
        """Idempotently retry the latest dirty manager generation."""
        command = "flush_persistence"
        with self._lock:
            if self._state_path is None:
                return JobOutcome(
                    command=command,
                    status=JobOutcomeStatus.OK,
                    code="persistence_disabled",
                    message="This job manager has no persistence path.",
                )
            if not self._persistence_dirty:
                return JobOutcome(
                    command=command,
                    status=JobOutcomeStatus.OK,
                    code="persistence_clean",
                    message="The latest manager generation is already durable.",
                )
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                return self._persistence_error(command, persistence_error)
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="persistence_flushed",
                message="The latest manager generation is durable.",
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
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
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
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
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
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                    if (
                        outcome.code == "pause_withdrawn"
                        and managed.runtime.control is not None
                    ):
                        managed.runtime.control.request_pause()
                else:
                    self._apply_control_signal_locked(managed, outcome.code)
                return self._persistence_error(
                    command,
                    persistence_error,
                    self._get_locked(job_id),
                )
            self._apply_control_signal_locked(managed, outcome.code)
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
            managed.runtime = _JobRuntimeOwner(task=None, control=None)
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
            managed.runtime = _JobRuntimeOwner(task=None, control=None)
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
                runtime=_JobRuntimeOwner(task=None, control=None),
            )
            self._active[new_id] = managed
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                return self._persistence_error(
                    command,
                    persistence_error,
                    (
                        self._get_locked(new_id)
                        if persistence_error.published
                        else parent.snapshot
                    ),
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
                if not persistence_error.published:
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
            persisted = _job_persistence.load_persisted_state(path)
        except FileNotFoundError:
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="no_persisted_jobs",
                message="No persisted job state exists.",
            )
        except (OSError, UnicodeError, KeyError, TypeError, ValueError) as exc:
            return self._persistence_error(command, str(exc), code="job_state_invalid")

        restored_jobs = persisted.jobs
        restored_bindings = persisted.bindings
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
        with self._lock:
            if self._active or self._terminal:
                return self._error(
                    command,
                    "manager_not_empty",
                    "Persisted state can only be restored into an empty manager.",
                )
            backup = self._capture_state_locked()
            now = time.time()
            restore_order = [
                *(job for job in restored_jobs if job.state.is_terminal),
                *(job for job in restored_jobs if not job.state.is_terminal),
            ]
            for snapshot in restore_order:
                restored_runtime = (
                    self._process_runtime_snapshot()
                    if snapshot.state in {JobState.QUEUED, JobState.PAUSED}
                    else replace(
                        snapshot.runtime,
                        task_active=False,
                        worker_active=False,
                    )
                )
                managed = _ManagedJob(
                    snapshot=replace(
                        snapshot,
                        runtime=restored_runtime,
                        resources=replace(
                            snapshot.resources,
                            index_capacity_held=False,
                            project_lease_held=False,
                            writer_lock_held=False,
                            pipeline_active=False,
                        ),
                    ),
                    runtime=_JobRuntimeOwner(task=None, control=None),
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

            while len(self._terminal) > self._max_terminal_history:
                evicted = self._terminal.popleft()
                self._forget_idempotency_locked(evicted.snapshot.id)
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

            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
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
            persistence_dirty=self._persistence_dirty,
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
        self._persistence_dirty = backup.persistence_dirty

    def _persist_locked(self) -> _job_persistence.PersistenceWriteError | None:
        path = self._state_path
        if path is None:
            self._persistence_dirty = False
            return None
        retained_ids = {
            *self._active,
            *(managed.snapshot.id for managed in self._terminal),
        }
        persisted = _job_persistence.PersistedManagerState(
            jobs=tuple(
                self._snapshot_locked(managed)
                for managed in [*self._active.values(), *self._terminal]
            ),
            bindings=tuple(
                (key, binding)
                for key, binding in self._idempotency.items()
                if binding.job_id in retained_ids
            ),
        )
        try:
            _job_persistence.save_persisted_state(path, persisted)
        except _job_persistence.PersistenceWriteError as exc:
            self._persistence_dirty = True
            logger.error("job state persistence failed: %s", exc)
            return exc
        self._persistence_dirty = False
        return None

    @staticmethod
    def _persistence_error(
        command: str,
        detail: str | _job_persistence.PersistenceWriteError,
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

    @staticmethod
    def _apply_control_signal_locked(managed: _ManagedJob, outcome_code: str) -> None:
        owner = managed.runtime
        if outcome_code == "pause_requested" and owner.control is not None:
            owner.control.request_pause()
        elif outcome_code == "cancellation_requested" and owner.control is not None:
            owner.control.request_cancel()

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
        managed.runtime = _JobRuntimeOwner(task=None, control=None)
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
        self._idempotency[key] = _job_persistence.IdempotencyBinding(signature, job_id)
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
        if len(normalized) > _job_persistence.MAX_IDEMPOTENCY_KEY_LENGTH:
            raise ValueError(
                "idempotency_key must not exceed "
                f"{_job_persistence.MAX_IDEMPOTENCY_KEY_LENGTH} characters"
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
