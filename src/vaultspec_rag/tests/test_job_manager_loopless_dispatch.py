"""A dispatch decided off the loop still reaches the loop that owns execution.

Job admission runs a policy preflight that scans the tree, so callers push
that work onto a plain worker thread to keep the scan off the serving path.
Such a thread has no event loop of its own and never will - waiting does not
give it one - so a dispatch resolved only against the calling thread is not
slow to succeed, it is unable to.

These tests pin both directions of the resolution. With a service loop
adopted the dispatch is marshalled onto it and the attempt really runs; with
none adopted the original rejection stands, because in a process that never
had a loop - the local CLI - "loopless" is the truth rather than a thread
boundary.

No mocks, stubs, or patches: a real ``JobManager``, a real bound runner, and
a real loopless worker thread via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import pytest

from .. import jobs
from ..job_manager.manager import JobManager
from ..job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ..registry import get_registry, reset_registry
from ..service import ServiceRegistry
from ..service_quiesce import ServiceQuiesceController
from ._job_roots import _TEST_PROJECT_ROOT

if TYPE_CHECKING:
    from ..job_manager.models import JobAttemptContext, JobExecutionResult
    from ..job_models import JobSnapshot

pytestmark = [pytest.mark.unit]


def _queued_code_job(manager: JobManager) -> str:
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.INCREMENTAL,
        ),
        JobInitiator("integrity", "loopless dispatch", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    return created.job.id


def _bind_recording_runner(
    manager: JobManager,
    job_id: str,
) -> tuple[threading.Event, threading.Event]:
    """Bind a real runner and return its reached/finished signals."""
    ran = threading.Event()
    finished = threading.Event()

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        del context
        from ..job_manager.models import JobExecutionResult as _Result

        ran.set()
        return _Result(summary="repaired")

    def on_finished(
        snapshot: JobSnapshot,
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
    return ran, finished


class TestDispatchFromALooplessThread:
    def test_registry_reset_replaces_the_manager_and_its_controller(self) -> None:
        """Public lookup never retains a manager from a discarded registry.

        The registry owns both the manager and the quiesce controller. If a
        module-level manager cache survives ``reset_registry()``, the public
        lookup crosses that lifecycle boundary and returns an authority tied
        to the closed controller instead of the live registry.
        """
        reset_registry()
        jobs.reset()
        try:
            retired_registry = get_registry()
            retired_manager = jobs.get_job_manager()
            assert retired_manager is retired_registry.create_job_manager()
            assert (
                retired_manager._quiesce_controller
                is retired_registry._quiesce_controller
            )

            reset_registry()

            live_registry = get_registry()
            live_manager = jobs.get_job_manager()
            assert live_registry is not retired_registry
            assert live_manager is live_registry.create_job_manager()
            assert live_manager is not retired_manager
            assert live_manager._quiesce_controller is live_registry._quiesce_controller
            assert (
                live_manager._quiesce_controller
                is not retired_manager._quiesce_controller
            )
        finally:
            jobs.reset()
            reset_registry()

    async def test_an_adopted_loop_runs_a_dispatch_decided_off_it(self) -> None:
        """The production shape: decide on a worker thread, run on the loop.

        Catches the handoff being dropped. Without it ``dispatch`` resolves
        only ``asyncio.get_running_loop()`` in the calling thread, so the
        outcome assertion fails on ``event_loop_required`` and the attempt
        never reaches the runner at all.
        """
        manager = JobManager(
            max_nonterminal=1,
            state_path=None,
            quiesce_controller=ServiceQuiesceController(),
        )
        job_id = _queued_code_job(manager)
        ran, finished = _bind_recording_runner(manager, job_id)
        manager.adopt_service_loop(asyncio.get_running_loop())

        outcome = await asyncio.to_thread(manager.dispatch, job_id)

        assert outcome.code == "attempt_started"
        assert await asyncio.to_thread(ran.wait, 5.0)
        assert await asyncio.to_thread(finished.wait, 5.0)
        final = manager.get(job_id)
        assert final is not None
        assert final.state is JobState.SUCCEEDED

    async def test_a_process_with_no_adopted_loop_still_rejects(self) -> None:
        """The handoff must not invent a loop where none exists.

        Catches the fallback being widened into "dispatch anywhere": a
        process that adopted no loop has nothing to marshal onto, and
        reporting success there would strand the attempt unrun.
        """
        manager = JobManager(
            max_nonterminal=1,
            state_path=None,
            quiesce_controller=ServiceQuiesceController(),
        )
        job_id = _queued_code_job(manager)
        ran, _finished = _bind_recording_runner(manager, job_id)

        outcome = await asyncio.to_thread(manager.dispatch, job_id)

        assert outcome.code == "event_loop_required"
        assert not ran.is_set()

    async def test_dispatch_on_the_loop_itself_is_unchanged(self) -> None:
        """The ordinary on-loop caller keeps its direct, unmarshalled path."""
        manager = JobManager(
            max_nonterminal=1,
            state_path=None,
            quiesce_controller=ServiceQuiesceController(),
        )
        job_id = _queued_code_job(manager)
        ran, finished = _bind_recording_runner(manager, job_id)

        assert manager.dispatch(job_id).code == "attempt_started"

        assert await asyncio.to_thread(ran.wait, 5.0)
        assert await asyncio.to_thread(finished.wait, 5.0)


class TestTheServiceWiresItsOwnLoop:
    async def test_startup_leaves_loopless_dispatch_working(self) -> None:
        """Startup must adopt the loop, or the handoff is unreachable code.

        This is the guard the original integrity-repair path never had: the
        mechanism existed and was simply never wired to a loop, so every
        repair admitted from a worker thread failed. Asserted through
        behaviour rather than the stored attribute - what matters is that a
        loopless dispatch lands after real startup, not where the loop is
        kept. With the adoption removed from ``_start_job_manager`` the
        outcome assertion fails on ``event_loop_required``.
        """
        from ..server._lifespan import _start_job_manager

        manager = JobManager(
            max_nonterminal=1,
            state_path=None,
            quiesce_controller=ServiceQuiesceController(),
        )
        await _start_job_manager(manager, ServiceRegistry())

        job_id = _queued_code_job(manager)
        ran, _finished = _bind_recording_runner(manager, job_id)
        outcome = await asyncio.to_thread(manager.dispatch, job_id)

        assert outcome.code == "attempt_started"
        assert await asyncio.to_thread(ran.wait, 5.0)
