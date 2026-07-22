"""Stress testing and filesystem watcher integration tests.

Tests concurrent reads and writes, SQLite lock constraints,
and the real watch files auto-reindexing loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, cast

import pytest

from ... import CodebaseIndexer, VaultIndexer, VaultStore
from ...concurrency import get_index_limiter
from ...config import EnvVar, get_config, reset_config

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ...embeddings import EmbeddingModel

from ...graph_cache import GraphCache
from ...progress import NullProgressReporter
from ...store import VaultStoreLockedError
from ...watcher import watch_and_reindex
from ...watcher_retry import WatcherRetryPolicy, WatcherSource

pytestmark = [pytest.mark.integration]


@contextmanager
def _watcher_retry_test_config() -> Generator[None]:
    values = {
        EnvVar.WATCH_RETRY_BASE_SECONDS: "2",
        EnvVar.WATCH_RETRY_MAX_SECONDS: "2",
        EnvVar.WATCH_RETRY_JITTER_FRACTION: "0",
        EnvVar.WATCH_CIRCUIT_FAILURE_THRESHOLD: "2",
    }
    previous = {key: os.environ.get(key.value) for key in values}
    try:
        for key, value in values.items():
            os.environ[key.value] = value
        reset_config()
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key.value, None)
            else:
                os.environ[key.value] = value
        reset_config()


def _load_watcher_state(path: Path) -> dict[str, object]:
    parsed: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return cast("dict[str, object]", parsed)


def _try_load_watcher_state(path: Path) -> dict[str, object] | None:
    try:
        return _load_watcher_state(path)
    except (FileNotFoundError, PermissionError):
        return None


async def _wait_for_watcher_failure(path: Path) -> dict[str, object]:
    for _ in range(60):
        await asyncio.sleep(0.05)
        state = _try_load_watcher_state(path)
        if state is not None and state.get("consecutive_failures"):
            return state
    pytest.fail("watcher failure state was not persisted")


async def _wait_for_path(path: Path) -> None:
    for _ in range(100):
        if path.exists():
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"expected path was not created: {path}")


async def _wait_for_state_retry_log(caplog: pytest.LogCaptureFixture) -> int:
    event_loop_ticks = 0
    deadline = time.monotonic() + 4.0
    while (
        "service.watcher event=state_transaction_retry" not in caplog.text
        and time.monotonic() < deadline
    ):
        await asyncio.sleep(0.02)
        event_loop_ticks += 1
    return event_loop_ticks


def _start_state_lock_holder(
    lock_path: Path,
    ready_path: Path,
    *,
    hold_seconds: float = 2.4,
) -> subprocess.Popen[str]:
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


def _start_test_watcher(
    root: Path,
    vault_dir: Path,
    embedding_model: EmbeddingModel,
    store: VaultStore,
    code_indexer: CodebaseIndexer,
) -> tuple[asyncio.Event, asyncio.Task[None]]:
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        watch_and_reindex(
            root_dir=root,
            vault_dir=vault_dir,
            vault_indexer=VaultIndexer(root, embedding_model, store),
            code_indexer=code_indexer,
            stop_event=stop_event,
            graph_cache=GraphCache(),
            debounce=50,
            cooldown=0.0,
        )
    )
    return stop_event, task


async def _wait_for_watcher_settled(path: Path) -> dict[str, object]:
    for _ in range(30):
        state = _try_load_watcher_state(path)
        if state is not None and (
            state.get("circuit_state") == "closed"
            and state.get("convergence_pending") is False
        ):
            return state
        await asyncio.sleep(0.05)
    pytest.fail("watcher convergence outcome was not persisted")


async def _wait_for_active_watcher_attempt(path: Path) -> dict[str, object]:
    for _ in range(200):
        state = _try_load_watcher_state(path)
        if state is not None and isinstance(state.get("attempt_generation"), int):
            return state
        await asyncio.sleep(0.01)
    pytest.fail("watcher never persisted an active convergence attempt")


async def _wait_for_newer_watcher_generation(
    path: Path,
    previous: int,
) -> dict[str, object]:
    for _ in range(200):
        state = _try_load_watcher_state(path)
        if state is not None:
            generation = state.get("convergence_generation")
            if isinstance(generation, int) and generation > previous:
                return state
        await asyncio.sleep(0.01)
    pytest.fail("event during indexing was not durably generation-marked")


async def _wait_for_code_payload(
    store: VaultStore,
    *,
    path: str,
    expected_content: str,
) -> None:
    from qdrant_client import models

    for _ in range(100):
        await asyncio.sleep(0.1)
        records, _offset = store.client.scroll(
            collection_name=store.CODE_TABLE_NAME,
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
    pytest.fail("restart did not perform the pending convergence pass")


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


@pytest.mark.asyncio
async def test_watcher_failure_is_bounded_and_restart_converges(
    tmp_path: Path, embedding_model: EmbeddingModel
) -> None:
    """A real store failure opens the circuit; restart performs convergence."""
    with _watcher_retry_test_config():
        vault_dir = tmp_path / ".vault"
        vault_dir.mkdir(parents=True)
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        changed = source_dir / "recover.py"
        changed.write_text(
            'def status():\n    return "before-watcher-recovery"\n',
            encoding="utf-8",
        )

        first_store = VaultStore(tmp_path)
        first_vault_indexer = VaultIndexer(tmp_path, embedding_model, first_store)
        first_code_indexer = CodebaseIndexer(tmp_path, embedding_model, first_store)
        first_code_indexer.full_index(reporter=NullProgressReporter())
        first_stop = asyncio.Event()
        first_task = asyncio.create_task(
            watch_and_reindex(
                root_dir=tmp_path,
                vault_dir=vault_dir,
                vault_indexer=first_vault_indexer,
                code_indexer=first_code_indexer,
                stop_event=first_stop,
                graph_cache=GraphCache(),
                debounce=50,
                cooldown=0.0,
            )
        )
        recovery_store: VaultStore | None = None
        recovery_task: asyncio.Task[None] | None = None
        recovery_stop = asyncio.Event()
        try:
            await asyncio.sleep(0.25)
            first_store.close()
            changed.write_text(
                'def status():\n    return "after-watcher-recovery"\n',
                encoding="utf-8",
            )

            state_path = (
                tmp_path / get_config().data_dir / "watcher-retry" / "code.json"
            )
            failed_state = await _wait_for_watcher_failure(state_path)
            assert failed_state["circuit_state"] == "open"
            assert failed_state["convergence_pending"] is True
            assert failed_state["consecutive_failures"] == 1

            # A later event is coalesced while the circuit is open. Several
            # idle ticks occur before the configured retry boundary.
            changed.write_text(
                "\n\n".join(
                    f'def recovery_{number}():\n    return "coalesced-{number}"'
                    for number in range(120)
                )
                + '\n\ndef status():\n    return "coalesced-watcher-recovery"\n',
                encoding="utf-8",
            )
            await asyncio.sleep(0.75)
            assert _load_watcher_state(state_path)["consecutive_failures"] == 1

            first_stop.set()
            await first_task

            recovery_store = VaultStore(tmp_path)
            recovery_task = asyncio.create_task(
                watch_and_reindex(
                    root_dir=tmp_path,
                    vault_dir=vault_dir,
                    vault_indexer=VaultIndexer(
                        tmp_path, embedding_model, recovery_store
                    ),
                    code_indexer=CodebaseIndexer(
                        tmp_path, embedding_model, recovery_store
                    ),
                    stop_event=recovery_stop,
                    graph_cache=GraphCache(),
                    debounce=50,
                    cooldown=0.0,
                )
            )
            await asyncio.sleep(0.1)
            (source_dir / "newer.py").write_text(
                'def newer():\n    return "arrived-after-restart"\n',
                encoding="utf-8",
            )
            active_state = await _wait_for_active_watcher_attempt(state_path)
            active_generation = active_state["attempt_generation"]
            assert isinstance(active_generation, int)
            changed.write_text(
                'def status():\n    return "during-active-watcher-recovery"\n',
                encoding="utf-8",
            )
            newer_state = await _wait_for_newer_watcher_generation(
                state_path,
                active_generation,
            )
            assert newer_state["attempt_generation"] == active_generation
            await _wait_for_code_payload(
                recovery_store,
                path=str(changed.relative_to(tmp_path)).replace("\\", "/"),
                expected_content="during-active-watcher-recovery",
            )

            settled = await _wait_for_watcher_settled(state_path)
            assert settled["circuit_state"] == "closed"
            assert settled["consecutive_failures"] == 0
            assert settled["convergence_pending"] is False
            assert isinstance(settled["last_durable_progress_at"], int | float)
        finally:
            first_stop.set()
            if not first_task.done():
                await first_task
            recovery_stop.set()
            if recovery_task is not None:
                await recovery_task
            if recovery_store is not None:
                recovery_store.close()
            first_store.close()


@pytest.mark.asyncio
async def test_watcher_retries_intent_after_real_state_lock_contention(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A process-held state lock delays persistence without losing the edit."""
    with _watcher_retry_test_config():
        vault_dir = tmp_path / ".vault"
        vault_dir.mkdir(parents=True)
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        changed = source_dir / "contended.py"
        changed.write_text(
            'def state():\n    return "before-lock-contention"\n',
            encoding="utf-8",
        )

        store = VaultStore(tmp_path)
        code_indexer = CodebaseIndexer(tmp_path, embedding_model, store)
        code_indexer.full_index(reporter=NullProgressReporter())
        stop_event, watcher_task = _start_test_watcher(
            tmp_path,
            vault_dir,
            embedding_model,
            store,
            code_indexer,
        )
        state_path = tmp_path / get_config().data_dir / "watcher-retry" / "code.json"
        ready_path = tmp_path / "state-lock-ready.marker"
        holder: subprocess.Popen[str] | None = None
        replacement_stop: asyncio.Event | None = None
        replacement_task: asyncio.Task[None] | None = None
        try:
            await _wait_for_path(state_path)
            lock_path = state_path.with_name(f"{state_path.name}.lock")
            holder = _start_state_lock_holder(lock_path, ready_path)
            await _wait_for_path(ready_path)

            with caplog.at_level(logging.WARNING, logger="vaultspec_rag.watcher"):
                changed.write_text(
                    'def state():\n    return "after-lock-contention"\n',
                    encoding="utf-8",
                )
                event_loop_ticks = await _wait_for_state_retry_log(caplog)

            assert "service.watcher event=state_transaction_retry" in caplog.text
            assert event_loop_ticks >= 20
            assert not watcher_task.done()
            stop_event.set()
            watcher_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await watcher_task
            await asyncio.to_thread(holder.wait, 10.0)
            assert holder.returncode == 0

            durable = _load_watcher_state(state_path)
            assert durable["convergence_pending"] is True
            replacement_stop, replacement_task = _start_test_watcher(
                tmp_path,
                vault_dir,
                embedding_model,
                store,
                code_indexer,
            )
            await _wait_for_code_payload(
                store,
                path=str(changed.relative_to(tmp_path)).replace("\\", "/"),
                expected_content="after-lock-contention",
            )
            settled = await _wait_for_watcher_settled(state_path)
            assert settled["convergence_pending"] is False
            assert settled["circuit_state"] == "closed"
        finally:
            stop_event.set()
            if not watcher_task.done():
                watcher_task.cancel()
                with suppress(asyncio.CancelledError):
                    await watcher_task
            if replacement_stop is not None:
                replacement_stop.set()
            if replacement_task is not None:
                await replacement_task
            if holder is not None and holder.poll() is None:
                holder.terminate()
                holder.wait(timeout=5.0)
            store.close()


