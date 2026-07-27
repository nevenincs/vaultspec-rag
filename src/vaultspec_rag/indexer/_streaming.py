"""Streaming embed-and-upsert helpers shared by both indexers.

Encodes dense + sparse vectors slice-by-slice and upserts each slice
immediately, flushing the CUDA caching allocator at every boundary to
keep peak memory bounded (the #68 RSS-leak fix).
"""

from __future__ import annotations

import logging
import queue
import time
from dataclasses import dataclass
from functools import partial
from itertools import chain, pairwise
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from ..job_control import NO_RUN_CONTROL, timed_gpu_lock

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from .._store_models import (
        CodeChunk,
        DocumentChunk,
        VaultChunk,
        VaultDocument,
    )
    from .._store_writes import StoreWritePolicy
    from ..embeddings import EmbeddingModel
    from ..job_control import RunControl
    from ..memory_probe import MemoryProbe
    from ..progress import ProgressReporter
    from ..store_runtime import VaultStore
    from ._reuse import DonorReuseContext

logger = logging.getLogger(__name__)

__all__ = [
    "CodeFileSegment",
    "CodeFileSegmentRequest",
    "CodeSliceRequest",
    "CodebaseStreamRequest",
    "DocumentSliceRequest",
    "DocumentSliceStreamRequest",
    "StoreWriteTask",
    "UnsettledStoreWriterError",
    "VaultStreamRequest",
    "WeightedCodeSlice",
    "WeightedDocumentSlice",
    "_SliceWriter",
    "_release_cuda_cache",
    "_stream_encode_and_upsert_codebase",
    "_stream_encode_and_upsert_vault",
    "encode_and_upsert_code_slice",
    "encode_and_upsert_document_slice",
    "estimate_code_chunk_bytes",
    "estimate_document_chunk_bytes",
    "iter_code_file_segments",
    "iter_weighted_code_slices",
    "iter_weighted_document_slices",
]

# Polling bound for every wait against the writer-side queue, so cooperative
# control and failure checks run between bounded blocking attempts.
_WRITER_POLL_SECONDS = 0.1

# Upper bound on how long writer shutdown waits for the writer thread to
# drain its final upsert and terminate. Generous for any healthy final store
# write yet finite, so a wedged Qdrant call escalates to a raised error
# instead of hanging the encoding thread under the indexer's writer lock.
_WRITER_SHUTDOWN_TIMEOUT_S = 300.0


# Conservative 64-bit CPython lifetime estimates. A dense element exists once
# in the float32 encode output and once as a Python float/list slot while the
# store point is built. A sparse entry exists as native index/value data plus
# two Python list entries. The fixed allowance covers the dataclass, payload
# mapping, Qdrant model, and the small containers joining those objects.
_DENSE_ELEMENT_LIFETIME_BYTES = 4 + 8 + 24
_SPARSE_ENTRY_LIFETIME_BYTES = 8 + 4 + (2 * 8) + 28 + 24
_POINT_FIXED_OVERHEAD_BYTES = 1024
_DEFAULT_SPARSE_DIMENSION = 30_522


@dataclass(frozen=True, slots=True)
class _CodeSegmentLimits:
    """Resolved memory and chunk limits for one segment stream."""

    max_chunks: int
    max_bytes: int
    dense_dimension: int
    sparse_enabled: bool
    sparse_dimension: int


@dataclass(frozen=True, slots=True)
class VaultStreamRequest:
    docs: list[VaultDocument]
    slice_size: int
    model: EmbeddingModel
    store: VaultStore
    gpu_lock: threading.Lock | None
    reporter: ProgressReporter
    ingest_wait: bool = True
    run_control: RunControl = NO_RUN_CONTROL
    reuse: DonorReuseContext | None = None


@dataclass(frozen=True, slots=True)
class DocumentSliceRequest:
    chunks: list[DocumentChunk]
    model: EmbeddingModel
    store: VaultStore
    gpu_lock: threading.Lock | None
    release_cache: bool = True
    encode_batch_size: int | None = None
    write_policy: StoreWritePolicy | None = None
    on_storage_confirmed: Callable[[], None] | None = None
    after_forward: Callable[[str], None] | None = None
    on_cuda_oom: Callable[[BaseException], None] | None = None
    run_control: RunControl = NO_RUN_CONTROL
    reuse: DonorReuseContext | None = None
    writer: _SliceWriter | None = None


@dataclass(frozen=True, slots=True)
class DocumentSliceStreamRequest:
    chunks: Iterable[DocumentChunk]
    max_chunks: int | None = None
    max_bytes: int | None = None
    dense_dimension: int | None = None
    sparse_enabled: bool | None = None
    sparse_dimension: int | None = None
    run_control: RunControl = NO_RUN_CONTROL


@dataclass(frozen=True, slots=True)
class CodeFileSegmentRequest:
    chunks: Iterable[CodeChunk]
    max_chunks: int | None = None
    max_bytes: int | None = None
    dense_dimension: int | None = None
    sparse_enabled: bool | None = None
    sparse_dimension: int | None = None
    run_control: RunControl = NO_RUN_CONTROL


@dataclass(frozen=True, slots=True)
class CodeSliceRequest:
    chunks: list[CodeChunk]
    model: EmbeddingModel
    store: VaultStore
    gpu_lock: threading.Lock | None
    release_cache: bool = True
    encode_batch_size: int | None = None
    write_policy: StoreWritePolicy | None = None
    ingest_wait: bool = True
    on_storage_confirmed: Callable[[], None] | None = None
    after_forward: Callable[[str], None] | None = None
    on_cuda_oom: Callable[[BaseException], None] | None = None
    run_control: RunControl = NO_RUN_CONTROL
    reuse: DonorReuseContext | None = None
    collection: str | None = None


@dataclass(frozen=True, slots=True)
class CodebaseStreamRequest:
    chunks: list[CodeChunk]
    slice_size: int
    model: EmbeddingModel
    store: VaultStore
    gpu_lock: threading.Lock | None
    reporter: ProgressReporter
    run_control: RunControl = NO_RUN_CONTROL
    reuse: DonorReuseContext | None = None


@dataclass(frozen=True, slots=True)
class WeightedDocumentSlice:
    """One document slice with an exact conservative retained-byte weight."""

    chunks: tuple[DocumentChunk, ...]
    estimated_bytes: int

    def __post_init__(self) -> None:
        if not self.chunks:
            raise ValueError("document slices must contain at least one chunk")
        if self.estimated_bytes <= 0:
            raise ValueError("document slice weight must be positive")


