"""Bounded search-availability classification for canonical job snapshots."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from qdrant_client.http.exceptions import UnexpectedResponse

from .._operator_commands import server_jobs_command

if TYPE_CHECKING:
    # The convergence-mode vocabulary has one declaration, in the transport.
    # Annotation-only, so the client is not imported at runtime.
    from ..serviceclient._transport import JobMode

__all__ = [
    "SearchResponseClassification",
    "classify_qdrant_collection_disappearance",
    "classify_search_response",
]

type IndexSource = Literal["vault", "code", "document"]
# One declaration of the convergence-mode vocabulary; the transport owns it.

_CANONICAL_NONTERMINAL_STATES = frozenset(
    {"queued", "running", "pausing", "paused", "cancelling"}
)
_MAX_EXPOSED_JOBS = 8


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
    if value == "incremental":
        return "incremental"
    if value == "rebuild":
        return "rebuild"
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


def _build_index_unavailable_response(
    *,
    requested_root: Path,
    source: IndexSource,
    request_id: str,
    index_state: Mapping[str, object],
    port: int | None,
    matching_jobs: Sequence[MatchingIndexJobReference],
    matching_jobs_truncated: bool,
    rebuilding: bool,
) -> dict[str, object]:
    """Build the exact failure body from the classification's own evidence."""
    response_index_state: dict[str, object] = {
        "source": index_state["source"],
        "indexed_count": index_state["indexed_count"],
        "indexed_target_root": index_state["indexed_target_root"],
        "requested_target_root": index_state["requested_target_root"],
        "target_matches": index_state["target_matches"],
        "status": "rebuilding" if rebuilding else "updating",
        "matching_jobs": [job.to_dict() for job in matching_jobs],
        "matching_jobs_truncated": matching_jobs_truncated,
    }
    return {
        "ok": False,
        "error": "index_unavailable",
        "message": (
            f"The {source} index for {requested_root} is changing; "
            "this empty search cannot establish that no matches exist."
        ),
        "request_id": request_id,
        "index_state": response_index_state,
        "remediation": [
            server_jobs_command(port, index=source),
            "Retry the search after the matching index job reaches a terminal state.",
        ],
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
    *,
    before_snapshot: Sequence[object],
    after_snapshot: Sequence[object],
    requested_root: Path,
    source: IndexSource,
    request_id: str,
    index_state: Mapping[str, object],
    port: int | None,
) -> SearchResponseClassification | None:
    """Convert a matching collection-disappearance race, or decline it."""
    if not _is_qdrant_collection_disappearance(exc):
        return None
    classification = classify_search_response(
        {"results": []},
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        requested_root=requested_root,
        source=source,
        request_id=request_id,
        index_state=index_state,
        port=port,
    )
    if classification.status_code != 503:
        return None
    return replace(classification, availability_cause="collection_missing")


def classify_search_response(
    result: dict[str, object],
    *,
    before_snapshot: Sequence[object],
    after_snapshot: Sequence[object],
    requested_root: Path,
    source: IndexSource,
    request_id: str,
    index_state: Mapping[str, object],
    port: int | None,
) -> SearchResponseClassification:
    """Classify one response and preserve one bounded before/after evidence set."""
    normalized_root = _normalized_root(requested_root)
    matches = (
        _combined_matches(
            before_snapshot,
            after_snapshot,
            requested_root=normalized_root,
            source=source,
        )
        if normalized_root is not None
        else []
    )
    matching_jobs = tuple(match.to_reference() for match in matches[:_MAX_EXPOSED_JOBS])
    matching_jobs_truncated = len(matches) > _MAX_EXPOSED_JOBS
    rebuilding = any(match.mode == "rebuild" for match in matches)

    results = result.get("results")
    if isinstance(results, list) and not results and matches:
        response = _build_index_unavailable_response(
            requested_root=requested_root,
            source=source,
            request_id=request_id,
            index_state=index_state,
            port=port,
            matching_jobs=matching_jobs,
            matching_jobs_truncated=matching_jobs_truncated,
            rebuilding=rebuilding,
        )
        return SearchResponseClassification(
            response=response,
            status_code=503,
            matching_jobs=matching_jobs,
            matching_jobs_truncated=matching_jobs_truncated,
            rebuilding=rebuilding,
            availability_cause="matching_index_job",
        )
    return SearchResponseClassification(
        response=result,
        status_code=200,
        matching_jobs=matching_jobs,
        matching_jobs_truncated=matching_jobs_truncated,
        rebuilding=rebuilding,
        availability_cause=None,
    )
