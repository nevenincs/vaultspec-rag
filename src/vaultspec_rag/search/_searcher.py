"""The VaultSearcher orchestration class for hybrid search.

Owns the stateful search pipeline: query encoding (Qwen3 dense + SPLADE
sparse), Qdrant hybrid search with RRF fusion, optional CrossEncoder
reranking, and graph-aware score boosts. Holds the GPU lock, the lazily
loaded reranker, and the TTL-cached VaultGraph.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, Protocol, cast

from .. import store_schema
from ._intent_rank import apply_intent_prior, apply_status_filter, apply_type_cap
from ._models import DocumentSearchResult, ParsedQuery, SearchResult
from ._noise import (
    apply_domain_demotion,
    partition_hard_domains,
    resolve_noise_policy,
)
from ._parsing import parse_query
from ._postprocess import (
    GLOB_FETCH_MULTIPLIER,
    _collapse_locale_variants,  # pyright: ignore[reportPrivateUsage]  # intra-package intentional re-export
)
from ._rerank import rerank_with_graph
from ._result_shaping import (
    PHASE_DEDUP,
    PHASE_DEMOTE,
    PHASE_GRAPH_RERANK,
    PHASE_PREFER,
    PHASE_QDRANT,
    PHASE_RERANK,
    PHASE_RESULT_MAPPING,
)
from ._result_shaping import (
    add_seconds as _add_seconds,
)
from ._result_shaping import (
    apply_prefer_nudge as _apply_prefer_nudge_impl,
)
from ._result_shaping import (
    filter_raw_codebase_results as _filter_raw_codebase_results_impl,
)
from ._result_shaping import (
    group_chunks_by_document as _group_chunks_by_document,
)
from ._result_shaping import (
    join_doc_path as _join_doc_path,
)
from ._result_shaping import (
    map_codebase_results as _map_codebase_results_impl,
)
from ._result_shaping import map_document_results as _map_document_results_impl
from ._result_shaping import (
    merge_domain_tokens as _merge_domain_tokens,
)
from ._result_shaping import (
    record_seconds as _record_seconds,
)
from ._result_shaping import select_combined_results as _select_combined_results

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Mapping

    from sentence_transformers import CrossEncoder
    from vaultspec_core.graph import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
        VaultGraph,
    )

    from ..embeddings import EmbeddingModel, SparseResult
    from ..job_control import QuiesceGate
    from ..store import VaultStore
    from ._noise import NoisePolicy

logger = logging.getLogger(__name__)


class _Rerankable(Protocol):
    """Small shared surface consumed by the content reranker."""

    score: float
    snippet: str
    rerank_text: str | None


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
        local_files_only: bool = False,
        quiesce_gate: QuiesceGate | None = None,
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
            local_files_only: Load a lazy reranker from the local Hugging Face
                cache without remote metadata requests. Normal product
                construction remains online-capable by default.
            quiesce_gate: Optional process-global hold gate consulted at
                search admission, before the GPU lock is acquired. When
                paused, new GPU sections park at zero CPU until resumed;
                requests already inside a GPU section are never preempted.
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
        self._quiesce_gate = quiesce_gate
        self._reranker_enabled: bool = cfg.reranker_enabled
        self._reranker_model_name: str = cfg.reranker_model
        self._sparse_enabled: bool = cfg.sparse_enabled
        self._reranker = reranker
        self._local_files_only = local_files_only
        self._reranker_lock = threading.Lock()

    def _vault_docs_prefix(self) -> str:
        """The docs directory (e.g. ``.vault``) vault paths are stored under."""
        from ..config import get_config

        return str(get_config().docs_dir)

    @contextmanager
    def _gpu_section(self, timings: dict[str, float] | None = None):
        # Admission gating: the quiesce wait must complete before the GPU
        # lock is acquired - parking while holding gpu_lock would serialize
        # every tenant behind a paused daemon.
        if self._quiesce_gate is not None:
            self._quiesce_gate.wait()
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
            from sentence_transformers import CrossEncoder

            from .._gpu import load_torch
            from ..config import get_config

            torch = load_torch()
            # Hold the shared GPU lock across the model load. Constructing the
            # CrossEncoder materialises weights on the device, and that CUDA work
            # must not run concurrently with another root's forward pass (or a
            # second searcher's own lazy load) on the one shared GPU - an
            # unserialised load races and crashes the process. The lock is
            # released before the forward pass in ``_rerank`` re-acquires it.
            with self._gpu_section():
                self._reranker = CrossEncoder(
                    self._reranker_model_name,
                    device="cuda",
                    activation_fn=torch.nn.Sigmoid(),
                    max_length=int(get_config().reranker_max_length),
                    local_files_only=self._local_files_only,
                )
            logger.info(
                "CrossEncoder reranker loaded on %s: %s",
                torch.cuda.get_device_name(0),
                self._reranker_model_name,
            )
            return self._reranker

    def _rerank[T: _Rerankable](
        self,
        query: str,
        results: list[T],
        top_k: int,
        *,
        timings: dict[str, float] | None = None,
    ) -> list[T]:
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
        internal lock+TTL cache for the fallback path.

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
        # Accept the alternate spelling ``debug`` as an alias for the canonical
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
            if k in store_schema.VAULT_FILTER_KEYS
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
        _record_seconds(timings, PHASE_QDRANT, phase_started)

        # Auto-generated feature-index documents are navigational document-lists
        # with no semantic content; they are never searchable and are
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
                [str(x) for x in cast("list[object]", related_raw)]
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
        _record_seconds(timings, PHASE_RESULT_MAPPING, phase_started)

        # Rerank the FULL fetched candidate set: grouping below can
        # collapse several chunks of one document into a single row, so
        # truncating before grouping could under-fill the final page
        # whenever one document's chunks dominate the rerank window.
        phase_started = time.perf_counter()
        results = self._rerank(query_text, results, len(results), timings=timings)
        _record_seconds(timings, PHASE_RERANK, phase_started)

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
        _record_seconds(timings, PHASE_GRAPH_RERANK, phase_started)
        if timings is not None:
            timings["postprocess_seconds"] = (
                timings.get(PHASE_RESULT_MAPPING, 0.0)
                + timings.get(PHASE_RERANK, 0.0)
                + timings.get(PHASE_GRAPH_RERANK, 0.0)
            )
        return results[:top_k]

    @staticmethod
    def _build_codebase_store_filters(
        parsed: ParsedQuery,
        language: str | None,
        path: str | None,
        node_type: str | None,
        function_name: str | None,
        class_name: str | None,
    ) -> dict[str, str]:
        # No inline marker maps to ``path``: an in-query ``path:`` token is a
        # pattern and joins the include patterns instead, so the exact-path
        # filter arrives only as an explicit argument.
        store_filters = {
            k: v
            for k, v in parsed.filters.items()
            if k in ("language", "node_type", "function_name", "class_name")
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

    def _fetch_codebase_candidates(
        self,
        *,
        query_vector: list[float],
        sparse_vector: SparseResult | None,
        query_text: str,
        store_filters: dict[str, str],
        top_k: int,
        include_norm: list[str],
        exclude_norm: list[str],
        policy: NoisePolicy,
        like_ids: list[str | int] | None,
        unlike_ids: list[str | int] | None,
        timings: dict[str, float] | None,
        notes: dict[str, object] | None,
    ) -> tuple[list[dict[str, object]], dict[str, int]]:
        """Fetch and hard-filter raw candidates, backfilling to fill ``top_k``.

        Domain hide/only constraints push down to Qdrant; the glob filter and
        the domain fallback (for chunks lacking a stored ``domain``) run
        post-query. Because post-query pruning can drop the page below
        ``top_k``, the fetch widens its window and re-queries until it can
        satisfy ``top_k``, the index is exhausted, or a hard cap is reached -
        never returning a silently depleted page when more candidates exist.
        Returns the surviving raw results and a per-domain drop count.

        When the include patterns turn out to be what emptied the page, that is
        recorded in ``notes`` so the caller can say so. An empty page is
        otherwise indistinguishable from a query that matched nothing, and a
        path pattern that matches no indexed path is the likelier mistake.
        """
        has_glob = bool(include_norm or exclude_norm)
        # Domain hide/only constraints are already pushed into Qdrant. Start
        # them at the ordinary rerank window and widen only when the legacy
        # missing-domain fallback actually depletes the survivors. Path globs
        # still run entirely in Python, so they retain the wider initial
        # window that protects the common post-filter case.
        if has_glob:
            base = max(top_k * GLOB_FETCH_MULTIPLIER, 50)
        else:
            base = max(top_k * 4, 20) if self._reranker_enabled else top_k * 2
        cap = max(base * 4, 500)
        pushdown_exclude = sorted(policy.hide) or None
        pushdown_only = sorted(policy.only) or None

        started = time.perf_counter()
        limit = base
        raw: list[dict[str, object]] = []
        globbed: list[dict[str, object]] = []
        kept: list[dict[str, object]] = []
        dropped: dict[str, int] = {}
        while True:
            raw = cast(
                "list[dict[str, object]]",
                self.store.hybrid_search_codebase(
                    query_vector=query_vector,
                    _query_text=query_text,
                    filters=store_filters or None,
                    limit=limit,
                    sparse_vector=sparse_vector,
                    like_ids=like_ids,
                    unlike_ids=unlike_ids,
                    exclude_domains=pushdown_exclude,
                    only_domains=pushdown_only,
                ),
            )
            globbed = _filter_raw_codebase_results_impl(raw, include_norm, exclude_norm)
            kept, dropped = partition_hard_domains(globbed, policy)
            # Stop when the page is fillable, the index is exhausted for this
            # query (fewer raw rows than asked), or we hit the cap.
            if len(kept) >= top_k or len(raw) < limit or limit >= cap:
                break
            limit = min(limit * 2, cap)
        _record_seconds(timings, PHASE_QDRANT, started)
        if notes is not None and include_norm and raw and not globbed:
            notes["path_filter"] = {
                "patterns": list(include_norm),
                "candidates_before_filter": len(raw),
            }
        if dropped:
            logger.info("code search dropped noise-domain candidates: %s", dropped)
        return kept, dropped

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
        dedup_locales: bool | None = None,
        prefer: str | None = None,
        exclude_domains: list[str] | None = None,
        only_domains: list[str] | None = None,
        include_domains: list[str] | None = None,
        like_ids: list[str | int] | None = None,
        unlike_ids: list[str | int] | None = None,
        notes: dict[str, object] | None = None,
        timings: dict[str, float] | None = None,
    ) -> list[SearchResult]:
        """Search codebase using pre-encoded dense and sparse vectors.

        Runs hybrid search against the codebase collection with the noise
        policy applied (hide/only as Qdrant pushdown plus a post-query
        fallback, demote as a post-rerank score penalty), then CrossEncoder
        reranking and the opt-in prefer/dedup passes.

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
                project-relative path.
            exclude_paths: Optional fnmatch glob list; a result is
                dropped when any pattern matches its path.
            dedup_locales: Tri-state. ``None`` resolves to the
                ``dedup_locales_default`` config knob; ``True`` / ``False``
                force the locale-collapse pass on or off.
            prefer: ``"prod"`` / ``"tests"`` / ``"docs"`` score nudge.
            exclude_domains: Noise domains to hard-drop for this call (adds
                to the profile hide set).
            only_domains: When set, keep only results in these domains.
            include_domains: Domains to re-admit, overriding the profile's
                hide/demote of them for this call.
            like_ids: Chunk/point IDs to steer search toward.
            unlike_ids: Chunk/point IDs to steer search away from.
            notes: Optional mutable mapping the search annotates with
                ``dropped_domains`` (per-domain drop counts) so a caller can
                surface what the noise filter removed.

        Returns:
            Ranked list of codebase SearchResult instances.
        """
        from ..config import get_config

        cfg = get_config()
        # Domain filters arrive either as explicit kwargs (api / MCP) or as
        # inline query tokens (exclude:/only:/include:, the CLI + HTTP path that
        # avoids the command's max-args ratchet); merge both before resolving.
        policy = resolve_noise_policy(
            cfg,
            exclude_domains=_merge_domain_tokens(
                parsed, "exclude_domain", exclude_domains
            ),
            only_domains=_merge_domain_tokens(parsed, "only_domain", only_domains),
            include_domains=_merge_domain_tokens(
                parsed, "include_domain", include_domains
            ),
        )
        effective_dedup = (
            bool(cfg.dedup_locales_default) if dedup_locales is None else dedup_locales
        )

        store_filters = self._build_codebase_store_filters(
            parsed, language, path, node_type, function_name, class_name
        )
        # Normalise caller patterns once. The codebase indexer stores POSIX
        # paths on every platform, so glob matching is consistent when caller
        # patterns carry the same convention. An inline ``path:`` token is one
        # more include pattern, matching how repeated patterns already union.
        inline_scope = parsed.filters.get("path_scope")
        include_norm = [
            p.replace("\\", "/")
            for p in [
                *(include_paths or []),
                *([inline_scope] if inline_scope else []),
            ]
        ]
        exclude_norm = (
            [p.replace("\\", "/") for p in exclude_paths] if exclude_paths else []
        )

        raw_results, dropped = self._fetch_codebase_candidates(
            query_vector=query_vector,
            sparse_vector=sparse_vector,
            query_text=query_text,
            store_filters=store_filters,
            top_k=top_k,
            include_norm=include_norm,
            exclude_norm=exclude_norm,
            policy=policy,
            like_ids=like_ids,
            unlike_ids=unlike_ids,
            timings=timings,
            notes=notes,
        )
        if notes is not None and dropped:
            notes["dropped_domains"] = dropped

        phase_started = time.perf_counter()
        results = _map_codebase_results_impl(raw_results)
        _record_seconds(timings, PHASE_RESULT_MAPPING, phase_started)

        # Rerank the FULL surviving window (not a top_k slice) so the
        # post-rerank demote pass can lift a production result above noise
        # that initially out-scored it; truncation happens at return.
        phase_started = time.perf_counter()
        results = self._rerank(query_text, results, len(results), timings=timings)
        _record_seconds(timings, PHASE_RERANK, phase_started)

        # Noise demote: subtract the penalty from demoted-domain results and
        # re-sort. Runs after rerank so query-relevance is scored first.
        phase_started = time.perf_counter()
        apply_domain_demotion(results, policy)
        _record_seconds(timings, PHASE_DEMOTE, phase_started)

        # --prefer post-rerank score nudge (opt-in, layered over demote).
        phase_started = time.perf_counter()
        _apply_prefer_nudge_impl(results, prefer)
        _record_seconds(timings, PHASE_PREFER, phase_started)

        # Locale-variant collapse (default on via config; tri-state override).
        phase_started = time.perf_counter()
        if effective_dedup:
            results = _collapse_locale_variants(results)
        _record_seconds(timings, PHASE_DEDUP, phase_started)
        if timings is not None:
            timings["postprocess_seconds"] = (
                timings.get(PHASE_RESULT_MAPPING, 0.0)
                + timings.get(PHASE_RERANK, 0.0)
                + timings.get(PHASE_DEMOTE, 0.0)
                + timings.get(PHASE_PREFER, 0.0)
                + timings.get(PHASE_DEDUP, 0.0)
            )

        return results[:top_k]

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
        dedup_locales: bool | None = None,
        prefer: str | None = None,
        exclude_domains: list[str] | None = None,
        only_domains: list[str] | None = None,
        include_domains: list[str] | None = None,
        like_ids: list[str | int] | None = None,
        unlike_ids: list[str | int] | None = None,
        notes: dict[str, object] | None = None,
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
            dedup_locales: Tri-state locale-collapse override; ``None``
                resolves to the ``dedup_locales_default`` config knob.
            prefer: Optional ``"prod" | "tests" | "docs"`` -
                applies a small +/- score nudge to the matching
                category after rerank. Opt-in.
            exclude_domains: Noise domains to hard-drop for this call.
            only_domains: Restrict results to these domains.
            include_domains: Re-admit domains the profile hides/demotes.
            like_ids: Optional list of chunk IDs or point IDs to guide search.
            unlike_ids: Optional list of chunk IDs or point IDs to push search away.
            notes: Optional mutable mapping annotated with ``dropped_domains``.

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
            exclude_domains=exclude_domains,
            only_domains=only_domains,
            include_domains=include_domains,
            like_ids=like_ids,
            unlike_ids=unlike_ids,
            notes=notes,
        )
        return results

    def search_document(
        self,
        raw_query: str,
        top_k: int = 5,
        *,
        source_path: str | None = None,
        extractor_id: str | None = None,
        extractor_version: str | None = None,
        locator_kind: str | None = None,
    ) -> list[DocumentSearchResult]:
        """Search only the independent document collection."""
        results, _timings = self.search_document_timed(
            raw_query,
            top_k=top_k,
            source_path=source_path,
            extractor_id=extractor_id,
            extractor_version=extractor_version,
            locator_kind=locator_kind,
        )
        return results

    def _search_document_encoded(
        self,
        query_vector: list[float],
        sparse_vector: SparseResult | None,
        parsed: ParsedQuery,
        query_text: str,
        top_k: int,
        *,
        source_path: str | None = None,
        extractor_id: str | None = None,
        extractor_version: str | None = None,
        locator_kind: str | None = None,
        timings: dict[str, float] | None = None,
    ) -> list[DocumentSearchResult]:
        """Search documents from one already encoded query."""
        filters = {
            key: value
            for key, value in parsed.filters.items()
            if key in store_schema.DOCUMENT_QUERY_FILTER_KEYS
        }
        for key, value in (
            ("source_path", source_path),
            ("extractor_id", extractor_id),
            ("extractor_version", extractor_version),
            ("locator_kind", locator_kind),
        ):
            if value is not None:
                filters[key] = value

        phase_started = time.perf_counter()
        fetch_limit = max(top_k * 4, 20) if self._reranker_enabled else top_k * 2
        raw_results = cast(
            "list[dict[str, object]]",
            self.store.hybrid_search_document(
                query_vector=query_vector,
                _query_text=query_text,
                filters=filters or None,
                limit=fetch_limit,
                sparse_vector=sparse_vector,
            ),
        )
        _record_seconds(timings, PHASE_QDRANT, phase_started)

        phase_started = time.perf_counter()
        results = _map_document_results_impl(raw_results)
        _record_seconds(timings, PHASE_RESULT_MAPPING, phase_started)
        phase_started = time.perf_counter()
        results = self._rerank(query_text, results, top_k, timings=timings)
        _record_seconds(timings, PHASE_RERANK, phase_started)
        if timings is not None:
            timings["postprocess_seconds"] = timings.get(
                PHASE_RESULT_MAPPING, 0.0
            ) + timings.get(PHASE_RERANK, 0.0)
        return results

    def search_document_timed(
        self,
        raw_query: str,
        top_k: int = 5,
        *,
        source_path: str | None = None,
        extractor_id: str | None = None,
        extractor_version: str | None = None,
        locator_kind: str | None = None,
    ) -> tuple[list[DocumentSearchResult], dict[str, float]]:
        """Search documents and return phase timings for diagnostics."""
        timings: dict[str, float] = {}
        phase_started = time.perf_counter()
        parsed, query_text, query_vector, sparse_vector = self._encode_query(
            raw_query,
            surface="document",
            timings=timings,
        )
        timings["embedding_seconds"] = time.perf_counter() - phase_started
        results = self._search_document_encoded(
            query_vector,
            sparse_vector,
            parsed,
            query_text,
            top_k,
            source_path=source_path,
            extractor_id=extractor_id,
            extractor_version=extractor_version,
            locator_kind=locator_kind,
            timings=timings,
        )
        return results, timings

    def search_combined(
        self,
        raw_query: str,
        top_k: int = 5,
        *,
        doc_type: str | None = None,
        feature: str | None = None,
        date: str | None = None,
        tag: str | None = None,
        intent: str | None = None,
        language: str | None = None,
        path: str | None = None,
        node_type: str | None = None,
        function_name: str | None = None,
        class_name: str | None = None,
        include_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        dedup_locales: bool | None = None,
        prefer: str | None = None,
        exclude_domains: list[str] | None = None,
        only_domains: list[str] | None = None,
        include_domains: list[str] | None = None,
        source_path: str | None = None,
        extractor_id: str | None = None,
        extractor_version: str | None = None,
        locator_kind: str | None = None,
    ) -> list[SearchResult | DocumentSearchResult]:
        """Search all three domains with explicit equal candidate allocation."""
        results, _timings = self.search_combined_timed(
            raw_query,
            top_k=top_k,
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            intent=intent,
            language=language,
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            dedup_locales=dedup_locales,
            prefer=prefer,
            exclude_domains=exclude_domains,
            only_domains=only_domains,
            include_domains=include_domains,
            source_path=source_path,
            extractor_id=extractor_id,
            extractor_version=extractor_version,
            locator_kind=locator_kind,
        )
        return results

    def search_combined_timed(
        self,
        raw_query: str,
        top_k: int = 5,
        *,
        doc_type: str | None = None,
        feature: str | None = None,
        date: str | None = None,
        tag: str | None = None,
        intent: str | None = None,
        language: str | None = None,
        path: str | None = None,
        node_type: str | None = None,
        function_name: str | None = None,
        class_name: str | None = None,
        include_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        dedup_locales: bool | None = None,
        prefer: str | None = None,
        exclude_domains: list[str] | None = None,
        only_domains: list[str] | None = None,
        include_domains: list[str] | None = None,
        source_path: str | None = None,
        extractor_id: str | None = None,
        extractor_version: str | None = None,
        locator_kind: str | None = None,
    ) -> tuple[list[SearchResult | DocumentSearchResult], dict[str, float]]:
        """Search all domains from one encoding and deterministically select top-k."""
        timings: dict[str, float] = {}
        phase_started = time.perf_counter()
        parsed, query_text, query_vector, sparse_vector = self._encode_query(
            raw_query,
            surface=None,
            timings=timings,
        )
        timings["embedding_seconds"] = time.perf_counter() - phase_started

        allocation = max(1, top_k)
        vault_timings: dict[str, float] = {}
        code_timings: dict[str, float] = {}
        document_timings: dict[str, float] = {}
        vault = self._search_vault_encoded(
            query_vector,
            sparse_vector,
            parsed,
            query_text,
            allocation,
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            intent=intent,
            timings=vault_timings,
        )
        code = self._search_codebase_encoded(
            query_vector,
            sparse_vector,
            parsed,
            query_text,
            allocation,
            language=language,
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            dedup_locales=dedup_locales,
            prefer=prefer,
            exclude_domains=exclude_domains,
            only_domains=only_domains,
            include_domains=include_domains,
            timings=code_timings,
        )
        documents = self._search_document_encoded(
            query_vector,
            sparse_vector,
            parsed,
            query_text,
            allocation,
            source_path=source_path,
            extractor_id=extractor_id,
            extractor_version=extractor_version,
            locator_kind=locator_kind,
            timings=document_timings,
        )
        candidates: list[SearchResult | DocumentSearchResult] = [
            *vault,
            *code,
            *documents,
        ]
        phase_started = time.perf_counter()
        candidates = self._rerank(
            query_text,
            candidates,
            len(candidates),
            timings=timings,
        )
        selected = _select_combined_results(candidates, top_k)
        timings["combined_selection_seconds"] = time.perf_counter() - phase_started
        for domain, values in (
            ("vault", vault_timings),
            ("code", code_timings),
            ("document", document_timings),
        ):
            for key, value in values.items():
                timings[f"{domain}_{key}"] = value
        timings["candidate_allocation_per_domain"] = float(allocation)
        return selected, timings

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
        dedup_locales: bool | None = None,
        prefer: str | None = None,
        exclude_domains: list[str] | None = None,
        only_domains: list[str] | None = None,
        include_domains: list[str] | None = None,
        like_ids: list[str | int] | None = None,
        unlike_ids: list[str | int] | None = None,
        notes: dict[str, object] | None = None,
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
            exclude_domains=exclude_domains,
            only_domains=only_domains,
            include_domains=include_domains,
            like_ids=like_ids,
            unlike_ids=unlike_ids,
            notes=notes,
            timings=timings,
        )
        return results, timings
