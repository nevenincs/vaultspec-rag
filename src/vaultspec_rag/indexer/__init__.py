"""Indexing pipeline for vault semantic search.

Scans vault documents, extracts metadata, generates embeddings, and
stores them in the Qdrant vector store. Supports full and incremental
indexing.

This module was split into a package (``indexer/``) per the
``2026-06-01-module-split-adr``. The verbatim public surface — the
``VaultIndexer`` / ``CodebaseIndexer`` orchestration classes, the
``IndexResult`` dataclass, the ``prepare_document`` helper, the
``ASTChunker`` / ``TextSplitter`` chunkers, the shared
``LANGUAGE_MAP`` / ``SUPPORTED_EXTENSIONS`` / AST node-type constants,
and the ``_extract_title`` / ``_extract_feature`` / ``_is_binary``
helpers that tests import directly — is re-exported here unchanged.
"""

from __future__ import annotations

from ._ast_chunker import ASTChunker
from ._chunking import (
    _CLASS_LIKE_NODES,
    _CONTAINER_NODES,
    _FUNCTION_LIKE_NODES,
    _MAX_FILE_SIZE,
    _TOP_LEVEL_NODES,
    LANGUAGE_MAP,
    SUPPORTED_EXTENSIONS,
    TextSplitter,
    _is_binary,
)
from ._codebase_indexer import CodebaseIndexer
from ._streaming import (
    _release_cuda_cache,
    _stream_encode_and_upsert_codebase,
    _stream_encode_and_upsert_vault,
)
from ._vault_indexer import VaultIndexer
from ._vault_prep import (
    IndexResult,
    _extract_feature,
    _extract_title,
    prepare_document,
)

__all__ = [
    "LANGUAGE_MAP",
    "SUPPORTED_EXTENSIONS",
    "_CLASS_LIKE_NODES",
    "_CONTAINER_NODES",
    "_FUNCTION_LIKE_NODES",
    "_MAX_FILE_SIZE",
    "_TOP_LEVEL_NODES",
    "ASTChunker",
    "CodebaseIndexer",
    "IndexResult",
    "TextSplitter",
    "VaultIndexer",
    "_extract_feature",
    "_extract_title",
    "_is_binary",
    "_release_cuda_cache",
    "_stream_encode_and_upsert_codebase",
    "_stream_encode_and_upsert_vault",
    "prepare_document",
]
