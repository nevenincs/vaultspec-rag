"""Stress testing and filesystem watcher integration tests.

Tests concurrent reads and writes, SQLite lock constraints,
and the real watch files auto-reindexing loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from ... import jobs, server
from ..._store_search import HybridSearchRequest
from ...concurrency import get_encode_limiter, reset_limiters
from ...config._settings import get_config
from ...indexer._vault_prep import prepare_document
from ...job_models import (
    DesiredJobState,
    JobOutcomeStatus,
    JobSnapshot,
    JobState,
    ResumeStrategy,
)
from ...progress import NullProgressReporter
from ...server import WatcherStartOutcome
from ...server import _watcher as watcher_lifecycle
from ...store_runtime import VaultStore
from ...watcher_retry import WatcherRetryPolicy, WatcherSource
from ..benchmarks.bench_large_index_resilience import (
    CorpusSpec,
    measure_full_index,
    prepare_corpus,
    retain_benchmark_evidence,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from sentence_transformers import CrossEncoder

    from ...embeddings import EmbeddingModel
    from ...job_manager.manager import JobManager
    from ...service import ProjectSlot, ServiceRegistry

from ..._store_locks import VaultStoreLockedError

pytestmark = [pytest.mark.integration]

_WATCHER_WAIT_SECONDS = 60.0
_WATCHER_POLL_SECONDS = 0.02


@pytest.fixture
async def managed_watcher_runtime(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    clean_config: None,
) -> AsyncGenerator[tuple[ServiceRegistry, JobManager]]:
    """Isolate the canonical manager, registry, and watcher ownership."""
    del clean_config
    jobs.reset()
    reset_limiters()
    get_config(
        {
            "status_dir": str(tmp_path / "status"),
            "qdrant_url": None,
            "qdrant_server": False,
            "local_only": True,
            "reranker_enabled": False,
            "embedding_dimension": embedding_model.dimension,
            "index_job_concurrency": 1,
            "job_shutdown_timeout_seconds": _WATCHER_WAIT_SECONDS,
            "watch_enabled": True,
            "watch_retry_base_seconds": 2.0,
            "watch_retry_max_seconds": 2.0,
            "watch_retry_jitter_fraction": 0.0,
            "watch_circuit_failure_threshold": 2,
        }
    )
    registry = server._registry
    registry.prepare_startup()
    registry._model = embedding_model  # pyright: ignore[reportPrivateUsage]
    assert (  # pyright: ignore[reportPrivateUsage]
        registry.health()["project_count"],
        bool(server._watcher_tasks),
        bool(watcher_lifecycle._watcher_drains),
    ) == (0, False, False)
    manager = jobs.get_job_manager()

    yield registry, manager

    cleanup_tasks = server._stop_all_watchers()
    if cleanup_tasks:
        cleanup_results = await asyncio.gather(*cleanup_tasks)
        assert all(cleanup_results)
    assert await server._wait_for_watcher_cleanup(timeout_seconds=_WATCHER_WAIT_SECONDS)
    for snapshot in manager.active():
        outcome = manager.set_desired_state(
            snapshot.id,
            DesiredJobState.CANCELLED,
        )
        assert outcome.status is not JobOutcomeStatus.ERROR
    for snapshot in manager.active():
        if snapshot.runtime.task_active:
            joined = await manager.wait_for_attempt(
                snapshot.id,
                timeout_seconds=_WATCHER_WAIT_SECONDS,
            )
            assert joined.code == "attempt_released"
    assert not manager.active()
    for project in registry.health()["projects"]:
        registry.close_project(Path(project))
    jobs.reset()
    reset_limiters()


def _watcher_jobs(manager: JobManager, root: Path) -> list[JobSnapshot]:
    """Return exact watcher-origin snapshots for one production root."""
    resolved = str(root.resolve())
    return [
        snapshot
        for snapshot in manager.list_jobs()
        if snapshot.initiator.kind == "watcher"
        and snapshot.spec.project_root == resolved
    ]


def _watcher_attempt_owns_runtime(snapshot: JobSnapshot) -> bool:
    """Observe the complete live ownership tuple without deriving state."""
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


async def _wait_for_watcher_job(
    manager: JobManager,
    root: Path,
    predicate: Callable[[JobSnapshot], bool],
    description: str,
) -> JobSnapshot:
    """Poll canonical snapshots until one real watcher job matches."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _WATCHER_WAIT_SECONDS
    while loop.time() < deadline:
        for snapshot in _watcher_jobs(manager, root):
            if predicate(snapshot):
                return snapshot
        await asyncio.sleep(_WATCHER_POLL_SECONDS)
    snapshots = _watcher_jobs(manager, root)
    raise AssertionError(f"{description}; last snapshots={snapshots!r}")


