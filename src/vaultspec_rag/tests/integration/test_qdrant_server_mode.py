"""Integration tests for qdrant server mode: real binary, real GPU.

Provisions the real pinned qdrant binary (network on first run; the
managed install is idempotent and cached across runs), supervises it
on an ephemeral loopback port with a temp storage dir, and proves the
full server-mode contract: stores open backend-aware with no point
locks, vault + code indexing and hybrid search round-trip through the
Rust engine, two roots land in differently prefixed collections on the
same server, and shutdown reaps the child with no orphaned process.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
from typing import TYPE_CHECKING

import pytest

from ...config import EnvVar, reset_config
from ...progress import NullProgressReporter
from ...qdrant_runtime import (
    QdrantProvisionAction,
    QdrantSupervisor,
    provision,
    resolve_binary,
)
from ..corpus import build_synthetic_vault

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import TempPathFactory

    from ...embeddings import EmbeddingModel

pytestmark = [pytest.mark.integration]

_SAMPLE_MODULE = '''"""Watcher debounce helper used by the server-mode test corpus."""


def debounce_window_ms(raw: int) -> int:
    """Clamp the watcher debounce window to a sane operator range."""
    return max(0, min(raw, 60_000))


class CooldownTracker:
    """Tracks per-source cooldown expiry for incremental reindexing."""

    def __init__(self, cooldown_s: float) -> None:
        self.cooldown_s = cooldown_s
        self._last: dict[str, float] = {}

    def ready(self, source: str, now: float) -> bool:
        """True when *source* has cooled down at *now*."""
        last = self._last.get(source, 0.0)
        return (now - last) >= self.cooldown_s
'''


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def real_qdrant_binary() -> Path:
    """Provision (or reuse) the real pinned binary in the managed dir."""
    reset_config()
    report = provision()
    assert report.action in (
        QdrantProvisionAction.CREATED,
        QdrantProvisionAction.UNCHANGED,
        QdrantProvisionAction.UPDATED,
    ), report.message
    resolved = resolve_binary()
    assert resolved is not None, "provisioned binary must resolve"
    return resolved.path


@pytest.fixture(scope="module")
def qdrant_server(
    real_qdrant_binary: Path,
    tmp_path_factory: TempPathFactory,
) -> Iterator[QdrantSupervisor]:
    """One real qdrant server on an ephemeral port with temp storage."""
    tmp = tmp_path_factory.mktemp("qdrant-server")
    supervisor = QdrantSupervisor(
        real_qdrant_binary,
        http_port=_free_port(),
        grpc_port=_free_port(),
        storage_dir=tmp / "storage",
        log_path=tmp / "qdrant.log",
    )
    supervisor.start(timeout=60.0)
    yield supervisor
    supervisor.stop()


@pytest.fixture
def server_mode(qdrant_server: QdrantSupervisor) -> Iterator[QdrantSupervisor]:
    """Point store construction at the running server via the URL knob."""
    prev = os.environ.get(EnvVar.QDRANT_URL.value)
    os.environ[EnvVar.QDRANT_URL.value] = qdrant_server.url
    reset_config()
    try:
        yield qdrant_server
    finally:
        if prev is None:
            os.environ.pop(EnvVar.QDRANT_URL.value, None)
        else:
            os.environ[EnvVar.QDRANT_URL.value] = prev
        reset_config()


class TestServerModeRoundTrip:
    def test_index_and_hybrid_search_through_server(
        self,
        server_mode: QdrantSupervisor,  # noqa: ARG002  # activates the URL env seam
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """Full vault + code index and hybrid search against the server."""
        from ... import CodebaseIndexer, VaultIndexer, VaultStore
        from ...search import VaultSearcher

        build_synthetic_vault(tmp_path, n_docs=8, seed=42)
        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "src" / "watcher_utils.py").write_text(
            _SAMPLE_MODULE, encoding="utf-8"
        )

        store = VaultStore(tmp_path)
        try:
            assert store._server_mode is True
            # Server mode must not engage point-operation locks.
            assert isinstance(
                store._point_lock(store.TABLE_NAME), contextlib.nullcontext
            )
            assert isinstance(
                store._point_lock(store.CODE_TABLE_NAME), contextlib.nullcontext
            )

            indexer = VaultIndexer(tmp_path, embedding_model, store)
            result = indexer.full_index(reporter=NullProgressReporter())
            assert result.added > 0

            code_indexer = CodebaseIndexer(tmp_path, embedding_model, store)
            code_indexer.full_index(reporter=NullProgressReporter())
            assert store.count() > 0
            assert store.count_code() > 0

            searcher = VaultSearcher(tmp_path, embedding_model, store)
            vault_hits = searcher.search_vault("synthetic vault document", top_k=5)
            assert vault_hits, "vault hybrid search returned nothing"

            code_hits = searcher.search_codebase(
                "clamp the watcher debounce window", top_k=5
            )
            assert code_hits, "code hybrid search returned nothing"
            assert any("watcher_utils" in hit.path for hit in code_hits)
        finally:
            store.close()

    def test_scoped_delete_evicts_in_server_mode(
        self,
        server_mode: QdrantSupervisor,  # noqa: ARG002  # activates the URL env seam
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """A scoped reindex of a deleted file evicts its chunks server-side.

        The store-level delete must be durable against the real Rust engine, not
        only the local on-disk store: index two files, delete one, run the scoped
        incremental reindex over the deleted path, and confirm the chunks are gone
        while the surviving file is untouched.
        """
        from ... import CodebaseIndexer, VaultStore

        build_synthetic_vault(tmp_path, n_docs=3, seed=11)
        pkg = tmp_path / "pkg"
        pkg.mkdir(parents=True, exist_ok=True)
        keep = pkg / "alpha.py"
        gone = pkg / "beta.py"
        keep.write_text("def alpha():\n    return 'alpha-one'\n", encoding="utf-8")
        gone.write_text("def beta():\n    return 'beta-one'\n", encoding="utf-8")

        store = VaultStore(tmp_path)
        try:
            assert store._server_mode is True
            code_indexer = CodebaseIndexer(tmp_path, embedding_model, store)
            code_indexer.full_index(reporter=NullProgressReporter())

            keep_rel = str(keep.relative_to(tmp_path)).replace("\\", "/")
            gone_rel = str(gone.relative_to(tmp_path)).replace("\\", "/")
            assert code_indexer._get_chunk_ids_for_files({gone_rel})

            gone.unlink()
            result = code_indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths={gone},
            )

            assert result.removed == 1
            assert not code_indexer._get_chunk_ids_for_files({gone_rel})
            assert code_indexer._get_chunk_ids_for_files({keep_rel})
            assert gone_rel not in code_indexer._load_meta()
        finally:
            store.close()

    def test_two_roots_namespace_collections_on_one_server(
        self,
        server_mode: QdrantSupervisor,  # noqa: ARG002  # activates the URL env seam
        tmp_path: Path,
    ) -> None:
        """Distinct roots own distinct prefixed collections server-side."""
        from ... import VaultStore

        root_a = tmp_path / "root-a"
        root_b = tmp_path / "root-b"
        root_a.mkdir()
        root_b.mkdir()

        store_a = VaultStore(root_a)
        store_b = VaultStore(root_b)
        try:
            assert store_a.TABLE_NAME != store_b.TABLE_NAME
            store_a.ensure_table()
            store_b.ensure_table()

            server_collections = {
                collection.name
                for collection in store_a.client.get_collections().collections
            }
            assert store_a.TABLE_NAME in server_collections
            assert store_b.TABLE_NAME in server_collections
        finally:
            store_a.close()
            store_b.close()


class TestServerModeDeletionEviction:
    """Issue 192: a scoped incremental reindex must evict a deleted file's
    data from the store in server mode, so search no longer surfaces it,
    without a full rebuild. Every prior deletion test forced local mode;
    these drive the real managed server.
    """

    def test_scoped_delete_evicts_code_chunks_and_search_in_server_mode(
        self,
        server_mode: QdrantSupervisor,  # noqa: ARG002  # activates the URL env seam
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """Deleting a code file then scoped-reindexing drops its chunks and
        removes it from hybrid search, in server mode."""
        from ... import CodebaseIndexer, VaultStore
        from ...search import VaultSearcher

        src = tmp_path / "src"
        src.mkdir(parents=True)
        keep = src / "keep_utils.py"
        gone = src / "gone_utils.py"
        keep.write_text(
            '"""Kept module."""\n\n\n'
            "def keep_sentinel() -> str:\n"
            '    """Return the kept sentinel."""\n'
            '    return "retained-keeptoken"\n',
            encoding="utf-8",
        )
        gone.write_text(
            '"""Doomed module."""\n\n\n'
            "def gone_sentinel() -> str:\n"
            '    """Return the doomed sentinel."""\n'
            '    return "deleteme-uniquegonetoken"\n',
            encoding="utf-8",
        )

        store = VaultStore(tmp_path)
        try:
            assert store._server_mode is True
            code_indexer = CodebaseIndexer(tmp_path, embedding_model, store)
            code_indexer.full_index(reporter=NullProgressReporter())

            gone_rel = str(gone.relative_to(tmp_path)).replace("\\", "/")
            assert code_indexer._get_chunk_ids_for_files({gone_rel}), (
                "doomed file must have chunks before deletion (sanity)"
            )

            searcher = VaultSearcher(tmp_path, embedding_model, store)
            assert any(
                "gone_utils" in hit.path
                for hit in searcher.search_codebase(
                    "deleteme uniquegonetoken doomed sentinel", top_k=5
                )
            ), "doomed file must be searchable before deletion (sanity)"

            gone.unlink()
            result = code_indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths={gone},
            )
            assert result.removed == 1

            assert not code_indexer._get_chunk_ids_for_files({gone_rel}), (
                "deleted file's chunks must be evicted from the store (issue 192)"
            )
            keep_rel = str(keep.relative_to(tmp_path)).replace("\\", "/")
            assert code_indexer._get_chunk_ids_for_files({keep_rel}), (
                "kept file's chunks must remain"
            )
            assert not any(
                "gone_utils" in hit.path
                for hit in searcher.search_codebase(
                    "deleteme uniquegonetoken doomed sentinel", top_k=5
                )
            ), "deleted file still returned by server-mode search (issue 192)"
        finally:
            store.close()

    def test_scoped_delete_evicts_vault_doc_in_server_mode(
        self,
        server_mode: QdrantSupervisor,  # noqa: ARG002  # activates the URL env seam
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """Deleting a vault document then scoped-reindexing evicts it from
        the vault collection, in server mode."""
        from ... import VaultIndexer, VaultStore
        from ...config import get_config

        build_synthetic_vault(tmp_path, n_docs=6, seed=7)
        store = VaultStore(tmp_path)
        try:
            assert store._server_mode is True
            vault_indexer = VaultIndexer(tmp_path, embedding_model, store)
            vault_indexer.full_index(reporter=NullProgressReporter())
            before = store.count()
            assert before > 0

            docs_dir = tmp_path / get_config().docs_dir
            doc = next(iter(sorted(docs_dir.rglob("*.md"))))
            doc.unlink()

            result = vault_indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths={doc},
            )
            assert result.removed >= 1
            assert store.count() < before, (
                "deleted vault document must reduce the stored count (issue 192)"
            )
        finally:
            store.close()


class TestServerModeWatcherEviction:
    """Issue 192 through the real watcher: deleting a file on disk while the
    watcher runs must evict it from search in server mode, end to end. This
    drives the actual ``awatch`` -> classify -> pending-set -> scoped
    incremental path the operator hits, not a direct indexer call.
    """

    async def test_watcher_evicts_deleted_vault_doc_in_server_mode(
        self,
        server_mode: QdrantSupervisor,  # noqa: ARG002  # activates the URL env seam
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        from ... import CodebaseIndexer, VaultIndexer, VaultStore
        from ...graph_cache import GraphCache
        from ...watcher import watch_and_reindex

        vault_dir = tmp_path / ".vault"
        adr_dir = vault_dir / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "init.md").write_text(
            "---\ntags: ['#adr', '#initial']\ndate: '2026-06-18'\n"
            "related: []\ntitle: Init\n---\n# Init\n\nInitial body.\n",
            encoding="utf-8",
        )
        doomed = adr_dir / "doomed.md"
        doomed.write_text(
            "---\ntags: ['#adr', '#doomed']\ndate: '2026-06-18'\n"
            "related: []\ntitle: Doomed\n---\n# Doomed\n\n"
            "This doomed decision mentions uniquewatchertoken repeatedly.\n",
            encoding="utf-8",
        )

        store = VaultStore(tmp_path)
        vault_indexer = VaultIndexer(tmp_path, embedding_model, store)
        code_indexer = CodebaseIndexer(tmp_path, embedding_model, store)
        graph_cache = GraphCache()
        vault_indexer.full_index(reporter=NullProgressReporter())

        q_vec = embedding_model.encode_query(
            "uniquewatchertoken doomed decision"
        ).tolist()

        def _hits() -> bool:
            results = store.hybrid_search(
                query_vector=q_vec,
                _query_text="uniquewatchertoken doomed decision",
                limit=10,
            )
            return any("uniquewatchertoken" in r.get("content", "") for r in results)

        assert _hits(), "doomed doc must be searchable before deletion (sanity)"

        stop_event = asyncio.Event()
        watcher_task = asyncio.create_task(
            watch_and_reindex(
                root_dir=tmp_path,
                vault_dir=vault_dir,
                vault_indexer=vault_indexer,
                code_indexer=code_indexer,
                stop_event=stop_event,
                graph_cache=graph_cache,
                debounce=50,
                cooldown=0.1,
            )
        )
        try:
            await asyncio.sleep(0.2)
            doomed.unlink()
            for _ in range(50):  # up to ~5s
                await asyncio.sleep(0.1)
                if not _hits():
                    break
            else:
                pytest.fail(
                    "watcher did not evict the deleted doc from server-mode "
                    "search within timeout (issue 192)"
                )
            # Survivor check: eviction removed the doomed doc, NOT the whole
            # collection. A kept sibling must still surface (distinguishes real
            # eviction from a search/store that simply stopped returning hits).
            init_vec = embedding_model.encode_query("Init initial body").tolist()
            init_results = store.hybrid_search(
                query_vector=init_vec, _query_text="Init initial body", limit=10
            )
            assert any("Initial body" in r.get("content", "") for r in init_results), (
                "kept sibling doc must still be searchable after eviction"
            )
        finally:
            stop_event.set()
            await watcher_task
            store.close()

    async def test_watcher_evicts_deleted_code_file_in_server_mode(
        self,
        server_mode: QdrantSupervisor,  # noqa: ARG002  # activates the URL env seam
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """The user's exact scenario: a deleted code file must drop out of
        code search after the watcher's scoped reindex, in server mode."""
        from ... import CodebaseIndexer, VaultIndexer, VaultStore
        from ...graph_cache import GraphCache
        from ...search import VaultSearcher
        from ...watcher import watch_and_reindex

        vault_dir = tmp_path / ".vault"
        vault_dir.mkdir(parents=True)
        src = tmp_path / "src"
        src.mkdir()
        (src / "keep_mod.py").write_text(
            '"""Kept."""\n\n\ndef keep() -> str:\n    return "retained"\n',
            encoding="utf-8",
        )
        gone = src / "gone_mod.py"
        gone.write_text(
            '"""Doomed."""\n\n\ndef gone() -> str:\n'
            '    return "uniquecodewatchertoken"\n',
            encoding="utf-8",
        )

        store = VaultStore(tmp_path)
        vault_indexer = VaultIndexer(tmp_path, embedding_model, store)
        code_indexer = CodebaseIndexer(tmp_path, embedding_model, store)
        graph_cache = GraphCache()
        code_indexer.full_index(reporter=NullProgressReporter())
        searcher = VaultSearcher(tmp_path, embedding_model, store)

        def _hits() -> bool:
            return any(
                "gone_mod" in hit.path
                for hit in searcher.search_codebase(
                    "uniquecodewatchertoken doomed", top_k=5
                )
            )

        assert _hits(), "doomed code file must be searchable before deletion (sanity)"

        stop_event = asyncio.Event()
        watcher_task = asyncio.create_task(
            watch_and_reindex(
                root_dir=tmp_path,
                vault_dir=vault_dir,
                vault_indexer=vault_indexer,
                code_indexer=code_indexer,
                stop_event=stop_event,
                graph_cache=graph_cache,
                debounce=50,
                cooldown=0.1,
            )
        )
        try:
            await asyncio.sleep(0.2)
            gone.unlink()
            for _ in range(50):  # up to ~5s
                await asyncio.sleep(0.1)
                if not _hits():
                    break
            else:
                pytest.fail(
                    "watcher did not evict the deleted code file from "
                    "server-mode search within timeout (issue 192)"
                )
            # Survivor check: the kept module must still surface, proving the
            # watcher evicted only the deleted file, not the whole collection.
            assert any(
                "keep_mod" in hit.path
                for hit in searcher.search_codebase("retained keep", top_k=5)
            ), "kept code file must still be searchable after eviction"
        finally:
            stop_event.set()
            await watcher_task
            store.close()


