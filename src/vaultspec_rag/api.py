"""Public API facade for vaultspec-rag.

Thin wrappers around :class:`ServiceRegistry.lease`.  Every facade
function acquires a refcounted lease on the per-project slot, so the
eviction machinery (idle TTL + LRU cap + busy-slot skip) applies to
direct API consumers as well as MCP tool handlers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .graph_cache import GraphCache
from .progress import NullProgressReporter
from .registry import get_registry

if TYPE_CHECKING:
    import pathlib

    from .indexer import IndexResult
    from .progress import ProgressReporter
    from .search import SearchResult

logger = logging.getLogger(__name__)

__all__ = [
    "GraphCache",
    "get_related",
    "index",
    "index_codebase",
    "list_documents",
    "search_codebase",
    "search_vault",
]


def _resolve(root_dir: pathlib.Path) -> pathlib.Path:
    from pathlib import Path

    return Path(root_dir).resolve()


def index(
    root_dir: pathlib.Path,
    *,
    full: bool = False,
    reporter: ProgressReporter | None = None,
) -> IndexResult:
    """Index vault documents, returning an :class:`IndexResult`.

    Invalidates the cached :class:`VaultGraph` after indexing so that
    subsequent ``get_related`` calls reflect updated documents.

    Args:
        root_dir: Workspace root directory.
        full: If ``True``, perform a full re-index (drops and
            recreates the collection); otherwise incremental.
        reporter: Optional progress reporter. A ``NullProgressReporter``
            is used when omitted so library consumers can call this
            facade without any UI.

    Returns:
        An ``IndexResult`` with counts of added, updated, and
        removed documents.
    """
    root = _resolve(root_dir)
    rep = reporter if reporter is not None else NullProgressReporter()
    with get_registry().lease(root) as slot:
        result = (
            slot.vault_indexer.full_index(reporter=rep)
            if full
            else slot.vault_indexer.incremental_index(reporter=rep)
        )
        slot.graph_cache.invalidate()
        return result


def index_codebase(
    root_dir: pathlib.Path,
    *,
    full: bool = False,
    reporter: ProgressReporter | None = None,
) -> IndexResult:
    """Index codebase source files, returning an :class:`IndexResult`.

    Does **not** invalidate the vault graph cache because code
    changes do not affect vault document relationships.

    Args:
        root_dir: Workspace root directory.
        full: If ``True``, perform a full re-index (drops and
            recreates the codebase collection); otherwise
            incremental.
        reporter: Optional progress reporter.

    Returns:
        An ``IndexResult`` with counts of added, updated, and
        removed code chunks.
    """
    root = _resolve(root_dir)
    rep = reporter if reporter is not None else NullProgressReporter()
    with get_registry().lease(root) as slot:
        if full:
            return slot.code_indexer.full_index(reporter=rep)
        return slot.code_indexer.incremental_index(reporter=rep)


def search_vault(
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
    doc_type: str | None = None,
    feature: str | None = None,
    date: str | None = None,
    tag: str | None = None,
) -> list[SearchResult]:
    """Search the documentation vault.

    Args:
        root_dir: Workspace root directory.
        query: Natural language search query.
        top_k: Number of results to return.
        doc_type: Optional vault doc-type filter (e.g. ``'adr'``).
        feature: Optional feature-tag filter.
        date: Optional ISO date filter.
        tag: Optional free-form tag filter.

    Returns:
        Ranked list of SearchResult objects.
    """
    root = _resolve(root_dir)
    with get_registry().lease(root) as slot:
        return slot.searcher.search_vault(
            query,
            top_k=top_k,
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
        )


def search_codebase(
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
    language: str | None = None,
    path: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
) -> list[SearchResult]:
    """Search the source codebase.

    Args:
        root_dir: Workspace root directory.
        query: Natural language search query or code snippet.
        top_k: Number of results to return.
        language: Optional language filter (e.g., ``'python'``,
            ``'rust'``).
        path: Optional exact-match path filter (KEYWORD payload
            index).
        node_type: Optional AST node type filter.
        function_name: Optional function/method name filter.
        class_name: Optional class/struct name filter.

    Returns:
        Ranked list of SearchResult objects.
    """
    root = _resolve(root_dir)
    with get_registry().lease(root) as slot:
        return slot.searcher.search_codebase(
            query,
            top_k=top_k,
            language=language,
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
        )


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
    root = _resolve(root_dir)
    with get_registry().lease(root) as slot:
        return slot.store.list_all_documents(doc_type=doc_type)


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
    root = _resolve(root_dir)
    with get_registry().lease(root) as slot:
        graph = slot.graph_cache.get(root)
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
