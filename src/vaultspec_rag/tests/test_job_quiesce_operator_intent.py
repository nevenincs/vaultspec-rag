"""Operator intent remains editable while global quiesce unwinds a job."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import pytest

from ..indexer._run_ledger_models import RunAuthority
from ..job_manager.manager import JobManager
from ..job_manager.models import JobAttemptContext, JobExecutionResult
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobOutcomeStatus,
    JobSource,
    JobSpec,
    JobState,
    capabilities_for_state,
)
from ..job_persistence import load_persisted_state
from ..service import ServiceRegistry
from ..service_quiesce import QuiesceTransitionCode
from ._job_roots import _TEST_PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _manager(state_path: Path) -> tuple[ServiceRegistry, JobManager, str]:
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
            RunAuthority.REBUILD,
        ),
        JobInitiator("test", "operator-global-pause", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    return registry, manager, created.job.id


async def test_operator_pause_during_global_unwind_is_durable_and_prevents_restart(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "jobs.json"
    registry, manager, job_id = _manager(state_path)
    started, release = threading.Event(), threading.Event()
    attempts: list[int] = []

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        attempts.append(context.attempt)
        with context.control.protected():
            started.set()
            assert release.wait(timeout=10)
        return JobExecutionResult(summary="completed")

    manager.bind_dispatch(job_id, runner)
    assert (await manager.dispatch_async(job_id)).code == "attempt_started"
    assert await asyncio.to_thread(started.wait, 5)
    try:
        assert registry.quiesce_resources(timeout_seconds=0).code is (
            QuiesceTransitionCode.DRAIN_TIMED_OUT
        )
        before = manager.get(job_id)
        assert before is not None and before.desired_state is DesiredJobState.RUNNING
        assert before.state is JobState.PAUSING
        assert before.capabilities.pausable, "global pause hid operator action"
        assert load_persisted_state(state_path).jobs[0].capabilities.pausable
        stale = manager.set_desired_state(
            job_id, DesiredJobState.PAUSED, expected_revision=before.revision - 1
        )
        assert stale.code == "revision_conflict"
        paused = manager.set_desired_state(
            job_id, DesiredJobState.PAUSED, expected_revision=before.revision
        )
        assert paused.code == "pause_requested", "global unwind rejected operator pause"
        assert paused.job is not None
        assert paused.job.runtime == before.runtime
        assert paused.job.resources == before.resources
        assert registry.quiesce_snapshot().active_compute_tickets == 1
        assert (
            manager.set_desired_state(
                job_id, DesiredJobState.PAUSED, expected_revision=before.revision
            ).status
            is JobOutcomeStatus.OK
        )
        persisted = load_persisted_state(state_path).jobs[0]
        assert persisted.desired_state is DesiredJobState.PAUSED
        assert registry.resume_resources(timeout_seconds=0).achieved
        release.set()
        assert (await manager.wait_for_attempt(job_id, timeout_seconds=5)).code == (
            "attempt_released"
        )
        final = manager.get(job_id)
        assert final is not None
        assert final.state is JobState.PAUSED
        assert final.desired_state is DesiredJobState.PAUSED
        assert final.attempt.number == 1 and attempts == [1]
        assert not final.resources.index_capacity_held
        assert registry.quiesce_snapshot().active_compute_tickets == 0
    finally:
        release.set()
        requested = manager.begin_shutdown()
        assert (await manager.wait_for_shutdown(requested, timeout_seconds=5)).clean


def test_operator_can_hold_idle_quiesced_job_and_replay_same_intent(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "jobs.json"
    registry, manager, job_id = _manager(state_path)
    manager.defer_unstarted_for_quiesce(job_id)
    before = manager.get(job_id)
    assert before is not None
    assert before.capabilities.pausable, "idle global pause hid operator action"
    assert (
        load_persisted_state(state_path).jobs[0].capabilities == before.capabilities
    ), "codec lost global quiesce pause capability"
    paused = manager.set_desired_state(job_id, DesiredJobState.PAUSED)
    assert paused.code == "job_paused", "held quiesced job rejected operator pause"
    assert paused.job is not None
    assert paused.job.attempt == before.attempt
    assert paused.job.runtime == before.runtime
    assert registry.resume_resources(timeout_seconds=0).achieved
    final = manager.get(job_id)
    assert final is not None and final.desired_state is DesiredJobState.PAUSED
    assert (
        manager.set_desired_state(
            job_id, DesiredJobState.PAUSED, expected_revision=before.revision
        ).status
        is JobOutcomeStatus.OK
    )


@pytest.mark.parametrize("state", [JobState.PAUSING, JobState.PAUSED])
def test_quiesced_job_capability_tracks_operator_intent(state: JobState) -> None:
    spec = JobSpec(
        JobOperation.INDEX,
        JobSource.CODE,
        _TEST_PROJECT_ROOT,
        JobMode.REBUILD,
        RunAuthority.REBUILD,
    )
    assert capabilities_for_state(
        spec, state, desired_state=DesiredJobState.RUNNING
    ).pausable, "global pause hid operator action"
    assert not capabilities_for_state(
        spec, state, desired_state=DesiredJobState.PAUSED
    ).pausable, "operator-paused job advertised another pause"


def test_quiesced_cancellation_remains_absorbing(tmp_path: Path) -> None:
    _, manager, job_id = _manager(tmp_path / "jobs.json")
    manager.defer_unstarted_for_quiesce(job_id)
    cancelled = manager.set_desired_state(job_id, DesiredJobState.CANCELLED)
    assert cancelled.code == "job_cancelled"
    assert cancelled.job is not None
    paused = manager.set_desired_state(job_id, DesiredJobState.PAUSED)
    assert paused.code == "invalid_transition", "cancelled job accepted pause intent"
    assert paused.status is JobOutcomeStatus.ERROR
    assert manager.get(job_id) == cancelled.job
