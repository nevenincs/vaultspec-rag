"""Admission is first come, first served, visible, and interruptible.

Real job-manager dispatch through the production limiter and worker machinery;
only the runners are fakes.

MUTATION PROOF, each run in one uninterrupted sequence:

- Restoring a timed re-entry around the limiter wait (wrapping the worker call
  in a 0.1 s ``move_on_after`` inside the retry loop) fails
  ``test_waiters_keep_arrival_order_and_are_granted_in_it`` on its
  ``positions == expected`` assertion: each expiry moves a waiter to the back.
- Removing the ``wake_on_request`` registration from the attempt's wait fails
  ``test_a_pause_reaches_a_waiter_without_a_poll`` on its
  ``JobState.PAUSED`` deadline assertion, because nothing interrupts the wait.

Restoring each returns the module to green.
"""

from __future__ import annotations

import asyncio
import os
import threading
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
from ..service_quiesce import ServiceQuiesceController
from ._job_roots import _TEST_PROJECT_ROOT, _TEST_PROJECT_ROOT_OTHER
from ._state_fixtures import reset_limiters

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytestmark = [pytest.mark.unit]

_THIRD_ROOT = os.path.abspath(os.path.join(os.sep, "third"))


@pytest.fixture(autouse=True)
def _fresh_limiters() -> Iterator[None]:
    reset_limiters()
    yield
    reset_limiters()


async def _until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition not reached before the deadline")
        await asyncio.sleep(0.005)


class _Queue:
    """One holder on the encode slot and encode jobs queued behind it."""

    def __init__(self, waiters: int) -> None:
        self.manager = JobManager(
            max_nonterminal=waiters + 1,
            state_path=None,
            quiesce_controller=ServiceQuiesceController(),
        )
        self.release = threading.Event()
        self.started = threading.Event()
        self.granted: list[str] = []
        self._granted_lock = threading.Lock()
        specs = [
            (JobSource.CODE, _TEST_PROJECT_ROOT),
            (JobSource.VAULT, _TEST_PROJECT_ROOT),
            (JobSource.CODE, _TEST_PROJECT_ROOT_OTHER),
            (JobSource.VAULT, _TEST_PROJECT_ROOT_OTHER),
            (JobSource.CODE, _THIRD_ROOT),
        ][: waiters + 1]
        self.ids: list[str] = []
        for source, root in specs:
            created = self.manager.create(
                JobSpec(
                    JobOperation.INDEX,
                    source,
                    root,
                    JobMode.REBUILD,
                    RunAuthority.REBUILD,
                ),
                JobInitiator("test", "admission-queue", root),
            )
            assert created.job is not None
            self.ids.append(created.job.id)

    def _holder(self, context: JobAttemptContext) -> JobExecutionResult:
        with context.control.protected():
            self.started.set()
            assert self.release.wait(timeout=10)
        return JobExecutionResult(summary="holder done")

    def _waiter(self, context: JobAttemptContext) -> JobExecutionResult:
        with self._granted_lock:
            self.granted.append(context.job_id)
        return JobExecutionResult(summary="waiter done")

    async def start(self) -> None:
        holder, *waiters = self.ids
        assert self.manager.bind_dispatch(holder, self._holder).code == (
            "dispatch_bound"
        )
        assert (await self.manager.dispatch_async(holder)).code == "attempt_started"
        assert await asyncio.to_thread(self.started.wait, 5)
        for index, job_id in enumerate(waiters, start=1):
            assert self.manager.bind_dispatch(job_id, self._waiter).code == (
                "dispatch_bound"
            )
            assert (await self.manager.dispatch_async(job_id)).code == (
                "attempt_started"
            )
            # Each waiter is in the limiter before the next is dispatched, so
            # arrival order is the dispatch order.
            await _until(
                lambda count=index: (
                    get_encode_limiter().statistics().tasks_waiting == count
                )
            )
            # Spread arrivals so a timed re-entry would rotate them visibly.
            await asyncio.sleep(0.03)

    def positions(self) -> list[tuple[str, str, int]]:
        return [
            (waiter.job_id, waiter.slot, waiter.position)
            for waiter in self.manager.admission_queue()
        ]

    async def close(self) -> None:
        self.release.set()
        requested = self.manager.begin_shutdown()
        assert (
            await self.manager.wait_for_shutdown(requested, timeout_seconds=5)
        ).clean


async def test_waiters_keep_arrival_order_and_are_granted_in_it() -> None:
    queue = _Queue(waiters=3)
    try:
        await queue.start()
        _holder, first, second, third = queue.ids
        expected = [
            (first, "encode", 1),
            (second, "encode", 2),
            (third, "encode", 3),
        ]
        # Sample across several former poll periods: order must never move.
        for _ in range(40):
            positions = queue.positions()
            assert positions == expected, positions
            await asyncio.sleep(0.01)
        queue.release.set()
        await _until(lambda: len(queue.granted) == 3)
        assert queue.granted == [first, second, third]
        assert queue.positions() == []
    finally:
        await queue.close()


async def test_a_pause_reaches_a_waiter_without_a_poll() -> None:
    """A paused waiter leaves the queue promptly and the rest move up."""
    queue = _Queue(waiters=2)
    try:
        await queue.start()
        _holder, first, second = queue.ids
        loop = asyncio.get_running_loop()
        requested = loop.time()
        queue.manager.set_desired_state(first, DesiredJobState.PAUSED)

        def paused() -> bool:
            snapshot = queue.manager.get(first)
            assert snapshot is not None
            return snapshot.state is JobState.PAUSED

        # The holder never releases here, so only the wake can deliver this.
        await _until(paused, timeout=1.0)
        assert loop.time() - requested < 1.0
        assert queue.positions() == [(second, "encode", 1)]
    finally:
        await queue.close()


async def test_a_job_wait_ends_on_admission_and_on_finish() -> None:
    queue = _Queue(waiters=1)
    try:
        await queue.start()
        holder, waiter = queue.ids
        expired = await queue.manager.wait_for_job(
            waiter, until="admitted", timeout_seconds=0.2
        )
        assert expired is not None
        assert not expired.reached
        assert expired.waited_seconds >= 0.2
        assert expired.job.timestamps.admission_acquired_at is None

        already = await queue.manager.wait_for_job(
            holder, until="admitted", timeout_seconds=5
        )
        assert already is not None
        assert already.reached
        assert already.waited_seconds < 1.0

        waiting = asyncio.create_task(
            queue.manager.wait_for_job(waiter, until="finished", timeout_seconds=5)
        )
        await asyncio.sleep(0.05)
        assert not waiting.done()
        queue.release.set()
        finished = await waiting
        assert finished is not None
        assert finished.reached
        assert finished.job.state is JobState.SUCCEEDED
    finally:
        await queue.close()


async def test_a_wait_for_an_unknown_job_reports_none() -> None:
    manager = JobManager(
        max_nonterminal=1,
        state_path=None,
        quiesce_controller=ServiceQuiesceController(),
    )
    assert (
        await manager.wait_for_job("0" * 32, until="finished", timeout_seconds=1)
        is None
    )
