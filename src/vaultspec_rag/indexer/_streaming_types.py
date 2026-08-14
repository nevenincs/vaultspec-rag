"""The requests, slices and cost constants the streaming pipeline passes around.

One vocabulary shared by the code that divides work into slices and the code
that streams those slices through the encoder. It sits below both so neither
has to import the other to name what it is handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..job_control import NO_RUN_CONTROL

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Iterable, Iterator

    from .._store_models import CodeChunk, DocumentChunk, VaultDocument
    from .._store_writes import StoreWritePolicy
    from ..embeddings import EmbeddingModel, EncodeBucketProgress
    from ..job_control import RunControl
    from ..progress import ProgressReporter
    from ..store_runtime import VaultStore
    from ._reuse import DonorReuseContext
    from ._streaming import _SliceWriter

# store point is built. A sparse entry exists as native index/value data plus
# two Python list entries. The fixed allowance covers the dataclass, payload
# mapping, Qdrant model, and the small containers joining those objects.
DENSE_ELEMENT_LIFETIME_BYTES = 4 + 8 + 24
SPARSE_ENTRY_LIFETIME_BYTES = 8 + 4 + (2 * 8) + 28 + 24
POINT_FIXED_OVERHEAD_BYTES = 1024
DEFAULT_SPARSE_DIMENSION = 30_522


@dataclass(frozen=True, slots=True)
class CodeSegmentLimits:
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
    before_forward: Callable[[str], None] | None = None
    after_forward: Callable[[str], None] | None = None
    on_encode_bucket: Callable[[str, EncodeBucketProgress], None] | None = None
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


def validate_segment_transition(
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
            validate_segment_transition(previous, current)


@runtime_checkable
class CpuTransferable(Protocol):
    """Structural protocol for accelerator-backed array/tensor results."""

    def cpu(self) -> object: ...


@runtime_checkable
class ListConvertible(Protocol):
    """Structural protocol shared by NumPy rows and Torch tensors."""

    def tolist(self) -> object: ...


@runtime_checkable
class DenseRowIterable(Protocol):
    """Structural protocol for dense result batches."""

    def __iter__(self) -> Iterator[object]: ...


class SparseVectorLike(Protocol):
    """Sparse row shape consumed by store-ready chunk fields."""

    indices: list[int]
    values: list[float]
