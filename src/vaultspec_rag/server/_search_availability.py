"""Bounded search-availability classification for canonical job snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from qdrant_client.http.exceptions import UnexpectedResponse

from .._root_identity import canonical_root_key
from .._search_state import (
    MAX_SEARCH_EVIDENCE_ITEMS,
    AbsenceAuthority,
    GenerationEvidence,
    SearchAvailability,
    SearchAvailabilityCause,
    SearchFreshness,
    SearchIndexStatus,
    SearchReasonCode,
    SearchSourceFact,
)
from ..job_models import JobMode, JobOperation, JobState

if TYPE_CHECKING:
    from .._source_types import IndexSource

__all__ = [
    "CanonicalSearchEvidence",
    "SearchResponseClassification",
    "SearchStatusCode",
    "classify_qdrant_collection_disappearance",
    "classify_search_response",
    "storage_conformance_refusal_fact",
]

# One declaration of the convergence-mode vocabulary; the transport owns it.

#: The stable HTTP statuses a classified search answers with. Declared beside
#: the classification that carries one so the transport's own mapping function
#: and this field cannot drift to different sets. The classifier cannot import
#: the transport - the transport imports it - so the alias lives on this side.
type SearchStatusCode = Literal[200, 409, 503]


@dataclass(frozen=True, slots=True)
class MatchingIndexJobReference:
    """Immutable public correlation fields for one matching index job."""

    id: str
    state: JobState
    mode: JobMode

    def to_dict(self) -> dict[str, object]:
        """Return the exact public response shape."""
        return {"id": self.id, "state": self.state.value, "mode": self.mode.value}


@dataclass(frozen=True, slots=True)
class SearchResponseClassification:
    """One response decision and its bounded, causally merged job evidence."""

    response: dict[str, object]
    status_code: SearchStatusCode
    matching_jobs: tuple[MatchingIndexJobReference, ...]
    matching_jobs_truncated: bool
    rebuilding: bool
    availability_cause: SearchAvailabilityCause | None
    source_fact: SearchSourceFact


@dataclass(frozen=True, slots=True)
class CanonicalSearchEvidence:
    """Explicit collection and publication evidence available at classification."""

    served_generation: str | None = None
    desired_generation: str | None = None
    publication_revision: int | None = None
    desired_revision: int | None = None
    collection_present: bool | None = None
    target_matches: bool | None = None
    integrity_verified: bool | None = None
    capacity_refused: bool = False
    rebuild_required: bool = False

    def __post_init__(self) -> None:
        GenerationEvidence(
            served_generation=self.served_generation,
            desired_generation=self.desired_generation,
            served_revision=self.publication_revision,
            desired_revision=self.desired_revision,
        )
        for field in (
            "collection_present",
            "target_matches",
            "integrity_verified",
        ):
            value = getattr(self, field)
            if value is not None and not isinstance(cast("object", value), bool):
                raise ValueError(f"{field} must be a boolean or None")
        if not isinstance(cast("object", self.capacity_refused), bool):
            raise ValueError("capacity_refused must be a boolean")
        if not isinstance(cast("object", self.rebuild_required), bool):
            raise ValueError("rebuild_required must be a boolean")
        if self.capacity_refused and self.rebuild_required:
            raise ValueError(
                "capacity_refused and rebuild_required are mutually exclusive"
            )


@dataclass(frozen=True, slots=True)
class SearchAvailabilityContext:
    """One request's immutable search-availability evidence and routing data.

    ``source`` names one concrete corpus, never the ``combined`` fan-out:
    :func:`_canonical_match` compares it against a job spec's own source, and
    no job is ever recorded against the fan-out. Callers construct this
    directly so the checker verifies that at the construction site; the value
    previously crossed a ``**values: object`` boundary that erased the type and
    then re-asserted it by cast, which is precisely how a ``combined`` value
    reached a field typed to exclude it without any checker objecting.
    """

    before_snapshot: Sequence[object]
    after_snapshot: Sequence[object]
    requested_root: Path
    source: IndexSource
    request_id: str
    index_state: Mapping[str, object]
    port: int | None
    canonical_evidence: CanonicalSearchEvidence = CanonicalSearchEvidence()


def storage_conformance_refusal_fact(
    exc: Exception,
    source_fact: SearchSourceFact,
    *,
    root: Path,
    port: int | None = None,
) -> SearchSourceFact | None:
    """Replace preflight readiness only for a typed compatibility refusal.

    Storage compatibility refusals require an explicit rebuild. Other failures
    remain under their existing error policy rather than gaining rebuild authority.
    Captured publication identities and bounded evidence remain diagnostic facts.
    """
    from ..store_runtime import StorageGeometryError

    if not isinstance(exc, StorageGeometryError):
        return None
    reason = SearchReasonCode.REBUILD_REQUIRED
    return replace(
        source_fact,
        availability=SearchAvailability.UNAVAILABLE,
        freshness=SearchFreshness.REBUILD_REQUIRED,
        absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
        reason_code=reason,
        retryable=False,
        remediation=reason.remediation(source_fact.source, port=port, target=str(root)),
    )


@dataclass(frozen=True, slots=True)
class _MatchingJob:
    """Normalized evidence from one matching convergence job."""

    id: str
    state: JobState
    mode: JobMode

    def to_reference(self) -> MatchingIndexJobReference:
        """Return immutable public job-reference evidence."""
        return MatchingIndexJobReference(id=self.id, state=self.state, mode=self.mode)


def _normalized_root(value: object) -> str | None:
    if not isinstance(value, (str, Path)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return canonical_root_key(Path(value).expanduser())
    except (OSError, RuntimeError, ValueError):
        return None


def _normalized_mode(value: object) -> JobMode | None:
    """Return the declared mode *value* names, or ``None`` when it names none.

    Asks the enum rather than testing its members one at a time: a third mode
    would have been rejected here as unknown while the domain accepted it.
    """
    try:
        return JobMode(value)
    except ValueError:
        return None


def _canonical_match(
    record: Mapping[str, object],
    spec: Mapping[str, object],
    *,
    requested_root: str,
    source: IndexSource,
) -> _MatchingJob | None:
    job_id = record.get("id")
    raw_state = record.get("state")
    if not isinstance(job_id, str) or not job_id.strip():
        return None
    state = _normalized_active_state(raw_state)
    if state is None:
        return None
    if spec.get("operation") != JobOperation.INDEX or spec.get("source") != source:
        return None
    if _normalized_root(spec.get("project_root")) != requested_root:
        return None
    mode = _normalized_mode(spec.get("mode"))
    if mode is None:
        return None
    return _MatchingJob(
        id=job_id,
        state=state,
        mode=mode,
    )


def _normalized_active_state(value: object) -> JobState | None:
    """Accept only known active states from canonical job records."""
    try:
        state = JobState(value)
    except ValueError:
        return None
    return None if state.is_terminal else state


def _matching_jobs(
    snapshot: Sequence[object],
    *,
    requested_root: str,
    source: IndexSource,
) -> list[_MatchingJob]:
    matches: list[_MatchingJob] = []
    for candidate in snapshot:
        if not isinstance(candidate, Mapping):
            continue
        # Mapping is invariant in its key type, so isinstance narrows only to
        # Mapping[Unknown, object]; every job record is str-keyed JSON.
        record = cast("Mapping[str, object]", candidate)
        spec = record.get("spec")
        if not isinstance(spec, Mapping):
            continue
        match = _canonical_match(
            record,
            cast("Mapping[str, object]", spec),
            requested_root=requested_root,
            source=source,
        )
        if match is not None:
            matches.append(match)
    return matches


def _deduplicated_matches(matches: Sequence[_MatchingJob]) -> list[_MatchingJob]:
    unique: list[_MatchingJob] = []
    seen_ids: set[str] = set()
    for match in matches:
        if match.id in seen_ids:
            continue
        seen_ids.add(match.id)
        unique.append(match)
    return unique


def _combined_matches(
    before_snapshot: Sequence[object],
    after_snapshot: Sequence[object],
    *,
    requested_root: str,
    source: IndexSource,
) -> list[_MatchingJob]:
    ordered_matches = _matching_jobs(
        after_snapshot,
        requested_root=requested_root,
        source=source,
    )
    ordered_matches.extend(
        _matching_jobs(
            before_snapshot,
            requested_root=requested_root,
            source=source,
        )
    )
    return _deduplicated_matches(ordered_matches)


def _target_is_current(evidence: CanonicalSearchEvidence) -> bool:
    """Return whether explicit publication evidence satisfies a verified target."""
    generation_targeted = evidence.desired_generation is not None
    revision_targeted = evidence.desired_revision is not None
    if not generation_targeted and not revision_targeted:
        return False
    generation_current = (
        not generation_targeted
        or evidence.served_generation == evidence.desired_generation
    )
    desired_revision = evidence.desired_revision
    revision_current = desired_revision is None or (
        evidence.publication_revision is not None
        and evidence.publication_revision >= desired_revision
    )
    return (
        evidence.collection_present is True
        and evidence.target_matches is True
        and evidence.integrity_verified is True
        and generation_current
        and revision_current
    )


def _source_states(
    canonical: CanonicalSearchEvidence,
    matches: Sequence[_MatchingJob],
    *,
    index_not_built: bool,
) -> tuple[SearchAvailability, SearchFreshness]:
    if canonical.capacity_refused:
        availability = SearchAvailability.CAPACITY_LIMITED
    elif (
        canonical.rebuild_required
        or canonical.collection_present is not True
        or index_not_built
    ):
        availability = SearchAvailability.UNAVAILABLE
    else:
        availability = SearchAvailability.USABLE
    if canonical.rebuild_required:
        freshness = SearchFreshness.REBUILD_REQUIRED
    elif matches:
        freshness = SearchFreshness.UPDATING
    elif _target_is_current(canonical):
        freshness = SearchFreshness.CURRENT
    else:
        freshness = SearchFreshness.UNVERIFIABLE
    return availability, freshness


def _source_reason(
    canonical: CanonicalSearchEvidence,
    matches: Sequence[_MatchingJob],
    *,
    index_not_built: bool,
) -> SearchReasonCode | None:
    if canonical.capacity_refused:
        return SearchReasonCode.CAPACITY_LIMITED
    if canonical.rebuild_required:
        return SearchReasonCode.REBUILD_REQUIRED
    if canonical.collection_present is False:
        return SearchReasonCode.INDEX_UNAVAILABLE
    if matches:
        return SearchReasonCode.INDEX_UPDATING
    if index_not_built:
        return SearchReasonCode.INDEX_NOT_BUILT
    return (
        None if _target_is_current(canonical) else SearchReasonCode.INDEX_UNVERIFIABLE
    )


def _project_source_fact(
    context: SearchAvailabilityContext,
    matches: Sequence[_MatchingJob],
) -> SearchSourceFact:
    """Project explicit canonical evidence without treating terminality as publish."""
    canonical = context.canonical_evidence
    index_not_built = _index_not_built(context)
    # A successful retrieval is direct evidence that this collection can serve,
    # even when an older daemon/index path supplied no publication identity.
    # Identity remains mandatory for CURRENT and authoritative absence below.
    availability, freshness = _source_states(
        canonical, matches, index_not_built=index_not_built
    )
    authority = (
        AbsenceAuthority.AUTHORITATIVE
        if availability is SearchAvailability.USABLE
        and freshness is SearchFreshness.CURRENT
        else AbsenceAuthority.NON_AUTHORITATIVE
    )
    reason_code = _source_reason(canonical, matches, index_not_built=index_not_built)
    remediation = (
        reason_code.remediation(
            context.source, port=context.port, target=str(context.requested_root)
        )
        if reason_code is not None
        else None
    )
    return SearchSourceFact(
        source=context.source,
        availability=availability,
        freshness=freshness,
        absence_authority=authority,
        generation=GenerationEvidence(
            served_generation=canonical.served_generation,
            desired_generation=canonical.desired_generation,
            served_revision=canonical.publication_revision,
            desired_revision=canonical.desired_revision,
        ),
        evidence=tuple(match.id for match in matches[:MAX_SEARCH_EVIDENCE_ITEMS]),
        reason_code=reason_code,
        retryable=(
            not canonical.rebuild_required
            and (
                canonical.capacity_refused
                or canonical.collection_present is False
                or bool(matches)
            )
        ),
        remediation=remediation,
    )


def _index_not_built(context: SearchAvailabilityContext) -> bool:
    """Require both an absent publication and a measured empty source."""
    from .._index_integrity import IntegrityReason

    integrity = context.index_state.get("index_integrity")
    if not isinstance(integrity, Mapping):
        return False
    integrity = cast("Mapping[str, object]", integrity)
    return (
        context.index_state.get("indexed_count") == 0
        and context.index_state.get("target_matches") is True
        and integrity.get("reason") == IntegrityReason.PROOF_MISSING
        and integrity.get("live_count") == 0
        and context.canonical_evidence.served_generation is None
        and context.canonical_evidence.publication_revision is None
    )


def _build_index_unavailable_response(
    context: SearchAvailabilityContext,
    *,
    matching_jobs: Sequence[MatchingIndexJobReference],
    matching_jobs_truncated: bool,
    rebuilding: bool,
    source_fact: SearchSourceFact,
) -> dict[str, object]:
    """Build a canonical failure body from the classification's source fact."""
    response_index_state: dict[str, object] = {
        "source": context.index_state["source"],
        "indexed_count": context.index_state["indexed_count"],
        "indexed_target_root": context.index_state["indexed_target_root"],
        "requested_target_root": context.index_state["requested_target_root"],
        "target_matches": context.index_state["target_matches"],
        "status": (
            SearchIndexStatus.UNAVAILABLE
            if context.canonical_evidence.collection_present is False
            else SearchIndexStatus.MISSING
            if source_fact.reason_code == SearchReasonCode.INDEX_NOT_BUILT
            else SearchIndexStatus.REBUILDING
            if rebuilding
            else SearchIndexStatus.UPDATING
        ).value,
        "matching_jobs": [job.to_dict() for job in matching_jobs],
        "matching_jobs_truncated": matching_jobs_truncated,
    }
    # The breadth verdict rides through the unavailability rewrite untouched:
    # an index mid-change is exactly when a caller needs to know whether the
    # collection it just read was reconcilable with its publication.
    integrity = context.index_state.get("index_integrity")
    if integrity is not None:
        response_index_state["index_integrity"] = integrity
    return source_fact.failure_response(
        request_id=context.request_id,
        index_state=response_index_state,
    )


