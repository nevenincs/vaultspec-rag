"""Public API facade for vaultspec-rag.

Provides simple top-level functions (index, index_codebase, search_vault,
search_codebase, list_documents, get_related) that manage an internal
engine singleton.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib

    from vaultspec_core.graph import VaultGraph

from .embeddings import EmbeddingModel
from .indexer import CodebaseIndexer, IndexResult, VaultIndexer
from .search import SearchResult, VaultSearcher
from .store import VaultStore

logger = logging.getLogger(__name__)

__all__ = [
    "GraphCache",
    "get_engine",
    "get_related",
    "index",
    "index_codebase",
    "list_documents",
    "reset_engine",
    "search_all",
    "search_codebase",
    "search_vault",
]


class _Engine:
    """Internal engine holding model, store, indexers, and searcher.

    Aggregates all RAG components for a single workspace root.  Created
    lazily by ``get_engine`` and kept as a module-level singleton.
    """

    def __init__(self, root_dir: pathlib.Path) -> None:
        """Initialise the engine for *root_dir*.

        Components are created in dependency order.  If
        ``EmbeddingModel()`` fails (e.g. no CUDA GPU), the already-
        opened ``VaultStore`` is closed before the exception propagates
        so that Qdrant file locks are released.

        Args:
            root_dir: Resolved workspace root directory.

        Raises:
            RuntimeError: If no CUDA GPU is available (from
                ``EmbeddingModel``).
        """
        from .config import get_config

        cfg = get_config()
        self.root_dir = root_dir
        self.store = VaultStore(root_dir)
        try:
            self.model = EmbeddingModel()
        except Exception:
            self.store.close()
            raise
        self.graph_cache = GraphCache(ttl_seconds=cfg.graph_ttl_seconds)
        self.indexer = VaultIndexer(root_dir, self.model, self.store)
        self.code_indexer = CodebaseIndexer(root_dir, self.model, self.store)
        self.searcher = VaultSearcher(
            root_dir,
            self.model,
            self.store,
            graph_provider=lambda: self.graph_cache.get(root_dir),
        )


_engine: _Engine | None = None
_engine_lock = threading.Lock()


def get_engine(root_dir: pathlib.Path) -> _Engine:
    """Return (or create) the singleton engine for *root_dir*.

    Thread-safe: uses a ``threading.Lock`` with a double-check
    pattern so that concurrent callers never create duplicate
    engines.  The *root_dir* is resolved to an absolute path before
    comparison so that ``./project`` and ``project`` hit the same
    cache entry.  If the cached engine targets a different root the
    old engine's store is closed first.

    Args:
        root_dir: Workspace root directory (resolved internally).

    Returns:
        The singleton ``_Engine`` instance for *root_dir*.

    Raises:
        RuntimeError: If no CUDA GPU is available (propagated from
            ``_Engine.__init__``).
    """
    from pathlib import Path

    global _engine
    root_dir = Path(root_dir).resolve()
    if _engine is not None and _engine.root_dir == root_dir:
        return _engine
    with _engine_lock:
        if _engine is not None and _engine.root_dir == root_dir:
            return _engine
        if _engine is not None:
            _engine.store.close()
        _engine = _Engine(root_dir)
    return _engine


def reset_engine() -> None:
    """Tear down the singleton engine (for testing).

    Closes the underlying Qdrant store and sets the module-level
    singleton to ``None``.  Thread-safe: acquires ``_engine_lock``
    so that concurrent ``get_engine`` callers see a consistent state.
    Safe to call when no engine exists.
    """
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.store.close()
            _engine = None


def index(root_dir: pathlib.Path, *, full: bool = False) -> IndexResult:
    """Index vault documents, returning an IndexResult.

    Invalidates the cached ``VaultGraph`` after indexing so that
    subsequent ``get_related`` calls reflect updated documents.

    Args:
        root_dir: Workspace root directory.
        full: If ``True``, perform a full re-index (drops and
            recreates the collection); otherwise incremental.

    Returns:
        An ``IndexResult`` with counts of added, updated, and
        removed documents.
    """
    engine = get_engine(root_dir)
    result = engine.indexer.full_index() if full else engine.indexer.incremental_index()
    engine.graph_cache.invalidate()
    return result


def index_codebase(
    root_dir: pathlib.Path,
    *,
    full: bool = False,
) -> IndexResult:
    """Index codebase source files, returning an IndexResult.

    Does **not** invalidate the vault graph cache because code
    changes do not affect vault document relationships.

    Args:
        root_dir: Workspace root directory.
        full: If ``True``, perform a full re-index (drops and
            recreates the codebase collection); otherwise
            incremental.

    Returns:
        An ``IndexResult`` with counts of added, updated, and
        removed code chunks.
    """
    engine = get_engine(root_dir)
    if full:
        return engine.code_indexer.full_index()
    return engine.code_indexer.incremental_index()


def search_vault(
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
) -> list[SearchResult]:
    """Search the documentation vault.

    Args:
        root_dir: Workspace root directory.
        query: Natural language search query.
        top_k: Number of results to return.

    Returns:
        Ranked list of SearchResult objects.
    """
    engine = get_engine(root_dir)
    return engine.searcher.search_vault(query, top_k=top_k)


def search_codebase(
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
    language: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
) -> list[SearchResult]:
    """Search the source codebase.

    This facade exposes the most common filter kwargs.  The
    underlying ``VaultSearcher.search_codebase()`` accepts the same
    parameters and can be accessed directly via the engine for
    advanced use cases.

    Args:
        root_dir: Workspace root directory.
        query: Natural language search query or code snippet.
        top_k: Number of results to return.
        language: Optional language filter (e.g., ``'python'``,
            ``'rust'``).
        node_type: Optional AST node type filter.
        function_name: Optional function/method name filter.
        class_name: Optional class/struct name filter.

    Returns:
        Ranked list of SearchResult objects.
    """
    engine = get_engine(root_dir)
    return engine.searcher.search_codebase(
        query,
        top_k=top_k,
        language=language,
        node_type=node_type,
        function_name=function_name,
        class_name=class_name,
    )


def search_all(
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
) -> list[SearchResult]:
    """Search both documentation and codebase.

    The query is encoded once and dispatched to both vault and
    codebase searches, then results are merged and re-ranked.

    Args:
        root_dir: Workspace root directory.
        query: Natural language search query.
        top_k: Number of results to return.

    Returns:
        Ranked list of SearchResult objects from both sources.
    """
    engine = get_engine(root_dir)
    return engine.searcher.search_all(query, top_k=top_k)


def list_documents(
    root_dir: pathlib.Path,
    doc_type: str | None = None,
) -> list[dict[str, object]]:
    """List all indexed documents, optionally filtered by doc_type.

    Args:
        root_dir: Workspace root directory.
        doc_type: If provided, only return documents of this type
            (e.g., ``"adr"``, ``"plan"``).

    Returns:
        List of document dicts with keys ``id``, ``path``,
        ``doc_type``, ``title``, etc.  Returns an empty list when
        no documents match.
    """
    engine = get_engine(root_dir)
    return engine.store.list_all_documents(doc_type=doc_type)


class GraphCache:
    """Thread-safe cached VaultGraph with lock, TTL, and explicit invalidation.

    Uses a ``threading.Lock`` with a double-check pattern so that
    concurrent callers never build duplicate graphs.  The TTL ensures
    the graph is periodically refreshed without requiring explicit
    invalidation after every change.
    """

    def __init__(self, *, ttl_seconds: float | None = None) -> None:
        """Initialise the graph cache.

        Args:
            ttl_seconds: Seconds before a cached graph expires.
                Defaults to ``graph_ttl_seconds`` from project
                config (300s).
        """
        if ttl_seconds is None:
            from .config import get_config

            ttl_seconds = get_config().graph_ttl_seconds
        self._ttl_seconds = ttl_seconds
        self._graph: VaultGraph | None = None
        self._root: pathlib.Path | None = None
        self._built_at: float = 0.0
        self._lock = threading.Lock()

    def _is_stale(self, root_dir: pathlib.Path) -> bool:
        """Return ``True`` when the cache needs a rebuild."""
        if self._graph is None or self._root != root_dir:
            return True
        return (time.monotonic() - self._built_at) >= self._ttl_seconds

    def get(self, root_dir: pathlib.Path) -> VaultGraph | None:
        """Return cached graph, building it if necessary or stale.

        Args:
            root_dir: Workspace root directory.

        Returns:
            The ``VaultGraph`` for *root_dir*, or ``None`` if the
            graph could not be built (e.g. missing vault directory).
        """
        if not self._is_stale(root_dir):
            return self._graph
        with self._lock:
            if not self._is_stale(root_dir):
                return self._graph
            from vaultspec_core.graph import VaultGraph

            try:
                self._graph = VaultGraph(root_dir)
                self._root = root_dir
                self._built_at = time.monotonic()
            except Exception:
                logger.warning("Failed to build vault graph", exc_info=True)
                self._graph = None
                self._root = None
                # Retry sooner on failure (5s vs normal TTL)
                self._built_at = time.monotonic() - self._ttl_seconds + 5.0
                return None
        return self._graph

    def invalidate(self) -> None:
        """Clear the cached graph.

        Call after vault reindex so that the next ``get()`` rebuilds
        the graph from updated documents.  Thread-safe.
        """
        with self._lock:
            self._graph = None
            self._root = None
            self._built_at = 0.0


def get_related(
    root_dir: pathlib.Path,
    doc_id: str,
) -> dict[str, object] | None:
    """Get graph relationships for a document.

    Args:
        root_dir: Workspace root directory.
        doc_id: Document identifier (relative path without
            extension, e.g. ``"adr/overview"``).

    Returns:
        A dict with keys ``doc_id`` (str), ``outgoing``
        (sorted list of linked doc IDs), and ``incoming``
        (sorted list of back-linking doc IDs).  Returns
        ``None`` if the vault graph could not be built or
        if *doc_id* is not present in the graph.
    """
    engine = get_engine(root_dir)
    graph = engine.graph_cache.get(root_dir)
    if graph is None:
        return None

    node = graph.nodes.get(doc_id)
    if node is None:
        return None

    return {
        "doc_id": doc_id,
        "outgoing": sorted(node.out_links),
        "incoming": sorted(node.in_links),
    }