@pytest.mark.asyncio
async def test_watcher_cancellation_releases_real_admitted_claim(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
) -> None:
    """Cancelling a dispatcher waiting on real admission settles its claim."""
    with _watcher_retry_test_config():
        vault_dir = tmp_path / ".vault"
        vault_dir.mkdir(parents=True)
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        changed = source_dir / "cancelled.py"
        changed.write_text(
            'def state():\n    return "before-cancellation"\n',
            encoding="utf-8",
        )

        store = VaultStore(tmp_path)
        code_indexer = CodebaseIndexer(tmp_path, embedding_model, store)
        code_indexer.full_index(reporter=NullProgressReporter())
        limiter = get_index_limiter()
        borrowers = [object() for _ in range(int(limiter.total_tokens))]
        for borrower in borrowers:
            await limiter.acquire_on_behalf_of(borrower)

        stop_event = asyncio.Event()
        watcher_task = asyncio.create_task(
            watch_and_reindex(
                root_dir=tmp_path,
                vault_dir=vault_dir,
                vault_indexer=VaultIndexer(tmp_path, embedding_model, store),
                code_indexer=code_indexer,
                stop_event=stop_event,
                graph_cache=GraphCache(),
                debounce=50,
                cooldown=0.0,
            )
        )
        state_path = tmp_path / get_config().data_dir / "watcher-retry" / "code.json"
        try:
            await _wait_for_path(state_path)
            changed.write_text(
                'def state():\n    return "during-cancellation"\n',
                encoding="utf-8",
            )
            active = await _wait_for_active_watcher_attempt(state_path)
            assert isinstance(active["attempt_generation"], int)

            watcher_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await watcher_task

            interrupted = _load_watcher_state(state_path)
            assert interrupted["attempt_generation"] is None
            assert interrupted["convergence_pending"] is True
            assert interrupted["unscoped_required"] is True
            assert interrupted["consecutive_failures"] == 0
        finally:
            for borrower in borrowers:
                limiter.release_on_behalf_of(borrower)
            if not watcher_task.done():
                watcher_task.cancel()
                with suppress(asyncio.CancelledError):
                    await watcher_task
            store.close()


