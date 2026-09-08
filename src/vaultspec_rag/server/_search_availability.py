"""Bounded search-availability classification for canonical job snapshots."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from qdrant_client.http.exceptions import UnexpectedResponse

from .._operator_commands import (
    IndexCommandOptions,
    index_command,
    server_jobs_command,
    server_status_command,
)
from .._search_state import (
    MAX_SEARCH_EVIDENCE_ITEMS,
    AbsenceAuthority,
    GenerationEvidence,
    SearchAvailability,
    SearchFreshness,
    SearchSourceFact,
    search_readiness_block,
)

if TYPE_CHECKING:
    from .._source_types import IndexSource

    # The convergence-mode vocabulary is the domain's, not the client's.
    # Annotation-only, so job_models is not imported at runtime.
    from ..job_models import JobMode

__all__ = [
    "CanonicalSearchEvidence",
    "SearchResponseClassification",
    "classify_qdrant_collection_disappearance",
    "classify_search_response",
]

# One declaration of the convergence-mode vocabulary; the transport owns it.

_CANONICAL_NONTERMINAL_STATES = frozenset(
    {"queued", "running", "pausing", "paused", "cancelling"}
)


@dataclass(frozen=True, slots=True)
class MatchingIndexJobReference:
    """Immutable public correlation fields for one matching index job."""

    id: str
    state: str
    mode: JobMode

    def to_dict(self) -> dict[str, object]:
        """Return the exact public response shape."""
        return {"id": self.id, "state": self.state, "mode": self.mode}


@dataclass(frozen=True, slots=True)
class SearchResponseClassification:
    """One response decision and its bounded, causally merged job evidence."""

    response: dict[str, object]
    status_code: Literal[200, 503]
    matching_jobs: tuple[MatchingIndexJobReference, ...]
    matching_jobs_truncated: bool
    rebuilding: bool
    availability_cause: Literal["matching_index_job", "collection_missing"] | None
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
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{field} must be a boolean or None")
        if not isinstance(self.capacity_refused, bool):
            raise ValueError("capacity_refused must be a boolean")
        if not isinstance(self.rebuild_required, bool):
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


@dataclass(frozen=True, slots=True)
class _MatchingJob:
    """Normalized evidence from one matching convergence job."""

    id: str
    state: str
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
        resolved = Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None
    return os.path.normcase(str(resolved))


def _normalized_mode(value: object) -> JobMode | None:
    """Return the declared mode *value* names, or ``None`` when it names none.

    Asks the enum rather than testing its members one at a time: a third mode
    would have been rejected here as unknown while the domain accepted it.
    """
    from ..job_models import JobMode as _JobMode

    try:
        return _JobMode(value)
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
    state = record.get("state")
    if not isinstance(job_id, str) or not job_id.strip():
        return None
    if not isinstance(state, str) or state not in _CANONICAL_NONTERMINAL_STATES:
        return None
    if spec.get("operation") != "index" or spec.get("source") != source:
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
    revision_current = not revision_targeted or (
        evidence.publication_revision is not None
        and evidence.publication_revision >= evidence.desired_revision
    )
    return (
        evidence.collection_present is True
        and evidence.target_matches is True
        and evidence.integrity_verified is True
        and generation_current
        and revision_current
    )


def _project_source_fact(
    context: SearchAvailabilityContext,
    matches: Sequence[_MatchingJob],
) -> SearchSourceFact:
    """Project explicit canonical evidence without treating terminality as publish."""
    canonical = context.canonical_evidence
    # A successful retrieval is direct evidence that this collection can serve,
    # even when an older daemon/index path supplied no publication identity.
    # Identity remains mandatory for CURRENT and authoritative absence below.
    served_collection = canonical.collection_present is True
    current = _target_is_current(canonical)
    if canonical.capacity_refused:
        availability = SearchAvailability.CAPACITY_LIMITED
    elif canonical.rebuild_required:
        availability = SearchAvailability.UNAVAILABLE
    elif served_collection:
        availability = SearchAvailability.USABLE
    else:
        availability = SearchAvailability.UNAVAILABLE
    if canonical.rebuild_required:
        freshness = SearchFreshness.REBUILD_REQUIRED
    elif matches:
        freshness = SearchFreshness.UPDATING
    elif current:
        freshness = SearchFreshness.CURRENT
    else:
        freshness = SearchFreshness.UNVERIFIABLE
    authority = (
        AbsenceAuthority.AUTHORITATIVE
        if availability is SearchAvailability.USABLE
        and freshness is SearchFreshness.CURRENT
        else AbsenceAuthority.NON_AUTHORITATIVE
    )
    reason_code = (
        "capacity_limited"
        if canonical.capacity_refused
        else "rebuild_required"
        if canonical.rebuild_required
        else "index_unavailable"
        if canonical.collection_present is False
        else "index_updating"
        if matches
        else "index_unverifiable"
        if not current
        else None
    )
    remediation = (
        index_command(
            context.source,
            IndexCommandOptions(rebuild=True, port=context.port),
        )
        if reason_code == "rebuild_required"
        else server_status_command(context.port, verbose=True)
        if reason_code == "index_unverifiable"
        else server_jobs_command(context.port, index=context.source)
        if matches or reason_code == "capacity_limited"
        else index_command(context.source, IndexCommandOptions(port=context.port))
        if reason_code == "index_unavailable"
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
            "unavailable"
            if context.canonical_evidence.collection_present is False
            else "rebuilding"
            if rebuilding
            else "updating"
        ),
        "matching_jobs": [job.to_dict() for job in matching_jobs],
        "matching_jobs_truncated": matching_jobs_truncated,
    }
    # The breadth verdict rides through the unavailability rewrite untouched:
    # an index mid-change is exactly when a caller needs to know whether the
    # collection it just read was reconcilable with its publication.
    integrity = context.index_state.get("index_integrity")
    if integrity is not None:
        response_index_state["index_integrity"] = integrity
    error = (
        source_fact.reason_code
        if source_fact.reason_code in {"capacity_limited", "rebuild_required"}
        else "index_unavailable"
    )
    state = (
        "unavailable"
        if context.canonical_evidence.collection_present is False
        else "changing"
    )
    return {
        "ok": False,
        "error": error,
        "message": (
            f"The {context.source} index for {context.requested_root} is {state}; "
            "this empty search cannot establish that no matches exist."
        ),
        "request_id": context.request_id,
        "index_state": response_index_state,
        "retryable": source_fact.retryable,
        "readiness": search_readiness_block((source_fact,)),
        "remediation": source_fact.remediation,
    }


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
        availability_cause="collection_missing",
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
    rebuilding = any(match.mode == "rebuild" for match in matches)
    source_fact = _project_source_fact(context, matches)

    results = result.get("results")
    if isinstance(results, list) and not results and matches:
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
            availability_cause="matching_index_job",
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
