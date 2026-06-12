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