@pytest.mark.asyncio
async def test_watcher_refreshes_intent_committed_by_retiring_policy(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
) -> None:
    """Idle refresh observes dirty state committed after clean construction."""
    with _watcher_retry_test_config():
        vault_dir = tmp_path / ".vault"
        vault_dir.mkdir(parents=True)
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        changed = source_dir / "late-intent.py"
        changed.write_text(
            'def state():\n    return "before-late-intent"\n',
            encoding="utf-8",
        )

        store = VaultStore(tmp_path)
        code_indexer = CodebaseIndexer(tmp_path, embedding_model, store)
        code_indexer.full_index(reporter=NullProgressReporter())
        retiring_policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
        changed.write_text(
            'def state():\n    return "after-late-intent"\n',
            encoding="utf-8",
        )
        stop_event, watcher_task = _start_test_watcher(
            tmp_path,
            vault_dir,
            embedding_model,
            store,
            code_indexer,
        )
        state_path = tmp_path / get_config().data_dir / "watcher-retry" / "code.json"
        try:
            await _wait_for_path(state_path)
            await asyncio.sleep(0.2)
            assert not watcher_task.done()
            await asyncio.to_thread(retiring_policy.mark_convergence_pending)

            await _wait_for_code_payload(
                store,
                path=str(changed.relative_to(tmp_path)).replace("\\", "/"),
                expected_content="after-late-intent",
            )
            settled = await _wait_for_watcher_settled(state_path)
            assert settled["convergence_pending"] is False
        finally:
            stop_event.set()
            await watcher_task
            store.close()


