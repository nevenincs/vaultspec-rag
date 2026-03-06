"""Retrieval pipeline for vault semantic search.

Implements query parsing, hybrid search, and graph-aware re-ranking.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import pathlib

    from vaultspec.graph import VaultGraph

    from .embeddings import EmbeddingModel
    from .store import VaultStore

logger = logging.getLogger(__name__)

__all__ = [
    "ParsedQuery",
    "SearchResult",
    "VaultSearcher",
    "parse_query",
    "rerank_with_graph",
]

# Filter token patterns: type:adr, feature:rag, date:2026-02,
# tag:#research, lang:python, path:src/
_FILTER_PATTERN = re.compile(r"\b(type|feature|date|tag|lang|path):(\S+)")

# Map filter keys to store column names
_FILTER_KEY_MAP = {
    "type": "doc_type",
    "feature": "feature",
    "date": "date",
    "lang": "language",
    "path": "path",
}


@dataclass
class ParsedQuery:
    """A parsed search query with extracted metadata filters."""

    text: str  # natural language portion
    filters: dict[str, str]  # extracted metadata filters


@dataclass
class SearchResult:
    """A single search result from vault or codebase."""

    id: str
    path: str
    title: str
    score: float
    snippet: str
    source: Literal["vault", "codebase"]
    doc_type: str = ""
    feature: str = ""
    date: str = ""
    language: str = ""
    line_start: int | None = None
    line_end: int | None = None


def parse_query(raw_query: str) -> ParsedQuery:
    """Parse a raw query string into text and metadata filters."""
    filters: dict[str, str] = {}

    for match in _FILTER_PATTERN.finditer(raw_query):
        key = match.group(1)
        value = match.group(2)

        if key == "tag":
            filters["tag"] = value.lstrip("#")
        elif key in _FILTER_KEY_MAP:
            filters[_FILTER_KEY_MAP[key]] = value

    # Remove filter tokens from the query text
    text = _FILTER_PATTERN.sub("", raw_query).strip()
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)

    return ParsedQuery(text=text, filters=filters)


def rerank_with_graph(
    results: list[SearchResult],
    root_dir: pathlib.Path,
    query: ParsedQuery,
    graph: VaultGraph | None = None,
) -> list[SearchResult]:
    """Apply graph-aware score boosts to vault search results."""
    # Only re-rank vault results using the graph
    vault_results = [r for r in results if r.source == "vault"]
    code_results = [r for r in results if r.source == "codebase"]

    if not vault_results:
        return results

    if graph is None:
        from vaultspec.graph import VaultGraph as _VaultGraph

        try:
            graph = _VaultGraph(root_dir)
        except Exception as e:
            logger.error("Graph build failed: %s", e)
            return results

    for result in vault_results:
        node = graph.nodes.get(result.id)
        if node is None:
            continue

        in_link_count = len(node.in_links)
        result.score *= 1 + 0.1 * min(in_link_count, 10)

        feature_filter = query.filters.get("feature")
        if feature_filter:
            feature_tag = f"#{feature_filter}"
            neighbor_has_feature = False
            for neighbor_name in node.out_links | node.in_links:
                neighbor = graph.nodes.get(neighbor_name)
                if neighbor and feature_tag in neighbor.tags:
                    neighbor_has_feature = True
                    break
            if neighbor_has_feature:
                result.score *= 1.15

    # Combined and re-sorted
    all_results = vault_results + code_results
    all_results.sort(key=lambda r: r.score, reverse=True)
    return all_results


class VaultSearcher:
    """Orchestrates hybrid search across vault and codebase."""

    def __init__(
        self,
        root_dir: pathlib.Path,
        model: EmbeddingModel,
        store: VaultStore,
        *,
        graph_ttl_seconds: float | None = None,
    ) -> None:
        if graph_ttl_seconds is None:
            from .config import get_config

            graph_ttl_seconds = get_config().graph_ttl_seconds
        self.root_dir = root_dir
        self.model = model
        self.store = store
        self._graph_ttl = graph_ttl_seconds
        self._cached_graph: VaultGraph | None = None
        self._graph_built_at: float = 0.0

    def _get_graph(self) -> VaultGraph | None:
        from vaultspec.graph import VaultGraph as _VaultGraph

        now = time.monotonic()
        if self._cached_graph is None or (now - self._graph_built_at) > self._graph_ttl:
            try:
                self._cached_graph = _VaultGraph(self.root_dir)
                self._graph_built_at = now
            except Exception as e:
                logger.error("Search failed: %s", e)
                self._graph_built_at = now
                return None
        return self._cached_graph

    def search_vault(self, raw_query: str, top_k: int = 5) -> list[SearchResult]:
        """Search only the documentation vault."""
        parsed = parse_query(raw_query)
        query_text = parsed.text or raw_query
        query_vector = self.model.encode_query(query_text)
        sparse_vector = self.model.encode_query_sparse(query_text)
        store_filters = {
            k: v
            for k, v in parsed.filters.items()
            if k in ("doc_type", "feature", "date")
        }

        raw_results = self.store.hybrid_search(
            query_vector=query_vector.tolist(),
            query_text=query_text,
            filters=store_filters or None,
            limit=top_k * 2,
            sparse_vector=sparse_vector,
        )

        results = []
        for r in raw_results:
            score = r.get("_relevance_score", 0.0)
            results.append(
                SearchResult(
                    id=r["id"],
                    path=r["path"],
                    title=r.get("title", ""),
                    score=float(score),
                    snippet=r.get("content", "")[:200].strip(),
                    source="vault",
                    doc_type=r.get("doc_type", ""),
                    feature=r.get("feature", ""),
                    date=r.get("date", ""),
                )
            )

        graph = self._get_graph()
        results = rerank_with_graph(results, self.root_dir, parsed, graph=graph)
        return results[:top_k]

    def search_codebase(self, raw_query: str, top_k: int = 5) -> list[SearchResult]:
        """Search only the source codebase."""
        parsed = parse_query(raw_query)
        query_text = parsed.text or raw_query
        query_vector = self.model.encode_query(query_text)
        sparse_vector = self.model.encode_query_sparse(query_text)
        store_filters = {
            k: v for k, v in parsed.filters.items() if k in ("language", "path")
        }

        raw_results = self.store.hybrid_search_codebase(
            query_vector=query_vector.tolist(),
            query_text=query_text,
            filters=store_filters or None,
            limit=top_k,
            sparse_vector=sparse_vector,
        )

        results = []
        for r in raw_results:
            score = r.get("_relevance_score", 0.0)
            results.append(
                SearchResult(
                    id=r["id"],
                    path=r["path"],
                    title=r["path"],
                    score=float(score),
                    snippet=r.get("content", "")[:200].strip(),
                    source="codebase",
                    language=r.get("language", ""),
                    line_start=r.get("line_start"),
                    line_end=r.get("line_end"),
                )
            )
        return results

    def search_all(self, raw_query: str, top_k: int = 5) -> list[SearchResult]:
        """Search both vault and codebase and combine results."""
        vault_results = self.search_vault(raw_query, top_k=top_k)
        code_results = self.search_codebase(raw_query, top_k=top_k)

        all_results = vault_results + code_results
        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[:top_k]

    def search(self, raw_query: str, top_k: int = 5) -> list[SearchResult]:
        """Alias for search_all — searches vault and codebase."""
        return self.search_all(raw_query, top_k=top_k)
