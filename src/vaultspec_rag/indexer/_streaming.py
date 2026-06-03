"""Streaming embed-and-upsert helpers shared by both indexers.

Encodes dense + sparse vectors slice-by-slice and upserts each slice
immediately, flushing the CUDA caching allocator at every boundary to
keep peak memory bounded (the #68 RSS-leak fix).
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import threading

    from ..embeddings import EmbeddingModel
    from ..progress import ProgressReporter
    from ..store import CodeChunk, VaultDocument, VaultStore

logger = logging.getLogger(__name__)


def _release_cuda_cache() -> None:
    """Return unused CUDA caching-allocator blocks to the driver.

    Called between embedding slices to prevent the allocator from
    growing unboundedly as per-batch activation buffers accumulate —
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


def _stream_encode_and_upsert_vault(
    *,
    docs: list[VaultDocument],
    slice_size: int,
    model: EmbeddingModel,
    store: VaultStore,
    gpu_lock: threading.Lock | None,
    reporter: ProgressReporter,
) -> None:
    """Encode dense + sparse vectors and upsert per-slice.

    Streaming the pipeline slice-by-slice keeps peak memory bounded to
    one batch's worth of embedding tensors and attention activations.
    The caching allocator is flushed at each slice boundary.

    Docs are processed in length-sorted order (longest first) so each
    slice contains length-uniform documents. Combined with
    SentenceTransformer's per-call length sort and the smaller
    ``embedding_encode_batch_size`` sub-batching, this eliminates the
    padding-waste pathology described in #68 where a single 8000-char
    research doc would force a 64-doc slice's attention matrix to be
    padded for everyone. The Qdrant upsert is order-independent
    (idempotent by doc_id) so the input order is purely a perf
    optimisation. Wall-clock work, #68.
    """
    from ..memory_probe import MemoryProbe

    # Sort docs by combined title+content length, longest first.
    # SentenceTransformer.encode internally sorts again per call, but
    # our slice-level sort makes each slice's longest document close
    # in length to its shortest, so the slice's worst-case padding
    # cost is bounded.
    sorted_docs = sorted(
        docs,
        key=lambda d: -(len(d.title) + len(d.content)),
    )

    with MemoryProbe(name="vault-full-index") as probe:
        reporter.phase_start("embed + upsert documents", len(sorted_docs))
        try:
            for i in range(0, len(sorted_docs), slice_size):
                slice_docs = sorted_docs[i : i + slice_size]
                slice_texts = [f"{d.title}\n\n{d.content}" for d in slice_docs]
                # Pre-bind dense/sparse to None so the finally clause
                # can ``del`` them unconditionally even when the encode
                # call raises before binding them.
                dense = None
                sparse = None
                probe.checkpoint(f"slice-{i}-before-encode")
                # Inner try/finally guarantees the per-slice CUDA
                # caching pool is released on every exit path —
                # success, exception, or KeyboardInterrupt — so a
                # mid-encode interrupt cannot leave a stale reserved
                # pool wedged in the allocator (#68 audit F6.9).
                try:
                    # Hold the GPU lock only across the encode call so
                    # that the I/O-bound upsert below runs without
                    # blocking concurrent searches on the same GPU.
                    with gpu_lock if gpu_lock is not None else nullcontext():
                        dense = model.encode_documents(slice_texts)
                        sparse = model.encode_documents_sparse(slice_texts)
                    probe.checkpoint(f"slice-{i}-after-encode")
                    for doc, vec, svec in zip(slice_docs, dense, sparse, strict=True):
                        doc.vector = vec.tolist()
                        doc.sparse_indices = list(svec.indices)
                        doc.sparse_values = list(svec.values)
                    store.upsert_documents(slice_docs)
                finally:
                    # Drop references to per-slice tensors before
                    # releasing the CUDA caching pool so freed blocks
                    # are returned to the driver immediately. ``del``
                    # is preferred over ``= None`` because it removes
                    # the local entirely from the frame instead of
                    # leaving a None binding. F10.3 audit fix.
                    del dense
                    del sparse
                    del slice_texts
                    _release_cuda_cache()
                probe.checkpoint(f"slice-{i}-after-empty-cache")
                reporter.advance(len(slice_docs))
        finally:
            # Always close the phase so progress reporters never see
            # an unbalanced phase_start/phase_end pair, even when the
            # slice loop raises (CUDA OOM, Qdrant I/O error, etc).
            reporter.phase_end()

    if probe.samples:
        logger.info("%s", probe.report())


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

    The GPU lock is held only across the encode calls so the I/O-bound upsert
    does not block concurrent searches on the same device. When
    ``release_cache`` is True the CUDA caching pool is returned to the driver
    on every exit path (#68 audit F6.9); the chunk-to-embed pipeline passes
    False on most slices and flushes periodically instead (#155 P03).

    Args:
        slice_chunks: Chunks to encode and upsert (mutated in place with
            their dense/sparse vectors).
        model: Embedding model.
        store: Vector store.
        gpu_lock: Optional lock serialising GPU access with search.
        release_cache: Whether to flush the CUDA caching allocator afterwards.
        encode_batch_size: Inner encode sub-batch size; ``None`` uses the
            model default. The codebase path passes the larger
            ``embedding_code_encode_batch_size`` (#155 P03) since code chunks
            are short and length-uniform.
    """
    if not slice_chunks:
        return
    slice_texts = [c.content for c in slice_chunks]
    dense = None
    sparse = None
    try:
        with gpu_lock if gpu_lock is not None else nullcontext():
            dense = model.encode_documents(slice_texts, batch_size=encode_batch_size)
            sparse = model.encode_documents_sparse(
                slice_texts,
                batch_size=encode_batch_size,
            )
        for chunk, vec, svec in zip(slice_chunks, dense, sparse, strict=True):
            chunk.vector = vec.tolist()
            chunk.sparse_indices = list(svec.indices)
            chunk.sparse_values = list(svec.values)
        store.upsert_code_chunks(slice_chunks)
    finally:
        # del beats ``= None`` for dropping the local out of the frame
        # entirely before the caching pool is released (#68 audit F10.4).
        del dense
        del sparse
        del slice_texts
        if release_cache:
            _release_cuda_cache()


def _stream_encode_and_upsert_codebase(
    *,
    chunks: list[CodeChunk],
    slice_size: int,
    model: EmbeddingModel,
    store: VaultStore,
    gpu_lock: threading.Lock | None,
    reporter: ProgressReporter,
) -> None:
    """Streaming variant of :func:`_stream_encode_and_upsert_vault`.

    Codebase chunks are generally smaller than vault documents, so the
    RSS benefit is less pronounced, but we apply the same pattern for
    consistency and so that large monorepos stay bounded too. Chunks
    are length-sorted before slicing for the same reason as the vault
    helper — minimises padding waste in the model's encode call.
    """
    from ..config import get_config
    from ..memory_probe import MemoryProbe

    cfg = get_config()
    encode_batch_size = int(cfg.embedding_code_encode_batch_size)
    flush_slices = max(1, int(cfg.index_cache_flush_slices))

    sorted_chunks = sorted(chunks, key=lambda c: -len(c.content))

    with MemoryProbe(name="codebase-full-index") as probe:
        reporter.phase_start("embed + upsert chunks", len(sorted_chunks))
        try:
            for slice_idx, i in enumerate(range(0, len(sorted_chunks), slice_size)):
                slice_chunks = sorted_chunks[i : i + slice_size]
                probe.checkpoint(f"slice-{i}-before-encode")
                # Throttle the per-slice CUDA cache flush (#155 P03): flush
                # every ``flush_slices`` slices instead of every slice, and
                # always on the final slice so the allocator is left clean.
                is_last = i + slice_size >= len(sorted_chunks)
                release = is_last or (slice_idx + 1) % flush_slices == 0
                encode_and_upsert_code_slice(
                    slice_chunks,
                    model=model,
                    store=store,
                    gpu_lock=gpu_lock,
                    release_cache=release,
                    encode_batch_size=encode_batch_size,
                )
                probe.checkpoint(f"slice-{i}-after-empty-cache")
                reporter.advance(len(slice_chunks))
        finally:
            reporter.phase_end()

    if probe.samples:
        logger.info("%s", probe.report())
