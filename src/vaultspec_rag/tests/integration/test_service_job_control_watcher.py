"""Watcher convergence scenarios over production components.

The watcher schedules its own jobs, so the control surface has to hold
against work nobody asked for directly: a pause that must coalesce the
edits arriving behind it, a cancellation that must be replaced by a fresh
convergence run, and a stop that must leave the store safe to close.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ... import server
from ...indexer._vault_prep import prepare_document
from ...job_models import DesiredJobState, JobState
from ...registry import get_registry
from ...server import WatcherStartOutcome
from ._service_job_control_e2e_support import (
    E2E_POLL_SECONDS,
    E2E_TIMEOUT_SECONDS,
    assert_released,
)
from ._service_job_control_e2e_support import _e2e_runtime as _e2e_runtime_fixture

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ...job_manager.manager import JobManager
    from ...job_models import JobSnapshot
    from ...service import ProjectSlot, ServiceRegistry

pytestmark = pytest.mark.integration

__all__ = ["_e2e_runtime_fixture"]


def _write_watched_document(path: Path, root: Path, marker: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "tags: ['#adr', '#service-job-control']\n"
        "---\n"
        f"# {marker}\n\n"
        f"watcher lifecycle convergence marker {marker}\n",
        encoding="utf-8",
    )
    document = prepare_document(path, root)
    assert document is not None
    return document.id


def _watcher_jobs(manager: JobManager, root: Path) -> list[JobSnapshot]:
    resolved = str(root.resolve())
    return [
        snapshot
        for snapshot in manager.list_jobs()
        if snapshot.initiator.kind == "watcher"
        and snapshot.spec.project_root == resolved
    ]


async def _wait_for_watcher_job(
    manager: JobManager,
    root: Path,
    predicate: Callable[[JobSnapshot], bool],
    description: str,
) -> JobSnapshot:
    deadline = asyncio.get_running_loop().time() + E2E_TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        for snapshot in _watcher_jobs(manager, root):
            if predicate(snapshot):
                return snapshot
        await asyncio.sleep(E2E_POLL_SECONDS)
    raise AssertionError(
        f"{description}; last snapshots={_watcher_jobs(manager, root)!r}"
    )


def _watcher_attempt_owns_runtime(snapshot: JobSnapshot) -> bool:
    return all(
        (
            snapshot.state is JobState.RUNNING,
            snapshot.runtime.task_active,
            snapshot.runtime.worker_active,
            snapshot.resources.index_capacity_held,
            snapshot.resources.project_lease_held,
            snapshot.resources.writer_lock_held,
        )
    )


async def _start_real_watcher(root: Path) -> None:
    resolved = root.resolve()
    assert (
        server._ensure_watcher(
            resolved,
            get_registry(),
            debounce_ms=50,
            cooldown_s=0.0,
        )
        is WatcherStartOutcome.STARTED
    )
    assert resolved in server._watcher_tasks
    await asyncio.sleep(0.3)


async def _stop_real_watcher(root: Path) -> None:
    resolved = root.resolve()
    cleanup = server._stop_watcher(resolved)
    assert resolved not in server._watcher_tasks
    assert resolved not in server._watcher_stops
    if cleanup is not None:
        assert await asyncio.wait_for(
            asyncio.shield(cleanup),
            timeout=E2E_TIMEOUT_SECONDS,
        )
    assert await server._wait_for_watcher_cleanup(
        resolved,
        timeout_seconds=E2E_TIMEOUT_SECONDS,
    )
    assert resolved not in server._watcher_tasks
    assert resolved not in server._watcher_stops


async def _exercise_watcher_pause_coalescing(
    manager: JobManager,
    registry: ServiceRegistry,
    root: Path,
    slot: ProjectSlot,
) -> JobSnapshot:
    first_path = root / ".vault" / "adr" / "paused-first.md"
    second_path = root / ".vault" / "adr" / "paused-second.md"
    first_id: str | None = None
    running: JobSnapshot | None = None
    with registry.compute_lease(root) as lease:
        writer_lock = lease.runtime.vault_indexer._writer_lock
        assert writer_lock.acquire(blocking=False)
        try:
            first_id = _write_watched_document(first_path, root, "paused first")
            running = await _wait_for_watcher_job(
                manager,
                root,
                _watcher_attempt_owns_runtime,
                "watcher pause attempt never acquired production resources",
            )
            pause = manager.set_desired_state(running.id, DesiredJobState.PAUSED)
            assert pause.code == "pause_requested"
        finally:
            writer_lock.release()
    assert running is not None
    assert first_id is not None
    assert (
        await manager.wait_for_attempt(
            running.id,
            timeout_seconds=E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    paused = manager.get(running.id)
    assert paused is not None
    assert paused.state is JobState.PAUSED
    assert_released(paused, slot)
    assert slot.store.get_by_id(first_id) is None

    second_id = _write_watched_document(second_path, root, "paused second")
    await asyncio.sleep(0.5)
    nonterminal = [
        job for job in _watcher_jobs(manager, root) if not job.state.is_terminal
    ]
    assert [(job.id, job.state) for job in nonterminal] == [
        (paused.id, JobState.PAUSED)
    ]
    resume = manager.set_desired_state(paused.id, DesiredJobState.RUNNING)
    assert resume.code == "resume_requested"
    assert (
        await manager.wait_for_attempt(
            paused.id,
            timeout_seconds=E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    succeeded = manager.get(paused.id)
    assert succeeded is not None
    assert succeeded.state is JobState.SUCCEEDED
    assert succeeded.attempt.number == 2
    assert_released(succeeded, slot)
    assert slot.store.get_by_id(first_id) is not None
    assert slot.store.get_by_id(second_id) is not None
    return succeeded


async def _exercise_watcher_cancel_replacement(
    manager: JobManager,
    registry: ServiceRegistry,
    root: Path,
    slot: ProjectSlot,
    prior_job_id: str,
) -> JobSnapshot:
    third_path = root / ".vault" / "adr" / "cancelled-third.md"
    fourth_path = root / ".vault" / "adr" / "replacement-fourth.md"
    third_id: str | None = None
    running: JobSnapshot | None = None
    with registry.compute_lease(root) as lease:
        writer_lock = lease.runtime.vault_indexer._writer_lock
        assert writer_lock.acquire(blocking=False)
        try:
            third_id = _write_watched_document(third_path, root, "cancelled third")
            running = await _wait_for_watcher_job(
                manager,
                root,
                lambda snapshot: (
                    snapshot.id != prior_job_id
                    and _watcher_attempt_owns_runtime(snapshot)
                ),
                "watcher cancellation attempt never reached the writer boundary",
            )
            cancel = manager.set_desired_state(running.id, DesiredJobState.CANCELLED)
            assert cancel.code == "cancellation_requested"
        finally:
            writer_lock.release()
    assert running is not None
    assert third_id is not None
    assert (
        await manager.wait_for_attempt(
            running.id,
            timeout_seconds=E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    cancelled = manager.get(running.id)
    assert cancelled is not None
    assert cancelled.state is JobState.CANCELLED
    assert cancelled.timestamps.finished_at is not None
    assert_released(cancelled, slot)
    assert slot.store.get_by_id(third_id) is None

    fourth_id = _write_watched_document(fourth_path, root, "replacement fourth")
    replacement = await _wait_for_watcher_job(
        manager,
        root,
        lambda snapshot: (
            snapshot.id not in {cancelled.id, prior_job_id}
            and snapshot.state is JobState.SUCCEEDED
        ),
        "watcher did not schedule and finish replacement convergence",
    )
    assert replacement.timestamps.created_at >= cancelled.timestamps.finished_at + 0.8
    assert_released(replacement, slot)
    assert slot.store.get_by_id(third_id) is not None
    assert slot.store.get_by_id(fourth_id) is not None
    return replacement


@pytest.mark.timeout(300)
async def test_watcher_coalesces_replaces_stops_and_closes_store_safely(
    tmp_path: Path,
    _e2e_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """Drive pause, replacement, explicit stop, and safe store closure."""
    registry, manager = _e2e_runtime
    root = (tmp_path / "watcher-shutdown").resolve()
    (root / ".vault").mkdir(parents=True)
    slot = registry.peek_project(root)

    await _start_real_watcher(root)
    paused_generation = await _exercise_watcher_pause_coalescing(
        manager,
        registry,
        root,
        slot,
    )
    replacement = await _exercise_watcher_cancel_replacement(
        manager,
        registry,
        root,
        slot,
        paused_generation.id,
    )
    assert replacement.id != paused_generation.id
    assert root in server._watcher_tasks

    await _stop_real_watcher(root)
    assert manager.active() == []
    assert slot.ref_count == 0
    registry.close_project(root)
    health = registry.health()
    assert health["project_count"] == 0
    assert str(root) not in health["projects"]
