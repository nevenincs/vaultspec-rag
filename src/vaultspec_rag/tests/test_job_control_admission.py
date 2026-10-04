"""Control reaches real AnyIO capacity waiters without abandoning workers."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from ..concurrency import get_encode_limiter
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
from ..service_quiesce import QuiesceState, ServiceQuiesceController
from ._job_roots import _TEST_PROJECT_ROOT
from ._state_fixtures import reset_limiters

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _fresh_limiters() -> Iterator[None]:
    reset_limiters()
    yield
    assert get_encode_limiter().borrowed_tokens == 0
    reset_limiters()


async def _until(predicate: Callable[[], bool]) -> None:
    deadline = asyncio.get_running_loop().time() + 3
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("control did not complete before capacity release")
        await asyncio.sleep(0.01)


def _has_state(manager: JobManager, job_id: str, state: JobState) -> bool:
    snapshot = manager.get(job_id)
    assert snapshot is not None
    return snapshot.state is state


@dataclass
class _AdmissionPair:
    manager: JobManager
    controller: ServiceQuiesceController
    holder_id: str
    waiter_id: str
    release: threading.Event
    waiter_entries: list[int]
    holder_entries: list[int]

    async def close(self) -> None:
        requested = self.manager.begin_shutdown()
        self.release.set()
        assert (
            await self.manager.wait_for_shutdown(requested, timeout_seconds=5)
        ).clean


async def _admitted_pair() -> _AdmissionPair:
    controller = ServiceQuiesceController()
    manager = JobManager(
        max_nonterminal=2, state_path=None, quiesce_controller=controller
    )
    ids: list[str] = []
    for source in (JobSource.CODE, JobSource.VAULT):
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                source,
                _TEST_PROJECT_ROOT,
                JobMode.REBUILD,
                RunAuthority.REBUILD,
            ),
            JobInitiator("test", "admission-control", _TEST_PROJECT_ROOT),
        )
        assert created.job is not None
        ids.append(created.job.id)
    release, started = threading.Event(), threading.Event()
    entries: list[int] = []
    holder_entries: list[int] = []

    def holder(context: JobAttemptContext) -> JobExecutionResult:
        holder_entries.append(context.attempt)
        with context.control.protected():
            started.set()
            assert release.wait(timeout=10)
        return JobExecutionResult(summary="holder completed")

    def waiter(context: JobAttemptContext) -> JobExecutionResult:
        entries.append(context.attempt)
        context.control.checkpoint()
        return JobExecutionResult(summary="waiter completed")

    assert manager.bind_dispatch(ids[0], holder).code == "dispatch_bound"
    assert manager.bind_dispatch(ids[1], waiter).code == "dispatch_bound"
    assert (await manager.dispatch_async(ids[0])).code == "attempt_started"
    assert await asyncio.to_thread(started.wait, 5)
    assert (await manager.dispatch_async(ids[1])).code == "attempt_started"
    await _until(lambda: get_encode_limiter().statistics().tasks_waiting == 1)
    return _AdmissionPair(
        manager, controller, ids[0], ids[1], release, entries, holder_entries
    )


@pytest.mark.parametrize("control", ["pause", "cancel", "quiesce", "shutdown"])
async def test_control_unwinds_capacity_waiter_before_worker_starts(
    control: str,
) -> None:
    pair = await _admitted_pair()
    try:
        initial = pair.manager.get(pair.waiter_id)
        assert initial is not None
        assert not initial.runtime.worker_active
        assert not initial.resources.index_capacity_held
        assert pair.controller.snapshot().active_compute_tickets == 2
        if control == "quiesce":
            assert pair.controller.begin_pause().snapshot.state is QuiesceState.PAUSING
            assert set(pair.manager.request_quiesce_attempts()) == {
                pair.holder_id,
                pair.waiter_id,
            }
        elif control == "shutdown":
            pair.manager.begin_shutdown()
        else:
            desired = (
                DesiredJobState.PAUSED
                if control == "pause"
                else DesiredJobState.CANCELLED
            )
            pair.manager.set_desired_state(pair.waiter_id, desired)
        expected = {
            "pause": JobState.PAUSED,
            "cancel": JobState.CANCELLED,
            "quiesce": JobState.PAUSED,
            "shutdown": JobState.INTERRUPTED,
        }[control]
        await _until(lambda: _has_state(pair.manager, pair.waiter_id, expected))
        final = pair.manager.get(pair.waiter_id)
        assert final is not None
        assert not final.runtime.task_active and not final.runtime.worker_active
        assert not final.resources.index_capacity_held
        assert pair.waiter_entries == [], "controlled waiter started a worker"
        assert get_encode_limiter().statistics().tasks_waiting == 0
        assert get_encode_limiter().borrowed_tokens == 1
        assert pair.controller.snapshot().active_compute_tickets == 1
    finally:
        await pair.close()


async def test_resume_withdraws_waiter_pause_before_delivery() -> None:
    pair = await _admitted_pair()
    try:
        assert (
            pair.manager.set_desired_state(pair.waiter_id, DesiredJobState.PAUSED).code
            == "pause_requested"
        )
        assert (
            pair.manager.set_desired_state(pair.waiter_id, DesiredJobState.RUNNING).code
            == "pause_withdrawn"
        )
        await asyncio.sleep(0.3)
        held = pair.manager.get(pair.waiter_id)
        assert held is not None
        assert held.state is JobState.RUNNING and held.attempt.number == 1
        assert pair.waiter_entries == []
        pair.release.set()
        await _until(
            lambda: _has_state(pair.manager, pair.waiter_id, JobState.SUCCEEDED)
        )
        assert pair.waiter_entries == [1]
    finally:
        await pair.close()


async def test_admitted_protected_worker_outlives_poll_deadlines_exactly_once() -> None:
    pair = await _admitted_pair()
    try:
        pair.manager.set_desired_state(pair.holder_id, DesiredJobState.PAUSED)
        await asyncio.sleep(0.35)
        held = pair.manager.get(pair.holder_id)
        assert held is not None
        assert held.state is JobState.PAUSING
        assert held.runtime.task_active and held.runtime.worker_active
        assert held.resources.index_capacity_held
        assert pair.controller.snapshot().active_compute_tickets == 2
        assert get_encode_limiter().borrowed_tokens == 1
        pair.release.set()
        await _until(lambda: _has_state(pair.manager, pair.holder_id, JobState.PAUSED))
        await _until(
            lambda: _has_state(pair.manager, pair.waiter_id, JobState.SUCCEEDED)
        )
        assert pair.waiter_entries == [1], "a shielded result caused a duplicate worker"
        assert pair.controller.snapshot().active_compute_tickets == 0
    finally:
        await pair.close()


async def test_successful_shielded_result_is_never_reexecuted() -> None:
    pair = await _admitted_pair()
    try:
        await asyncio.sleep(0.35)
        pair.release.set()
        await _until(
            lambda: _has_state(pair.manager, pair.holder_id, JobState.SUCCEEDED)
        )
        await _until(
            lambda: _has_state(pair.manager, pair.waiter_id, JobState.SUCCEEDED)
        )
        assert pair.holder_entries == [1], "a shielded result executed twice"
        assert pair.waiter_entries == [1]
        assert pair.controller.snapshot().active_compute_tickets == 0
    finally:
        await pair.close()
