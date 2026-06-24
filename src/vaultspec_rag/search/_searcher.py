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
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, cast

from ._intent_rank import apply_intent_prior, apply_status_filter, apply_type_cap
from ._models import ParsedQuery, SearchResult
from ._parsing import parse_query
from ._postprocess import (
    GLOB_FETCH_MULTIPLIER,
    PREFER_CATEGORIES,
    PREFER_SCORE_NUDGE,
    _classify_chunk_type,  # pyright: ignore[reportPrivateUsage]  # intra-package intentional re-export
    _collapse_locale_variants,  # pyright: ignore[reportPrivateUsage]  # intra-package intentional re-export
)
from ._rerank import rerank_with_graph

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Mapping

    from sentence_transformers import CrossEncoder
    from vaultspec_core.graph import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
        VaultGraph,
    )

    from ..embeddings import EmbeddingModel, SparseResult
    from ..store import VaultStore

logger = logging.getLogger(__name__)


def _format_locator(payload: dict[str, object]) -> str | None:
    """Render a preprocess result's split locator into a readable string (#185).

    Combines the ``locator_kind`` with whichever of ``locator_value_int`` /
    ``locator_value_str`` is present, e.g. ``"page 12"`` or ``"sheet Summary"``.
    Returns ``None`` for ordinary code chunks (no locator kind).
    """
    kind = payload.get("locator_kind")
    if not isinstance(kind, str) or not kind:
        return None
    value = _locator_component(payload, "locator_value_int", "locator_value_str")
    if value is None:
        return kind
    end = _locator_component(payload, "locator_end_int", "locator_end_str")
    if end is not None:
        return f"{kind} {value}-{end}"
    return f"{kind} {value}"


def _locator_component(
    payload: dict[str, object], int_key: str, str_key: str
) -> str | None:
    """Return the int or str locator component as a display string, or None."""
    value_int = payload.get(int_key)
    if isinstance(value_int, int) and not isinstance(value_int, bool):
        return str(value_int)
    value_str = payload.get(str_key)
    if isinstance(value_str, str) and value_str:
        return value_str
    return None


def _join_doc_path(docs_prefix: str, stored_path: str) -> str:
    """Return a vault doc's path relative to the project root.

    Vault chunks store their path relative to the docs directory
    (e.g. ``research/foo.md``); prepending the docs prefix
    (``.vault``) yields a path that resolves from the project root the
    same way code-result paths do. Idempotent if the prefix is already
    present.
    """
    if not docs_prefix:
        return stored_path
    normalised = stored_path.replace("\\", "/")
    prefix = docs_prefix.replace("\\", "/").rstrip("/")
    if normalised == prefix or normalised.startswith(prefix + "/"):
        return normalised
    return f"{prefix}/{normalised}"


def _group_chunks_by_document(results: list[SearchResult]) -> list[SearchResult]:
    """Collapse chunk-level vault hits to one result per document.

    The vault collection stores one point per document chunk, so a
    single document can occupy several candidate slots. The
    best-scoring chunk represents its document (its snippet is the
    matched passage); duplicates drop. Order follows the surviving
    scores, descending.
    """
    best: dict[str, SearchResult] = {}
    for result in results:
        current = best.get(result.id)
        if current is None or result.score > current.score:
            best[result.id] = result
    return sorted(best.values(), key=lambda r: r.score, reverse=True)


def _record_seconds(
    timings: dict[str, float] | None,
    key: str,
    started: float,
) -> None:
    if timings is not None:
        timings[key] = time.perf_counter() - started


def _add_seconds(
    timings: dict[str, float] | None,
    key: str,
    seconds: float,
) -> None:
    if timings is not None:
        timings[key] = timings.get(key, 0.0) + seconds


