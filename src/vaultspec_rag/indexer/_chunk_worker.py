"""CPU-only chunking worker for the process-pool indexer.

This module is imported and executed inside spawn-started worker processes. It
must never construct an :class:`~vaultspec_rag.embeddings.EmbeddingModel`, touch
``torch.cuda``, or otherwise initialise a CUDA context: the embedding GPU is the
exclusive province of the single in-process consumer. Workers that initialise
CUDA reintroduce the fork/spawn CUDA-context crash class. The pool is always
created with the ``spawn`` start method so no parent CUDA context is inherited.
See ADR ``2026-06-02-index-perf-hardening`` and rule
``index-workers-stay-cpu-only``.

The chunking logic here is the byte-for-byte equivalent of the former
``CodebaseIndexer._chunk_file`` / ``_chunk_with_ast`` / ``_chunk_with_splitter``
methods, relocated to module scope so the worker callable is picklable and so
the in-process fallback shares the exact same code path (guaranteeing
chunk-identity parity between serial and parallel runs).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..store import CodeChunk
from ._ast_chunker import ASTChunker
from ._chunking import LANGUAGE_MAP, TextSplitter

if TYPE_CHECKING:
    import pathlib

logger = logging.getLogger(__name__)

# Per-worker reusable chunker. ``ASTChunker`` itself is cheap to build, but the
# tree-sitter parsers it drives are cached inside ``tree_sitter_language_pack``
# across calls, so a single instance per process avoids repeated lookups over
# tens of thousands of files (research O3).
_CHUNKER: ASTChunker | None = None


@dataclass(slots=True)
class FileChunkResult:
    """One file's chunks plus its content hash, returned from a worker.

    Carrying the blake2b hash back from the same read that produced the chunks
    lets the full-index path skip the separate hash pass — the tree is read
    once, not twice (#155 P03 / finding C4). ``slots=True`` keeps the pickled
    payload that crosses the process boundary lean (research O3).
    """

    rel_path: str
    content_hash: str
    chunks: list[CodeChunk]


def _get_chunker() -> ASTChunker:
    """Return the per-process reusable :class:`ASTChunker`, building it once."""
    global _CHUNKER
    if _CHUNKER is None:
        _CHUNKER = ASTChunker()
    return _CHUNKER


def _decode_source(raw: bytes, path: pathlib.Path) -> str | None:
    """Decode raw file bytes as UTF-8 with universal-newline translation.

    Replicates :meth:`pathlib.Path.read_text` semantics (``\\r\\n`` and lone
    ``\\r`` collapse to ``\\n``) so chunk text, line numbers, and chunk ids are
    byte-identical to the pre-single-read code path. Returns ``None`` when the
    bytes are not valid UTF-8.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        logger.warning("Cannot decode %s: %s", path, e)
        return None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _chunk_decoded(
    content: str,
    path: pathlib.Path,
    root_dir: pathlib.Path,
) -> list[CodeChunk]:
    """Split already-decoded source into chunks, selecting AST vs splitter."""
    ext = path.suffix.lower()
    lang_entry = LANGUAGE_MAP.get(ext)
    language = lang_entry[0] if lang_entry else "text"
    grammar = lang_entry[1] if lang_entry else None
    rel_path = str(path.relative_to(root_dir)).replace("\\", "/")

    if grammar:
        return chunk_with_ast(content, rel_path, language, grammar)
    return chunk_with_splitter(content, rel_path, language)


def chunk_file(path: pathlib.Path, root_dir: pathlib.Path) -> list[CodeChunk]:
    """Read a file, decode it once, and split it into AST-aware ``CodeChunk``s.

    This is the picklable process-pool entry point for the incremental and
    scoped paths (which hash separately). It performs only CPU work: a single
    file read, tree-sitter parsing (or text-splitter fallback), and chunk
    construction with empty vectors for the consumer to embed.

    Args:
        path: Absolute path to the source file.
        root_dir: Project root used to compute the chunk's relative path.

    Returns:
        List of ``CodeChunk`` instances with empty vectors, or an empty list
        when the file cannot be read or decoded.
    """
    try:
        raw = path.read_bytes()
    except OSError as e:
        logger.warning("Cannot read %s: %s", path, e)
        return []
    content = _decode_source(raw, path)
    if content is None:
        return []
    return _chunk_decoded(content, path, root_dir)


def chunk_and_hash_file(
    path: pathlib.Path,
    root_dir: pathlib.Path,
) -> FileChunkResult | None:
    """Read a file once, returning both its content hash and its chunks.

    The full-index path uses this so the tree is read a single time rather than
    once for hashing and again for chunking (#155 P03). The blake2b hash is
    computed over the raw bytes, matching ``hashlib.file_digest`` exactly, so
    incremental-index change detection is unaffected. A file that is readable
    but not valid UTF-8 still yields its hash (with no chunks) so it remains
    tracked in the index metadata.

    Args:
        path: Absolute path to the source file.
        root_dir: Project root used to compute the relative path.

    Returns:
        A :class:`FileChunkResult`, or ``None`` when the file cannot be read.
    """
    try:
        raw = path.read_bytes()
    except OSError as e:
        logger.warning("Cannot read %s: %s", path, e)
        return None
    content_hash = hashlib.blake2b(raw).hexdigest()
    rel_path = str(path.relative_to(root_dir)).replace("\\", "/")
    content = _decode_source(raw, path)
    if content is None:
        return FileChunkResult(rel_path, content_hash, [])
    try:
        chunks = _chunk_decoded(content, path, root_dir)
    except Exception:
        # The hash is already computed, so still return a result (with no
        # chunks) rather than raising: that keeps the file present in the
        # index metadata, matching the pre-rework behaviour where hashing was
        # an independent pass. Dropping it would make every later incremental
        # run re-chunk the file.
        logger.warning("Chunking failed for %s; indexing hash only", rel_path)
        return FileChunkResult(rel_path, content_hash, [])
    return FileChunkResult(rel_path, content_hash, chunks)


def chunk_with_ast(
    content: str,
    rel_path: str,
    language: str,
    grammar: str,
) -> list[CodeChunk]:
    """Chunk source code using tree-sitter AST, falling back to the splitter."""
    chunker = _get_chunker()
    try:
        ast_chunks = chunker.chunk(content, grammar)
    except Exception:
        logger.warning(
            "AST parsing failed for %s, falling back to text splitter",
            rel_path,
            exc_info=True,
        )
        return chunk_with_splitter(content, rel_path, language)

    chunks: list[CodeChunk] = []
    for (
        text,
        line_start,
        line_end,
        node_type,
        function_name,
        class_name,
    ) in ast_chunks:
        if not text.strip():
            continue
        chunk_hash = hashlib.blake2b(
            text.encode("utf-8"),
            digest_size=6,
        ).hexdigest()
        chunks.append(
            CodeChunk(
                id=f"{rel_path}:{line_start}-{line_end}:{chunk_hash}",
                path=rel_path,
                language=language,
                content=text,
                line_start=line_start,
                line_end=line_end,
                node_type=node_type,
                function_name=function_name,
                class_name=class_name,
                vector=[],
            ),
        )
    return chunks


def chunk_with_splitter(
    content: str,
    rel_path: str,
    language: str,
) -> list[CodeChunk]:
    """Chunk content using ``TextSplitter`` for non-AST languages."""
    # chunk_overlap=0 is required: non-zero overlap prepends content from the
    # previous chunk, making chunks not findable verbatim in the original source.
    # This breaks line number tracking below.
    splitter = TextSplitter(language=language, chunk_overlap=0)
    text_chunks = splitter.split_text(content)

    chunks: list[CodeChunk] = []
    search_offset = 0
    for text in text_chunks:
        idx = content.find(text, search_offset)
        if idx != -1:
            line_start = content.count("\n", 0, idx) + 1
            search_offset = idx + len(text)
        else:
            # Chunk not found verbatim — happens when TextSplitter overlap
            # is > 0 and prepended tail text shifts the chunk boundary.
            logger.debug(
                "Chunk not found verbatim in %s at offset %d; "
                "line_start is approximate (chunk_overlap > 0?)",
                rel_path,
                search_offset,
            )
            line_start = content.count("\n", 0, search_offset) + 1
            search_offset += len(text)
        line_end = line_start + text.count("\n")

        chunk_hash = hashlib.blake2b(
            text.encode("utf-8"),
            digest_size=6,
        ).hexdigest()
        chunks.append(
            CodeChunk(
                id=f"{rel_path}:{line_start}-{line_end}:{chunk_hash}",
                path=rel_path,
                language=language,
                content=text,
                line_start=line_start,
                line_end=line_end,
                vector=[],
            ),
        )
    return chunks
