"""Public API facade for vaultspec-rag.

Provides simple top-level functions (index, list_documents, get_related)
that manage an internal engine singleton.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib

from .embeddings import EmbeddingModel
from .indexer import IndexResult, VaultIndexer
from .store import VaultStore

logger = logging.getLogger(__name__)

__all__ = [
    "get_engine",
    "get_related",
    "index",
    "list_documents",
    "reset_engine",
]


class _Engine:
    """Internal engine holding model, store, and indexer for a workspace."""

    def __init__(self, root_dir: pathlib.Path) -> None:
        self.root_dir = root_dir
        self.store = VaultStore(root_dir)
        self.model = EmbeddingModel()
        self.indexer = VaultIndexer(root_dir, self.model, self.store)


_engine: _Engine | None = None


def get_engine(root_dir: pathlib.Path) -> _Engine:
    """Return (or create) the singleton engine for *root_dir*."""
    global _engine
    if _engine is None or _engine.root_dir != root_dir:
        _engine = _Engine(root_dir)
    return _engine


def reset_engine() -> None:
    """Tear down the singleton engine (for testing)."""
    global _engine
    if _engine is not None:
        _engine.store.close()
        _engine = None


def index(root_dir: pathlib.Path, *, full: bool = False) -> IndexResult:
    """Index vault documents, returning an IndexResult.

    Args:
        root_dir: Workspace root directory.
        full: If True, perform a full re-index; otherwise incremental.

    Returns:
        An IndexResult with counts of added/updated/removed documents.
    """
    engine = get_engine(root_dir)
    if full:
        return engine.indexer.full_index()
    return engine.indexer.incremental_index()


def list_documents(root_dir: pathlib.Path, doc_type: str | None = None) -> list[dict]:
    """List all indexed documents, optionally filtered by doc_type.

    Args:
        root_dir: Workspace root directory.
        doc_type: If provided, only return documents of this type.

    Returns:
        List of document dicts with id, path, doc_type, title, etc.
    """
    engine = get_engine(root_dir)
    engine.store.ensure_table()

    all_ids = engine.store.get_all_ids()
    docs = []
    for doc_id in sorted(all_ids):
        doc = engine.store.get_by_id(doc_id)
        if doc is None:
            continue
        if doc_type and doc.get("doc_type") != doc_type:
            continue
        docs.append(doc)
    return docs


def get_related(root_dir: pathlib.Path, doc_id: str) -> dict | None:
    """Get graph relationships for a document.

    Args:
        root_dir: Workspace root directory.
        doc_id: Document stem to look up.

    Returns:
        Dict with doc_id, outgoing, and incoming link lists,
        or None if the document is not found.
    """
    from vaultspec.graph import VaultGraph

    try:
        graph = VaultGraph(root_dir)
    except Exception:
        logger.warning("Failed to build vault graph", exc_info=True)
        return {"doc_id": doc_id, "outgoing": [], "incoming": []}

    node = graph.nodes.get(doc_id)
    if node is None:
        return {"doc_id": doc_id, "outgoing": [], "incoming": []}

    return {
        "doc_id": doc_id,
        "outgoing": sorted(node.out_links),
        "incoming": sorted(node.in_links),
    }
