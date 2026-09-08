"""Immutable canonical readiness scenarios shared by cross-surface tests.

The catalog describes service-owned facts and expected wire outcomes.  It does
not render CLI text, wrap MCP content, or classify HTTP responses; later tests
apply the same facts independently at each real boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from .._search_state import (
    MAX_SEARCH_EVIDENCE_ITEMS,
    AbsenceAuthority,
    FreshnessWaitPolicy,
    GenerationEvidence,
    SearchAvailability,
    SearchFreshness,
    SearchReadinessAggregate,
    SearchSourceFact,
    SearchWaitCause,
    WaitObservation,
    search_readiness_block,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .._source_types import IndexSource


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """Small source-neutral result witness retained by successful scenarios."""

    source: IndexSource
    result_id: str
    text: str

    def as_dict(self) -> dict[str, object]:
        return {"source": self.source, "id": self.result_id, "text": self.text}


@dataclass(frozen=True, slots=True)
class ScenarioFailure:
    """Stable failure fields owned by the service response."""

    code: str
    message: str
    retryable: bool
    remediation: str


@dataclass(frozen=True, slots=True)
class SearchReadinessScenario:
    """One deterministic response scenario reusable by every public surface."""

    name: str
    request_id: str
    status_code: int
    source_facts: tuple[SearchSourceFact, ...]
    results: tuple[ScenarioResult, ...] = ()
    failure: ScenarioFailure | None = None
    headers: tuple[tuple[str, str], ...] = ()
    aggregate: SearchReadinessAggregate = field(init=False)

    def __post_init__(self) -> None:
        aggregate = SearchReadinessAggregate.from_sources(self.source_facts)
        object.__setattr__(self, "aggregate", aggregate)
        if not self.name or not self.request_id:
            raise ValueError("scenario name and request_id must be non-empty")
        if self.failure is None:
            if self.status_code != 200:
                raise ValueError("successful scenarios must use status 200")
        elif self.status_code == 200 or self.results:
            raise ValueError("failure scenarios must suppress results and be non-200")
        if len(self.source_facts) > MAX_SEARCH_EVIDENCE_ITEMS:
            raise ValueError("scenario sources exceed the canonical evidence bound")

    def readiness(self) -> dict[str, object]:
        """Return the canonical serializer's source and aggregate block."""
        return search_readiness_block(self.source_facts)

    def result_payloads(self) -> list[dict[str, object]]:
        return [result.as_dict() for result in self.results]


def _generation(source: IndexSource, *, current: bool) -> GenerationEvidence:
    served = f"{source}-published-1"
    desired = served if current else f"{source}-target-2"
    return GenerationEvidence(
        served_generation=served,
        desired_generation=desired,
        served_revision=1,
        desired_revision=1 if current else 2,
    )


def _current(source: IndexSource, *, authoritative: bool = False) -> SearchSourceFact:
    return SearchSourceFact(
        source=source,
        availability=SearchAvailability.USABLE,
        freshness=SearchFreshness.CURRENT,
        absence_authority=(
            AbsenceAuthority.AUTHORITATIVE
            if authoritative
            else AbsenceAuthority.NON_AUTHORITATIVE
        ),
        generation=_generation(source, current=True),
        evidence=("publication_current",),
        reason_code="published_generation_current",
    )


def _updating(source: IndexSource) -> SearchSourceFact:
    return SearchSourceFact(
        source=source,
        availability=SearchAvailability.USABLE,
        freshness=SearchFreshness.UPDATING,
        absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
        generation=_generation(source, current=False),
        evidence=("prior_publication_served", "newer_target_pending"),
        reason_code="index_transition",
        retryable=True,
    )


def _failure_fact(  # noqa: PLR0913 - canonical facts keep each authority explicit.
    source: IndexSource,
    *,
    availability: SearchAvailability,
    freshness: SearchFreshness,
    reason: str,
    remediation: str,
    generation: GenerationEvidence | None = None,
    wait_policy: FreshnessWaitPolicy = FreshnessWaitPolicy.IMMEDIATE,
    waits: tuple[WaitObservation, ...] = (),
) -> SearchSourceFact:
    return SearchSourceFact(
        source=source,
        availability=availability,
        freshness=freshness,
        absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
        generation=generation or GenerationEvidence(),
        wait_policy=wait_policy,
        waits=waits,
        evidence=(reason,),
        reason_code=reason,
        retryable=freshness is not SearchFreshness.REBUILD_REQUIRED,
        remediation=remediation,
    )


_STATUS_REMEDIATION = "vaultspec-rag server status"
_REBUILD_REMEDIATION = "vaultspec-rag index --rebuild"
_TIMEOUT_WAIT = WaitObservation(
    cause=SearchWaitCause.INDEX_TRANSITION,
    waited_seconds=2.0,
    configured_bound_seconds=2.0,
    remaining_bound_seconds=0.0,
)


