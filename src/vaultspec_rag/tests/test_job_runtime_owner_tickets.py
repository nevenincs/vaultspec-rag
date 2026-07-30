"""Compute admission survives every managed-job runtime owner replacement."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from ..job_control import RunControlToken
from ..job_manager import state as job_manager_state
from ..job_manager._control import AttemptTerminal
from ..job_manager.manager import JobManager
from ..job_manager.state import (
    UNOWNED_RUNTIME,
    JobRuntimeOwner,
    ManagedJob,
    assign_runtime_owner,
)
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
from ._job_roots import _TEST_PROJECT_ROOT

pytestmark = [pytest.mark.unit]


def _admitted_job(controller: ServiceQuiesceController) -> tuple[JobManager, str]:
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
        JobInitiator("test", "runtime-owner-tickets", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    return manager, created.job.id


async def _idle_attempt() -> None:
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_finish_attempt_releases_the_attempts_compute_ticket() -> None:
    """A terminal commit gives back the admission its attempt still holds."""
    controller = ServiceQuiesceController()
    manager, job_id = _admitted_job(controller)
    task = asyncio.get_running_loop().create_task(_idle_attempt())
    try:
        started = manager.start_attempt(job_id, task=task, control=RunControlToken())
        assert started.code == "attempt_started"
        assert controller.snapshot().active_compute_tickets == 1

        finished = manager.finish_attempt(
            job_id,
            AttemptTerminal(
                attempt=1,
                task=task,
                state=JobState.FAILED,
                result="the attempt raised before releasing its resources",
                error_kind="unknown",
            ),
        )
        assert finished.code == "job_finished"
        assert controller.snapshot().active_compute_tickets == 0
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_acknowledge_control_releases_the_attempts_compute_ticket() -> None:
    """An unwound attempt gives back the admission it still holds."""
    controller = ServiceQuiesceController()
    manager, job_id = _admitted_job(controller)
    task = asyncio.get_running_loop().create_task(_idle_attempt())
    try:
        started = manager.start_attempt(job_id, task=task, control=RunControlToken())
        assert started.code == "attempt_started"
        assert controller.snapshot().active_compute_tickets == 1

        paused = manager.set_desired_state(job_id, DesiredJobState.PAUSED)
        assert paused.code == "pause_requested"
        acknowledged = manager.acknowledge_control(job_id, attempt=1, task=task)
        assert acknowledged.code == "control_acknowledged"
        assert controller.snapshot().active_compute_tickets == 0
    finally:
        task.cancel()


def test_assign_runtime_owner_carries_a_retained_ticket_unreleased() -> None:
    """Refining an owner that keeps its ticket must not release that ticket."""
    controller = ServiceQuiesceController()
    manager, job_id = _admitted_job(controller)
    snapshot = manager.get(job_id)
    assert snapshot is not None
    ticket = controller.acquire_ticket()
    managed = ManagedJob(
        snapshot=snapshot,
        runtime=JobRuntimeOwner(task=None, control=None, compute_ticket=ticket),
    )

    assign_runtime_owner(
        managed,
        JobRuntimeOwner(
            task=None,
            control=None,
            worker_active=True,
            compute_ticket=ticket,
        ),
    )
    assert controller.snapshot().active_compute_tickets == 1

    assign_runtime_owner(managed, UNOWNED_RUNTIME)
    assert controller.snapshot().active_compute_tickets == 0

    # A path that released before replacing its owner stays correct: the
    # controller tracks tickets by identity, so releasing twice is a no-op.
    assign_runtime_owner(managed, UNOWNED_RUNTIME)
    assert controller.snapshot().active_compute_tickets == 0


def test_runtime_owner_replacement_has_exactly_one_owner() -> None:
    """No manager module may install a runtime owner past the releasing seam.

    Guard proof: reintroducing a direct ``managed.runtime = ...`` assignment in
    any other module of the package fails this on the offending module name.
    """
    package = Path(job_manager_state.__file__).parent
    assignment = re.compile(r"\.runtime\s*=[^=]")
    offenders = sorted(
        module.name
        for module in package.glob("*.py")
        if module.name != "state.py"
        and assignment.search(module.read_text(encoding="utf-8"))
    )
    assert offenders == []
