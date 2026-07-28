"""Durability contract for deferred progress persistence.

Progress-only publications coalesce their durable write onto a time budget;
lifecycle transitions persist synchronously and unconditionally carry any
progress still deferred inside that budget. These tests pin both halves of
the contract against the real state file through the real writer.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

from ..job_control import RunControlToken
from ..job_manager._control import AttemptTerminal
from ..job_manager._persistence import PROGRESS_FLUSH_BUDGET_SECONDS
from ..job_manager.manager import JobManager
from ..job_manager.models import ProgressUpdate
from ..job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSnapshot,
    JobSource,
    JobSpec,
    JobState,
)
from ..job_persistence import load_persisted_state

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _started_manager(
    state_path: Path,
    root: str,
    task: asyncio.Task[bool],
) -> tuple[JobManager, str]:
    """Create one persisted manager whose only job owns a started attempt."""
    manager = JobManager(max_nonterminal=1, state_path=state_path)
    created = manager.create(
        JobSpec(JobOperation.INDEX, JobSource.CODE, root, JobMode.INCREMENTAL),
        JobInitiator("service", "reindex_codebase", root),
    )
    assert created.job is not None
    started = manager.start_attempt(
        created.job.id,
        task=task,
        control=RunControlToken(),
    )
    assert started.code == "attempt_started"
    return manager, created.job.id


def _persisted_job(state_path: Path, job_id: str) -> JobSnapshot:
    """Load the durable generation and return one exact job from it."""
    persisted = load_persisted_state(state_path)
    for job in persisted.jobs:
        if job.id == job_id:
            return job
    raise AssertionError(f"job {job_id} is not in the persisted state")


async def test_progress_publish_inside_the_budget_defers_the_durable_write(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "jobs-state.json"
    task = asyncio.create_task(asyncio.Event().wait())
    try:
        manager, job_id = _started_manager(state_path, str(tmp_path), task)
        before = state_path.read_bytes()
        outcome = manager.update_progress(
            job_id,
            ProgressUpdate(1, task, "hash", completed=5, total=10),
        )
        assert outcome.code == "progress_updated"
        # Catches a reintroduced per-publish persist: any durable write here
        # rewrites the state file, so unchanged bytes are the deferral.
        # start_attempt persisted immediately above, so the flush budget
        # cannot have expired between the two adjacent calls.
        assert state_path.read_bytes() == before
        live = manager.get(job_id)
        assert live is not None
        assert live.progress is not None
        assert live.progress.completed == 5
        # Catches deferred progress being reported as already durable: the
        # in-memory generation is ahead of disk and must say so.
        assert manager.persistence_dirty is True
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_terminal_transition_is_durable_and_carries_deferred_progress(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "jobs-state.json"
    task = asyncio.create_task(asyncio.Event().wait())
    try:
        manager, job_id = _started_manager(state_path, str(tmp_path), task)
        published = manager.update_progress(
            job_id,
            ProgressUpdate(1, task, "hash", completed=7, total=9),
        )
        assert published.code == "progress_updated"
        finished = manager.finish_attempt(
            job_id,
            AttemptTerminal(
                attempt=1,
                task=task,
                state=JobState.SUCCEEDED,
                result="indexed",
            ),
        )
        assert finished.code == "job_finished"
        persisted = _persisted_job(state_path, job_id)
        # Catches a terminal transition riding the lazy progress budget: the
        # state on disk must already be terminal when finish_attempt returns,
        # even though the budget since the last flush has not expired.
        assert persisted.state is JobState.SUCCEEDED
        # Catches a transition write that drops the deferred progress: the
        # synchronous persist serializes the full current generation, so the
        # last published progress rides along.
        assert persisted.progress is not None
        assert persisted.progress.step == "hash"
        assert persisted.progress.completed == 7
        assert manager.persistence_dirty is False
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_expired_budget_flushes_on_the_next_publish(tmp_path: Path) -> None:
    state_path = tmp_path / "jobs-state.json"
    task = asyncio.create_task(asyncio.Event().wait())
    try:
        manager, job_id = _started_manager(state_path, str(tmp_path), task)
        deferred = manager.update_progress(
            job_id,
            ProgressUpdate(1, task, "hash", completed=1, total=10),
        )
        assert deferred.code == "progress_updated"
        time.sleep(PROGRESS_FLUSH_BUDGET_SECONDS + 0.05)
        flushing = manager.update_progress(
            job_id,
            ProgressUpdate(1, task, "hash", completed=9, total=10),
        )
        assert flushing.code == "progress_updated"
        persisted = _persisted_job(state_path, job_id)
        # Catches a coalesced flush that never fires without a transition:
        # the first publish past the expired budget must write, and it must
        # carry the newest count, not the one that was deferred.
        assert persisted.progress is not None
        assert persisted.progress.completed == 9
        assert manager.persistence_dirty is False
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_flush_persistence_makes_deferred_progress_durable(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "jobs-state.json"
    task = asyncio.create_task(asyncio.Event().wait())
    try:
        manager, job_id = _started_manager(state_path, str(tmp_path), task)
        published = manager.update_progress(
            job_id,
            ProgressUpdate(1, task, "hash", completed=3, total=10),
        )
        assert published.code == "progress_updated"
        flushed = manager.flush_persistence()
        # Catches deferred progress being treated as clean: shutdown funnels
        # through flush_persistence, so a pending generation must flush there
        # rather than report itself already durable.
        assert flushed.code == "persistence_flushed"
        persisted = _persisted_job(state_path, job_id)
        assert persisted.progress is not None
        assert persisted.progress.completed == 3
        assert manager.persistence_dirty is False
        assert manager.flush_persistence().code == "persistence_clean"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