class VaultGraphError(RuntimeError):
    """Raised when the VaultGraph fails to initialize."""


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
        resolved_ttl: float = (
            graph_ttl_seconds
            if graph_ttl_seconds is not None
            else float(cfg.graph_ttl_seconds)
        )
        self.root_dir = root_dir
        self.model = model
        self.store = store
        self._graph_provider = graph_provider
        self._graph_ttl: float = resolved_ttl
        self._cached_graph: VaultGraph | None = None
        self._graph_built_at: float = 0.0
        self._graph_lock = threading.Lock()
        self._gpu_lock = gpu_lock
        self._reranker_enabled: bool = cfg.reranker_enabled
        self._reranker_model_name: str = cfg.reranker_model
        self._sparse_enabled: bool = cfg.sparse_enabled
        self._reranker = reranker
        self._reranker_lock = threading.Lock()

    def _vault_docs_prefix(self) -> str:
        """The docs directory (e.g. ``.vault``) vault paths are stored under."""
        from ..config import get_config

        return str(get_config().docs_dir)

    @contextmanager
    def _gpu_section(self, timings: dict[str, float] | None = None):
        if self._gpu_lock is None:
            with nullcontext():
                yield
            return
        started = time.perf_counter()
        self._gpu_lock.acquire()
        wait_seconds = time.perf_counter() - started
        _add_seconds(timings, "gpu_queue_wait_seconds", wait_seconds)
        _add_seconds(timings, "queue_wait_seconds", wait_seconds)
        try:
            yield
        finally:
            self._gpu_lock.release()

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

            from ..config import get_config

            if not torch.cuda.is_available():
                msg = (
                    "CUDA GPU required for CrossEncoder reranker. No CUDA device found."
                )
                raise RuntimeError(msg)
            self._reranker = CrossEncoder(
                self._reranker_model_name,
                device="cuda",
                activation_fn=torch.nn.Sigmoid(),
                max_length=int(get_config().reranker_max_length),
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
        *,
        timings: dict[str, float] | None = None,
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

        cfg = get_config()
        reranker = self._get_reranker()
        # Score the real candidate content, not the 200-char display
        # snippet. The character cap only bounds tokenizer work on
        # oversized rows (~6 chars per BPE token is a safe ceiling);
        # the model's own max_length does the exact token truncation.
        char_cap = max(1, int(cfg.reranker_max_length)) * 6
        pairs = [(query, (r.rerank_text or r.snippet)[:char_cap]) for r in results]
        batch_size = cfg.reranker_batch_size
        raw_scores = None
        # The GPU lock wraps only the model forward call; the
        # score-to-float conversion below runs after release.
        with self._gpu_section(timings):
            while True:
                try:
                    raw_scores = reranker.predict(  # pyright: ignore[reportUnknownMemberType]  # sentence_transformers stubs incomplete
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
        scores = [float(s) for s in raw_scores]
        for result, score in zip(results, scores, strict=True):
            result.score = score
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

        from vaultspec_core.graph import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
            VaultGraph as _VaultGraph,
        )

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
                        raise VaultGraphError("Failed to build vault graph") from e
        return self._cached_graph

    def _resolve_intent_profile(
        self, intent: str | None
    ) -> Mapping[str, Mapping[str, float]] | None:
        """Resolve the active intent weight profile, or ``None`` to skip.

        Returns ``None`` when intent ranking is disabled in config or the
        requested/default intent name has no profile, so the caller leaves the
        bare-reranker ordering untouched.
        """
        from ..config import get_config

        cfg = get_config()
        if not cfg.vault_intent_ranking_enabled:
            return None
        name = (intent or cfg.vault_intent_default or "orientation").strip().lower()
        # Accept the ADR-prose spelling ``debug`` as an alias for the canonical
        # ``debugging`` profile so a literal ``intent:debug`` is not a silent no-op.
        if name == "debug":
            name = "debugging"
        profile = cfg.intent_weight_profiles.get(name)
        if profile is None and intent is not None:
            # An explicitly requested intent with no shipped profile (e.g. a
            # typo, or the deferred ``implementation`` profile) silently falls
            # back to the bare-reranker ordering; log it so it is diagnosable.
            logger.debug(
                "intent %r has no ranking profile; using bare-reranker ordering",
                intent,
            )
        return profile

    def _apply_intent_prior(
        self, results: list[SearchResult], intent: str | None
    ) -> list[SearchResult]:
        """Apply the intent type x status prior and per-type cap when active."""
        from ..config import get_config

        profile = self._resolve_intent_profile(intent)
        if profile is None:
            return results
        results = apply_intent_prior(results, profile)
        cap = int(get_config().vault_intent_type_cap)
        return apply_type_cap(results, cap)

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
        intent: str | None = None,
        like_ids: list[str | int] | None = None,
        unlike_ids: list[str | int] | None = None,
        timings: dict[str, float] | None = None,
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
            like_ids: Optional list of document IDs or point IDs to guide
                search (positive feedback).
            unlike_ids: Optional list of document IDs or point IDs to push
                search away (negative feedback).

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
        phase_started = time.perf_counter()
        raw_results: list[dict[str, object]] = cast(
            "list[dict[str, object]]",
            self.store.hybrid_search(
                query_vector=query_vector,
                _query_text=query_text,
                filters=store_filters or None,
                limit=fetch_limit,
                sparse_vector=sparse_vector,
                like_ids=like_ids,
                unlike_ids=unlike_ids,
            ),
        )
        _record_seconds(timings, "qdrant_seconds", phase_started)

        # Auto-generated feature-index documents are navigational document-lists
        # with no semantic content (ADR D6); they are never searchable and are
        # dropped before rerank so they cannot crowd or top the results (a real
        # vault search lists every feature doc inside one index file, which the
        # cross-encoder otherwise scores very high on feature-name queries).
        raw_results = [r for r in raw_results if r.get("doc_type") != "index"]

        phase_started = time.perf_counter()
        docs_prefix = self._vault_docs_prefix()
        results: list[SearchResult] = []
        for r in raw_results:
            raw_score = r.get("_relevance_score", 0.0)
            score = float(raw_score) if isinstance(raw_score, (int, float)) else 0.0
            content = str(r.get("content", ""))
            related_raw = r.get("related")
            related = (
                [str(x) for x in related_raw]
                if isinstance(related_raw, list)
                else []
            )
            results.append(
                SearchResult(
                    id=str(r["id"]),
                    path=_join_doc_path(docs_prefix, str(r["path"])),
                    title=str(r.get("title", "")),
                    score=score,
                    snippet=content[:200].strip(),
                    source="vault",
                    doc_type=str(r.get("doc_type", "")),
                    feature=str(r.get("feature", "")),
                    date=str(r.get("date", "")),
                    status=str(r.get("status", "")),
                    related=related,
                    rerank_text=content or None,
                ),
            )
        _record_seconds(timings, "result_mapping_seconds", phase_started)

        # Rerank the FULL fetched candidate set: grouping below can
        # collapse several chunks of one document into a single row, so
        # truncating before grouping could under-fill the final page
        # whenever one document's chunks dominate the rerank window.
        phase_started = time.perf_counter()
        results = self._rerank(query_text, results, len(results), timings=timings)
        _record_seconds(timings, "rerank_seconds", phase_started)

        phase_started = time.perf_counter()
        results = _group_chunks_by_document(results)
        graph = self._get_graph()
        results = rerank_with_graph(results, self.root_dir, parsed, graph=graph)
        # Intent-conditioned type x status prior: composes after the graph
        # nudges so the pipeline-role/status signal is primary and the graph
        # in-link/feature nudges break ties within the reweighted ordering. An
        # explicit intent argument wins; otherwise an inline ``intent:`` query
        # token selects the profile (the CLI surface, since a flag would breach
        # the frozen max-args lint ratchet).
        effective_intent = intent or parsed.filters.get("intent")
        results = self._apply_intent_prior(results, effective_intent)
        status_spec = parsed.filters.get("status")
        if status_spec:
            results = apply_status_filter(results, status_spec)
        _record_seconds(timings, "graph_rerank_seconds", phase_started)
        if timings is not None:
            timings["postprocess_seconds"] = (
                timings.get("result_mapping_seconds", 0.0)
                + timings.get("rerank_seconds", 0.0)
                + timings.get("graph_rerank_seconds", 0.0)
            )
        return results[:top_k]

    def _build_codebase_store_filters(
        self,
        parsed: ParsedQuery,
        language: str | None,
        path: str | None,
        node_type: str | None,
        function_name: str | None,
        class_name: str | None,
    ) -> dict[str, str]:
        store_filters = {
            k: v
            for k, v in parsed.filters.items()
            if k in ("language", "path", "node_type", "function_name", "class_name")
        }
        for k, v in (
            ("language", language),
            ("path", path),
            ("node_type", node_type),
            ("function_name", function_name),
            ("class_name", class_name),
        ):
            if v is not None:
                store_filters[k] = v
        return store_filters

    def _filter_raw_codebase_results(
        self,
        raw_results: list[dict[str, object]],
        include_norm: list[str],
        exclude_norm: list[str],
    ) -> list[dict[str, object]]:
        if not include_norm and not exclude_norm:
            return raw_results
        filtered: list[dict[str, object]] = []
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
        return filtered

    def _map_codebase_results(
        self, raw_results: list[dict[str, object]]
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        for r in raw_results:
            raw_score = r.get("_relevance_score", 0.0)
            score = float(raw_score) if isinstance(raw_score, (int, float)) else 0.0
            r_id = str(r["id"])
            r_path = str(r["path"])
            content = str(r.get("content", ""))
            snippet = content[:200].strip()
            language = str(r.get("language", ""))
            line_start = r.get("line_start")
            line_end = r.get("line_end")
            node_type = r.get("node_type")
            function_name = r.get("function_name")
            class_name = r.get("class_name")
            source_path = r.get("source_path")
            preprocessor_id = r.get("preprocessor_id")
            anchor = r.get("anchor")
            results.append(
                SearchResult(
                    id=r_id,
                    path=r_path,
                    title=r_path,
                    score=score,
                    snippet=snippet,
                    source="codebase",
                    language=language,
                    line_start=int(line_start) if isinstance(line_start, int) else None,
                    line_end=int(line_end) if isinstance(line_end, int) else None,
                    node_type=str(node_type) if node_type is not None else None,
                    function_name=(
                        str(function_name) if function_name is not None else None
                    ),
                    class_name=str(class_name) if class_name is not None else None,
                    source_path=str(source_path) if source_path is not None else None,
                    preprocessor_id=(
                        str(preprocessor_id) if preprocessor_id is not None else None
                    ),
                    anchor=str(anchor) if anchor is not None else None,
                    locator=_format_locator(r),
                    rerank_text=content or None,
                ),
            )
        return results

    def _apply_prefer_nudge(
        self, results: list[SearchResult], prefer: str | None
    ) -> None:
        if prefer not in PREFER_CATEGORIES:
            return
        for r in results:
            category = _classify_chunk_type(r.path)
            if category == prefer:
                r.score += PREFER_SCORE_NUDGE
            else:
                r.score -= PREFER_SCORE_NUDGE
        results.sort(key=lambda r: r.score, reverse=True)

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
        like_ids: list[str | int] | None = None,
        unlike_ids: list[str | int] | None = None,
        timings: dict[str, float] | None = None,
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
                ``"docs"``, apply ``±PREFER_SCORE_NUDGE`` to
                results based on path-derived category after
                rerank, then re-sort. Opt-in; default is no
                preference.
            like_ids: Optional list of chunk IDs or point IDs to guide
                search (positive feedback).
            unlike_ids: Optional list of chunk IDs or point IDs to push
                search away (negative feedback).

        Returns:
            Ranked list of codebase SearchResult instances.
        """
        store_filters = self._build_codebase_store_filters(
            parsed, language, path, node_type, function_name, class_name
        )

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
            fetch_limit = max(top_k * GLOB_FETCH_MULTIPLIER, 50)
        else:
            fetch_limit = max(top_k * 4, 20) if self._reranker_enabled else top_k * 2
        phase_started = time.perf_counter()
        raw_results: list[dict[str, object]] = cast(
            "list[dict[str, object]]",
            self.store.hybrid_search_codebase(
                query_vector=query_vector,
                _query_text=query_text,
                filters=store_filters or None,
                limit=fetch_limit,
                sparse_vector=sparse_vector,
                like_ids=like_ids,
                unlike_ids=unlike_ids,
            ),
        )
        _record_seconds(timings, "qdrant_seconds", phase_started)

        # Post-query glob filter. Runs before SearchResult / rerank
        # so the CrossEncoder cost is proportional to the survivors,
        # not the over-fetched raw set.
        phase_started = time.perf_counter()
        raw_results = self._filter_raw_codebase_results(
            raw_results, include_norm, exclude_norm
        )
        _record_seconds(timings, "glob_filter_seconds", phase_started)

        phase_started = time.perf_counter()
        results = self._map_codebase_results(raw_results)
        _record_seconds(timings, "result_mapping_seconds", phase_started)

        phase_started = time.perf_counter()
        results = self._rerank(query_text, results, top_k, timings=timings)
        _record_seconds(timings, "rerank_seconds", phase_started)

        # --prefer post-rerank score nudge. Apply ±PREFER_SCORE_NUDGE
        # based on path-derived category, then re-sort. The
        # CrossEncoder's query-relevance scoring runs first; user
        # preference re-orders ties and near-ties only.
        phase_started = time.perf_counter()
        self._apply_prefer_nudge(results, prefer)
        _record_seconds(timings, "prefer_seconds", phase_started)

        # --dedup-locales collapse pass. Group results by locale
        # stem; within each group, near-tie scores (within
        # _LOCALE_DEDUP_SCORE_WINDOW) collapse to the highest-scoring
        # entry. Non-locale paths and singletons pass through.
        phase_started = time.perf_counter()
        if dedup_locales:
            results = _collapse_locale_variants(results)
        _record_seconds(timings, "dedup_seconds", phase_started)
        if timings is not None:
            timings["postprocess_seconds"] = (
                timings.get("glob_filter_seconds", 0.0)
                + timings.get("result_mapping_seconds", 0.0)
                + timings.get("rerank_seconds", 0.0)
                + timings.get("prefer_seconds", 0.0)
                + timings.get("dedup_seconds", 0.0)
            )

        return results

    def _encode_query(
        self,
        raw_query: str,
        *,
        surface: str | None = None,
        timings: dict[str, float] | None = None,
    ) -> tuple[ParsedQuery, str, list[float], SparseResult | None]:
        """Parse and encode a query, returning shared components.

        Used by ``search_vault`` and ``search_codebase`` to
        encode the query exactly once.

        Args:
            raw_query: Raw query string, possibly with filter
                tokens.
            surface: Target corpus kind (``"vault"`` or ``"code"``)
                selecting the dense encoder's task instruction.

        Returns:
            Four-element tuple of (parsed_query, cleaned_text,
            dense_vector, sparse_vector).
        """
        parsed = parse_query(raw_query)
        query_text = parsed.text or raw_query

        # A cache hit skips both forward passes and - more importantly
        # under load - the GPU lock acquisition entirely. Entries that
        # were computed without a sparse vector are recomputed when
        # sparse encoding is enabled.
        cache_key = (surface or "", query_text)
        cached = self.model.query_cache.get(cache_key)
        if cached is not None and (not self._sparse_enabled or cached[1] is not None):
            dense, sparse = cached
            return (
                parsed,
                query_text,
                dense.tolist(),
                sparse if self._sparse_enabled else None,
            )

        with self._gpu_section(timings):
            dense = self.model.encode_query(query_text, surface=surface)
            sparse = (
                self.model.encode_query_sparse(query_text)
                if self._sparse_enabled
                else None
            )
        self.model.query_cache.put(cache_key, (dense, sparse))
        return parsed, query_text, dense.tolist(), sparse

    def search_vault(
        self,
        raw_query: str,
        top_k: int = 5,
        *,
        doc_type: str | None = None,
        feature: str | None = None,
        date: str | None = None,
        tag: str | None = None,
        intent: str | None = None,
        like_ids: list[str | int] | None = None,
        unlike_ids: list[str | int] | None = None,
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
            like_ids: Optional list of document IDs or point IDs to guide search.
            unlike_ids: Optional list of document IDs or point IDs to push search away.

        Returns:
            Ranked list of vault SearchResult instances.
        """
        results, _timings = self.search_vault_timed(
            raw_query,
            top_k=top_k,
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            intent=intent,
            like_ids=like_ids,
            unlike_ids=unlike_ids,
        )
        return results

    def search_vault_timed(
        self,
        raw_query: str,
        top_k: int = 5,
        *,
        doc_type: str | None = None,
        feature: str | None = None,
        date: str | None = None,
        tag: str | None = None,
        intent: str | None = None,
        like_ids: list[str | int] | None = None,
        unlike_ids: list[str | int] | None = None,
    ) -> tuple[list[SearchResult], dict[str, float]]:
        """Search vault and return phase timings for service diagnostics."""
        timings: dict[str, float] = {}
        phase_started = time.perf_counter()
        parsed, query_text, query_vector, sparse_vector = self._encode_query(
            raw_query,
            surface="vault",
            timings=timings,
        )
        timings["embedding_seconds"] = time.perf_counter() - phase_started
        results = self._search_vault_encoded(
            query_vector,
            sparse_vector,
            parsed,
            query_text,
            top_k,
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            intent=intent,
            like_ids=like_ids,
            unlike_ids=unlike_ids,
            timings=timings,
        )
        return results, timings

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
        like_ids: list[str | int] | None = None,
        unlike_ids: list[str | int] | None = None,
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
            like_ids: Optional list of chunk IDs or point IDs to guide search.
            unlike_ids: Optional list of chunk IDs or point IDs to push search away.

        Returns:
            Ranked list of codebase SearchResult instances.
        """
        results, _timings = self.search_codebase_timed(
            raw_query,
            top_k=top_k,
            language=language,
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            dedup_locales=dedup_locales,
            prefer=prefer,
            like_ids=like_ids,
            unlike_ids=unlike_ids,
        )
        return results

    def search_codebase_timed(
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
        like_ids: list[str | int] | None = None,
        unlike_ids: list[str | int] | None = None,
    ) -> tuple[list[SearchResult], dict[str, float]]:
        """Search codebase and return phase timings for service diagnostics."""
        timings: dict[str, float] = {}
        phase_started = time.perf_counter()
        parsed, query_text, query_vector, sparse_vector = self._encode_query(
            raw_query,
            surface="code",
            timings=timings,
        )
        timings["embedding_seconds"] = time.perf_counter() - phase_started
        results = self._search_codebase_encoded(
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
            like_ids=like_ids,
            unlike_ids=unlike_ids,
            timings=timings,
        )
        return results, timings
