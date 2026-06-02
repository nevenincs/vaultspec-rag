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


def _get_chunker() -> ASTChunker:
    """Return the per-process reusable :class:`ASTChunker`, building it once."""
    global _CHUNKER
    if _CHUNKER is None:
        _CHUNKER = ASTChunker()
    return _CHUNKER


def chunk_file(path: pathlib.Path, root_dir: pathlib.Path) -> list[CodeChunk]:
    """Read a file, decode it once, and split it into AST-aware ``CodeChunk``s.

    This is the picklable process-pool entry point. It performs only CPU work:
    a single file read, tree-sitter parsing (or text-splitter fallback), and
    chunk construction with empty vectors for the consumer to embed.

    Args:
        path: Absolute path to the source file.
        root_dir: Project root used to compute the chunk's relative path.

    Returns:
        List of ``CodeChunk`` instances with empty vectors, or an empty list
        when the file cannot be read.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Cannot read %s: %s", path, e)
        return []

    ext = path.suffix.lower()
    lang_entry = LANGUAGE_MAP.get(ext)
    language = lang_entry[0] if lang_entry else "text"
    grammar = lang_entry[1] if lang_entry else None
    rel_path = str(path.relative_to(root_dir)).replace("\\", "/")

    if grammar:
        return chunk_with_ast(content, rel_path, language, grammar)
    return chunk_with_splitter(content, rel_path, language)


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
