"""Document and combined public-search facades over registry leases."""

from __future__ import annotations

import pathlib
from dataclasses import asdict, dataclass, field, replace
from typing import TYPE_CHECKING

from ._index_integrity import IntegrityVerdict
from ._publication_state import (
    IndexTransitionError,
    capture_source_read_fence,
    read_current_epoch,
)
from ._search_state import BreadthFindings, search_index_state
from ._source_types import PublicSourceType
from .registry import get_registry
from .search import InvalidFilterForSearchTypeError, validate_search_filters
from .search._outcomes import CombinedSearchOutcome, SearchDomainOutcome
from .server._search_availability import (
    CanonicalSearchEvidence,
    SearchAvailabilityContext,
    classify_search_response,
    storage_refusal_fact,
)
from .store_runtime import StorageGeometryError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ._index_integrity import IndexIntegrity
    from ._publication_state import SourceReadFence
    from ._search_state import SearchSourceFact
    from .search import DocumentSearchResult, SearchFilterOptions
    from .search._outcomes import AnySearchResult
    from .search._searcher import VaultSearcher
    from .service import ServiceRegistry

__all__ = [
    "CodeCombinedSearchFilters",
    "CombinedSearchRequest",
    "DocumentCombinedSearchFilters",
    "DocumentSearchRequest",
    "VaultCombinedSearchFilters",
    "search_combined",
    "search_combined_timed",
    "search_documents",
    "search_documents_timed",
]


@dataclass(frozen=True, slots=True)
class VaultCombinedSearchFilters:
    """Vault-owned filters for a combined search request."""

    doc_type: str | None = None
    feature: str | None = None
    date: str | None = None
    tag: str | None = None
    intent: str | None = None


@dataclass(frozen=True, slots=True)
class CodeCombinedSearchFilters:
    """Code-owned filters for a combined search request."""

    language: str | None = None
    path: str | None = None
    node_type: str | None = None
    function_name: str | None = None
    class_name: str | None = None
    include_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()
    dedup_locales: bool | None = None
    prefer: str | None = None
    exclude_domains: tuple[str, ...] = ()
    only_domains: tuple[str, ...] = ()
    include_domains: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentCombinedSearchFilters:
    """Document-owned filters for a combined search request."""

    source_path: str | None = None
    extractor_id: str | None = None
    extractor_version: str | None = None
    locator_kind: str | None = None
    extractor_prefix: str | None = None
    metadata_filters: Mapping[str, Sequence[str]] | None = None


@dataclass(frozen=True, slots=True)
class DocumentSearchRequest:
    """One document-only search operation and its owned filters."""

    root_dir: pathlib.Path
    query: str
    top_k: int = 5
    source_path: str | None = None
    extractor_id: str | None = None
    extractor_version: str | None = None
    locator_kind: str | None = None
    extractor_prefix: str | None = None
    metadata_filters: Mapping[str, Sequence[str]] | None = None


@dataclass(frozen=True, slots=True)
class CombinedSearchRequest:
    """One combined search operation and its domain-owned filters."""

    root_dir: pathlib.Path
    query: str
    top_k: int = 5
    vault_filters: VaultCombinedSearchFilters = field(
        default_factory=VaultCombinedSearchFilters
    )
    code_filters: CodeCombinedSearchFilters = field(
        default_factory=CodeCombinedSearchFilters
    )
    document_filters: DocumentCombinedSearchFilters = field(
        default_factory=DocumentCombinedSearchFilters
    )
    include_documents: bool = True

    def __post_init__(self) -> None:
        from .search._parsing import parse_query

        if self.include_documents:
            return
        if (
            self.vault_filters.doc_type is None
            and "doc_type" not in parse_query(self.query).filters
        ):
            object.__setattr__(
                self, "vault_filters", replace(self.vault_filters, doc_type="adr")
            )


def search_documents(
    request: DocumentSearchRequest,
) -> list[DocumentSearchResult]:
    """Search only the independently owned document collection."""
    results, _timings = search_documents_timed(request)
    return results


