"""Indexing pipeline for vault semantic search.

Scans vault documents, extracts metadata, generates embeddings, and
stores them in the Qdrant vector store. Supports full and incremental
indexing.

The package's public surface is exported here: the ``VaultIndexer`` /
``CodebaseIndexer`` / ``DocumentIndexer`` orchestration classes, the
``IndexResult`` dataclass, the ``prepare_document`` helper, the
``ASTChunker`` / ``TextSplitter`` chunkers, and the shared
``LANGUAGE_MAP`` / ``SUPPORTED_EXTENSIONS`` tables. Internal helpers,
AST node-type constants and the streaming pipeline stay private to the
modules that own them and are imported from there.
"""

from __future__ import annotations

from ._ast_chunker import ASTChunker
from ._chunking import (
    LANGUAGE_MAP,
    SUPPORTED_EXTENSIONS,
    TextSplitter,
)
from ._codebase_indexer import CodebaseIndexer
from ._document_indexer import DocumentIndexer
from ._vault_indexer import VaultIndexer
from ._vault_prep import IndexResult, prepare_document

__all__ = [
    "LANGUAGE_MAP",
    "SUPPORTED_EXTENSIONS",
    "ASTChunker",
    "CodebaseIndexer",
    "DocumentIndexer",
    "IndexResult",
    "TextSplitter",
    "VaultIndexer",
    "prepare_document",
]
