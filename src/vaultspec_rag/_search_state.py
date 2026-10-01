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
from typing import TYPE_CHECKING, Final, cast

from ._source_types import (
    INDEX_SOURCES,
    IndexSource,
    PublicSourceType,
    parse_source_type,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ._index_breadth import BreadthShortfall
    from ._index_integrity import IndexIntegrity

__all__ = [
    "COLLAPSE_MINIMUM_RESULTS",
    "MAX_SEARCH_EVIDENCE_ITEMS",
    "AbsenceAuthority",
    "BreadthFindings",
    "FreshnessWaitPolicy",
    "GenerationEvidence",
    "SearchAvailability",
    "SearchAvailabilityCause",
    "SearchEmptyReason",
    "SearchFreshness",
    "SearchIndexStatus",
    "SearchReadinessAggregate",
    "SearchReasonCode",
    "SearchSourceFact",
    "SearchWaitCause",
    "WaitObservation",
    "result_collapse",
    "search_index_state",
    "search_readiness_block",
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


class SearchIndexStatus(StrEnum):
    """Observed state of the source collection behind a search."""

    MISSING = "missing"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    REBUILDING = "rebuilding"
    UPDATING = "updating"


class SearchAvailabilityCause(StrEnum):
    """Evidence explaining an unavailable search response."""

    MATCHING_INDEX_JOB = "matching_index_job"
    COLLECTION_MISSING = "collection_missing"
    STORAGE_BACKEND = "storage_backend"


class SearchEmptyReason(StrEnum):
    """Why an authoritative search returned no matches."""

    PUBLISHED_EMPTY = "published_empty"
    NO_MATCH = "no_match"
    NO_MATCH_PATH_FILTER = "no_match_path_filter"


class SearchReasonCode(StrEnum):
    """Canonical diagnostic and failure vocabulary for search readiness."""

    INDEX_NOT_BUILT = "index_not_built"
    INDEX_UNAVAILABLE = "index_unavailable"
    INDEX_UNVERIFIABLE = "index_unverifiable"
    INDEX_UPDATING = "index_updating"
    INDEX_TRANSITION = "index_transition"
    PUBLISHED_GENERATION_CURRENT = "published_generation_current"
    REBUILD_REQUIRED = "rebuild_required"
    REBUILD_REFUSED = "rebuild_refused"
    FRESHNESS_WAIT_TIMEOUT = "freshness_wait_timeout"
    CAPACITY_LIMITED = "capacity_limited"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    BAD_REQUEST = "bad_request"
    QUIESCE_ADMISSION_CLOSED = "quiesce_admission_closed"

    @property
    def failure_code(self) -> SearchReasonCode:
        """Map setup and transition reasons onto the stable failure contract."""
        if self in {self.INDEX_NOT_BUILT, self.INDEX_UPDATING}:
            return self.INDEX_UNAVAILABLE
        return self

    @property
    def label(self) -> str:
        """Explain the index condition without inferring service health."""
        return {
            self.INDEX_NOT_BUILT: (
                "The index has not been built yet in the selected backend. "
                "Initial indexing is required; this does not by itself indicate "
                "a degraded service. Search cannot establish that no matching "
                "content exists until the index is published."
            ),
            self.INDEX_UPDATING: (
                "An index job is active for this worktree and source. The index "
                "is not yet ready to establish that no matches exist. Inspect "
                "the matching job before submitting another index request, "
                "then verify publication and retry the search."
            ),
            self.INDEX_UNAVAILABLE: "The index is unavailable for this search.",
            self.INDEX_UNVERIFIABLE: (
                "The empty search result is not authoritative for this source."
            ),
            self.INDEX_TRANSITION: "The index publication is changing.",
            self.PUBLISHED_GENERATION_CURRENT: "The published generation is current.",
            self.REBUILD_REQUIRED: "An explicit index rebuild is required.",
            self.REBUILD_REFUSED: "The requested index rebuild was refused.",
            self.FRESHNESS_WAIT_TIMEOUT: (
                "The index did not reach the requested publication before the bound."
            ),
            self.CAPACITY_LIMITED: "Search capacity is currently limited.",
            self.BACKEND_UNAVAILABLE: "The search backend is unavailable.",
            self.BAD_REQUEST: "The search request is invalid.",
            self.QUIESCE_ADMISSION_CLOSED: (
                "Search is temporarily unavailable while service compute admission "
                "is closed; retry after the service returns to running."
            ),
        }[self]

    def remediation(
        self, source: IndexSource, *, port: int | None, target: str
    ) -> str | None:
        """Name the operator action for this service-owned diagnosis."""
        from ._operator_commands import (
            IndexCommandOptions,
            index_command,
            server_jobs_command,
            server_status_command,
        )

        if self is self.INDEX_NOT_BUILT:
            status = server_status_command(port, verbose=True)
            jobs = server_jobs_command(port, index=source)
            build = index_command(
                source, IndexCommandOptions(rebuild=True, port=port, target=target)
            )
            return (
                f"Check service status with `{status}` and active jobs with `{jobs}`. "
                f"If no job is building this root and source, run `{build}`. "
                "After publication, verify this root's index status "
                "and retry the search."
            )
        if self is self.REBUILD_REQUIRED:
            return index_command(
                source, IndexCommandOptions(rebuild=True, port=port, target=target)
            )
        if self is self.INDEX_UNVERIFIABLE:
            return server_status_command(port, verbose=True)
        if self in {self.INDEX_UPDATING, self.CAPACITY_LIMITED}:
            return server_jobs_command(port, index=source)
        if self is self.INDEX_UNAVAILABLE:
            return index_command(source, IndexCommandOptions(port=port, target=target))
        return None


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


def _bounded_text(value: object, *, field: str, limit: int) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{field} must contain 1 to {limit} characters")


def _non_negative_finite(value: object, *, field: str) -> None:
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
        if not isinstance(cast("object", self.cause), SearchWaitCause):
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
    if (
        not isinstance(cast("object", fact.source), str)
        or fact.source not in INDEX_SOURCES
    ):
        raise ValueError(f"source must be a concrete index source, got {fact.source!r}")
    for field, expected in (
        ("availability", SearchAvailability),
        ("freshness", SearchFreshness),
        ("absence_authority", AbsenceAuthority),
        ("wait_policy", FreshnessWaitPolicy),
    ):
        if not isinstance(cast("object", getattr(fact, field)), expected):
            raise ValueError(f"{field} must be a {expected.__name__}")
    if not isinstance(cast("object", fact.generation), GenerationEvidence):
        raise ValueError("generation must be GenerationEvidence")
    if not isinstance(cast("object", fact.retryable), bool):
        raise ValueError("retryable must be a boolean")
    if not isinstance(cast("object", fact.waits), tuple) or not all(
        isinstance(cast("object", item), WaitObservation) for item in fact.waits
    ):
        raise ValueError("waits must be an immutable tuple of WaitObservation")
    if not isinstance(cast("object", fact.evidence), tuple) or not all(
        isinstance(cast("object", item), str) for item in fact.evidence
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
    reason_code: SearchReasonCode | None = None
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
        if self.reason_code is not None and not isinstance(
            cast("object", self.reason_code), SearchReasonCode
        ):
            raise ValueError("reason_code must be a SearchReasonCode or None")
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
            block["reason_code"] = self.reason_code.value
        if self.remediation is not None:
            block["remediation"] = self.remediation
        return block

    def failure_response(
        self,
        *,
        request_id: str,
        index_state: dict[str, object],
        sources: tuple[SearchSourceFact, ...] | None = None,
    ) -> dict[str, object]:
        """Serialize a service-owned readiness failure for every adapter."""
        reason = self.reason_code or SearchReasonCode.INDEX_UNVERIFIABLE
        return {
            "ok": False,
            "error": reason.failure_code.value,
            "message": (
                f"{self.source} index for {index_state.get('requested_target_root')}: "
                f"{reason.label}"
            ),
            "request_id": request_id,
            "index_state": index_state,
            "retryable": self.retryable,
            "readiness": search_readiness_block(sources or (self,)),
            "remediation": self.remediation,
        }


@dataclass(frozen=True, slots=True)
class SearchReadinessAggregate:
    """Lossless summary derived from all requested concrete source facts."""

    availability: SearchAvailability
    freshness: SearchFreshness
    absence_authority: AbsenceAuthority
    source_count: int
    usable_source_count: int
    degraded_sources: tuple[IndexSource, ...]

    def _validate_counts(self) -> None:
        if (
            not isinstance(cast("object", self.source_count), int)
            or isinstance(self.source_count, bool)
            or self.source_count <= 0
        ):
            raise ValueError("source_count must be positive")
        if (
            not isinstance(cast("object", self.usable_source_count), int)
            or isinstance(self.usable_source_count, bool)
            or not 0 <= self.usable_source_count <= self.source_count
        ):
            raise ValueError("usable_source_count must fit within source_count")

    def _validate_consistency(self) -> None:
        degraded_count = len(self.degraded_sources)
        unavailable_count = self.source_count - self.usable_source_count
        if not unavailable_count <= degraded_count <= self.source_count:
            raise ValueError("degraded_sources contradict the aggregate source counts")
        if self.freshness is SearchFreshness.CURRENT:
            if degraded_count != unavailable_count:
                raise ValueError(
                    "current aggregate cannot contain freshness degradation"
                )
        elif not degraded_count:
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

    @classmethod
    def from_sources(
        cls,
        sources: tuple[SearchSourceFact, ...],
    ) -> SearchReadinessAggregate:
        if not isinstance(cast("object", sources), tuple) or not all(
            isinstance(cast("object", fact), SearchSourceFact) for fact in sources
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
        degraded: tuple[IndexSource, ...] = tuple(
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
            if not isinstance(cast("object", getattr(self, field)), expected):
                raise ValueError(f"{field} must be a {expected.__name__}")
        if not isinstance(cast("object", self.degraded_sources), tuple) or not all(
            isinstance(cast("object", source), str) and source in INDEX_SOURCES
            for source in self.degraded_sources
        ):
            raise ValueError("degraded_sources must be an immutable tuple of sources")
        self._validate_counts()
        if len(set(self.degraded_sources)) != len(self.degraded_sources):
            raise ValueError("degraded_sources cannot contain duplicates")
        self._validate_consistency()
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


def search_readiness_block(
    sources: tuple[SearchSourceFact, ...],
) -> dict[str, object]:
    """Serialize source facts beside their solely derived aggregate."""
    aggregate = SearchReadinessAggregate.from_sources(sources)
    return {
        "sources": [source.as_dict() for source in sources],
        "aggregate": aggregate.as_dict(),
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

    ``shortfall`` is present only over a demonstrated deficit and carries the
    figures, so a renderer names it without comparing counts for itself.

    ``integrity`` follows the opposite discipline: emitted whenever the
    serve-time check ran, ``consistent`` included, so an absent block means
    only that the surface predates the check - never that the collection was
    checked and found fine.
    """

    shortfall: BreadthShortfall | None = None
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
    found = findings or BreadthFindings()
    from ._index_integrity import IntegrityVerdict

    unpublished_empty = count == 0 and (
        found.integrity is None
        or found.integrity.verdict is not IntegrityVerdict.CONSISTENT
    )
    state: dict[str, object] = {
        "source": source,
        "indexed_count": count,
        "indexed_target_root": requested_target,
        "requested_target_root": requested_target,
        "target_matches": True,
        "status": (
            SearchIndexStatus.MISSING
            if unpublished_empty
            else SearchIndexStatus.AVAILABLE
        ).value,
    }
    if found.shortfall is not None:
        state["shortfall"] = found.shortfall.as_index_state_block()
    if found.collapse is not None:
        state["result_collapse"] = dict(found.collapse)
    if found.integrity is not None:
        block = found.integrity.as_block()
        if found.integrity_repair_job_id is not None:
            block["repair_job_id"] = found.integrity_repair_job_id
        state["index_integrity"] = block
    return state
