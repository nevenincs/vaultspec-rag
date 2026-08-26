"""Real CPU/thread coverage for controller-bound managed-job quiesce."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING

import pytest

from ..job_manager.manager import JobManager
from ..job_manager.models import (
    JobAttemptContext,
    JobExecutionResult,
    QuiescedResumePersistence,
    QuiescedResumeResult,
    QuiescedResumeStatus,
)
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobOutcomeStatus,
    JobSource,
    JobSpec,
    JobState,
)
from ..service_quiesce import QuiesceState, ServiceQuiesceController
from ._job_roots import _TEST_PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestGpuLockWaitTelemetry:
    """Timed GPU-lock acquisition accumulates per attempt and publishes."""

    def test_timed_acquire_credits_the_active_scope(self) -> None:
        from ..job_control import gpu_lock_wait_scope, timed_gpu_lock

        lock = threading.Lock()
        lock.acquire()
        releaser = threading.Timer(0.2, lock.release)
        releaser.start()
        try:
            with gpu_lock_wait_scope() as accumulator:
                with timed_gpu_lock(lock):
                    pass
                assert accumulator.seconds >= 0.1
        finally:
            releaser.cancel()
            if lock.locked():
                lock.release()

    @pytest.mark.asyncio
    async def test_lock_wait_publishes_on_the_job_record(self) -> None:
        from ..job_control import timed_gpu_lock

        controller = ServiceQuiesceController()
        manager = JobManager(
            max_nonterminal=1,
            state_path=None,
            quiesce_controller=controller,
        )
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.VAULT,
                _TEST_PROJECT_ROOT,
                JobMode.REBUILD,
            ),
            JobInitiator("test", "gpu-wait-telemetry", None),
        )
        assert created.job is not None
        gpu_lock = threading.Lock()

        def runner(context: JobAttemptContext) -> JobExecutionResult:
            del context
            gpu_lock.acquire()
            releaser = threading.Timer(0.2, gpu_lock.release)
            releaser.start()
            try:
                with timed_gpu_lock(gpu_lock):
                    time.sleep(0.05)
            finally:
                releaser.cancel()
            return JobExecutionResult(summary="encoded")

        assert manager.bind_dispatch(created.job.id, runner).code == "dispatch_bound"
        assert (await manager.dispatch_async(created.job.id)).code == "attempt_started"
        await _await_state(manager, created.job.id, JobState.SUCCEEDED)
        completed = manager.get(created.job.id)
        assert completed is not None
        assert completed.gpu_lock_wait_seconds is not None
        assert completed.gpu_lock_wait_seconds >= 0.1
        assert completed.to_dict()["gpu_lock_wait_seconds"] == (
            completed.gpu_lock_wait_seconds
        )


async def _await_state(manager: JobManager, job_id: str, state: JobState) -> None:
    deadline = asyncio.get_running_loop().time() + 10.0
    while True:
        snapshot = manager.get(job_id)
        assert snapshot is not None
        if snapshot.state is state:
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"{job_id} did not reach {state.value}")
        await asyncio.sleep(0.01)


def _warming_controller() -> ServiceQuiesceController:
    controller = ServiceQuiesceController()
    assert controller.begin_pause().snapshot.state is QuiesceState.PAUSING
    assert controller.wait_for_drain(timeout=0).achieved
    assert controller.acknowledge_vram_released().achieved
    assert controller.begin_warming().snapshot.state is QuiesceState.WARMING
    return controller


def _create_quiesced_job(
    controller: ServiceQuiesceController,
    state_path: Path | None,
) -> tuple[JobManager, str]:
    manager = JobManager(
        max_nonterminal=1,
        state_path=state_path,
        quiesce_controller=controller,
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        ),
        JobInitiator("test", "quiesced-recovery", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    job_id = created.job.id
    assert (
        manager.defer_unstarted_for_quiesce(job_id).code
        == "quiesce_deferred_before_start"
    )
    return manager, job_id


async def _invalidate_loopless_recovery_before_callback(
    manager: JobManager,
    job_id: str,
    prepared: QuiescedResumeResult,
    *,
    shutdown: bool,
) -> tuple[tuple[str, ...], bool, str]:
    """Control one claimed recovery while its service-loop callback is queued."""
    scheduled: list[tuple[str, ...]] = []
    callback_blocked = threading.Event()
    release_callback = threading.Event()
    claim_observed: list[bool] = []
    controls: list[str] = []

    def block_service_loop() -> None:
        callback_blocked.set()
        assert release_callback.wait(timeout=5.0)

    def schedule_recovery() -> None:
        scheduled.append(manager.dispatch_prepared_quiesced_resume(prepared))

    def control_before_recovery_callback() -> None:
        claimed = False
        try:
            assert callback_blocked.wait(timeout=5.0)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                with manager._lock:
                    claimed = job_id in manager._pending_quiesced_dispatches
                if claimed:
                    break
                time.sleep(0.01)
            claim_observed.append(claimed)
            if claimed:
                if shutdown:
                    assert manager.begin_shutdown() == ()
                    controls.append("shutdown")
                else:
                    controls.append(
                        manager.set_desired_state(
                            job_id,
                            DesiredJobState.CANCELLED,
                        ).code
                    )
        finally:
            release_callback.set()

    asyncio.get_running_loop().call_soon(block_service_loop)
    scheduler = threading.Thread(
        target=schedule_recovery,
        name="blocked-loop-recovery-scheduler",
    )
    controller_thread = threading.Thread(
        target=control_before_recovery_callback,
        name="blocked-loop-recovery-control",
    )
    scheduler.start()
    controller_thread.start()
    await asyncio.to_thread(scheduler.join, 5.0)
    await asyncio.to_thread(controller_thread.join, 5.0)

    assert not scheduler.is_alive()
    assert not controller_thread.is_alive()
    assert len(scheduled) == 1
    assert len(claim_observed) == 1
    assert len(controls) == 1
    return scheduled[0], claim_observed[0], controls[0]


def _assert_paused_job_released_everything(
    manager: JobManager,
    controller: ServiceQuiesceController,
    job_id: str,
) -> None:
    """Assert the paused attempt surrendered its ticket and every resource."""
    quiesced = manager.get(job_id)
    assert quiesced is not None
    assert quiesced.id == job_id
    assert quiesced.desired_state is DesiredJobState.RUNNING
    assert not quiesced.resources.holds_anything
    assert controller.snapshot().active_compute_tickets == 0
    assert controller.wait_for_drain(timeout=0).achieved
    assert controller.acknowledge_vram_released().achieved


def _prepared_durable_resume(
    manager: JobManager,
    controller: ServiceQuiesceController,
    job_id: str,
) -> QuiescedResumeResult:
    """Warm the controller and return the durable resume it prepared."""
    assert controller.begin_warming().snapshot.state is QuiesceState.WARMING
    prepared = manager.prepare_quiesced_resume()
    assert prepared.status is QuiescedResumeStatus.PREPARED
    assert prepared.persistence is QuiescedResumePersistence.DURABLE
    assert prepared.job_ids == (job_id,)
    return prepared


@pytest.mark.asyncio
async def test_quiesce_releases_ticket_and_resources_before_same_id_resume() -> None:
    """A real worker unwinds, drains, and reconciles only after running."""
    controller = ServiceQuiesceController()
    manager = JobManager(
        max_nonterminal=1,
        state_path=None,
        quiesce_controller=controller,
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        ),
        JobInitiator("test", "controller-quiesce", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    job_id = created.job.id
    first_attempt_ready = threading.Event()
    release_first_attempt = threading.Event()

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        if context.attempt == 1:
            first_attempt_ready.set()
            assert release_first_attempt.wait(timeout=5.0)
            context.control.checkpoint()
        return JobExecutionResult(summary=f"attempt {context.attempt} complete")

    assert manager.bind_dispatch(job_id, runner).code == "dispatch_bound"
    assert (await manager.dispatch_async(job_id)).code == "attempt_started"
    assert await asyncio.to_thread(first_attempt_ready.wait, 5.0)
    assert controller.snapshot().active_compute_tickets == 1

    assert controller.begin_pause().snapshot.state is QuiesceState.PAUSING
    assert manager.request_quiesce_attempts() == (job_id,)
    release_first_attempt.set()
    await _await_state(manager, job_id, JobState.PAUSED)

    _assert_paused_job_released_everything(manager, controller, job_id)
    prepared = _prepared_durable_resume(manager, controller, job_id)
    assert controller.complete_warming().snapshot.state is QuiesceState.RUNNING
    assert manager.dispatch_prepared_quiesced_resume(prepared) == (job_id,)
    await _await_state(manager, job_id, JobState.SUCCEEDED)

    completed = manager.get(job_id)
    assert completed is not None
    assert completed.id == job_id
    assert completed.attempt.number == 2


@pytest.mark.asyncio
async def test_unpublished_prepare_failure_retries_without_dispatch(
    tmp_path: Path,
) -> None:
    """A real parent-path write failure rolls back and retry dispatches once."""
    state_path = tmp_path / "state" / "jobs.json"
    controller = _warming_controller()
    manager, job_id = _create_quiesced_job(controller, state_path)
    runner_started = threading.Event()

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        runner_started.set()
        return JobExecutionResult(summary=f"attempt {context.attempt} complete")

    assert manager.bind_dispatch(job_id, runner).code == "dispatch_bound"
    state_path.unlink()
    state_path.parent.rmdir()
    state_path.parent.write_text("not a directory", encoding="utf-8")

    failed = manager.prepare_quiesced_resume()
    assert failed.status is QuiescedResumeStatus.PERSISTENCE_UNPUBLISHED
    assert failed.job_ids == (job_id,)
    assert failed.persistence is QuiescedResumePersistence.UNPUBLISHED
    retained = manager.get(job_id)
    assert retained is not None
    assert retained.state is JobState.PAUSED
    assert retained.attempt.number == 1
    assert manager.dispatch_prepared_quiesced_resume(failed) == ()
    assert not runner_started.is_set()

    state_path.parent.unlink()
    state_path.parent.mkdir()
    retried = manager.prepare_quiesced_resume()
    assert retried.status is QuiescedResumeStatus.PREPARED
    queued = manager.get(job_id)
    assert queued is not None
    assert queued.state is JobState.QUEUED
    assert queued.attempt.number == 2

    assert controller.complete_warming().snapshot.state is QuiesceState.RUNNING
    assert manager.dispatch_prepared_quiesced_resume(retried) == (job_id,)
    await _await_state(manager, job_id, JobState.SUCCEEDED)
    assert runner_started.is_set()


@pytest.mark.asyncio
async def test_durable_queued_prepare_recovers_after_restart_without_new_id(
    tmp_path: Path,
) -> None:
    """A durable queued preparation survives a restart and dispatches once."""
    state_path = tmp_path / "jobs.json"
    controller = _warming_controller()
    manager, job_id = _create_quiesced_job(controller, state_path)
    prepared = manager.prepare_quiesced_resume()
    assert prepared.status is QuiescedResumeStatus.PREPARED
    assert prepared.job_ids == (job_id,)

    restarted_controller = _warming_controller()
    restarted = JobManager(
        max_nonterminal=1,
        state_path=state_path,
        quiesce_controller=restarted_controller,
    )
    assert restarted.restore_persisted().code == "job_state_restored"
    restored = restarted.get(job_id)
    assert restored is not None
    assert restored.state is JobState.QUEUED
    assert restored.attempt.number == 2
    attempts: list[int] = []

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        attempts.append(context.attempt)
        return JobExecutionResult(summary="recovered")

    assert restarted.bind_dispatch(job_id, runner).code == "dispatch_bound"
    assert (
        restarted_controller.complete_warming().snapshot.state is QuiesceState.RUNNING
    )
    assert restarted.recover_running_quiesced_resume() == (job_id,)
    await _await_state(restarted, job_id, JobState.SUCCEEDED)
    assert attempts == [2]


def test_concurrent_unpublished_preparation_reports_failure_without_dispatch(
    tmp_path: Path,
) -> None:
    """Concurrent warming callers report the same real persistence failure."""
    state_path = tmp_path / "state" / "jobs.json"
    controller = _warming_controller()
    manager, job_id = _create_quiesced_job(controller, state_path)
    runner_started = threading.Event()

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        del context
        runner_started.set()
        return JobExecutionResult(summary="unexpected")

    assert manager.bind_dispatch(job_id, runner).code == "dispatch_bound"
    state_path.unlink()
    state_path.parent.rmdir()
    state_path.parent.write_text("not a directory", encoding="utf-8")
    barrier = threading.Barrier(3)
    results: list[QuiescedResumeResult] = []

    def prepare() -> None:
        barrier.wait(timeout=5.0)
        results.append(manager.prepare_quiesced_resume())

    first = threading.Thread(target=prepare)
    second = threading.Thread(target=prepare)
    first.start()
    second.start()
    barrier.wait(timeout=5.0)
    first.join(timeout=5.0)
    second.join(timeout=5.0)
    assert not first.is_alive()
    assert not second.is_alive()
    assert len(results) == 2
    assert all(
        result.status is QuiescedResumeStatus.PERSISTENCE_UNPUBLISHED
        for result in results
    )
    assert all(
        result.persistence is QuiescedResumePersistence.UNPUBLISHED
        for result in results
    )
    retained = manager.get(job_id)
    assert retained is not None
    assert retained.state is JobState.PAUSED
    assert not runner_started.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "desired_state", [DesiredJobState.PAUSED, DesiredJobState.CANCELLED]
)
async def test_prepared_dispatch_rechecks_operator_intent(
    desired_state: DesiredJobState,
) -> None:
    """A pause or cancellation race prevents a prepared ID from dispatching."""
    controller = _warming_controller()
    manager, job_id = _create_quiesced_job(controller, None)
    runner_started = threading.Event()

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        del context
        runner_started.set()
        return JobExecutionResult(summary="unexpected")

    assert manager.bind_dispatch(job_id, runner).code == "dispatch_bound"
    prepared = manager.prepare_quiesced_resume()
    assert prepared.status is QuiescedResumeStatus.PREPARED
    assert (
        manager.set_desired_state(job_id, desired_state).status
        is not JobOutcomeStatus.ERROR
    )
    assert controller.complete_warming().snapshot.state is QuiesceState.RUNNING
    assert manager.dispatch_prepared_quiesced_resume(prepared) == ()
    assert manager.recover_running_quiesced_resume() == ()
    assert not runner_started.is_set()


@pytest.mark.asyncio
async def test_concurrent_recovery_dispatches_claim_one_same_id_attempt() -> None:
    """Two real resume callers schedule one durable attempt, never two."""
    controller = ServiceQuiesceController()
    manager = JobManager(
        max_nonterminal=1,
        state_path=None,
        quiesce_controller=controller,
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        ),
        JobInitiator("test", "recovery-dispatch-coalescing", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    job_id = created.job.id
    first_attempt_started = threading.Event()
    release_first_attempt = threading.Event()
    attempts: list[int] = []

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        attempts.append(context.attempt)
        if context.attempt == 1:
            first_attempt_started.set()
            assert release_first_attempt.wait(timeout=5.0)
            context.control.checkpoint()
        return JobExecutionResult(summary=f"attempt {context.attempt} complete")

    assert manager.bind_dispatch(job_id, runner).code == "dispatch_bound"
    assert (await manager.dispatch_async(job_id)).code == "attempt_started"
    assert await asyncio.to_thread(first_attempt_started.wait, 5.0)
    assert controller.begin_pause().snapshot.state is QuiesceState.PAUSING
    assert manager.request_quiesce_attempts() == (job_id,)
    release_first_attempt.set()
    await _await_state(manager, job_id, JobState.PAUSED)
    assert controller.wait_for_drain(timeout=0).achieved
    assert controller.acknowledge_vram_released().achieved
    assert controller.begin_warming().snapshot.state is QuiesceState.WARMING
    prepared = manager.prepare_quiesced_resume()
    assert prepared.status is QuiescedResumeStatus.PREPARED
    assert controller.complete_warming().snapshot.state is QuiesceState.RUNNING
    manager.adopt_service_loop(asyncio.get_running_loop())

    launch = threading.Barrier(3)
    scheduled: list[tuple[str, ...]] = []

    def dispatch_recovery() -> None:
        launch.wait(timeout=5.0)
        scheduled.append(manager.dispatch_prepared_quiesced_resume(prepared))

    first = threading.Thread(target=dispatch_recovery, name="recovery-dispatch-1")
    second = threading.Thread(target=dispatch_recovery, name="recovery-dispatch-2")
    first.start()
    second.start()
    launch.wait(timeout=5.0)
    await asyncio.to_thread(first.join, 5.0)
    await asyncio.to_thread(second.join, 5.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert sorted(scheduled, key=len) == [(), (job_id,)]
    await _await_state(manager, job_id, JobState.SUCCEEDED)
    assert attempts == [1, 2]


@pytest.mark.asyncio
async def test_loopless_quiesced_recovery_uses_the_adopted_service_loop() -> None:
    """Recovery uses canonical loopless dispatch after releasing manager state."""
    controller = _warming_controller()
    manager, job_id = _create_quiesced_job(controller, None)
    attempts: list[int] = []

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        attempts.append(context.attempt)
        return JobExecutionResult(summary="recovered on service loop")

    assert manager.bind_dispatch(job_id, runner).code == "dispatch_bound"
    prepared = manager.prepare_quiesced_resume()
    assert prepared.status is QuiescedResumeStatus.PREPARED
    queued = manager.get(job_id)
    assert queued is not None
    assert queued.state is JobState.QUEUED
    assert queued.attempt.number == 2
    assert controller.complete_warming().snapshot.state is QuiesceState.RUNNING
    manager.adopt_service_loop(asyncio.get_running_loop())

    assert await asyncio.to_thread(
        manager.dispatch_prepared_quiesced_resume, prepared
    ) == (job_id,)
    await _await_state(manager, job_id, JobState.SUCCEEDED)

    completed = manager.get(job_id)
    assert completed is not None
    assert completed.id == job_id
    assert completed.attempt.number == 2
    assert attempts == [2]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "shutdown",
    [False, True],
    ids=("cancellation", "shutdown"),
)
async def test_blocked_loop_control_invalidates_recovery_claim(
    shutdown: bool,
) -> None:
    """A queued loop callback cannot outlive cancellation or shutdown."""
    controller = ServiceQuiesceController()
    manager = JobManager(
        max_nonterminal=1,
        state_path=None,
        quiesce_controller=controller,
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        ),
        JobInitiator("test", "recovery-claim-control", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    job_id = created.job.id
    first_attempt_started = threading.Event()
    release_first_attempt = threading.Event()
    attempts: list[int] = []

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        attempts.append(context.attempt)
        if context.attempt == 1:
            first_attempt_started.set()
            assert release_first_attempt.wait(timeout=5.0)
            context.control.checkpoint()
        return JobExecutionResult(summary=f"attempt {context.attempt} complete")

    assert manager.bind_dispatch(job_id, runner).code == "dispatch_bound"
    assert (await manager.dispatch_async(job_id)).code == "attempt_started"
    assert await asyncio.to_thread(first_attempt_started.wait, 5.0)
    assert controller.begin_pause().snapshot.state is QuiesceState.PAUSING
    assert manager.request_quiesce_attempts() == (job_id,)
    release_first_attempt.set()
    await _await_state(manager, job_id, JobState.PAUSED)
    assert controller.wait_for_drain(timeout=0).achieved
    assert controller.acknowledge_vram_released().achieved
    assert controller.begin_warming().snapshot.state is QuiesceState.WARMING
    prepared = manager.prepare_quiesced_resume()
    assert prepared.status is QuiescedResumeStatus.PREPARED
    assert controller.complete_warming().snapshot.state is QuiesceState.RUNNING
    manager.adopt_service_loop(asyncio.get_running_loop())

    (
        scheduled,
        claim_observed,
        control,
    ) = await _invalidate_loopless_recovery_before_callback(
        manager,
        job_id,
        prepared,
        shutdown=shutdown,
    )

    assert claim_observed
    assert control == ("shutdown" if shutdown else "job_cancelled")
    assert scheduled == ()

    final = manager.get(job_id)
    assert final is not None
    assert final.state is (JobState.QUEUED if shutdown else JobState.CANCELLED)
    assert attempts == [1]
    assert manager.recover_running_quiesced_resume() == ()


def test_no_loop_recovery_claim_is_released_for_a_later_owner_loop() -> None:
    """A missing owner loop drops its claim so later recovery can dispatch."""
    controller = _warming_controller()
    manager, job_id = _create_quiesced_job(controller, None)
    attempts: list[int] = []

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        attempts.append(context.attempt)
        return JobExecutionResult(summary="recovered after loop ownership")

    assert manager.bind_dispatch(job_id, runner).code == "dispatch_bound"
    prepared = manager.prepare_quiesced_resume()
    assert prepared.status is QuiescedResumeStatus.PREPARED
    assert controller.complete_warming().snapshot.state is QuiesceState.RUNNING
    assert manager.dispatch_prepared_quiesced_resume(prepared) == ()

    async def recover_on_owner_loop() -> None:
        assert manager.recover_running_quiesced_resume() == (job_id,)
        await _await_state(manager, job_id, JobState.SUCCEEDED)

    asyncio.run(recover_on_owner_loop())
    assert attempts == [2]


def test_stopped_owner_loop_recovery_claim_moves_to_later_owner_loop() -> None:
    """A durable retry can bind its callback to a new live owner loop."""
    controller = ServiceQuiesceController()
    manager = JobManager(
        max_nonterminal=1,
        state_path=None,
        quiesce_controller=controller,
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        ),
        JobInitiator("test", "stopped-owner-loop-recovery", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    job_id = created.job.id
    first_attempt_started = threading.Event()
    release_first_attempt = threading.Event()
    attempts: list[int] = []

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        attempts.append(context.attempt)
        if context.attempt == 1:
            first_attempt_started.set()
            assert release_first_attempt.wait(timeout=5.0)
            context.control.checkpoint()
        return JobExecutionResult(summary=f"attempt {context.attempt} complete")

    assert manager.bind_dispatch(job_id, runner).code == "dispatch_bound"

    async def prepare_on_original_owner_loop() -> QuiescedResumeResult:
        assert (await manager.dispatch_async(job_id)).code == "attempt_started"
        assert await asyncio.to_thread(first_attempt_started.wait, 5.0)
        assert controller.begin_pause().snapshot.state is QuiesceState.PAUSING
        assert manager.request_quiesce_attempts() == (job_id,)
        release_first_attempt.set()
        await _await_state(manager, job_id, JobState.PAUSED)
        assert controller.wait_for_drain(timeout=0).achieved
        assert controller.acknowledge_vram_released().achieved
        assert controller.begin_warming().snapshot.state is QuiesceState.WARMING
        prepared = manager.prepare_quiesced_resume()
        assert prepared.status is QuiescedResumeStatus.PREPARED
        assert controller.complete_warming().snapshot.state is QuiesceState.RUNNING
        return prepared

    prepared = asyncio.run(prepare_on_original_owner_loop())
    assert manager.dispatch_prepared_quiesced_resume(prepared) == ()

    async def recover_on_later_owner_loop() -> None:
        assert manager.recover_running_quiesced_resume() == (job_id,)
        await _await_state(manager, job_id, JobState.SUCCEEDED)

    asyncio.run(recover_on_later_owner_loop())
    assert attempts == [1, 2]
