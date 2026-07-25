"""Vault document preparation and the shared :class:`IndexResult` type.

Reads markdown vault files, parses frontmatter via vaultspec-core, and
builds :class:`~vaultspec_rag.store.VaultDocument` instances ready for
embedding. Also defines the :class:`IndexResult` dataclass returned by
both indexers.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from vaultspec_core.vaultcore import (  # pyright: ignore[reportMissingTypeStubs]  # no stubs for vaultspec_core
    DocType,
    get_doc_type,
    parse_vault_metadata,
)

from ..job_control import NO_RUN_CONTROL
from ..store import VaultChunk, VaultDocument
from ._chunking import TextSplitter

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from ..job_control import RunControl

logger = logging.getLogger(__name__)

__all__ = [
    "IndexResult",
    "_extract_feature",
    "_extract_status",
    "_extract_title",
    "prepare_document",
    "split_document",
    "split_documents",
]

# Fan each worker's share out over several batches so one heavyweight
# document cannot serialize the tail of the pool behind a single task.
_SPLIT_BATCHES_PER_WORKER = 4

# ADR status lives in the H1 title, not frontmatter, in the canonical
# vaultspec-core form ``... | (**status:** `value`)``. The marker is optional
# (legacy ``# ADR: ...`` headings carry none) and the value may or may not be
# backtick-wrapped, so both patterns are tolerant of surrounding backticks and
# whitespace.
_STATUS_RE = re.compile(
    r"\(\s*\*\*status:\*\*\s*`?\s*([A-Za-z][A-Za-z-]*)\s*`?\s*\)",
    re.IGNORECASE,
)
_STATUS_SUFFIX_RE = re.compile(
    r"\s*\|\s*\(\s*\*\*status:\*\*.*?\)\s*$",
    re.IGNORECASE,
)


@dataclass
class IndexResult:
    """Result of an indexing operation.

    Attributes:
        total: Total number of items in the index after the operation.
        added: Number of newly indexed items.
        updated: Number of re-indexed (modified) items.
        removed: Number of items removed from the index.
        duration_ms: Wall-clock time for the operation in milliseconds.
        device: Compute device used for embeddings (e.g. ``"cuda"``).
        files: Number of files processed (for codebase indexing).
        preprocess_ok: Number of files a document-preprocessing rule fed into
            the index this run (fresh runs and cache hits alike), surfaced so
            a working preprocess pipeline is positively observable and rule-fed
            content silently absent from the index is distinguishable from
            "no rules matched".
        preprocess_skipped: Number of files a document-preprocessing rule
            skipped this run (``on_error=skip``), surfaced so coverage gaps are
            never silent (#185).
        preprocess_failures: ``"rel_path: reason"`` for each skipped file.
        reuse: Donor vector-reuse telemetry for this run (hit/miss counts,
            hit rate, estimated GPU seconds saved, donor availability), or
            ``None`` when reuse is disabled or the run never reached the
            encode pipeline.
        drift: Source-drift telemetry for this run: the paths whose source
            moved while the run was recording them and had to be superseded,
            and any left stale for the next generation. Reported so drift
            volume is visible in its own right, because a run that remediates
            drift succeeds and therefore tells the circuit breaker nothing.
            ``None`` when the run never opened a generation.
    """

    total: int
    added: int
    updated: int
    removed: int
    duration_ms: int
    device: str
    files: int = 0
    preprocess_ok: int = 0
    preprocess_skipped: int = 0
    preprocess_failures: list[str] = field(default_factory=list)
    reuse: dict[str, object] | None = None
    drift: dict[str, object] | None = None


def _first_h1(body: str) -> str:
    """Return the first H1 heading text (without the leading ``# ``), or ``""``."""
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _extract_title(body: str) -> str:
    """Extract the first H1 heading, stripped of any trailing status marker.

    The canonical ADR heading carries a ``| (**status:** `value`)`` suffix; it
    is a status signal, not part of the title, so it is removed here (fixing
    the prior behaviour that leaked the marker into the displayed title).
    Non-ADR and legacy headings are returned unchanged.

    Args:
        body: Raw markdown text to scan.

    Returns:
        The cleaned heading text, or ``""`` if no H1 is found.
    """
    heading = _first_h1(body)
    if not heading:
        return ""
    return _STATUS_SUFFIX_RE.sub("", heading).strip()


def _extract_status(body: str) -> str:
    """Extract the ADR status encoded in the H1 title, lowercased.

    Returns the status value (e.g. ``"accepted"``, ``"superseded"``) when the
    ``(**status:** ...)`` marker is present, or ``""`` when absent (legacy
    ``# ADR: ...`` headings and every non-ADR document). Callers treat an empty
    status as ``unknown`` and active.

    Args:
        body: Raw markdown text to scan.

    Returns:
        The lowercased status value, or ``""`` when no marker is present.
    """
    heading = _first_h1(body)
    if not heading:
        return ""
    match = _STATUS_RE.search(heading)
    return match.group(1).lower() if match else ""


def _extract_feature(metadata_tags: list[str]) -> str:
    """Extract the feature tag (non-directory tag) from the tag list.

    Args:
        metadata_tags: List of frontmatter tag strings (e.g. ``["#plan", "#rag"]``).

    Returns:
        The feature tag value without the leading ``#``, or ``""`` if none found.
    """
    for tag in metadata_tags:
        if not DocType.from_tag(tag):
            return tag.lstrip("#")
    return ""


def split_document(
    doc: VaultDocument,
    chunk_chars: int,
) -> list[VaultChunk]:
    """Split a prepared document into heading-aware vault chunks.

    Uses the markdown-separator ``TextSplitter`` with no overlap so the
    chunks partition the body cleanly. A document whose body fits the
    budget (or is empty) still yields exactly one chunk, keeping every
    document findable by its title and metadata. The ordinal-0 chunk
    carries the full body so retrieval-by-id stays byte-exact.

    Args:
        doc: Prepared document (vector fields are ignored).
        chunk_chars: Maximum characters per chunk.

    Returns:
        Ordered list of ``VaultChunk`` with empty vectors.
    """
    splitter = TextSplitter(
        chunk_size=max(1, chunk_chars),
        chunk_overlap=0,
        language="markdown",
    )
    pieces = [p for p in splitter.split_text(doc.content) if p.strip()]
    if not pieces:
        pieces = [doc.content]
    chunk_count = len(pieces)
    return [
        VaultChunk(
            doc_id=doc.id,
            ordinal=ordinal,
            chunk_count=chunk_count,
            text=piece,
            path=doc.path,
            doc_type=doc.doc_type,
            feature=doc.feature,
            date=doc.date,
            tags=doc.tags,
            related=doc.related,
            title=doc.title,
            status=doc.status,
            doc_content=doc.content if ordinal == 0 else None,
        )
        for ordinal, piece in enumerate(pieces)
    ]


def _split_document_batch(
    docs: list[VaultDocument],
    chunk_chars: int,
) -> list[VaultChunk]:
    """Split one ordered document batch (spawn-worker entry point).

    Runs inside CPU-only spawn workers: it must never construct an embedding
    model, touch CUDA, or pull a module-scope torch import onto this module's
    import chain.
    """
    return [chunk for doc in docs for chunk in split_document(doc, chunk_chars)]


def _plan_split_workers(docs: Sequence[VaultDocument]) -> int:
    """Decide the split worker count, gating auto mode on corpus size.

    Mirrors the code path's worker policy: ``index_chunk_workers`` ``0`` means
    auto (process CPU count) but engages the spawn pool only once the corpus
    crosses ``index_parallel_min_bytes`` - below that, worker startup cost
    outweighs the parallel split. An explicit positive value is honoured
    verbatim, clamped to the document count.
    """
    from ..config import get_config

    cfg = get_config()
    configured = int(cfg.index_chunk_workers)
    workers = configured if configured > 0 else (os.process_cpu_count() or 1)
    workers = max(1, min(workers, len(docs)))
    if workers <= 1:
        return 1
    if configured > 0:
        return workers
    min_bytes = int(cfg.index_parallel_min_bytes)
    total = 0
    for doc in docs:
        total += len(doc.content)
        if total >= min_bytes:
            return workers
    return 1


def _split_documents_serial(
    docs: list[VaultDocument],
    chunk_chars: int,
    run_control: RunControl,
) -> list[VaultChunk]:
    """Split documents one at a time on the calling thread."""
    chunks: list[VaultChunk] = []
    for doc in docs:
        run_control.checkpoint()
        chunks.extend(split_document(doc, chunk_chars))
    run_control.checkpoint()
    return chunks


def split_documents(
    docs: list[VaultDocument],
    chunk_chars: int,
    *,
    run_control: RunControl = NO_RUN_CONTROL,
) -> list[VaultChunk]:
    """Split prepared documents into chunks, preserving document order.

    Whole-corpus markdown splitting is a pure-CPU stage that previously ran
    single-threaded for the entire corpus. Above the configured parallel byte
    gate it fans out across a ``spawn`` process pool whose workers do CPU-only
    work and never initialise CUDA. Output is identical to the serial path
    because workers run the same :func:`split_document` over contiguous,
    order-preserving batches.
    """
    from itertools import repeat

    workers = _plan_split_workers(docs)
    if workers <= 1:
        return _split_documents_serial(docs, chunk_chars, run_control)

    import multiprocessing
    from concurrent.futures.process import BrokenProcessPool

    from ._pool_guard import spawn_pool

    batch_size = max(
        1,
        -(-len(docs) // (workers * _SPLIT_BATCHES_PER_WORKER)),
    )
    batches = [
        docs[index : index + batch_size] for index in range(0, len(docs), batch_size)
    ]
    ctx = multiprocessing.get_context("spawn")
    chunks: list[VaultChunk] = []
    try:
        with spawn_pool(max_workers=workers, mp_context=ctx) as pool:
            for batch_chunks in pool.map(
                _split_document_batch,
                batches,
                repeat(chunk_chars),
            ):
                run_control.checkpoint()
                chunks.extend(batch_chunks)
    except BrokenProcessPool:
        logger.warning(
            "Document split process pool broke; splitting serially",
            exc_info=True,
        )
        return _split_documents_serial(docs, chunk_chars, run_control)
    run_control.checkpoint()
    return chunks


def prepare_document(
    path: pathlib.Path,
    root_dir: pathlib.Path,
) -> VaultDocument | None:
    """Prepare a single vault document for indexing (without vector).

    Reads the file, parses metadata, and constructs a VaultDocument
    with all fields except the vector (which is filled during embedding).

    Args:
        path: Absolute path to the markdown document file.
        root_dir: Workspace root directory used to compute the relative path.

    Returns:
        A ``VaultDocument`` with an empty vector, or ``None`` if the file
        cannot be read or has no recognised doc type.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Cannot read %s: %s", path, e)
        return None

    metadata, body = parse_vault_metadata(content)
    doc_type_enum = get_doc_type(path, root_dir)

    if doc_type_enum is None:
        return None

    from ..config import get_config

    docs_dir = root_dir / get_config().docs_dir
    try:
        rel_path = str(path.relative_to(docs_dir)).replace("\\", "/")
    except ValueError as exc:
        logger.debug(
            "relative_to(%s) failed for %s: %s; using basename",
            docs_dir,
            path,
            exc,
        )
        rel_path = path.name

    title = _extract_title(body)
    if not title:
        title = path.stem

    feature = _extract_feature(metadata.tags)

    # Use relative path (without extension) as ID to avoid collisions
    # e.g., "adr/overview" instead of just "overview"
    doc_id = rel_path.rsplit(".", 1)[0] if "." in rel_path else rel_path

    return VaultDocument(
        id=doc_id,
        path=rel_path,
        doc_type=doc_type_enum.value,
        feature=feature,
        date=metadata.date or "",
        tags=metadata.tags,
        related=metadata.related,
        title=title,
        status=_extract_status(body),
        content=body.strip(),
        vector=[],  # filled during embedding step
    )
