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
    from types import FrameType

    from ..job_manager.models import JobAttemptContext

pytestmark = [pytest.mark.unit]


async def test_rebuild_completion_reconciles_on_worker_thread(
    tmp_path: Path,
) -> None:
    """Observe the real reconciliation call site; no watcher state means it
    runs and returns False harmlessly, so nothing needs to be substituted.
    """
    finished = threading.Event()
    observations: list[tuple[str, int]] = []
    loop_thread = threading.get_ident()
    reconcile_code = watcher_runtime.reconcile_completed_rebuild.__code__

    def observe(frame: FrameType, event: str, _arg: object) -> None:
        if event == "call" and frame.f_code is reconcile_code:
            snapshot = frame.f_locals["snapshot"]
            observations.append((snapshot.id, threading.get_ident()))
            finished.set()

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        del context
        return JobExecutionResult(summary="verified rebuild")

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
    prior_profile = threading.getprofile()
    threading.setprofile(observe)
    try:
        await manager.dispatch_async(job_id)
        assert await asyncio.to_thread(finished.wait, 5.0)
    finally:
        threading.setprofile(prior_profile)
    assert observations[0][0] == job_id
    # Calling reconciliation inline on the event loop thread never starts a
    # new profiled thread, so the profile hook is never entered and
    # ``finished.wait`` above times out and fails instead; restoring executor
    # dispatch schedules a worker thread and returns both assertions to green.
    assert observations[0][1] != loop_thread