def _validate_segment_transition(
    previous: CodeFileSegment,
    current: CodeFileSegment,
) -> None:
    """Validate one deterministic file/ordinal transition."""
    if previous.path == current.path:
        if previous.is_file_end or current.ordinal != previous.ordinal + 1:
            raise ValueError(
                "same-file segments must be contiguous and cannot follow "
                "a file-end marker"
            )
    elif not previous.is_file_end or current.ordinal != 0:
        raise ValueError(
            "a new file in one weighted stream must follow a file-end marker "
            "and begin at ordinal zero"
        )


@dataclass(frozen=True, slots=True)
class CodeFileSegment:
    """One ordered, weighted, file-local code indexing unit.

    ``ordinal`` is zero-based within the file and ``is_file_end`` marks the
    only segment after which a later ledger may declare that file complete.
    The tuple owns only references to the bounded active chunks; callers must
    discard the segment after its confirmed store mutation.
    """

    path: str
    ordinal: int
    chunks: tuple[CodeChunk, ...]
    estimated_bytes: int
    is_file_end: bool

    def __post_init__(self) -> None:
        """Reject malformed durable-unit boundaries at construction time."""
        if isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError(
                f"segment ordinal must be a non-negative integer, got {self.ordinal!r}"
            )
        if not self.chunks:
            raise ValueError("code file segments must contain at least one chunk")
        if isinstance(self.estimated_bytes, bool) or self.estimated_bytes <= 0:
            raise ValueError(
                "segment estimated_bytes must be a positive integer, "
                f"got {self.estimated_bytes!r}"
            )
        mismatched = next(
            (chunk.path for chunk in self.chunks if chunk.path != self.path),
            None,
        )
        if mismatched is not None:
            raise ValueError(
                "code file segment cannot cross file boundaries: "
                f"expected {self.path!r}, got {mismatched!r}"
            )


@dataclass(frozen=True, slots=True)
class WeightedCodeSlice:
    """One bounded encode/upsert slice retaining its file-unit boundaries."""

    segments: tuple[CodeFileSegment, ...]
    chunks: tuple[CodeChunk, ...]
    estimated_bytes: int

    def __post_init__(self) -> None:
        """Keep segment order, chunk ownership, and byte weight exact."""
        if not self.segments:
            raise ValueError("weighted code slices must contain at least one segment")
        if not self.chunks:
            raise ValueError("weighted code slices must contain at least one chunk")
        if isinstance(self.estimated_bytes, bool) or self.estimated_bytes <= 0:
            raise ValueError(
                "slice estimated_bytes must be a positive integer, "
                f"got {self.estimated_bytes!r}"
            )

        flattened = tuple(
            chunk for segment in self.segments for chunk in segment.chunks
        )
        if len(flattened) != len(self.chunks) or any(
            actual is not expected
            for actual, expected in zip(flattened, self.chunks, strict=True)
        ):
            raise ValueError(
                "weighted code slice chunks must exactly flatten its ordered segments"
            )
        segment_bytes = sum(segment.estimated_bytes for segment in self.segments)
        if segment_bytes != self.estimated_bytes:
            raise ValueError(
                "weighted code slice byte total does not match its segments: "
                f"expected {segment_bytes}, got {self.estimated_bytes}"
            )

        for previous, current in pairwise(self.segments):
            _validate_segment_transition(previous, current)


@runtime_checkable
class _CpuTransferable(Protocol):
    """Structural protocol for accelerator-backed array/tensor results."""

    def cpu(self) -> object: ...


@runtime_checkable
class _ListConvertible(Protocol):
    """Structural protocol shared by NumPy rows and Torch tensors."""

    def tolist(self) -> object: ...


@runtime_checkable
class _DenseRowIterable(Protocol):
    """Structural protocol for dense result batches."""

    def __iter__(self) -> Iterator[object]: ...


class _SparseVectorLike(Protocol):
    """Sparse row shape consumed by store-ready chunk fields."""

    indices: list[int]
    values: list[float]


def _release_cuda_cache() -> None:
    """Return unused CUDA caching-allocator blocks to the driver.

    Called between embedding slices to prevent the allocator from
    growing unboundedly as per-batch activation buffers accumulate -
    the root cause of the 24 GB RSS leak documented in issue #68.
    Safe no-op when torch is unavailable.
    """
    try:
        import torch
    except ImportError as exc:
        logger.debug("torch unavailable; CUDA cache flush skipped: %s", exc)
        return
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _transfer_to_cpu(value: object) -> object:
    """Return ``value`` on CPU when it exposes the tensor ``cpu`` protocol.

    Ordinary dense callers receive a CPU NumPy array. Index streaming requests
    an accelerator tensor and crosses this boundary immediately after the
    caller releases ``gpu_lock``. The structural check keeps both forms lazy
    without adding an eager Torch import to this module.
    """
    if isinstance(value, _CpuTransferable):
        return value.cpu()
    return value


def _dense_rows(value: object) -> Iterable[object]:
    """Validate and expose rows from a CPU dense-embedding result."""
    if not isinstance(value, _DenseRowIterable):
        msg = f"dense encoder returned a non-iterable result: {type(value).__name__}"
        raise TypeError(msg)
    return value


def _dense_vector_to_list(value: object) -> list[float]:
    """Map one already-transferred dense row to the store's list shape."""
    cpu_value = _transfer_to_cpu(value)
    if isinstance(cpu_value, list):
        return cast("list[float]", cpu_value)
    if not isinstance(cpu_value, _ListConvertible):
        msg = (
            "dense encoder row cannot be converted to a list: "
            f"{type(cpu_value).__name__}"
        )
        raise TypeError(msg)
    values = cpu_value.tolist()
    if not isinstance(values, list):
        msg = f"dense encoder row produced {type(values).__name__}, expected list"
        raise TypeError(msg)
    return cast("list[float]", values)


def _release_vector_fields(
    chunks: Iterable[CodeChunk | DocumentChunk | VaultChunk],
) -> None:
    """Release vector-bearing fields retained by chunk objects."""
    for chunk in chunks:
        chunk.vector.clear()
        chunk.sparse_indices.clear()
        chunk.sparse_values.clear()


