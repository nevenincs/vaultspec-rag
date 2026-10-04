"""Durable same-ID recovery across failed drains and idempotent resumes."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING

import pytest

from .. import _atomic_write
from ..indexer._run_ledger_models import RunAuthority
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
from ..job_persistence import load_persisted_state
from ..service import ServiceRegistry
from ..service_quiesce import (
    QuiesceAdmissionClosedError,
    QuiesceState,
    QuiesceTransitionCode,
)
from ._job_roots import _TEST_PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

    from ..job_models import JobSnapshot
    from ..service_quiesce import QuiesceTransition

pytestmark = [pytest.mark.unit]


def _registry_jobs(state_path: Path) -> tuple[ServiceRegistry, JobManager]:
    registry = ServiceRegistry()
    manager = JobManager(
        max_nonterminal=4,
        state_path=state_path,
        quiesce_controller=registry._quiesce_controller,
    )
    registry._job_manager = manager
    return registry, manager


def _create(manager: JobManager, name: str) -> str:
    root = _TEST_PROJECT_ROOT + "/" + name
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            root,
            JobMode.REBUILD,
            RunAuthority.REBUILD,
        ),
        JobInitiator("test", "quiesce-recovery", root),
    )
    assert created.job is not None
    return created.job.id


async def _wait_state(manager: JobManager, job_id: str, state: JobState) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while True:
        snapshot = manager.get(job_id)
        assert snapshot is not None
        if snapshot.state is state:
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"held same-ID job did not reach {state.value}")
        await asyncio.sleep(0.01)


def _block_parent(state_path: Path) -> None:
    state_path.unlink()
    state_path.parent.rmdir()
    state_path.parent.write_text("not a directory", encoding="utf-8")


def _repair_parent(state_path: Path) -> None:
    state_path.parent.unlink()
    state_path.parent.mkdir()


def _snapshot(manager: JobManager, job_id: str) -> JobSnapshot:
    snapshot = manager.get(job_id)
    assert snapshot is not None
    return snapshot


def _inject_persistence_fault(
    state_path: Path, monkeypatch: pytest.MonkeyPatch, *, published: bool
) -> None:
    if not published:
        _block_parent(state_path)
        return

    def fail_after_replace(source: Path | str, destination: Path | str) -> None:
        _atomic_write.replace_atomically(source, destination)
        raise _atomic_write.NotDurableError("forced post-publication sync fault")

    monkeypatch.setattr(_atomic_write, "replace_durably", fail_after_replace)


async def test_abort_prepares_paused_work_before_opening_and_dispatches_same_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "jobs.json"
    registry, manager = _registry_jobs(state_path)
    job_id = _create(manager, "held")
    assert manager.defer_unstarted_for_quiesce(job_id).status.value == "ok"
    attempts: list[int] = []

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        attempts.append(context.attempt)
        return JobExecutionResult(summary="recovered")

    manager.bind_dispatch(job_id, runner)
    held_ticket = registry.acquire_compute_ticket()
    original = registry._quiesce_controller.abort_pause

    def inspect_before_open() -> QuiesceTransition:
        assert not registry.quiesce_snapshot().admissions_open
        persisted = load_persisted_state(state_path)
        assert persisted.jobs[0].state is JobState.QUEUED, (
            "opened before durable recovery"
        )
        assert persisted.jobs[0].attempt.number == 2
        return original()

    monkeypatch.setattr(
        registry._quiesce_controller, "abort_pause", inspect_before_open
    )
    try:
        assert registry.quiesce_resources(timeout_seconds=0).code is (
            QuiesceTransitionCode.DRAIN_TIMED_OUT
        )
        resumed = registry.resume_resources(timeout_seconds=0)
        assert resumed.achieved and resumed.code is QuiesceTransitionCode.PAUSE_ABORTED
        await _wait_state(manager, job_id, JobState.SUCCEEDED)
        assert attempts == [2], "paused running work was stranded by abort"
        assert _snapshot(manager, job_id).id == job_id
    finally:
        held_ticket.release()


@pytest.mark.parametrize("state", [QuiesceState.PAUSING, QuiesceState.RUNNING])
@pytest.mark.parametrize("published", [False, True], ids=["unpublished", "published"])
async def test_recovery_persistence_failure_closes_without_disturbing_live_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: QuiesceState,
    published: bool,
) -> None:
    state_path = tmp_path / "state" / "jobs.json"
    registry, manager = _registry_jobs(state_path)
    live_id, held_id = _create(manager, "live"), _create(manager, "held")
    manager.defer_unstarted_for_quiesce(held_id)
    started, release = threading.Event(), threading.Event()

    def live(context: JobAttemptContext) -> JobExecutionResult:
        with context.control.protected():
            started.set()
            assert release.wait(timeout=10)
        return JobExecutionResult(summary="live completed")

    manager.bind_dispatch(live_id, live)
    assert (await manager.dispatch_async(live_id)).code == "attempt_started"
    assert await asyncio.to_thread(started.wait, 5)
    if state is QuiesceState.PAUSING:
        registry._quiesce_controller.begin_pause()
    before = manager.get(live_id)
    epoch = registry.quiesce_snapshot().admission_epoch
    _inject_persistence_fault(state_path, monkeypatch, published=published)
    try:
        failed = registry.resume_resources(timeout_seconds=0)
        assert failed.code is QuiesceTransitionCode.RESUME_RECOVERY_FAILED
        assert not failed.achieved, "recovery persistence fault reported success"
        assert failed.snapshot.state is QuiesceState.PAUSING
        assert not failed.snapshot.admissions_open
        assert not failed.snapshot.safe_to_borrow_gpu
        assert failed.snapshot.admission_epoch == epoch
        assert failed.snapshot.active_compute_tickets == 1
        assert manager.get(live_id) == before, "recovery fault disturbed admitted work"
        held = manager.get(held_id)
        assert held is not None
        assert held.state is (JobState.QUEUED if published else JobState.PAUSED)
        assert held.desired_state is DesiredJobState.RUNNING
        assert held.attempt.number == (2 if published else 1)
        if published:
            assert any(
                job.id == held_id and job.state is JobState.QUEUED
                for job in load_persisted_state(state_path).jobs
            )
        with pytest.raises(QuiesceAdmissionClosedError):
            registry.acquire_compute_ticket()
    finally:
        monkeypatch.undo()
        if not published:
            _repair_parent(state_path)
        release.set()
        await _wait_state(manager, live_id, JobState.SUCCEEDED)
    retried = registry.resume_resources(timeout_seconds=0)
    assert retried.achieved
    assert retried.snapshot.admission_epoch == epoch
    assert _snapshot(manager, held_id).attempt.number == 2


@pytest.mark.parametrize(
    "before_open", [True, False], ids=["before-open", "after-open"]
)
async def test_acknowledgement_between_prepare_and_abort_is_recovered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, before_open: bool
) -> None:
    registry, manager = _registry_jobs(tmp_path / "jobs.json")
    manager.adopt_service_loop(asyncio.get_running_loop())
    job_id = _create(manager, "late-unwind")
    started, release = threading.Event(), threading.Event()
    attempts: list[int] = []

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        attempts.append(context.attempt)
        if context.attempt == 1:
            with context.control.protected():
                started.set()
                assert release.wait(timeout=10)
        return JobExecutionResult(summary="completed")

    manager.bind_dispatch(job_id, runner)
    assert (await manager.dispatch_async(job_id)).code == "attempt_started"
    assert await asyncio.to_thread(started.wait, 5)
    assert registry.quiesce_resources(timeout_seconds=0).code is (
        QuiesceTransitionCode.DRAIN_TIMED_OUT
    )
    original = registry._quiesce_controller.abort_pause

    def acknowledge_before_open() -> QuiesceTransition:
        if before_open:
            release.set()
            deadline = time.monotonic() + 5
            while _snapshot(manager, job_id).state is not JobState.PAUSED:
                assert time.monotonic() < deadline, "attempt did not acknowledge pause"
                time.sleep(0.01)
        assert not registry.quiesce_snapshot().admissions_open
        return original()

    monkeypatch.setattr(
        registry._quiesce_controller, "abort_pause", acknowledge_before_open
    )
    try:
        resumed = await asyncio.to_thread(registry.resume_resources, timeout_seconds=0)
        assert resumed.achieved
        release.set()
        await _wait_state(manager, job_id, JobState.SUCCEEDED)
        assert attempts == [1, 2], "prepare/open gap stranded late acknowledgement"
    finally:
        release.set()
        requested = manager.begin_shutdown()
        assert (await manager.wait_for_shutdown(requested, timeout_seconds=5)).clean


@pytest.mark.parametrize("desired", [DesiredJobState.PAUSED, DesiredJobState.CANCELLED])
async def test_abort_preserves_operator_intent(
    tmp_path: Path, desired: DesiredJobState
) -> None:
    registry, manager = _registry_jobs(tmp_path / "jobs.json")
    job_id = _create(manager, "operator-held")
    manager.set_desired_state(job_id, desired)
    held_ticket = registry.acquire_compute_ticket()
    try:
        registry.quiesce_resources(timeout_seconds=0)
        assert registry.resume_resources(timeout_seconds=0).achieved
        snapshot = manager.get(job_id)
        assert snapshot is not None
        assert snapshot.desired_state is desired, "abort overrode operator intent"
        assert snapshot.state is (
            JobState.PAUSED if desired is DesiredJobState.PAUSED else JobState.CANCELLED
        )
        assert snapshot.attempt.number == 1
        assert not snapshot.runtime.task_active
    finally:
        held_ticket.release()


def test_recovery_failure_rejects_stale_running_report() -> None:
    registry = ServiceRegistry()
    outcome = registry._quiesce_controller.fail_transition(
        code=QuiesceTransitionCode.RESUME_RECOVERY_FAILED,
        reason="stale recovery failure",
        recovery_state=QuiesceState.PAUSING,
    )
    assert outcome.code is QuiesceTransitionCode.QUIESCE_UNAVAILABLE
    assert not outcome.achieved
    assert outcome.snapshot.state is QuiesceState.RUNNING
    assert outcome.snapshot.failure_reason is None


async def test_running_resume_recovers_paused_work_once(tmp_path: Path) -> None:
    registry, manager = _registry_jobs(tmp_path / "jobs.json")
    job_id = _create(manager, "already-running-held")
    manager.defer_unstarted_for_quiesce(job_id)
    attempts: list[int] = []

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        attempts.append(context.attempt)
        return JobExecutionResult(summary="recovered")

    manager.bind_dispatch(job_id, runner)
    assert registry.resume_resources(timeout_seconds=0).achieved
    assert registry.resume_resources(timeout_seconds=0).achieved
    await _wait_state(manager, job_id, JobState.SUCCEEDED)
    assert attempts == [2], "idempotent running resume stranded or duplicated work"


async def test_after_open_recovery_fault_closes_admission_and_retries_same_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "state" / "jobs.json"
    registry, manager = _registry_jobs(state_path)
    job_id = _create(manager, "late-held")
    original = registry._quiesce_controller.abort_pause
    held_ticket = registry.acquire_compute_ticket()
    registry.quiesce_resources(timeout_seconds=0)

    def defer_then_open_and_fault() -> QuiesceTransition:
        manager.defer_unstarted_for_quiesce(job_id)
        completed = original()
        _block_parent(state_path)
        return completed

    monkeypatch.setattr(
        registry._quiesce_controller, "abort_pause", defer_then_open_and_fault
    )
    try:
        failed = registry.resume_resources(timeout_seconds=0)
        assert failed.code is QuiesceTransitionCode.RESUME_RECOVERY_FAILED
        assert not failed.achieved, "follow-up recovery failure reported success"
        assert failed.snapshot.state is QuiesceState.PAUSING
        assert not failed.snapshot.admissions_open
        assert not failed.snapshot.safe_to_borrow_gpu
        assert failed.snapshot.active_compute_tickets == 1
        assert _snapshot(manager, job_id).state is JobState.PAUSED
        _repair_parent(state_path)
        monkeypatch.undo()
        assert registry.resume_resources(timeout_seconds=0).achieved
        assert _snapshot(manager, job_id).attempt.number == 2
    finally:
        held_ticket.release()
