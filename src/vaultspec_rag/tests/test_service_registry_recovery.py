"""CPU-only evidence for registry-owned durable quiesce recovery."""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from ..job_manager.manager import JobManager
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ..job_persistence import load_persisted_state
from ..service import ServiceRegistry
from ..service_quiesce import QuiesceState, QuiesceTransition, QuiesceTransitionCode
from ._job_roots import _TEST_PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..job_manager.models import JobAttemptContext, JobExecutionResult
    from ..job_models import JobSnapshot

pytestmark = [pytest.mark.unit]

_WAIT_SECONDS = 5.0


def _registry_with_quiesced_job(
    state_path: Path,
) -> tuple[ServiceRegistry, JobManager, str]:
    registry = ServiceRegistry()
    manager = JobManager(
        max_nonterminal=1,
        state_path=state_path,
        quiesce_controller=registry._quiesce_controller,
    )
    registry._job_manager = manager
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        ),
        JobInitiator("test", "registry-durable-recovery", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    job_id = created.job.id
    assert (
        manager.defer_unstarted_for_quiesce(job_id).code
        == "quiesce_deferred_before_start"
    )
    assert registry.quiesce_resources(timeout_seconds=0).achieved
    return registry, manager, job_id


@contextmanager
def _running_service_loop() -> Generator[asyncio.AbstractEventLoop]:
    """Run one real event loop on its own thread for loopless recovery dispatch."""
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run_loop() -> None:
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()
        loop.close()

    owner = threading.Thread(target=run_loop, name="registry-recovery-loop")
    owner.start()
    if not ready.wait(timeout=_WAIT_SECONDS):
        raise AssertionError("the real service loop did not start")
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        owner.join(timeout=_WAIT_SECONDS)
        assert not owner.is_alive(), "the real service loop did not stop"


@contextmanager
def _hold_service_loop(loop: asyncio.AbstractEventLoop) -> Generator[threading.Event]:
    """Hold the next real loop callback until a test observes durable recovery."""
    entered = threading.Event()
    release = threading.Event()

    def hold_callback() -> None:
        entered.set()
        release.wait(timeout=_WAIT_SECONDS)

    loop.call_soon_threadsafe(hold_callback)
    if not entered.wait(timeout=_WAIT_SECONDS):
        raise AssertionError("the service loop did not enter the recovery hold")
    try:
        yield release
    finally:
        release.set()


def _persisted_job(state_path: Path, job_id: str) -> JobSnapshot | None:
    """Return the exact durable job record, if the current generation has one."""
    persisted = load_persisted_state(state_path)
    return next((job for job in persisted.jobs if job.id == job_id), None)


def _wait_for_durable_queued_recovery(
    state_path: Path,
    job_id: str,
    *,
    runner_started: threading.Event,
    registry: ServiceRegistry,
) -> JobSnapshot:
    """Observe the real queued recovery record before allowing its runner to start."""
    deadline = time.monotonic() + _WAIT_SECONDS
    latest = "no durable job record"
    while time.monotonic() < deadline:
        try:
            durable = _persisted_job(state_path, job_id)
        except (OSError, ValueError) as exc:
            latest = f"durable read failed: {exc}"
        else:
            if durable is None:
                latest = "job id absent from durable state"
            else:
                latest = (
                    f"state={durable.state.value}, "
                    f"desired={durable.desired_state.value}, "
                    f"attempt={durable.attempt.number}"
                )
                if (
                    durable.state is JobState.QUEUED
                    and durable.desired_state is DesiredJobState.RUNNING
                    and durable.attempt.number == 2
                ):
                    assert not runner_started.is_set(), (
                        "the bound runner started before the queued recovery "
                        "was observed"
                    )
                    return durable
        time.sleep(0.01)
    snapshot = registry.quiesce_snapshot()
    raise AssertionError(
        "did not observe the durable queued recovery before runner execution; "
        f"latest={latest}; controller={snapshot.state.value}; "
        f"epoch={snapshot.admission_epoch}; runner_started={runner_started.is_set()}"
    )


def _wait_for_state(manager: JobManager, job_id: str, state: JobState) -> JobSnapshot:
    """Wait for one real runner to publish its terminal state with diagnostics."""
    deadline = time.monotonic() + _WAIT_SECONDS
    latest = "job not found"
    while time.monotonic() < deadline:
        snapshot = manager.get(job_id)
        if snapshot is not None:
            latest = (
                f"state={snapshot.state.value}, "
                f"desired={snapshot.desired_state.value}, "
                f"attempt={snapshot.attempt.number}"
            )
            if snapshot.state is state:
                return snapshot
        time.sleep(0.01)
    raise AssertionError(
        f"job {job_id} did not reach {state.value} after recovery; latest={latest}"
    )


def _wait_for_reopened_admission(
    registry: ServiceRegistry,
    *,
    expected_epoch: int,
) -> None:
    """Wait for the controller to reopen admission at exactly *expected_epoch*.

    Reopening is what the durable record happens BEFORE, so it cannot be read
    as though the two were simultaneous. Publishing a generation makes it
    visible to a reader at the rename and only then forces the rename itself to
    disk, and that trailing sync is a real device round trip on the platforms
    that need it. A reader polling the state file can therefore hold the new
    record in its hands while the writer is still inside the publication that
    precedes reopening, and an instantaneous read of the controller fails for
    that reason alone - more often the stronger the durability guarantee gets.

    Waiting concedes nothing the ordering rests on. The state and the epoch are
    still exact, a controller that never reopens still fails, and the direction
    of the ordering is carried by the assertion that no runner had started when
    the durable record was first observed.
    """
    deadline = time.monotonic() + _WAIT_SECONDS
    while True:
        snapshot = registry.quiesce_snapshot()
        if snapshot.state is QuiesceState.RUNNING:
            assert snapshot.admission_epoch == expected_epoch
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                "the controller did not reopen admission after durable "
                f"recovery; controller={snapshot.state.value}; "
                f"epoch={snapshot.admission_epoch}; expected={expected_epoch}"
            )
        time.sleep(0.01)


