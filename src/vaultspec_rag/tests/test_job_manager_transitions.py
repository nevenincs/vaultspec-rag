"""Cohesive unit coverage for job-management behavior."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest

from ..indexer._run_ledger_models import RunAuthority
from ..job_control import PauseRequested, RunControlToken
from ..job_manager._control import AttemptTerminal
from ..job_manager.manager import JobManager
from ..job_manager.models import (
    ProgressUpdate,
    ResourceUpdate,
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
from ..job_persistence import load_persisted_state
from ..service_quiesce import ServiceQuiesceController
from ._job_manager_transition_helpers import (
    assert_delivered_pause_requeues_resume,
    create_paused_vault_job,
    pending_attempt,
    resume_paused_job,
)
from ._job_roots import _TEST_PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestManagedJobTransitions:
    """Revision and attempt identity make lifecycle races deterministic."""

    @pytest.mark.asyncio
    async def test_new_resumed_attempt_clears_resource_boundaries(
        self, tmp_path: Path
    ) -> None:
        """Omitting the canonical reset carries the paused attempt's readings."""
        controller = ServiceQuiesceController()
        path = tmp_path / "jobs.json"
        manager = JobManager(
            quiesce_controller=controller, max_nonterminal=1, state_path=path
        )
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.VAULT,
                _TEST_PROJECT_ROOT,
                JobMode.REBUILD,
                RunAuthority.REBUILD,
            ),
            JobInitiator("test", "resource-resume", _TEST_PROJECT_ROOT),
        )
        assert created.job is not None
        job_id = created.job.id
        tasks = [asyncio.create_task(pending_attempt()) for _ in range(2)]
        control = RunControlToken()
        try:
            assert manager.start_attempt(
                job_id, task=tasks[0], control=control
            ).code == ("attempt_started")
            assert manager.update_execution_resources(
                job_id,
                task=tasks[0],
                update=ResourceUpdate(started=manager._process_resource_snapshot()),
            )
            manager.set_desired_state(job_id, DesiredJobState.PAUSED)
            with pytest.raises(PauseRequested):
                control.checkpoint()
            assert manager.release_execution_resources(
                job_id, task=tasks[0], finished=manager._process_resource_snapshot()
            )
            paused = manager.acknowledge_control(job_id, attempt=1, task=tasks[0])
            assert paused.job is not None and paused.job.state is JobState.PAUSED
            assert paused.job.resources.started is not None
            assert paused.job.resources.finished is not None
            assert not paused.job.resources.holds_anything
            assert controller.snapshot().active_compute_tickets == 0

            resumed = manager.set_desired_state(job_id, DesiredJobState.RUNNING)
            assert resumed.job is not None and resumed.job.state is JobState.QUEUED
            assert resumed.job.attempt.number == 2
            assert resumed.job.resources.started is None, (
                "new resumed attempt retained prior started resource reading"
            )
            assert resumed.job.resources.finished is None, (
                "new resumed attempt retained prior finished resource reading"
            )
            assert not resumed.job.resources.holds_anything
            durable = load_persisted_state(path).jobs[0]
            assert durable.resources == resumed.job.resources
            assert durable.attempt == resumed.job.attempt
            assert (
                manager.start_attempt(
                    job_id, task=tasks[1], control=RunControlToken()
                ).code
                == "attempt_started"
            )
            assert manager.update_execution_resources(
                job_id,
                task=tasks[1],
                update=ResourceUpdate(started=manager._process_resource_snapshot()),
            )
            running = manager.get(job_id)
            assert running is not None and running.resources.started is not None
            assert running.resources.finished is None
            assert manager.release_execution_resources(
                job_id, task=tasks[1], finished=manager._process_resource_snapshot()
            )
            assert (
                manager.finish_attempt(
                    job_id,
                    AttemptTerminal(
                        attempt=2,
                        task=tasks[1],
                        state=JobState.SUCCEEDED,
                        result="complete",
                    ),
                ).code
                == "job_finished"
            )
            assert controller.snapshot().active_compute_tickets == 0
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with pytest.raises(asyncio.CancelledError):
                    await task

    @pytest.mark.asyncio
    async def test_pause_withdrawal_preserves_boundaries_and_terminal_history(
        self,
    ) -> None:
        """A same-attempt withdrawal must not run the new-attempt reset."""
        controller = ServiceQuiesceController()
        manager = JobManager(
            quiesce_controller=controller, max_nonterminal=2, state_path=None
        )
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.VAULT,
                _TEST_PROJECT_ROOT,
                JobMode.REBUILD,
                RunAuthority.REBUILD,
            ),
            JobInitiator("test", "resource-withdrawal", _TEST_PROJECT_ROOT),
        )
        assert created.job is not None
        job_id = created.job.id
        task = asyncio.create_task(pending_attempt())
        control = RunControlToken()
        try:
            manager.start_attempt(job_id, task=task, control=control)
            assert manager.update_execution_resources(
                job_id,
                task=task,
                update=ResourceUpdate(started=manager._process_resource_snapshot()),
            )
            running = manager.get(job_id)
            assert running is not None
            manager.set_desired_state(job_id, DesiredJobState.PAUSED)
            withdrawn = manager.set_desired_state(job_id, DesiredJobState.RUNNING)
            assert withdrawn.code == "pause_withdrawn"
            assert withdrawn.job is not None
            assert withdrawn.job.attempt.number == 1
            assert withdrawn.job.resources == running.resources, (
                "same attempt withdrawal cleared resource boundaries"
            )
            assert controller.snapshot().active_compute_tickets == 1
            assert manager.release_execution_resources(
                job_id, task=task, finished=manager._process_resource_snapshot()
            )
            failed = manager.finish_attempt(
                job_id,
                AttemptTerminal(
                    attempt=1,
                    task=task,
                    state=JobState.FAILED,
                    result="failed after release",
                    error_kind="other",
                ),
            )
            assert failed.job is not None
            assert failed.job.resources.started is not None
            assert failed.job.resources.finished is not None
            retried = manager.retry(job_id)
            assert retried.job is not None
            assert retried.job.resources == JobResourceSnapshot(None, None)
            assert manager.get(job_id) == failed.job
            assert controller.snapshot().active_compute_tickets == 0
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_shutdown_closes_the_attempt_claim_boundary(self) -> None:
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=None,
        )
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                _TEST_PROJECT_ROOT,
                JobMode.INCREMENTAL,
                RunAuthority.PUBLICATION,
            ),
            JobInitiator("service", "shutdown-race", _TEST_PROJECT_ROOT),
        )
        assert created.job is not None
        task = asyncio.create_task(pending_attempt())
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
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=None,
        )
        job_id = create_paused_vault_job(manager)
        resume_paused_job(manager, job_id)
        resumed = manager.get(job_id)
        assert resumed is not None
        assert resumed.spec.authority is RunAuthority.PUBLICATION

        task = asyncio.create_task(pending_attempt())
        control = RunControlToken()
        try:
            assert_delivered_pause_requeues_resume(manager, job_id, task, control)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_progress_requires_the_exact_current_attempt_and_task(self) -> None:
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=None,
        )
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.INCREMENTAL,
            RunAuthority.PUBLICATION,
        )
        created = manager.create(
            spec,
            JobInitiator("watcher", "watcher_code_index", _TEST_PROJECT_ROOT),
        )
        assert created.job is not None
        owner_task = asyncio.create_task(pending_attempt())
        stale_task = asyncio.create_task(pending_attempt())
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
            RunAuthority.PUBLICATION,
        )
        initiator = JobInitiator("cli", "server job stop", _TEST_PROJECT_ROOT)

        queued_manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=None,
        )
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

        running_manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=None,
        )
        running = running_manager.create(spec, initiator)
        assert running.job is not None
        task = asyncio.create_task(pending_attempt())
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
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            max_terminal_history=2,
            state_path=None,
        )
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
            RunAuthority.REBUILD,
        )
        initiator = JobInitiator("http", "POST /jobs", _TEST_PROJECT_ROOT)
        created = manager.create(spec, initiator)
        assert created.job is not None
        job_id = created.job.id
        task = asyncio.create_task(pending_attempt())
        control = RunControlToken()
        try:
            assert manager.start_attempt(job_id, task=task, control=control).code == (
                "attempt_started"
            )
            failed = manager.finish_attempt(
                job_id,
                AttemptTerminal(
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
                    AttemptTerminal(
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
            assert retried.job.spec.authority is RunAuthority.REBUILD
            assert manager.delete(retried.job.id).code == "job_not_terminal"
            assert manager.delete(job_id).code == "job_deleted"
            assert manager.get(job_id) is None
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
