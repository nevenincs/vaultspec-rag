"""Document and combined public-search facades over registry leases."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._source_types import PublicSourceType
from .registry import get_registry
from .search import validate_search_filters
from .search._outcomes import CombinedSearchOutcome, SearchDomainOutcome

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .search import DocumentSearchResult
    from .search._outcomes import AnySearchResult

__all__ = [
    "CodeCombinedSearchFilters",
    "DocumentCombinedSearchFilters",
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


def search_documents(
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
    source_path: str | None = None,
    extractor_id: str | None = None,
    extractor_version: str | None = None,
    locator_kind: str | None = None,
) -> list[DocumentSearchResult]:
    """Search only the independently owned document collection."""
    results, _timings = search_documents_timed(
        root_dir,
        query,
        top_k=top_k,
        source_path=source_path,
        extractor_id=extractor_id,
        extractor_version=extractor_version,
        locator_kind=locator_kind,
    )
    return results


def search_documents_timed(
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
    source_path: str | None = None,
    extractor_id: str | None = None,
    extractor_version: str | None = None,
    locator_kind: str | None = None,
) -> tuple[list[DocumentSearchResult], dict[str, float]]:
    """Search documents and return canonical service timing fields."""
    validate_search_filters(
        PublicSourceType.DOCUMENT,
        source_path=source_path,
        extractor_id=extractor_id,
        extractor_version=extractor_version,
        locator_kind=locator_kind,
    )
    root = pathlib.Path(root_dir).resolve()
    registry = get_registry()
    indexed_count = registry.document_chunk_count(root)
    if indexed_count == 0:
        return [], {"indexed_count": 0.0}
    registry.load_model()
    with registry.lease(root) as slot:
        results, timings = slot.searcher.search_document_timed(
            query,
            top_k=top_k,
            source_path=source_path,
            extractor_id=extractor_id,
            extractor_version=extractor_version,
            locator_kind=locator_kind,
        )
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
) -> tuple[
    dict[PublicSourceType, int],
    dict[PublicSourceType, SearchDomainOutcome],
    dict[str, float],
]:
    """Count each domain independently and retain model-free failures."""
    registry = get_registry()
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
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
    vault_filters: VaultCombinedSearchFilters | None = None,
    code_filters: CodeCombinedSearchFilters | None = None,
    document_filters: DocumentCombinedSearchFilters | None = None,
) -> CombinedSearchOutcome:
    """Search all domains while retaining independent failures."""
    outcome, _timings = search_combined_timed(
        root_dir,
        query,
        top_k=top_k,
        vault_filters=vault_filters,
        code_filters=code_filters,
        document_filters=document_filters,
    )
    return outcome


def search_combined_timed(
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
    vault_filters: VaultCombinedSearchFilters | None = None,
    code_filters: CodeCombinedSearchFilters | None = None,
    document_filters: DocumentCombinedSearchFilters | None = None,
) -> tuple[CombinedSearchOutcome, dict[str, float]]:
    """Search all domains under one lease with explicit partial outcomes."""
    vault_filters = vault_filters or VaultCombinedSearchFilters()
    code_filters = code_filters or CodeCombinedSearchFilters()
    document_filters = document_filters or DocumentCombinedSearchFilters()
    validate_search_filters(
        PublicSourceType.COMBINED,
        language=code_filters.language,
        path=code_filters.path,
        node_type=code_filters.node_type,
        function_name=code_filters.function_name,
        class_name=code_filters.class_name,
        doc_type=vault_filters.doc_type,
        feature=vault_filters.feature,
        date=vault_filters.date,
        tag=vault_filters.tag,
        include_paths=list(code_filters.include_paths) or None,
        exclude_paths=list(code_filters.exclude_paths) or None,
        dedup_locales=code_filters.dedup_locales,
        prefer=code_filters.prefer,
        exclude_domains=list(code_filters.exclude_domains) or None,
        only_domains=list(code_filters.only_domains) or None,
        include_domains=list(code_filters.include_domains) or None,
        source_path=document_filters.source_path,
        extractor_id=document_filters.extractor_id,
        extractor_version=document_filters.extractor_version,
        locator_kind=document_filters.locator_kind,
    )
    root = pathlib.Path(root_dir).resolve()
    registry = get_registry()
    counts, count_failures, timings = _count_combined_domains(root)
    if not any(counts.values()):
        return _empty_or_failed_combined_outcome(count_failures, top_k), timings

    registry.load_model()
    with registry.lease(root) as slot:
        vault = _indexed_domain_outcome(
            PublicSourceType.VAULT,
            counts,
            count_failures,
            lambda: slot.searcher.search_vault(
                query,
                top_k=top_k,
                doc_type=vault_filters.doc_type,
                feature=vault_filters.feature,
                date=vault_filters.date,
                tag=vault_filters.tag,
                intent=vault_filters.intent,
            ),
        )
        code = _indexed_domain_outcome(
            PublicSourceType.CODE,
            counts,
            count_failures,
            lambda: slot.searcher.search_codebase(
                query,
                top_k=top_k,
                language=code_filters.language,
                path=code_filters.path,
                node_type=code_filters.node_type,
                function_name=code_filters.function_name,
                class_name=code_filters.class_name,
                include_paths=list(code_filters.include_paths) or None,
                exclude_paths=list(code_filters.exclude_paths) or None,
                dedup_locales=code_filters.dedup_locales,
                prefer=code_filters.prefer,
                exclude_domains=list(code_filters.exclude_domains) or None,
                only_domains=list(code_filters.only_domains) or None,
                include_domains=list(code_filters.include_domains) or None,
            ),
        )
        document = _indexed_domain_outcome(
            PublicSourceType.DOCUMENT,
            counts,
            count_failures,
            lambda: slot.searcher.search_document(
                query,
                top_k=top_k,
                source_path=document_filters.source_path,
                extractor_id=document_filters.extractor_id,
                extractor_version=document_filters.extractor_version,
                locator_kind=document_filters.locator_kind,
            ),
        )
    return CombinedSearchOutcome(vault, code, document, top_k), timings
