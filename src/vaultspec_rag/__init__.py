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

The public names above resolve lazily through :pep:`562` ``__getattr__``: the
heavy facade modules (``api``, ``embeddings``, ``indexer``, ``search``,
``store``) are imported only when one of their names is first accessed on the
package. Importing a submodule (for example ``vaultspec_rag.serviceclient`` or
``vaultspec_rag.cli._service_status``) therefore no longer eager-loads Torch,
the models, or the store through this top-level init.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

try:
    __version__: str = version("vaultspec-rag")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

if TYPE_CHECKING:
    # Eager view for static type checkers and IDEs; never executed at runtime,
    # so it does not defeat the lazy loading the runtime path provides.
    from .api import (
        GraphCache,
        clean,
        get_readiness,
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
        search_codebase_timed,
        search_vault,
        search_vault_timed,
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

# Maps each lazily-exported public name to the submodule that defines it.
# Accessing ``vaultspec_rag.<name>`` imports the owning submodule on demand.
_LAZY_EXPORTS: dict[str, str] = {
    "GraphCache": "api",
    "clean": "api",
    "get_readiness": "api",
    "get_related": "api",
    "get_service_state": "api",
    "get_status": "api",
    "index": "api",
    "index_codebase": "api",
    "list_documents": "api",
    "run_benchmark": "api",
    "run_quality_probe": "api",
    "scan_codebase_files": "api",
    "search_codebase": "api",
    "search_codebase_timed": "api",
    "search_vault": "api",
    "search_vault_timed": "api",
    "EmbeddingModel": "embeddings",
    "SparseResult": "embeddings",
    "CodebaseIndexer": "indexer",
    "IndexResult": "indexer",
    "VaultIndexer": "indexer",
    "prepare_document": "indexer",
    "ParsedQuery": "search",
    "SearchResult": "search",
    "VaultSearcher": "search",
    "parse_query": "search",
    "rerank_with_graph": "search",
    "CodeChunk": "store",
    "VaultDocument": "store",
    "VaultStore": "store",
}

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
    "get_readiness",
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
    "search_codebase_timed",
    "search_vault",
    "search_vault_timed",
]


def __getattr__(name: str) -> Any:
    """Lazily resolve a public export to its owning submodule (:pep:`562`).

    Importing ``vaultspec_rag`` no longer eager-loads the heavy facade; the
    owning submodule is imported only when one of its names is first accessed.
    """
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