def search_documents_timed(
    request: DocumentSearchRequest,
    *,
    registry: ServiceRegistry | None = None,
) -> tuple[list[DocumentSearchResult], dict[str, float]]:
    """Search documents and return canonical service timing fields."""
    from .search import SearchFilterOptions

    validate_search_filters(
        PublicSourceType.DOCUMENT,
        SearchFilterOptions(
            source_path=request.source_path,
            extractor_id=request.extractor_id,
            extractor_version=request.extractor_version,
            locator_kind=request.locator_kind,
            extractor_prefix=request.extractor_prefix,
            metadata_filters=request.metadata_filters,
        ),
    )
    root = pathlib.Path(request.root_dir).resolve()
    _refuse_document_filters(root, request.query, request)
    active_registry = registry if registry is not None else get_registry()
    return read_current_epoch(
        root,
        PublicSourceType.DOCUMENT,
        lambda: _search_document_storage(request, root, active_registry),
    )


def _search_document_storage(
    request: DocumentSearchRequest,
    root: pathlib.Path,
    active_registry: ServiceRegistry,
) -> tuple[list[DocumentSearchResult], dict[str, float]]:
    """Count and search the document collection as it stands now."""
    indexed_count = active_registry.document_chunk_count(root)
    if indexed_count == 0:
        return [], {"indexed_count": 0.0}
    results: list[DocumentSearchResult] | None = None
    timings: dict[str, float] | None = None
    with active_registry.search_lease(root) as lease:
        results, timings = lease.searcher.search_document_timed(
            request.query,
            top_k=request.top_k,
            source_path=request.source_path,
            extractor_id=request.extractor_id,
            extractor_version=request.extractor_version,
            locator_kind=request.locator_kind,
            extractor_prefix=request.extractor_prefix,
            metadata_filters=request.metadata_filters,
        )
    if results is None or timings is None:
        raise RuntimeError("document search lease ended without a result")
    timings["indexed_count"] = float(indexed_count)
    return results, timings


def _refuse_document_filters(
    root: pathlib.Path,
    query: str,
    filters: DocumentSearchRequest | DocumentCombinedSearchFilters,
) -> None:
    """Refuse document filters the root cannot apply, before any count.

    The answer must not depend on whether the collection holds points: an
    undeclared key is refused on an empty index exactly as on a full one.
    """
    from .indexer._preprocess_config import load_filterable_metadata
    from .search._parsing import parse_query
    from .search._validation import DocumentFilterRequest, validate_document_filters

    validate_document_filters(
        DocumentFilterRequest(
            source_path=filters.source_path,
            extractor_id=filters.extractor_id,
            extractor_version=filters.extractor_version,
            locator_kind=filters.locator_kind,
            extractor_prefix=filters.extractor_prefix,
            metadata_filters=filters.metadata_filters,
            inline=parse_query(query).filters,
        ),
        load_filterable_metadata(root),
    )


@dataclass(frozen=True, slots=True)
class _DomainSearch:
    """A concrete operation bound to its actual source and requested root."""

    source: PublicSourceType
    root: pathlib.Path
    operation: Callable[[], Sequence[AnySearchResult]]


def _domain_failure(
    source: PublicSourceType,
    root: pathlib.Path,
    exc: Exception,
    source_fact: SearchSourceFact,
    job_snapshot: Sequence[object],
) -> SearchDomainOutcome:
    """Retain the exception and project typed compatibility or reset refusals.

    *job_snapshot* decides whether an unfinished reset still has a live owner;
    other failures ignore it.
    """
    refused_fact = (
        storage_refusal_fact(exc, source_fact, root=root, job_snapshot=job_snapshot)
        if isinstance(exc, (StorageGeometryError, IndexTransitionError))
        else None
    )
    return SearchDomainOutcome.failure(
        source,
        refused_fact.reason_code.value
        if refused_fact is not None and refused_fact.reason_code is not None
        else type(exc).__name__,
        str(exc) or type(exc).__name__,
        source_fact=refused_fact or source_fact,
    )


def _search_domain(
    request: _DomainSearch,
    source_fact: SearchSourceFact,
) -> SearchDomainOutcome:
    try:
        return SearchDomainOutcome.success(
            request.source, list(request.operation()), source_fact=source_fact
        )
    except InvalidFilterForSearchTypeError:
        # A refused filter is the caller's error, not one domain failing: the
        # whole request is refused rather than answered without that domain.
        raise
    except Exception as exc:
        # Retrieval runs after the reset fence was captured and holds none of
        # its own, so no failure here is an unfinished reset needing job state.
        return _domain_failure(request.source, request.root, exc, source_fact, ())


