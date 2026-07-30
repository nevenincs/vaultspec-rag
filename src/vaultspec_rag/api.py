"""Public API facade for vaultspec-rag.

Thin wrappers around :class:`ServiceRegistry.lease`.  Every facade
function acquires a refcounted lease on the per-project slot, so the
eviction machinery (idle TTL + LRU cap + busy-slot skip) applies to
direct API consumers as well as MCP tool handlers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from ._source_types import PublicSourceType, parse_source_type
from ._units import bytes_to_mib
from .progress import NullProgressReporter
from .registry import get_registry
from .search._result_shaping import PHASE_MODEL_LOAD, PHASE_PROJECT_LEASE

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

    from .indexer import IndexResult
    from .indexer._codebase_indexer import CodeIndexPreflight, ContentScanResult
    from .indexer._content_policy import RootContentPolicy
    from .indexer._document_indexer import (
        DocumentIndexPreflight,
        DocumentScopedPreflight,
    )
    from .progress import ProgressReporter
    from .search import SearchResult

logger = logging.getLogger(__name__)

__all__ = [
    "AllIndexOptions",
    "AllIndexOutcomes",
    "CodeIndexOptions",
    "CodebaseSearchRequest",
    "DocumentIndexOptions",
    "DomainIndexOutcome",
    "IndexOptions",
    "VaultSearchRequest",
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
    "run_benchmark",
    "run_quality_probe",
    "scan_codebase",
    "scan_codebase_files",
    "search_codebase",
    "search_codebase_timed",
    "search_vault",
    "search_vault_timed",
]


@dataclass(frozen=True, slots=True)
class DomainIndexOutcome:
    """Explicit success or failure for one independently mutable domain."""

    result: IndexResult | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if (self.result is None) == (self.error is None):
            raise ValueError("domain outcome must contain exactly one result or error")

    @property
    def ok(self) -> bool:
        return self.result is not None


@dataclass(frozen=True, slots=True)
class AllIndexOutcomes:
    """Complete, non-collapsing outcome of an all-domain index request."""

    vault: DomainIndexOutcome
    code: DomainIndexOutcome
    document: DomainIndexOutcome


@dataclass(frozen=True, slots=True)
class IndexOptions:
    """Common controls for one indexing operation."""

    full: bool = False
    clean: bool = False
    reporter: ProgressReporter | None = None
    model_name: str | None = None


@dataclass(frozen=True, slots=True)
class CodeIndexOptions(IndexOptions):
    """Controls unique to codebase indexing."""

    extra_excludes: list[str] | None = None


@dataclass(frozen=True, slots=True)
class DocumentIndexOptions(IndexOptions):
    """Controls unique to document indexing."""

    changed_paths: list[pathlib.Path] | None = None
    extra_excludes: list[str] | None = None
    content_policy: RootContentPolicy | None = None


@dataclass(frozen=True, slots=True)
class AllIndexOptions(IndexOptions):
    """Controls shared by every domain in a combined indexing run."""

    extra_excludes: list[str] | None = None
    content_policy: RootContentPolicy | None = None


@dataclass(frozen=True, slots=True)
class VaultSearchRequest:
    """One public vault-search request."""

    root_dir: pathlib.Path
    query: str
    top_k: int = 5
    doc_type: str | None = None
    feature: str | None = None
    date: str | None = None
    tag: str | None = None
    intent: str | None = None
    like_ids: list[str | int] | None = None
    unlike_ids: list[str | int] | None = None


@dataclass(frozen=True, slots=True)
class CodebaseSearchRequest:
    """One public codebase-search request."""

    root_dir: pathlib.Path
    query: str
    top_k: int = 5
    language: str | None = None
    path: str | None = None
    node_type: str | None = None
    function_name: str | None = None
    class_name: str | None = None
    include_paths: list[str] | None = None
    exclude_paths: list[str] | None = None
    dedup_locales: bool | None = None
    prefer: str | None = None
    exclude_domains: list[str] | None = None
    only_domains: list[str] | None = None
    include_domains: list[str] | None = None
    like_ids: list[str | int] | None = None
    unlike_ids: list[str | int] | None = None
    notes: dict[str, object] | None = None


def _resolve(root_dir: pathlib.Path) -> pathlib.Path:
    from pathlib import Path

    return Path(root_dir).resolve()


def _preflight_code_index(
    root: pathlib.Path,
    *,
    extra_excludes: list[str] | None = None,
    sample_limit: int = 100,
) -> CodeIndexPreflight:
    """Resolve policy and discovery without opening storage or loading models.

    ``CodebaseIndexer.__init__`` only stores ``model``/``store`` on
    collaborators that read them lazily during an actual index run;
    construction and ``preflight_content`` never touch either, so ``None``
    is safe here.
    """
    from .indexer import CodebaseIndexer

    indexer = CodebaseIndexer(
        root,
        model=cast("Any", None),
        store=cast("Any", None),
        options=CodebaseIndexer.Options(extra_excludes=extra_excludes),
    )
    return indexer.preflight_content(sample_limit=sample_limit)


def _preflight_document_index(
    root: pathlib.Path,
    *,
    extra_excludes: list[str] | None = None,
    content_policy: RootContentPolicy | None = None,
) -> DocumentIndexPreflight:
    """Resolve document policy and discovery before storage or model loading.

    ``DocumentIndexer.__init__`` only stores ``model``/``store``; both are
    read lazily inside a run, never during construction or
    ``preflight_content``, so ``None`` is safe here.
    """
    from .indexer import DocumentIndexer

    indexer = DocumentIndexer(
        root,
        model=cast("Any", None),
        store=cast("Any", None),
        extra_excludes=extra_excludes,
        content_policy=content_policy,
    )
    return indexer.preflight_content()


def _preflight_document_scope(
    root: pathlib.Path,
    changed_paths: list[pathlib.Path],
    *,
    extra_excludes: list[str] | None = None,
    content_policy: RootContentPolicy | None = None,
) -> DocumentScopedPreflight:
    """Resolve document policy against only the caller-selected paths.

    ``DocumentIndexer.__init__`` only stores ``model``/``store``; both are
    read lazily inside a run, never during construction or
    ``preflight_changed_paths``, so ``None`` is safe here.
    """
    from .indexer import DocumentIndexer

    indexer = DocumentIndexer(
        root,
        model=cast("Any", None),
        store=cast("Any", None),
        extra_excludes=extra_excludes,
        content_policy=content_policy,
    )
    return indexer.preflight_changed_paths(changed_paths)


def index(
    root_dir: pathlib.Path,
    *,
    full: bool = False,
    clean: bool = False,
    reporter: ProgressReporter | None = None,
    model_name: str | None = None,
) -> IndexResult:
    """Index vault documents, returning an :class:`IndexResult`.

    Invalidates the cached :class:`VaultGraph` after indexing so that
    subsequent ``get_related`` calls reflect updated documents.

    Args:
        root_dir: Workspace root directory.
        full: If ``True``, perform a full re-index; otherwise incremental.
        clean: If ``True``, fully replace the collection's contents. The
            replacement happens in place and keeps the previous points
            serving until the rebuild succeeds; only a collection whose
            stored geometry cannot hold the new configuration is recreated.
        reporter: Optional progress reporter. A ``NullProgressReporter``
            is used when omitted so library consumers can call this
            facade without any UI.
        model_name: Optional override for the dense embedding model name.

    Returns:
        An ``IndexResult`` with counts of added, updated, and
        removed documents.
    """
    root = _resolve(root_dir)
    rep = reporter if reporter is not None else NullProgressReporter()
    registry = get_registry()
    result: IndexResult | None = None
    with registry.compute_lease(root, model_name=model_name) as lease:
        runtime = lease.runtime
        result = (
            runtime.vault_indexer.full_index(clean=clean, reporter=rep)
            if (full or clean)
            else runtime.vault_indexer.incremental_index(reporter=rep)
        )
        registry.peek_project(root).graph_cache.invalidate()
    if result is None:
        raise RuntimeError("vault indexing lease ended without a result")
    return result


def index_codebase(
    root_dir: pathlib.Path,
    options: CodeIndexOptions | None = None,
) -> IndexResult:
    """Index codebase source files, returning an :class:`IndexResult`.

    Does **not** invalidate the vault graph cache because code
    changes do not affect vault document relationships.

    Args:
        root_dir: Workspace root directory.
        options: Explicit controls for indexing and exclusions.

    Returns:
        An ``IndexResult`` with counts of added, updated, and
        removed code chunks.
    """
    if options is None:
        options = CodeIndexOptions()
    root = _resolve(root_dir)
    rep = options.reporter if options.reporter is not None else NullProgressReporter()
    preflight = _preflight_code_index(root, extra_excludes=options.extra_excludes)
    registry = get_registry()
    result: IndexResult | None = None
    with registry.compute_lease(root, model_name=options.model_name) as lease:
        runtime = lease.runtime
        if options.full or options.clean:
            result = runtime.code_indexer.full_index(
                clean=options.clean,
                reporter=rep,
                preflight=preflight,
            )
        else:
            result = runtime.code_indexer.incremental_index(
                reporter=rep,
                preflight=preflight,
            )
    if result is None:
        raise RuntimeError("code indexing lease ended without a result")
    return result


def index_documents(
    root_dir: pathlib.Path,
    options: DocumentIndexOptions | None = None,
) -> IndexResult:
    """Index only explicitly routed documents into document storage."""
    if options is None:
        options = DocumentIndexOptions()
    if options.changed_paths is not None and (options.full or options.clean):
        raise ValueError("scoped document indexing cannot be full or clean")
    root = _resolve(root_dir)
    rep = options.reporter if options.reporter is not None else NullProgressReporter()
    preflight = (
        _preflight_document_index(
            root,
            extra_excludes=options.extra_excludes,
            content_policy=options.content_policy,
        )
        if options.changed_paths is None
        else _preflight_document_scope(
            root,
            options.changed_paths,
            extra_excludes=options.extra_excludes,
            content_policy=options.content_policy,
        )
    )
    registry = get_registry()
    result: IndexResult | None = None
    with registry.compute_lease(root, model_name=options.model_name) as lease:
        runtime = lease.runtime
        if options.full or options.clean:
            # The scoped-indexing guard above already raises when
            # ``options.full or options.clean`` and ``changed_paths`` is set,
            # so reaching here means ``preflight`` came from
            # ``_preflight_document_index``, never ``_preflight_document_scope``.
            result = runtime.document_indexer.full_index(
                clean=options.clean,
                reporter=rep,
                preflight=cast("DocumentIndexPreflight", preflight),
            )
        else:
            result = runtime.document_indexer.incremental_index(
                reporter=rep,
                changed_paths=options.changed_paths,
                preflight=preflight,
            )
    if result is None:
        raise RuntimeError("document indexing lease ended without a result")
    return result


def _domain_outcome(operation: Callable[[], IndexResult]) -> DomainIndexOutcome:
    """Run one domain operation while retaining its explicit failure."""
    try:
        return DomainIndexOutcome(result=operation())
    except Exception as exc:
        logger.exception("Index domain failed")
        return DomainIndexOutcome(error=f"{type(exc).__name__}: {exc}")


def index_all(
    root_dir: pathlib.Path,
    options: AllIndexOptions | None = None,
) -> AllIndexOutcomes:
    """Index every domain and return every success or failure independently."""
    if options is None:
        options = AllIndexOptions()
    return AllIndexOutcomes(
        vault=_domain_outcome(
            lambda: index(
                root_dir,
                full=options.full,
                clean=options.clean,
                reporter=options.reporter,
                model_name=options.model_name,
            )
        ),
        code=_domain_outcome(
            lambda: index_codebase(
                root_dir,
                CodeIndexOptions(
                    full=options.full,
                    clean=options.clean,
                    reporter=options.reporter,
                    model_name=options.model_name,
                    extra_excludes=options.extra_excludes,
                ),
            )
        ),
        document=_domain_outcome(
            lambda: index_documents(
                root_dir,
                DocumentIndexOptions(
                    full=options.full,
                    clean=options.clean,
                    reporter=options.reporter,
                    model_name=options.model_name,
                    extra_excludes=options.extra_excludes,
                    content_policy=options.content_policy,
                ),
            )
        ),
    )


def search_vault(request: VaultSearchRequest) -> list[SearchResult]:
    """Search the documentation vault.

    Args:
        request: Query, root, ranking controls, and optional filters.

    Returns:
        Ranked list of SearchResult objects.
    """
    from .search import SearchFilterOptions, validate_search_filters

    validate_search_filters(
        "vault",
        SearchFilterOptions(
            doc_type=request.doc_type,
            feature=request.feature,
            date=request.date,
            tag=request.tag,
        ),
    )
    root = _resolve(request.root_dir)
    registry = get_registry()
    # An empty or unbuilt vault index needs no query encoding: short-circuit
    # to an empty result without loading the GPU model (so an empty search is
    # cheap and works on a CPU-only host).
    if registry.vault_doc_count(root) == 0:
        return []
    results: list[SearchResult] | None = None
    with registry.search_lease(root) as lease:
        results = lease.searcher.search_vault(
            request.query,
            top_k=request.top_k,
            doc_type=request.doc_type,
            feature=request.feature,
            date=request.date,
            tag=request.tag,
            intent=request.intent,
            like_ids=request.like_ids,
            unlike_ids=request.unlike_ids,
        )
    if results is None:
        raise RuntimeError("vault search lease ended without a result")
    return results


def search_vault_timed(
    request: VaultSearchRequest,
) -> tuple[list[SearchResult], dict[str, float]]:
    """Search the vault and return phase timings for service diagnostics."""
    from .search import SearchFilterOptions, validate_search_filters

    validate_search_filters(
        "vault",
        SearchFilterOptions(
            doc_type=request.doc_type,
            feature=request.feature,
            date=request.date,
            tag=request.tag,
        ),
    )
    root = _resolve(request.root_dir)
    registry = get_registry()
    # Empty/unbuilt index: return an empty result without loading the model.
    indexed_count = registry.vault_doc_count(root)
    if indexed_count == 0:
        return [], {
            "indexed_count": indexed_count,
            "model_load_seconds": 0.0,
            "project_lease_seconds": 0.0,
        }
    phase_started = time.perf_counter()
    project_lease_seconds: float | None = None
    results: list[SearchResult] | None = None
    timings: dict[str, float] | None = None
    with registry.search_lease(root) as lease:
        project_lease_seconds = time.perf_counter() - phase_started
        results, timings = lease.searcher.search_vault_timed(
            request.query,
            top_k=request.top_k,
            doc_type=request.doc_type,
            feature=request.feature,
            date=request.date,
            tag=request.tag,
            intent=request.intent,
            like_ids=request.like_ids,
            unlike_ids=request.unlike_ids,
        )
    if results is None or timings is None or project_lease_seconds is None:
        raise RuntimeError("vault search lease ended without a result")
    timings[PHASE_MODEL_LOAD] = 0.0
    timings[PHASE_PROJECT_LEASE] = project_lease_seconds
    timings["indexed_count"] = indexed_count
    return results, timings


def search_codebase(request: CodebaseSearchRequest) -> list[SearchResult]:
    """Search the source codebase.

    Args:
        request: Query, root, ranking controls, and optional filters.

    Returns:
        Ranked list of SearchResult objects.
    """
    from .search import SearchFilterOptions, validate_search_filters

    validate_search_filters(
        "code",
        SearchFilterOptions(
            language=request.language,
            path=request.path,
            node_type=request.node_type,
            function_name=request.function_name,
            class_name=request.class_name,
            include_paths=request.include_paths,
            exclude_paths=request.exclude_paths,
            dedup_locales=request.dedup_locales,
            prefer=request.prefer,
            exclude_domains=request.exclude_domains,
            only_domains=request.only_domains,
            include_domains=request.include_domains,
        ),
    )
    root = _resolve(request.root_dir)
    registry = get_registry()
    # Empty/unbuilt code index: return an empty result without loading the model.
    if registry.code_chunk_count(root) == 0:
        return []
    results: list[SearchResult] | None = None
    with registry.search_lease(root) as lease:
        results = lease.searcher.search_codebase(
            request.query,
            top_k=request.top_k,
            language=request.language,
            path=request.path,
            node_type=request.node_type,
            function_name=request.function_name,
            class_name=request.class_name,
            include_paths=request.include_paths,
            exclude_paths=request.exclude_paths,
            dedup_locales=request.dedup_locales,
            prefer=request.prefer,
            exclude_domains=request.exclude_domains,
            only_domains=request.only_domains,
            include_domains=request.include_domains,
            like_ids=request.like_ids,
            unlike_ids=request.unlike_ids,
        )
    if results is None:
        raise RuntimeError("code search lease ended without a result")
    return results


def _code_breadth_timings(
    root: pathlib.Path,
    indexed_count: int,
) -> dict[str, float]:
    """Return the carried completeness fields for *root*, empty when complete.

    An empty mapping means the collection holds everything its publication
    claimed, or that there is no claim to compare against. The two are
    deliberately indistinguishable to a consumer: neither is a shortfall, and a
    root written by a build that recorded no breadth must not be reported as
    incomplete for want of evidence.
    """
    from ._index_breadth import code_breadth_shortfall, code_file_breadth_shortfall

    carried: dict[str, float] = {}
    shortfall = code_breadth_shortfall(root, indexed_count)
    if shortfall is not None:
        carried["published_points"] = float(shortfall.published)
    file_shortfall = code_file_breadth_shortfall(root)
    if file_shortfall is not None:
        carried["named_files"] = float(file_shortfall.named)
        carried["covered_files"] = float(file_shortfall.covered)
    return carried


def search_codebase_timed(
    request: CodebaseSearchRequest,
) -> tuple[list[SearchResult], dict[str, float]]:
    """Search codebase and return phase timings for service diagnostics."""
    from .search import SearchFilterOptions, validate_search_filters

    validate_search_filters(
        "code",
        SearchFilterOptions(
            language=request.language,
            path=request.path,
            node_type=request.node_type,
            function_name=request.function_name,
            class_name=request.class_name,
            include_paths=request.include_paths,
            exclude_paths=request.exclude_paths,
            dedup_locales=request.dedup_locales,
            prefer=request.prefer,
            exclude_domains=request.exclude_domains,
            only_domains=request.only_domains,
            include_domains=request.include_domains,
        ),
    )
    root = _resolve(request.root_dir)
    registry = get_registry()
    # Empty/unbuilt code index: return an empty result without loading the model.
    indexed_count = registry.code_chunk_count(root)
    # The completeness fact is settled here, once, from the count this path
    # already takes - so it costs no extra store round trip and every adapter
    # reads one conclusion rather than comparing figures for itself.
    breadth = _code_breadth_timings(root, indexed_count)
    if indexed_count == 0:
        return [], {
            "indexed_count": indexed_count,
            "model_load_seconds": 0.0,
            "project_lease_seconds": 0.0,
            **breadth,
        }
    phase_started = time.perf_counter()
    project_lease_seconds: float | None = None
    results: list[SearchResult] | None = None
    timings: dict[str, float] | None = None
    with registry.search_lease(root) as lease:
        project_lease_seconds = time.perf_counter() - phase_started
        results, timings = lease.searcher.search_codebase_timed(
            request.query,
            top_k=request.top_k,
            language=request.language,
            path=request.path,
            node_type=request.node_type,
            function_name=request.function_name,
            class_name=request.class_name,
            include_paths=request.include_paths,
            exclude_paths=request.exclude_paths,
            dedup_locales=request.dedup_locales,
            prefer=request.prefer,
            exclude_domains=request.exclude_domains,
            only_domains=request.only_domains,
            include_domains=request.include_domains,
            like_ids=request.like_ids,
            unlike_ids=request.unlike_ids,
            notes=request.notes,
        )
    if results is None or timings is None or project_lease_seconds is None:
        raise RuntimeError("code search lease ended without a result")
    timings[PHASE_MODEL_LOAD] = 0.0
    timings[PHASE_PROJECT_LEASE] = project_lease_seconds
    timings["indexed_count"] = indexed_count
    timings.update(breadth)
    return results, timings


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
        raw = slot.store.list_all_documents(doc_type=doc_type)
        return cast("list[dict[str, object]]", raw)


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


def clean(
    root_dir: pathlib.Path,
    *,
    clean_type: PublicSourceType
    | Literal[
        "vault", "code", "document", "combined", "all", "codebase", "docs"
    ] = "all",
) -> list[str]:
    """Wipe the selected collections and their index metadata sidecars.

    Does not load embedding models or touch GPUs.

    Args:
        root_dir: Workspace root directory.
        clean_type: Canonical source type or an established compatibility alias.

    Returns:
        List of cleared source labels (e.g. ['vault', 'codebase']).
    """
    source_type = parse_source_type(clean_type, allow_aliases=True)
    root = _resolve(root_dir)
    from ._index_breadth import index_meta_path

    cleared: list[str] = []

    combined = source_type is PublicSourceType.COMBINED
    do_vault = source_type is PublicSourceType.VAULT or combined
    do_code = source_type is PublicSourceType.CODE or combined
    do_document = source_type is PublicSourceType.DOCUMENT or combined

    with get_registry().lease_maintenance_store(root) as store:
        # Sidecars go before collections, and the ordering is load-bearing: a
        # sidecar is a breadth claim, and a crash between the two steps must
        # never leave a claim standing over data that is already gone - a
        # serve-time check would read that as a full index over an empty husk.
        # The safe interruption is the reverse: intact data with no claim, which
        # reads as honestly unverifiable.
        if do_vault:
            index_meta_path(root, PublicSourceType.VAULT).unlink(missing_ok=True)
        if do_code:
            index_meta_path(root, PublicSourceType.CODE).unlink(missing_ok=True)
        if do_document:
            # Documents publish a differently shaped record under an independently
            # chosen name, so it resolves through its own owner rather than here.
            from .indexer._document_meta import document_metadata_path

            document_metadata_path(root).unlink(missing_ok=True)

        if do_vault:
            store.drop_table()
            store.ensure_table()
            cleared.append("vault")
        if do_code:
            store.drop_code_table()
            store.ensure_code_table()
            cleared.append("codebase")
        if do_document:
            store.drop_document_table()
            store.ensure_document_table()
            cleared.append("document")

    return cleared


def get_status(root_dir: pathlib.Path) -> dict[str, object]:
    """Return status of the RAG engine, storage metrics, and GPU info.

    Args:
        root_dir: Workspace root directory.

    Returns:
        Dict containing RAG status information.
    """
    root = _resolve(root_dir)
    torch: Any = None
    try:
        import torch as _torch

        torch = _torch
    except ImportError:
        pass

    cuda_available = torch is not None and torch.cuda.is_available()
    if cuda_available and torch is not None:
        gpu_name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram_mib = int(bytes_to_mib(props.total_memory))
        vram_gb = round(props.total_memory / 1e9, 2)
    else:
        gpu_name = None
        vram_mib = 0
        vram_gb = 0.0

    from .capabilities import backend_capabilities_dict
    from .config._settings import get_config
    from .index_profiles import index_support_profile_status
    from .jobs import index_job_status
    from .registry import get_registry

    registry = get_registry()
    with registry.lease_store(root) as store:
        vault_count = store.count()
        code_count = store.count_code()
        document_count = store.count_document()
        storage_path = str(store.db_path)

    support_profile = index_support_profile_status(get_config().index_support_profile)
    lifecycle = index_job_status(root)

    return {
        "cuda": cuda_available,
        "gpu_name": gpu_name,
        "vram_mib": vram_mib,
        "vram_gb": vram_gb,
        "storage_path": storage_path,
        "vault_documents": vault_count,
        "codebase_chunks": code_count,
        "document_chunks": document_count,
        "vault_count": vault_count,
        "code_count": code_count,
        "document_count": document_count,
        "support_profile": support_profile,
        "generations": lifecycle["sources"],
        "degraded_reasons": lifecycle["degraded_reasons"],
        "target_dir": str(root),
        "backend_capabilities": backend_capabilities_dict(),
    }


def scan_codebase(
    root_dir: pathlib.Path,
    *,
    extra_excludes: list[str] | None = None,
    sample_limit: int = 100,
) -> ContentScanResult:
    """Scan the codebase through the production admission policy.

    The structured result includes the compatibility file projection, bounded
    disposition samples, stable kind/reason counts, and the resolved policy
    fingerprint. It does not require GPU or vector storage.
    """
    root = _resolve(root_dir)
    return _preflight_code_index(
        root,
        extra_excludes=extra_excludes,
        sample_limit=sample_limit,
    ).scan


def scan_codebase_files(
    root_dir: pathlib.Path,
    *,
    extra_excludes: list[str] | None = None,
) -> list[pathlib.Path]:
    """Return the compatible path-list projection of structured admission."""
    return list(
        scan_codebase(
            root_dir,
            extra_excludes=extra_excludes,
            sample_limit=0,
        ).files
    )


def run_benchmark(
    root_dir: pathlib.Path,
    *,
    n_queries: int = 20,
) -> dict[str, Any]:
    """Run search latency benchmarks against the indexed vault.

    Args:
        root_dir: Workspace root directory.
        n_queries: Number of search queries to time.

    Returns:
        Dict containing benchmark results: p50, p95, p99, mean, stdev,
        vault_count, code_count, gpu_name, vram_mib.
    """
    import statistics
    import time

    root = _resolve(root_dir)
    registry = get_registry()
    with registry.lease_store(root) as store:
        vault_count = store.count()
        if vault_count == 0:
            raise ValueError("No vault documents indexed.")

        code_count = store.count_code()

    benchmark: dict[str, object] | None = None
    with registry.search_lease(root) as lease:
        # Warmup
        lease.searcher.search_vault("warmup", top_k=1)

        _bench_queries = [
            "architecture decision",
            "pipeline execution model",
            "connector protocol design",
            "security audit vulnerability",
            "implementation plan phase",
            "type:adr architecture",
            "feature:pipeline-engine execution",
            "scheduler algorithm selection",
            "pipeline executor implementation",
            "dag execution research",
            "data transformation pipeline",
            "worker pool thread",
            "type:plan implementation",
            "semantic search embedding",
            "Qdrant vector store",
            "date:2026-01 decisions",
            "checkpoint storage performance",
            "connector grpc streaming",
            "execution graph dependency",
            "incremental indexing hash",
        ]

        latencies: list[float] = []
        for i in range(n_queries):
            q = _bench_queries[i % len(_bench_queries)]
            t0 = time.perf_counter()
            lease.searcher.search_vault(q, top_k=5)
            latencies.append((time.perf_counter() - t0) * 1000)

        latencies.sort()
        p50 = latencies[n_queries // 2]
        p95 = latencies[int(n_queries * 0.95)]
        p99 = latencies[int(n_queries * 0.99)]
        mean = statistics.mean(latencies)
        stdev = statistics.stdev(latencies) if len(latencies) > 1 else 0.0

        try:
            import torch

            gpu_name = (
                torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A"
            )
            vram_mib = (
                bytes_to_mib(torch.cuda.memory_allocated(0))
                if torch.cuda.is_available()
                else 0.0
            )
        except ImportError:
            gpu_name = "N/A"
            vram_mib = 0.0

        benchmark = {
            "p50": p50,
            "p95": p95,
            "p99": p99,
            "mean": mean,
            "stdev": stdev,
            "vault_count": vault_count,
            "code_count": code_count,
            "gpu": gpu_name,
            "vram_mib": vram_mib,
        }
    if benchmark is None:
        raise RuntimeError("benchmark search lease ended without a result")
    return benchmark


def run_quality_probe(
    *,
    threshold: float = 0.75,
) -> dict[str, Any]:
    """Run search quality probes against a synthetic test corpus.

    Generates a temporary synthetic vault, indexes it, runs
    needle-based precision probes, and returns results.

    Returns:
        Dict containing:
            - "passed": int
            - "total": int
            - "precision": float
            - "threshold": float
            - "probes": list of dicts with {"query": str, "label": str, "passed": bool}
    """
    import tempfile
    from pathlib import Path

    from .progress import NullProgressReporter
    from .synthetic import build_synthetic_vault

    registry = get_registry()
    with tempfile.TemporaryDirectory(prefix="vaultspec-quality-") as tmp:
        root = Path(tmp)
        manifest = build_synthetic_vault(root, n_docs=24, seed=42)
        probes: list[dict[str, object]] = []
        passed = 0
        needles = list(manifest.needles.items())[:8]

        with registry.compute_lease(root) as lease:
            runtime = lease.runtime
            runtime.vault_indexer.full_index(reporter=NullProgressReporter())

            for needle, doc_id in needles:
                results = runtime.searcher.search_vault(needle, top_k=5)
                ok = any(doc_id in r.id for r in results)
                if ok:
                    passed += 1
                probes.append(
                    {
                        "query": needle,
                        "label": f"Needle → {doc_id}",
                        "expected_id": doc_id,
                        "passed": ok,
                    }
                )

        total = len(needles)
        precision = passed / total if total else 0.0

        registry.close_project(root)

        return {
            "passed": passed,
            "total": total,
            "precision": precision,
            "threshold": threshold,
            "probes": probes,
        }


def get_readiness() -> dict[str, Any]:
    """Return a bounded, read-only dependency-readiness snapshot.

    Reports, per external dependency, whether it is provisioned and
    usable - torch CUDA availability, model presence in the Hugging
    Face cache, and the qdrant binary resolution source plus supervised
    server liveness. It is the read-only mirror of the provisioning
    front door: it loads no model, touches no GPU, downloads nothing,
    and mutates nothing, so it is safe to call before the runtime is up.

    Readiness is a process-wide, project-independent concern (the three
    dependencies live outside any one workspace), so this facade takes
    no ``root_dir`` and acquires no project lease.

    Returns:
        The JSON-serialisable :meth:`ReadinessReport.to_dict` view: a
        top-level ``ready`` boolean, ``server_mode``, a ``dependencies``
        list with one ``{name, status, detail, info}`` node per
        dependency, the ``degraded_reasons`` detail strings of the
        non-ready dimensions, the config-derived ``support_profile``,
        and the bounded storage ``schema`` descriptor. Designed to serve
        both a human render and a JSON envelope.
    """
    from ._readiness import compute_readiness

    return compute_readiness().to_dict()


class _WatcherState(TypedDict):
    """The filesystem-watcher section of :func:`get_service_state`."""

    watch_enabled: bool
    debounce_ms: int
    cooldown_s: float
    watching: list[str]
    running: bool


def get_service_state(
    root_dir: pathlib.Path,
    *,
    watching_roots: list[str] | None = None,
) -> dict[str, Any]:
    """Return a consolidated read-only snapshot of the service's state.

    Args:
        root_dir: Workspace root directory.
        watching_roots: Optional list of root paths currently watched.

    Returns:
        Dict containing index, projects, and watcher sections.
    """
    from datetime import datetime

    from ._store_locks import VaultStoreLockedError
    from .config._settings import get_config
    from .registry import get_registry
    from .service import RegistryFullError

    root = _resolve(root_dir)

    try:
        index_data = get_status(root)
    except RegistryFullError as exc:
        index_data = {
            "error": "registry_full",
            "message": str(exc),
            "max_projects": exc.max_projects,
        }
    except VaultStoreLockedError as exc:
        index_data = {
            "error": "store_locked",
            "message": str(exc),
        }
    except Exception as exc:
        index_data = {
            "error": "unknown",
            "message": str(exc),
        }

    registry = get_registry()
    snapshot = registry.snapshot()
    wall_now = datetime.now().astimezone()
    projects: list[dict[str, object]] = []
    for entry in snapshot:
        idle_s = float(entry["idle_seconds"])
        last_access_wall = wall_now.timestamp() - idle_s
        last_access_iso = (
            datetime.fromtimestamp(last_access_wall).astimezone().isoformat()
        )
        projects.append(
            {
                "root": str(entry["root"]),
                "last_access_iso": last_access_iso,
                "idle_seconds": idle_s,
                "ref_count": int(entry["ref_count"]),
            },
        )
    projects_data = {
        "projects": projects,
        "max_projects": registry.max_projects,
        "idle_ttl_seconds": registry.idle_ttl_seconds,
    }

    cfg = get_config()
    watching = watching_roots or []
    watcher_data: _WatcherState = {
        "watch_enabled": bool(cfg.watch_enabled),
        "debounce_ms": int(cfg.watch_debounce_ms),
        "cooldown_s": float(cfg.watch_cooldown_s),
        "watching": watching,
        "running": str(root) in watching,
    }

    from . import store_schema
    from .qdrant_runtime._supervise import runtime_state

    return {
        "index": index_data,
        "projects": projects_data,
        "watcher": watcher_data,
        "qdrant": runtime_state().to_dict(),
        "quiesce": registry.quiesce_snapshot().as_envelope(),
        # Bare storage-schema version echo: lets a consumer polling
        # /service-state for freshness also pre-check the data shape without a
        # separate /readiness round-trip. The full descriptor is on /readiness.
        "schema_version": store_schema.STORAGE_SCHEMA_VERSION,
    }