def _is_qdrant_collection_disappearance(exc: BaseException) -> bool:
    """Recognize only Qdrant's structured collection-missing HTTP 404."""
    if not isinstance(exc, UnexpectedResponse) or exc.status_code != 404:
        return False
    try:
        payload_object: object = json.loads(exc.content)
    except (TypeError, ValueError):
        return False
    if not isinstance(payload_object, Mapping):
        return False
    payload = cast("Mapping[str, object]", payload_object)
    status_object = payload.get("status")
    if not isinstance(status_object, Mapping):
        return False
    status = cast("Mapping[str, object]", status_object)
    error = status.get("error")
    if not isinstance(error, str):
        return False
    normalized_error = error.casefold()
    return "collection" in normalized_error and (
        "doesn't exist" in normalized_error
        or "does not exist" in normalized_error
        or "not found" in normalized_error
    )


def classify_qdrant_collection_disappearance(
    exc: BaseException,
    context: SearchAvailabilityContext,
) -> SearchResponseClassification | None:
    """Convert a matching collection-disappearance race, or decline it."""
    if not _is_qdrant_collection_disappearance(exc):
        return None
    disappearance_context = replace(
        context,
        canonical_evidence=replace(
            context.canonical_evidence,
            collection_present=False,
            integrity_verified=False,
        ),
    )
    classification = classify_search_response(
        {"results": []},
        disappearance_context,
    )
    response = _build_index_unavailable_response(
        disappearance_context,
        matching_jobs=classification.matching_jobs,
        matching_jobs_truncated=classification.matching_jobs_truncated,
        rebuilding=classification.rebuilding,
        source_fact=classification.source_fact,
    )
    return replace(
        classification,
        response=response,
        status_code=503,
        availability_cause=SearchAvailabilityCause.COLLECTION_MISSING,
    )


