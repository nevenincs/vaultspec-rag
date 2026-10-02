"""Managed success preserves drift from the external indexing result boundary."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

from ..indexer._run_ledger_models import RunAuthority
from ..job_manager._persistence import SnapshotTransition
from ..job_manager.manager import JobManager
from ..job_manager.models import JobExecutionResult
from ..job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ..service_quiesce import ServiceQuiesceController

if TYPE_CHECKING:
    from pathlib import Path

    from ..job_manager.models import JobAttemptContext
    from ..job_models import JobSnapshot

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_successful_dispatch_persists_positive_drift_to_the_public_snapshot(
    tmp_path: Path,
) -> None:
    """Only the indexer-return boundary is supplied; managed execution is real.

    A model-free runner returns the exact canonical drift block so the manager,
    transitions, JSON persistence and public serialization remain exercised.
    """
    state_path = tmp_path / "jobs.json"
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=1,
        state_path=state_path,
    )
    root = str(tmp_path / "project")
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            root,
            JobMode.INCREMENTAL,
            RunAuthority.PUBLICATION,
        ),
        JobInitiator("cli", "drift propagation guard", root),
    )
    assert created.job is not None
    drift: dict[str, object] = {
        "superseded_paths": 2,
        "deferred_paths": ["pending.py"],
        "collisions_observed": 1,
        "retry_budget": 3,
    }
    finished = asyncio.Event()
    loop = asyncio.get_running_loop()

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        context.control.checkpoint()
        return JobExecutionResult(summary="repaired", drift=drift)

    def on_finished(
        snapshot: JobSnapshot,
        duration_seconds: float,
        result: JobExecutionResult | None,
        error: BaseException | None,
    ) -> None:
        del snapshot, duration_seconds, result, error
        loop.call_soon_threadsafe(finished.set)

    assert (
        manager.bind_dispatch(created.job.id, runner, on_finished=on_finished).code
        == "dispatch_bound"
    )
    try:
        assert manager.dispatch(created.job.id).code == "attempt_started"
        await asyncio.wait_for(finished.wait(), timeout=10)
        current = manager.get(created.job.id)
        assert current is not None
        assert current.state is JobState.SUCCEEDED
        # Dropping drift at any success transition fails this exact block.
        assert current.drift == drift
        assert current.to_dict()["drift"] == drift
        # A later revision omitting telemetry must carry it, not clear it.
        with manager._lock:
            terminal = next(
                job for job in manager._terminal if job.snapshot.id == current.id
            )
            manager._replace_snapshot_locked(
                terminal,
                SnapshotTransition(
                    state=current.state,
                    desired_state=current.desired_state,
                    now=time.time(),
                    finished_at=time.time(),
                ),
            )
        carried = manager.get(current.id)
        assert carried is not None
        # A None default instead of ellipsis fails this retention assertion.
        assert carried.drift == drift
        with manager._lock:
            assert manager._persist_locked() is None
        restored = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        assert restored.restore_persisted().code == "job_state_restored"
        loaded = restored.get(created.job.id)
        assert loaded is not None
        assert loaded.state is JobState.SUCCEEDED
        assert loaded.revision == carried.revision
        assert loaded.drift == drift
        assert loaded.to_dict()["drift"] == drift
    finally:
        requested = manager.begin_shutdown()
        shutdown = await manager.wait_for_shutdown(requested, timeout_seconds=10)
        assert shutdown.clean
