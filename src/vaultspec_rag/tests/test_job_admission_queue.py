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
from typing import TYPE_CHECKING

import pytest

from ..job_manager.manager import JobManager
from ..job_models import DesiredJobState, JobState
from ..service_quiesce import ServiceQuiesceController
from ._admission_queue import EncodeQueue, until
from ._state_fixtures import reset_limiters

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _fresh_limiters() -> Iterator[None]:
    reset_limiters()
    yield
    reset_limiters()


async def test_waiters_keep_arrival_order_and_are_granted_in_it() -> None:
    queue = EncodeQueue(waiters=3)
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
        await until(lambda: len(queue.granted) == 3)
        assert queue.granted == [first, second, third]
        assert queue.positions() == []
    finally:
        await queue.close()


async def test_a_pause_reaches_a_waiter_without_a_poll() -> None:
    """A paused waiter leaves the queue promptly and the rest move up."""
    queue = EncodeQueue(waiters=2)
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
        await until(paused, timeout=1.0)
        assert loop.time() - requested < 1.0
        assert queue.positions() == [(second, "encode", 1)]
    finally:
        await queue.close()


async def test_a_job_wait_ends_on_admission_and_on_finish() -> None:
    queue = EncodeQueue(waiters=1)
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
