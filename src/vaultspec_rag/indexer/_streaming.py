"""Streaming embed-and-upsert helpers shared by both indexers.

Encodes dense + sparse vectors slice-by-slice and upserts each slice
immediately, flushing the CUDA caching allocator at every boundary to
keep peak memory bounded (the #68 RSS-leak fix).
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from dataclasses import dataclass
from itertools import chain, pairwise
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from ..embeddings import EmbeddingModel
    from ..memory_probe import MemoryProbe
    from ..progress import ProgressReporter
    from ..store import CodeChunk, VaultChunk, VaultDocument, VaultStore

logger = logging.getLogger(__name__)

__all__ = [
    "CodeFileSegment",
    "WeightedCodeSlice",
    "_release_cuda_cache",
    "_stream_encode_and_upsert_vault",
    "encode_and_upsert_code_slice",
    "estimate_code_chunk_bytes",
    "iter_code_file_segments",
    "iter_weighted_code_slices",
]


# Conservative 64-bit CPython lifetime estimates. A dense element exists once
# in the float32 encode output and once as a Python float/list slot while the
# store point is built. A sparse entry exists as native index/value data plus
# two Python list entries. The fixed allowance covers the dataclass, payload
# mapping, Qdrant model, and the small containers joining those objects.
_DENSE_ELEMENT_LIFETIME_BYTES = 4 + 8 + 24
_SPARSE_ENTRY_LIFETIME_BYTES = 8 + 4 + (2 * 8) + 28 + 24
_CODE_POINT_FIXED_OVERHEAD_BYTES = 1024
_DEFAULT_SPARSE_DIMENSION = 30_522


@dataclass(frozen=True, slots=True)
class _CodeSegmentLimits:
    """Resolved memory and chunk limits for one segment stream."""

    max_chunks: int
    max_bytes: int
    dense_dimension: int
    sparse_enabled: bool
    sparse_dimension: int


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
    chunks: Iterable[CodeChunk | VaultChunk],
) -> None:
    """Release vector-bearing fields retained by chunk objects."""
    for chunk in chunks:
        chunk.vector.clear()
        chunk.sparse_indices.clear()
        chunk.sparse_values.clear()


def _populate_vector_fields(
    chunks: Sequence[CodeChunk | VaultChunk],
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


def _encode_slice_vector_fields(
    *,
    chunks: Sequence[CodeChunk | VaultChunk],
    slice_texts: list[str],
    model: EmbeddingModel,
    gpu_lock: threading.Lock | None,
    sparse_enabled: bool,
    encode_batch_size: int | None,
    after_encode: Callable[[], None] | None = None,
) -> None:
    """Populate one bounded slice, dropping all array/tensor owners on return."""
    dense_device: object | None = None
    dense_cpu: object | None = None
    sparse: Iterable[_SparseVectorLike | None] | None = None
    try:
        with gpu_lock if gpu_lock is not None else nullcontext():
            dense_device = model.encode_documents_on_device(
                slice_texts,
                batch_size=encode_batch_size,
            )
        dense_cpu = _transfer_to_cpu(dense_device)
        dense_device = None
        if sparse_enabled:
            sparse = model.encode_documents_sparse(
                slice_texts,
                batch_size=encode_batch_size,
                gpu_lock=gpu_lock,
            )
        else:
            sparse = [None] * len(slice_texts)
        if after_encode is not None:
            after_encode()
        _populate_vector_fields(chunks, dense_cpu, sparse)
    finally:
        # Chunk fields own the store-ready lists. Drop accelerator/CPU arrays
        # and the embedding-text copies before Qdrant builds point models.
        del dense_device
        del dense_cpu
        del sparse
        del slice_texts


def _encode_and_upsert_vault_slice(
    *,
    slice_chunks: list[VaultChunk],
    slice_index: int,
    model: EmbeddingModel,
    store: VaultStore,
    gpu_lock: threading.Lock | None,
    sparse_enabled: bool,
    probe: MemoryProbe,
) -> None:
    """Encode, synchronously store, and release one vault chunk slice."""

    def _after_encode() -> None:
        probe.checkpoint(f"slice-{slice_index}-after-encode")

    probe.checkpoint(f"slice-{slice_index}-before-encode")
    try:
        _encode_slice_vector_fields(
            chunks=slice_chunks,
            slice_texts=[f"{chunk.title}\n\n{chunk.text}" for chunk in slice_chunks],
            model=model,
            gpu_lock=gpu_lock,
            sparse_enabled=sparse_enabled,
            encode_batch_size=None,
            after_encode=_after_encode,
        )
        store.upsert_document_chunks(slice_chunks, write_policy=None)
    finally:
        _release_vector_fields(slice_chunks)
        _release_cuda_cache()


def _stream_encode_and_upsert_vault(
    *,
    docs: list[VaultDocument],
    slice_size: int,
    model: EmbeddingModel,
    store: VaultStore,
    gpu_lock: threading.Lock | None,
    reporter: ProgressReporter,
) -> dict[str, int]:
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
    from ..config import get_config
    from ..memory_probe import MemoryProbe
    from ._vault_prep import split_document

    cfg = get_config()
    sparse_enabled = cfg.sparse_enabled
    chunk_chars = int(cfg.vault_chunk_chars)

    # Expand documents into heading-aware chunks (one point each), then
    # sort by embed-text length, longest first. SentenceTransformer
    # sorts again per call, but the slice-level sort makes each slice's
    # longest text close in length to its shortest, bounding the
    # slice's worst-case padding cost.
    chunks = [c for d in docs for c in split_document(d, chunk_chars)]
    chunk_counts = {c.doc_id: c.chunk_count for c in chunks}
    sorted_chunks = sorted(
        chunks,
        key=lambda c: -(len(c.title) + len(c.text)),
    )

    # Same fail-fast contract as the codebase path: refuse a run the
    # store volume cannot absorb before any encoding starts.
    store.disk_headroom_preflight(len(sorted_chunks))

    with MemoryProbe(name="vault-full-index") as probe:
        reporter.phase_start("embed + upsert documents", len(sorted_chunks))
        try:
            for i in range(0, len(sorted_chunks), slice_size):
                slice_chunks = sorted_chunks[i : i + slice_size]
                _encode_and_upsert_vault_slice(
                    slice_chunks=slice_chunks,
                    slice_index=i,
                    model=model,
                    store=store,
                    gpu_lock=gpu_lock,
                    sparse_enabled=sparse_enabled,
                    probe=probe,
                )
                probe.checkpoint(f"slice-{i}-after-empty-cache")
                reporter.advance(len(slice_chunks))
        finally:
            # Always close the phase so progress reporters never see
            # an unbalanced phase_start/phase_end pair, even when the
            # slice loop raises (CUDA OOM, Qdrant I/O error, etc).
            reporter.phase_end()

    if probe.samples:
        logger.info("%s", probe.report())
    return chunk_counts


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
    return " :: ".join(parts) + "\n" + chunk.content


def _utf8_size(value: str | None) -> int:
    """Return the encoded size of an optional payload string."""
    return len(value.encode("utf-8")) if value is not None else 0


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
    if dense_dimension <= 0:
        raise ValueError(
            f"dense_dimension must be a positive integer, got {dense_dimension}"
        )
    if sparse_enabled and (isinstance(sparse_dimension, bool) or sparse_dimension <= 0):
        raise ValueError(
            f"sparse_dimension must be a positive integer, got {sparse_dimension}"
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

    dense_entries = max(dense_dimension, len(chunk.vector))
    dense_bytes = dense_entries * _DENSE_ELEMENT_LIFETIME_BYTES

    sparse_bytes = 0
    if sparse_enabled:
        # SPLADE applies ReLU and pooling across its vocabulary without a
        # production top-k. Any output dimension can therefore survive as a
        # nonzero entry; reserve the loaded model's full output dimension.
        # Runtime memory probes remain the authority for allocator overhead.
        sparse_entries = max(
            sparse_dimension,
            len(chunk.sparse_indices),
            len(chunk.sparse_values),
        )
        sparse_bytes = sparse_entries * _SPARSE_ENTRY_LIFETIME_BYTES

    return (
        _CODE_POINT_FIXED_OVERHEAD_BYTES
        + source_bytes
        + embed_bytes
        + payload_bytes
        + dense_bytes
        + sparse_bytes
    )


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
    from ..config import get_config

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
    chunks: Iterable[CodeChunk],
    *,
    max_chunks: int | None = None,
    max_bytes: int | None = None,
    dense_dimension: int | None = None,
    sparse_enabled: bool | None = None,
    sparse_dimension: int | None = None,
) -> Iterator[CodeFileSegment]:
    """Yield ordered file-local segments within configured chunk/byte bounds.

    ``chunks`` must contain one file in its original chunk order. No segment
    crosses that file boundary, and the final yielded segment alone carries
    ``is_file_end=True`` for later storage-confirmed ledger completion. A
    single overweight chunk is rejected because silently admitting it would
    make the configured memory ceiling non-enforceable.
    """
    limits = _resolve_code_segment_limits(
        max_chunks=max_chunks,
        max_bytes=max_bytes,
        dense_dimension=dense_dimension,
        sparse_enabled=sparse_enabled,
        sparse_dimension=sparse_dimension,
    )
    chunk_iterator = iter(chunks)
    first_chunk = next(chunk_iterator, None)
    if first_chunk is None:
        return

    path = first_chunk.path
    ordinal = 0
    segment_chunks: list[CodeChunk] = []
    segment_bytes = 0

    for chunk in chain((first_chunk,), chunk_iterator):
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
            ordinal += 1
            segment_chunks.clear()
            segment_bytes = 0

        segment_chunks.append(chunk)
        segment_bytes += chunk_bytes

    yield CodeFileSegment(
        path=path,
        ordinal=ordinal,
        chunks=tuple(segment_chunks),
        estimated_bytes=segment_bytes,
        is_file_end=True,
    )


def iter_weighted_code_slices(
    segments: Iterable[CodeFileSegment],
    *,
    max_chunks: int | None = None,
    max_bytes: int | None = None,
) -> Iterator[WeightedCodeSlice]:
    """Pack ordered file segments into bounded encode/upsert slices.

    Segment objects are never split or reordered, so later checkpoint code can
    record every file-local unit covered by one confirmed store mutation. Small
    files may share an encode slice, retaining batching throughput without
    losing their resumability boundaries.
    """
    from ..config import get_config

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
            slice_segments.clear()
            slice_chunks.clear()
            slice_bytes = 0

        slice_segments.append(segment)
        slice_chunks.extend(segment.chunks)
        slice_bytes += segment.estimated_bytes

    if slice_segments:
        yield WeightedCodeSlice(
            segments=tuple(slice_segments),
            chunks=tuple(slice_chunks),
            estimated_bytes=slice_bytes,
        )


def encode_and_upsert_code_slice(
    slice_chunks: list[CodeChunk],
    *,
    model: EmbeddingModel,
    store: VaultStore,
    gpu_lock: threading.Lock | None,
    release_cache: bool = True,
    encode_batch_size: int | None = None,
) -> None:
    """Encode dense + sparse vectors for one slice of code chunks and upsert it.

    Dense and sparse forwards use separate GPU-lock spans, and sparse transfer
    and conversion run outside the lock, so the I/O-bound upsert does not block
    concurrent searches on the same device. When
    ``release_cache`` is True the CUDA caching pool is returned to the driver
    on every exit path (#68 audit F6.9); the chunk-to-embed pipeline passes
    False on most slices and flushes periodically instead (#155 P03).

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
            ``embedding_code_encode_batch_size`` (#155 P03) since code chunks
            are short and length-uniform.
    """
    from ..config import get_config

    cfg = get_config()

    if not slice_chunks:
        return
    try:
        _encode_slice_vector_fields(
            chunks=slice_chunks,
            slice_texts=[_code_embed_text(chunk) for chunk in slice_chunks],
            model=model,
            gpu_lock=gpu_lock,
            sparse_enabled=bool(cfg.sparse_enabled),
            encode_batch_size=encode_batch_size,
        )
        store.upsert_code_chunks(slice_chunks, write_policy=None)
    finally:
        # A successful synchronous upsert is the durable boundary. Failed or
        # cancelled slices also discard partial vector fields so retained file
        # or corpus objects stay vector-free and can be safely re-encoded.
        _release_vector_fields(slice_chunks)
        if release_cache:
            _release_cuda_cache()
