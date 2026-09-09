"""CPU-only watcher intake coverage for service resource quiesce."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from ..indexer._run_ledger_models import RunAuthority
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
from ..watcher_intake import _new_controller
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
            RunAuthority.PUBLICATION,
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
                controller=_new_controller(slot.retry_policy),
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
