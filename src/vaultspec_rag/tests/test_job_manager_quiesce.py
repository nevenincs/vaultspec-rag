"""Real CPU/thread coverage for controller-bound managed-job quiesce."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from ..job_manager.manager import JobManager
from ..job_manager.models import JobAttemptContext, JobExecutionResult
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ..service_quiesce import QuiesceState, ServiceQuiesceController
from ._job_roots import _TEST_PROJECT_ROOT

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

    quiesced = manager.get(job_id)
    assert quiesced is not None
    assert quiesced.id == job_id
    assert quiesced.desired_state is DesiredJobState.RUNNING
    assert not quiesced.resources.holds_anything
    assert controller.snapshot().active_compute_tickets == 0
    assert manager.resume_quiesced_attempts() == ()

    assert controller.wait_for_drain(timeout=0).achieved
    assert controller.acknowledge_vram_released().achieved
    assert controller.begin_warming().snapshot.state is QuiesceState.WARMING
    assert controller.complete_warming().snapshot.state is QuiesceState.RUNNING
    assert manager.resume_quiesced_attempts() == (job_id,)
    await _await_state(manager, job_id, JobState.SUCCEEDED)

    completed = manager.get(job_id)
    assert completed is not None
    assert completed.id == job_id
    assert completed.attempt.number == 2