async def _start_watcher(root: Path, *, cooldown: float) -> None:
    """Start the real server watcher and wait for watchfiles intake."""
    resolved = root.resolve()
    assert (
        server._ensure_watcher(
            resolved,
            debounce_ms=50,
            cooldown_s=cooldown,
        )
        is WatcherStartOutcome.STARTED
    )
    assert resolved in server._watcher_tasks
    await asyncio.sleep(0.3)


async def _stop_watcher(root: Path) -> None:
    """Explicitly disable intake and join its production cleanup owner."""
    resolved = root.resolve()
    cleanup = server._stop_watcher(resolved)
    if cleanup is not None:
        assert await asyncio.wait_for(
            asyncio.shield(cleanup),
            timeout=_WATCHER_WAIT_SECONDS,
        )
    assert await server._wait_for_watcher_cleanup(
        resolved,
        timeout_seconds=_WATCHER_WAIT_SECONDS,
    )
    _assert_watcher_intake_disabled(resolved)
    assert resolved not in watcher_lifecycle._watcher_drains  # pyright: ignore[reportPrivateUsage]


def _assert_watcher_intake_disabled(root: Path) -> None:
    """Require the public enabled-intake bookkeeping to be empty."""
    assert (root in server._watcher_tasks, root in server._watcher_stops) == (
        False,
        False,
    )


