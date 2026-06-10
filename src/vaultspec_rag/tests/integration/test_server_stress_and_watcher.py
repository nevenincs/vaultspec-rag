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
        """Assert that multiple threads using the same VaultStore instance

        are serialized via RLock.
        """
        store = VaultStore(tmp_path)
        store.ensure_table()
        store.ensure_code_table()

        errors: list[Exception] = []
        search_started = threading.Event()
        search_finished = threading.Event()

        # Hold the client lock in main thread
        store._client_lock.acquire()

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
        store._client_lock.release()
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