def classify_search_response(
    result: dict[str, object],
    context: SearchAvailabilityContext,
) -> SearchResponseClassification:
    """Classify one response and preserve one bounded before/after evidence set."""
    normalized_root = _normalized_root(context.requested_root)
    matches = (
        _combined_matches(
            context.before_snapshot,
            context.after_snapshot,
            requested_root=normalized_root,
            source=context.source,
        )
        if normalized_root is not None
        else []
    )
    matching_jobs = tuple(
        match.to_reference() for match in matches[:MAX_SEARCH_EVIDENCE_ITEMS]
    )
    matching_jobs_truncated = len(matches) > MAX_SEARCH_EVIDENCE_ITEMS
    rebuilding = any(match.mode is JobMode.REBUILD for match in matches)
    source_fact = _project_source_fact(context, matches)

    results = result.get("results")
    if (
        isinstance(results, list)
        and not results
        and (matches or source_fact.reason_code == SearchReasonCode.INDEX_NOT_BUILT)
    ):
        response = _build_index_unavailable_response(
            context,
            matching_jobs=matching_jobs,
            matching_jobs_truncated=matching_jobs_truncated,
            rebuilding=rebuilding,
            source_fact=source_fact,
        )
        return SearchResponseClassification(
            response=response,
            status_code=503,
            matching_jobs=matching_jobs,
            matching_jobs_truncated=matching_jobs_truncated,
            rebuilding=rebuilding,
            availability_cause=SearchAvailabilityCause.MATCHING_INDEX_JOB
            if matches
            else None,
            source_fact=source_fact,
        )
    return SearchResponseClassification(
        response=result,
        status_code=200,
        matching_jobs=matching_jobs,
        matching_jobs_truncated=matching_jobs_truncated,
        rebuilding=rebuilding,
        availability_cause=None,
        source_fact=source_fact,
    )
