"""A held encode slot with encode jobs queued behind it, on a real job manager.

The slot is held by a real attempt running through the production limiter and
worker machinery; only the runners are test bodies. Both the manager-level and
the route-level admission tests build their queue here, so there is one
definition of "a job is waiting for the slot".
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import TYPE_CHECKING

from ..concurrency import get_encode_limiter
from ..indexer._run_ledger_models import RunAuthority
from ..job_manager.manager import JobManager
from ..job_manager.models import JobAttemptContext, JobExecutionResult
from ..job_models import JobInitiator, JobMode, JobOperation, JobSource, JobSpec
from ..service_quiesce import ServiceQuiesceController
from ._job_roots import _TEST_PROJECT_ROOT, _TEST_PROJECT_ROOT_OTHER

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["EncodeQueue", "until"]

_THIRD_ROOT = os.path.abspath(os.path.join(os.sep, "third"))


async def until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    """Poll *predicate* on the running loop until it holds or *timeout* ends."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition not reached before the deadline")
        await asyncio.sleep(0.005)


class EncodeQueue:
    """One holder on the encode slot and encode jobs queued behind it.

    ``ids`` lists the holder first, then the waiters in arrival order. Pass a
    ``manager`` to queue on one the service routes also read; the default is a
    private manager.
    """

    def __init__(self, waiters: int, manager: JobManager | None = None) -> None:
        self.manager = manager or JobManager(
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
            await until(
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