def _assert_running_after_durable_preparation(
    state_path: Path,
    job_id: str,
    *,
    expected_epoch: int,
    runner_started: threading.Event,
    registry: ServiceRegistry,
) -> JobSnapshot:
    """Prove the reopened controller follows, rather than precedes, durability."""
    durable = _wait_for_durable_queued_recovery(
        state_path,
        job_id,
        runner_started=runner_started,
        registry=registry,
    )
    _wait_for_reopened_admission(registry, expected_epoch=expected_epoch)
    assert durable.id == job_id
    return durable


def _bind_recording_recovery_runner(
    manager: JobManager,
    job_id: str,
    state_path: Path,
    started: threading.Event,
) -> tuple[list[int], list[tuple[JobState, DesiredJobState]]]:
    """Bind a real runner that records the durable state visible at execution."""
    attempts: list[int] = []
    durable_states: list[tuple[JobState, DesiredJobState]] = []

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        durable = _persisted_job(state_path, context.job_id)
        if durable is None:
            raise AssertionError("runner started without its durable recovery record")
        attempts.append(context.attempt)
        durable_states.append((durable.state, durable.desired_state))
        started.set()
        from ..job_manager.models import JobExecutionResult as _Result

        return _Result(summary="real registry recovery runner completed")

    assert manager.bind_dispatch(job_id, runner).code == "dispatch_bound"
    return attempts, durable_states


def _unpublished_recovery_failure(
    registry: ServiceRegistry,
    state_path: Path,
) -> QuiesceTransition:
    """Break the real state directory, then make the registry expose the failure."""
    state_path.unlink()
    state_path.parent.rmdir()
    state_path.parent.write_text("not a directory", encoding="utf-8")
    return registry.resume_resources(timeout_seconds=0)