def _combined_source_fact(
    root: pathlib.Path,
    source: PublicSourceType,
    registry: ServiceRegistry,
    *,
    observation: IndexIntegrity | None,
    job_snapshot: list[dict[str, object]],
) -> SearchSourceFact:
    """Project one domain through the canonical availability authority."""
    from .server._search_readiness import ReadinessRegistryClosedError

    if source is PublicSourceType.COMBINED:
        raise ValueError("combined readiness requires one concrete source")
    concrete_source = source.value

    try:
        readiness = registry.readiness_registry
    except RuntimeError as exc:
        if str(exc) != "readiness registry is not started":
            raise
        snapshot = None
    else:
        try:
            snapshot = readiness.snapshot(root, concrete_source)
        except ReadinessRegistryClosedError:
            snapshot = None
    target = snapshot.publication_target() if snapshot is not None else None
    evidence = CanonicalSearchEvidence(
        served_generation=(
            snapshot.published_generation if snapshot is not None else None
        ),
        observed_generation=(
            snapshot.observed_generation if snapshot is not None else None
        ),
        desired_generation=(target.generation if target is not None else None),
        publication_revision=(
            snapshot.publication_revision if snapshot is not None else None
        ),
        desired_revision=(target.revision if target is not None else None),
        collection_present=True if observation is not None else None,
        target_matches=True,
        integrity_verified=observation is not None
        and observation.verdict is IntegrityVerdict.CONSISTENT
        and snapshot is not None
        and snapshot.published_generation is not None
        and observation.generation_id == snapshot.published_generation,
    )
    classification = classify_search_response(
        {},
        SearchAvailabilityContext(
            before_snapshot=job_snapshot,
            after_snapshot=job_snapshot,
            requested_root=root,
            source=concrete_source,
            request_id="combined-search",
            index_state=search_index_state(
                indexed_count=observation.live_count or 0
                if observation is not None
                else 0,
                requested_root=root,
                search_type=source,
                findings=BreadthFindings(integrity=observation),
            ),
            port=None,
            canonical_evidence=evidence,
        ),
    )
    return classification.source_fact


def _count_combined_domains(
    root: pathlib.Path,
    registry: ServiceRegistry,
    *,
    include_documents: bool,
) -> tuple[
    dict[PublicSourceType, int],
    dict[PublicSourceType, SearchDomainOutcome],
    dict[PublicSourceType, SearchSourceFact],
    dict[str, float],
    dict[PublicSourceType, SourceReadFence],
]:
    """Count each domain independently and retain model-free failures.

    Each domain's reset epoch is captured before its count, so the count and
    the later search of that domain are validated against one epoch.
    """
    operations = {
        PublicSourceType.VAULT: lambda: registry.vault_doc_count(root),
        PublicSourceType.CODE: lambda: registry.code_chunk_count(root),
        PublicSourceType.DOCUMENT: lambda: registry.document_chunk_count(root),
    }
    counts: dict[PublicSourceType, int] = {}
    failures: dict[PublicSourceType, SearchDomainOutcome] = {}
    facts: dict[PublicSourceType, SearchSourceFact] = {}
    timings: dict[str, float] = {}
    fences: dict[PublicSourceType, SourceReadFence] = {}
    from ._index_integrity import acquire_index_integrity_snapshot_if_proven
    from .server._routes import canonical_job_snapshot

    jobs = canonical_job_snapshot()
    for source, operation in operations.items():
        if source is PublicSourceType.DOCUMENT and not include_documents:
            continue
        try:
            fences[source] = capture_source_read_fence(root, source)
            integrity_snapshot = acquire_index_integrity_snapshot_if_proven(
                root, source
            )
            count = operation()
            integrity = integrity_snapshot.finish(count)
        except Exception as exc:
            source_fact = _combined_source_fact(
                root,
                source,
                registry,
                observation=None,
                job_snapshot=jobs,
            )
            failures[source] = _domain_failure(source, root, exc, source_fact, jobs)
            facts[source] = failures[source].source_fact
        else:
            counts[source] = count
            facts[source] = _combined_source_fact(
                root,
                source,
                registry,
                observation=integrity,
                job_snapshot=jobs,
            )
            timings[f"{source.value}_indexed_count"] = float(count)
    return counts, failures, facts, timings, fences


