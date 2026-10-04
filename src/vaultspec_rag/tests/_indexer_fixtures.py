"""Indexer observations and materialised results for tests.

Production streams a document's chunks and never asks a queue or an indexer
how much it is holding. A test asserting on those reads them here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..indexer._chunk_worker import (
    _DEFAULT_DOCUMENT_CHUNKING_OPTIONS,
    DocumentChunkingOptions,
    stream_document_and_hash_file,
)

if TYPE_CHECKING:
    import pathlib

    from .._store_models import DocumentChunk
    from ..index_profiles import SupportMeasurement
    from ..indexer._chunk_producer import WeightedCodeSegmentQueue
    from ..indexer._codebase_indexer import CodebaseIndexer


@dataclass(slots=True)
class DocumentFileChunkResult:
    """One document source's chunks, materialised, and its source hash."""

    rel_path: str
    content_hash: str
    chunks: list[DocumentChunk]
    preprocess_status: str | None = None
    preprocess_reason: str | None = None


def chunk_document_and_hash_file(
    path: pathlib.Path,
    root_dir: pathlib.Path,
    options: DocumentChunkingOptions = _DEFAULT_DOCUMENT_CHUNKING_OPTIONS,
) -> DocumentFileChunkResult:
    """Drain the production document stream into a list."""
    result = stream_document_and_hash_file(path, root_dir, options)
    return DocumentFileChunkResult(
        result.rel_path,
        result.content_hash,
        list(result.chunks),
        result.preprocess_status,
        result.preprocess_reason,
    )


def support_measurement(indexer: CodebaseIndexer) -> SupportMeasurement:
    """Return the indexer's latest code workload measurement."""
    return indexer._support_budget.measurement


def queued_chunks(segment_queue: WeightedCodeSegmentQueue) -> int:
    """Return the number of chunks waiting in the queue."""
    with segment_queue._condition:
        return segment_queue._queued_chunks


def queued_bytes(segment_queue: WeightedCodeSegmentQueue) -> int:
    """Return the estimated bytes waiting in the queue."""
    with segment_queue._condition:
        return segment_queue._queued_bytes