def _concurrent_resume_workers(
    registry: ServiceRegistry,
) -> tuple[
    threading.Barrier,
    list[QuiesceTransition],
    list[BaseException],
    tuple[threading.Thread, threading.Thread],
]:
    """Build two real resume callers sharing one lifecycle authority."""
    launch = threading.Barrier(3)
    outcomes: list[QuiesceTransition] = []
    errors: list[BaseException] = []

    def resume() -> None:
        try:
            launch.wait(timeout=_WAIT_SECONDS)
            outcomes.append(registry.resume_resources(timeout_seconds=_WAIT_SECONDS))
        except BaseException as exc:
            errors.append(exc)

    return (
        launch,
        outcomes,
        errors,
        (
            threading.Thread(target=resume, name="registry-recovery-1"),
            threading.Thread(target=resume, name="registry-recovery-2"),
        ),
    )


def test_registry_persists_same_id_recovery_before_reopening_admission(
    tmp_path: Path,
) -> None:
    """A bound runner cannot start until resume persists its same-ID attempt.

    Restoring recovery's legacy ``_schedule_dispatch`` handoff makes the
    blocked-loop assertion fail: resume returns before the adopted loop admits
    the dispatch, so no runner can execute through the registry lifecycle.
    """
    state_path = tmp_path / "managed" / "jobs.json"
    registry, manager, job_id = _registry_with_quiesced_job(state_path)
    runner_started = threading.Event()
    attempts, durable_states = _bind_recording_recovery_runner(
        manager,
        job_id,
        state_path,
        runner_started,
    )
    outcomes: list[QuiesceTransition] = []
    errors: list[BaseException] = []

    def resume() -> None:
        try:
            outcomes.append(registry.resume_resources(timeout_seconds=_WAIT_SECONDS))
        except BaseException as exc:
            errors.append(exc)

    with _running_service_loop() as service_loop:
        manager.adopt_service_loop(service_loop)
        worker = threading.Thread(target=resume, name="registry-recovery-resume")
        try:
            with _hold_service_loop(service_loop) as release_loop:
                worker.start()
                _assert_running_after_durable_preparation(
                    state_path,
                    job_id,
                    expected_epoch=2,
                    runner_started=runner_started,
                    registry=registry,
                )
                assert worker.is_alive(), (
                    "resume returned before its blocked loop dispatch was admitted"
                )
                release_loop.set()
        finally:
            worker.join(timeout=_WAIT_SECONDS)

        assert not worker.is_alive(), "resume did not finish after loop admission"
        assert runner_started.wait(timeout=_WAIT_SECONDS), (
            "the bound recovery runner never executed"
        )
        completed = _wait_for_state(manager, job_id, JobState.SUCCEEDED)

    assert errors == []
    assert len(outcomes) == 1
    assert outcomes[0].code is QuiesceTransitionCode.RUNNING
    assert outcomes[0].snapshot.state is QuiesceState.RUNNING
    assert attempts == [2]
    assert durable_states == [(JobState.RUNNING, DesiredJobState.RUNNING)]
    assert completed.attempt.number == 2


def test_registry_reports_unpublished_recovery_without_reopening_admission(
    tmp_path: Path,
) -> None:
    """A real state-path failure is explicit and leaves warming closed."""
    state_path = tmp_path / "managed" / "jobs.json"
    registry, manager, job_id = _registry_with_quiesced_job(state_path)
    state_path.unlink()
    state_path.parent.rmdir()
    state_path.parent.write_text("not a directory", encoding="utf-8")

    failed = registry.resume_resources(timeout_seconds=0)

    assert failed.code is QuiesceTransitionCode.RESUME_RECOVERY_FAILED
    assert not failed.achieved
    assert failed.snapshot.state is QuiesceState.WARMING
    assert not failed.snapshot.admissions_open
    assert not failed.snapshot.vram_released
    assert not failed.snapshot.safe_to_borrow_gpu
    assert failed.snapshot.failure_reason == "job_resume_persistence_unpublished"
    retained = manager.get(job_id)
    assert retained is not None
    assert retained.state is JobState.PAUSED
    assert retained.desired_state is DesiredJobState.RUNNING


