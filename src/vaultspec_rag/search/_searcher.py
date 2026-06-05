"""The VaultSearcher orchestration class for hybrid search.

Owns the stateful search pipeline: query encoding (Qwen3 dense + SPLADE
sparse), Qdrant hybrid search with RRF fusion, optional CrossEncoder
reranking, and graph-aware score boosts. Holds the GPU lock, the lazily
loaded reranker, and the TTL-cached VaultGraph.
"""

from __future__ import annotations

import fnmatch
import logging
import threading
import time
from contextlib import nullcontext
from typing import TYPE_CHECKING

from ._models import ParsedQuery, SearchResult
from ._parsing import parse_query
from ._postprocess import (
    _GLOB_FETCH_MULTIPLIER,
    _PREFER_CATEGORIES,
    _PREFER_SCORE_NUDGE,
    _classify_chunk_type,
    _collapse_locale_variants,
)
from ._rerank import rerank_with_graph

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

    from sentence_transformers import CrossEncoder
    from vaultspec_core.graph import VaultGraph

    from ..embeddings import EmbeddingModel, SparseResult
    from ..store import VaultStore

logger = logging.getLogger(__name__)


class VaultSearcher:
    """Orchestrates hybrid search across vault and codebase.

    Encodes queries into dense (Qwen3) and sparse (SPLADE) vectors,
    executes Qdrant hybrid search with RRF fusion, optionally reranks
    results with a CrossEncoder, and applies graph-aware score boosts
    using the VaultGraph relationship data.  Supports searching vault
    documents, codebase chunks, or both collections in a single call.
    """

    def __init__(
        self,
        root_dir: pathlib.Path,
        model: EmbeddingModel,
        store: VaultStore,
        *,
        graph_ttl_seconds: float | None = None,
        graph_provider: Callable[[], VaultGraph | None] | None = None,
        gpu_lock: threading.Lock | None = None,
        reranker: CrossEncoder | None = None,
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
            gpu_lock: Optional ``threading.Lock`` that serializes
                GPU operations (encoding + reranking) across
                concurrent search calls.  When ``None``, no
                external serialization is applied.
            reranker: Optional pre-loaded ``CrossEncoder`` shared
                across searchers (avoids ~560 MB VRAM per instance).
                When ``None``, the searcher loads its own on first
                use.
        """
        from ..config import get_config

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
        self._gpu_lock = gpu_lock
        self._reranker_enabled: bool = cfg.reranker_enabled
        self._reranker_model_name: str = cfg.reranker_model
        self._reranker = reranker
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

        from ..config import get_config

        reranker = self._get_reranker()
        pairs = [(query, r.snippet) for r in results]
        batch_size = get_config().reranker_batch_size
        with self._gpu_lock if self._gpu_lock is not None else nullcontext():
            while True:
                try:
                    scores = reranker.predict(
                        pairs,
                        batch_size=batch_size,
                        show_progress_bar=False,
                    )
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
        *,
        doc_type: str | None = None,
        feature: str | None = None,
        date: str | None = None,
        tag: str | None = None,
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
            doc_type: Optional vault doc-type filter (e.g. ``'adr'``).
            feature: Optional feature-tag filter.
            date: Optional ISO date filter.
            tag: Optional free-form tag filter.

        Returns:
            Ranked list of vault SearchResult instances.
        """
        store_filters = {
            k: v
            for k, v in parsed.filters.items()
            if k in ("doc_type", "feature", "date", "tag")
        }
        if doc_type is not None:
            store_filters["doc_type"] = doc_type
        if feature is not None:
            store_filters["feature"] = feature
        if date is not None:
            store_filters["date"] = date
        if tag is not None:
            store_filters["tag"] = tag

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
        path: str | None = None,
        node_type: str | None = None,
        function_name: str | None = None,
        class_name: str | None = None,
        include_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        dedup_locales: bool = False,
        prefer: str | None = None,
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
            include_paths: Optional fnmatch glob list; a result is
                kept only when at least one pattern matches its
                project-relative path. Patterns are normalised so
                Windows-style backslashes work transparently.
            exclude_paths: Optional fnmatch glob list; a result is
                dropped when any pattern matches its
                project-relative path.
            dedup_locales: When True, collapse near-duplicate
                locale-variant paths after rerank - the highest
                scoring entry wins, the others drop.
            prefer: When set to ``"prod"`` / ``"tests"`` /
                ``"docs"``, apply ``±_PREFER_SCORE_NUDGE`` to
                results based on path-derived category after
                rerank, then re-sort. Opt-in; default is no
                preference.

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
        if path is not None:
            store_filters["path"] = path
        if node_type is not None:
            store_filters["node_type"] = node_type
        if function_name is not None:
            store_filters["function_name"] = function_name
        if class_name is not None:
            store_filters["class_name"] = class_name

        # Normalise caller patterns once. The codebase indexer stores
        # POSIX paths on every platform (indexer.py:1600 replaces
        # backslashes), so glob matching is consistent if patterns
        # carry the same convention.
        include_norm = (
            [p.replace("\\", "/") for p in include_paths] if include_paths else []
        )
        exclude_norm = (
            [p.replace("\\", "/") for p in exclude_paths] if exclude_paths else []
        )
        has_glob_filter = bool(include_norm or exclude_norm)

        if has_glob_filter:
            fetch_limit = max(top_k * _GLOB_FETCH_MULTIPLIER, 50)
        else:
            fetch_limit = max(top_k * 4, 20) if self._reranker_enabled else top_k * 2
        raw_results = self.store.hybrid_search_codebase(
            query_vector=query_vector,
            query_text=query_text,
            filters=store_filters or None,
            limit=fetch_limit,
            sparse_vector=sparse_vector,
        )

        # Post-query glob filter. Runs before SearchResult / rerank
        # so the CrossEncoder cost is proportional to the survivors,
        # not the over-fetched raw set.
        if has_glob_filter:
            filtered: list[dict] = []
            for r in raw_results:
                path_value = str(r.get("path", ""))
                if include_norm and not any(
                    fnmatch.fnmatch(path_value, pat) for pat in include_norm
                ):
                    continue
                if exclude_norm and any(
                    fnmatch.fnmatch(path_value, pat) for pat in exclude_norm
                ):
                    continue
                filtered.append(r)
            raw_results = filtered

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
        results = self._rerank(query_text, results, top_k)

        # --prefer post-rerank score nudge. Apply ±_PREFER_SCORE_NUDGE
        # based on path-derived category, then re-sort. The
        # CrossEncoder's query-relevance scoring runs first; user
        # preference re-orders ties and near-ties only.
        if prefer in _PREFER_CATEGORIES:
            for r in results:
                category = _classify_chunk_type(r.path)
                if category == prefer:
                    r.score += _PREFER_SCORE_NUDGE
                else:
                    r.score -= _PREFER_SCORE_NUDGE
            results.sort(key=lambda r: r.score, reverse=True)

        # --dedup-locales collapse pass. Group results by locale
        # stem; within each group, near-tie scores (within
        # _LOCALE_DEDUP_SCORE_WINDOW) collapse to the highest-scoring
        # entry. Non-locale paths and singletons pass through.
        if dedup_locales:
            results = _collapse_locale_variants(results)

        return results

    def _encode_query(
        self,
        raw_query: str,
    ) -> tuple[ParsedQuery, str, list[float], SparseResult]:
        """Parse and encode a query, returning shared components.

        Used by ``search_vault`` and ``search_codebase`` to
        encode the query exactly once.

        Args:
            raw_query: Raw query string, possibly with filter
                tokens.

        Returns:
            Four-element tuple of (parsed_query, cleaned_text,
            dense_vector, sparse_vector).
        """
        parsed = parse_query(raw_query)
        query_text = parsed.text or raw_query
        with self._gpu_lock if self._gpu_lock is not None else nullcontext():
            query_vector = self.model.encode_query(query_text).tolist()
            sparse_vector = self.model.encode_query_sparse(query_text)
        return parsed, query_text, query_vector, sparse_vector

    def search_vault(
        self,
        raw_query: str,
        top_k: int = 5,
        *,
        doc_type: str | None = None,
        feature: str | None = None,
        date: str | None = None,
        tag: str | None = None,
    ) -> list[SearchResult]:
        """Search only the vault collection.

        Parses the query, encodes it, and delegates to
        ``_search_vault_encoded``.

        Args:
            raw_query: Natural language query, optionally with
                filter tokens.
            top_k: Maximum number of results to return.
            doc_type: Optional vault doc-type filter (e.g. ``'adr'``).
            feature: Optional feature-tag filter.
            date: Optional ISO date filter.
            tag: Optional free-form tag filter.

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
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
        )

    def search_codebase(
        self,
        raw_query: str,
        top_k: int = 5,
        *,
        language: str | None = None,
        path: str | None = None,
        node_type: str | None = None,
        function_name: str | None = None,
        class_name: str | None = None,
        include_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        dedup_locales: bool = False,
        prefer: str | None = None,
    ) -> list[SearchResult]:
        """Search only the source codebase.

        Args:
            raw_query: Natural language query or code snippet.
            top_k: Number of results to return.
            language: Optional language filter (e.g., 'python', 'rust').
            path: Optional exact-match path filter
                (KEYWORD payload index).
            node_type: Optional AST node type filter.
            function_name: Optional function/method name filter.
            class_name: Optional class/struct name filter.
            include_paths: Optional fnmatch glob patterns; results
                whose project-relative path matches at least one
                pattern are kept (post-query Python filter).
            exclude_paths: Optional fnmatch glob patterns; results
                whose project-relative path matches any pattern
                are dropped (post-query Python filter).
            dedup_locales: When True, collapse near-tie locale
                variants (e.g. ``locales/{en,es}.yml``) into a
                single canonical result. Opt-in.
            prefer: Optional ``"prod" | "tests" | "docs"`` -
                applies a small +/- score nudge to the matching
                category after rerank. Opt-in.

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
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            dedup_locales=dedup_locales,
            prefer=prefer,
        )
