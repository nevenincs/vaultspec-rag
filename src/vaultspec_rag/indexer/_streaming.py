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
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from ..job_control import NO_RUN_CONTROL
from ._slicing import (
    code_embed_text,
    document_embed_text,
)
from ._streaming_types import (
    CodebaseStreamRequest,
    CodeSliceRequest,
    CpuTransferable,
    DenseRowIterable,
    DocumentSliceRequest,
    ListConvertible,
    SparseVectorLike,
    VaultStreamRequest,
)

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Iterable, Sequence

    from .._store_models import (
        CodeChunk,
        DocumentChunk,
        VaultChunk,
    )
    from .._store_writes import StoreWritePolicy
    from ..embeddings import EmbeddingModel, EncodeBucketProgress
    from ..job_control import RunControl
    from ..memory_probe import MemoryProbe
    from ..progress import ProgressReporter
    from ..store_runtime import VaultStore
    from ._reuse import DonorReuseContext

logger = logging.getLogger(__name__)

__all__ = [
    "EncodeBucketReporter",
    "StoreWriteTask",
    "UnsettledStoreWriterError",
    "_SliceWriter",
    "_release_cuda_cache",
    "_stream_encode_and_upsert_codebase",
    "_stream_encode_and_upsert_vault",
    "encode_and_upsert_code_slice",
    "encode_and_upsert_document_slice",
    "report_forward_entry",
    "report_forward_exit",
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
def _release_cuda_cache() -> None:
    """Return unused accelerator caching-allocator blocks to the backend.

    Called between embedding slices to prevent the allocator from
    growing unboundedly as per-batch activation buffers accumulate -
    the root cause of the 24 GB RSS leak documented in issue #68.
    Safe no-op when torch is unavailable.
    """
    from .._gpu import load_accelerator

    try:
        accelerator = load_accelerator()
    except (ImportError, RuntimeError) as exc:
        logger.debug("accelerator cache flush skipped: %s", exc)
        return
    accelerator.release_cache()


def _transfer_to_cpu(value: object) -> object:
    """Return ``value`` on CPU when it exposes the tensor ``cpu`` protocol.

    Ordinary dense callers receive a CPU NumPy array. Index streaming requests
    an accelerator tensor and crosses this boundary immediately after the
    encoder releases its last per-bucket ``gpu_lock`` hold. The structural
    check keeps both forms lazy without adding an eager Torch import to this
    module.
    """
    if isinstance(value, CpuTransferable):
        return value.cpu()
    return value


def _dense_rows(value: object) -> Iterable[object]:
    """Validate and expose rows from a CPU dense-embedding result."""
    if not isinstance(value, DenseRowIterable):
        msg = f"dense encoder returned a non-iterable result: {type(value).__name__}"
        raise TypeError(msg)
    return value


def _dense_vector_to_list(value: object) -> list[float]:
    """Map one already-transferred dense row to the store's list shape."""
    cpu_value = _transfer_to_cpu(value)
    if isinstance(cpu_value, list):
        return cast("list[float]", cpu_value)
    if not isinstance(cpu_value, ListConvertible):
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
    sparse: Iterable[SparseVectorLike | None],
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
    # Forward-pass boundary callbacks, called with the pass kind ("dense" or
    # "sparse"). ``before_forward`` fires on the encoding thread immediately
    # before the first bucket forward seeks the GPU lock, so an in-flight
    # encode - the only activity inside a slice - is observable while it
    # runs, not only after.
    before_forward: Callable[[str], None] | None = None
    after_forward: Callable[[str], None] | None = None
    # Per-bucket encode boundary callback. The dense and sparse encoders each
    # split the slice into token-budgeted buckets and call this at every
    # boundary, so the reporting it drives resolves inside a slice rather
    # than only at its edges.
    on_encode_bucket: Callable[[str, EncodeBucketProgress], None] | None = None
    on_cuda_oom: Callable[[BaseException], None] | None = None
    reuse: DonorReuseContext | None = None


def _notify_forward_boundary(
    callback: Callable[[str], None] | None,
    kind: str,
) -> None:
    """Fire one optional forward-boundary callback."""
    if callback is not None:
        callback(kind)


def _encode_slice_vector_fields(request: _VectorEncodeRequest) -> None:
    """Populate one bounded slice, dropping all array/tensor owners on return."""
    # Both stay local: the donor adoption below rebinds them to the miss
    # sub-slice, and the ``finally`` drops that slice's owners.
    chunks = request.chunks
    slice_texts = request.slice_texts
    reuse = request.reuse
    if reuse is not None:
        chunks, slice_texts = _adopt_donor_vectors(
            reuse,
            chunks,
            slice_texts,
            sparse_enabled=request.sparse_enabled,
        )
        if not chunks:
            # Every point was adopted from a donor: no forward pass runs and
            # the GPU is never touched for this slice. ``after_encode`` still
            # fires so caller-side accounting (memory-probe checkpoints)
            # stays balanced; ``after_forward`` does not, because no forward
            # happened.
            if request.after_encode is not None:
                request.after_encode()
            return
    encode_started = time.perf_counter()
    dense_device: object | None = None
    dense_cpu: object | None = None
    sparse: Iterable[SparseVectorLike | None] | None = None
    try:
        _notify_forward_boundary(request.before_forward, "dense")
        # The model brackets each planned encode bucket's forward with its
        # own GPU-lock hold, so a concurrent search on the shared device
        # waits for at most one bucket, never a whole slice.
        dense_device = request.model.encode_documents_on_device(
            slice_texts,
            batch_size=request.encode_batch_size,
            gpu_lock=request.gpu_lock,
            on_bucket=request.on_encode_bucket,
        )
        _notify_forward_boundary(request.after_forward, "dense")
        dense_cpu = _transfer_to_cpu(dense_device)
        dense_device = None
        if request.sparse_enabled:
            _notify_forward_boundary(request.before_forward, "sparse")
            sparse = request.model.encode_documents_sparse(
                slice_texts,
                batch_size=request.encode_batch_size,
                gpu_lock=request.gpu_lock,
                on_bucket=request.on_encode_bucket,
            )
            _notify_forward_boundary(request.after_forward, "sparse")
        else:
            sparse = [None] * len(slice_texts)
        if request.after_encode is not None:
            request.after_encode()
        _populate_vector_fields(chunks, dense_cpu, sparse)
        if reuse is not None:
            reuse.stats.record_encode(
                time.perf_counter() - encode_started,
                len(chunks),
            )
    except Exception as exc:
        from .._gpu import load_accelerator

        try:
            accelerator = load_accelerator()
        except (ImportError, RuntimeError):
            accelerator = None
        if (
            request.on_cuda_oom is not None
            and accelerator is not None
            and accelerator.is_out_of_memory(exc)
        ):
            request.on_cuda_oom(exc)
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
        # Daemon because both shutdown paths are bounded and both document
        # giving up: close raises once the bound expires and abandon logs and
        # returns, each leaving a thread that may still be parked or wedged in
        # a store call. A non-daemon thread makes that documented decision
        # unreachable - the interpreter then waits on the very thread the
        # bound exists to stop waiting for, and the process never exits.
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
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

        Any exit that leaves the thread running abandons it here rather than
        propagating first. The checkpoint below raises on a cancel or a pause,
        and it does so before the sentinel is delivered, so the thread is left
        parked on an empty queue; a caller's error path cannot cover that,
        because the exception is raised *by* the shutdown it would run after.
        """
        try:
            self._drain_and_stop(run_control)
        except BaseException:
            self.abandon()
            raise
        self._raise_if_failed()

    def _drain_and_stop(self, run_control: RunControl) -> None:
        """Deliver the sentinel and wait for the thread, both bounded."""
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
    before_forward: Callable[[str], None] | None = None
    after_forward: Callable[[str], None] | None = None
    on_encode_bucket: Callable[[str, EncodeBucketProgress], None] | None = None


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
                before_forward=request.before_forward,
                after_forward=request.after_forward,
                on_encode_bucket=request.on_encode_bucket,
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


def report_forward_entry(
    reporter: ProgressReporter,
    ordinal: int,
    items: int,
    kind: str,
) -> None:
    """Adapt one slice's forward-entry boundary onto the progress reporter."""
    del kind
    reporter.forward_started(ordinal=ordinal, items=items)


def report_forward_exit(
    reporter: ProgressReporter,
    ordinal: int,
    items: int,
    kind: str,
) -> None:
    """Adapt one slice's forward-exit boundary onto the progress reporter."""
    del kind
    reporter.forward_finished(ordinal=ordinal, items=items)


@runtime_checkable
class _EncodeTelemetrySink(Protocol):
    """The encode-state surface a progress reporter may also publish.

    Forward boundaries mean something to every reporter; encode budget and
    memory-retry state only mean something to one with a job record behind
    it. Narrowing to the capability keeps that state off the reporters that
    have nowhere to put it, without a no-op member on each of them.
    """

    def encode_bucket_observed(
        self,
        *,
        token_budget: int | None,
        bucket_items: int | None,
        items_done: int | None,
        items_total: int | None,
    ) -> None: ...

    def encode_oom(self) -> None: ...


class EncodeBucketReporter:
    """Adapt one slice's per-bucket encode boundaries onto the reporter.

    The encoder splits a slice into token-budgeted buckets and calls this at
    each boundary, on the encoding thread and outside any GPU-lock hold. Every
    boundary reopens or closes the forward window, so a slice that takes
    minutes reads as work moving through it instead of one silent open
    window, and every boundary republishes the token budget and bucket size
    the encoder is working under, which is what makes a collapsed encode rate
    attributable to a memory ceiling rather than to a stuck pass.

    The window is always reported with the slice's own item count, which is
    what that number has to mean for a reader who finds the window open:
    the sub-slice climb through those items is published beside the budget
    instead, as a done-and-total pair that says what it is without a second
    field to read it against.

    Bucket progress carries the encoder's running memory-retry count rather
    than an event per retry, so each rise in it is republished as the retries
    it stands for. The dense and sparse encodes of one slice share this
    adapter but hold independent counts that each restart at zero, so the
    drained total is tracked per encode kind - a sparse retry is never read
    as already reported because a dense count got there first.
    """

    __slots__ = ("_items", "_ooms_reported", "_ordinal", "_reporter", "_sink")

    def __init__(
        self,
        reporter: ProgressReporter,
        ordinal: int,
        items: int,
    ) -> None:
        self._reporter = reporter
        self._ordinal = ordinal
        self._items = items
        self._sink = reporter if isinstance(reporter, _EncodeTelemetrySink) else None
        self._ooms_reported: dict[str, int] = {}

    def __call__(self, phase: str, progress: EncodeBucketProgress) -> None:
        try:
            self._publish(phase, progress)
        except Exception:
            # This runs inside the encoder's bucket loop, so raising would
            # discard every bucket the slice has already encoded. Reporting is
            # never worth an encode: record the failure and let the slice run.
            logger.warning("encode bucket telemetry failed", exc_info=True)

    def _publish(self, phase: str, progress: EncodeBucketProgress) -> None:
        if self._sink is not None:
            reported = self._ooms_reported.get(progress.kind, 0)
            while reported < progress.oom_count:
                reported += 1
                self._sink.encode_oom()
            self._ooms_reported[progress.kind] = reported
            self._sink.encode_bucket_observed(
                token_budget=progress.token_budget,
                bucket_items=progress.bucket_items,
                items_done=progress.items_done,
                items_total=progress.items_total,
            )
        if phase == "before":
            self._reporter.forward_started(
                ordinal=self._ordinal,
                items=self._items,
            )
            return
        self._reporter.forward_finished(
            ordinal=self._ordinal,
            items=self._items,
        )


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
                            before_forward=partial(
                                report_forward_entry,
                                request.reporter,
                                slice_index,
                                len(slice_chunks),
                            ),
                            after_forward=partial(
                                report_forward_exit,
                                request.reporter,
                                slice_index,
                                len(slice_chunks),
                            ),
                            on_encode_bucket=EncodeBucketReporter(
                                request.reporter,
                                slice_index,
                                len(slice_chunks),
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
                slice_texts=[document_embed_text(chunk) for chunk in request.chunks],
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


def encode_and_upsert_code_slice(request: CodeSliceRequest) -> None:
    """Encode dense + sparse vectors for one slice of code chunks and upsert it.

    Every dense and sparse bucket forward holds its own GPU-lock span, and
    transfer and conversion run outside the lock, so the I/O-bound upsert does
    not block concurrent searches on the same device. When
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
                slice_texts=[code_embed_text(chunk) for chunk in request.chunks],
                model=request.model,
                gpu_lock=request.gpu_lock,
                sparse_enabled=bool(cfg.sparse_enabled),
                encode_batch_size=request.encode_batch_size,
                before_forward=request.before_forward,
                after_forward=request.after_forward,
                on_encode_bucket=request.on_encode_bucket,
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