def _assert_recovery_failed_before_running(
    failed: QuiesceTransition,
    runner_started: threading.Event,
) -> None:
    """Assert the unpublished recovery stopped short of running the attempt."""
    assert failed.code is QuiesceTransitionCode.RESUME_RECOVERY_FAILED
    assert not failed.achieved
    assert failed.snapshot.state is QuiesceState.WARMING
    assert failed.snapshot.admission_epoch == 1
    assert not runner_started.is_set()


def _assert_both_workers_shared_one_outcome(
    first: threading.Thread,
    second: threading.Thread,
    errors: list[BaseException],
    outcomes: list[QuiesceTransition],
    *,
    expected_epoch: int,
) -> None:
    """Assert two racing resumes returned the very same transition object.

    Identity, not equality: two equal-but-distinct results would mean each
    worker drove its own transition, which is the coalescing this guards.
    """
    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert len(outcomes) == 2
    assert outcomes[0] is outcomes[1]
    assert outcomes[0].code is QuiesceTransitionCode.RUNNING
    assert outcomes[0].snapshot.admission_epoch == expected_epoch


def test_repaired_concurrent_resume_shares_one_transition_claim_and_attempt(
    tmp_path: Path,
) -> None:
    """Repaired durable recovery coalesces one epoch and one bound attempt."""
    state_path = tmp_path / "managed" / "jobs.json"
    registry, manager, job_id = _registry_with_quiesced_job(state_path)
    runner_started = threading.Event()
    attempts, durable_states = _bind_recording_recovery_runner(
        manager,
        job_id,
        state_path,
        runner_started,
    )

    failed = _unpublished_recovery_failure(registry, state_path)
    _assert_recovery_failed_before_running(failed, runner_started)

    state_path.parent.unlink()
    state_path.parent.mkdir()
    launch, outcomes, errors, workers = _concurrent_resume_workers(registry)
    first, second = workers
    assert registry.gpu_lock.acquire(timeout=_WAIT_SECONDS)
    initial_claim_generation = manager._next_quiesced_dispatch_generation

    with _running_service_loop() as service_loop:
        manager.adopt_service_loop(service_loop)
        try:
            with _hold_service_loop(service_loop) as release_loop:
                first.start()
                second.start()
                launch.wait(timeout=_WAIT_SECONDS)
                deadline = time.monotonic() + _WAIT_SECONDS
                while registry._resource_transition is None:
                    assert time.monotonic() < deadline, (
                        "concurrent repaired retry did not claim a lifecycle transition"
                    )
                    time.sleep(0.01)
                registry.gpu_lock.release()
                _assert_running_after_durable_preparation(
                    state_path,
                    job_id,
                    expected_epoch=failed.snapshot.admission_epoch + 1,
                    runner_started=runner_started,
                    registry=registry,
                )
                release_loop.set()
        finally:
            if registry.gpu_lock.locked():
                registry.gpu_lock.release()
            for worker in (first, second):
                worker.join(timeout=_WAIT_SECONDS)

        assert runner_started.wait(timeout=_WAIT_SECONDS), (
            "the repaired recovery did not execute its bound runner"
        )
        completed = _wait_for_state(manager, job_id, JobState.SUCCEEDED)

    _assert_both_workers_shared_one_outcome(
        first,
        second,
        errors,
        outcomes,
        expected_epoch=failed.snapshot.admission_epoch + 1,
    )
    assert manager._next_quiesced_dispatch_generation == initial_claim_generation + 1
    assert manager._pending_quiesced_dispatches == {}
    assert attempts == [2]
    assert durable_states == [(JobState.RUNNING, DesiredJobState.RUNNING)]
    assert completed.attempt.number == 2
