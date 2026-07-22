"""Bounded search-availability classification for copied job snapshots."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

__all__ = ["build_index_unavailable_response"]

type IndexSource = Literal["vault", "code"]
type JobMode = Literal["incremental", "rebuild"]

_CANONICAL_NONTERMINAL_STATES = frozenset(
    {"queued", "running", "pausing", "paused", "cancelling"}
)
_MAX_EXPOSED_JOBS = 8


@dataclass(frozen=True, slots=True)
class _MatchingJob:
    """Normalized evidence from one matching convergence job."""

    id: str
    state: str
    mode: JobMode | None

    def to_reference(self) -> dict[str, object]:
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
    return _MatchingJob(
        id=job_id,
        state=state,
        mode=_normalized_mode(spec.get("mode")),
    )


def _compatibility_match(
    record: Mapping[str, object],
    *,
    requested_root: str,
    source: IndexSource,
) -> _MatchingJob | None:
    job_id = record.get("id")
    if not isinstance(job_id, str) or not job_id.strip():
        return None
    if record.get("source") != source or record.get("phase") != "running":
        return None
    initiator = record.get("initiator")
    if not isinstance(initiator, Mapping):
        return None
    initiator_data = cast("Mapping[str, object]", initiator)
    if _normalized_root(initiator_data.get("project_root")) != requested_root:
        return None
    return _MatchingJob(id=job_id, state="running", mode=None)


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
        if "spec" in record:
            spec = record.get("spec")
            if not isinstance(spec, Mapping):
                continue
            spec_data = cast("Mapping[str, object]", spec)
            match = _canonical_match(
                record,
                spec_data,
                requested_root=requested_root,
                source=source,
            )
        else:
            match = _compatibility_match(
                record,
                requested_root=requested_root,
                source=source,
            )
        if match is not None:
            matches.append(match)
    return matches


def _combined_matches(
    before_snapshot: Sequence[object],
    after_snapshot: Sequence[object],
    *,
    requested_root: str,
    source: IndexSource,
) -> list[_MatchingJob]:
    ordered = _matching_jobs(
        after_snapshot,
        requested_root=requested_root,
        source=source,
    )
    ordered.extend(
        _matching_jobs(
            before_snapshot,
            requested_root=requested_root,
            source=source,
        )
    )
    unique: list[_MatchingJob] = []
    seen_ids: set[str] = set()
    for match in ordered:
        if match.id in seen_ids:
            continue
        seen_ids.add(match.id)
        unique.append(match)
    return unique


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
    matches = _combined_matches(
        before_snapshot,
        after_snapshot,
        requested_root=normalized_root,
        source=source,
    )
    if not matches:
        return None

    exposed_matches = matches[:_MAX_EXPOSED_JOBS]
    status = (
        "rebuilding" if any(job.mode == "rebuild" for job in matches) else "updating"
    )
    response_index_state: dict[str, object] = {
        "source": index_state["source"],
        "indexed_count": index_state["indexed_count"],
        "indexed_target_root": index_state["indexed_target_root"],
        "requested_target_root": index_state["requested_target_root"],
        "target_matches": index_state["target_matches"],
        "status": status,
        "matching_jobs": [job.to_reference() for job in exposed_matches],
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