def _validated_epoch(
    outcome: SearchDomainOutcome,
    fences: dict[PublicSourceType, SourceReadFence],
    root: pathlib.Path,
) -> SearchDomainOutcome:
    """Refuse one domain's answer when a reset began after its count.

    A domain that already failed keeps its own failure; a fenced domain loses
    its results to a typed retryable transition instead of returning content
    read across the reset.
    """
    fence = fences.get(outcome.source)
    if fence is None or not outcome.ok:
        return outcome
    try:
        fence.validate()
    except IndexTransitionError as exc:
        # Validation only ever reports a reset that began after capture, which
        # is running now; no job state changes that answer.
        return _domain_failure(outcome.source, root, exc, outcome.source_fact, ())
    return outcome


def _empty_or_failed_combined_outcome(
    failures: dict[PublicSourceType, SearchDomainOutcome],
    facts: dict[PublicSourceType, SearchSourceFact],
    top_k: int,
) -> CombinedSearchOutcome:
    """Build the no-positive-count outcome without erasing count failures."""

    def outcome(source: PublicSourceType) -> SearchDomainOutcome:
        return failures.get(source) or SearchDomainOutcome.success(
            source, [], source_fact=facts[source]
        )

    return CombinedSearchOutcome(
        outcome(PublicSourceType.VAULT),
        outcome(PublicSourceType.CODE),
        outcome(PublicSourceType.DOCUMENT)
        if PublicSourceType.DOCUMENT in facts
        else None,
        top_k,
    )


def _indexed_domain_outcome(
    request: _DomainSearch,
    counts: dict[PublicSourceType, int],
    failures: dict[PublicSourceType, SearchDomainOutcome],
    facts: dict[PublicSourceType, SearchSourceFact],
) -> SearchDomainOutcome:
    """Search one counted domain or return its preserved count outcome."""
    source = request.source
    failure = failures.get(source)
    if failure is not None:
        return failure
    if counts.get(source, 0) == 0:
        return SearchDomainOutcome.success(source, [], source_fact=facts[source])
    return _search_domain(request, facts[source])


def search_combined(
    request: CombinedSearchRequest,
) -> CombinedSearchOutcome:
    """Search selected domains while retaining independent failures."""
    outcome, _timings = search_combined_timed(request)
    return outcome


def _combined_filter_options(request: CombinedSearchRequest) -> SearchFilterOptions:
    """Build the complete validation surface for a combined request."""
    from .search import SearchFilterOptions

    return SearchFilterOptions(
        language=request.code_filters.language,
        path=request.code_filters.path,
        node_type=request.code_filters.node_type,
        function_name=request.code_filters.function_name,
        class_name=request.code_filters.class_name,
        doc_type=request.vault_filters.doc_type,
        feature=request.vault_filters.feature,
        date=request.vault_filters.date,
        tag=request.vault_filters.tag,
        include_paths=list(request.code_filters.include_paths) or None,
        exclude_paths=list(request.code_filters.exclude_paths) or None,
        dedup_locales=request.code_filters.dedup_locales,
        prefer=request.code_filters.prefer,
        exclude_domains=list(request.code_filters.exclude_domains) or None,
        only_domains=list(request.code_filters.only_domains) or None,
        include_domains=list(request.code_filters.include_domains) or None,
        source_path=request.document_filters.source_path,
        extractor_id=request.document_filters.extractor_id,
        extractor_version=request.document_filters.extractor_version,
        locator_kind=request.document_filters.locator_kind,
        extractor_prefix=request.document_filters.extractor_prefix,
        metadata_filters=request.document_filters.metadata_filters,
    )