class TestSupervision:
    def test_stop_reaps_the_child(
        self,
        real_qdrant_binary: Path,
        tmp_path: Path,
    ) -> None:
        """A stopped supervisor leaves no qdrant process behind."""
        import vaultspec_rag.cli as cli

        supervisor = QdrantSupervisor(
            real_qdrant_binary,
            http_port=_free_port(),
            grpc_port=_free_port(),
            storage_dir=tmp_path / "storage",
            log_path=tmp_path / "qdrant.log",
        )
        supervisor.start(timeout=60.0)
        pid = supervisor.pid
        assert pid is not None
        assert cli._is_pid_alive(pid)
        assert supervisor.server_version().startswith("1.18")

        supervisor.stop()

        assert not supervisor.is_alive()
        assert not cli._is_pid_alive(pid), "qdrant child must be reaped"

    def test_restart_recovers_a_killed_child(
        self,
        real_qdrant_binary: Path,
        tmp_path: Path,
    ) -> None:
        """The heartbeat's single bounded restart brings the server back."""
        supervisor = QdrantSupervisor(
            real_qdrant_binary,
            http_port=_free_port(),
            grpc_port=_free_port(),
            storage_dir=tmp_path / "storage",
            log_path=tmp_path / "qdrant.log",
        )
        supervisor.start(timeout=60.0)
        try:
            proc = supervisor._proc
            assert proc is not None
            proc.kill()
            proc.wait(timeout=10)
            assert not supervisor.is_alive()

            assert supervisor.restart(timeout=60.0) is True
            assert supervisor.restart_count == 1
            assert supervisor.is_alive()
            assert supervisor.server_version().startswith("1.18")
        finally:
            supervisor.stop()


