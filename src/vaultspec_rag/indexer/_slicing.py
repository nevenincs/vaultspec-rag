"""Dividing indexable work into slices, and predicting what each will cost.

A slice is the unit the encoder is handed and the store is written from, so
its size decides peak memory: too large and the run reaches its ceiling, too
small and the device is never saturated. These functions estimate a chunk's
lifetime cost and then divide files into slices that respect the configured
bounds, which is a different concern from streaming those slices through the
encoder.
"""

from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING

from ..job_control import NO_RUN_CONTROL
from ._streaming_types import (
    DEFAULT_SPARSE_DIMENSION,
    DENSE_ELEMENT_LIFETIME_BYTES,
    POINT_FIXED_OVERHEAD_BYTES,
    SPARSE_ENTRY_LIFETIME_BYTES,
    CodeFileSegment,
    CodeFileSegmentRequest,
    CodeSegmentLimits,
    DocumentSliceStreamRequest,
    WeightedCodeSlice,
    WeightedDocumentSlice,
    validate_segment_transition,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from .._store_models import CodeChunk, DocumentChunk
    from ..job_control import RunControl


_EMBED_CONTEXT_SEPARATOR = " :: "
_EMBED_HEADER_SEPARATOR = "\n"


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
    return max(dense_dimension, vector_length) * DENSE_ELEMENT_LIFETIME_BYTES


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
    return max(sparse_dimension, index_count, value_count) * SPARSE_ENTRY_LIFETIME_BYTES


def estimate_code_chunk_bytes(
    chunk: CodeChunk,
    *,
    dense_dimension: int,
    sparse_enabled: bool,
    sparse_dimension: int = DEFAULT_SPARSE_DIMENSION,
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
    embed_bytes = _utf8_size(code_embed_text(chunk))
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
        POINT_FIXED_OVERHEAD_BYTES
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
    sparse_dimension: int = DEFAULT_SPARSE_DIMENSION,
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
        POINT_FIXED_OVERHEAD_BYTES
        + _utf8_size(payload.content)
        + _utf8_size(document_embed_text(chunk))
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
        DEFAULT_SPARSE_DIMENSION
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
) -> CodeSegmentLimits:
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
        DEFAULT_SPARSE_DIMENSION if sparse_dimension is None else sparse_dimension
    )
    if include_sparse:
        sparse_output_dimension = _positive_limit(
            "sparse_dimension",
            sparse_output_dimension,
        )
    return CodeSegmentLimits(
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
    limits: CodeSegmentLimits,
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
    limits: CodeSegmentLimits,
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
            validate_segment_transition(previous_segment, segment)
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


def _embed_text(context: list[str], content: str) -> str:
    """Compose one embedding input: locational header, then raw content."""
    return _EMBED_CONTEXT_SEPARATOR.join(context) + _EMBED_HEADER_SEPARATOR + content


def code_embed_text(chunk: CodeChunk) -> str:
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


def document_embed_text(chunk: DocumentChunk) -> str:
    """Build document embedding input without altering the stored payload."""
    payload = chunk.payload
    context = [payload.source_path]
    if payload.title:
        context.append(payload.title)
    if payload.section:
        context.append(payload.section)
    return _embed_text(context, payload.content)
