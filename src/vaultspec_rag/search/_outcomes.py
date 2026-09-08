"""Explicit per-domain outcomes for combined public search."""

from __future__ import annotations

from dataclasses import dataclass

from .._search_state import SearchReadinessAggregate, SearchSourceFact
from .._source_types import PublicSourceType
from ._models import DocumentSearchResult, SearchResult
from ._result_shaping import select_combined_results

__all__ = [
    "COMBINED_SEARCH_FAILED",
    "COMBINED_SEARCH_FAILED_MESSAGE",
    "FAILED_ACTIVITY_OUTCOMES",
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

#: Every activity outcome that means the search did not serve its caller.
#:
#: Named here for the same reason as the error kind above: a console marks
#: these rows as failures and the route classifies them, so a set restated on
#: the display side drifts silently the moment a condition is added. It drifted
#: exactly that way once - a client copy omitted the two admission-side
#: outcomes, so a registry refusing every search on the box rendered in the
#: same tone as a completed one, and only the outcome word said otherwise.
FAILED_ACTIVITY_OUTCOMES = frozenset(
    {
        "admission_failed",
        "cancelled",
        "combined_failed",
        "failed",
        "unavailable",
        "validation_rejected",
    }
)


@dataclass(frozen=True, slots=True)
class SearchDomainOutcome:
    """Success or failure for one independently queried search domain."""

    source: PublicSourceType
    source_fact: SearchSourceFact
    results: tuple[AnySearchResult, ...] = ()
    error_kind: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, PublicSourceType):
            raise ValueError("a domain outcome source must be a PublicSourceType")
        if self.source is PublicSourceType.COMBINED:
            raise ValueError("a domain outcome cannot use the combined source")
        if not isinstance(self.source_fact, SearchSourceFact):
            raise ValueError("a domain outcome requires a SearchSourceFact")
        if self.source_fact.source != self.source.value:
            raise ValueError("a domain outcome source fact carries the wrong source")
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
        *,
        source_fact: SearchSourceFact,
    ) -> SearchDomainOutcome:
        """Build a completed domain outcome."""
        return cls(source=source, source_fact=source_fact, results=tuple(results))

    @classmethod
    def failure(
        cls,
        source: PublicSourceType,
        error_kind: str,
        detail: str,
        *,
        source_fact: SearchSourceFact,
    ) -> SearchDomainOutcome:
        """Build a visible domain failure."""
        if not error_kind.strip() or not detail.strip():
            raise ValueError("search failure fields must not be empty")
        return cls(
            source=source,
            source_fact=source_fact,
            error_kind=error_kind,
            detail=detail,
        )


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

    @property
    def source_facts(self) -> tuple[SearchSourceFact, ...]:
        """Return every constituent fact in the stable domain order."""
        return (
            self.vault.source_fact,
            self.code.source_fact,
            self.document.source_fact,
        )

    @property
    def readiness(self) -> SearchReadinessAggregate:
        """Derive the combined state without erasing degraded constituents."""
        return SearchReadinessAggregate.from_sources(self.source_facts)

    def domain_status_payload(self) -> dict[str, dict[str, object]]:
        """Return the canonical wire status for each closed domain."""
        return {
            outcome.source.value: {
                "ok": outcome.ok,
                "results_count": len(outcome.results),
                "error_kind": outcome.error_kind,
                "detail": outcome.detail,
                "readiness": outcome.source_fact.as_dict(),
            }
            for outcome in (self.vault, self.code, self.document)
        }
