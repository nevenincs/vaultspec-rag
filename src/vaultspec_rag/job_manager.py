"""Service-domain ownership and lifecycle orchestration for canonical jobs."""

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
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Any, Literal, cast

from anyio.to_thread import run_sync as _run_in_thread

from . import job_persistence as _job_persistence
from ._job_errors import classify_error_text
from .concurrency import get_index_limiter
from .config import get_config
from .job_control import (
    CancelRequested,
    PauseRequested,
    RunControlToken,
    ShutdownRequested,
)
from .job_models import (
    DesiredJobState,
    IndexResilienceSnapshot,
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
    ProcessResourceSnapshot,
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

# Preserve the established logger surface while the compatibility module remains public.
logger = logging.getLogger(f"{__package__}.jobs")

__all__ = [
    "MAX_RECORDS",
    "JobAttemptContext",
    "JobExecutionResult",
    "JobManager",
    "JobShutdownResult",
]

# Bounded ring buffer cap. Generous enough to retain a meaningful recent
# history without unbounded growth; the oldest record is evicted past this.
MAX_RECORDS = 256
_MANAGED_STATE_FILENAME = "jobs-state.json"


class _ConfiguredStatePath:
    __slots__ = ()


_CONFIGURED_STATE_PATH = _ConfiguredStatePath()


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    """Result returned by one synchronous managed execution attempt."""

    summary: str
    preprocess_ok: int = 0
    preprocess_skipped: int = 0
    preprocess_failures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JobShutdownResult:
    """Bounded manager-drain result consumed by service shutdown."""

    resources_released: bool
    persistence_ok: bool
    requested_job_ids: tuple[str, ...]
    surviving_job_ids: tuple[str, ...]
    persistence_code: str

    @property
    def clean(self) -> bool:
        """Return whether shutdown was both resource-safe and durable."""
        return self.resources_released and self.persistence_ok


@dataclass(frozen=True, slots=True)
class JobAttemptContext:
    """Exact manager-owned resources passed to a synchronous attempt runner."""

    manager: JobManager
    job_id: str
    attempt: int
    task: asyncio.Task[Any]
    control: RunControlToken

    def update_progress(
        self,
        step: str,
        completed: int = 0,
        total: int | None = None,
    ) -> JobOutcome:
        """Publish progress only if this context still owns the attempt."""
        return self.manager.update_progress(
            self.job_id,
            attempt=self.attempt,
            task=self.task,
            step=step,
            completed=completed,
            total=total,
        )

    def set_resources(
        self,
        *,
        started: ProcessResourceSnapshot | None | object = ...,
        finished: ProcessResourceSnapshot | None | object = ...,
        index_capacity_held: bool | None = None,
        project_lease_held: bool | None = None,
        writer_lock_held: bool | None = None,
        pipeline_active: bool | None = None,
    ) -> bool:
        """Update this attempt's resource ownership without stale-task writes."""
        return self.manager.update_execution_resources(
            self.job_id,
            task=self.task,
            started=started,
            finished=finished,
            index_capacity_held=index_capacity_held,
            project_lease_held=project_lease_held,
            writer_lock_held=writer_lock_held,
            pipeline_active=pipeline_active,
        )

    def set_resilience(self, resilience: IndexResilienceSnapshot) -> bool:
        """Publish canonical resilience state for this exact attempt."""
        return self.manager.update_resilience(
            self.job_id,
            task=self.task,
            resilience=resilience,
        )


type JobAttemptRunner = Callable[[JobAttemptContext], JobExecutionResult]
type JobAttemptStartedCallback = Callable[[JobSnapshot], None]
type JobAttemptFinishedCallback = Callable[
    [JobSnapshot, float, JobExecutionResult | None, BaseException | None],
    None,
]


@dataclass(frozen=True, slots=True)
class _JobDispatchBinding:
    runner: JobAttemptRunner
    on_started: JobAttemptStartedCallback | None = None
    on_finished: JobAttemptFinishedCallback | None = None
    loop: asyncio.AbstractEventLoop | None = None


@dataclass(frozen=True, slots=True)
class _AttemptExit:
    result: JobExecutionResult | None
    control_signal: PauseRequested | CancelRequested | ShutdownRequested | None
    error: BaseException | None
    duration_seconds: float
    release_persisted: bool


@dataclass(frozen=True, slots=True)
class _JobRuntimeOwner:
    """Strong references to the live execution for one exact job ID."""

    task: asyncio.Task[Any] | None
    control: RunControlToken | None
    worker_active: bool = False
    worker_thread: threading.Thread | None = None


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
    dispatchers: dict[str, _JobDispatchBinding]
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
        self._dispatchers: dict[str, _JobDispatchBinding] = {}
        self._retiring_tasks: set[asyncio.Task[Any]] = set()
        self._persistence_dirty = False
        self._accepting_dispatch = True
        self._lifecycle_state: Literal["new", "running", "stopping", "stopped"] = "new"
        self._startup_restore_incomplete = False

    def prepare_startup(self) -> bool:
        """Open dispatch for one service life and report whether restore is needed.

        A cleanly stopped manager is reused in place so queued and paused jobs keep
        their exact identities. An unclean manager cannot be reopened while live
        ownership may still exist.

        Returns:
            ``True`` for a fresh manager that must restore its persisted state;
            ``False`` when reopening the clean in-memory generation.
        """
        with self._lock:
            if self._lifecycle_state == "new":
                self._lifecycle_state = "running"
                self._accepting_dispatch = True
                self._startup_restore_incomplete = True
                return True
            if self._lifecycle_state == "stopped":
                self._lifecycle_state = "running"
                self._accepting_dispatch = True
                self._startup_restore_incomplete = False
                return False
            if self._lifecycle_state == "stopping":
                raise RuntimeError(
                    "JobManager cannot restart after an unclean shutdown while "
                    "runtime ownership may still be live."
                )
            raise RuntimeError("JobManager service lifecycle is already running.")

    def complete_startup(self) -> None:
        """Mark the fresh manager generation restored before dispatch begins."""
        with self._lock:
            if self._lifecycle_state != "running":
                raise RuntimeError("JobManager startup is not active.")
            self._startup_restore_incomplete = False

    def abort_startup(self) -> bool:
        """Return an untouched manager to ``new``, or report retained state."""
        with self._lock:
            if not self._startup_restore_incomplete:
                raise RuntimeError("JobManager startup restore is not pending.")
            if self._active or self._terminal or self._live_runtime_ids_locked():
                return False
            self._lifecycle_state = "new"
            self._accepting_dispatch = True
            self._startup_restore_incomplete = False
            return True

    def complete_shutdown(self, *, resources_released: bool) -> None:
        """Close the service life only after every reachable owner is released."""
        with self._lock:
            if not resources_released:
                self._lifecycle_state = "stopping"
                return
            survivors = self._live_runtime_ids_locked()
            if survivors:
                raise RuntimeError(
                    "JobManager cannot complete clean shutdown with live runtimes: "
                    + ", ".join(survivors)
                )
            self._lifecycle_state = (
                "new" if self._startup_restore_incomplete else "stopped"
            )
            self._startup_restore_incomplete = False

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
            self._dispatchers[job_id] = _JobDispatchBinding(
                runner=runner,
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

    def dispatch(self, job_id: str) -> JobOutcome:
        """Schedule one queued attempt and attach its exact task and control token."""
        command = "dispatch"
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self._error(
                command,
                "event_loop_required",
                "Managed dispatch requires a running event loop.",
            )

        with self._lock:
            managed = self._active.get(job_id)
            if managed is None:
                return self._error(command, "job_not_found", "The job was not found.")
            if not self._accepting_dispatch:
                return self._error(
                    command,
                    "dispatch_stopped",
                    "Managed dispatch is stopped for service shutdown.",
                    managed,
                )
            binding = self._dispatchers.get(job_id)
            if binding is None:
                return self._error(
                    command,
                    "dispatch_not_bound",
                    "The job has no execution binding.",
                    managed,
                )
            if managed.runtime.task is not None:
                return self._error(
                    command,
                    "runtime_already_owned",
                    "The current attempt already has a runtime owner.",
                    managed,
                )
            if (
                managed.snapshot.state is not JobState.QUEUED
                or managed.snapshot.desired_state is not DesiredJobState.RUNNING
            ):
                return self._error(
                    command,
                    "invalid_transition",
                    "Only queued work with running desired state can dispatch.",
                    managed,
                )

            if binding.loop is not loop:
                binding = replace(binding, loop=loop)
                self._dispatchers[job_id] = binding
            attempt = managed.snapshot.attempt.number
            control = RunControlToken()
            task = loop.create_task(
                self._run_attempt(
                    job_id=job_id,
                    attempt=attempt,
                    control=control,
                    binding=binding,
                ),
                name=f"vaultspec-job-{job_id}-attempt-{attempt}",
            )
            self._retiring_tasks.add(task)
            task.add_done_callback(
                partial(
                    self._complete_attempt,
                    job_id,
                    attempt,
                    binding=binding,
                )
            )
            started = self.start_attempt(job_id, task=task, control=control)
            latest = self._active.get(job_id)
            owns_runtime = latest is not None and latest.runtime.task is task
            if not owns_runtime:
                task.cancel()
                return started
            assert latest is not None
            started_snapshot = self._snapshot_locked(latest)

        self._notify_started(binding, started_snapshot)
        return started

    async def dispatch_async(self, job_id: str) -> JobOutcome:
        """Dispatch without running durable registry writes on the event loop.

        The attempt task is created on its owning loop, but waits behind a gate
        until :meth:`start_attempt` has synchronously persisted runtime ownership
        in a worker thread.  This retains durable-before-execution ordering while
        keeping whole-registry serialization, replacement, and fsync off ASGI.
        """
        command = "dispatch"
        loop = asyncio.get_running_loop()
        start_gate = asyncio.Event()

        with self._lock:
            managed = self._active.get(job_id)
            if managed is None:
                return self._error(command, "job_not_found", "The job was not found.")
            if not self._accepting_dispatch:
                return self._error(
                    command,
                    "dispatch_stopped",
                    "Managed dispatch is stopped for service shutdown.",
                    managed,
                )
            binding = self._dispatchers.get(job_id)
            if binding is None:
                return self._error(
                    command,
                    "dispatch_not_bound",
                    "The job has no execution binding.",
                    managed,
                )
            if managed.runtime.task is not None:
                return self._error(
                    command,
                    "runtime_already_owned",
                    "The current attempt already has a runtime owner.",
                    managed,
                )
            if (
                managed.snapshot.state is not JobState.QUEUED
                or managed.snapshot.desired_state is not DesiredJobState.RUNNING
            ):
                return self._error(
                    command,
                    "invalid_transition",
                    "Only queued work with running desired state can dispatch.",
                    managed,
                )

            if binding.loop is not loop:
                binding = replace(binding, loop=loop)
                self._dispatchers[job_id] = binding
            attempt = managed.snapshot.attempt.number
            control = RunControlToken()
            task = loop.create_task(
                self._run_attempt_after_start(
                    start_gate,
                    job_id=job_id,
                    attempt=attempt,
                    control=control,
                    binding=binding,
                ),
                name=f"vaultspec-job-{job_id}-attempt-{attempt}",
            )
            self._retiring_tasks.add(task)
            task.add_done_callback(
                partial(
                    self._complete_attempt,
                    job_id,
                    attempt,
                    binding=binding,
                )
            )

        try:
            started = await _run_in_thread(
                partial(self.start_attempt, job_id, task=task, control=control)
            )
        except BaseException:
            task.cancel()
            raise

        with self._lock:
            latest = self._active.get(job_id)
            owns_runtime = latest is not None and latest.runtime.task is task
            if not owns_runtime:
                task.cancel()
                return started
            assert latest is not None
            started_snapshot = self._snapshot_locked(latest)

        start_gate.set()
        self._notify_started(binding, started_snapshot)
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
                terminal: _ManagedJob | None = None
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
        binding: _JobDispatchBinding,
    ) -> _AttemptExit:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("managed attempt requires an asyncio task")
        context = JobAttemptContext(
            manager=self,
            job_id=job_id,
            attempt=attempt,
            task=task,
            control=control,
        )
        started = time.perf_counter()
        result: JobExecutionResult | None = None
        control_signal: PauseRequested | CancelRequested | ShutdownRequested | None = (
            None
        )
        error: BaseException | None = None
        release_persisted = False
        try:
            result = await _run_in_thread(
                self._run_worker_attempt,
                context,
                binding,
                limiter=get_index_limiter(),
            )
        except (PauseRequested, CancelRequested, ShutdownRequested) as exc:
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
        return _AttemptExit(
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
        binding: _JobDispatchBinding,
    ) -> _AttemptExit:
        """Hold execution until its runtime ownership is durably published."""
        await start_gate.wait()
        return await self._run_attempt(
            job_id=job_id,
            attempt=attempt,
            control=control,
            binding=binding,
        )

    def _run_worker_attempt(
        self,
        context: JobAttemptContext,
        binding: _JobDispatchBinding,
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
        capacity_persisted = context.set_resources(
            started=self._process_resource_snapshot(),
            index_capacity_held=True,
        )
        if not capacity_persisted:
            raise RuntimeError("could not publish managed index-capacity ownership")
        return binding.runner(context)

    def _complete_attempt(
        self,
        job_id: str,
        attempt: int,
        task: asyncio.Task[_AttemptExit],
        binding: _JobDispatchBinding,
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
    def _attempt_exit(task: asyncio.Task[_AttemptExit]) -> _AttemptExit:
        """Read the task result while preserving asynchronous failures as data."""
        try:
            return task.result()
        except BaseException as exc:
            return _AttemptExit(
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
        task: asyncio.Task[_AttemptExit],
        exit_state: _AttemptExit,
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
                attempt=attempt,
                task=task,
                state=JobState.SUCCEEDED,
                result=result.summary if result is not None else None,
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
        binding: _JobDispatchBinding,
        exit_state: _AttemptExit,
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
        task: asyncio.Task[_AttemptExit],
        exit_state: _AttemptExit,
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
            attempt=attempt,
            task=task,
            state=state,
            result=result,
            error_kind=("interrupted" if interrupted else classify_error_text(result)),
        )

    @staticmethod
    def _notify_started(binding: _JobDispatchBinding, snapshot: JobSnapshot) -> None:
        callback = binding.on_started
        if callback is None:
            return
        try:
            callback(snapshot)
        except Exception:
            logger.exception("managed job start callback failed")

    @staticmethod
    def _notify_finished(
        binding: _JobDispatchBinding,
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

    def _replay_idempotent_locked(
        self,
        normalized_key: str | None,
        signature: tuple[JobSpec, JobInitiator, bool],
    ) -> JobOutcome | None:
        """Resolve an idempotency key against existing bindings.

        Returns the outcome to hand back when the key conflicts with a
        different request or replays an existing job, or ``None`` when
        admission should proceed - including when the bound job has since
        disappeared, whose stale binding is dropped here.
        """
        if normalized_key is None:
            return None
        binding = self._idempotency.get(normalized_key)
        if binding is None:
            return None
        self._idempotency.move_to_end(normalized_key)
        existing = self._get_locked(binding.job_id)
        if binding.signature != signature:
            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.ERROR,
                code="idempotency_key_conflict",
                message=(
                    "The idempotency key is already bound to a different job request."
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
        return None

    def _adopt_equivalent_locked(
        self,
        equivalent: JobSnapshot,
        *,
        normalized_key: str | None,
        signature: tuple[JobSpec, JobInitiator, bool],
        backup: _ManagerStateBackup,
    ) -> JobOutcome:
        """Bind an optional replay key to equivalent active work durably."""
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

    def create(
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
            replay = self._replay_idempotent_locked(normalized_key, signature)
            if replay is not None:
                return replay

            equivalent = self._find_equivalent_active_locked(spec)
            if equivalent is not None:
                return self._adopt_equivalent_locked(
                    equivalent,
                    normalized_key=normalized_key,
                    signature=signature,
                    backup=backup,
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
            if not self._accepting_dispatch:
                return self._error(
                    command,
                    "dispatch_stopped",
                    "Managed dispatch is stopped for service shutdown.",
                    managed,
                )
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
        worker_thread: threading.Thread | None = None,
    ) -> bool:
        """Update worker ownership only for the currently attached attempt."""
        with self._lock:
            backup = self._capture_state_locked()
            managed = self._active.get(job_id)
            if managed is None or managed.runtime.task is not task:
                return False
            managed.runtime = replace(
                managed.runtime,
                worker_active=active,
                worker_thread=worker_thread if active else None,
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
        task: asyncio.Task[Any],
        started: ProcessResourceSnapshot | None | object = ...,
        finished: ProcessResourceSnapshot | None | object = ...,
        index_capacity_held: bool | None = None,
        project_lease_held: bool | None = None,
        writer_lock_held: bool | None = None,
        pipeline_active: bool | None = None,
    ) -> bool:
        with self._lock:
            backup = self._capture_state_locked()
            managed = self._active.get(job_id)
            if managed is None or managed.runtime.task is not task:
                return False
            previous = managed.snapshot.resources
            managed.snapshot = replace(
                managed.snapshot,
                resources=replace(
                    previous,
                    started=(
                        previous.started
                        if started is ...
                        else cast("ProcessResourceSnapshot | None", started)
                    ),
                    finished=(
                        previous.finished
                        if finished is ...
                        else cast("ProcessResourceSnapshot | None", finished)
                    ),
                    index_capacity_held=(
                        previous.index_capacity_held
                        if index_capacity_held is None
                        else index_capacity_held
                    ),
                    project_lease_held=(
                        previous.project_lease_held
                        if project_lease_held is None
                        else project_lease_held
                    ),
                    writer_lock_held=(
                        previous.writer_lock_held
                        if writer_lock_held is None
                        else writer_lock_held
                    ),
                    pipeline_active=(
                        previous.pipeline_active
                        if pipeline_active is None
                        else pipeline_active
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
        task: asyncio.Task[Any],
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
        task: asyncio.Task[Any],
        finished: ProcessResourceSnapshot,
    ) -> bool:
        """Atomically clear worker and physical ownership for one exact attempt."""
        with self._lock:
            managed = self._active.get(job_id)
            if managed is None or managed.runtime.task is not task:
                return False
            managed.runtime = replace(
                managed.runtime,
                worker_active=False,
                worker_thread=None,
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

    def _resolve_control_target_locked(
        self,
        command: str,
        job_id: str,
        desired_state: DesiredJobState,
        *,
        expected_revision: int | None,
        mode: str,
    ) -> tuple[_ManagedJob | None, JobOutcome | None]:
        """Resolve and validate the resource targeted by a control request."""
        managed = self._active.get(job_id)
        terminal = None if managed is not None else self._get_terminal_locked(job_id)
        if managed is None and terminal is None:
            return None, self._error(
                command,
                "job_not_found",
                "The job was not found.",
            )
        target = managed if managed is not None else terminal
        if mode == "force":
            return None, self._error(
                command,
                "force_termination_unavailable",
                "Per-job force termination is unavailable for this runtime.",
                target,
            )
        if mode != "graceful":
            return None, self._error(
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
                return None, self._already_satisfied(command, terminal)
            return None, self._error(
                command,
                "invalid_transition",
                "A terminal job cannot change desired state.",
                terminal,
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

    def _request_desired_transition_locked(
        self,
        command: str,
        managed: _ManagedJob,
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
        managed: _ManagedJob,
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
        managed: _ManagedJob,
        outcome: JobOutcome,
        backup: _ManagerStateBackup,
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
                return self._error(command, "job_not_found", "The job was not found.")
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

    def _restore_snapshot_locked(self, snapshot: JobSnapshot, *, now: float) -> None:
        """Restore one validated snapshot with no live execution resources."""
        resumable = snapshot.state in {JobState.QUEUED, JobState.PAUSED}
        restored_runtime = (
            self._process_runtime_snapshot()
            if resumable
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
        if resumable:
            self._active[snapshot.id] = managed
            return
        if snapshot.state in {
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
            return
        self._terminal.append(managed)

    def _restore_jobs_locked(
        self,
        restored_jobs: tuple[JobSnapshot, ...],
        *,
        now: float,
    ) -> None:
        """Restore terminal history before active and interrupted resources."""
        restore_order = [
            *(job for job in restored_jobs if job.state.is_terminal),
            *(job for job in restored_jobs if not job.state.is_terminal),
        ]
        for snapshot in restore_order:
            self._restore_snapshot_locked(snapshot, now=now)

    def _trim_restored_history_locked(self) -> None:
        """Apply the configured terminal bound to restored history."""
        while len(self._terminal) > self._max_terminal_history:
            evicted = self._terminal.popleft()
            self._forget_idempotency_locked(evicted.snapshot.id)

    def _restore_bindings_locked(
        self,
        restored_bindings: tuple[
            tuple[str, _job_persistence.IdempotencyBinding],
            ...,
        ],
    ) -> None:
        """Restore only bindings whose target survived configured retention."""
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

    def restore_persisted(self) -> JobOutcome:
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
            self._restore_jobs_locked(restored_jobs, now=now)
            self._trim_restored_history_locked()
            self._restore_bindings_locked(restored_bindings)

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
        managed: _ManagedJob,
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
            dispatchers=dict(self._dispatchers),
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
        self._dispatchers = backup.dispatchers
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
    def _apply_control_signal_locked(
        managed: _ManagedJob,
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
        self._dispatchers.pop(managed.snapshot.id, None)
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

    @staticmethod
    def _process_resource_snapshot() -> ProcessResourceSnapshot:
        from .memory_probe import current_cuda_mb, current_rss_mb

        cuda_allocated_mb, cuda_reserved_mb = current_cuda_mb()
        return ProcessResourceSnapshot(
            rss_mb=round(current_rss_mb(), 1),
            cuda_allocated_mb=round(cuda_allocated_mb, 1),
            cuda_reserved_mb=round(cuda_reserved_mb, 1),
        )