def _populate_vector_fields(
    chunks: Sequence[CodeChunk | DocumentChunk | VaultChunk],
    dense_cpu: object,
    sparse: Iterable[_SparseVectorLike | None],
) -> None:
    """Attach already-CPU dense and sparse rows to one bounded chunk slice."""
    for chunk, vec, sparse_row in zip(
        chunks,
        _dense_rows(dense_cpu),
        sparse,
        strict=True,
    ):
        chunk.vector = _dense_vector_to_list(vec)
        if sparse_row is None:
            chunk.sparse_indices = []
            chunk.sparse_values = []
            continue
        chunk.sparse_indices = list(sparse_row.indices)
        chunk.sparse_values = list(sparse_row.values)


def _adopt_donor_vectors(
    reuse: DonorReuseContext,
    chunks: Sequence[CodeChunk | DocumentChunk | VaultChunk],
    slice_texts: list[str],
    *,
    sparse_enabled: bool,
) -> tuple[Sequence[CodeChunk | DocumentChunk | VaultChunk], list[str]]:
    """Adopt verified donor vectors and return only the miss sub-slice.

    Runs on the calling consumer thread, strictly before (and outside) any
    ``gpu_lock`` acquisition. Hits leave this function already carrying
    their store-ready vector fields; the returned chunk/text pair stays
    position-aligned because both sides are filtered by the same hit mask
    under one strict zip - the alignment invariant the later
    ``_populate_vector_fields`` strict zip then preserves for the misses.
    """
    hit_mask = reuse.adopt_verified_vectors(chunks, sparse_required=sparse_enabled)
    if not any(hit_mask):
        return chunks, slice_texts
    misses = [
        (chunk, text)
        for chunk, text, hit in zip(chunks, slice_texts, hit_mask, strict=True)
        if not hit
    ]
    return [chunk for chunk, _text in misses], [text for _chunk, text in misses]


@dataclass(frozen=True, slots=True)
class _VectorEncodeRequest:
    """All model and lifecycle inputs for one bounded vector encode."""

    chunks: Sequence[CodeChunk | DocumentChunk | VaultChunk]
    slice_texts: list[str]
    model: EmbeddingModel
    gpu_lock: threading.Lock | None
    sparse_enabled: bool
    encode_batch_size: int | None
    after_encode: Callable[[], None] | None = None
    after_forward: Callable[[str], None] | None = None
    on_cuda_oom: Callable[[BaseException], None] | None = None
    reuse: DonorReuseContext | None = None


def _encode_slice_vector_fields(request: _VectorEncodeRequest) -> None:
    """Populate one bounded slice, dropping all array/tensor owners on return."""
    chunks = request.chunks
    slice_texts = request.slice_texts
    model = request.model
    gpu_lock = request.gpu_lock
    sparse_enabled = request.sparse_enabled
    encode_batch_size = request.encode_batch_size
    after_encode = request.after_encode
    after_forward = request.after_forward
    on_cuda_oom = request.on_cuda_oom
    reuse = request.reuse
    if reuse is not None:
        chunks, slice_texts = _adopt_donor_vectors(
            reuse,
            chunks,
            slice_texts,
            sparse_enabled=sparse_enabled,
        )
        if not chunks:
            # Every point was adopted from a donor: no forward pass runs and
            # the GPU is never touched for this slice. ``after_encode`` still
            # fires so caller-side accounting (memory-probe checkpoints)
            # stays balanced; ``after_forward`` does not, because no forward
            # happened.
            if after_encode is not None:
                after_encode()
            return
    encode_started = time.perf_counter()
    dense_device: object | None = None
    dense_cpu: object | None = None
    sparse: Iterable[_SparseVectorLike | None] | None = None
    try:
        with timed_gpu_lock(gpu_lock):
            dense_device = model.encode_documents_on_device(
                slice_texts,
                batch_size=encode_batch_size,
            )
        if after_forward is not None:
            after_forward("dense")
        dense_cpu = _transfer_to_cpu(dense_device)
        dense_device = None
        if sparse_enabled:
            sparse = model.encode_documents_sparse(
                slice_texts,
                batch_size=encode_batch_size,
                gpu_lock=gpu_lock,
            )
            if after_forward is not None:
                after_forward("sparse")
        else:
            sparse = [None] * len(slice_texts)
        if after_encode is not None:
            after_encode()
        _populate_vector_fields(chunks, dense_cpu, sparse)
        if reuse is not None:
            reuse.stats.record_encode(
                time.perf_counter() - encode_started,
                len(chunks),
            )
    except Exception as exc:
        from .._gpu import is_cuda_out_of_memory

        if on_cuda_oom is not None and is_cuda_out_of_memory(exc):
            on_cuda_oom(exc)
        raise
    finally:
        # Chunk fields own the store-ready lists. Drop accelerator/CPU arrays
        # and the embedding-text copies before Qdrant builds point models.
        del dense_device
        del dense_cpu
        del sparse
        del slice_texts


@dataclass(slots=True)
class StoreWriteTask:
    """One ordered storage hand-off from the encoding thread.

    ``write`` performs the synchronous store mutation plus any
    storage-confirmed accounting; ``release`` drops the slice's vector-bearing
    fields and always runs once the task settles, successful or not.
    """

    write: Callable[[], None]
    release: Callable[[], None]


class UnsettledStoreWriterError(RuntimeError):
    """The store writer thread remained live after its bounded shutdown wait."""


