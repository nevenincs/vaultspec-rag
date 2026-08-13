"""Holding managed jobs across a quiesce, and resuming them afterwards.

When the service pauses, queued work must be retained rather than started and
running attempts must be asked to stop at a checkpoint. When it resumes, the
jobs held that way have to be claimed exactly once - which is what the
dispatch claims here exist to guarantee, since a resume that dispatches a job
twice is worse than one that dispatches it late.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from ..job_models import (
    DesiredJobState,
    JobOutcome,
    JobOutcomeStatus,
    JobState,
)
from ..service_quiesce import QuiesceState
from ._persistence import SnapshotTransition
from .models import (
    QuiescedDispatchClaim,
    QuiescedResumePersistence,
    QuiescedResumeResult,
    QuiescedResumeStatus,
)
from .state import (
    JobDispatchBinding,
    JobManagerState,
    ManagedJob,
)

logger = logging.getLogger("vaultspec_rag.jobs")

#: Rejection codes that indicate a broken internal contract rather than a
#: request an operator can correct. They log at ERROR; every other rejection
#: is an answerable request and logs at WARNING.
INTERNAL_REJECTION_CODES = frozenset(
    {
        "dispatch_loop_unresponsive",
        "dispatch_not_bound",
        "event_loop_required",
        "invalid_progress",
        "manager_not_empty",
        "resources_still_owned",
        "runtime_already_owned",
    }
)


class JobManagerQuiesceControl(JobManagerState):
    """Defers, holds and resumes managed jobs around a service quiesce."""

    if TYPE_CHECKING:
        # Provided by the control surface this mixes into.
        def _queue_resumed_attempt_locked(
            self, managed: ManagedJob, *, now: float
        ) -> None: ...

    def defer_unstarted_for_quiesce(self, job_id: str) -> JobOutcome:
        """Retain queued logical work when quiesce closes its start boundary."""
        command = "defer_unstarted_for_quiesce"
        with self._lock:
            backup = self._capture_state_locked()
            managed = self._active.get(job_id)
            if managed is None:
                return self._error(
                    command,
                    "job_not_found",
                    "The job was not found.",
                )
            if (
                managed.snapshot.state is not JobState.QUEUED
                or managed.snapshot.desired_state is not DesiredJobState.RUNNING
                or managed.runtime.task is not None
            ):
                return self._error(
                    command,
                    "invalid_transition",
                    "Only queued running work without a runtime can defer for quiesce.",
                    managed,
                )
            now = time.time()
            self._replace_snapshot_locked(
                managed,
                SnapshotTransition(
                    state=JobState.PAUSED,
                    desired_state=DesiredJobState.RUNNING,
                    now=now,
                    control_requested_at=now,
                    control_acknowledged_at=now,
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
                code="quiesce_deferred_before_start",
                message="The job was retained for service quiesce resume.",
                job=self._snapshot_locked(managed),
            )

    def request_quiesce_attempts(self) -> tuple[str, ...]:
        """Ask active attempts to unwind for a service-managed quiesce.

        This adapts live attempts only. The service controller owns lifecycle
        transitions and admission; the manager does not advance either.
        """
        with self._lock:
            backup = self._capture_state_locked()
            requested: list[str] = []
            for job_id, managed in self._active.items():
                if (
                    managed.snapshot.state is not JobState.RUNNING
                    or managed.runtime.task is None
                    or managed.runtime.control is None
                ):
                    continue
                now = time.time()
                self._replace_snapshot_locked(
                    managed,
                    SnapshotTransition(
                        state=JobState.PAUSING,
                        desired_state=DesiredJobState.RUNNING,
                        now=now,
                        control_requested_at=now,
                    ),
                )
                requested.append(job_id)
            if not requested:
                return ()
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                return ()
            for job_id in requested:
                managed = self._active.get(job_id)
                if managed is not None and managed.runtime.control is not None:
                    managed.runtime.control.request_quiesce()
            return tuple(requested)

    def prepare_quiesced_resume(self) -> QuiescedResumeResult:
        """Durably prepare same-ID recovery while warming keeps admission closed."""
        if self._quiesce_controller.snapshot().state is not QuiesceState.WARMING:
            raise RuntimeError("Quiesced recovery preparation requires warming state.")
        with self._lock:
            backup = self._capture_state_locked()
            prepared: list[str] = []
            now = time.time()
            for job_id, managed in self._active.items():
                snapshot = managed.snapshot
                if (
                    not snapshot.state.is_idle
                    or snapshot.desired_state is not DesiredJobState.RUNNING
                    or managed.runtime.task is not None
                ):
                    continue
                if snapshot.state is JobState.PAUSED:
                    self._queue_resumed_attempt_locked(managed, now=now)
                prepared.append(job_id)
            if not prepared:
                return QuiescedResumeResult(
                    status=QuiescedResumeStatus.NO_WORK,
                    persistence=QuiescedResumePersistence.NOT_REQUIRED,
                    job_ids=(),
                )
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                return QuiescedResumeResult(
                    status=(
                        QuiescedResumeStatus.PERSISTENCE_PUBLISHED_NOT_DURABLE
                        if persistence_error.published
                        else QuiescedResumeStatus.PERSISTENCE_UNPUBLISHED
                    ),
                    persistence=(
                        QuiescedResumePersistence.PUBLISHED_NOT_DURABLE
                        if persistence_error.published
                        else QuiescedResumePersistence.UNPUBLISHED
                    ),
                    job_ids=tuple(prepared),
                )
            return QuiescedResumeResult(
                status=QuiescedResumeStatus.PREPARED,
                persistence=QuiescedResumePersistence.DURABLE,
                job_ids=tuple(prepared),
            )

    def dispatch_prepared_quiesced_resume(
        self,
        prepared: QuiescedResumeResult,
    ) -> tuple[str, ...]:
        """Schedule durable recovery only after the controller opens admission."""
        if (
            prepared.status is not QuiescedResumeStatus.PREPARED
            or self._quiesce_controller.snapshot().state is not QuiesceState.RUNNING
        ):
            return ()
        return self._schedule_recoverable_quiesced_jobs(prepared.job_ids)

    def recover_running_quiesced_resume(self) -> tuple[str, ...]:
        """Schedule retained durable queued work during an already-running resume."""
        if self._quiesce_controller.snapshot().state is not QuiesceState.RUNNING:
            return ()
        with self._lock:
            queued_ids = tuple(self._active)
        return self._schedule_recoverable_quiesced_jobs(queued_ids)

    def _schedule_recoverable_quiesced_jobs(
        self,
        candidate_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Claim each exact durable recovery before its loop dispatches it."""
        with self._lock:
            claims = tuple(
                claim
                for job_id in candidate_ids
                if (claim := self._claim_recoverable_quiesced_job_locked(job_id))
                is not None
            )
        scheduled: list[str] = []
        for claim in claims:
            dispatched = self.dispatch(claim.job_id, _quiesced_claim=claim)
            if dispatched.code == "attempt_started":
                scheduled.append(claim.job_id)
        return tuple(scheduled)

    def _claim_recoverable_quiesced_job_locked(
        self,
        job_id: str,
    ) -> QuiescedDispatchClaim | None:
        managed = self._active.get(job_id)
        binding = self._dispatchers.get(job_id)
        if (
            managed is None
            or binding is None
            or not self._accepting_dispatch
            or managed.snapshot.state is not JobState.QUEUED
            or managed.snapshot.desired_state is not DesiredJobState.RUNNING
            or managed.runtime.task is not None
        ):
            return None
        existing = self._pending_quiesced_dispatches.get(job_id)
        if existing is not None:
            if self._claim_matches_recoverable_job_locked(existing, managed, binding):
                return None
            self._pending_quiesced_dispatches.pop(job_id, None)
        self._next_quiesced_dispatch_generation += 1
        claim = QuiescedDispatchClaim(
            job_id=job_id,
            attempt=managed.snapshot.attempt.number,
            binding_nonce=binding.nonce,
            generation_nonce=self._next_quiesced_dispatch_generation,
        )
        self._pending_quiesced_dispatches[job_id] = claim
        return claim

    @staticmethod
    def _claim_matches_recoverable_job_locked(
        claim: QuiescedDispatchClaim,
        managed: ManagedJob,
        binding: JobDispatchBinding,
    ) -> bool:
        return (
            managed.snapshot.id == claim.job_id
            and managed.snapshot.attempt.number == claim.attempt
            and managed.snapshot.state is JobState.QUEUED
            and managed.snapshot.desired_state is DesiredJobState.RUNNING
            and managed.runtime.task is None
            and binding.nonce == claim.binding_nonce
        )

    def _claim_quiesced_dispatch_binding_locked(
        self,
        claim: QuiescedDispatchClaim,
    ) -> JobDispatchBinding | None:
        """Return a still-current claim binding or clear that exact stale claim."""
        if self._pending_quiesced_dispatches.get(claim.job_id) != claim:
            return None
        managed = self._active.get(claim.job_id)
        binding = self._dispatchers.get(claim.job_id)
        if (
            managed is None
            or binding is None
            or not self._claim_matches_recoverable_job_locked(claim, managed, binding)
        ):
            self._pending_quiesced_dispatches.pop(claim.job_id, None)
            return None
        return binding

    def _consume_quiesced_dispatch_claim_locked(
        self,
        claim: QuiescedDispatchClaim,
        managed: ManagedJob,
        binding: JobDispatchBinding,
    ) -> bool:
        """Consume only the exact pending claim validated by canonical dispatch."""
        if self._pending_quiesced_dispatches.get(claim.job_id) != claim:
            return False
        if not self._claim_matches_recoverable_job_locked(claim, managed, binding):
            self._pending_quiesced_dispatches.pop(claim.job_id, None)
            return False
        self._pending_quiesced_dispatches.pop(claim.job_id, None)
        return True

    def _clear_quiesced_dispatch_claim_locked(
        self,
        claim: QuiescedDispatchClaim | None,
    ) -> None:
        """Clear an exact stale or refused claim without disturbing a newer one."""
        if (
            claim is not None
            and self._pending_quiesced_dispatches.get(claim.job_id) == claim
        ):
            self._pending_quiesced_dispatches.pop(claim.job_id, None)

    def _supersede_quiesced_dispatch_claim_locked(self, job_id: str) -> None:
        """Discard recovery scheduling once another canonical dispatch owns it."""
        self._pending_quiesced_dispatches.pop(job_id, None)