def _write_vault_document(path: Path, marker: str) -> str:
    """Write one valid ADR and return its production document ID."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "tags: ['#adr', '#watcher-control']\n"
        "---\n"
        f"# {marker}\n\n"
        f"alpha beta watcher control {marker}\n",
        encoding="utf-8",
    )
    document = prepare_document(path, path.parents[2])
    assert document is not None
    return document.id


def _load_watcher_state(path: Path) -> dict[str, object]:
    parsed: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return cast("dict[str, object]", parsed)


def _try_load_watcher_state(path: Path) -> dict[str, object] | None:
    try:
        return _load_watcher_state(path)
    except (FileNotFoundError, PermissionError):
        return None


async def _wait_for_watcher_state(
    path: Path,
    predicate: Callable[[dict[str, object]], bool],
    description: str,
) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + _WATCHER_WAIT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        state = _try_load_watcher_state(path)
        if state is not None and predicate(state):
            return state
        await asyncio.sleep(_WATCHER_POLL_SECONDS)
    raise AssertionError(f"{description}; last state={_try_load_watcher_state(path)!r}")


def _start_state_lock_holder(
    lock_path: Path,
    ready_path: Path,
    *,
    hold_seconds: float = 2.4,
) -> subprocess.Popen[str]:
    """Hold the production cross-process state lock without test doubles."""
    script = "\n".join(
        (
            "import sys, time",
            "from pathlib import Path",
            "from vaultspec_rag._store_locks import FileLock",
            "lock = FileLock(Path(sys.argv[1]))",
            "assert lock.acquire()",
            "Path(sys.argv[2]).write_text('ready', encoding='utf-8')",
            "time.sleep(float(sys.argv[3]))",
            "lock.release()",
        )
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(lock_path),
            str(ready_path),
            str(hold_seconds),
        ],
        text=True,
    )


async def _wait_for_path(path: Path) -> None:
    await _wait_for_watcher_state(
        path,
        lambda _state: True,
        f"watcher state path was not created: {path}",
    )


async def _wait_for_code_payload(
    slot: ProjectSlot,
    *,
    path: str,
    expected_content: str,
) -> None:
    from qdrant_client import models

    deadline = asyncio.get_running_loop().time() + _WATCHER_WAIT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        records, _offset = slot.store.client.scroll(
            collection_name=slot.store.CODE_TABLE_NAME,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="path",
                        match=models.MatchValue(value=path),
                    )
                ]
            ),
            limit=10,
            with_payload=["content"],
            with_vectors=False,
        )
        if any(
            expected_content in str((record.payload or {}).get("content", ""))
            for record in records
        ):
            return
        await asyncio.sleep(0.1)
    pytest.fail("watcher did not converge the expected code payload")


def _assert_watcher_resources_released(
    snapshot: JobSnapshot,
    slot: ProjectSlot,
) -> None:
    """Require canonical and physical watcher attempt ownership to be clear."""
    assert (
        snapshot.runtime.task_active,
        snapshot.runtime.worker_active,
        snapshot.resources.index_capacity_held,
        snapshot.resources.project_lease_held,
        snapshot.resources.writer_lock_held,
        snapshot.resources.pipeline_active,
        slot.ref_count,
    ) == (False, False, False, False, False, False, 0)
    assert slot.vault_indexer._writer_lock.acquire(  # pyright: ignore[reportPrivateUsage]
        blocking=False
    )
    slot.vault_indexer._writer_lock.release()  # pyright: ignore[reportPrivateUsage]


async def _pause_blocked_watcher_attempt(
    manager: JobManager,
    root: Path,
    slot: ProjectSlot,
    path: Path,
) -> tuple[JobSnapshot, str]:
    """Pause attempt one while it waits on the real writer lock."""
    writer_lock = slot.vault_indexer._writer_lock  # pyright: ignore[reportPrivateUsage]
    assert writer_lock.acquire(blocking=False)
    try:
        document_id = _write_vault_document(path, "pause-first-generation")
        running = await _wait_for_watcher_job(
            manager,
            root,
            _watcher_attempt_owns_runtime,
            "watcher attempt did not acquire its managed resources",
        )
        assert (running.attempt.number, slot.ref_count) == (1, 1)
        pause = manager.set_desired_state(running.id, DesiredJobState.PAUSED)
        assert pause.job is not None
        assert (pause.status, pause.job.state) == (
            JobOutcomeStatus.ACCEPTED,
            JobState.PAUSING,
        )
    finally:
        writer_lock.release()

    joined = await manager.wait_for_attempt(
        running.id,
        timeout_seconds=_WATCHER_WAIT_SECONDS,
    )
    paused = manager.get(running.id)
    assert paused is not None
    assert (joined.code, paused.state, paused.desired_state) == (
        "attempt_released",
        JobState.PAUSED,
        DesiredJobState.PAUSED,
    )
    _assert_watcher_resources_released(paused, slot)
    assert slot.store.get_by_id(document_id) is None
    return paused, document_id


async def _resume_blocked_watcher_and_stop(
    manager: JobManager,
    root: Path,
    slot: ProjectSlot,
    job_id: str,
) -> JobSnapshot:
    """Prove explicit stop waits for a naturally completing resumed attempt."""
    writer_lock = slot.vault_indexer._writer_lock  # pyright: ignore[reportPrivateUsage]
    assert writer_lock.acquire(blocking=False)
    cleanup: asyncio.Task[bool] | None = None
    try:
        resume = manager.set_desired_state(job_id, DesiredJobState.RUNNING)
        assert resume.status is JobOutcomeStatus.ACCEPTED
        resumed = await _wait_for_watcher_job(
            manager,
            root,
            lambda snapshot: all(
                (
                    snapshot.id == job_id,
                    snapshot.attempt.number == 2,
                    _watcher_attempt_owns_runtime(snapshot),
                )
            ),
            "resumed watcher attempt did not reacquire resources",
        )
        assert (
            resumed.attempt.resumed_from_attempt,
            resumed.attempt.resume_strategy,
        ) == (1, ResumeStrategy.RECONCILE)

        cleanup = server._stop_watcher(root)
        assert cleanup is not None
        _assert_watcher_intake_disabled(root)
        await asyncio.sleep(0.1)
        assert not cleanup.done()
        still_running = manager.get(job_id)
        assert still_running is not None
        assert (still_running.state, still_running.desired_state) == (
            JobState.RUNNING,
            DesiredJobState.RUNNING,
        )
    finally:
        writer_lock.release()

    assert cleanup is not None
    assert await asyncio.wait_for(
        asyncio.shield(cleanup),
        timeout=_WATCHER_WAIT_SECONDS,
    )
    assert await server._wait_for_watcher_cleanup(
        root,
        timeout_seconds=_WATCHER_WAIT_SECONDS,
    )
    succeeded = manager.get(job_id)
    assert succeeded is not None
    assert succeeded.state is JobState.SUCCEEDED
    return succeeded


async def _cancel_blocked_watcher_attempt(
    manager: JobManager,
    root: Path,
    slot: ProjectSlot,
    path: Path,
) -> tuple[JobSnapshot, str, float]:
    """Cancel attempt one while it waits on the real writer lock."""
    writer_lock = slot.vault_indexer._writer_lock  # pyright: ignore[reportPrivateUsage]
    assert writer_lock.acquire(blocking=False)
    try:
        document_id = _write_vault_document(path, "cancel-first-generation")
        running = await _wait_for_watcher_job(
            manager,
            root,
            _watcher_attempt_owns_runtime,
            "watcher attempt did not reach the real writer boundary",
        )
        requested_at = time.time()
        cancel = manager.set_desired_state(running.id, DesiredJobState.CANCELLED)
        assert cancel.job is not None
        assert (cancel.status, cancel.job.state) == (
            JobOutcomeStatus.ACCEPTED,
            JobState.CANCELLING,
        )
    finally:
        writer_lock.release()

    joined = await manager.wait_for_attempt(
        running.id,
        timeout_seconds=_WATCHER_WAIT_SECONDS,
    )
    cancelled = manager.get(running.id)
    assert cancelled is not None
    finished_at = cancelled.timestamps.finished_at
    assert finished_at is not None
    assert (
        joined.code,
        cancelled.state,
        finished_at >= requested_at,
    ) == ("attempt_released", JobState.CANCELLED, True)
    _assert_watcher_resources_released(cancelled, slot)
    assert slot.store.get_by_id(document_id) is None
    assert root in server._watcher_tasks
    assert not server._watcher_tasks[root].done()
    assert not server._watcher_stops[root].is_set()
    return cancelled, document_id, finished_at


class TestLocalConcurrencyLocks:
    """Verifies concurrency safety and locking policy in local file mode."""

    def test_local_mode_multi_process_raises_lock_error(self, tmp_path: Path) -> None:
        """Assert that two distinct VaultStore instances on the same path

        trigger VaultStoreLockedError.
        """
        store1 = VaultStore(tmp_path)
        try:
            # Second store must raise VaultStoreLockedError
            with pytest.raises(VaultStoreLockedError):
                VaultStore(tmp_path)
        finally:
            store1.close()

    def test_local_mode_in_process_concurrency_serialized(self, tmp_path: Path) -> None:
        """Assert that same-collection threads on one VaultStore instance

        are serialized via the collection's lock.
        """
        store = VaultStore(tmp_path)
        store.ensure_table()
        store.ensure_code_table()

        errors: list[Exception] = []
        search_started = threading.Event()
        search_finished = threading.Event()

        # Hold the vault collection lock in the main thread
        store._collection_locks[store.TABLE_NAME].acquire()

        def worker():
            search_started.set()
            try:
                # This should block until client lock is released
                store.hybrid_search(
                    HybridSearchRequest(
                        query_vector=[0.0] * 1024,
                        query_text="blocking test",
                        limit=1,
                    )
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                search_finished.set()

        thread = threading.Thread(target=worker)
        thread.start()

        search_started.wait(timeout=5)
        time.sleep(0.2)  # Give thread a moment to block on the lock

        assert thread.is_alive()
        assert not search_finished.is_set()

        # Release lock and assert the thread completes
        store._collection_locks[store.TABLE_NAME].release()
        thread.join(timeout=10)

        assert not thread.is_alive()
        assert not errors
        store.close()


class TestLargeIndexSearchHeadroom:
    """Concurrent code search remains live under bounded production load."""

    @pytest.mark.performance
    @pytest.mark.timeout(900)
    def test_search_completes_while_large_index_retains_cuda_headroom(
        self,
        tmp_path: Path,
        embedding_model: EmbeddingModel,
        shared_reranker: CrossEncoder,
    ) -> None:
        from concurrent.futures import ThreadPoolExecutor

        from ... import CodebaseIndexer, VaultSearcher
        from ..._gpu import load_torch

        root = tmp_path / "large-index-search-headroom"
        spec = CorpusSpec(files=256, chunks_per_file=3)
        prepare_corpus(root, spec)
        store = VaultStore(root)
        gpu_lock = threading.Lock()
        try:
            indexer = CodebaseIndexer(
                root,
                embedding_model,
                store,
                options=CodebaseIndexer.Options(gpu_lock=gpu_lock),
            )
            bootstrap = (
                root / "src" / "acceptance_workload" / "000" / ("module_000000.py")
            )
            indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths=[bootstrap],
                preflight=indexer.preflight_changed_paths([bootstrap]),
            )
            searcher = VaultSearcher(
                root,
                embedding_model,
                store,
                gpu_lock=gpu_lock,
                reranker=shared_reranker,
            )
            index_started = threading.Event()
            index_finished = threading.Event()

            def _index():
                index_started.set()
                try:
                    return measure_full_index(
                        indexer,
                        indexer.preflight_content(),
                        clean=False,
                    )
                finally:
                    index_finished.set()

            def _search(task: int) -> tuple[int, bool]:
                results = searcher.search_codebase(
                    f"acceptance workload value offset {task}",
                    top_k=5,
                )
                return len(results), index_finished.is_set()

            with ThreadPoolExecutor(max_workers=5) as pool:
                index_future = pool.submit(_index)
                assert index_started.wait(timeout=10.0)
                search_futures = [pool.submit(_search, task) for task in range(8)]
                search_outcomes = [future.result() for future in search_futures]
                measured = index_future.result()

            assert measured.result.total == spec.expected_chunks
            assert all(count > 0 for count, _finished in search_outcomes)
            assert any(not finished for _count, finished in search_outcomes), (
                "no search completed while bounded indexing was still progressing"
            )

            torch = load_torch()
            total_cuda_mb = float(
                torch.cuda.get_device_properties(0).total_memory / 1024**2
            )
            configured_fraction = float(get_config().index_cuda_allocator_fraction)
            required_headroom_mb = total_cuda_mb * (1.0 - configured_fraction)
            observed_headroom_mb = (
                total_cuda_mb - measured.resources.peak_cuda_reserved_mb
            )
            retained_headroom = observed_headroom_mb >= required_headroom_mb - 128.0
            retain_benchmark_evidence(
                "concurrent-search-headroom",
                {
                    "files": spec.files,
                    "chunks": measured.result.total,
                    "wall_seconds": measured.wall_seconds,
                    "resources": asdict(measured.resources),
                    "searches": len(search_outcomes),
                    "nonempty_searches": sum(
                        count > 0 for count, _finished in search_outcomes
                    ),
                    "searches_completed_before_index": sum(
                        not finished for _count, finished in search_outcomes
                    ),
                    "total_cuda_mb": total_cuda_mb,
                    "configured_allocator_fraction": configured_fraction,
                    "required_headroom_mb": required_headroom_mb,
                    "observed_headroom_mb": observed_headroom_mb,
                    "headroom_tolerance_mb": 128.0,
                    "checks": {"retained_reserved_headroom": retained_headroom},
                },
            )
            assert observed_headroom_mb >= required_headroom_mb - 128.0
        finally:
            store.close()


@pytest.mark.asyncio
async def test_watcher_detects_and_indexes_file(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    managed_watcher_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """Verify that writing a physical vault file triggers the watcher

    and updates search results.
    """
    # 1. Setup watched directories
    vault_dir: Path = tmp_path / ".vault"
    adr_dir: Path = vault_dir / "adr"
    adr_dir.mkdir(parents=True)

    # Write initial file to establish the table schema
    init_file: Path = adr_dir / "init.md"
    init_text = (
        "---\n"
        "tags: ['#adr', '#initial']\n"
        "date: '2026-06-05'\n"
        "related: []\n"
        "title: Init\n"
        "---\n"
        "# Init\n\n"
        "Initial body.\n"
    )
    init_file.write_text(init_text, encoding="utf-8")

    # 2. Setup the canonical registry-owned RAG components.
    registry, _manager = managed_watcher_runtime
    assert registry.model is embedding_model
    slot = registry.peek_project(tmp_path)
    store = slot.store

    # Build the initial index so the table exists
    slot.vault_indexer.full_index(reporter=NullProgressReporter())

    # 3. Start through the real server watcher owner.
    await _start_watcher(tmp_path, cooldown=0.1)

    try:
        # Confirm we cannot find the new document yet
        q_vec = embedding_model.encode_query("concurrency adversarial stress").tolist()
        results = store.hybrid_search(
            HybridSearchRequest(
                query_vector=q_vec,
                query_text="concurrency adversarial stress",
                limit=10,
            )
        )
        assert not any("adversarial" in r.get("content", "") for r in results)

        # 4. Write new document to disk
        new_file = adr_dir / "stress-test.md"
        new_text = (
            "---\n"
            "tags: ['#adr', '#adversarial']\n"
            "date: '2026-06-05'\n"
            "related: []\n"
            "title: Stress Test\n"
            "---\n"
            "# Stress Test\n\n"
            "This is a concurrency adversarial stress test of the policy.\n"
        )
        new_file.write_text(new_text, encoding="utf-8")

        # 5. Wait for watcher to detect, debounce, and trigger re-index
        for _ in range(30):  # Poll for up to 3 seconds
            await asyncio.sleep(0.1)
            results = store.hybrid_search(
                HybridSearchRequest(
                    query_vector=q_vec,
                    query_text="concurrency adversarial stress",
                    limit=10,
                )
            )
            if any("adversarial" in r.get("content", "") for r in results):
                break
        else:
            pytest.fail(
                "Watcher failed to trigger and index the new document within timeout"
            )

    finally:
        await _stop_watcher(tmp_path)


def _build_watched_code_project(
    tmp_path: Path,
    registry: ServiceRegistry,
) -> tuple[ProjectSlot, Path, Path]:
    """Index a minimal vault + two source files through the canonical slot."""
    vault_dir = tmp_path / ".vault"
    (vault_dir / "adr").mkdir(parents=True)
    (vault_dir / "adr" / "init.md").write_text(
        "---\ntags: ['#adr', '#initial']\ndate: '2026-06-18'\nrelated: []\n"
        "title: Init\n---\n# Init\n\nInitial body.\n",
        encoding="utf-8",
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    trigger = pkg / "trigger.py"
    trigger.write_text("def t():\n    return 1\n", encoding="utf-8")
    target = pkg / "uniquemod.py"
    target.write_text(
        "def zebrafish_marker():\n    return 'zebrafish-unique-token'\n",
        encoding="utf-8",
    )

    slot = registry.peek_project(tmp_path)
    slot.vault_indexer.full_index(reporter=NullProgressReporter())
    slot.code_indexer.full_index(
        reporter=NullProgressReporter(),
        preflight=slot.code_indexer.preflight_content(),
    )
    return slot, trigger, target


@pytest.mark.asyncio
async def test_watcher_evicts_cooldown_suppressed_delete(
    tmp_path: Path,
    managed_watcher_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """A deletion suppressed by the cooldown is reconciled on a quiet tree.

    Regression for the stranded-pending bug: prime the per-source cooldown with
    an edit, delete a second file inside the cooldown window, then leave the
    tree quiet. The idle tick must flush the carried-forward deletion once the
    cooldown elapses - without any further filesystem event. The poll window
    deliberately exceeds cooldown + idle-tick interval.
    """
    cooldown = 2.0
    registry, _manager = managed_watcher_runtime
    slot, trigger, target = _build_watched_code_project(tmp_path, registry)
    code_indexer = slot.code_indexer
    target_rel = str(target.relative_to(tmp_path)).replace("\\", "/")
    assert code_indexer._get_chunk_ids_for_files({target_rel}), "target not indexed"

    await _start_watcher(tmp_path, cooldown=cooldown)
    try:
        # Prime the cooldown with an unrelated edit so the deletion that
        # follows lands inside the cooldown window.
        trigger.write_text("def t():\n    return 2\n", encoding="utf-8")
        await asyncio.sleep(0.8)
        target.unlink()

        evicted = False
        # cooldown (2s) + idle tick (1s) + generous margin; no further FS events.
        for _ in range(120):  # up to 12s
            await asyncio.sleep(0.1)
            if not code_indexer._get_chunk_ids_for_files({target_rel}):
                evicted = True
                break
        assert evicted, "idle tick did not flush the cooldown-suppressed deletion"
    finally:
        await _stop_watcher(tmp_path)


@pytest.mark.asyncio
async def test_watcher_idle_tick_does_not_bypass_cooldown(
    tmp_path: Path,
    managed_watcher_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """The idle tick must not reconcile a change before the cooldown elapses.

    Enabling the idle yield must not weaken the anti-thrash cooldown: a deletion
    that lands inside a long cooldown window stays pending (chunks still present)
    until the window elapses, even though idle ticks fire meanwhile.
    """
    cooldown = 6.0
    registry, _manager = managed_watcher_runtime
    slot, trigger, target = _build_watched_code_project(tmp_path, registry)
    code_indexer = slot.code_indexer
    target_rel = str(target.relative_to(tmp_path)).replace("\\", "/")

    await _start_watcher(tmp_path, cooldown=cooldown)
    try:
        trigger.write_text("def t():\n    return 2\n", encoding="utf-8")
        await asyncio.sleep(0.8)
        target.unlink()
        # Several idle ticks fire in this window, but the cooldown (6s) is far
        # from elapsed, so the deletion must remain unreconciled.
        await asyncio.sleep(2.5)
        assert code_indexer._get_chunk_ids_for_files({target_rel}), (
            "idle tick bypassed the cooldown and reindexed early"
        )
    finally:
        await _stop_watcher(tmp_path)


@pytest.mark.asyncio
async def test_watcher_pause_coalesces_and_explicit_stop_joins_cleanup(
    tmp_path: Path,
    managed_watcher_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """Paused dirtiness stays on one job and stop joins its resumed attempt."""
    registry, manager = managed_watcher_runtime
    root = tmp_path.resolve()
    slot = registry.peek_project(root)
    first_path = root / ".vault" / "adr" / "first-paused.md"
    second_path = root / ".vault" / "adr" / "second-paused.md"

    await _start_watcher(root, cooldown=0.0)
    paused, first_id = await _pause_blocked_watcher_attempt(
        manager,
        root,
        slot,
        first_path,
    )

    second_id = _write_vault_document(second_path, "pause-second-generation")
    await asyncio.sleep(0.5)
    active = [
        snapshot
        for snapshot in _watcher_jobs(manager, root)
        if not snapshot.state.is_terminal
    ]
    assert [(snapshot.id, snapshot.state) for snapshot in active] == [
        (paused.id, JobState.PAUSED)
    ]

    succeeded = await _resume_blocked_watcher_and_stop(
        manager,
        root,
        slot,
        paused.id,
    )
    assert (
        succeeded.attempt.number,
        succeeded.attempt.resumed_from_attempt,
    ) == (2, 1)
    _assert_watcher_resources_released(succeeded, slot)
    assert (
        slot.store.get_by_id(first_id) is not None,
        slot.store.get_by_id(second_id) is not None,
    ) == (True, True)
    assert root not in watcher_lifecycle._watcher_drains  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_watcher_cancel_preserves_dirtiness_and_submits_replacement(
    tmp_path: Path,
    managed_watcher_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """Cancellation leaves intake enabled and converges through a new job."""
    registry, manager = managed_watcher_runtime
    root = tmp_path.resolve()
    slot = registry.peek_project(root)
    first_path = root / ".vault" / "adr" / "first-cancelled.md"
    second_path = root / ".vault" / "adr" / "second-cancelled.md"

    await _start_watcher(root, cooldown=0.0)
    cancelled, first_id, cancelled_finished_at = await _cancel_blocked_watcher_attempt(
        manager,
        root,
        slot,
        first_path,
    )

    second_id = _write_vault_document(second_path, "cancel-second-generation")
    replacement = await _wait_for_watcher_job(
        manager,
        root,
        lambda snapshot: (
            snapshot.id != cancelled.id and snapshot.state is JobState.SUCCEEDED
        ),
        "watcher did not submit and complete a replacement convergence job",
    )
    assert (
        replacement.initiator.kind,
        replacement.spec,
        replacement.timestamps.created_at >= cancelled_finished_at + 0.8,
    ) == ("watcher", cancelled.spec, True)
    assert {snapshot.id for snapshot in _watcher_jobs(manager, root)} == {
        cancelled.id,
        replacement.id,
    }
    _assert_watcher_resources_released(replacement, slot)
    assert (
        slot.store.get_by_id(first_id) is not None,
        slot.store.get_by_id(second_id) is not None,
        root in server._watcher_tasks,
    ) == (True, True, True)

    await _stop_watcher(root)


@pytest.mark.asyncio
async def test_watcher_failure_is_bounded_and_restart_converges(
    tmp_path: Path,
    managed_watcher_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """A real store failure opens durable retry state; restart converges it."""
    registry, manager = managed_watcher_runtime
    root = tmp_path.resolve()
    slot, _trigger, target = _build_watched_code_project(root, registry)
    relative = str(target.relative_to(root)).replace("\\", "/")
    state_path = root / get_config().data_dir / "watcher-retry" / "code.json"

    await _start_watcher(root, cooldown=0.0)
    try:
        slot.store.close()
        target.write_text(
            'def zebrafish_marker():\n    return "failed-generation"\n',
            encoding="utf-8",
        )
        failed = await _wait_for_watcher_job(
            manager,
            root,
            lambda snapshot: snapshot.state is JobState.FAILED,
            "real store failure did not fail the managed watcher job",
        )
        durable = await _wait_for_watcher_state(
            state_path,
            lambda state: state.get("consecutive_failures") == 1,
            "watcher failure was not durably classified",
        )
        assert (
            failed.state,
            durable["circuit_state"],
            durable["convergence_pending"],
            durable["attempt_generation"],
        ) == (JobState.FAILED, "open", True, None)
    finally:
        await _stop_watcher(root)

    registry.close_project(root)
    recovered_slot = registry.peek_project(root)
    await _start_watcher(root, cooldown=0.0)
    try:
        target.write_text(
            'def zebrafish_marker():\n    return "restart-converged"\n',
            encoding="utf-8",
        )
        await _wait_for_code_payload(
            recovered_slot,
            path=relative,
            expected_content="restart-converged",
        )
        settled = await _wait_for_watcher_state(
            state_path,
            lambda state: state.get("convergence_pending") is False,
            "restart did not settle durable convergence",
        )
        assert (settled["circuit_state"], settled["consecutive_failures"]) == (
            "closed",
            0,
        )
    finally:
        await _stop_watcher(root)


@pytest.mark.asyncio
async def test_watcher_retries_intent_after_real_state_lock_contention(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    managed_watcher_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """A process-held state lock delays intake without losing durable intent."""
    registry, _manager = managed_watcher_runtime
    root = tmp_path.resolve()
    _slot, _trigger, target = _build_watched_code_project(root, registry)
    state_path = root / get_config().data_dir / "watcher-retry" / "code.json"
    ready_path = root / "watcher-state-lock-ready.marker"
    holder: subprocess.Popen[str] | None = None

    await _start_watcher(root, cooldown=0.0)
    try:
        await _wait_for_path(state_path)
        holder = _start_state_lock_holder(
            state_path.with_name(f"{state_path.name}.lock"),
            ready_path,
        )
        deadline = asyncio.get_running_loop().time() + 10.0
        while not ready_path.exists() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.02)
        assert ready_path.exists()
        with caplog.at_level(logging.WARNING, logger="vaultspec_rag.watcher"):
            target.write_text(
                'def zebrafish_marker():\n    return "lock-contended"\n',
                encoding="utf-8",
            )
            ticks = 0
            while (
                "service.watcher event=state_transaction_retry" not in caplog.text
                and ticks < 200
            ):
                await asyncio.sleep(0.02)
                ticks += 1
        assert ticks >= 20
        cleanup = server._stop_watcher(root)
        assert cleanup is not None
        assert await asyncio.wait_for(asyncio.shield(cleanup), timeout=10.0)
        durable = _load_watcher_state(state_path)
        assert durable["convergence_pending"] is True
    finally:
        if root in server._watcher_tasks:
            await _stop_watcher(root)
        if holder is not None and holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=5.0)

    await _start_watcher(root, cooldown=0.0)
    try:
        slot = registry.peek_project(root)
        await _wait_for_code_payload(
            slot,
            path=str(target.relative_to(root)).replace("\\", "/"),
            expected_content="lock-contended",
        )
        settled = await _wait_for_watcher_state(
            state_path,
            lambda state: state.get("convergence_pending") is False,
            "replacement watcher did not settle contended intent",
        )
        assert settled["circuit_state"] == "closed"
    finally:
        await _stop_watcher(root)


@pytest.mark.asyncio
async def test_watcher_cancellation_releases_real_admitted_claim(
    tmp_path: Path,
    managed_watcher_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """Operator cancellation settles the admitted durable generation as dirty."""
    registry, manager = managed_watcher_runtime
    root = tmp_path.resolve()
    _slot, _trigger, target = _build_watched_code_project(root, registry)
    # Encode-bearing watcher jobs wait on the machine-wide encode
    # admission slot, so that is the limiter to saturate to hold the
    # admitted attempt short of its worker thread.
    limiter = get_encode_limiter()
    borrowers = [object() for _ in range(int(limiter.total_tokens))]
    for borrower in borrowers:
        await limiter.acquire_on_behalf_of(borrower)
    state_path = root / get_config().data_dir / "watcher-retry" / "code.json"

    await _start_watcher(root, cooldown=0.0)
    try:
        target.write_text(
            'def zebrafish_marker():\n    return "cancel-admitted"\n',
            encoding="utf-8",
        )
        active_state = await _wait_for_watcher_state(
            state_path,
            lambda state: isinstance(state.get("attempt_generation"), int),
            "watcher never durably admitted a convergence generation",
        )
        running = await _wait_for_watcher_job(
            manager,
            root,
            lambda snapshot: snapshot.runtime.task_active,
            "manager did not own the admitted watcher attempt",
        )
        cancelled = manager.set_desired_state(
            running.id,
            DesiredJobState.CANCELLED,
        )
        assert cancelled.status is JobOutcomeStatus.ACCEPTED
    finally:
        for borrower in borrowers:
            limiter.release_on_behalf_of(borrower)

    terminal = await _wait_for_watcher_job(
        manager,
        root,
        lambda snapshot: snapshot.state is JobState.CANCELLED,
        "managed watcher cancellation was not acknowledged",
    )
    interrupted = await _wait_for_watcher_state(
        state_path,
        lambda state: state.get("attempt_generation") is None,
        "cancelled manager attempt retained its durable claim",
    )
    assert (
        terminal.id,
        active_state["attempt_generation"] is not None,
        interrupted["convergence_pending"],
        interrupted["unscoped_required"],
        interrupted["consecutive_failures"],
    ) == (running.id, True, True, True, 0)
    await _stop_watcher(root)


@pytest.mark.asyncio
async def test_watcher_refreshes_intent_committed_by_retiring_policy(
    tmp_path: Path,
    managed_watcher_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """Idle refresh observes dirty state committed by another policy owner."""
    registry, _manager = managed_watcher_runtime
    root = tmp_path.resolve()
    slot, _trigger, target = _build_watched_code_project(root, registry)
    relative = str(target.relative_to(root)).replace("\\", "/")
    target.write_text(
        'def zebrafish_marker():\n    return "retiring-policy-intent"\n',
        encoding="utf-8",
    )
    await _start_watcher(root, cooldown=0.0)
    try:
        state_path = root / get_config().data_dir / "watcher-retry" / "code.json"
        await _wait_for_path(state_path)
        retiring = WatcherRetryPolicy.for_root(root, WatcherSource.CODE)
        await asyncio.to_thread(retiring.mark_convergence_pending)
        await _wait_for_code_payload(
            slot,
            path=relative,
            expected_content="retiring-policy-intent",
        )
        settled = await _wait_for_watcher_state(
            state_path,
            lambda state: state.get("convergence_pending") is False,
            "idle refresh did not settle external durable intent",
        )
        assert settled["attempt_generation"] is None
    finally:
        await _stop_watcher(root)


@pytest.mark.asyncio
async def test_watcher_startup_retries_real_state_lock_contention(
    tmp_path: Path,
    managed_watcher_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """Canonical watcher startup survives another process holding state lock."""
    registry, _manager = managed_watcher_runtime
    root = tmp_path.resolve()
    slot, _trigger, target = _build_watched_code_project(root, registry)
    relative = str(target.relative_to(root)).replace("\\", "/")
    target.write_text(
        'def zebrafish_marker():\n    return "startup-contention"\n',
        encoding="utf-8",
    )
    retiring = WatcherRetryPolicy.for_root(root, WatcherSource.CODE)
    retiring.mark_convergence_pending()
    state_path = root / get_config().data_dir / "watcher-retry" / "code.json"
    ready_path = root / "watcher-startup-lock-ready.marker"
    holder = _start_state_lock_holder(
        state_path.with_name(f"{state_path.name}.lock"),
        ready_path,
    )
    try:
        deadline = asyncio.get_running_loop().time() + 10.0
        while not ready_path.exists() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.02)
        assert ready_path.exists()
        await _start_watcher(root, cooldown=0.0)
        await asyncio.sleep(0.1)
        assert not server._watcher_tasks[root].done()
        await _wait_for_code_payload(
            slot,
            path=relative,
            expected_content="startup-contention",
        )
        await asyncio.to_thread(holder.wait, 10.0)
        assert holder.returncode == 0
        settled = await _wait_for_watcher_state(
            state_path,
            lambda state: state.get("convergence_pending") is False,
            "startup contention did not settle durable intent",
        )
        assert settled["circuit_state"] == "closed"
    finally:
        if root in server._watcher_tasks:
            await _stop_watcher(root)
        if holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=5.0)
