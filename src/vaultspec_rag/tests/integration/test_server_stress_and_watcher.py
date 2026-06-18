"""Stress testing and filesystem watcher integration tests.

Tests concurrent reads and writes, SQLite lock constraints,
and the real watch files auto-reindexing loop.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING

import pytest

from ... import CodebaseIndexer, VaultIndexer, VaultStore

if TYPE_CHECKING:
    from pathlib import Path

    from ...embeddings import EmbeddingModel

from ...graph_cache import GraphCache
from ...progress import NullProgressReporter
from ...store import VaultStoreLockedError
from ...watcher import watch_and_reindex

pytestmark = [pytest.mark.integration]


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
                    query_vector=[0.0] * 1024,
                    _query_text="blocking test",
                    limit=1,
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


@pytest.mark.asyncio
async def test_watcher_detects_and_indexes_file(
    tmp_path: Path, embedding_model: EmbeddingModel
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

    # 2. Setup RAG components
    store = VaultStore(tmp_path)
    vault_indexer: VaultIndexer = VaultIndexer(tmp_path, embedding_model, store)
    code_indexer: CodebaseIndexer = CodebaseIndexer(tmp_path, embedding_model, store)
    graph_cache = GraphCache()

    # Build the initial index so the table exists
    vault_indexer.full_index(reporter=NullProgressReporter())

    stop_event = asyncio.Event()

    # 3. Start the watcher task
    watcher_task = asyncio.create_task(
        watch_and_reindex(
            root_dir=tmp_path,
            vault_dir=vault_dir,
            vault_indexer=vault_indexer,
            code_indexer=code_indexer,
            stop_event=stop_event,
            graph_cache=graph_cache,
            debounce=50,  # Fast debounce (50ms)
            cooldown=0.1,  # Fast cooldown (100ms)
        )
    )

    try:
        # Give watcher a moment to startup
        await asyncio.sleep(0.2)

        # Confirm we cannot find the new document yet
        q_vec = embedding_model.encode_query("concurrency adversarial stress").tolist()
        results = store.hybrid_search(
            query_vector=q_vec, _query_text="concurrency adversarial stress", limit=10
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
                query_vector=q_vec,
                _query_text="concurrency adversarial stress",
                limit=10,
            )
            if any("adversarial" in r.get("content", "") for r in results):
                break
        else:
            pytest.fail(
                "Watcher failed to trigger and index the new document within timeout"
            )

    finally:
        # Stop the watcher task gracefully
        stop_event.set()
        await watcher_task
        store.close()


def _build_watched_code_project(
    tmp_path: Path, model: EmbeddingModel
) -> tuple[VaultStore, VaultIndexer, CodebaseIndexer, Path, Path]:
    """Index a minimal vault + two source files; return store, indexers, files."""
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

    store = VaultStore(tmp_path)
    vault_indexer = VaultIndexer(tmp_path, model, store)
    code_indexer = CodebaseIndexer(tmp_path, model, store)
    vault_indexer.full_index(reporter=NullProgressReporter())
    code_indexer.full_index(reporter=NullProgressReporter())
    return store, vault_indexer, code_indexer, trigger, target


@pytest.mark.asyncio
async def test_watcher_evicts_cooldown_suppressed_delete(
    tmp_path: Path, embedding_model: EmbeddingModel
) -> None:
    """A deletion suppressed by the cooldown is reconciled on a quiet tree.

    Regression for the stranded-pending bug: prime the per-source cooldown with
    an edit, delete a second file inside the cooldown window, then leave the
    tree quiet. The idle tick must flush the carried-forward deletion once the
    cooldown elapses - without any further filesystem event. The poll window
    deliberately exceeds cooldown + idle-tick interval.
    """
    import asyncio

    cooldown = 2.0
    store, _vi, code_indexer, trigger, target = _build_watched_code_project(
        tmp_path, embedding_model
    )
    target_rel = str(target.relative_to(tmp_path)).replace("\\", "/")
    assert code_indexer._get_chunk_ids_for_files({target_rel}), "target not indexed"

    stop_event = asyncio.Event()
    watcher_task = asyncio.create_task(
        watch_and_reindex(
            root_dir=tmp_path,
            vault_dir=tmp_path / ".vault",
            vault_indexer=_vi,
            code_indexer=code_indexer,
            stop_event=stop_event,
            graph_cache=GraphCache(),
            debounce=50,
            cooldown=cooldown,
        )
    )
    try:
        await asyncio.sleep(0.3)
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
        stop_event.set()
        await watcher_task
        store.close()


@pytest.mark.asyncio
async def test_watcher_idle_tick_does_not_bypass_cooldown(
    tmp_path: Path, embedding_model: EmbeddingModel
) -> None:
    """The idle tick must not reconcile a change before the cooldown elapses.

    Enabling the idle yield must not weaken the anti-thrash cooldown: a deletion
    that lands inside a long cooldown window stays pending (chunks still present)
    until the window elapses, even though idle ticks fire meanwhile.
    """
    import asyncio

    cooldown = 6.0
    store, _vi, code_indexer, trigger, target = _build_watched_code_project(
        tmp_path, embedding_model
    )
    target_rel = str(target.relative_to(tmp_path)).replace("\\", "/")

    stop_event = asyncio.Event()
    watcher_task = asyncio.create_task(
        watch_and_reindex(
            root_dir=tmp_path,
            vault_dir=tmp_path / ".vault",
            vault_indexer=_vi,
            code_indexer=code_indexer,
            stop_event=stop_event,
            graph_cache=GraphCache(),
            debounce=50,
            cooldown=cooldown,
        )
    )
    try:
        await asyncio.sleep(0.3)
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
        stop_event.set()
        await watcher_task
        store.close()
