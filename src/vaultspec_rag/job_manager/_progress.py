"""Concrete job-manager responsibility owner."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import TYPE_CHECKING

from ..job_models import (
    DesiredJobState,
    IndexResilienceSnapshot,
    JobOutcome,
    JobOutcomeStatus,
    JobProgress,
    JobResourceSnapshot,
    JobState,
    ProcessResourceSnapshot,
)
from ..service_quiesce import QuiesceAdmissionClosedError
from .state import (
    JobManagerState,
    JobRuntimeOwner,
    assign_runtime_owner,
)

if TYPE_CHECKING:
    import asyncio
    import threading

    from ..job_control import RunControlToken
    from .models import ProgressUpdate, ResourceUpdate
    from .state import AttemptExit

logger = logging.getLogger("vaultspec_rag.jobs")


class JobManagerProgress(JobManagerState):
    def start_attempt(
        self,
        job_id: str,
        *,
        task: asyncio.Task[AttemptExit],
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
                not self._accepting_dispatch
                or managed.snapshot.state is not JobState.QUEUED
                or managed.snapshot.desired_state is not DesiredJobState.RUNNING
            ):
                return self._error(
                    command,
                    (
                        "dispatch_stopped"
                        if not self._accepting_dispatch
                        else "invalid_transition"
                    ),
                    (
                        "Managed dispatch is stopped for service shutdown."
                        if not self._accepting_dispatch
                        else "Only queued work with running desired state can start."
                    ),
                    managed,
                )
            if managed.runtime.task is not None:
                return self._error(
                    command,
                    "runtime_already_owned",
                    "The current attempt already has a runtime owner.",
                    managed,
                )

            try:
                ticket = self._quiesce_controller.acquire_ticket()
            except QuiesceAdmissionClosedError:
                return self._error(
                    command,
                    "quiesce_admission_closed",
                    "Service quiesce has closed compute admission.",
                    managed,
                )
            assign_runtime_owner(
                managed,
                JobRuntimeOwner(task=task, control=control, compute_ticket=ticket),
            )
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
        update: ProgressUpdate,
    ) -> JobOutcome:
        """Publish progress only from the exact task owning the current attempt.

        Progress is an advisory, high-frequency signal: the mutation lands in
        memory immediately and its durable write is coalesced onto the flush
        budget rather than paid per call, so loops that publish per item never
        pay a per-call fsync. Lifecycle transitions remain synchronously
        durable and carry any deferred progress with them. When a coalesced
        flush does run here, only the write happens outside the manager lock;
        a flush failure is surfaced on the publish that attempted it while the
        in-memory progress stays authoritative for the retrying flush.
        """
        command = "update_progress"
        normalized_progress = _normalize_progress(
            update.step, update.completed, update.total
        )
        if isinstance(normalized_progress, str):
            return self._error(
                command,
                "invalid_progress",
                normalized_progress,
            )
        normalized_step, normalized_completed, normalized_total = normalized_progress
        with self._lock:
            managed = self._active.get(job_id)
            if managed is None:
                return self._error(command, "job_not_found", "The job was not found.")
            if (
                managed.snapshot.attempt.number != update.attempt
                or managed.runtime.task is not update.task
            ):
                return JobOutcome(
                    command=command,
                    status=JobOutcomeStatus.OK,
                    code="stale_attempt_ignored",
                    message="Progress from a stale attempt was ignored.",
                    job=self._snapshot_locked(managed),
                )
            if not managed.snapshot.state.is_live_attempt:
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
                    completed=normalized_completed,
                    total=normalized_total,
                    last_updated=time.time(),
                ),
            )
            self._note_progress_mutation_locked()
            updated = JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="progress_updated",
                message="The current attempt progress was updated.",
                job=self._snapshot_locked(managed),
            )
            pending = self._begin_progress_flush_locked()
        if pending is not None:
            flush_error = self._complete_progress_flush(pending)
            if flush_error is not None:
                return self._persistence_error(
                    command,
                    flush_error,
                    self.get(job_id),
                )
        return updated

    def flush_persistence(self) -> JobOutcome:
        """Idempotently flush the latest dirty or deferred manager generation."""
        command = "flush_persistence"
        with self._lock:
            if self._state_path is None:
                return JobOutcome(
                    command=command,
                    status=JobOutcomeStatus.OK,
                    code="persistence_disabled",
                    message="This job manager has no persistence path.",
                )
            if (
                not self._persistence_dirty
                and self._flushed_generation == self._state_generation
            ):
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
        task: asyncio.Task[AttemptExit],
        active: bool,
        worker_thread: threading.Thread | None = None,
    ) -> bool:
        """Update worker ownership only for the currently attached attempt."""
        with self._lock:
            backup = self._capture_state_locked()
            managed = self._active.get(job_id)
            if managed is None or managed.runtime.task is not task:
                return False
            assign_runtime_owner(
                managed,
                replace(
                    managed.runtime,
                    worker_active=active,
                    worker_thread=worker_thread if active else None,
                ),
            )
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                return False
            return True

    def update_execution_resources(
        self,
        job_id: str,
        *,
        task: asyncio.Task[AttemptExit],
        update: ResourceUpdate,
    ) -> bool:
        with self._lock:
            backup = self._capture_state_locked()
            managed = self._active.get(job_id)
            if managed is None or managed.runtime.task is not task:
                return False
            previous = managed.snapshot.resources
            timestamps = managed.snapshot.timestamps
            managed.snapshot = replace(
                managed.snapshot,
                timestamps=(
                    timestamps
                    if update.admission_acquired_at is None
                    else replace(
                        timestamps,
                        admission_acquired_at=update.admission_acquired_at,
                    )
                ),
                gpu_lock_wait_seconds=(
                    managed.snapshot.gpu_lock_wait_seconds
                    if update.gpu_lock_wait_seconds is None
                    else update.gpu_lock_wait_seconds
                ),
                resources=replace(
                    previous,
                    started=(
                        previous.started if update.started is ... else update.started
                    ),
                    finished=(
                        previous.finished if update.finished is ... else update.finished
                    ),
                    index_capacity_held=(
                        previous.index_capacity_held
                        if update.index_capacity_held is None
                        else update.index_capacity_held
                    ),
                    project_lease_held=(
                        previous.project_lease_held
                        if update.project_lease_held is None
                        else update.project_lease_held
                    ),
                    writer_lock_held=(
                        previous.writer_lock_held
                        if update.writer_lock_held is None
                        else update.writer_lock_held
                    ),
                    pipeline_active=(
                        previous.pipeline_active
                        if update.pipeline_active is None
                        else update.pipeline_active
                    ),
                ),
            )
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                return False
            return True

    def update_resilience(
        self,
        job_id: str,
        *,
        task: asyncio.Task[AttemptExit],
        resilience: IndexResilienceSnapshot,
    ) -> bool:
        """Publish resilience state only for the currently attached attempt."""
        with self._lock:
            backup = self._capture_state_locked()
            managed = self._active.get(job_id)
            if managed is None or managed.runtime.task is not task:
                return False
            managed.snapshot = replace(
                managed.snapshot,
                resilience=resilience,
            )
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                return False
            return True

    def update_terminal_resilience(
        self,
        job_id: str,
        *,
        attempt: int,
        resilience: IndexResilienceSnapshot,
    ) -> bool:
        """Publish settled retry truth for one exact terminal attempt."""
        with self._lock:
            backup = self._capture_state_locked()
            managed = self._get_terminal_locked(job_id)
            if (
                managed is None
                or not managed.snapshot.state.is_terminal
                or managed.snapshot.attempt.number != attempt
            ):
                return False
            managed.snapshot = replace(
                managed.snapshot,
                resilience=resilience,
            )
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                return False
            return True

    def release_execution_resources(
        self,
        job_id: str,
        *,
        task: asyncio.Task[AttemptExit],
        finished: ProcessResourceSnapshot,
    ) -> bool:
        """Atomically clear worker and physical ownership for one exact attempt."""
        with self._lock:
            managed = self._active.get(job_id)
            if managed is None or managed.runtime.task is not task:
                return False
            assign_runtime_owner(
                managed,
                replace(
                    managed.runtime,
                    worker_active=False,
                    worker_thread=None,
                    compute_ticket=None,
                ),
            )
            managed.snapshot = replace(
                managed.snapshot,
                resources=replace(
                    managed.snapshot.resources,
                    finished=finished,
                    index_capacity_held=False,
                    project_lease_held=False,
                    writer_lock_held=False,
                    pipeline_active=False,
                ),
            )
            persistence_error = self._persist_locked()
            # Physical release is irreversible. Retaining truthful cleared
            # ownership in memory lets finish/acknowledge immediately retry
            # the complete generation instead of restoring stale held flags.
            return persistence_error is None

    def set_execution_resources(
        self,
        job_id: str,
        *,
        task: asyncio.Task[AttemptExit],
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


def _normalize_progress(
    step: object,
    completed: object,
    total: object,
) -> tuple[str, int, int | None] | str:
    """Validate and normalize one untrusted progress publication."""
    if not isinstance(step, str) or not step.strip():
        return "Progress step is required."
    if not isinstance(completed, int) or isinstance(completed, bool) or completed < 0:
        return "Progress counts must satisfy 0 <= completed <= total when total is set."
    if total is None:
        return step.strip(), completed, None
    if not isinstance(total, int) or isinstance(total, bool) or total < completed:
        return "Progress counts must satisfy 0 <= completed <= total when total is set."
    return step.strip(), completed, total
