"""RAG (Retrieval-Augmented Generation) for vault documents.

GPU-native embedding and search pipeline for vault documents and codebase files.
Uses Qwen3-Embedding-0.6B for dense embeddings and SPLADE v3 for sparse embeddings,
with optional cross-encoder reranking (BAAI/bge-reranker-v2-m3). Hybrid search via
Qdrant local-mode vector database with unified query interface across vault documents,
codebase files, and vault relationship graphs.

Exports:
    High-level API: index(), search_vault(), search_codebase(), search_all(),
    index_codebase(), list_documents(), get_related()

    Core classes: VaultStore, VaultSearcher, VaultIndexer, CodebaseIndexer,
    EmbeddingModel, VaultDocument, CodeChunk, SearchResult, ParsedQuery
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("vaultspec-rag")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

from .api import (
    GraphCache,
    clean,
    get_related,
    get_service_state,
    get_status,
    index,
    index_codebase,
    list_documents,
    run_benchmark,
    run_quality_probe,
    scan_codebase_files,
    search_codebase,
    search_vault,
)
from .embeddings import EmbeddingModel, SparseResult
from .indexer import (
    CodebaseIndexer,
    IndexResult,
    VaultIndexer,
    prepare_document,
)
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
    "GraphCache",
    "IndexResult",
    "ParsedQuery",
    "SearchResult",
    "SparseResult",
    "VaultDocument",
    "VaultIndexer",
    "VaultSearcher",
    "VaultStore",
    "__version__",
    "clean",
    "get_related",
    "get_service_state",
    "get_status",
    "index",
    "index_codebase",
    "list_documents",
    "parse_query",
    "prepare_document",
    "rerank_with_graph",
    "run_benchmark",
    "run_quality_probe",
    "scan_codebase_files",
    "search_codebase",
    "search_vault",
]