def _scenarios() -> dict[str, SearchReadinessScenario]:
    current = _current("vault")
    updating = _updating("code")
    authoritative_empty = _current("document", authoritative=True)
    return {
        "current": SearchReadinessScenario(
            "current",
            "scenario-current",
            200,
            (current,),
            (ScenarioResult("vault", "vault-1", "current result"),),
        ),
        "updating": SearchReadinessScenario(
            "updating",
            "scenario-updating",
            200,
            (updating,),
            (ScenarioResult("code", "code-1", "prior publication result"),),
        ),
        "unavailable": SearchReadinessScenario(
            "unavailable",
            "scenario-unavailable",
            503,
            (
                _failure_fact(
                    "vault",
                    availability=SearchAvailability.UNAVAILABLE,
                    freshness=SearchFreshness.UNVERIFIABLE,
                    reason="index_unavailable",
                    remediation=_STATUS_REMEDIATION,
                ),
            ),
            failure=ScenarioFailure(
                "index_unavailable",
                "The requested index is unavailable.",
                True,
                _STATUS_REMEDIATION,
            ),
        ),
        "unverifiable": SearchReadinessScenario(
            "unverifiable",
            "scenario-unverifiable",
            503,
            (
                _failure_fact(
                    "code",
                    availability=SearchAvailability.UNAVAILABLE,
                    freshness=SearchFreshness.UNVERIFIABLE,
                    reason="index_unverifiable",
                    remediation=_STATUS_REMEDIATION,
                ),
            ),
            failure=ScenarioFailure(
                "index_unverifiable",
                "Publication evidence is unavailable.",
                True,
                _STATUS_REMEDIATION,
            ),
        ),
        "rebuild_required": SearchReadinessScenario(
            "rebuild_required",
            "scenario-rebuild",
            409,
            (
                _failure_fact(
                    "document",
                    availability=SearchAvailability.UNAVAILABLE,
                    freshness=SearchFreshness.REBUILD_REQUIRED,
                    reason="rebuild_required",
                    remediation=_REBUILD_REMEDIATION,
                ),
            ),
            failure=ScenarioFailure(
                "rebuild_required",
                "The requested index requires a rebuild.",
                False,
                _REBUILD_REMEDIATION,
            ),
        ),
        "bounded_timeout": SearchReadinessScenario(
            "bounded_timeout",
            "scenario-timeout",
            503,
            (
                _failure_fact(
                    "code",
                    availability=SearchAvailability.USABLE,
                    freshness=SearchFreshness.UPDATING,
                    reason="freshness_wait_timeout",
                    remediation=_STATUS_REMEDIATION,
                    generation=_generation("code", current=False),
                    wait_policy=FreshnessWaitPolicy.BOUNDED,
                    waits=(_TIMEOUT_WAIT,),
                ),
            ),
            failure=ScenarioFailure(
                "freshness_wait_timeout",
                "The freshness wait reached its configured bound.",
                True,
                _STATUS_REMEDIATION,
            ),
        ),
        "capacity_limited": SearchReadinessScenario(
            "capacity_limited",
            "scenario-capacity",
            503,
            (
                _failure_fact(
                    "vault",
                    availability=SearchAvailability.CAPACITY_LIMITED,
                    freshness=SearchFreshness.UNVERIFIABLE,
                    reason="capacity_limited",
                    remediation=_STATUS_REMEDIATION,
                ),
            ),
            failure=ScenarioFailure(
                "capacity_limited",
                "Search capacity is temporarily unavailable.",
                True,
                _STATUS_REMEDIATION,
            ),
        ),
        "backend_unavailable": SearchReadinessScenario(
            "backend_unavailable",
            "scenario-backend",
            503,
            (
                _failure_fact(
                    "document",
                    availability=SearchAvailability.UNAVAILABLE,
                    freshness=SearchFreshness.UNVERIFIABLE,
                    reason="backend_unavailable",
                    remediation=_STATUS_REMEDIATION,
                ),
            ),
            failure=ScenarioFailure(
                "backend_unavailable",
                "The search backend is unavailable.",
                True,
                _STATUS_REMEDIATION,
            ),
        ),
        "authoritative_empty": SearchReadinessScenario(
            "authoritative_empty", "scenario-empty", 200, (authoritative_empty,)
        ),
        "mixed_combined": SearchReadinessScenario(
            "mixed_combined",
            "scenario-mixed",
            200,
            (
                current,
                updating,
                _failure_fact(
                    "document",
                    availability=SearchAvailability.UNAVAILABLE,
                    freshness=SearchFreshness.UNVERIFIABLE,
                    reason="backend_unavailable",
                    remediation=_STATUS_REMEDIATION,
                ),
            ),
            (ScenarioResult("vault", "vault-1", "useful partial result"),),
        ),
    }


SEARCH_READINESS_SCENARIOS: Final[Mapping[str, SearchReadinessScenario]] = (
    MappingProxyType(_scenarios())
)

__all__ = [
    "SEARCH_READINESS_SCENARIOS",
    "ScenarioFailure",
    "ScenarioResult",
    "SearchReadinessScenario",
]
