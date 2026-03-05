"""RAG (Retrieval-Augmented Generation) for vault documents.

Extracted module providing heavy ML-dependent retrieval logic.
"""

from __future__ import annotations

from .embeddings import CUDA_INDEX_TAG, CUDA_INDEX_URL, EmbeddingModel, GPUNotAvailableError, get_device_info
from .indexer import IndexResult, VaultIndexer, prepare_document
from .search import ParsedQuery, SearchResult, VaultSearcher, parse_query, rerank_with_graph
from .store import EMBEDDING_DIM, VaultDocument, VaultStore

__all__ = [
    "CUDA_INDEX_TAG",
    "CUDA_INDEX_URL",
    "EmbeddingModel",
    "GPUNotAvailableError",
    "get_device_info",
    "IndexResult",
    "VaultIndexer",
    "prepare_document",
    "ParsedQuery",
    "SearchResult",
    "VaultSearcher",
    "parse_query",
    "rerank_with_graph",
    "EMBEDDING_DIM",
    "VaultDocument",
    "VaultStore",
]
