"""Operator completion must reconcile watcher state without blocking its loop."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import pytest

from .. import jobs, watcher_runtime
from ..indexer._run_ledger_models import RunAuthority
from ..job_manager.manager import JobManager
from ..job_manager.models import JobExecutionResult
from ..job_models import JobInitiator, JobMode, JobOperation, JobSource, JobSpec
from ..service_quiesce import ServiceQuiesceController

if TYPE_CHECKING:
    from pathlib import Path

    from ..job_manager.models import JobAttemptContext
    from ..job_models import JobSnapshot

pytestmark = [pytest.mark.unit]


async def test_rebuild_completion_reconciles_on_worker_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    finished = threading.Event()
    observations: list[tuple[str, int]] = []
    loop_thread = threading.get_ident()

    def observe(snapshot: JobSnapshot) -> bool:
        observations.append((snapshot.id, threading.get_ident()))
        finished.set()
        return False

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        del context
        return JobExecutionResult(summary="verified rebuild")

    monkeypatch.setattr(watcher_runtime, "reconcile_completed_rebuild", observe)
    manager = JobManager(
        state_path=None,
        max_nonterminal=1,
        quiesce_controller=ServiceQuiesceController(),
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.REBUILD,
            RunAuthority.REBUILD,
        ),
        JobInitiator("cli", "index --rebuild", str(tmp_path)),
    )
    assert created.job is not None
    job_id = created.job.id
    manager.bind_dispatch(job_id, runner, on_finished=jobs._sync_legacy_finished)
    await manager.dispatch_async(job_id)
    assert await asyncio.to_thread(finished.wait, 5.0)
    assert observations[0][0] == job_id
    # Calling reconciliation directly in the completion callback makes this
    # fail at the thread assertion; restoring executor dispatch returns green.
    assert observations[0][1] != loop_thread
