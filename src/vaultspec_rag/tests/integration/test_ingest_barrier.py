"""Ingest-barrier integration tests against the real pinned qdrant server.

Rebuild-path upserts run with ``wait=False``: the server acknowledges on
the WAL write and applies asynchronously. The barrier (fence delete with
``wait=True``, then an exact count) is the only thing standing between an
acknowledged-but-never-applied batch and a terminal metadata publish over
missing points, so these tests exercise it against the real Rust engine:
a poisoned batch the server acknowledges and silently drops, and a full
vault rebuild whose points vanish between acknowledgement and barrier.

No GPU: embeddings come from a deterministic CPU-only fake model; the
subject under test is the store's wait policy and barrier placement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from ...config import EnvVar, get_config, reset_config
from ...progress import NullProgressReporter
from ...store import IngestVerificationError, VaultStore
from ..corpus import build_synthetic_vault
from ._helpers import provisioned_qdrant_binary, serve_qdrant

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import TempPathFactory

    from ..._store_writes import StoreWritePolicy
    from ...qdrant_runtime._supervise import QdrantSupervisor
    from ...store import CodeChunk, VaultChunk

pytestmark = [pytest.mark.integration]


@pytest.fixture(scope="module")
def real_qdrant_binary() -> Path:
    """Provision (or reuse) the pinned real Qdrant binary."""
    return provisioned_qdrant_binary()


@pytest.fixture(scope="module")
def qdrant_server(
    real_qdrant_binary: Path,
    tmp_path_factory: TempPathFactory,
) -> Iterator[QdrantSupervisor]:
    """One real qdrant server on ephemeral ports with temp storage."""
    yield from serve_qdrant(
        real_qdrant_binary, tmp_path_factory.mktemp("qdrant-barrier")
    )


@pytest.fixture
def server_mode(
    qdrant_server: QdrantSupervisor,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[QdrantSupervisor]:
    """Point store construction at the running server via the URL knob."""
    monkeypatch.setenv(EnvVar.QDRANT_URL.value, qdrant_server.url)
    reset_config()
    try:
        yield qdrant_server
    finally:
        monkeypatch.delenv(EnvVar.QDRANT_URL.value, raising=False)
        reset_config()


class _DeterministicCpuModel:
    """CPU-only stand-in emitting stable dense rows and no sparse rows."""

    device = "cpu"

    def __init__(self) -> None:
        self._dimension = int(get_config().embedding_dimension)

    def _row(self, text: str) -> list[float]:
        seed = (hash(text) % 997) + 1
        row = [0.0] * self._dimension
        row[seed % self._dimension] = 1.0
        return row

    def encode_documents_on_device(
        self,
        texts: list[str],
        batch_size: int | None = None,
    ) -> list[list[float]]:
        del batch_size
        return [self._row(text) for text in texts]

    def encode_documents_sparse(
        self,
        texts: list[str],
        batch_size: int | None = None,
        gpu_lock: object | None = None,
    ) -> list[None]:
        del batch_size, gpu_lock
        return [None] * len(texts)


def _make_code_chunks(count: int, dimension: int) -> list[CodeChunk]:
    from ...store import CodeChunk

    chunks: list[CodeChunk] = []
    for index in range(count):
        vector = [0.0] * dimension
        vector[index % dimension] = 1.0
        chunks.append(
            CodeChunk(
                id=f"pkg/mod.py:{index}",
                path="pkg/mod.py",
                language="python",
                content=f"def fn_{index}():\n    return {index}\n",
                line_start=index * 3 + 1,
                line_end=index * 3 + 2,
                vector=vector,
            )
        )
    return chunks


class TestIngestBarrierStoreContract:
    """The barrier proves application; acknowledgement alone is not enough."""

    def test_barrier_passes_when_every_acknowledged_point_applied(
        self,
        server_mode: QdrantSupervisor,  # noqa: ARG002  # activates the URL env seam
        tmp_path: Path,
    ) -> None:
        store = VaultStore(tmp_path)
        try:
            assert store._server_mode is True
            store.ensure_code_table()
            chunks = _make_code_chunks(8, int(get_config().embedding_dimension))
            store.upsert_code_chunks(chunks, write_policy=None, wait=False)
            store.apply_ingest_barrier(
                store.CODE_TABLE_NAME,
                expected_points=len(chunks),
            )
            assert store.count_code() == len(chunks)
        finally:
            store.close()

    def test_barrier_catches_an_acknowledged_batch_that_never_applies(
        self,
        server_mode: QdrantSupervisor,
        tmp_path: Path,
    ) -> None:
        """A wrong-named-vector batch is acknowledged and silently dropped.

        The server returns success for an upsert naming an unknown vector
        when the apply is deferred, and never applies or reports it. Only
        the barrier's exact count catches the loss - this is the injected
        shortfall, and the assertion below is the one a removed or
        weakened barrier turns vacuous.
        """
        from qdrant_client import QdrantClient, models

        store = VaultStore(tmp_path)
        try:
            store.ensure_code_table()
            dimension = int(get_config().embedding_dimension)
            chunks = _make_code_chunks(6, dimension)
            store.upsert_code_chunks(chunks, write_policy=None, wait=False)

            raw = QdrantClient(url=server_mode.url)
            try:
                raw.upsert(
                    collection_name=store.CODE_TABLE_NAME,
                    points=[
                        models.PointStruct(
                            id=10_000_001,
                            vector={"bogus": [0.5] * dimension},
                            payload={"id": "poisoned"},
                        )
                    ],
                    wait=False,
                )
            finally:
                raw.close()

            with pytest.raises(IngestVerificationError, match="expected 7"):
                store.apply_ingest_barrier(
                    store.CODE_TABLE_NAME,
                    expected_points=len(chunks) + 1,
                )
        finally:
            store.close()

    def test_barrier_is_inert_for_the_embedded_backend(
        self,
        tmp_path: Path,
    ) -> None:
        """Local mode has no wait semantics; the barrier must not engage."""
        reset_config()
        store = VaultStore(tmp_path)
        try:
            assert store._server_mode is False
            store.ensure_code_table()
            chunks = _make_code_chunks(3, int(get_config().embedding_dimension))
            # The embedded engine applies synchronously; wait is ignored.
            store.upsert_code_chunks(chunks, write_policy=None, wait=False)
            # A wildly wrong expectation must not raise: the barrier is
            # a server-mode contract and local behavior stays unchanged.
            store.apply_ingest_barrier(store.CODE_TABLE_NAME, expected_points=999)
            assert store.count_code() == len(chunks)
        finally:
            store.close()


class _VanishingChunkStore(VaultStore):
    """The real store, plus a backend that loses acknowledged chunk points.

    Every vault-chunk upsert runs the production path unmodified; the
    freshly acknowledged points are then deleted server-side with
    ``wait=True``, so the collection genuinely lacks them by the time
    the rebuild reaches its barrier.
    """

    def __init__(self, root: Path, raw: Any) -> None:
        super().__init__(root)
        self._raw_client = raw

    def upsert_document_chunks(
        self,
        chunks: list[VaultChunk],
        *,
        write_policy: StoreWritePolicy | None,
        wait: bool = True,
    ) -> None:
        from qdrant_client import models

        super().upsert_document_chunks(chunks, write_policy=write_policy, wait=wait)
        self._raw_client.delete(
            collection_name=self.TABLE_NAME,
            points_selector=models.PointIdsList(
                points=[self._stable_id(chunk.point_key) for chunk in chunks],
            ),
            wait=True,
        )


class _PoisonedThroughWriterStore(VaultStore):
    """Real store that swaps one chunk's write for an acknowledged no-apply.

    The swap happens inside ``upsert_document_chunks`` itself, so during a
    production rebuild it executes on the slice-writer thread: one chunk's
    point is written through the raw client with an unknown named vector
    (the proven acknowledged-but-never-applied class) while the remainder
    of the slice takes the production path unmodified. The recorded thread
    idents prove the injection rode the writer, not the encoding caller.
    """

    def __init__(self, root: Path, raw: Any) -> None:
        super().__init__(root)
        self._raw_client = raw
        self.upsert_threads: list[int] = []
        self._poisoned = False

    def upsert_document_chunks(
        self,
        chunks: list[VaultChunk],
        *,
        write_policy: StoreWritePolicy | None,
        wait: bool = True,
    ) -> None:
        import threading

        from qdrant_client import models

        self.upsert_threads.append(threading.get_ident())
        delivered = chunks
        if not self._poisoned and chunks:
            victim, delivered = chunks[0], chunks[1:]
            self._poisoned = True
            dimension = int(get_config().embedding_dimension)
            self._raw_client.upsert(
                collection_name=self.TABLE_NAME,
                points=[
                    models.PointStruct(
                        id=self._stable_id(victim.point_key),
                        vector={"bogus": [0.5] * dimension},
                        payload={"id": victim.point_key},
                    )
                ],
                wait=False,
            )
        if delivered:
            super().upsert_document_chunks(
                delivered,
                write_policy=write_policy,
                wait=wait,
            )


class TestBarrierComposesWithSliceWriter:
    """The terminal barrier drains the writer queue and verifies its writes."""

    def test_rebuild_fails_at_barrier_when_writer_carried_a_silent_drop(
        self,
        server_mode: QdrantSupervisor,
        tmp_path: Path,
    ) -> None:
        """A writer-carried acknowledged-never-applied point fails the run.

        The production vault rebuild hands every upsert to the single
        slice-writer thread; the poisoned store swaps one chunk for a
        wrong-named-vector write the server acknowledges and silently
        drops. Only the barrier's exact count - which runs after the
        writer queue drains and before stale-purge or metadata publish -
        can reject the run. Weakening the barrier's count comparison
        makes the rebuild "succeed" over the missing point, turning the
        raises-assertion below red; that is the mutation this test
        exists to catch.
        """
        import threading

        from qdrant_client import QdrantClient

        from ...indexer import VaultIndexer

        build_synthetic_vault(tmp_path, n_docs=4, seed=7)
        raw = QdrantClient(url=server_mode.url)
        store = _PoisonedThroughWriterStore(tmp_path, raw)
        indexer = VaultIndexer(
            tmp_path,
            cast("Any", _DeterministicCpuModel()),
            store,
        )
        caller = threading.get_ident()
        try:
            with pytest.raises(IngestVerificationError):
                indexer.full_index(reporter=NullProgressReporter())
            assert not indexer._meta_path.exists(), (
                "terminal metadata was published over a writer-carried silent drop"
            )
            assert store.upsert_threads, "the rebuild never reached storage"
            assert all(ident != caller for ident in store.upsert_threads), (
                "upserts ran inline on the encoding thread; the injection "
                "never rode the slice writer"
            )
        finally:
            raw.close()
            store.close()


class TestTerminalStateNeverPrecedesAppliedPoints:
    """A rebuild whose points did not apply must fail before metadata."""

    def test_vault_rebuild_fails_before_metadata_when_points_vanish(
        self,
        server_mode: QdrantSupervisor,
        tmp_path: Path,
    ) -> None:
        """Points deleted between acknowledgement and barrier fail the run.

        The sabotage wraps the store's chunk upsert to remove the freshly
        acknowledged points server-side (a real backend-state shortfall),
        then runs the production vault rebuild. The barrier must fail the
        job before the stale purge and before ``_save_meta`` publishes
        terminal metadata. Removing or weakening the barrier makes the
        rebuild "succeed" over an empty collection, turning both
        assertions red.
        """
        from qdrant_client import QdrantClient

        from ...indexer import VaultIndexer

        build_synthetic_vault(tmp_path, n_docs=4, seed=7)
        raw = QdrantClient(url=server_mode.url)
        # The real store with one injected backend loss: every chunk
        # upsert completes for real, then the acknowledged points are
        # deleted server-side so the collection genuinely lacks them.
        store = _VanishingChunkStore(tmp_path, raw)
        indexer = VaultIndexer(
            tmp_path,
            cast("Any", _DeterministicCpuModel()),
            store,
        )
        try:
            with pytest.raises(IngestVerificationError):
                indexer.full_index(reporter=NullProgressReporter())
            assert not indexer._meta_path.exists(), (
                "terminal metadata was published over unapplied points"
            )
        finally:
            raw.close()
            store.close()

    def test_vault_rebuild_publishes_metadata_when_points_apply(
        self,
        server_mode: QdrantSupervisor,  # noqa: ARG002  # activates the URL env seam
        tmp_path: Path,
    ) -> None:
        """The happy rebuild passes the barrier and publishes terminally."""
        from ...indexer import VaultIndexer

        build_synthetic_vault(tmp_path, n_docs=4, seed=7)
        store = VaultStore(tmp_path)
        indexer = VaultIndexer(
            tmp_path,
            cast("Any", _DeterministicCpuModel()),
            store,
        )
        try:
            result = indexer.full_index(reporter=NullProgressReporter())
            assert result.added > 0
            assert indexer._meta_path.exists()
            assert store.count() > 0
        finally:
            store.close()
