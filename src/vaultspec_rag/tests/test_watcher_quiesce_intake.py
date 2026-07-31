"""CPU-only watcher intake coverage for service resource quiesce."""

from __future__ import annotations

import logging
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
from ..service import ServiceRegistry
from ..service_quiesce import QuiesceState
from ..watcher_execution import (
    _CreatedWatcherJobRequest,
    _dispatch_created_watcher_job,
)
from ..watcher_intake import _reconcile_watcher_slot
from ..watcher_retry import WatcherRetryPolicy, WatcherSource
from ..watcher_runtime import WatcherConvergenceSlot

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from pathlib import Path


def _slot(root: Path, registry: ServiceRegistry) -> WatcherConvergenceSlot:
    """Build one real on-disk retry owner with deferred code work."""
    policy = WatcherRetryPolicy.for_root(root, WatcherSource.CODE)
    policy.mark_convergence_pending(now=1.0)
    slot = WatcherConvergenceSlot(
        JobSource.CODE,
        root,
        registry,
        policy,
    )
    slot.add_dirty(root / "changed.py")
    return slot


@pytest.mark.asyncio
async def test_closed_quiesce_defers_dirty_watcher_work_without_retry_mutation(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Closed admission must leave durable generation and dirty intent untouched."""
    registry = ServiceRegistry()
    slot = _slot(tmp_path, registry)
    before = slot.retry_policy.state

    paused = registry.quiesce_resources(timeout_seconds=0)
    assert paused.achieved
    assert registry.quiesce_snapshot().state is QuiesceState.QUIESCED

    with caplog.at_level(logging.DEBUG, logger="vaultspec_rag.watcher_intake"):
        await _reconcile_watcher_slot(slot, cooldown=0.0, now=2.0)

    assert slot.dirty_paths() == frozenset({tmp_path / "changed.py"})
    assert slot.retry_policy.state == before
    assert any(
        "event=quiesce_admission_closed" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_idle_tick_reenters_normal_reconciliation_after_warming(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The existing idle tick resumes ordinary reconciliation after warming."""
    registry = ServiceRegistry()
    slot = _slot(tmp_path, registry)
    slot.last_success = 10.0

    assert registry.quiesce_resources(timeout_seconds=0).achieved
    assert registry.resume_resources().achieved
    assert registry.quiesce_snapshot().state is QuiesceState.RUNNING

    with caplog.at_level(logging.DEBUG, logger="vaultspec_rag.watcher_intake"):
        await _reconcile_watcher_slot(slot, cooldown=1.0, now=10.0)

    assert slot.dirty_paths() == frozenset({tmp_path / "changed.py"})
    assert slot.retry_policy.state.convergence_generation == 1
    assert any(
        "event=reindex_suppressed" in record.getMessage()
        and "cooldown_remaining_seconds=1" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_pause_between_watcher_observation_and_start_defers_exact_work(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A closed start boundary retains the same watcher job and retry claim."""
    registry = ServiceRegistry()
    slot = _slot(tmp_path, registry)
    manager = JobManager(
        max_nonterminal=1,
        state_path=None,
        quiesce_controller=registry._quiesce_controller,
    )
    admitted = slot.retry_policy.admit(now=2.0)
    assert admitted.admitted
    assert admitted.attempt_generation is not None
    retry_before = slot.retry_policy.state
    candidate_paths = slot.dirty_paths()
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.INCREMENTAL,
        ),
        JobInitiator("watcher", slot.command, str(tmp_path)),
    )
    assert created.job is not None
    with slot.lock:
        slot.job_id = created.job.id
        slot.watcher_owned = True
        slot.observed_state = created.job.state
        slot.retry_attempt_generations[created.job.attempt.number] = (
            admitted.attempt_generation
        )

    assert (
        registry._quiesce_controller.begin_pause().snapshot.state
        is QuiesceState.PAUSING
    )

    with caplog.at_level(logging.DEBUG, logger="vaultspec_rag.watcher_execution"):
        await _dispatch_created_watcher_job(
            _CreatedWatcherJobRequest(
                slot=slot,
                manager=manager,
                snapshot=created.job,
                candidate_paths=candidate_paths,
                code_preflight=None,
                document_preflight=None,
                secondary_graph_cache=None,
            )
        )

    deferred = manager.get(created.job.id)
    assert deferred is not None
    assert deferred.state is JobState.PAUSED
    assert deferred.desired_state is DesiredJobState.RUNNING
    assert not deferred.resources.holds_anything
    assert slot.dirty_paths() == candidate_paths
    assert slot.retry_policy.state == retry_before
    assert any(
        "event=quiesce_admission_deferred" in record.getMessage()
        for record in caplog.records
    )
