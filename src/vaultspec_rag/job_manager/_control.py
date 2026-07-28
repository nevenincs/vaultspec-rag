"""Concrete job-manager responsibility owner."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, Literal

from anyio.to_thread import run_sync as _run_in_thread

from .._job_errors import classify_error_text
from ..job_models import (
    DesiredJobState,
    JobAttempt,
    JobInitiator,
    JobOutcome,
    JobOutcomeStatus,
    JobResourceSnapshot,
    JobSnapshot,
    JobState,
    JobTimestamps,
    ResumeStrategy,
)
from ..job_models import (
    capabilities_for_state as _capabilities_for_state,
)
from ..logging_config import log_event
from .state import (
    JobManagerState,
    JobRuntimeOwner,
    ManagedJob,
    ManagerStateBackup,
)

if TYPE_CHECKING:
    from .. import job_persistence as _job_persistence

logger = logging.getLogger("vaultspec_rag.jobs")

#: Rejection codes that indicate a broken internal contract rather than a
#: request an operator can correct. They log at ERROR; every other rejection
#: is an answerable request and logs at WARNING.
_INTERNAL_REJECTION_CODES = frozenset(
    {
        "dispatch_not_bound",
        "event_loop_required",
        "invalid_progress",
        "manager_not_empty",
        "resources_still_owned",
        "runtime_already_owned",
    }
)


def _log_rejection(
    command: str,
    code: str,
    message: str,
    *,
    job_id: str | None,
    initiator: JobInitiator | None,
    **extra_fields: object,
) -> None:
    """Log one command rejection so it leaves a trace beyond the HTTP body.

    Every rejection composes an accurate outcome for the caller, but a caller
    that discards the body (or a UI that only shows acceptance) leaves the
    operator with no record of why nothing happened. This is the single log
    site for all of them.
    """
    fields: dict[str, object] = {
        "command": command,
        "code": code,
        "reason": message,
    }
    if job_id is not None:
        fields["job_id"] = job_id
    if initiator is not None:
        fields["initiator_kind"] = initiator.kind
        fields["initiator_command"] = initiator.command
    fields.update(
        {key: value for key, value in extra_fields.items() if value is not None}
    )
    log_event(
        logger,
        "service.job",
        "rejected",
        severity=(
            logging.ERROR if code in _INTERNAL_REJECTION_CODES else logging.WARNING
        ),
        fields=fields,
    )


@dataclass(frozen=True, slots=True)
class _RequestAttribution:
    """Who asked for a rejected command, and which resource they named.

    Rejection logging needs both even when the target job does not exist or
    the requester is not the job's original initiator; a rejection outcome
    alone carries neither.
    """

    job_id: str | None = None
    initiator: JobInitiator | None = None


@dataclass(frozen=True, slots=True)
class AttemptTerminal:
    attempt: int
    task: asyncio.Task[Any]
    state: JobState
    result: str | None = None
    error_kind: str | None = None
    reuse: dict[str, object] | None = None


class JobManagerControl(JobManagerState):
    def _resolve_control_target_locked(
        self,
        command: str,
        job_id: str,
        desired_state: DesiredJobState,
        *,
        expected_revision: int | None,
        mode: str,
    ) -> tuple[ManagedJob | None, JobOutcome | None]:
        """Resolve and validate the resource targeted by a control request."""
        managed = self._active.get(job_id)
        terminal = None if managed is not None else self._get_terminal_locked(job_id)
        target = managed if managed is not None else terminal
        if mode == "force":
            return None, self._error(
                command,
                "force_termination_unavailable",
                "Per-job force termination is unavailable for this runtime.",
                target,
                attribution=_RequestAttribution(job_id=job_id),
            )
        if mode != "graceful":
            return None, self._error(
                command,
                "invalid_control_mode",
                f"Unsupported control mode {mode!r}.",
                target,
                attribution=_RequestAttribution(job_id=job_id),
            )
        if managed is None:
            return None, self._terminal_control_target_outcome(
                command,
                terminal,
                job_id=job_id,
                desired_state=desired_state,
            )
        if managed.snapshot.desired_state is desired_state:
            return None, self._already_satisfied(command, managed)
        if (
            expected_revision is not None
            and expected_revision != managed.snapshot.revision
        ):
            return None, self._error(
                command,
                "revision_conflict",
                (
                    f"Expected revision {expected_revision}, but the job is at "
                    f"revision {managed.snapshot.revision}."
                ),
                managed,
            )
        return managed, None

    def _terminal_control_target_outcome(
        self,
        command: str,
        terminal: ManagedJob | None,
        *,
        job_id: str,
        desired_state: DesiredJobState,
    ) -> JobOutcome:
        """Resolve a missing or terminal target without mutating manager state."""
        if terminal is None:
            return self._error(
                command,
                "job_not_found",
                "The job was not found.",
                attribution=_RequestAttribution(job_id=job_id),
            )
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

    def _request_desired_transition_locked(
        self,
        command: str,
        managed: ManagedJob,
        desired_state: DesiredJobState,
    ) -> JobOutcome:
        """Apply one validated desired-state transition in memory."""
        state = managed.snapshot.state
        if desired_state is DesiredJobState.PAUSED:
            return self._request_pause_locked(command, managed, state)
        if desired_state is DesiredJobState.RUNNING:
            return self._request_resume_locked(command, managed, state)
        return self._request_cancel_locked(command, managed, state)

    def _resolve_pause_withdrawal_locked(
        self,
        command: str,
        managed: ManagedJob,
        outcome: JobOutcome,
        *,
        resume_withdrawn: bool | None,
    ) -> JobOutcome:
        """Publish the result of racing pause delivery with a resume request."""
        if outcome.code != "pause_withdrawal_pending":
            return outcome
        if resume_withdrawn:
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="pause_withdrawn",
                message="The undelivered pause request was withdrawn.",
                job=self._snapshot_locked(managed),
            )

        # Delivery won the race while RUNNING was being made durable. Restore
        # truthful PAUSING state and let cleanup queue a reconciliation attempt.
        persistence_error = self._restore_delivered_pause_locked(managed)
        if persistence_error is not None:
            return self._persistence_error(
                command,
                persistence_error,
                self._get_locked(managed.snapshot.id),
            )
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.ACCEPTED,
            code="resume_requested",
            message="The delivered pause will unwind before resume requeues.",
            job=self._snapshot_locked(managed),
        )

    def _persist_desired_transition_locked(
        self,
        command: str,
        job_id: str,
        managed: ManagedJob,
        outcome: JobOutcome,
        backup: ManagerStateBackup,
    ) -> JobOutcome:
        """Persist a transition before delivering its cooperative signal."""
        persistence_error = self._persist_locked()
        if persistence_error is not None:
            if not persistence_error.published:
                self._restore_state_locked(backup)
            else:
                resume_withdrawn = self._apply_control_signal_locked(
                    managed,
                    outcome.code,
                )
                if outcome.code == "pause_withdrawal_pending" and not resume_withdrawn:
                    self._restore_delivered_pause_locked(managed)
            return self._persistence_error(
                command,
                persistence_error,
                self._get_locked(job_id),
            )

        resume_withdrawn = self._apply_control_signal_locked(managed, outcome.code)
        return self._resolve_pause_withdrawal_locked(
            command,
            managed,
            outcome,
            resume_withdrawn=resume_withdrawn,
        )

    def set_desired_state(
        self,
        job_id: str,
        desired_state: DesiredJobState,
        *,
        expected_revision: int | None = None,
        mode: Literal["graceful", "force"] = "graceful",
        _schedule_dispatch_after_transition: bool = True,
    ) -> JobOutcome:
        """Set operator intent for one exact job and request cooperative control.

        Replays of the current desired state are successful even when the supplied
        revision is stale. This lets clients safely retry a request whose response
        was lost without weakening optimistic concurrency for real state changes.
        """
        return self._set_desired_state(
            job_id,
            desired_state,
            expected_revision=expected_revision,
            mode=mode,
            schedule_dispatch=_schedule_dispatch_after_transition,
        )

    async def set_desired_state_async(
        self,
        job_id: str,
        desired_state: DesiredJobState,
        *,
        expected_revision: int | None = None,
        mode: Literal["graceful", "force"] = "graceful",
    ) -> JobOutcome:
        """Persist desired state off-loop, then dispatch through the owning loop."""
        outcome = await _run_in_thread(
            partial(
                self.set_desired_state,
                job_id,
                desired_state,
                expected_revision=expected_revision,
                mode=mode,
                _schedule_dispatch_after_transition=False,
            )
        )
        snapshot = outcome.job
        if (
            outcome.status is not JobOutcomeStatus.ERROR
            and snapshot is not None
            and snapshot.state is JobState.QUEUED
            and snapshot.desired_state is DesiredJobState.RUNNING
        ):
            with self._lock:
                dispatch_bound = job_id in self._dispatchers
            if dispatch_bound:
                dispatched = await self.dispatch_async(job_id)
                if dispatched.status is JobOutcomeStatus.ERROR:
                    logger.error(
                        "could not dispatch resumed job %s: %s",
                        job_id,
                        dispatched.message,
                    )
        return outcome

    def _set_desired_state(
        self,
        job_id: str,
        desired_state: DesiredJobState,
        *,
        expected_revision: int | None,
        mode: Literal["graceful", "force"],
        schedule_dispatch: bool,
    ) -> JobOutcome:
        """Apply and persist intent, optionally scheduling synchronous dispatch."""
        command = "set_desired_state"
        with self._lock:
            backup = self._capture_state_locked()
            managed, early_outcome = self._resolve_control_target_locked(
                command,
                job_id,
                desired_state,
                expected_revision=expected_revision,
                mode=mode,
            )
            if early_outcome is not None:
                return early_outcome
            assert managed is not None
            outcome = self._request_desired_transition_locked(
                command,
                managed,
                desired_state,
            )
            if outcome.status is JobOutcomeStatus.ERROR:
                return outcome
            outcome = self._persist_desired_transition_locked(
                command,
                job_id,
                managed,
                outcome,
                backup,
            )
            if outcome.status is JobOutcomeStatus.ERROR:
                return outcome
            dispatch_after_transition = (
                managed.snapshot.state is JobState.QUEUED
                and managed.snapshot.desired_state is DesiredJobState.RUNNING
                and job_id in self._dispatchers
            )
        if schedule_dispatch and dispatch_after_transition:
            self._schedule_dispatch(job_id)
        return outcome

    def _schedule_dispatch(self, job_id: str) -> None:
        """Dispatch now or hand execution back to the job's owning event loop."""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        with self._lock:
            binding = self._dispatchers.get(job_id)
            owner_loop = binding.loop if binding is not None else None
        if owner_loop is None or owner_loop is current_loop:
            if current_loop is not None:
                self._dispatch_and_log(job_id)
                return
        elif owner_loop.is_running():
            owner_loop.call_soon_threadsafe(self._dispatch_and_log, job_id)
            return
        if current_loop is None:
            logger.error(
                "could not schedule resumed job %s: no live event loop", job_id
            )
            return
        logger.error("could not schedule resumed job %s: owner loop stopped", job_id)

    def _dispatch_and_log(self, job_id: str) -> None:
        dispatched = self.dispatch(job_id)
        if dispatched.status is JobOutcomeStatus.ERROR:
            logger.error(
                "could not dispatch resumed job %s: %s",
                job_id,
                dispatched.message,
            )

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
                return self._missing_acknowledgement_target_locked(command, job_id)
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
            if managed.runtime.worker_active or resources.holds_anything:
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
                return self._complete_resumed_control_locked(
                    command,
                    managed,
                    now,
                )
            return self._complete_control_acknowledgement_locked(
                command,
                managed,
                state,
                now,
            )

    def _missing_acknowledgement_target_locked(
        self,
        command: str,
        job_id: str,
    ) -> JobOutcome:
        terminal = self._get_terminal_locked(job_id)
        if terminal is None:
            return self._error(
                command,
                "job_not_found",
                "The job was not found.",
                attribution=_RequestAttribution(job_id=job_id),
            )
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.OK,
            code="terminal_state_preserved",
            message="The job is already terminal; its first outcome was kept.",
            job=self._snapshot_locked(terminal),
        )

    def _complete_resumed_control_locked(
        self,
        command: str,
        managed: ManagedJob,
        now: float,
    ) -> JobOutcome:
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

    def _complete_control_acknowledgement_locked(
        self,
        command: str,
        managed: ManagedJob,
        state: JobState,
        now: float,
    ) -> JobOutcome:
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
        terminal: AttemptTerminal,
    ) -> JobOutcome:
        """Commit one attempt's terminal outcome with first-writer-wins semantics."""
        command = "finish_attempt"
        if not terminal.state.is_terminal:
            raise ValueError("attempt completion requires a terminal state")
        with self._lock:
            managed = self._active.get(job_id)
            if managed is None:
                archived_terminal = self._get_terminal_locked(job_id)
                if archived_terminal is not None:
                    return JobOutcome(
                        command=command,
                        status=JobOutcomeStatus.OK,
                        code="terminal_state_preserved",
                        message="The first terminal outcome was preserved.",
                        job=self._snapshot_locked(archived_terminal),
                    )
                return self._error(
                    command,
                    "job_not_found",
                    "The job was not found.",
                    attribution=_RequestAttribution(job_id=job_id),
                )
            if (
                managed.snapshot.attempt.number != terminal.attempt
                or managed.runtime.task is not terminal.task
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
                state=terminal.state,
                desired_state=(
                    DesiredJobState.CANCELLED
                    if terminal.state is JobState.CANCELLED
                    else managed.snapshot.desired_state
                ),
                now=now,
                finished_at=now,
                result=terminal.result,
                error_kind=terminal.error_kind,
                reuse=terminal.reuse,
            )
            self._archive_terminal_locked(managed)
            if terminal.state is JobState.SUCCEEDED:
                self._resolve_retry_ancestry_locked(
                    managed.snapshot.attempt.parent_job_id,
                    resolved_by=managed.snapshot.id,
                )
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
                message=f"The job finished as {terminal.state.value}.",
                job=self._snapshot_locked(managed),
            )

    def fail_unstarted(self, job_id: str, *, result: str) -> JobOutcome:
        """Durably fail admitted work that could not acquire a runtime owner."""
        command = "fail_unstarted"
        with self._lock:
            backup = self._capture_state_locked()
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
                return self._error(
                    command,
                    "job_not_found",
                    "The job was not found.",
                    attribution=_RequestAttribution(job_id=job_id),
                )
            if (
                managed.snapshot.state is not JobState.QUEUED
                or managed.runtime.task is not None
            ):
                return self._error(
                    command,
                    "runtime_already_owned",
                    "Only queued work without a runtime owner can fail admission.",
                    managed,
                )

            now = time.time()
            self._replace_snapshot_locked(
                managed,
                state=JobState.FAILED,
                desired_state=managed.snapshot.desired_state,
                now=now,
                finished_at=now,
                result=result,
                error_kind=classify_error_text(result),
            )
            self._archive_terminal_locked(managed)
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
                code="job_failed_before_dispatch",
                message="The admitted job failed before execution started.",
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
                return self._missing_retry_target_locked(
                    command,
                    job_id,
                    initiator=initiator,
                )
            if not parent.snapshot.state.is_retryable:
                return self._error(
                    command,
                    "job_not_retryable",
                    (
                        "A linked retry already succeeded; superseded jobs are "
                        "recreated through ordinary job creation."
                        if parent.snapshot.state is JobState.SUPERSEDED
                        else "Succeeded jobs are recreated through ordinary "
                        "job creation."
                    ),
                    parent,
                    attribution=_RequestAttribution(initiator=initiator),
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
                    attribution=_RequestAttribution(initiator=initiator),
                )
            equivalent = self._find_equivalent_active_locked(parent.snapshot.spec)
            if equivalent is not None:
                message = "Equivalent active work is already registered."
                _log_rejection(
                    command,
                    "active_job_exists",
                    message,
                    job_id=job_id,
                    initiator=initiator or parent.snapshot.initiator,
                    equivalent_job_id=equivalent.id,
                )
                return JobOutcome(
                    command=command,
                    status=JobOutcomeStatus.ERROR,
                    code="active_job_exists",
                    message=message,
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
                capabilities=_capabilities_for_state(
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
            managed = ManagedJob(
                snapshot=retried,
                runtime=JobRuntimeOwner(task=None, control=None),
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

    def _missing_retry_target_locked(
        self,
        command: str,
        job_id: str,
        *,
        initiator: JobInitiator | None,
    ) -> JobOutcome:
        active = self._active.get(job_id)
        if active is None:
            return self._error(
                command,
                "job_not_found",
                "The job was not found.",
                attribution=_RequestAttribution(job_id=job_id, initiator=initiator),
            )
        return self._error(
            command,
            "job_not_terminal",
            "Only terminal jobs can be retried.",
            active,
            attribution=_RequestAttribution(initiator=initiator),
        )

    def _resolve_retry_ancestry_locked(
        self,
        parent_job_id: str | None,
        *,
        resolved_by: str,
    ) -> None:
        """Mark every retryable terminal ancestor superseded after a retry wins.

        A retryable parent that keeps advertising retry after its linked retry
        succeeded sends the operator around a loop: they retry, the retry
        finishes clean and scrolls away, and the parent still offers retry.
        Resolution walks the whole lineage so a chain of failed retries is
        settled by the one that finally succeeds. A retry that fails or is
        cancelled resolves nothing - its parent honestly still has work to
        offer. Only terminal records change here, so active-work equivalence
        (which scans the active set alone) is untouched.
        """
        seen: set[str] = set()
        while parent_job_id is not None and parent_job_id not in seen:
            seen.add(parent_job_id)
            parent = self._get_terminal_locked(parent_job_id)
            if parent is None or not parent.snapshot.state.is_retryable:
                return
            # The persisted-clock contract reads the finish stamp as the
            # final state change, so resolution keeps the parent's original
            # finish clock instead of advancing either stamp.
            finished_at = parent.snapshot.timestamps.finished_at
            stamp = finished_at if finished_at is not None else time.time()
            self._replace_snapshot_locked(
                parent,
                state=JobState.SUPERSEDED,
                desired_state=parent.snapshot.desired_state,
                now=stamp,
                finished_at=stamp,
            )
            log_event(
                logger,
                "service.job",
                "superseded",
                job_id=parent_job_id,
                resolved_by=resolved_by,
            )
            parent_job_id = parent.snapshot.attempt.parent_job_id

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
                return self._error(
                    command,
                    "job_not_found",
                    "The job was not found.",
                    attribution=_RequestAttribution(job_id=job_id),
                )
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

    def _request_pause_locked(
        self,
        command: str,
        managed: ManagedJob,
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
        managed: ManagedJob,
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
            elif control is not None:
                # Persist RUNNING before withdrawing the token. If checkpoint
                # delivery wins meanwhile, set_desired_state restores PAUSING
                # and the finished attempt queues reconciliation.
                self._replace_snapshot_locked(
                    managed,
                    state=JobState.RUNNING,
                    desired_state=DesiredJobState.RUNNING,
                    now=now,
                    control_requested_at=None,
                    control_acknowledged_at=None,
                )
                code = "pause_withdrawal_pending"
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

    def _restore_delivered_pause_locked(
        self,
        managed: ManagedJob,
    ) -> _job_persistence.PersistenceWriteError | None:
        self._replace_snapshot_locked(
            managed,
            state=JobState.PAUSING,
            desired_state=DesiredJobState.RUNNING,
            now=time.time(),
        )
        return self._persist_locked()

    def _queue_resumed_attempt_locked(
        self,
        managed: ManagedJob,
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
        managed: ManagedJob,
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

    def _already_satisfied(
        self,
        command: str,
        managed: ManagedJob,
    ) -> JobOutcome:
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.OK,
            code="already_satisfied",
            message="The requested desired state is already set.",
            job=self._snapshot_locked(managed),
        )

    @staticmethod
    def _apply_control_signal_locked(
        managed: ManagedJob,
        outcome_code: str,
    ) -> bool | None:
        owner = managed.runtime
        if outcome_code == "pause_requested" and owner.control is not None:
            owner.control.request_pause()
        elif outcome_code == "cancellation_requested" and owner.control is not None:
            owner.control.request_cancel()
        elif outcome_code == "pause_withdrawal_pending" and owner.control is not None:
            return owner.control.request_resume()
        return None

    def _error(
        self,
        command: str,
        code: str,
        message: str,
        managed: ManagedJob | None = None,
        *,
        attribution: _RequestAttribution | None = None,
    ) -> JobOutcome:
        snapshot = self._snapshot_locked(managed) if managed is not None else None
        job_id = attribution.job_id if attribution is not None else None
        initiator = attribution.initiator if attribution is not None else None
        if snapshot is not None:
            if job_id is None:
                job_id = snapshot.id
            if initiator is None:
                initiator = snapshot.initiator
        _log_rejection(command, code, message, job_id=job_id, initiator=initiator)
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.ERROR,
            code=code,
            message=message,
            job=snapshot,
        )
