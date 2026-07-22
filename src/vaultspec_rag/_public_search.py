"""Document and combined public-search facades over registry leases."""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from ._source_types import PublicSourceType
from .registry import get_registry
from .search._outcomes import CombinedSearchOutcome, SearchDomainOutcome

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .search import DocumentSearchResult
    from .search._outcomes import AnySearchResult

__all__ = [
    "search_combined",
    "search_combined_timed",
    "search_documents",
    "search_documents_timed",
]


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


def search_combined(
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
) -> CombinedSearchOutcome:
    """Search all domains while retaining independent failures."""
    outcome, _timings = search_combined_timed(root_dir, query, top_k=top_k)
    return outcome


def search_combined_timed(
    root_dir: pathlib.Path,
    query: str,
    *,
    top_k: int = 5,
) -> tuple[CombinedSearchOutcome, dict[str, float]]:
    """Search all domains under one lease with explicit partial outcomes."""
    root = pathlib.Path(root_dir).resolve()
    registry = get_registry()
    counts = {
        PublicSourceType.VAULT: registry.vault_doc_count(root),
        PublicSourceType.CODE: registry.code_chunk_count(root),
        PublicSourceType.DOCUMENT: registry.document_chunk_count(root),
    }
    timings: dict[str, float] = {
        f"{source.value}_indexed_count": float(count)
        for source, count in counts.items()
    }
    if not any(counts.values()):
        return (
            CombinedSearchOutcome(
                SearchDomainOutcome.success(PublicSourceType.VAULT, []),
                SearchDomainOutcome.success(PublicSourceType.CODE, []),
                SearchDomainOutcome.success(PublicSourceType.DOCUMENT, []),
                top_k,
            ),
            timings,
        )

    registry.load_model()
    with registry.lease(root) as slot:
        vault = _search_domain(
            PublicSourceType.VAULT,
            lambda: (
                slot.searcher.search_vault(query, top_k=top_k)
                if counts[PublicSourceType.VAULT]
                else []
            ),
        )
        code = _search_domain(
            PublicSourceType.CODE,
            lambda: (
                slot.searcher.search_codebase(query, top_k=top_k)
                if counts[PublicSourceType.CODE]
                else []
            ),
        )
        document = _search_domain(
            PublicSourceType.DOCUMENT,
            lambda: (
                slot.searcher.search_document(query, top_k=top_k)
                if counts[PublicSourceType.DOCUMENT]
                else []
            ),
        )
    return CombinedSearchOutcome(vault, code, document, top_k), timings