class TestServerFirstStartupSelection:
    """The service-startup selection contract: server mode by default,
    local store only under --local-only, loud failure when the default
    server backend cannot start.

    These exercise the real selection (``effective_server_mode``) and the
    real failure path the service lifespan routes through, without
    spawning the GPU daemon or disturbing any running service.
    """

    def test_default_config_selects_server_mode(self) -> None:
        """With no opt-out set, the resident service starts server mode."""
        from ...config import get_config

        prev_server = os.environ.get(EnvVar.QDRANT_SERVER.value)
        prev_local = os.environ.get(EnvVar.LOCAL_ONLY.value)
        os.environ.pop(EnvVar.QDRANT_SERVER.value, None)
        os.environ.pop(EnvVar.LOCAL_ONLY.value, None)
        reset_config()
        try:
            cfg = get_config()
            assert cfg.qdrant_server is True
            assert cfg.local_only is False
            # The one selection point the lifespan consults.
            assert cfg.effective_server_mode() is True
        finally:
            if prev_server is None:
                os.environ.pop(EnvVar.QDRANT_SERVER.value, None)
            else:
                os.environ[EnvVar.QDRANT_SERVER.value] = prev_server
            if prev_local is None:
                os.environ.pop(EnvVar.LOCAL_ONLY.value, None)
            else:
                os.environ[EnvVar.LOCAL_ONLY.value] = prev_local
            reset_config()

    def test_local_only_opt_out_opens_the_on_disk_store(
        self,
        tmp_path: Path,
    ) -> None:
        """--local-only deselects server mode and opens the local store.

        With ``local_only`` set the lifespan never spawns the child and
        never publishes ``QDRANT_URL``, so a store opens in on-disk mode
        with point-operation locks engaged - the backend-aware local path.
        """
        from ... import VaultStore
        from ...config import get_config

        prev_local = os.environ.get(EnvVar.LOCAL_ONLY.value)
        prev_url = os.environ.get(EnvVar.QDRANT_URL.value)
        os.environ[EnvVar.LOCAL_ONLY.value] = "1"
        # No server URL is published in local-only mode.
        os.environ.pop(EnvVar.QDRANT_URL.value, None)
        reset_config()
        try:
            cfg = get_config()
            assert cfg.effective_server_mode() is False

            store = VaultStore(tmp_path)
            try:
                assert store._server_mode is False
                # Local mode takes a real reentrant point lock, never the
                # server-mode null context.
                assert not isinstance(
                    store._point_lock(store.TABLE_NAME), contextlib.nullcontext
                )
            finally:
                store.close()
        finally:
            if prev_local is None:
                os.environ.pop(EnvVar.LOCAL_ONLY.value, None)
            else:
                os.environ[EnvVar.LOCAL_ONLY.value] = prev_local
            if prev_url is not None:
                os.environ[EnvVar.QDRANT_URL.value] = prev_url
            reset_config()

    def test_missing_binary_default_path_fails_loud_and_actionable(
        self,
        tmp_path: Path,
    ) -> None:
        """The default server backend with no binary aborts actionably.

        Server mode is the default; with the managed dir empty, no
        operator binary, and ``qdrant`` absent from ``PATH``,
        ``start_supervised_from_config`` (the call the lifespan wraps)
        raises a ``RuntimeError`` that names the install command. The
        service lifespan turns this into the startup abort that also
        names ``--local-only``; here we prove the underlying loud failure
        the contract depends on.
        """
        from ...qdrant_runtime import resolve_binary, start_supervised_from_config

        prev_status = os.environ.get(EnvVar.STATUS_DIR.value)
        prev_binary = os.environ.get(EnvVar.QDRANT_BINARY.value)
        prev_local = os.environ.get(EnvVar.LOCAL_ONLY.value)
        # Isolate the managed dir to an empty tmp so nothing is
        # provisioned, point the operator-binary knob at a path that does
        # not exist, and keep server mode the default (no local-only).
        os.environ[EnvVar.STATUS_DIR.value] = str(tmp_path)
        os.environ[EnvVar.QDRANT_BINARY.value] = str(tmp_path / "does-not-exist")
        os.environ.pop(EnvVar.LOCAL_ONLY.value, None)
        reset_config()
        try:
            if resolve_binary() is not None:
                pytest.fail(
                    "a qdrant binary resolved on PATH; this host cannot "
                    "exercise the missing-binary loud-failure contract"
                )
            with pytest.raises(RuntimeError) as exc_info:
                start_supervised_from_config()
            message = str(exc_info.value)
            assert "vaultspec-rag server qdrant install" in message
            assert "vaultspec-rag server start --local-only" in message
        finally:
            if prev_status is None:
                os.environ.pop(EnvVar.STATUS_DIR.value, None)
            else:
                os.environ[EnvVar.STATUS_DIR.value] = prev_status
            if prev_binary is None:
                os.environ.pop(EnvVar.QDRANT_BINARY.value, None)
            else:
                os.environ[EnvVar.QDRANT_BINARY.value] = prev_binary
            if prev_local is not None:
                os.environ[EnvVar.LOCAL_ONLY.value] = prev_local
            reset_config()
