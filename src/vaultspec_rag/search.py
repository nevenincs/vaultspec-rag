"""Retrieval pipeline for vault semantic search.

Implements query parsing, hybrid search, and graph-aware re-ranking.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

    from sentence_transformers import CrossEncoder
    from vaultspec_core.graph import VaultGraph

    from .embeddings import EmbeddingModel, SparseResult
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
# tag:#research, lang:python, path:src/,
# func:encode, class:Foo, nodetype:function_definition
_FILTER_PATTERN = re.compile(
    r"\b(type|feature|date|tag|lang|path|func|class|nodetype):(\S+)",
)

_FILTER_KEY_MAP = {
    "type": "doc_type",
    "feature": "feature",
    "date": "date",
    "lang": "language",
    "path": "path",
    "func": "function_name",
    "class": "class_name",
    "nodetype": "node_type",
}


@dataclass
class ParsedQuery:
    """A parsed search query with extracted metadata filters."""

    text: str
    filters: dict[str, str]


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
    node_type: str | None = None
    function_name: str | None = None
    class_name: str | None = None


def parse_query(raw_query: str) -> ParsedQuery:
    """Parse a raw query string into text and metadata filters.

    Extracts structured filter tokens (e.g. ``type:adr``,
    ``feature:rag``) from the query and returns the remaining
    natural-language text alongside the parsed filters.

    Args:
        raw_query: Raw query string, possibly containing filter
            tokens such as ``type:adr`` or ``date:2026-02``.

    Returns:
        ParsedQuery with the cleaned text and extracted filters.
    """
    filters: dict[str, str] = {}

    for match in _FILTER_PATTERN.finditer(raw_query):
        key = match.group(1)
        value = match.group(2)

        if key == "tag":
            filters["tag"] = value.lstrip("#")
        elif key in _FILTER_KEY_MAP:
            filters[_FILTER_KEY_MAP[key]] = value

    text = _FILTER_PATTERN.sub("", raw_query).strip()
    text = re.sub(r"\s+", " ", text)

    return ParsedQuery(text=text, filters=filters)


def rerank_with_graph(
    results: list[SearchResult],
    root_dir: pathlib.Path,
    query: ParsedQuery,
    graph: VaultGraph | None = None,
) -> list[SearchResult]:
    """Apply graph-aware score boosts to vault search results.

    Boosts vault results based on in-link count (up to +100%)
    and neighbor feature-tag matches (+15%).  Codebase results
    pass through unmodified.  The combined list is re-sorted by
    score descending.

    Args:
        results: Mixed vault/codebase results to rerank.
        root_dir: Project root used to build a VaultGraph when
            *graph* is ``None``.
        query: Parsed query; its ``feature`` filter drives the
            neighbor-feature boost.
        graph: Pre-built graph.  When ``None``, a new VaultGraph
            is constructed from *root_dir*.

    Returns:
        Re-sorted list of SearchResult with updated scores.
    """
    vault_results = [r for r in results if r.source == "vault"]
    code_results = [r for r in results if r.source == "codebase"]

    if not vault_results:
        return results

    if graph is None:
        from vaultspec_core.graph import VaultGraph as _VaultGraph

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

    all_results = vault_results + code_results
    all_results.sort(key=lambda r: r.score, reverse=True)
    return all_results


def _normalize_minmax(results: list[SearchResult], weight: float = 1.0) -> None:
    """Normalize scores in-place using min-max scaling, then apply weight.

    Handles edge cases: empty list, all-same scores (set to weight).

    Args:
        results: Search results whose ``score`` attributes are
            modified in-place.
        weight: Multiplier applied after scaling to [0, 1].

    Returns:
        None.  Scores are mutated in-place.
    """
    if not results:
        return
    scores = [r.score for r in results]
    lo, hi = min(scores), max(scores)
    span = hi - lo
    if span == 0:
        for r in results:
            r.score = weight
    else:
        for r in results:
            r.score = ((r.score - lo) / span) * weight


class VaultSearcher:
    """Orchestrates hybrid search across vault and codebase."""

    def __init__(
        self,
        root_dir: pathlib.Path,
        model: EmbeddingModel,
        store: VaultStore,
        *,
        graph_ttl_seconds: float | None = None,
        graph_provider: Callable[[], VaultGraph | None] | None = None,
    ) -> None:
        """Initialize the searcher.

        Args:
            root_dir: Project root directory containing the vault.
            model: Embedding model used for query encoding.
            store: Vector store backend (Qdrant local mode).
            graph_ttl_seconds: TTL for the cached VaultGraph in
                seconds.  Defaults to the value from project config
                (``graph_ttl_seconds``).  Only used when
                *graph_provider* is ``None``.
            graph_provider: Zero-arg callable returning the current
                ``VaultGraph`` (or ``None``).  When set,
                ``_get_graph()`` delegates entirely to it and the
                internal cache fields are unused.  When ``None``,
                an internal lock+TTL cache is used as fallback.
        """
        from .config import get_config

        cfg = get_config()
        if graph_ttl_seconds is None:
            graph_ttl_seconds = cfg.graph_ttl_seconds
        self.root_dir = root_dir
        self.model = model
        self.store = store
        self._graph_provider = graph_provider
        self._graph_ttl = graph_ttl_seconds
        self._cached_graph: VaultGraph | None = None
        self._graph_built_at: float = 0.0
        self._graph_lock = threading.Lock()
        self._reranker_enabled: bool = cfg.reranker_enabled
        self._reranker_model_name: str = cfg.reranker_model
        self._reranker = None
        self._reranker_lock = threading.Lock()

    def _get_reranker(self) -> CrossEncoder:
        """Lazily load the CrossEncoder reranker model onto GPU.

        Returns the cached CrossEncoder instance on subsequent calls.
        The model (BAAI/bge-reranker-v2-m3 by default) is loaded with
        ``activation_fn=Sigmoid()`` for calibrated [0, 1] scores.

        Returns:
            Cached or newly loaded CrossEncoder instance.

        Raises:
            RuntimeError: If no CUDA GPU is available.
        """
        if self._reranker is not None:
            return self._reranker
        with self._reranker_lock:
            if self._reranker is not None:
                return self._reranker
            import torch
            from sentence_transformers import CrossEncoder

            if not torch.cuda.is_available():
                msg = (
                    "CUDA GPU required for CrossEncoder reranker. No CUDA device found."
                )
                raise RuntimeError(msg)
            self._reranker = CrossEncoder(
                self._reranker_model_name,
                device="cuda",
                activation_fn=torch.nn.Sigmoid(),
            )
            logger.info(
                "CrossEncoder reranker loaded on %s: %s",
                torch.cuda.get_device_name(0),
                self._reranker_model_name,
            )
            return self._reranker

    def _rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """Rerank results using CrossEncoder if enabled.

        When the reranker is disabled or there are fewer than two
        results, returns ``results[:top_k]`` unchanged.  Otherwise
        scores are replaced with CrossEncoder sigmoid outputs, the
        list is re-sorted, and the top *top_k* are returned.

        Args:
            query: Natural-language query text.
            results: Candidate results to rerank.
            top_k: Maximum number of results to return.

        Returns:
            Reranked (or truncated) list of SearchResult.

        Raises:
            torch.cuda.OutOfMemoryError: If OOM persists even
                after halving batch size down to 1.
        """
        if not self._reranker_enabled or len(results) <= 1:
            return results[:top_k]
        import torch

        from .config import get_config

        reranker = self._get_reranker()
        pairs = [(query, r.snippet) for r in results]
        batch_size = get_config().reranker_batch_size
        while True:
            try:
                scores = reranker.predict(pairs, batch_size=batch_size)
                break
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                if batch_size <= 1:
                    raise
                batch_size = max(1, batch_size // 2)
                logger.warning(
                    "CUDA OOM during reranking, retrying with batch_size=%d",
                    batch_size,
                )
        for result, score in zip(results, scores, strict=True):
            result.score = float(score)
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def _get_graph(self) -> VaultGraph | None:
        """Return the cached VaultGraph, rebuilding on TTL expiry.

        When a ``graph_provider`` was supplied at construction time,
        delegates entirely to it.  Otherwise falls back to an
        internal lock+TTL cache (fixes R36-C1 for the fallback
        path).

        Returns:
            Cached VaultGraph, or ``None`` if the build fails.
        """
        if self._graph_provider is not None:
            return self._graph_provider()

        from vaultspec_core.graph import VaultGraph as _VaultGraph

        now = time.monotonic()
        if self._cached_graph is None or (now - self._graph_built_at) > self._graph_ttl:
            with self._graph_lock:
                now = time.monotonic()
                if (
                    self._cached_graph is None
                    or (now - self._graph_built_at) > self._graph_ttl
                ):
                    try:
                        self._cached_graph = _VaultGraph(self.root_dir)
                        self._graph_built_at = now
                    except Exception as e:
                        logger.error("Graph build failed: %s", e)
                        self._graph_built_at = now
                        return None
        return self._cached_graph

    def _search_vault_encoded(
        self,
        query_vector: list[float],
        sparse_vector: SparseResult | None,
        parsed: ParsedQuery,
        query_text: str,
        top_k: int,
    ) -> list[SearchResult]:
        """Search vault using pre-encoded dense and sparse vectors.

        Runs hybrid search (dense + SPLADE) via Qdrant, applies
        CrossEncoder reranking (if enabled), then graph reranking.

        Args:
            query_vector: Dense embedding of the query (1024-d).
            sparse_vector: SPLADE sparse embedding of the query.
            parsed: Parsed query with extracted metadata filters.
            query_text: Clean query text (filters removed).
            top_k: Maximum number of results to return.

        Returns:
            Ranked list of vault SearchResult instances.
        """
        store_filters = {
            k: v
            for k, v in parsed.filters.items()
            if k in ("doc_type", "feature", "date", "tag")
        }

        # Fetch extra candidates when reranker will narrow them down
        fetch_limit = max(top_k * 4, 20) if self._reranker_enabled else top_k * 2
        raw_results = self.store.hybrid_search(
            query_vector=query_vector,
            query_text=query_text,
            filters=store_filters or None,
            limit=fetch_limit,
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
                ),
            )

        results = self._rerank(query_text, results, top_k)
        graph = self._get_graph()
        return rerank_with_graph(results, self.root_dir, parsed, graph=graph)

    def _search_codebase_encoded(
        self,
        query_vector: list[float],
        sparse_vector: SparseResult | None,
        parsed: ParsedQuery,
        query_text: str,
        top_k: int,
        *,
        language: str | None = None,
        node_type: str | None = None,
        function_name: str | None = None,
        class_name: str | None = None,
    ) -> list[SearchResult]:
        """Search codebase using pre-encoded dense and sparse vectors.

        Runs hybrid search against the codebase collection, then
        applies CrossEncoder reranking if enabled.

        Args:
            query_vector: Dense embedding of the query (1024-d).
            sparse_vector: SPLADE sparse embedding of the query.
            parsed: Parsed query with extracted metadata filters.
            query_text: Clean query text (filters removed).
            top_k: Maximum number of results to return.
            language: Optional language filter (e.g. ``'python'``).
            node_type: Optional AST node type filter.
            function_name: Optional function/method name filter.
            class_name: Optional class/struct name filter.

        Returns:
            Ranked list of codebase SearchResult instances.
        """
        store_filters = {
            k: v
            for k, v in parsed.filters.items()
            if k in ("language", "path", "node_type", "function_name", "class_name")
        }
        if language is not None:
            store_filters["language"] = language
        if node_type is not None:
            store_filters["node_type"] = node_type
        if function_name is not None:
            store_filters["function_name"] = function_name
        if class_name is not None:
            store_filters["class_name"] = class_name

        fetch_limit = max(top_k * 4, 20) if self._reranker_enabled else top_k * 2
        raw_results = self.store.hybrid_search_codebase(
            query_vector=query_vector,
            query_text=query_text,
            filters=store_filters or None,
            limit=fetch_limit,
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
                    node_type=r.get("node_type"),
                    function_name=r.get("function_name"),
                    class_name=r.get("class_name"),
                ),
            )
        return self._rerank(query_text, results, top_k)

    def _encode_query(
        self,
        raw_query: str,
    ) -> tuple[ParsedQuery, str, list[float], SparseResult]:
        """Parse and encode a query, returning shared components.

        Used by ``search_vault``, ``search_codebase``, and
        ``search_all`` to encode the query exactly once.

        Args:
            raw_query: Raw query string, possibly with filter
                tokens.

        Returns:
            Four-element tuple of (parsed_query, cleaned_text,
            dense_vector, sparse_vector).
        """
        parsed = parse_query(raw_query)
        query_text = parsed.text or raw_query
        query_vector = self.model.encode_query(query_text).tolist()
        sparse_vector = self.model.encode_query_sparse(query_text)
        return parsed, query_text, query_vector, sparse_vector

    def search_vault(self, raw_query: str, top_k: int = 5) -> list[SearchResult]:
        """Search only the vault collection.

        Parses the query, encodes it, and delegates to
        ``_search_vault_encoded``.

        Args:
            raw_query: Natural language query, optionally with
                filter tokens.
            top_k: Maximum number of results to return.

        Returns:
            Ranked list of vault SearchResult instances.
        """
        parsed, query_text, query_vector, sparse_vector = self._encode_query(raw_query)
        return self._search_vault_encoded(
            query_vector,
            sparse_vector,
            parsed,
            query_text,
            top_k,
        )

    def search_codebase(
        self,
        raw_query: str,
        top_k: int = 5,
        *,
        language: str | None = None,
        node_type: str | None = None,
        function_name: str | None = None,
        class_name: str | None = None,
    ) -> list[SearchResult]:
        """Search only the source codebase.

        Args:
            raw_query: Natural language query or code snippet.
            top_k: Number of results to return.
            language: Optional language filter (e.g., 'python', 'rust').
            node_type: Optional AST node type filter.
            function_name: Optional function/method name filter.
            class_name: Optional class/struct name filter.

        Returns:
            Ranked list of codebase SearchResult instances.
        """
        parsed, query_text, query_vector, sparse_vector = self._encode_query(raw_query)
        return self._search_codebase_encoded(
            query_vector,
            sparse_vector,
            parsed,
            query_text,
            top_k,
            language=language,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
        )

    def search_all(
        self,
        raw_query: str,
        top_k: int = 5,
        *,
        vault_weight: float = 0.5,
        code_weight: float = 0.5,
    ) -> list[SearchResult]:
        """Search both vault and codebase with score normalization.

        Each result set is normalized independently before combining:
        - RRF (Reciprocal Rank Fusion) scores from Qdrant hybrid
          search use min-max normalization.
        - CrossEncoder scores use sigmoid normalization (when the
          reranker is enabled).

        Note: Graph reranking is NOT applied to search_all results
        -- it only applies within search_vault().  Vault and code
        results are normalized separately using min-max scaling
        before merging (equal weighting by default).

        Args:
            raw_query: Natural language search query.
            top_k: Number of results to return.
            vault_weight: Weight for vault results (default 0.5).
            code_weight: Weight for codebase results (default 0.5).

        Returns:
            Merged and re-sorted list of SearchResult from both
            vault and codebase collections.
        """
        parsed, query_text, query_vector, sparse_vector = self._encode_query(raw_query)

        vault_results = self._search_vault_encoded(
            query_vector,
            sparse_vector,
            parsed,
            query_text,
            top_k,
        )
        code_results = self._search_codebase_encoded(
            query_vector,
            sparse_vector,
            parsed,
            query_text,
            top_k,
        )

        _normalize_minmax(vault_results, vault_weight)
        _normalize_minmax(code_results, code_weight)

        all_results = vault_results + code_results
        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[:top_k]

    def search(self, raw_query: str, top_k: int = 5) -> list[SearchResult]:
        """Search vault and codebase with equal weights.

        Delegates to ``search_all`` with default weights
        (vault_weight=0.5, code_weight=0.5).

        Args:
            raw_query: Natural language search query.
            top_k: Number of results to return.

        Returns:
            Merged and re-sorted list of SearchResult.
        """
        return self.search_all(raw_query, top_k=top_k)