class _SliceWriter:
    """Single writer thread draining a bounded queue of store-write tasks.

    Overlaps slice N's storage I/O with slice N+1's encode while the calling
    (encoding) thread remains the only thread touching the GPU: the writer
    performs storage work exclusively and never acquires ``gpu_lock``. Tasks
    execute in submission order on one thread, so storage confirmations and
    checkpoints land in slice order. After the first task failure the writer
    stops writing and only releases the remaining tasks' vector fields; the
    recorded failure re-raises on the encoding side at the next ``submit`` or
    at ``close``. Every shutdown wait (the sentinel put and the join) is
    liveness-guarded and time-bounded so a wedged store call aborts the run
    rather than hanging it.
    """

    __slots__ = ("_failure", "_poll_seconds", "_queue", "_shutdown_timeout", "_thread")

    def __init__(
        self,
        *,
        name: str,
        max_pending: int = 2,
        poll_seconds: float = _WRITER_POLL_SECONDS,
        shutdown_timeout_seconds: float = _WRITER_SHUTDOWN_TIMEOUT_S,
    ) -> None:
        import threading

        if isinstance(max_pending, bool) or max_pending <= 0:
            raise ValueError("max_pending must be a positive integer")
        self._queue: queue.Queue[StoreWriteTask | None] = queue.Queue(
            maxsize=max_pending
        )
        self._poll_seconds = poll_seconds
        self._shutdown_timeout = shutdown_timeout_seconds
        self._failure: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name=name)
        self._thread.start()

    def _run(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                return
            try:
                if self._failure is None:
                    task.write()
            except BaseException as exc:
                self._failure = exc
            finally:
                task.release()

    @property
    def failure(self) -> BaseException | None:
        """Return the first recorded write failure, if any."""
        return self._failure

    def _raise_if_failed(self) -> None:
        if self._failure is not None:
            raise self._failure

    def submit(
        self,
        task: StoreWriteTask,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Queue one write task, re-raising any already-recorded failure.

        The caller retains cleanup responsibility for ``task`` until this
        method returns: on any raise here the task was not accepted and its
        ``release`` has not run.
        """
        while True:
            run_control.checkpoint()
            self._raise_if_failed()
            if not self._thread.is_alive():
                raise RuntimeError("store writer terminated unexpectedly")
            try:
                self._queue.put(task, timeout=self._poll_seconds)
            except queue.Full:
                continue
            return

    def close(self, *, run_control: RunControl = NO_RUN_CONTROL) -> None:
        """Drain outstanding writes and stop the writer, bounded end to end.

        Raises the writer's recorded failure once the thread settles, and
        raises :class:`UnsettledStoreWriterError` when the sentinel cannot be
        delivered or the thread does not terminate within the shutdown bound.
        """
        deadline = time.monotonic() + self._shutdown_timeout
        sentinel_delivered = False
        while self._thread.is_alive() and not sentinel_delivered:
            run_control.checkpoint()
            if time.monotonic() >= deadline:
                break
            try:
                self._queue.put(None, timeout=self._poll_seconds)
            except queue.Full:
                continue
            sentinel_delivered = True
        while self._thread.is_alive():
            run_control.checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._thread.join(timeout=min(self._poll_seconds, remaining))
        if self._thread.is_alive():
            logger.error(
                "store writer %r did not terminate within %.0fs; aborting the run",
                self._thread.name,
                self._shutdown_timeout,
            )
            raise UnsettledStoreWriterError(
                f"store writer {self._thread.name!r} did not terminate within "
                f"{self._shutdown_timeout:.0f}s"
            )
        self._raise_if_failed()

    def abandon(self) -> None:
        """Best-effort bounded shutdown for the encoding side's error path.

        Never raises, so the original encoding-side exception propagates; a
        writer that cannot be settled within the bound is logged and left to
        finish its wedged store call on its own.
        """
        deadline = time.monotonic() + self._shutdown_timeout
        while self._thread.is_alive():
            try:
                self._queue.put(None, timeout=self._poll_seconds)
                break
            except queue.Full:
                if time.monotonic() >= deadline:
                    break
        self._thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if self._thread.is_alive():
            logger.error(
                "store writer %r still live after abandon; a store call may be wedged",
                self._thread.name,
            )


@dataclass(frozen=True, slots=True)
class _VaultSliceRequest:
    """One bounded vault slice and its ordered publication controls."""

    slice_chunks: list[VaultChunk]
    slice_index: int
    model: EmbeddingModel
    store: VaultStore
    gpu_lock: threading.Lock | None
    sparse_enabled: bool
    probe: MemoryProbe
    ingest_wait: bool = True
    run_control: RunControl = NO_RUN_CONTROL
    reuse: DonorReuseContext | None = None
    writer: _SliceWriter | None = None
    release_cache: bool = True


def _encode_and_upsert_vault_slice(request: _VaultSliceRequest) -> None:
    """Encode one vault chunk slice and store it, inline or via the writer.

    ``ingest_wait=False`` defers the server-mode apply handshake to the
    caller's ingest barrier; the embedded backend ignores it.
    ``release_cache=False`` skips this slice's CUDA cache flush so the
    caller's cadence throttle decides when the allocator is emptied.

    With a ``writer``, the synchronous upsert is handed to the single writer
    thread so the next slice's encode overlaps this slice's storage I/O; the
    writer releases the slice's vector fields once its upsert settles. The
    per-slice CUDA cache flush stays on this (encoding) thread at the same
    once-per-slice cadence as the inline path.
    """

    def _after_encode() -> None:
        request.probe.checkpoint(f"slice-{request.slice_index}-after-encode")

    request.probe.checkpoint(f"slice-{request.slice_index}-before-encode")
    handed_off = False
    try:
        request.run_control.checkpoint()
        _encode_slice_vector_fields(
            _VectorEncodeRequest(
                chunks=request.slice_chunks,
                slice_texts=[
                    f"{chunk.title}\n\n{chunk.text}" for chunk in request.slice_chunks
                ],
                model=request.model,
                gpu_lock=request.gpu_lock,
                sparse_enabled=request.sparse_enabled,
                encode_batch_size=None,
                after_encode=_after_encode,
                reuse=request.reuse,
            )
        )
        request.run_control.checkpoint()
        if request.writer is None:
            request.store.upsert_document_chunks(
                request.slice_chunks,
                write_policy=None,
                wait=request.ingest_wait,
            )
        else:
            request.writer.submit(
                StoreWriteTask(
                    write=partial(
                        request.store.upsert_document_chunks,
                        request.slice_chunks,
                        write_policy=None,
                        wait=request.ingest_wait,
                    ),
                    release=partial(_release_vector_fields, request.slice_chunks),
                ),
                run_control=request.run_control,
            )
            handed_off = True
    finally:
        if not handed_off:
            _release_vector_fields(request.slice_chunks)
        if request.release_cache:
            _release_cuda_cache()


def _stream_encode_and_upsert_vault(request: VaultStreamRequest) -> dict[str, int]:
    """Encode dense + sparse vectors and upsert per-slice.

    Streaming the pipeline slice-by-slice keeps peak memory bounded to
    one batch's worth of embedding tensors and attention activations.
    The caching allocator is flushed at each slice boundary.

    Chunks are processed in length-sorted order (longest first) so each
    slice contains length-uniform texts. Combined with
    SentenceTransformer's per-call length sort and the smaller
    ``embedding_encode_batch_size`` sub-batching, this eliminates the
    padding-waste pathology described in #68 where a single 8000-char
    research doc would force a 64-doc slice's attention matrix to be
    padded for everyone. The Qdrant upsert is order-independent
    (idempotent by chunk point key) so the input order is purely a perf
    optimisation. Wall-clock work, #68.

    Returns:
        Mapping of document id to the number of chunks written for it,
        so callers can purge stale tail chunks of documents that
        shrank since the previous run.
    """
    from ..config._settings import get_config
    from ..memory_probe import MemoryProbe
    from ._vault_prep import split_documents

    cfg = get_config()
    sparse_enabled = cfg.sparse_enabled
    chunk_chars = int(cfg.vault_chunk_chars)

    # Expand documents into heading-aware chunks (one point each), then
    # sort by embed-text length, longest first. SentenceTransformer
    # sorts again per call, but the slice-level sort makes each slice's
    # longest text close in length to its shortest, bounding the
    # slice's worst-case padding cost.
    chunks = split_documents(request.docs, chunk_chars, run_control=request.run_control)
    chunk_counts = {c.doc_id: c.chunk_count for c in chunks}
    sorted_chunks = sorted(
        chunks,
        key=lambda c: -(len(c.title) + len(c.text)),
    )

    # Same fail-fast contract as the codebase path: refuse a run the
    # store volume cannot absorb before any encoding starts.
    request.store.disk_headroom_preflight(len(sorted_chunks))

    with MemoryProbe(name="vault-full-index") as probe:
        request.reporter.phase_start("embed + upsert documents", len(sorted_chunks))
        writer = _SliceWriter(name="vault-slice-writer")
        try:
            try:
                flush_slices = max(1, int(cfg.vault_cache_flush_slices))
                for slice_index, i in enumerate(
                    range(0, len(sorted_chunks), request.slice_size)
                ):
                    slice_chunks = sorted_chunks[i : i + request.slice_size]
                    is_last = i + request.slice_size >= len(sorted_chunks)
                    _encode_and_upsert_vault_slice(
                        _VaultSliceRequest(
                            slice_chunks=slice_chunks,
                            slice_index=i,
                            model=request.model,
                            store=request.store,
                            gpu_lock=request.gpu_lock,
                            sparse_enabled=sparse_enabled,
                            probe=probe,
                            ingest_wait=request.ingest_wait,
                            run_control=request.run_control,
                            reuse=request.reuse,
                            writer=writer,
                            release_cache=(
                                is_last or (slice_index + 1) % flush_slices == 0
                            ),
                        )
                    )
                    probe.checkpoint(f"slice-{i}-after-empty-cache")
                    request.reporter.advance(len(slice_chunks))
            except BaseException:
                writer.abandon()
                raise
            writer.close(run_control=request.run_control)
        finally:
            # Always close the phase so progress reporters never see
            # an unbalanced phase_start/phase_end pair, even when the
            # slice loop raises (CUDA OOM, Qdrant I/O error, etc).
            request.reporter.phase_end()

    if probe.samples:
        logger.info("%s", probe.report())
    return chunk_counts


#: What separates the locational parts of an embedding input from each
#: other, and the whole header from the content. Both builders composed
#: this by hand with the same two literals. They are not decoration: the
#: header is what lets a query match a chunk through its location rather
#: than only its body, so code and document inputs drifting apart in format
#: makes their scores quietly less comparable, and nothing fails.
_EMBED_CONTEXT_SEPARATOR = " :: "
_EMBED_HEADER_SEPARATOR = "\n"


def _embed_text(context: list[str], content: str) -> str:
    """Compose one embedding input: locational header, then raw content."""
    return _EMBED_CONTEXT_SEPARATOR.join(context) + _EMBED_HEADER_SEPARATOR + content


def _code_embed_text(chunk: CodeChunk) -> str:
    """Build the embedding input for a code chunk.

    Prepends a one-line locational header (project-relative path plus
    enclosing class/function when known) so queries can match a chunk
    through its location and naming context, not just its body. The
    stored payload keeps the raw chunk content; only the embedding
    input carries the header.
    """
    parts = [chunk.path]
    if chunk.class_name:
        parts.append(chunk.class_name)
    if chunk.function_name:
        parts.append(chunk.function_name)
    return _embed_text(parts, chunk.content)


def _document_embed_text(chunk: DocumentChunk) -> str:
    """Build document embedding input without altering the stored payload."""
    payload = chunk.payload
    context = [payload.source_path]
    if payload.title:
        context.append(payload.title)
    if payload.section:
        context.append(payload.section)
    return _embed_text(context, payload.content)


def encode_and_upsert_document_slice(request: DocumentSliceRequest) -> None:
    """Encode and publish one bounded document-only slice.

    Without a ``writer`` the upsert and its confirmation callback run
    synchronously on this thread. With a ``writer``, both are handed to the
    single writer thread in submission order, so the next slice's encode
    overlaps this slice's storage I/O; the writer releases the slice's vector
    fields once the task settles, and any write failure re-raises on the
    encoding side at the next hand-off or at the writer's close.
    """
    from ..config._settings import get_config

    if not request.chunks:
        return
    handed_off = False
    try:
        request.run_control.checkpoint()
        _encode_slice_vector_fields(
            _VectorEncodeRequest(
                chunks=request.chunks,
                slice_texts=[_document_embed_text(chunk) for chunk in request.chunks],
                model=request.model,
                gpu_lock=request.gpu_lock,
                sparse_enabled=bool(get_config().sparse_enabled),
                encode_batch_size=request.encode_batch_size,
                after_forward=request.after_forward,
                on_cuda_oom=request.on_cuda_oom,
                reuse=request.reuse,
            )
        )
        request.run_control.checkpoint()
        if request.writer is None:
            request.store.upsert_document_content_chunks(
                request.chunks,
                write_policy=request.write_policy,
            )
            if request.on_storage_confirmed is not None:
                request.on_storage_confirmed()
        else:
            request.writer.submit(
                StoreWriteTask(
                    write=partial(
                        _write_document_slice,
                        request.chunks,
                        store=request.store,
                        write_policy=request.write_policy,
                        on_storage_confirmed=request.on_storage_confirmed,
                    ),
                    release=partial(_release_vector_fields, request.chunks),
                ),
                run_control=request.run_control,
            )
            handed_off = True
    finally:
        if not handed_off:
            _release_vector_fields(request.chunks)
        if request.release_cache:
            _release_cuda_cache()


def _write_document_slice(
    slice_chunks: list[DocumentChunk],
    *,
    store: VaultStore,
    write_policy: StoreWritePolicy | None,
    on_storage_confirmed: Callable[[], None] | None,
) -> None:
    """Publish one encoded document slice and confirm it, in writer order."""
    store.upsert_document_content_chunks(
        slice_chunks,
        write_policy=write_policy,
    )
    if on_storage_confirmed is not None:
        on_storage_confirmed()


def _utf8_size(value: str | None) -> int:
    """Return the encoded size of an optional payload string."""
    return len(value.encode("utf-8")) if value is not None else 0


def _validate_estimator_dimensions(
    *,
    dense_dimension: int,
    sparse_enabled: bool,
    sparse_dimension: int,
) -> None:
    """Reject dimensions no chunk estimator can weigh."""
    if dense_dimension <= 0:
        raise ValueError(
            f"dense_dimension must be a positive integer, got {dense_dimension}"
        )
    if sparse_enabled and (isinstance(sparse_dimension, bool) or sparse_dimension <= 0):
        raise ValueError(
            f"sparse_dimension must be a positive integer, got {sparse_dimension}"
        )


def _dense_lifetime_bytes(dense_dimension: int, vector_length: int) -> int:
    """Return the dense bytes reserved for one point."""
    return max(dense_dimension, vector_length) * _DENSE_ELEMENT_LIFETIME_BYTES


def _sparse_lifetime_bytes(
    sparse_dimension: int, index_count: int, value_count: int
) -> int:
    """Return the sparse bytes reserved for one point.

    SPLADE applies ReLU and pooling across its vocabulary without a production
    top-k. Any output dimension can therefore survive as a nonzero entry, so an
    unpopulated chunk still reserves the loaded model's full output dimension
    and a populated one uses whichever count is larger. Runtime memory probes
    remain the authority for allocator overhead.
    """
    return (
        max(sparse_dimension, index_count, value_count) * _SPARSE_ENTRY_LIFETIME_BYTES
    )


def estimate_code_chunk_bytes(
    chunk: CodeChunk,
    *,
    dense_dimension: int,
    sparse_enabled: bool,
    sparse_dimension: int = _DEFAULT_SPARSE_DIMENSION,
) -> int:
    """Estimate the peak retained bytes attributable to one code chunk.

    The estimate deliberately counts concurrent representations rather than
    serialized payload size alone: source content, embedding input, payload
    strings, the float32 dense batch, the temporary Python dense vector, and
    sparse native/Python entries. Before sparse encoding, the loaded sparse
    model's full output dimension is reserved; populated chunks use whichever
    count is larger. The hard RSS/CUDA probes remain the authority for native-
    model variance. This weight drives both file segmentation here and the
    weighted queue introduced by the following orchestration steps.
    """
    _validate_estimator_dimensions(
        dense_dimension=dense_dimension,
        sparse_enabled=sparse_enabled,
        sparse_dimension=sparse_dimension,
    )

    source_bytes = _utf8_size(chunk.content)
    embed_bytes = _utf8_size(_code_embed_text(chunk))
    payload_bytes = sum(
        _utf8_size(value)
        for value in (
            chunk.id,
            chunk.path,
            chunk.language,
            chunk.content,
            chunk.node_type,
            chunk.function_name,
            chunk.class_name,
            chunk.source_path,
            chunk.preprocessor_id,
            chunk.anchor,
            chunk.locator_kind,
            chunk.locator_value_str,
            chunk.locator_end_str,
        )
    )

    dense_bytes = _dense_lifetime_bytes(dense_dimension, len(chunk.vector))

    sparse_bytes = 0
    if sparse_enabled:
        sparse_bytes = _sparse_lifetime_bytes(
            sparse_dimension,
            len(chunk.sparse_indices),
            len(chunk.sparse_values),
        )

    return (
        _POINT_FIXED_OVERHEAD_BYTES
        + source_bytes
        + embed_bytes
        + payload_bytes
        + dense_bytes
        + sparse_bytes
    )


def estimate_document_chunk_bytes(
    chunk: DocumentChunk,
    *,
    dense_dimension: int,
    sparse_enabled: bool,
    sparse_dimension: int = _DEFAULT_SPARSE_DIMENSION,
) -> int:
    """Estimate retained source, payload, dense, and sparse document bytes."""
    _validate_estimator_dimensions(
        dense_dimension=dense_dimension,
        sparse_enabled=sparse_enabled,
        sparse_dimension=sparse_dimension,
    )
    payload = chunk.payload
    locator = payload.locator
    payload_bytes = sum(
        _utf8_size(value)
        for value in (
            chunk.id,
            payload.source_path,
            payload.content_fingerprint,
            payload.content,
            payload.title,
            payload.section,
            payload.anchor,
            locator.kind if locator is not None else None,
            str(locator.value) if locator is not None else None,
            (
                str(locator.end)
                if locator is not None and locator.end is not None
                else None
            ),
            payload.document_metadata.canonical_json,
            payload.unit_metadata.canonical_json,
            payload.extractor_id,
            payload.extractor_version,
        )
    )
    dense_bytes = _dense_lifetime_bytes(dense_dimension, len(chunk.vector))
    sparse_bytes = 0
    if sparse_enabled:
        sparse_bytes = _sparse_lifetime_bytes(
            sparse_dimension,
            len(chunk.sparse_indices),
            len(chunk.sparse_values),
        )
    return (
        _POINT_FIXED_OVERHEAD_BYTES
        + _utf8_size(payload.content)
        + _utf8_size(_document_embed_text(chunk))
        + payload_bytes
        + dense_bytes
        + sparse_bytes
    )


def iter_weighted_document_slices(
    request: DocumentSliceStreamRequest,
) -> Iterator[WeightedDocumentSlice]:
    """Yield document slices within the configured queue count and byte caps."""
    from ..config._settings import get_config

    cfg = get_config()
    chunk_limit = _positive_limit(
        "max_chunks",
        int(cfg.index_queue_max_chunks)
        if request.max_chunks is None
        else request.max_chunks,
    )
    byte_limit = _positive_limit(
        "max_bytes",
        int(cfg.index_queue_max_bytes)
        if request.max_bytes is None
        else request.max_bytes,
    )
    dimension = _positive_limit(
        "dense_dimension",
        int(cfg.embedding_dimension)
        if request.dense_dimension is None
        else request.dense_dimension,
    )
    include_sparse = (
        bool(cfg.sparse_enabled)
        if request.sparse_enabled is None
        else request.sparse_enabled
    )
    sparse_output_dimension = (
        _DEFAULT_SPARSE_DIMENSION
        if request.sparse_dimension is None
        else request.sparse_dimension
    )
    if include_sparse:
        sparse_output_dimension = _positive_limit(
            "sparse_dimension", sparse_output_dimension
        )

    selected: list[DocumentChunk] = []
    selected_bytes = 0
    for chunk in request.chunks:
        request.run_control.checkpoint()
        weight = estimate_document_chunk_bytes(
            chunk,
            dense_dimension=dimension,
            sparse_enabled=include_sparse,
            sparse_dimension=sparse_output_dimension,
        )
        if weight > byte_limit:
            raise ValueError(
                f"document chunk {chunk.id!r} estimated at {weight} bytes exceeds "
                f"the queue ceiling {byte_limit}"
            )
        if selected and (
            len(selected) >= chunk_limit or selected_bytes + weight > byte_limit
        ):
            yield WeightedDocumentSlice(tuple(selected), selected_bytes)
            selected.clear()
            selected_bytes = 0
            request.run_control.checkpoint()
        selected.append(chunk)
        selected_bytes += weight
    if selected:
        yield WeightedDocumentSlice(tuple(selected), selected_bytes)
    request.run_control.checkpoint()


def _positive_limit(name: str, value: int) -> int:
    """Validate one positive integer resource limit."""
    if isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return value


def _selected_int(value: int | None, configured: Callable[[], int]) -> int:
    """Choose an explicit integer without evaluating its configured default."""
    return configured() if value is None else value


def _resolve_code_segment_limits(
    *,
    max_chunks: int | None,
    max_bytes: int | None,
    dense_dimension: int | None,
    sparse_enabled: bool | None,
    sparse_dimension: int | None,
) -> _CodeSegmentLimits:
    """Resolve and validate one file-segment policy."""
    from ..config._settings import get_config

    chunk_limit = _selected_int(
        max_chunks,
        lambda: int(get_config().index_segment_max_chunks),
    )
    byte_limit = _selected_int(
        max_bytes,
        lambda: int(get_config().index_segment_max_bytes),
    )
    dimension = _selected_int(
        dense_dimension,
        lambda: int(get_config().embedding_dimension),
    )
    include_sparse = (
        bool(get_config().sparse_enabled) if sparse_enabled is None else sparse_enabled
    )
    sparse_output_dimension = (
        _DEFAULT_SPARSE_DIMENSION if sparse_dimension is None else sparse_dimension
    )
    if include_sparse:
        sparse_output_dimension = _positive_limit(
            "sparse_dimension",
            sparse_output_dimension,
        )
    return _CodeSegmentLimits(
        max_chunks=_positive_limit(
            "max_chunks",
            chunk_limit,
        ),
        max_bytes=_positive_limit(
            "max_bytes",
            byte_limit,
        ),
        dense_dimension=_positive_limit(
            "dense_dimension",
            dimension,
        ),
        sparse_enabled=include_sparse,
        sparse_dimension=sparse_output_dimension,
    )


def _file_chunk_weight(
    chunk: CodeChunk,
    *,
    path: str,
    limits: _CodeSegmentLimits,
) -> int:
    """Validate one file-local chunk and return its bounded weight."""
    if chunk.path != path:
        raise ValueError(
            "one segment stream cannot cross file boundaries: "
            f"expected {path!r}, got {chunk.path!r}"
        )
    chunk_bytes = estimate_code_chunk_bytes(
        chunk,
        dense_dimension=limits.dense_dimension,
        sparse_enabled=limits.sparse_enabled,
        sparse_dimension=limits.sparse_dimension,
    )
    if chunk_bytes > limits.max_bytes:
        raise ValueError(
            f"code chunk {chunk.id!r} estimated at {chunk_bytes} bytes "
            f"exceeds index_segment_max_bytes={limits.max_bytes}"
        )
    return chunk_bytes


def _segment_would_overflow(
    *,
    chunk_count: int,
    segment_bytes: int,
    next_chunk_bytes: int,
    limits: _CodeSegmentLimits,
) -> bool:
    """Return whether the next chunk requires a new file segment."""
    return (
        chunk_count >= limits.max_chunks
        or segment_bytes + next_chunk_bytes > limits.max_bytes
    )


def iter_code_file_segments(
    request: CodeFileSegmentRequest,
) -> Iterator[CodeFileSegment]:
    """Yield ordered file-local segments within configured chunk/byte bounds.

    ``chunks`` must contain one file in its original chunk order. No segment
    crosses that file boundary, and the final yielded segment alone carries
    ``is_file_end=True`` for later storage-confirmed ledger completion. A
    single overweight chunk is rejected because silently admitting it would
    make the configured memory ceiling non-enforceable.
    """
    request.run_control.checkpoint()
    limits = _resolve_code_segment_limits(
        max_chunks=request.max_chunks,
        max_bytes=request.max_bytes,
        dense_dimension=request.dense_dimension,
        sparse_enabled=request.sparse_enabled,
        sparse_dimension=request.sparse_dimension,
    )
    chunk_iterator = iter(request.chunks)
    first_chunk = next(chunk_iterator, None)
    if first_chunk is None:
        return

    path = first_chunk.path
    ordinal = 0
    segment_chunks: list[CodeChunk] = []
    segment_bytes = 0

    for chunk in chain((first_chunk,), chunk_iterator):
        request.run_control.checkpoint()
        chunk_bytes = _file_chunk_weight(
            chunk,
            path=path,
            limits=limits,
        )
        if segment_chunks and _segment_would_overflow(
            chunk_count=len(segment_chunks),
            segment_bytes=segment_bytes,
            next_chunk_bytes=chunk_bytes,
            limits=limits,
        ):
            yield CodeFileSegment(
                path=path,
                ordinal=ordinal,
                chunks=tuple(segment_chunks),
                estimated_bytes=segment_bytes,
                is_file_end=False,
            )
            request.run_control.checkpoint()
            ordinal += 1
            segment_chunks.clear()
            segment_bytes = 0

        segment_chunks.append(chunk)
        segment_bytes += chunk_bytes
        request.run_control.checkpoint()

    request.run_control.checkpoint()
    yield CodeFileSegment(
        path=path,
        ordinal=ordinal,
        chunks=tuple(segment_chunks),
        estimated_bytes=segment_bytes,
        is_file_end=True,
    )
    request.run_control.checkpoint()


def iter_weighted_code_slices(
    segments: Iterable[CodeFileSegment],
    *,
    max_chunks: int | None = None,
    max_bytes: int | None = None,
    run_control: RunControl = NO_RUN_CONTROL,
) -> Iterator[WeightedCodeSlice]:
    """Pack ordered file segments into bounded encode/upsert slices.

    Segment objects are never split or reordered, so later checkpoint code can
    record every file-local unit covered by one confirmed store mutation. Small
    files may share an encode slice, retaining batching throughput without
    losing their resumability boundaries.
    """
    from ..config._settings import get_config

    run_control.checkpoint()
    configured_chunks = _selected_int(
        max_chunks,
        lambda: int(get_config().index_queue_max_chunks),
    )
    configured_bytes = _selected_int(
        max_bytes,
        lambda: int(get_config().index_queue_max_bytes),
    )
    chunk_limit = _positive_limit(
        "max_chunks",
        configured_chunks,
    )
    byte_limit = _positive_limit(
        "max_bytes",
        configured_bytes,
    )

    slice_segments: list[CodeFileSegment] = []
    slice_chunks: list[CodeChunk] = []
    slice_bytes = 0
    previous_segment: CodeFileSegment | None = None

    for segment in segments:
        run_control.checkpoint()
        if previous_segment is not None:
            _validate_segment_transition(previous_segment, segment)
        previous_segment = segment
        segment_chunk_count = len(segment.chunks)
        if segment_chunk_count > chunk_limit or segment.estimated_bytes > byte_limit:
            raise ValueError(
                f"code file segment {segment.path!r}#{segment.ordinal} exceeds "
                f"slice bounds: chunks={segment_chunk_count}/{chunk_limit}, "
                f"bytes={segment.estimated_bytes}/{byte_limit}"
            )

        if slice_segments and (
            len(slice_chunks) + segment_chunk_count > chunk_limit
            or slice_bytes + segment.estimated_bytes > byte_limit
        ):
            yield WeightedCodeSlice(
                segments=tuple(slice_segments),
                chunks=tuple(slice_chunks),
                estimated_bytes=slice_bytes,
            )
            run_control.checkpoint()
            slice_segments.clear()
            slice_chunks.clear()
            slice_bytes = 0

        slice_segments.append(segment)
        slice_chunks.extend(segment.chunks)
        slice_bytes += segment.estimated_bytes
        run_control.checkpoint()

    if slice_segments:
        run_control.checkpoint()
        yield WeightedCodeSlice(
            segments=tuple(slice_segments),
            chunks=tuple(slice_chunks),
            estimated_bytes=slice_bytes,
        )
        run_control.checkpoint()


def encode_and_upsert_code_slice(request: CodeSliceRequest) -> None:
    """Encode dense + sparse vectors for one slice of code chunks and upsert it.

    Dense and sparse forwards use separate GPU-lock spans, and sparse transfer
    and conversion run outside the lock, so the I/O-bound upsert does not block
    concurrent searches on the same device. When
    ``release_cache`` is True the CUDA caching pool is returned to the driver
    on every exit path (#68); the chunk-to-embed pipeline passes
    False on most slices and flushes periodically instead (#155).

    Args:
        slice_chunks: Chunks to encode and upsert. Dense/sparse fields are
            populated only for the synchronous store call and cleared before
            this function returns or propagates an error.
        model: Embedding model.
        store: Vector store.
        gpu_lock: Optional lock serialising GPU access with search.
        release_cache: Whether to flush the CUDA caching allocator afterwards.
        encode_batch_size: Inner encode sub-batch size; ``None`` uses the
            model default. The codebase path passes the larger
            ``embedding_code_encode_batch_size`` (#155) since code chunks
            are short and length-uniform.
        ingest_wait: Server-mode durability handshake for the upsert.
            Rebuild callers pass ``False`` and verify application through
            the store's ingest barrier before their terminal steps; the
            embedded backend ignores it.
        run_control: Cooperative control checked outside the GPU lock before
            and after this bounded slice.
    """
    from ..config._settings import get_config

    cfg = get_config()

    if not request.chunks:
        return
    try:
        request.run_control.checkpoint()
        _encode_slice_vector_fields(
            _VectorEncodeRequest(
                chunks=request.chunks,
                slice_texts=[_code_embed_text(chunk) for chunk in request.chunks],
                model=request.model,
                gpu_lock=request.gpu_lock,
                sparse_enabled=bool(cfg.sparse_enabled),
                encode_batch_size=request.encode_batch_size,
                after_forward=request.after_forward,
                on_cuda_oom=request.on_cuda_oom,
                reuse=request.reuse,
            )
        )
        request.run_control.checkpoint()
        request.store.upsert_code_chunks(
            request.chunks,
            write_policy=request.write_policy,
            wait=request.ingest_wait,
            collection=request.collection,
        )
        if request.on_storage_confirmed is not None:
            request.on_storage_confirmed()
    finally:
        # A successful synchronous upsert is the durable boundary. Failed or
        # cancelled slices also discard partial vector fields so retained file
        # or corpus objects stay vector-free and can be safely re-encoded.
        _release_vector_fields(request.chunks)
        if request.release_cache:
            _release_cuda_cache()


def _stream_encode_and_upsert_codebase(request: CodebaseStreamRequest) -> None:
    """Encode and publish an in-memory code chunk set in bounded slices."""
    from ..config._settings import get_config
    from ..memory_probe import MemoryProbe

    cfg = get_config()
    encode_batch_size = int(cfg.embedding_code_encode_batch_size)
    flush_slices = max(1, int(cfg.index_cache_flush_slices))
    sorted_chunks = sorted(request.chunks, key=lambda chunk: -len(chunk.content))
    request.store.disk_headroom_preflight(len(sorted_chunks))

    with MemoryProbe(name="codebase-full-index") as probe:
        request.reporter.phase_start("embed + upsert chunks", len(sorted_chunks))
        try:
            for slice_index, offset in enumerate(
                range(0, len(sorted_chunks), request.slice_size)
            ):
                request.run_control.checkpoint()
                slice_chunks = sorted_chunks[offset : offset + request.slice_size]
                probe.checkpoint(f"slice-{offset}-before-encode")
                is_last = offset + request.slice_size >= len(sorted_chunks)
                release = is_last or (slice_index + 1) % flush_slices == 0
                encode_and_upsert_code_slice(
                    CodeSliceRequest(
                        chunks=slice_chunks,
                        model=request.model,
                        store=request.store,
                        gpu_lock=request.gpu_lock,
                        release_cache=release,
                        encode_batch_size=encode_batch_size,
                        run_control=request.run_control,
                        reuse=request.reuse,
                    )
                )
                probe.checkpoint(f"slice-{offset}-after-empty-cache")
                request.reporter.advance(len(slice_chunks))
                request.run_control.checkpoint()
        finally:
            request.reporter.phase_end()

    if probe.samples:
        logger.info("%s", probe.report())
