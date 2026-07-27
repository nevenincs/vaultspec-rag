"""Cohesive unit coverage for job-management behavior."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import TYPE_CHECKING, cast

import pytest

from ..job_control import QuiesceGate, RunControlToken
from ..job_manager._control import _AttemptTerminal
from ..job_manager.manager import JobManager
from ..job_manager.models import (
    JobAttemptContext,
    JobExecutionResult,
    ProgressUpdate,
)
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobResourceSnapshot,
    JobSource,
    JobSpec,
    JobState,
)
from ._job_manager_transition_helpers import (
    assert_delivered_pause_requeues_resume,
    create_paused_vault_job,
    resume_paused_job,
)

if TYPE_CHECKING:
    from .. import job_models

pytestmark = [pytest.mark.unit]

_TEST_PROJECT_ROOT = os.path.abspath(os.path.join(os.sep, "project"))
_TEST_PROJECT_ROOT_OTHER = os.path.abspath(os.path.join(os.sep, "other"))
_TEST_PROJECT_ROOT_DIFFERENT = os.path.abspath(os.path.join(os.sep, "different"))


class TestManagedJobTransitions:
    """Revision and attempt identity make lifecycle races deterministic."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_the_attempt_claim_boundary(self) -> None:
        manager = JobManager(max_nonterminal=1, state_path=None)
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                _TEST_PROJECT_ROOT,
                JobMode.INCREMENTAL,
            ),
            JobInitiator("service", "shutdown-race", _TEST_PROJECT_ROOT),
        )
        assert created.job is not None
        task = asyncio.create_task(asyncio.Event().wait())
        try:
            assert manager.begin_shutdown() == ()
            outcome = manager.start_attempt(
                created.job.id,
                task=task,
                control=RunControlToken(),
            )
            assert outcome.code == "dispatch_stopped"
            retained = manager.get(created.job.id)
            assert retained is not None
            assert retained.state is JobState.QUEUED
            assert retained.runtime.task_active is False
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_pause_resume_race_requeues_after_delivered_unwind(self) -> None:
        manager = JobManager(max_nonterminal=2, state_path=None)
        job_id = create_paused_vault_job(manager)
        resume_paused_job(manager, job_id)

        task = asyncio.create_task(asyncio.Event().wait())
        control = RunControlToken()
        try:
            assert_delivered_pause_requeues_resume(manager, job_id, task, control)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_progress_requires_the_exact_current_attempt_and_task(self) -> None:
        manager = JobManager(max_nonterminal=1, state_path=None)
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.INCREMENTAL,
        )
        created = manager.create(
            spec,
            JobInitiator("watcher", "watcher_code_index", _TEST_PROJECT_ROOT),
        )
        assert created.job is not None
        owner_task = asyncio.create_task(asyncio.Event().wait())
        stale_task = asyncio.create_task(asyncio.Event().wait())
        try:
            assert (
                manager.start_attempt(
                    created.job.id,
                    task=owner_task,
                    control=RunControlToken(),
                ).code
                == "attempt_started"
            )
            assert (
                manager.update_progress(
                    created.job.id,
                    ProgressUpdate(1, stale_task, "embed", completed=1, total=2),
                ).code
                == "stale_attempt_ignored"
            )
            assert (
                manager.update_progress(
                    created.job.id,
                    ProgressUpdate(1, owner_task, cast("str", 7)),
                ).code
                == "invalid_progress"
            )
            assert (
                manager.update_progress(
                    created.job.id,
                    ProgressUpdate(
                        1,
                        owner_task,
                        "embed",
                        completed=cast("int", 1.5),
                        total=cast("int", 2.0),
                    ),
                ).code
                == "invalid_progress"
            )
            updated = manager.update_progress(
                created.job.id,
                ProgressUpdate(1, owner_task, "embed", completed=1, total=2),
            )
            assert updated.code == "progress_updated"
            assert updated.job is not None
            assert updated.job.progress is not None
            assert updated.job.progress.step == "embed"
            assert updated.job.progress.completed == 1
            assert updated.job.revision == created.job.revision + 2
            assert (
                manager.update_progress(
                    created.job.id,
                    ProgressUpdate(2, owner_task, "publish"),
                ).code
                == "stale_attempt_ignored"
            )
            unchanged = manager.get(created.job.id)
            assert unchanged is not None
            assert unchanged.progress == updated.job.progress
        finally:
            owner_task.cancel()
            stale_task.cancel()
            for task in (owner_task, stale_task):
                with pytest.raises(asyncio.CancelledError):
                    await task

    @pytest.mark.asyncio
    async def test_cancellation_is_immediate_or_acknowledged_after_unwind(
        self,
    ) -> None:
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            _TEST_PROJECT_ROOT,
            JobMode.INCREMENTAL,
        )
        initiator = JobInitiator("cli", "server job stop", _TEST_PROJECT_ROOT)

        queued_manager = JobManager(max_nonterminal=1, state_path=None)
        queued = queued_manager.create(spec, initiator)
        assert queued.job is not None
        immediate = queued_manager.set_desired_state(
            queued.job.id,
            DesiredJobState.CANCELLED,
        )
        assert immediate.job is not None
        assert immediate.job.state is JobState.CANCELLED
        assert immediate.job.timestamps.control_acknowledged_at is not None
        assert (
            queued_manager.set_desired_state(
                queued.job.id,
                DesiredJobState.CANCELLED,
                expected_revision=1,
            ).code
            == "already_satisfied"
        )

        running_manager = JobManager(max_nonterminal=1, state_path=None)
        running = running_manager.create(spec, initiator)
        assert running.job is not None
        task = asyncio.create_task(asyncio.Event().wait())
        control = RunControlToken()
        try:
            running_manager.start_attempt(running.job.id, task=task, control=control)
            assert running_manager.set_worker_active(
                running.job.id,
                task=task,
                active=True,
            )
            assert running_manager.set_execution_resources(
                running.job.id,
                task=task,
                resources=JobResourceSnapshot(
                    started=None,
                    finished=None,
                    pipeline_active=True,
                ),
            )
            running_manager.set_desired_state(
                running.job.id,
                DesiredJobState.PAUSED,
            )
            cancelling = running_manager.set_desired_state(
                running.job.id,
                DesiredJobState.CANCELLED,
            )
            assert cancelling.job is not None
            assert cancelling.job.state is JobState.CANCELLING
            control_snapshot = control.snapshot()
            assert control_snapshot.desired is not None
            assert control_snapshot.desired.value == "cancel"
            assert (
                running_manager.acknowledge_control(
                    running.job.id,
                    attempt=1,
                    task=task,
                ).code
                == "resources_still_owned"
            )
            assert running_manager.set_worker_active(
                running.job.id,
                task=task,
                active=False,
            )
            assert running_manager.set_execution_resources(
                running.job.id,
                task=task,
                resources=JobResourceSnapshot(started=None, finished=None),
            )
            acknowledged = running_manager.acknowledge_control(
                running.job.id,
                attempt=1,
                task=task,
            )
            assert acknowledged.job is not None
            assert acknowledged.job.state is JobState.CANCELLED
            assert (
                running_manager.set_desired_state(
                    running.job.id,
                    DesiredJobState.RUNNING,
                ).code
                == "invalid_transition"
            )
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_terminal_first_writer_retry_and_delete_contract(self) -> None:
        manager = JobManager(
            max_nonterminal=2,
            max_terminal_history=2,
            state_path=None,
        )
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        )
        initiator = JobInitiator("http", "POST /jobs", _TEST_PROJECT_ROOT)
        created = manager.create(spec, initiator)
        assert created.job is not None
        job_id = created.job.id
        task = asyncio.create_task(asyncio.Event().wait())
        control = RunControlToken()
        try:
            assert manager.start_attempt(job_id, task=task, control=control).code == (
                "attempt_started"
            )
            failed = manager.finish_attempt(
                job_id,
                _AttemptTerminal(
                    attempt=1,
                    task=task,
                    state=JobState.FAILED,
                    result="index failed",
                    error_kind="other",
                ),
            )
            assert failed.job is not None
            assert failed.job.state is JobState.FAILED
            assert (
                manager.finish_attempt(
                    job_id,
                    _AttemptTerminal(
                        attempt=1,
                        task=task,
                        state=JobState.SUCCEEDED,
                        result="late success",
                    ),
                ).job
                == failed.job
            )
            assert (
                manager.set_desired_state(job_id, DesiredJobState.RUNNING).code
                == "invalid_transition"
            )
            assert (
                manager.set_desired_state(
                    job_id,
                    DesiredJobState.CANCELLED,
                    mode="force",
                ).code
                == "force_termination_unavailable"
            )

            retried = manager.retry(job_id)
            assert retried.job is not None
            assert retried.job.id != job_id
            assert retried.job.attempt.parent_job_id == job_id
            assert manager.delete(retried.job.id).code == "job_not_terminal"
            assert manager.delete(job_id).code == "job_deleted"
            assert manager.get(job_id) is None
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_dispatched_attempt_token_observes_shared_quiesce_gate() -> None:
    """Pausing the manager-injected gate parks a dispatched attempt's token.

    Guard: the negative half (the attempt does not pass its checkpoint while
    the gate is paused) is bounded so a token built without the shared gate
    fails the not-passed assertion instead of hanging. The mutation that
    proves red is constructing the dispatch token without the manager's gate.
    """
    gate = QuiesceGate()
    manager = JobManager(max_nonterminal=1, state_path=None, quiesce_gate=gate)
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        ),
        JobInitiator("cli", "server job create", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    job_id = created.job.id
    reached = threading.Event()
    passed = threading.Event()
    finished = threading.Event()

    def runner(
        context: JobAttemptContext,
    ) -> JobExecutionResult:
        reached.set()
        context.control.checkpoint()
        passed.set()
        return JobExecutionResult(summary="done")

    def on_finished(
        snapshot: job_models.JobSnapshot,
        duration_seconds: float,
        result: JobExecutionResult | None,
        error: BaseException | None,
    ) -> None:
        del snapshot, duration_seconds, result, error
        finished.set()

    assert (
        manager.bind_dispatch(job_id, runner, on_finished=on_finished).code
        == "dispatch_bound"
    )
    gate.pause()
    # The gate must reopen even on a red assertion, or the parked attempt
    # worker outlives the test and hangs the suite at interpreter exit.
    try:
        assert manager.dispatch(job_id).code == "attempt_started"
        assert await asyncio.to_thread(reached.wait, 5.0)
        assert not await asyncio.to_thread(passed.wait, 0.5), (
            "dispatched attempt did not park at the shared paused gate"
        )
    finally:
        gate.resume()
    assert await asyncio.to_thread(passed.wait, 5.0), (
        "dispatched attempt did not resume with the shared gate"
    )
    assert await asyncio.to_thread(finished.wait, 5.0)
    final = manager.get(job_id)
    assert final is not None
    assert final.state is JobState.SUCCEEDED
