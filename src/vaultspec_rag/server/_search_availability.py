"""Bounded search-availability classification for canonical job snapshots."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict, cast

__all__ = [
    "build_index_unavailable_response",
    "classify_search_response",
    "matching_index_jobs",
]

type IndexSource = Literal["vault", "code"]
type JobMode = Literal["incremental", "rebuild"]

_CANONICAL_NONTERMINAL_STATES = frozenset(
    {"queued", "running", "pausing", "paused", "cancelling"}
)
_MAX_EXPOSED_JOBS = 8


class MatchingIndexJobReference(TypedDict):
    """Exact public correlation fields for one matching index job."""

    id: str
    state: str
    mode: JobMode


@dataclass(frozen=True, slots=True)
class MatchingIndexJobs:
    """Bounded public evidence from one copied canonical job snapshot."""

    references: tuple[MatchingIndexJobReference, ...]
    truncated: bool
    rebuilding: bool


@dataclass(frozen=True, slots=True)
class _MatchingJob:
    """Normalized evidence from one matching convergence job."""

    id: str
    state: str
    mode: JobMode

    def to_reference(self) -> MatchingIndexJobReference:
        """Return the exact public job-reference shape."""
        return {"id": self.id, "state": self.state, "mode": self.mode}


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


def matching_index_jobs(
    snapshot: Sequence[object],
    *,
    requested_root: Path,
    source: IndexSource,
) -> MatchingIndexJobs:
    """Return bounded exact-job evidence from one canonical observation."""
    normalized_root = _normalized_root(requested_root)
    if normalized_root is None:
        return MatchingIndexJobs(references=(), truncated=False, rebuilding=False)
    matches = _deduplicated_matches(
        _matching_jobs(
            snapshot,
            requested_root=normalized_root,
            source=source,
        )
    )
    return MatchingIndexJobs(
        references=tuple(match.to_reference() for match in matches[:_MAX_EXPOSED_JOBS]),
        truncated=len(matches) > _MAX_EXPOSED_JOBS,
        rebuilding=any(match.mode == "rebuild" for match in matches),
    )


def build_index_unavailable_response(
    *,
    before_snapshot: Sequence[object],
    after_snapshot: Sequence[object],
    requested_root: Path,
    source: IndexSource,
    request_id: str,
    index_state: Mapping[str, object],
    port: int | None,
) -> dict[str, object] | None:
    """Build the exact temporary-unavailability body when either view matches."""
    normalized_root = _normalized_root(requested_root)
    if normalized_root is None:
        return None
    ordered_matches = _matching_jobs(
        after_snapshot,
        requested_root=normalized_root,
        source=source,
    )
    ordered_matches.extend(
        _matching_jobs(
            before_snapshot,
            requested_root=normalized_root,
            source=source,
        )
    )
    matches = _deduplicated_matches(ordered_matches)
    if not matches:
        return None

    response_index_state: dict[str, object] = {
        "source": index_state["source"],
        "indexed_count": index_state["indexed_count"],
        "indexed_target_root": index_state["indexed_target_root"],
        "requested_target_root": index_state["requested_target_root"],
        "target_matches": index_state["target_matches"],
        "status": (
            "rebuilding"
            if any(match.mode == "rebuild" for match in matches)
            else "updating"
        ),
        "matching_jobs": [
            match.to_reference() for match in matches[:_MAX_EXPOSED_JOBS]
        ],
        "matching_jobs_truncated": len(matches) > _MAX_EXPOSED_JOBS,
    }
    port_suffix = f" --port {port}" if port is not None else ""
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
            f"vaultspec-rag server jobs --state active --index {source}{port_suffix}",
            "Retry the search after the matching index job reaches a terminal state.",
        ],
    }


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
) -> tuple[dict[str, object], int]:
    """Classify one successful search body without suppressing usable results."""
    results = result.get("results")
    if not isinstance(results, list) or results:
        return result, 200

    unavailable = build_index_unavailable_response(
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        requested_root=requested_root,
        source=source,
        request_id=request_id,
        index_state=index_state,
        port=port,
    )
    if unavailable is not None:
        return unavailable, 503
    return result, 200
