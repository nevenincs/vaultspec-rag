"""The real runtime the service job-control scenarios share.

The pause/restart scenarios and the watcher scenario drive the same
production registry, job manager, and embedding model, and both close on
the same question: did the attempt actually let go of everything it
borrowed. That runtime and that assertion live here once.

Everything else stays with the scenario that owns it. A helper only the
watcher drives, or only the restart sequence drives, is not shared
scaffolding just because it once sat in the same file.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ... import jobs, server
from ...concurrency import limiter_stats, reset_limiters
from ...config._settings import get_config
from ...job_models import DesiredJobState, JobOutcomeStatus
from ...registry import get_registry, reset_registry

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from ...embeddings import EmbeddingModel
    from ...job_manager.manager import JobManager
    from ...job_models import JobSnapshot
    from ...service import ProjectSlot, ServiceRegistry

__all__ = [
    "E2E_POLL_SECONDS",
    "E2E_TIMEOUT_SECONDS",
    "_e2e_runtime",
    "assert_released",
]

#: The budget a scenario allows any single real attempt to reach a state.
E2E_TIMEOUT_SECONDS = 180.0

#: How often a scenario re-reads a snapshot while waiting on one.
E2E_POLL_SECONDS = 0.01


@pytest.fixture(name="_e2e_runtime")
async def _e2e_runtime(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    clean_config: None,
) -> AsyncGenerator[tuple[ServiceRegistry, JobManager]]:
    """Provide one real model, registry, manager, and bounded teardown."""
    del clean_config
    jobs.reset()
    reset_limiters()
    get_config(
        {
            "data_dir": ".service-job-control-e2e",
            "status_dir": str(tmp_path / "status"),
            "qdrant_url": None,
            "qdrant_server": False,
            "local_only": True,
            "index_support_profile": "embedded-local",
            "sparse_enabled": False,
            "reranker_enabled": False,
            "embedding_dimension": embedding_model.dimension,
            "embedding_batch_size": 8,
            "embedding_encode_batch_size": 1,
            "index_segment_max_chunks": 8,
            "index_queue_max_chunks": 16,
            "index_job_concurrency": 1,
            "job_shutdown_timeout_seconds": E2E_TIMEOUT_SECONDS,
            "watch_enabled": True,
            "watch_retry_base_seconds": 1.0,
            "watch_retry_max_seconds": 1.0,
            "watch_retry_jitter_fraction": 0.0,
        }
    )
    # ``get_registry()`` is a process-wide singleton, so a module whose
    # teardown was cut short hands this one its still-open project slots.
    # Claim a fresh registry instead of inheriting whatever the run left
    # behind: closing an ownerless registry is the cleanup its owner skipped,
    # and it makes this fixture's starting state a product of its own action
    # rather than a bet on every earlier module having tidied up.
    reset_registry()
    # ``get_registry()`` rebinds the server package's cached ``_registry``
    # alias as it rebuilds, so the test, the watcher, and the job dispatcher
    # all drive one registry rather than double-opening the same
    # non-parallel-safe local store from two.
    registry = get_registry()
    registry._model = embedding_model
    manager = jobs.get_job_manager()
    try:
        yield registry, manager
    finally:
        try:
            watcher_cleanup = server._stop_all_watchers()
            if watcher_cleanup:
                assert all(await asyncio.gather(*watcher_cleanup))
            assert await server._wait_for_watcher_cleanup(
                timeout_seconds=E2E_TIMEOUT_SECONDS
            )
            owned_managers = {manager, jobs.get_job_manager()}
            for owned_manager in owned_managers:
                for snapshot in owned_manager.active():
                    outcome = owned_manager.set_desired_state(
                        snapshot.id,
                        DesiredJobState.CANCELLED,
                    )
                    assert outcome.status is not JobOutcomeStatus.ERROR
                for snapshot in owned_manager.active():
                    if snapshot.runtime.task_active:
                        joined = await owned_manager.wait_for_attempt(
                            snapshot.id,
                            timeout_seconds=E2E_TIMEOUT_SECONDS,
                        )
                        assert joined.code == "attempt_released"
                assert owned_manager.active() == []
        finally:
            # Release the process-global singletons even when a drain
            # assertion above fails. These assertions report on the test that
            # just ran; letting one of them skip the release turns a single
            # failure into a setup error for every test that follows it.
            #
            # Drop the singleton rather than closing it in place: ``close_all``
            # latches ``_shutting_down`` and only ``prepare_startup`` clears it,
            # so a closed-but-retained registry makes every later
            # ``get_registry()`` hand back an instance that raises on the first
            # slot it is asked for. ``reset_registry`` closes this one and clears
            # the reference, so the next caller builds a live registry.
            reset_registry()
            jobs.reset()
            reset_limiters()


def assert_released(snapshot: JobSnapshot, slot: ProjectSlot) -> None:
    """Assert an attempt gave back every runtime handle and admission token."""
    assert snapshot.runtime.task_active is False
    assert snapshot.runtime.worker_active is False
    assert snapshot.resources.index_capacity_held is False
    assert snapshot.resources.project_lease_held is False
    assert snapshot.resources.writer_lock_held is False
    assert snapshot.resources.pipeline_active is False
    assert slot.ref_count == 0
    # Encode-bearing jobs borrow the machine-wide encode admission slot;
    # the index partition must stay unborrowed either way.
    assert limiter_stats()["encode"] == {
        "total_tokens": 1,
        "borrowed_tokens": 0,
        "waiting": 0,
    }
    index_stats = limiter_stats()["index"]
    assert index_stats["borrowed_tokens"] == 0
    assert index_stats["waiting"] == 0
