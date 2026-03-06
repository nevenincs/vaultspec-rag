"""RAG (Retrieval-Augmented Generation) for vault documents.

GPU-native embedding pipeline using sentence-transformers + Qwen3-Embedding-0.6B
for dense embeddings and SPLADE v3 for sparse. Qdrant local mode for vector storage.
"""

from __future__ import annotations

from .api import get_related, index, list_documents
from .embeddings import EmbeddingModel
from .indexer import IndexResult, VaultIndexer, prepare_document
from .search import (
    ParsedQuery,
    SearchResult,
    VaultSearcher,
    parse_query,
    rerank_with_graph,
)
from .store import VaultDocument, VaultStore

__all__ = [
    "EmbeddingModel",
    "IndexResult",
    "ParsedQuery",
    "SearchResult",
    "VaultDocument",
    "VaultIndexer",
    "VaultSearcher",
    "VaultStore",
    "get_related",
    "index",
    "list_documents",
    "parse_query",
    "prepare_document",
    "rerank_with_graph",
]
