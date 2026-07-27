"""RAG (Retrieval-Augmented Generation) for vault documents.

GPU-native embedding and search pipeline for vault documents and codebase files.
Uses Qwen3-Embedding-0.6B for dense embeddings and SPLADE v3 for sparse embeddings,
with optional cross-encoder reranking (BAAI/bge-reranker-v2-m3). Hybrid search via
Qdrant local-mode vector database with unified query interface across vault documents,
codebase files, and vault relationship graphs.

Exports:
    High-level API: index(), search_vault(), search_codebase(), search_all(),
    index_codebase(), list_documents(), get_related()

    Core classes: VaultSearcher, VaultIndexer, CodebaseIndexer,
    EmbeddingModel, VaultDocument, CodeChunk, SearchResult, ParsedQuery

The public names above resolve lazily through :pep:`562` ``__getattr__``: the
heavy facade modules (``api``, ``embeddings``, ``indexer``, ``search``,
``store``) are imported only when one of their names is first accessed on the
package. Importing a submodule (for example ``vaultspec_rag.serviceclient`` or
``vaultspec_rag.cli._service_status``) therefore no longer eager-loads Torch,
the models, or the store through this top-level init.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    #: Resolved lazily at runtime; declared here so type checkers and IDEs see it.
    __version__: str

if TYPE_CHECKING:
    # Eager view for static type checkers and IDEs; never executed at runtime,
    # so it does not defeat the lazy loading the runtime path provides.
    from ._public_index import DocumentScanResult, scan_documents
    from ._public_search import (
        CodeCombinedSearchFilters,
        CombinedSearchRequest,
        DocumentCombinedSearchFilters,
        DocumentSearchRequest,
        VaultCombinedSearchFilters,
        search_combined,
        search_combined_timed,
        search_documents,
        search_documents_timed,
    )
    from ._store_models import CodeChunk, VaultDocument
    from .api import (
        AllIndexOptions,
        CodebaseSearchRequest,
        CodeIndexOptions,
        DocumentIndexOptions,
        IndexOptions,
        VaultSearchRequest,
        clean,
        get_readiness,
        get_related,
        get_service_state,
        get_status,
        index,
        index_all,
        index_codebase,
        index_documents,
        list_documents,
        run_benchmark,
        run_quality_probe,
        scan_codebase,
        scan_codebase_files,
        search_codebase,
        search_codebase_timed,
        search_vault,
        search_vault_timed,
    )
    from .embeddings import EmbeddingModel, SparseResult
    from .graph_cache import GraphCache
    from .indexer import (
        CodebaseIndexer,
        DocumentIndexer,
        IndexResult,
        VaultIndexer,
        prepare_document,
    )
    from .search import (
        CombinedSearchOutcome,
        DocumentSearchResult,
        ParsedQuery,
        SearchDomainOutcome,
        SearchResult,
        VaultSearcher,
        parse_query,
        rerank_with_graph,
    )

# Maps each lazily-exported public name to the submodule that defines it.
# Accessing ``vaultspec_rag.<name>`` imports the owning submodule on demand.
_LAZY_EXPORTS: dict[str, str] = {
    "AllIndexOptions": "api",
    "CodebaseSearchRequest": "api",
    "CodeIndexOptions": "api",
    "CodeCombinedSearchFilters": "_public_search",
    "CombinedSearchRequest": "_public_search",
    "DocumentCombinedSearchFilters": "_public_search",
    "DocumentSearchRequest": "_public_search",
    "VaultCombinedSearchFilters": "_public_search",
    "DocumentScanResult": "_public_index",
    "DocumentIndexOptions": "api",
    "IndexOptions": "api",
    "scan_documents": "_public_index",
    "search_combined": "_public_search",
    "search_combined_timed": "_public_search",
    "search_documents": "_public_search",
    "search_documents_timed": "_public_search",
    "clean": "api",
    "get_readiness": "api",
    "get_related": "api",
    "get_service_state": "api",
    "get_status": "api",
    "index": "api",
    "index_all": "api",
    "index_codebase": "api",
    "index_documents": "api",
    "list_documents": "api",
    "run_benchmark": "api",
    "run_quality_probe": "api",
    "scan_codebase": "api",
    "scan_codebase_files": "api",
    "search_codebase": "api",
    "search_codebase_timed": "api",
    "search_vault": "api",
    "search_vault_timed": "api",
    "VaultSearchRequest": "api",
    "GraphCache": "graph_cache",
    "EmbeddingModel": "embeddings",
    "SparseResult": "embeddings",
    "CodebaseIndexer": "indexer",
    "DocumentIndexer": "indexer",
    "IndexResult": "indexer",
    "VaultIndexer": "indexer",
    "prepare_document": "indexer",
    "ParsedQuery": "search",
    "CombinedSearchOutcome": "search",
    "DocumentSearchResult": "search",
    "SearchDomainOutcome": "search",
    "SearchResult": "search",
    "VaultSearcher": "search",
    "parse_query": "search",
    "rerank_with_graph": "search",
    "CodeChunk": "_store_models",
    "VaultDocument": "_store_models",
}

__all__ = [
    "AllIndexOptions",
    "CodeChunk",
    "CodeCombinedSearchFilters",
    "CodeIndexOptions",
    "CodebaseIndexer",
    "CodebaseSearchRequest",
    "CombinedSearchOutcome",
    "CombinedSearchRequest",
    "DocumentCombinedSearchFilters",
    "DocumentIndexOptions",
    "DocumentIndexer",
    "DocumentScanResult",
    "DocumentSearchRequest",
    "DocumentSearchResult",
    "EmbeddingModel",
    "GraphCache",
    "IndexOptions",
    "IndexResult",
    "ParsedQuery",
    "SearchDomainOutcome",
    "SearchResult",
    "SparseResult",
    "VaultCombinedSearchFilters",
    "VaultDocument",
    "VaultIndexer",
    "VaultSearchRequest",
    "VaultSearcher",
    "__version__",
    "clean",
    "get_readiness",
    "get_related",
    "get_service_state",
    "get_status",
    "index",
    "index_all",
    "index_codebase",
    "index_documents",
    "list_documents",
    "parse_query",
    "prepare_document",
    "rerank_with_graph",
    "run_benchmark",
    "run_quality_probe",
    "scan_codebase",
    "scan_codebase_files",
    "scan_documents",
    "search_codebase",
    "search_codebase_timed",
    "search_combined",
    "search_combined_timed",
    "search_documents",
    "search_documents_timed",
    "search_vault",
    "search_vault_timed",
]


def __getattr__(name: str) -> Any:
    """Lazily resolve a public export to its owning submodule (:pep:`562`).

    Importing ``vaultspec_rag`` no longer eager-loads the heavy facade; the
    owning submodule is imported only when one of its names is first accessed.
    """
    if name == "__version__":
        # Reading installed package metadata costs ~98ms of this package's
        # ~106ms import, and every spawn worker re-imports this module in its
        # own interpreter, so paying it eagerly taxed each one for a string
        # almost nothing reads. Resolved on first access and cached below.
        from importlib.metadata import PackageNotFoundError, version

        try:
            resolved = version("vaultspec-rag")
        except PackageNotFoundError:
            resolved = "0.0.0.dev0"
        globals()[name] = resolved
        return resolved
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    # Cache on the package so subsequent accesses skip __getattr__ entirely.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
