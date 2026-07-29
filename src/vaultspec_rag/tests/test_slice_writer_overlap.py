"""Real-object coverage for the writer-side encode/upsert overlap pipeline.

These tests drive the real vault streaming path against a real local Qdrant
store in a temp dir, with latency injected by subclassing the store's own
upsert (no mocks of the pipeline under test). The encoder is a minimal
deterministic object satisfying the same structural protocol the production
model exposes, so thread ownership and overlap are observable without a GPU.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from .._store_models import VaultChunk, VaultDocument

if TYPE_CHECKING:
    from pathlib import Path

    from .._store_writes import StoreWritePolicy
    from ..embeddings import EmbeddingModel
from ..indexer._streaming import (
    StoreWriteTask,
    UnsettledStoreWriterError,
    VaultStreamRequest,
    _release_cuda_cache,
    _SliceWriter,
    _stream_encode_and_upsert_vault,
)
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore

pytestmark = [pytest.mark.unit]

_DIM = 8


@dataclass(slots=True)
class _SparseRow:
    indices: list[int] = field(default_factory=lambda: [0])
    values: list[float] = field(default_factory=lambda: [1.0])


class _RecordingEncoder:
    """Deterministic encoder recording per-call spans and thread identity."""

    device = "cpu"

    def __init__(self, *, encode_seconds: float = 0.0) -> None:
        self._encode_seconds = encode_seconds
        self.encode_spans: list[tuple[float, float]] = []
        self.encode_threads: list[int] = []
        self.encoded_slices: list[list[str]] = []
        self.seen_batch_sizes: list[int | None] = []
        self.seen_gpu_locks: list[threading.Lock | None] = []

    def encode_documents_on_device(
        self,
        texts: list[str],
        batch_size: int | None = None,
        gpu_lock: threading.Lock | None = None,
        on_bucket: object | None = None,
    ) -> list[list[float]]:
        del on_bucket
        started = time.monotonic()
        self.seen_batch_sizes.append(batch_size)
        self.seen_gpu_locks.append(gpu_lock)
        self.encode_threads.append(threading.get_ident())
        self.encoded_slices.append(list(texts))
        if self._encode_seconds:
            time.sleep(self._encode_seconds)
        rows = [[float(len(text) % 7) + 0.25] * _DIM for text in texts]
        self.encode_spans.append((started, time.monotonic()))
        return rows

    def encode_documents_sparse(
        self,
        texts: list[str],
        batch_size: int | None = None,
        gpu_lock: threading.Lock | None = None,
    ) -> list[_SparseRow]:
        self.seen_batch_sizes.append(batch_size)
        self.seen_gpu_locks.append(gpu_lock)
        return [_SparseRow() for _ in texts]


class _SlowUpsertStore(VaultStore):
    """Real local store whose vault upsert carries injected latency."""

    def __init__(self, root: Path, *, latency_seconds: float) -> None:
        super().__init__(root, embedding_dim=_DIM)
        self._latency_seconds = latency_seconds
        self.upsert_windows: list[tuple[float, float]] = []
        self.upsert_threads: list[int] = []
        self.upserted_slices: list[list[str]] = []

    def upsert_document_chunks(
        self,
        chunks: list[VaultChunk],
        *,
        write_policy: StoreWritePolicy | None,
        wait: bool = True,
    ) -> None:
        started = time.monotonic()
        self.upsert_threads.append(threading.get_ident())
        time.sleep(self._latency_seconds)
        super().upsert_document_chunks(chunks, write_policy=write_policy, wait=wait)
        self.upsert_windows.append((started, time.monotonic()))
        self.upserted_slices.append(
            [f"{chunk.doc_id}#c{chunk.ordinal}" for chunk in chunks]
        )


class _FailingUpsertStore(VaultStore):
    """Real local store whose vault upsert fails on the second slice."""

    def __init__(self, root: Path) -> None:
        super().__init__(root, embedding_dim=_DIM)
        self.upsert_calls = 0

    def upsert_document_chunks(
        self,
        chunks: list[VaultChunk],
        *,
        write_policy: StoreWritePolicy | None,
        wait: bool = True,
    ) -> None:
        self.upsert_calls += 1
        if self.upsert_calls == 2:
            raise RuntimeError("injected upsert failure")
        super().upsert_document_chunks(chunks, write_policy=write_policy, wait=wait)


def _doc(index: int) -> VaultDocument:
    return VaultDocument(
        id=f"research/doc-{index:02d}",
        path=f"research/doc-{index:02d}.md",
        doc_type="research",
        feature="feature-x",
        date="2026-01-01",
        tags=["#research", "#feature-x"],
        related=[],
        title=f"Doc {index}",
        status="",
        content=f"short body {index} " + ("x" * (10 + index)),
        vector=[],
    )


def _stream(
    store: VaultStore,
    encoder: _RecordingEncoder,
    *,
    n_docs: int = 6,
    slice_size: int = 2,
) -> dict[str, int]:
    # The encoder satisfies the streaming path's structural encode protocol;
    # the cast keeps the real GPU model out of a threading/timing test.
    return _stream_encode_and_upsert_vault(
        VaultStreamRequest(
            docs=[_doc(index) for index in range(n_docs)],
            slice_size=slice_size,
            model=cast("EmbeddingModel", encoder),
            store=store,
            gpu_lock=threading.Lock(),
            reporter=NullProgressReporter(),
        )
    )


class TestVaultEncodeUpsertOverlap:
    """The vault path must overlap slice N's upsert with slice N+1's encode."""

    def test_next_slice_encode_starts_while_prior_upsert_is_in_flight(
        self,
        tmp_path: Path,
    ) -> None:
        # Latency injection: upserts are slow enough that, with overlap, at
        # least one later encode must begin inside an earlier upsert's
        # in-flight window. A mutation that moves the upsert back inline on
        # the encoding thread serializes the two and turns this red.
        # Warm the lazy torch import behind the per-slice cache flush first,
        # so its one-off cost cannot serialize the timed windows.
        _release_cuda_cache()
        store = _SlowUpsertStore(tmp_path, latency_seconds=0.4)
        encoder = _RecordingEncoder(encode_seconds=0.05)
        counts = _stream(store, encoder)
        assert len(store.upsert_windows) == 3
        overlapped = any(
            upsert_start <= encode_start < upsert_end
            for encode_start, _encode_end in encoder.encode_spans[1:]
            for upsert_start, upsert_end in store.upsert_windows
        )
        assert overlapped, "no encode started while an upsert was in flight"
        assert set(counts.values()) == {1}

    def test_exactly_one_writer_thread_and_encode_stays_on_the_caller(
        self,
        tmp_path: Path,
    ) -> None:
        store = _SlowUpsertStore(tmp_path, latency_seconds=0.05)
        encoder = _RecordingEncoder()
        caller = threading.get_ident()
        _stream(store, encoder)
        # One writer thread only: a mutation adding a second writer (or any
        # second storage consumer) makes this set grow past one.
        assert len(set(store.upsert_threads)) == 1
        # Upserts moved off the encoding thread: a mutation that calls the
        # store inline on the encoding thread turns this assertion red.
        assert store.upsert_threads[0] != caller
        # The caller stays the only encode (GPU-consumer) thread.
        assert set(encoder.encode_threads) == {caller}

    def test_slices_are_stored_in_encode_order(self, tmp_path: Path) -> None:
        store = _SlowUpsertStore(tmp_path, latency_seconds=0.05)
        encoder = _RecordingEncoder()
        _stream(store, encoder)

        # The single FIFO writer preserves the encode-submission order, so
        # storage confirmations land in exact slice order. Each embed text is
        # "Doc {n}\n\n{body}", mapping back to the doc id that was upserted.
        def _expected_ids(texts: list[str]) -> list[str]:
            return [
                f"research/doc-{int(text.splitlines()[0].split()[1]):02d}#c0"
                for text in texts
            ]

        assert store.upserted_slices == [
            _expected_ids(texts) for texts in encoder.encoded_slices
        ]

    def test_a_writer_failure_fails_the_run(self, tmp_path: Path) -> None:
        store = _FailingUpsertStore(tmp_path)
        encoder = _RecordingEncoder()
        # The failure surfaces on the encoding side, so callers never reach
        # their stale-purge or metadata-publish steps. A mutation that stops
        # recording the writer's failure turns this into a silent success.
        with pytest.raises(RuntimeError, match="injected upsert failure"):
            _stream(store, encoder)


class TestSliceWriterContract:
    """Direct coverage of the writer thread's ordering and shutdown bounds."""

    def test_tasks_run_in_submission_order_on_one_thread(self) -> None:
        writer = _SliceWriter(name="order-writer", max_pending=2)
        executed: list[int] = []
        threads: list[int] = []

        def _work(index: int) -> None:
            threads.append(threading.get_ident())
            time.sleep(0.01 if index % 2 else 0.03)
            executed.append(index)

        for index in range(6):
            writer.submit(
                StoreWriteTask(
                    write=lambda index=index: _work(index),
                    release=lambda: None,
                )
            )
        writer.close()
        assert executed == list(range(6))
        assert len(set(threads)) == 1

    def test_failure_releases_later_tasks_without_writing_them(self) -> None:
        writer = _SliceWriter(name="failing-writer", max_pending=4)
        written: list[int] = []
        released: list[int] = []

        def _fail() -> None:
            raise RuntimeError("injected write failure")

        writer.submit(StoreWriteTask(write=_fail, release=lambda: released.append(0)))
        writer.submit(
            StoreWriteTask(
                write=lambda: written.append(1),
                release=lambda: released.append(1),
            )
        )
        with pytest.raises(RuntimeError, match="injected write failure"):
            writer.close()
        # After the first failure the writer only releases queued work; the
        # forbidden thing this guards is a later slice being published on top
        # of a failed earlier one.
        assert written == []
        assert released == [0, 1]

    def test_submit_after_failure_reraises_and_leaves_the_task_unwritten(
        self,
    ) -> None:
        writer = _SliceWriter(name="post-failure-writer")

        def _fail() -> None:
            raise RuntimeError("injected write failure")

        writer.submit(StoreWriteTask(write=_fail, release=lambda: None))
        deadline = time.monotonic() + 5.0
        while writer.failure is None and time.monotonic() < deadline:
            time.sleep(0.01)
        with pytest.raises(RuntimeError, match="injected write failure"):
            writer.submit(StoreWriteTask(write=lambda: None, release=lambda: None))
        with pytest.raises(RuntimeError, match="injected write failure"):
            writer.close()

    def test_wedged_writer_close_raises_within_its_bound(self) -> None:
        # Wedge safety: close() must log-and-raise within its shutdown bound
        # rather than wait forever on a stuck store call. The helper thread's
        # bounded join is this test's own timeout guard - a mutation removing
        # the shutdown deadline makes close() hang and turns the liveness
        # assertion red instead of hanging the suite.
        writer = _SliceWriter(
            name="wedged-writer",
            shutdown_timeout_seconds=0.5,
        )
        unwedge = threading.Event()

        def _wedged_write() -> None:
            unwedge.wait(20.0)

        writer.submit(StoreWriteTask(write=_wedged_write, release=lambda: None))
        outcome: dict[str, BaseException] = {}

        def _close() -> None:
            try:
                writer.close()
            except BaseException as exc:
                outcome["raised"] = exc

        closer = threading.Thread(target=_close, name="wedge-closer")
        started = time.monotonic()
        closer.start()
        closer.join(timeout=10.0)
        try:
            assert not closer.is_alive(), "close() hung past its shutdown bound"
            assert isinstance(outcome.get("raised"), UnsettledStoreWriterError)
            assert time.monotonic() - started < 10.0
        finally:
            unwedge.set()
            closer.join(timeout=10.0)