@pytest.mark.asyncio
async def test_watcher_startup_retries_real_state_lock_contention(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
) -> None:
    """Replacement construction survives a retiring policy's state lock."""
    with _watcher_retry_test_config():
        vault_dir = tmp_path / ".vault"
        vault_dir.mkdir(parents=True)
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        changed = source_dir / "startup-contention.py"
        changed.write_text(
            'def state():\n    return "before-startup-contention"\n',
            encoding="utf-8",
        )

        store = VaultStore(tmp_path)
        code_indexer = CodebaseIndexer(tmp_path, embedding_model, store)
        code_indexer.full_index(reporter=NullProgressReporter())
        retiring_policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
        changed.write_text(
            'def state():\n    return "after-startup-contention"\n',
            encoding="utf-8",
        )
        retiring_policy.mark_convergence_pending()
        state_path = tmp_path / get_config().data_dir / "watcher-retry" / "code.json"
        ready_path = tmp_path / "startup-lock-ready.marker"
        holder = _start_state_lock_holder(
            state_path.with_name(f"{state_path.name}.lock"),
            ready_path,
        )
        stop_event: asyncio.Event | None = None
        watcher_task: asyncio.Task[None] | None = None
        try:
            await _wait_for_path(ready_path)
            stop_event, watcher_task = _start_test_watcher(
                tmp_path,
                vault_dir,
                embedding_model,
                store,
                code_indexer,
            )
            await asyncio.sleep(0.1)
            assert not watcher_task.done()
            await _wait_for_code_payload(
                store,
                path=str(changed.relative_to(tmp_path)).replace("\\", "/"),
                expected_content="after-startup-contention",
            )
            await asyncio.to_thread(holder.wait, 10.0)
            assert holder.returncode == 0
            settled = await _wait_for_watcher_settled(state_path)
            assert settled["convergence_pending"] is False
        finally:
            if stop_event is not None:
                stop_event.set()
            if watcher_task is not None:
                await watcher_task
            if holder.poll() is None:
                holder.terminate()
                holder.wait(timeout=5.0)
            store.close()
