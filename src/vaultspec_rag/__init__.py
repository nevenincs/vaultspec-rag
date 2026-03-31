"""RAG (Retrieval-Augmented Generation) for vault documents.

GPU-native embedding pipeline using sentence-transformers + Qwen3-Embedding-0.6B
for dense embeddings and SPLADE v3 for sparse. Qdrant local mode for vector storage.
"""

from __future__ import annotations

from .api import (
    get_related,
    index,
    index_codebase,
    list_documents,
    search_all,
    search_codebase,
    search_vault,
)
from .embeddings import EmbeddingModel, SparseResult
from .indexer import CodebaseIndexer, IndexResult, VaultIndexer, prepare_document
from .search import (
    ParsedQuery,
    SearchResult,
    VaultSearcher,
    parse_query,
    rerank_with_graph,
)
from .store import CodeChunk, VaultDocument, VaultStore

__all__ = [
    "CodeChunk",
    "CodebaseIndexer",
    "EmbeddingModel",
    "IndexResult",
    "ParsedQuery",
    "SearchResult",
    "SparseResult",
    "VaultDocument",
    "VaultIndexer",
    "VaultSearcher",
    "VaultStore",
    "get_related",
    "index",
    "index_codebase",
    "list_documents",
    "parse_query",
    "prepare_document",
    "rerank_with_graph",
    "search_all",
    "search_codebase",
    "search_vault",
]
