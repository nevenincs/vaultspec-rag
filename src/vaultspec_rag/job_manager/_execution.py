"""Concrete job-manager responsibility owner."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING, cast

from anyio.to_thread import run_sync as _run_in_thread

if TYPE_CHECKING:
    import anyio

    from .manager import JobManager

from .._job_errors import classify_error_text
from ..concurrency import get_encode_limiter, get_index_limiter
from ..config._settings import get_config
from ..job_control import (
    CancelRequested,
    PauseRequested,
    QuiesceRequested,
    RunControlToken,
    ShutdownRequested,
    gpu_lock_wait_scope,
)
from ..job_models import (
    DesiredJobState,
    JobOutcome,
    JobOutcomeStatus,
    JobSnapshot,
    JobState,
)
from ..job_models import (
    is_encode_bearing as _is_encode_bearing,
)
from ._control import AttemptTerminal
from .models import (
    JobAttemptContext,
    JobExecutionResult,
    JobShutdownResult,
    QuiescedDispatchClaim,
    ResourceUpdate,
)
from .state import (
    AttemptExit,
    JobAttemptFinishedCallback,
    JobAttemptRunner,
    JobAttemptStartedCallback,
    JobDispatchBinding,
    JobManagerState,
    ManagedJob,
)

logger = logging.getLogger("vaultspec_rag.jobs")

#: How long a loopless caller waits for the service loop to accept its
#: dispatch. The handed-off work is bookkeeping under the manager lock plus
#: one ``create_task``, so this is not a work budget - it is the point past
#: which the loop is wedged and the service has larger problems than one
#: repair. Generous on purpose: expiring early would report a failure for a
#: dispatch the loop then goes on to perform.
_LOOPLESS_DISPATCH_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class _DispatchAdmission:
    """Validated immutable inputs for one newly scheduled attempt."""

    binding: JobDispatchBinding
    attempt: int
    control: RunControlToken


class JobManagerExecution(JobManagerState):
    #: Declared here because this owner both adopts and reads it. Adoption
    #: only ever stores a live loop, so a type inferred from that write alone
    #: would define the unadopted case out of existence and silently retire
    #: the rejection a loopless dispatch depends on.
    _service_loop: asyncio.AbstractEventLoop | None

    def bind_dispatch(
        self,
        job_id: str,
        runner: JobAttemptRunner,
        *,
        on_started: JobAttemptStartedCallback | None = None,
        on_finished: JobAttemptFinishedCallback | None = None,
    ) -> JobOutcome:
        """Bind one in-process runner to a logical job across resume attempts."""
        command = "bind_dispatch"
        with self._lock:
            managed = self._active.get(job_id)
            if managed is None:
                return self._error(command, "job_not_found", "The job was not found.")
            if managed.runtime.task is not None:
                return self._error(
                    command,
                    "runtime_already_owned",
                    "A live attempt cannot replace its dispatch binding.",
                    managed,
                )
            self._next_dispatch_binding_nonce += 1
            self._supersede_quiesced_dispatch_claim_locked(job_id)
            self._dispatchers[job_id] = JobDispatchBinding(
                runner=runner,
                nonce=self._next_dispatch_binding_nonce,
                on_started=on_started,
                on_finished=on_finished,
            )
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="dispatch_bound",
                message="The job execution binding was attached.",
                job=self._snapshot_locked(managed),
            )

    def _dispatch_admission_locked(
        self,
        job_id: str,
        loop: asyncio.AbstractEventLoop,
        *,
        quiesced_claim: QuiescedDispatchClaim | None = None,
    ) -> _DispatchAdmission | JobOutcome:
        """Validate one queued job and bind its execution to ``loop``."""
        command = "dispatch"
        if quiesced_claim is None:
            self._supersede_quiesced_dispatch_claim_locked(job_id)
        managed = self._active.get(job_id)
        if managed is None:
            self._clear_quiesced_dispatch_claim_locked(quiesced_claim)
            return self._error(command, "job_not_found", "The job was not found.")
        if not self._accepting_dispatch:
            self._clear_quiesced_dispatch_claim_locked(quiesced_claim)
            return self._error(
                command,
                "dispatch_stopped",
                "Managed dispatch is stopped for service shutdown.",
                managed,
            )
        binding = self._dispatchers.get(job_id)
        if binding is None:
            self._clear_quiesced_dispatch_claim_locked(quiesced_claim)
            return self._error(
                command,
                "dispatch_not_bound",
                "The job has no execution binding.",
                managed,
            )
        refusal = self._dispatch_runtime_refusal_locked(managed)
        if refusal is not None:
            self._clear_quiesced_dispatch_claim_locked(quiesced_claim)
            return refusal
        if quiesced_claim is not None and not (
            self._consume_quiesced_dispatch_claim_locked(
                quiesced_claim,
                managed,
                binding,
            )
        ):
            return self._error(
                command,
                "stale_recovery_dispatch",
                "The recovery dispatch claim was superseded before execution.",
                managed,
            )
        if binding.loop is not loop:
            binding = replace(binding, loop=loop)
            self._dispatchers[job_id] = binding
        return _DispatchAdmission(
            binding=binding,
            attempt=managed.snapshot.attempt.number,
            control=RunControlToken(),
        )

    def _dispatch_runtime_refusal_locked(
        self,
        managed: ManagedJob,
    ) -> JobOutcome | None:
        """Return the exact state refusal that prevents attempt admission."""
        if managed.runtime.task is not None:
            return self._error(
                "dispatch",
                "runtime_already_owned",
                "The current attempt already has a runtime owner.",
                managed,
            )
        if (
            managed.snapshot.state is not JobState.QUEUED
            or managed.snapshot.desired_state is not DesiredJobState.RUNNING
        ):
            return self._error(
                "dispatch",
                "invalid_transition",
                "Only queued work with running desired state can dispatch.",
                managed,
            )
        return None

    def adopt_service_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the loop that owns managed execution for this service life."""
        with self._lock:
            self._service_loop = loop

    def dispatch(
        self,
        job_id: str,
        *,
        _quiesced_claim: QuiescedDispatchClaim | None = None,
    ) -> JobOutcome:
        """Schedule one queued attempt, from this thread's loop or the service's."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self._dispatch_from_loopless_thread(
                job_id,
                _quiesced_claim=_quiesced_claim,
            )
        return self._dispatch_on(job_id, loop, _quiesced_claim=_quiesced_claim)

    def _dispatch_from_loopless_thread(
        self,
        job_id: str,
        *,
        _quiesced_claim: QuiescedDispatchClaim | None = None,
    ) -> JobOutcome:
        """Hand a dispatch decided off the loop back to the service's own loop.

        Job admission runs a policy preflight that scans the tree, so callers
        deliberately decide to dispatch from a plain worker thread to keep
        that scan off the serving path. Such a thread never has a running
        loop of its own - not at any point in its life - so resolving one
        here is the difference between a repair that runs and a job that is
        admitted only to fail. A process that adopted no loop keeps the
        original rejection: there, loopless really does mean no loop exists.
        """
        command = "dispatch"
        with self._lock:
            loop = self._service_loop
        if loop is None or loop.is_closed() or not loop.is_running():
            with self._lock:
                self._clear_quiesced_dispatch_claim_locked(_quiesced_claim)
            return self._error(
                command,
                "event_loop_required",
                "Managed dispatch requires a running event loop.",
            )
        assert loop is not None

        outcome: concurrent.futures.Future[JobOutcome] = concurrent.futures.Future()

        def _dispatch_on_service_loop() -> None:
            try:
                outcome.set_result(
                    self._dispatch_on(
                        job_id,
                        loop,
                        _quiesced_claim=_quiesced_claim,
                    )
                )
            except BaseException as exc:
                # Carried to the waiting caller rather than escaping into the
                # loop's exception handler, where it would be logged and lost.
                outcome.set_exception(exc)

        try:
            loop.call_soon_threadsafe(_dispatch_on_service_loop)
        except RuntimeError:
            # Closed between the liveness check above and the handoff.
            with self._lock:
                self._clear_quiesced_dispatch_claim_locked(_quiesced_claim)
            return self._error(
                command,
                "event_loop_required",
                "Managed dispatch requires a running event loop.",
            )
        try:
            return outcome.result(timeout=_LOOPLESS_DISPATCH_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            with self._lock:
                self._clear_quiesced_dispatch_claim_locked(_quiesced_claim)
            return self._error(
                command,
                "dispatch_loop_unresponsive",
                "The service event loop did not accept the dispatch in time.",
            )

    def _dispatch_on(
        self,
        job_id: str,
        loop: asyncio.AbstractEventLoop,
        *,
        _quiesced_claim: QuiescedDispatchClaim | None = None,
    ) -> JobOutcome:
        """Admit and schedule one queued attempt on *loop*, which must be running."""
        with self._lock:
            admission = self._dispatch_admission_locked(
                job_id,
                loop,
                quiesced_claim=_quiesced_claim,
            )
            if isinstance(admission, JobOutcome):
                return admission
            task = loop.create_task(
                self._run_attempt(
                    job_id=job_id,
                    attempt=admission.attempt,
                    control=admission.control,
                    binding=admission.binding,
                ),
                name=f"vaultspec-job-{job_id}-attempt-{admission.attempt}",
            )
            self._retiring_tasks.add(task)
            task.add_done_callback(
                partial(
                    self._complete_attempt,
                    job_id,
                    admission.attempt,
                    binding=admission.binding,
                )
            )
            started = self.start_attempt(job_id, task=task, control=admission.control)
            latest = self._active.get(job_id)
            owns_runtime = latest is not None and latest.runtime.task is task
            if not owns_runtime:
                task.cancel()
                return started
            assert latest is not None
            started_snapshot = self._snapshot_locked(latest)

        self._notify_started(admission.binding, started_snapshot)
        return started

    async def dispatch_async(self, job_id: str) -> JobOutcome:
        """Dispatch without running durable registry writes on the event loop.

        The attempt task is created on its owning loop, but waits behind a gate
        until :meth:`start_attempt` has synchronously persisted runtime ownership
        in a worker thread.  This retains durable-before-execution ordering while
        keeping whole-registry serialization, replacement, and fsync off ASGI.
        """
        loop = asyncio.get_running_loop()
        start_gate = asyncio.Event()

        with self._lock:
            admission = self._dispatch_admission_locked(job_id, loop)
            if isinstance(admission, JobOutcome):
                return admission
            task = loop.create_task(
                self._run_attempt_after_start(
                    start_gate,
                    job_id=job_id,
                    attempt=admission.attempt,
                    control=admission.control,
                    binding=admission.binding,
                ),
                name=f"vaultspec-job-{job_id}-attempt-{admission.attempt}",
            )
            self._retiring_tasks.add(task)

        try:
            started = await _run_in_thread(
                partial(
                    self.start_attempt,
                    job_id,
                    task=task,
                    control=admission.control,
                )
            )
        except BaseException:
            task.cancel()
            raise

        with self._lock:
            latest = self._active.get(job_id)
            owns_runtime = latest is not None and latest.runtime.task is task
            if not owns_runtime:
                task.cancel()
                self._retiring_tasks.discard(task)
                return started
            assert latest is not None
            started_snapshot = self._snapshot_locked(latest)
            task.add_done_callback(
                partial(
                    self._complete_attempt,
                    job_id,
                    admission.attempt,
                    binding=admission.binding,
                )
            )

        start_gate.set()
        self._notify_started(admission.binding, started_snapshot)
        return started

    async def wait_for_attempt(
        self,
        job_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> JobOutcome:
        """Boundedly join the exact task without cancelling its worker thread."""
        command = "wait_for_attempt"
        timeout = (
            get_config().job_shutdown_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            with self._lock:
                managed = self._active.get(job_id)
                terminal: ManagedJob | None = None
                if managed is None:
                    terminal = self._get_terminal_locked(job_id)
                    if terminal is None:
                        return self._error(
                            command,
                            "job_not_found",
                            "The job was not found.",
                        )
                    task = None
                    snapshot = self._snapshot_locked(terminal)
                else:
                    task = managed.runtime.task
                    snapshot = self._snapshot_locked(managed)
            if task is None:
                return JobOutcome(
                    command=command,
                    status=JobOutcomeStatus.OK,
                    code="attempt_released",
                    message="The attempt released its task and worker resources.",
                    job=snapshot,
                )

            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
                # Let the task's synchronous done callback acknowledge control and
                # install any resume-requeued replacement before checking ownership.
                await asyncio.sleep(0)
            except TimeoutError:
                break

        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.ERROR,
            code="attempt_join_timeout",
            message=f"The attempt did not release within {timeout:g} seconds.",
            job=self.get(job_id),
        )

    def begin_shutdown(self) -> tuple[str, ...]:
        """Stop new dispatch and signal each exact live attempt for shutdown."""
        with self._lock:
            self._accepting_dispatch = False
            self._lifecycle_state = "stopping"
            self._pending_quiesced_dispatches.clear()
            requested: list[str] = []
            for job_id, managed in self._active.items():
                if managed.runtime.task is None or managed.runtime.control is None:
                    continue
                managed.runtime.control.request_shutdown()
                requested.append(job_id)
            return tuple(requested)

    async def wait_for_shutdown(
        self,
        requested_job_ids: tuple[str, ...],
        *,
        timeout_seconds: float,
    ) -> JobShutdownResult:
        """Join shutdown-signalled attempts without cancelling their tasks."""
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must not be negative")
        with self._lock:
            tasks = {
                managed.runtime.task
                for job_id in requested_job_ids
                if (managed := self._active.get(job_id)) is not None
                and managed.runtime.task is not None
            }
        if tasks and timeout_seconds > 0:
            await asyncio.wait(tasks, timeout=timeout_seconds)
            # Synchronous done callbacks commit resource release and the
            # distinct interrupted outcome after the task becomes done.
            await asyncio.sleep(0)
        with self._lock:
            survivors = self._live_runtime_ids_locked()
        persistence = self.flush_persistence()
        persistence_ok = persistence.status is not JobOutcomeStatus.ERROR
        return JobShutdownResult(
            resources_released=not survivors,
            persistence_ok=persistence_ok,
            requested_job_ids=requested_job_ids,
            surviving_job_ids=survivors,
            persistence_code=persistence.code,
        )

    def _live_runtime_ids_locked(self) -> tuple[str, ...]:
        """Return stable IDs whose exact attempts still own execution resources."""
        return tuple(
            job_id
            for job_id, managed in self._active.items()
            if managed.runtime.task is not None
            or managed.runtime.worker_active
            or managed.snapshot.resources.index_capacity_held
            or managed.snapshot.resources.project_lease_held
            or managed.snapshot.resources.writer_lock_held
            or managed.snapshot.resources.pipeline_active
        )

    async def _run_attempt(
        self,
        *,
        job_id: str,
        attempt: int,
        control: RunControlToken,
        binding: JobDispatchBinding,
    ) -> AttemptExit:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("managed attempt requires an asyncio task")
        context = JobAttemptContext(
            manager=cast("JobManager", self),
            job_id=job_id,
            attempt=attempt,
            task=task,
            control=control,
        )
        started = time.perf_counter()
        result: JobExecutionResult | None = None
        control_signal: (
            PauseRequested
            | CancelRequested
            | QuiesceRequested
            | ShutdownRequested
            | None
        ) = None
        error: BaseException | None = None
        release_persisted = False
        try:
            result = await _run_in_thread(
                self._run_worker_attempt,
                context,
                binding,
                limiter=self._attempt_limiter(job_id),
            )
        except (
            PauseRequested,
            CancelRequested,
            QuiesceRequested,
            ShutdownRequested,
        ) as exc:
            control_signal = exc
        except BaseException as exc:
            error = exc
        finally:
            try:
                # AnyIO has returned the synchronous call, so its worker and
                # index-capacity token are physically released before the
                # manager clears their ownership snapshot.
                release_persisted = self.release_execution_resources(
                    job_id,
                    task=task,
                    finished=self._process_resource_snapshot(),
                )
            except BaseException as exc:
                # Application failures retain priority. A cleanup failure is
                # still stronger than cooperative control because the manager
                # cannot truthfully acknowledge a failed release.
                if error is None:
                    error = exc
        return AttemptExit(
            result=result,
            control_signal=control_signal,
            error=error,
            duration_seconds=time.perf_counter() - started,
            release_persisted=release_persisted,
        )

    async def _run_attempt_after_start(
        self,
        start_gate: asyncio.Event,
        *,
        job_id: str,
        attempt: int,
        control: RunControlToken,
        binding: JobDispatchBinding,
    ) -> AttemptExit:
        """Hold execution until its runtime ownership is durably published."""
        await start_gate.wait()
        return await self._run_attempt(
            job_id=job_id,
            attempt=attempt,
            control=control,
            binding=binding,
        )

    def _attempt_limiter(self, job_id: str) -> anyio.CapacityLimiter:
        """Return the worker-thread limiter that admits one exact attempt.

        Encode-bearing jobs pass through the single machine-wide encode
        admission slot so at most one of them is ever in flight; every
        other managed job keeps the wider index partition. The mapping is
        spec-driven, so read-only and maintenance work can never be pulled
        behind the encode slot by a dispatch-site mistake.

        Acquisition order with the quiesce gate is one-way and fixed: this
        limiter (the admission slot) is acquired first, and the quiesce
        gate is consulted only inside the admitted attempt at unprotected
        checkpoints. Never wait on this limiter from code that is already
        parked at - or responsible for releasing - the quiesce gate.
        """
        with self._lock:
            managed = self._active.get(job_id)
            spec = managed.snapshot.spec if managed is not None else None
        if spec is not None and _is_encode_bearing(spec):
            return get_encode_limiter()
        return get_index_limiter()

    def _run_worker_attempt(
        self,
        context: JobAttemptContext,
        binding: JobDispatchBinding,
    ) -> JobExecutionResult:
        thread = threading.current_thread()
        worker_persisted = self.set_worker_active(
            context.job_id,
            task=context.task,
            active=True,
            worker_thread=thread,
        )
        if not worker_persisted:
            raise RuntimeError("could not publish managed worker ownership")
        # This worker thread only starts once the attempt's capacity
        # limiter admitted it, so this transaction is the admission
        # moment: the stamp makes the record's admission wait measurable
        # and distinguishes a genuinely running attempt from one still
        # queued behind the encode slot.
        capacity_persisted = context.set_resources(
            ResourceUpdate(
                started=self._process_resource_snapshot(),
                index_capacity_held=True,
                admission_acquired_at=time.time(),
            )
        )
        if not capacity_persisted:
            raise RuntimeError("could not publish managed index-capacity ownership")
        # The scope makes every timed GPU-lock acquisition on this attempt's
        # threads attributable to this job; the total publishes beside the
        # admission stamp even when the runner unwinds on control or error.
        with gpu_lock_wait_scope() as gpu_wait:
            try:
                return binding.runner(context)
            finally:
                context.set_resources(
                    ResourceUpdate(gpu_lock_wait_seconds=gpu_wait.seconds)
                )

    def _complete_attempt(
        self,
        job_id: str,
        attempt: int,
        task: asyncio.Task[AttemptExit],
        binding: JobDispatchBinding,
    ) -> None:
        try:
            exit_state = self._attempt_exit(task)
            outcome = self._commit_attempt_exit(
                job_id,
                attempt=attempt,
                task=task,
                exit_state=exit_state,
            )
            outcome = self._recover_completion_persistence(
                job_id,
                attempt=attempt,
                outcome=outcome,
            )
            self._publish_attempt_completion(
                job_id,
                attempt=attempt,
                binding=binding,
                exit_state=exit_state,
                outcome=outcome,
            )
        finally:
            self._retiring_tasks.discard(task)

    @staticmethod
    def _attempt_exit(task: asyncio.Task[AttemptExit]) -> AttemptExit:
        """Read the task result while preserving asynchronous failures as data."""
        try:
            return task.result()
        except BaseException as exc:
            return AttemptExit(
                result=None,
                control_signal=None,
                error=exc,
                duration_seconds=0.0,
                release_persisted=False,
            )

    def _commit_attempt_exit(
        self,
        job_id: str,
        *,
        attempt: int,
        task: asyncio.Task[AttemptExit],
        exit_state: AttemptExit,
    ) -> JobOutcome:
        """Commit one attempt exit under the control-transition lock."""
        # A cross-thread resume/control request cannot invalidate the branch
        # between the pending-state read and acknowledgement.
        with self._lock:
            current = self._active.get(job_id)
            control_pending = current is not None and current.snapshot.state in {
                JobState.PAUSING,
                JobState.CANCELLING,
            }
            if exit_state.error is not None or isinstance(
                exit_state.control_signal,
                ShutdownRequested,
            ):
                return self._finish_terminal_exit(
                    job_id,
                    attempt=attempt,
                    task=task,
                    exit_state=exit_state,
                )
            if exit_state.control_signal is not None or control_pending:
                return self.acknowledge_control(
                    job_id,
                    attempt=attempt,
                    task=task,
                )
            result = exit_state.result
            return self.finish_attempt(
                job_id,
                AttemptTerminal(
                    attempt=attempt,
                    task=task,
                    state=JobState.SUCCEEDED,
                    result=result.summary if result is not None else None,
                    reuse=result.reuse if result is not None else None,
                ),
            )

    def _recover_completion_persistence(
        self,
        job_id: str,
        *,
        attempt: int,
        outcome: JobOutcome,
    ) -> JobOutcome:
        """Retry a failed completion write and shape its durable outcome."""
        if outcome.code != "job_persistence_failed":
            return outcome
        retried = self.flush_persistence()
        if retried.status is JobOutcomeStatus.ERROR:
            return outcome
        recovered = self.get(job_id)
        resume_requeued = (
            recovered is not None
            and recovered.state is JobState.QUEUED
            and recovered.desired_state is DesiredJobState.RUNNING
            and recovered.attempt.resumed_from_attempt == attempt
        )
        return JobOutcome(
            command="complete_attempt",
            status=JobOutcomeStatus.OK,
            code=(
                "resume_requeued"
                if resume_requeued
                else "completion_persistence_recovered"
            ),
            message=(
                "The resumed reconciliation attempt became durable on retry."
                if resume_requeued
                else "Attempt completion became durable on retry."
            ),
            job=recovered,
        )

    def _publish_attempt_completion(
        self,
        job_id: str,
        *,
        attempt: int,
        binding: JobDispatchBinding,
        exit_state: AttemptExit,
        outcome: JobOutcome,
    ) -> None:
        """Notify compatibility observers and dispatch a durable resume."""
        snapshot = outcome.job or self.get(job_id)
        completion_committed = outcome.status is not JobOutcomeStatus.ERROR and (
            outcome.code
            not in {
                "control_acknowledgement_ignored",
                "resources_still_owned",
                "stale_attempt_ignored",
            }
        )
        if snapshot is not None and completion_committed:
            self._notify_finished(
                binding,
                snapshot,
                exit_state.duration_seconds,
                exit_state.result,
                exit_state.error,
            )
        elif not completion_committed:
            logger.error(
                "managed job %s attempt %s could not commit completion: %s",
                job_id,
                attempt,
                outcome.message,
            )
        if outcome.code != "resume_requeued":
            return
        resumed = self.dispatch(job_id)
        if resumed.status is JobOutcomeStatus.ERROR:
            logger.error(
                "could not dispatch resumed job %s: %s",
                job_id,
                resumed.message,
            )

    def _finish_terminal_exit(
        self,
        job_id: str,
        *,
        attempt: int,
        task: asyncio.Task[AttemptExit],
        exit_state: AttemptExit,
    ) -> JobOutcome:
        """Commit an application, release, cancellation, or shutdown failure."""
        error = exit_state.error
        shutdown = error is None and isinstance(
            exit_state.control_signal,
            ShutdownRequested,
        )
        interrupted = shutdown or isinstance(error, asyncio.CancelledError)
        state = JobState.INTERRUPTED if interrupted else JobState.FAILED
        result = (
            "Service shutdown interrupted the indexing attempt."
            if shutdown
            else str(error)
        )
        return self.finish_attempt(
            job_id,
            AttemptTerminal(
                attempt=attempt,
                task=task,
                state=state,
                result=result,
                error_kind=(
                    "interrupted" if interrupted else classify_error_text(result)
                ),
            ),
        )

    @staticmethod
    def _notify_started(binding: JobDispatchBinding, snapshot: JobSnapshot) -> None:
        callback = binding.on_started
        if callback is None:
            return
        try:
            callback(snapshot)
        except Exception:
            logger.exception("managed job start callback failed")

    @staticmethod
    def _notify_finished(
        binding: JobDispatchBinding,
        snapshot: JobSnapshot,
        duration_seconds: float,
        result: JobExecutionResult | None,
        error: BaseException | None,
    ) -> None:
        callback = binding.on_finished
        if callback is None:
            return
        try:
            callback(snapshot, duration_seconds, result, error)
        except Exception:
            logger.exception("managed job completion callback failed")
