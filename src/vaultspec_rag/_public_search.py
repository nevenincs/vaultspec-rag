"""Document and combined public-search facades over registry leases."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._source_types import PublicSourceType
from .registry import get_registry
from .search import validate_search_filters
from .search._outcomes import CombinedSearchOutcome, SearchDomainOutcome

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .search import DocumentSearchResult
    from .search._outcomes import AnySearchResult
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
        ),
    )
    root = pathlib.Path(request.root_dir).resolve()
    active_registry = registry if registry is not None else get_registry()
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
        )
    if results is None or timings is None:
        raise RuntimeError("document search lease ended without a result")
    timings["indexed_count"] = float(indexed_count)
    return results, timings


def _search_domain(
    source: PublicSourceType,
    operation: Callable[[], Sequence[AnySearchResult]],
) -> SearchDomainOutcome:
    try:
        return SearchDomainOutcome.success(source, list(operation()))
    except Exception as exc:
        return SearchDomainOutcome.failure(
            source,
            type(exc).__name__,
            str(exc) or type(exc).__name__,
        )


def _count_combined_domains(
    root: pathlib.Path,
    registry: ServiceRegistry,
) -> tuple[
    dict[PublicSourceType, int],
    dict[PublicSourceType, SearchDomainOutcome],
    dict[str, float],
]:
    """Count each domain independently and retain model-free failures."""
    operations = {
        PublicSourceType.VAULT: lambda: registry.vault_doc_count(root),
        PublicSourceType.CODE: lambda: registry.code_chunk_count(root),
        PublicSourceType.DOCUMENT: lambda: registry.document_chunk_count(root),
    }
    counts: dict[PublicSourceType, int] = {}
    failures: dict[PublicSourceType, SearchDomainOutcome] = {}
    timings: dict[str, float] = {}
    for source, operation in operations.items():
        try:
            count = operation()
        except Exception as exc:
            failures[source] = SearchDomainOutcome.failure(
                source,
                type(exc).__name__,
                str(exc) or type(exc).__name__,
            )
        else:
            counts[source] = count
            timings[f"{source.value}_indexed_count"] = float(count)
    return counts, failures, timings


def _empty_or_failed_combined_outcome(
    failures: dict[PublicSourceType, SearchDomainOutcome],
    top_k: int,
) -> CombinedSearchOutcome:
    """Build the no-positive-count outcome without erasing count failures."""

    def outcome(source: PublicSourceType) -> SearchDomainOutcome:
        return failures.get(source) or SearchDomainOutcome.success(source, [])

    return CombinedSearchOutcome(
        outcome(PublicSourceType.VAULT),
        outcome(PublicSourceType.CODE),
        outcome(PublicSourceType.DOCUMENT),
        top_k,
    )


def _indexed_domain_outcome(
    source: PublicSourceType,
    counts: dict[PublicSourceType, int],
    failures: dict[PublicSourceType, SearchDomainOutcome],
    operation: Callable[[], Sequence[AnySearchResult]],
) -> SearchDomainOutcome:
    """Search one counted domain or return its preserved count outcome."""
    failure = failures.get(source)
    if failure is not None:
        return failure
    if counts.get(source, 0) == 0:
        return SearchDomainOutcome.success(source, [])
    return _search_domain(source, operation)


def search_combined(
    request: CombinedSearchRequest,
) -> CombinedSearchOutcome:
    """Search all domains while retaining independent failures."""
    outcome, _timings = search_combined_timed(request)
    return outcome


def search_combined_timed(
    request: CombinedSearchRequest,
    *,
    registry: ServiceRegistry | None = None,
) -> tuple[CombinedSearchOutcome, dict[str, float]]:
    """Search all domains under one lease with explicit partial outcomes."""
    from .search import SearchFilterOptions

    validate_search_filters(
        PublicSourceType.COMBINED,
        SearchFilterOptions(
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
        ),
    )
    root = pathlib.Path(request.root_dir).resolve()
    active_registry = registry if registry is not None else get_registry()
    counts, count_failures, timings = _count_combined_domains(root, active_registry)
    if not any(counts.values()):
        return _empty_or_failed_combined_outcome(count_failures, request.top_k), timings

    vault: SearchDomainOutcome | None = None
    code: SearchDomainOutcome | None = None
    document: SearchDomainOutcome | None = None
    with active_registry.search_lease(root) as lease:
        vault = _indexed_domain_outcome(
            PublicSourceType.VAULT,
            counts,
            count_failures,
            lambda: lease.searcher.search_vault(
                request.query,
                top_k=request.top_k,
                doc_type=request.vault_filters.doc_type,
                feature=request.vault_filters.feature,
                date=request.vault_filters.date,
                tag=request.vault_filters.tag,
                intent=request.vault_filters.intent,
            ),
        )
        code = _indexed_domain_outcome(
            PublicSourceType.CODE,
            counts,
            count_failures,
            lambda: lease.searcher.search_codebase(
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
        )
        document = _indexed_domain_outcome(
            PublicSourceType.DOCUMENT,
            counts,
            count_failures,
            lambda: lease.searcher.search_document(
                request.query,
                top_k=request.top_k,
                source_path=request.document_filters.source_path,
                extractor_id=request.document_filters.extractor_id,
                extractor_version=request.document_filters.extractor_version,
                locator_kind=request.document_filters.locator_kind,
            ),
        )
    if vault is None or code is None or document is None:
        raise RuntimeError("combined search lease ended without domain outcomes")
    return CombinedSearchOutcome(vault, code, document, request.top_k), timings
