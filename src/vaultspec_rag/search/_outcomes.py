"""Explicit per-domain outcomes for combined public search."""

from __future__ import annotations

from dataclasses import dataclass

from .._source_types import PublicSourceType
from ._models import DocumentSearchResult, SearchResult
from ._result_shaping import select_combined_results

__all__ = [
    "COMBINED_SEARCH_FAILED",
    "COMBINED_SEARCH_FAILED_MESSAGE",
    "CombinedSearchOutcome",
    "SearchDomainOutcome",
]

type AnySearchResult = SearchResult | DocumentSearchResult

#: Wire error kind for a combined search in which no domain completed. Named
#: here, beside the outcome that decides the condition, because the service
#: route and the in-process CLI path both report it and an operator hitting the
#: same failure through either must be told the same thing.
COMBINED_SEARCH_FAILED = "combined_search_failed"

#: The one sentence describing that condition on every surface.
COMBINED_SEARCH_FAILED_MESSAGE = "Every combined-search domain failed."


@dataclass(frozen=True, slots=True)
class SearchDomainOutcome:
    """Success or failure for one independently queried search domain."""

    source: PublicSourceType
    results: tuple[AnySearchResult, ...] = ()
    error_kind: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.source is PublicSourceType.COMBINED:
            raise ValueError("a domain outcome cannot use the combined source")
        if (self.error_kind is None) != (self.detail is None):
            raise ValueError("error kind and detail must be present together")
        if self.error_kind is not None and self.results:
            raise ValueError("a failed domain outcome cannot carry results")

    @property
    def ok(self) -> bool:
        """Return whether this domain completed, including an empty success."""
        return self.error_kind is None

    @classmethod
    def success(
        cls,
        source: PublicSourceType,
        results: list[AnySearchResult],
    ) -> SearchDomainOutcome:
        """Build a completed domain outcome."""
        return cls(source=source, results=tuple(results))

    @classmethod
    def failure(
        cls,
        source: PublicSourceType,
        error_kind: str,
        detail: str,
    ) -> SearchDomainOutcome:
        """Build a visible domain failure."""
        if not error_kind.strip() or not detail.strip():
            raise ValueError("search failure fields must not be empty")
        return cls(source=source, error_kind=error_kind, detail=detail)


@dataclass(frozen=True, slots=True)
class CombinedSearchOutcome:
    """Three-domain search outcome that never collapses partial failure."""

    vault: SearchDomainOutcome
    code: SearchDomainOutcome
    document: SearchDomainOutcome
    top_k: int

    def __post_init__(self) -> None:
        if self.vault.source is not PublicSourceType.VAULT:
            raise ValueError("vault outcome carries the wrong source")
        if self.code.source is not PublicSourceType.CODE:
            raise ValueError("code outcome carries the wrong source")
        if self.document.source is not PublicSourceType.DOCUMENT:
            raise ValueError("document outcome carries the wrong source")
        if isinstance(self.top_k, bool) or self.top_k < 0:
            raise ValueError("top_k must be a non-negative integer")

    @property
    def partial(self) -> bool:
        """Return whether at least one domain failed and another succeeded."""
        statuses = (self.vault.ok, self.code.ok, self.document.ok)
        return any(statuses) and not all(statuses)

    @property
    def ok(self) -> bool:
        """Return whether at least one domain completed successfully."""
        return any((self.vault.ok, self.code.ok, self.document.ok))

    @property
    def results(self) -> list[AnySearchResult]:
        """Select deterministic top-k from every successful domain."""
        candidates = [
            result
            for outcome in (self.vault, self.code, self.document)
            for result in outcome.results
        ]
        return select_combined_results(candidates, self.top_k)

    def domain_status_payload(self) -> dict[str, dict[str, object]]:
        """Return the canonical wire status for each closed domain."""
        return {
            outcome.source.value: {
                "ok": outcome.ok,
                "results_count": len(outcome.results),
                "error_kind": outcome.error_kind,
                "detail": outcome.detail,
            }
            for outcome in (self.vault, self.code, self.document)
        }