def _search_combined_domains(
    request: CombinedSearchRequest,
    searcher: VaultSearcher,
    counts: dict[PublicSourceType, int],
    failures: dict[PublicSourceType, SearchDomainOutcome],
    facts: dict[PublicSourceType, SearchSourceFact],
) -> tuple[SearchDomainOutcome, SearchDomainOutcome, SearchDomainOutcome | None]:
    """Execute each domain against its independently counted readiness fact."""
    vault = _indexed_domain_outcome(
        _DomainSearch(
            PublicSourceType.VAULT,
            request.root_dir.resolve(),
            lambda: searcher.search_vault(
                request.query,
                top_k=request.top_k,
                doc_type=request.vault_filters.doc_type,
                feature=request.vault_filters.feature,
                date=request.vault_filters.date,
                tag=request.vault_filters.tag,
                intent=request.vault_filters.intent,
            ),
        ),
        counts,
        failures,
        facts,
    )
    code = _indexed_domain_outcome(
        _DomainSearch(
            PublicSourceType.CODE,
            request.root_dir.resolve(),
            lambda: searcher.search_codebase(
                request.query,
                top_k=request.top_k,
                language=request.code_filters.language,
                path=request.code_filters.path,
                node_type=request.code_filters.node_type,
                function_name=request.code_filters.function_name,
                class_name=request.code_filters.class_name,
                include_paths=list(request.code_filters.include_paths) or None,
                exclude_paths=list(request.code_filters.exclude_paths) or None,
                dedup_locales=request.code_filters.dedup_locales,
                prefer=request.code_filters.prefer,
                exclude_domains=list(request.code_filters.exclude_domains) or None,
                only_domains=list(request.code_filters.only_domains) or None,
                include_domains=list(request.code_filters.include_domains) or None,
            ),
        ),
        counts,
        failures,
        facts,
    )
    if not request.include_documents:
        return vault, code, None
    document = _indexed_domain_outcome(
        _DomainSearch(
            PublicSourceType.DOCUMENT,
            request.root_dir.resolve(),
            lambda: searcher.search_document(
                request.query,
                top_k=request.top_k,
                source_path=request.document_filters.source_path,
                extractor_id=request.document_filters.extractor_id,
                extractor_version=request.document_filters.extractor_version,
                locator_kind=request.document_filters.locator_kind,
                extractor_prefix=request.document_filters.extractor_prefix,
                metadata_filters=request.document_filters.metadata_filters,
            ),
        ),
        counts,
        failures,
        facts,
    )
    return vault, code, document


def search_combined_timed(
    request: CombinedSearchRequest,
    *,
    registry: ServiceRegistry | None = None,
) -> tuple[CombinedSearchOutcome, dict[str, float]]:
    """Search selected domains under one lease with explicit partial outcomes."""
    validate_search_filters(
        PublicSourceType.COMBINED,
        _combined_filter_options(request),
        include_documents=request.include_documents,
    )
    root = pathlib.Path(request.root_dir).resolve()
    if request.include_documents:
        _refuse_document_filters(root, request.query, request.document_filters)
    active_registry = registry if registry is not None else get_registry()
    counts, count_failures, source_facts, timings, fences = _count_combined_domains(
        root, active_registry, include_documents=request.include_documents
    )
    if not any(counts.values()):
        empty = _empty_or_failed_combined_outcome(
            count_failures, source_facts, request.top_k
        )
        return _fenced_combined_outcome(empty, fences, root), timings

    vault: SearchDomainOutcome | None = None
    code: SearchDomainOutcome | None = None
    document: SearchDomainOutcome | None = None
    from .search._parsing import parse_query
    from .search._typesafe_context import classification_scope

    parsed = parse_query(request.query)
    filters: dict[str, object] = dict(parsed.filters)
    for group in (
        request.vault_filters,
        request.code_filters,
        request.document_filters,
    ):
        filters.update(
            {key: value for key, value in asdict(group).items() if value is not None}
        )
    with (
        active_registry.search_lease(root) as lease,
        classification_scope(
            parsed.text if request.top_k > 0 else "", "combined", filters
        ) as scope,
    ):
        session = scope.session
        timings["typesafe_query_attempt_ms"] = scope.query_attempt_ms
        for _attempt in range(2):
            vault, code, document = _search_combined_domains(
                request, lease.searcher, counts, count_failures, source_facts
            )
            if scope.session is None or not scope.session.failed:
                break
            scope.session = None
            timings["classification_fallback"] = 1.0
        if session is not None:
            timings.update(session.timings)
    if vault is None or code is None:
        raise RuntimeError("combined search lease ended without domain outcomes")
    outcome = CombinedSearchOutcome(vault, code, document, request.top_k)
    return _fenced_combined_outcome(outcome, fences, root), timings


def _fenced_combined_outcome(
    outcome: CombinedSearchOutcome,
    fences: dict[PublicSourceType, SourceReadFence],
    root: pathlib.Path,
) -> CombinedSearchOutcome:
    """Validate every domain against the epoch its count was taken under."""
    return CombinedSearchOutcome(
        _validated_epoch(outcome.vault, fences, root),
        _validated_epoch(outcome.code, fences, root),
        _validated_epoch(outcome.document, fences, root)
        if outcome.document is not None
        else None,
        outcome.top_k,
    )
