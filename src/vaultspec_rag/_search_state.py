"""The index-state block a search response carries, and who decides it.

Every search surface has to tell a caller what the index behind an answer was
holding: which source it read, how many items that source had, whether the root
it searched is the root the caller asked for, and whether the collection is
demonstrably short of what it published. That is one fact about the service,
not a rendering concern, so it is settled here once and rendered by whoever
asked.

The module is a neutral leaf - stdlib plus the source-type vocabulary, no
server, no command-line, no store - so the in-process search path and the
daemon route can both reach it without importing each other. Two builders would
let the surfaces disagree about the shape a renderer looks up, and a renderer
reading a key only one of them emitted goes quiet on exactly the surface that
lacked it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import TYPE_CHECKING, Final

from ._source_types import (
    INDEX_SOURCES,
    IndexSource,
    PublicSourceType,
    parse_source_type,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ._index_breadth import BreadthShortfall, FileBreadthShortfall
    from ._index_integrity import IndexIntegrity

__all__ = [
    "COLLAPSE_MINIMUM_RESULTS",
    "MAX_SEARCH_EVIDENCE_ITEMS",
    "AbsenceAuthority",
    "BreadthFindings",
    "FreshnessWaitPolicy",
    "GenerationEvidence",
    "SearchAvailability",
    "SearchFreshness",
    "SearchReadinessAggregate",
    "SearchSourceFact",
    "SearchWaitCause",
    "WaitObservation",
    "result_collapse",
    "search_index_state",
]

#: How many results a page must hold before resolving to one path is evidence
#: of anything. A narrow query legitimately answers from a single file, and one
#: or two rows agreeing says nothing at all - so the signal stays silent until
#: a page is wide enough that agreement is the anomaly.
COLLAPSE_MINIMUM_RESULTS = 5

# Keep diagnostic payload work and wire size independent of job history size.
MAX_SEARCH_EVIDENCE_ITEMS: Final = 8
_MAX_IDENTIFIER_LENGTH: Final = 256
_MAX_REMEDIATION_LENGTH: Final = 1_024


class SearchAvailability(StrEnum):
    """Whether a concrete source can serve this request."""

    USABLE = "usable"
    UNAVAILABLE = "unavailable"
    CAPACITY_LIMITED = "capacity_limited"


class SearchFreshness(StrEnum):
    """Relationship between the served and desired published generations."""

    CURRENT = "current"
    UPDATING = "updating"
    UNVERIFIABLE = "unverifiable"
    REBUILD_REQUIRED = "rebuild_required"


class AbsenceAuthority(StrEnum):
    """Whether an empty answer proves absence for the requested target."""

    AUTHORITATIVE = "authoritative"
    NON_AUTHORITATIVE = "non_authoritative"


class FreshnessWaitPolicy(StrEnum):
    """Caller policy for publication convergence."""

    IMMEDIATE = "immediate"
    BOUNDED = "bounded"


class SearchWaitCause(StrEnum):
    """Closed ownership vocabulary for time spent waiting during search."""

    INDEX_TRANSITION = "index_transition"
    CONTROLLER_DEFERRAL = "controller_deferral"
    GPU_COMPUTE = "gpu_compute"
    SEARCH_ADMISSION = "search_admission"
    PROJECT_LEASE = "project_lease"
    STORAGE_BACKEND = "storage_backend"
    OTHER_SERVICE_CAPACITY = "other_service_capacity"


def _bounded_text(value: str | None, *, field: str, limit: int) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{field} must contain 1 to {limit} characters")


def _non_negative_finite(value: float | None, *, field: str) -> None:
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{field} must be a finite non-negative number")


@dataclass(frozen=True, slots=True)
class GenerationEvidence:
    """Canonical publication identities observed for one concrete source."""

    served_generation: str | None = None
    observed_generation: str | None = None
    desired_generation: str | None = None
    served_revision: int | None = None
    observed_revision: int | None = None
    desired_revision: int | None = None

    def __post_init__(self) -> None:
        for field in ("served_generation", "observed_generation", "desired_generation"):
            _bounded_text(
                getattr(self, field),
                field=field,
                limit=_MAX_IDENTIFIER_LENGTH,
            )
        for field in ("served_revision", "observed_revision", "desired_revision"):
            value = getattr(self, field)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ValueError(f"{field} must be a non-negative integer")

    def as_dict(self) -> dict[str, object]:
        """Return a transport-safe block without inventing absent evidence."""
        return {
            field: value
            for field in (
                "served_generation",
                "observed_generation",
                "desired_generation",
                "served_revision",
                "observed_revision",
                "desired_revision",
            )
            if (value := getattr(self, field)) is not None
        }


@dataclass(frozen=True, slots=True)
class WaitObservation:
    """One bounded wait measurement attributed to its owning boundary."""

    cause: SearchWaitCause
    waited_seconds: float
    configured_bound_seconds: float
    remaining_bound_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.cause, SearchWaitCause):
            raise ValueError("cause must be a SearchWaitCause")
        for field in (
            "waited_seconds",
            "configured_bound_seconds",
            "remaining_bound_seconds",
        ):
            _non_negative_finite(getattr(self, field), field=field)
        if self.remaining_bound_seconds > self.configured_bound_seconds:
            raise ValueError(
                "remaining_bound_seconds cannot exceed the configured bound"
            )
        if self.waited_seconds + self.remaining_bound_seconds > (
            self.configured_bound_seconds + 1e-9
        ):
            raise ValueError(
                "waited and remaining time cannot exceed the configured bound"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "cause": self.cause.value,
            "waited_seconds": self.waited_seconds,
            "configured_bound_seconds": self.configured_bound_seconds,
            "remaining_bound_seconds": self.remaining_bound_seconds,
        }


def _validate_source_fact_structure(fact: SearchSourceFact) -> None:
    if not isinstance(fact.source, str) or fact.source not in INDEX_SOURCES:
        raise ValueError(f"source must be a concrete index source, got {fact.source!r}")
    for field, expected in (
        ("availability", SearchAvailability),
        ("freshness", SearchFreshness),
        ("absence_authority", AbsenceAuthority),
        ("wait_policy", FreshnessWaitPolicy),
    ):
        if not isinstance(getattr(fact, field), expected):
            raise ValueError(f"{field} must be a {expected.__name__}")
    if not isinstance(fact.generation, GenerationEvidence):
        raise ValueError("generation must be GenerationEvidence")
    if not isinstance(fact.retryable, bool):
        raise ValueError("retryable must be a boolean")
    if not isinstance(fact.waits, tuple) or not all(
        isinstance(item, WaitObservation) for item in fact.waits
    ):
        raise ValueError("waits must be an immutable tuple of WaitObservation")
    if not isinstance(fact.evidence, tuple) or not all(
        isinstance(item, str) for item in fact.evidence
    ):
        raise ValueError("evidence must be an immutable tuple of strings")


@dataclass(frozen=True, slots=True)
class SearchSourceFact:
    """Immutable readiness evidence for one requested concrete source."""

    source: IndexSource
    availability: SearchAvailability
    freshness: SearchFreshness
    absence_authority: AbsenceAuthority
    generation: GenerationEvidence = GenerationEvidence()
    wait_policy: FreshnessWaitPolicy = FreshnessWaitPolicy.IMMEDIATE
    waits: tuple[WaitObservation, ...] = ()
    evidence: tuple[str, ...] = ()
    reason_code: str | None = None
    retryable: bool = False
    remediation: str | None = None

    def __post_init__(self) -> None:
        _validate_source_fact_structure(self)
        if len(self.waits) > MAX_SEARCH_EVIDENCE_ITEMS:
            raise ValueError("wait observations exceed the bounded evidence limit")
        if len(self.evidence) > MAX_SEARCH_EVIDENCE_ITEMS:
            raise ValueError("source evidence exceeds the bounded evidence limit")
        for item in self.evidence:
            _bounded_text(item, field="evidence item", limit=_MAX_IDENTIFIER_LENGTH)
        _bounded_text(
            self.reason_code,
            field="reason_code",
            limit=_MAX_IDENTIFIER_LENGTH,
        )
        _bounded_text(
            self.remediation,
            field="remediation",
            limit=_MAX_REMEDIATION_LENGTH,
        )
        if self.absence_authority is AbsenceAuthority.AUTHORITATIVE and (
            self.availability is not SearchAvailability.USABLE
            or self.freshness is not SearchFreshness.CURRENT
        ):
            raise ValueError("authoritative absence requires a usable, current source")
        served_revision = self.generation.served_revision
        desired_revision = self.generation.desired_revision
        if (
            self.freshness is SearchFreshness.CURRENT
            and served_revision is not None
            and desired_revision is not None
            and served_revision < desired_revision
        ):
            raise ValueError("current freshness cannot serve an older revision")
        served_generation = self.generation.served_generation
        desired_generation = self.generation.desired_generation
        if (
            self.freshness is SearchFreshness.CURRENT
            and served_generation is not None
            and desired_generation is not None
            and served_generation != desired_generation
        ):
            raise ValueError("current freshness cannot name different generations")

    def as_dict(self) -> dict[str, object]:
        block: dict[str, object] = {
            "source": self.source,
            "availability": self.availability.value,
            "freshness": self.freshness.value,
            "absence_authority": self.absence_authority.value,
            "generation": self.generation.as_dict(),
            "wait_policy": self.wait_policy.value,
            "waits": [observation.as_dict() for observation in self.waits],
            "evidence": list(self.evidence),
            "retryable": self.retryable,
        }
        if self.reason_code is not None:
            block["reason_code"] = self.reason_code
        if self.remediation is not None:
            block["remediation"] = self.remediation
        return block


@dataclass(frozen=True, slots=True)
class SearchReadinessAggregate:
    """Lossless summary derived from all requested concrete source facts."""

    availability: SearchAvailability
    freshness: SearchFreshness
    absence_authority: AbsenceAuthority
    source_count: int
    usable_source_count: int
    degraded_sources: tuple[IndexSource, ...]

    @classmethod
    def from_sources(
        cls,
        sources: tuple[SearchSourceFact, ...],
    ) -> SearchReadinessAggregate:
        if not isinstance(sources, tuple) or not all(
            isinstance(fact, SearchSourceFact) for fact in sources
        ):
            raise ValueError("sources must be an immutable tuple of source facts")
        if not sources:
            raise ValueError("an aggregate requires at least one source fact")
        identities = tuple(fact.source for fact in sources)
        if len(set(identities)) != len(identities):
            raise ValueError("an aggregate cannot contain duplicate source facts")
        usable_count = sum(
            fact.availability is SearchAvailability.USABLE for fact in sources
        )
        if usable_count:
            availability = SearchAvailability.USABLE
        elif any(
            fact.availability is SearchAvailability.CAPACITY_LIMITED for fact in sources
        ):
            availability = SearchAvailability.CAPACITY_LIMITED
        else:
            availability = SearchAvailability.UNAVAILABLE
        freshness = next(
            (
                state
                for state in (
                    SearchFreshness.REBUILD_REQUIRED,
                    SearchFreshness.UNVERIFIABLE,
                    SearchFreshness.UPDATING,
                )
                if any(fact.freshness is state for fact in sources)
            ),
            SearchFreshness.CURRENT,
        )
        authority = (
            AbsenceAuthority.AUTHORITATIVE
            if all(
                fact.absence_authority is AbsenceAuthority.AUTHORITATIVE
                for fact in sources
            )
            else AbsenceAuthority.NON_AUTHORITATIVE
        )
        degraded = tuple(
            fact.source
            for fact in sources
            if fact.availability is not SearchAvailability.USABLE
            or fact.freshness is not SearchFreshness.CURRENT
        )
        return cls(
            availability=availability,
            freshness=freshness,
            absence_authority=authority,
            source_count=len(sources),
            usable_source_count=usable_count,
            degraded_sources=degraded,
        )

    def __post_init__(self) -> None:
        for field, expected in (
            ("availability", SearchAvailability),
            ("freshness", SearchFreshness),
            ("absence_authority", AbsenceAuthority),
        ):
            if not isinstance(getattr(self, field), expected):
                raise ValueError(f"{field} must be a {expected.__name__}")
        if not isinstance(self.degraded_sources, tuple) or not all(
            isinstance(source, str) and source in INDEX_SOURCES
            for source in self.degraded_sources
        ):
            raise ValueError("degraded_sources must be an immutable tuple of sources")
        if (
            not isinstance(self.source_count, int)
            or isinstance(self.source_count, bool)
            or self.source_count <= 0
        ):
            raise ValueError("source_count must be positive")
        if (
            not isinstance(self.usable_source_count, int)
            or isinstance(self.usable_source_count, bool)
            or not 0 <= self.usable_source_count <= self.source_count
        ):
            raise ValueError("usable_source_count must fit within source_count")
        if len(set(self.degraded_sources)) != len(self.degraded_sources):
            raise ValueError("degraded_sources cannot contain duplicates")
        degraded_count = len(self.degraded_sources)
        unavailable_count = self.source_count - self.usable_source_count
        if not unavailable_count <= degraded_count <= self.source_count:
            raise ValueError("degraded_sources contradict the aggregate source counts")
        if (
            self.freshness is SearchFreshness.CURRENT
            and degraded_count != unavailable_count
        ):
            raise ValueError("current aggregate cannot contain freshness degradation")
        if self.freshness is not SearchFreshness.CURRENT and not degraded_count:
            raise ValueError("non-current aggregate requires a degraded source")
        if (
            self.availability is SearchAvailability.USABLE
            and not self.usable_source_count
        ):
            raise ValueError("usable aggregate requires at least one usable source")
        if (
            self.availability is not SearchAvailability.USABLE
            and self.usable_source_count
        ):
            raise ValueError("non-usable aggregate cannot report usable sources")
        if self.absence_authority is AbsenceAuthority.AUTHORITATIVE and (
            self.availability is not SearchAvailability.USABLE
            or self.freshness is not SearchFreshness.CURRENT
            or self.usable_source_count != self.source_count
            or self.degraded_sources
        ):
            raise ValueError(
                "authoritative aggregate requires every source to be usable and current"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "availability": self.availability.value,
            "freshness": self.freshness.value,
            "absence_authority": self.absence_authority.value,
            "source_count": self.source_count,
            "usable_source_count": self.usable_source_count,
            "degraded_sources": list(self.degraded_sources),
        }


def result_collapse(paths: Sequence[str]) -> dict[str, object] | None:
    """Return the collapse figures when a whole page resolves to one path.

    The failure this reports is the one a count cannot: an index that answers
    every query from a single surviving file while reporting a healthy section
    count. Both observed occurrences looked like real "this behaviour does not
    exist here" answers, and a false negative to that question is how a second
    implementation of something gets written.

    Deliberately count-independent, and that is the whole point of having it
    beside the breadth comparisons rather than folded into them. A fragment
    that republished its own point figure is self-consistent, so every count
    the service can check agrees with itself; the only thing left that
    disagrees is what the results actually look like.

    Returns ``None`` for a page too small to judge, an empty page, or a page
    spanning more than one path. A caller must not read absence as "diverse" -
    it also covers "not enough evidence".

    This is a signal, not a verdict. A broad query that genuinely belongs to
    one file trips it, and that is the accepted cost: the warning says what was
    observed and lets the reader judge, rather than asserting the index is
    broken.
    """
    if len(paths) < COLLAPSE_MINIMUM_RESULTS:
        return None
    distinct = set(paths)
    if len(distinct) != 1:
        return None
    return {
        "result_count": len(paths),
        "distinct_paths": 1,
        "path": next(iter(distinct)),
    }


@dataclass(frozen=True, slots=True)
class BreadthFindings:
    """Completeness conclusions one search settled, attached to its block.

    ``shortfall`` and ``file_shortfall`` are present only over a demonstrated
    deficit and carry the figures, so a renderer names them without comparing
    counts for itself. Absence means complete or unknowable; a consumer must
    not read it as either one alone.

    ``integrity`` follows the opposite discipline: emitted whenever the
    serve-time check ran, ``consistent`` included, so an absent block means
    only that the surface predates the check - never that the collection was
    checked and found fine.
    """

    shortfall: BreadthShortfall | None = None
    file_shortfall: FileBreadthShortfall | None = None
    integrity: IndexIntegrity | None = None
    #: Id of the automatic repair job in flight for a shrunken verdict, set by
    #: the service path that queued it. Rendered as an additive key inside the
    #: integrity block, so surfaces that never queue repairs simply omit it.
    integrity_repair_job_id: str | None = None
    #: Figures from :func:`result_collapse` when this page resolved to one
    #: path. Absent when the page was diverse OR too small to judge, so a
    #: consumer must not read absence as a clean bill of health.
    collapse: dict[str, object] | None = None


def search_index_state(
    *,
    indexed_count: int | float,
    requested_root: object,
    search_type: PublicSourceType | str,
    findings: BreadthFindings | None = None,
) -> dict[str, object]:
    """Return the canonical ``index_state`` block for one search response.

    ``findings`` carries the completeness conclusions the search settled; see
    :class:`BreadthFindings` for the presence discipline of each field.
    """
    requested_target = str(requested_root)
    source = parse_source_type(search_type, allow_aliases=True).value
    count = int(indexed_count)
    state: dict[str, object] = {
        "source": source,
        "indexed_count": count,
        "indexed_target_root": requested_target,
        "requested_target_root": requested_target,
        "target_matches": True,
        "status": "missing" if count == 0 else "available",
    }
    found = findings or BreadthFindings()
    if found.shortfall is not None:
        state["shortfall"] = found.shortfall.as_index_state_block()
    # Independent of the point comparison: a republished fragment stamps a
    # point count that agrees with itself, so only the file figures disagree.
    if found.file_shortfall is not None:
        state["file_shortfall"] = found.file_shortfall.as_index_state_block()
    if found.collapse is not None:
        state["result_collapse"] = dict(found.collapse)
    if found.integrity is not None:
        block = found.integrity.as_block()
        if found.integrity_repair_job_id is not None:
            block["repair_job_id"] = found.integrity_repair_job_id
        state["index_integrity"] = block
    return state
