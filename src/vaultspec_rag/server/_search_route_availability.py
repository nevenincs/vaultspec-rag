"""Index-state construction and availability classification for search routes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from anyio.to_thread import run_sync as _run_in_thread
from qdrant_client.http.exceptions import UnexpectedResponse

from .._operator_commands import (
    IndexCommandOptions,
    index_command,
    server_jobs_command,
    server_status_command,
)
from .._search_state import (
    AbsenceAuthority,
    FreshnessWaitPolicy,
    SearchSourceFact,
    search_readiness_block,
)
from .._source_types import INDEX_SOURCES, IndexSource, PublicSourceType
from ..concurrency import get_search_limiter
from ._search_availability import (
    CanonicalSearchEvidence,
    SearchAvailabilityContext,
    SearchResponseClassification,
    classify_qdrant_collection_disappearance,
    classify_search_response,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from .._index_integrity import IndexIntegrity
    from ..service import ServiceRegistry
    from ._routes_search import SearchRequest
    from ._search_readiness import PublicationTarget, ReadinessRevisionSnapshot


@dataclass(frozen=True, slots=True)
class SearchIndexStateInput:
    """Measurements required to render the canonical index-state block."""

    indexed_count: int | float
    requested_root: object
    search_type: PublicSourceType | str
    published_points: float | None = None
    named_files: float | None = None
    covered_files: float | None = None
    integrity: IndexIntegrity | None = None
    integrity_repair_job_id: str | None = None
    #: Path of every result on the page, in rank order. Empty on the routes
    #: that build a block without having searched, where there is nothing to
    #: judge and the collapse signal correctly stays silent.
    result_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchAvailabilityRequestFacts:
    """Stable pre-retrieval request facts used while classifying availability.

    Deliberately a different type from
    :class:`~._search_availability.SearchAvailabilityContext`, not a second
    spelling of it: these are the facts fixed before retrieval runs, while the
    context additionally carries the after-retrieval job snapshot and the
    index-state block. Both of those exist only once retrieval has finished,
    and the index-state block differs between the completed-search and
    vanished-collection call sites, so the two cannot share one lifetime.

    ``source`` names one concrete corpus. The ``combined`` fan-out has no
    single index to classify against and never builds these facts at all.
    """

    job_snapshot_before: list[dict[str, object]]
    root: Path
    source: IndexSource
    request_id: str
    port: int | None
    readiness_snapshot: ReadinessRevisionSnapshot | None = None
    readiness_target: PublicationTarget | None = None
    wait_policy: FreshnessWaitPolicy = FreshnessWaitPolicy.IMMEDIATE

    def __post_init__(self) -> None:
        """Refuse a source no index job can ever be recorded against.

        The declared type already excludes the fan-out and the checker enforces
        it at the one construction site. This costs one set membership test per
        classified search and closes the gap that type alone leaves: a value
        arriving through ``object``, ``Any``, or an untyped test helper reaches
        the field unchecked, and the failure it causes is a silent misroute -
        the classifier compares this against a job spec's own source, matches
        nothing, and reports a healthy index for one that is mid-rebuild.
        """
        if self.source not in INDEX_SOURCES:
            raise ValueError(
                f"search availability facts require one concrete index source, "
                f"got {self.source!r}; the combined fan-out has no single index "
                f"to classify against"
            )

    def to_context(
        self,
        *,
        after_snapshot: list[dict[str, object]],
        index_state: dict[str, object],
    ) -> SearchAvailabilityContext:
        """Complete these facts with the evidence retrieval has since produced."""
        integrity = index_state.get("index_integrity")
        integrity_block = (
            cast("dict[str, object]", integrity)
            if isinstance(integrity, dict)
            else None
        )
        integrity_verified = (
            integrity_block is not None
            and integrity_block.get("verdict") == "consistent"
        )
        snapshot = self.readiness_snapshot
        target = self.readiness_target
        return SearchAvailabilityContext(
            before_snapshot=self.job_snapshot_before,
            after_snapshot=after_snapshot,
            requested_root=self.root,
            source=self.source,
            request_id=self.request_id,
            index_state=index_state,
            port=self.port,
            canonical_evidence=CanonicalSearchEvidence(
                served_generation=(
                    snapshot.published_generation if snapshot is not None else None
                ),
                desired_generation=(
                    target.generation
                    if target is not None
                    else snapshot.desired_generation
                    if snapshot is not None
                    else None
                ),
                publication_revision=(
                    snapshot.publication_revision if snapshot is not None else None
                ),
                desired_revision=(
                    target.revision
                    if target is not None
                    else snapshot.controller_revision
                    if snapshot is not None
                    else None
                ),
                collection_present=True,
                target_matches=index_state.get("target_matches") is True,
                integrity_verified=integrity_verified,
            ),
        )


def search_index_state_for_route(input: SearchIndexStateInput) -> dict[str, object]:
    """Adapt this route's carried figures onto the service-domain block.

    The route owns no part of the shape. It converts the published-point
    figure it carries on the timing channel back into the shortfall the
    domain builder expects, and renders whatever that returns.
    """
    from .._index_breadth import BreadthShortfall, FileBreadthShortfall
    from .._search_state import BreadthFindings, result_collapse, search_index_state

    count = int(input.indexed_count)
    shortfall = (
        None
        if input.published_points is None
        else BreadthShortfall(published=int(input.published_points), live=count)
    )
    file_shortfall = (
        None
        if input.named_files is None or input.covered_files is None
        else FileBreadthShortfall(
            named=int(input.named_files), covered=int(input.covered_files)
        )
    )
    return search_index_state(
        indexed_count=count,
        requested_root=input.requested_root,
        search_type=input.search_type,
        findings=BreadthFindings(
            shortfall=shortfall,
            file_shortfall=file_shortfall,
            integrity=input.integrity,
            integrity_repair_job_id=input.integrity_repair_job_id,
            collapse=result_collapse(input.result_paths),
        ),
    )


def search_integrity_for_route(
    request: SearchRequest,
    phase_timing: dict[str, float],
) -> tuple[IndexIntegrity, str | None]:
    """Settle the serve-time breadth verdict for one dispatched search.

    Single-domain searches reconcile their own domain against the count the
    dispatch already took. A combined search reconciles the code domain,
    mirroring how the combined envelope already carries the code shortfall: it
    is the domain with the richest published claim, and its per-domain count
    travels on the timing channel. A domain whose count never landed there -
    a failed combined leg - yields ``unverifiable``, never a claim of zero.

    The verdict is also handed to the remediation registry here - the one
    service-side seam every daemon search passes through - so a demonstrated
    shrink turns into at most one supervised repair, whose job id (when known)
    rides back on the envelope beside the verdict that motivated it.
    """
    from .._index_integrity import evaluate_index_integrity
    from .._integrity_remediation import note_integrity_verdict
    from ..store_runtime import configured_backend_identity

    backend_identity = configured_backend_identity(request.root)

    if request.search_type is PublicSourceType.COMBINED:
        code_count = phase_timing.get("code_indexed_count")
        source = PublicSourceType.CODE
        integrity = evaluate_index_integrity(
            request.root,
            source,
            None if code_count is None else int(code_count),
            backend_identity=backend_identity,
        )
    else:
        source = request.search_type
        integrity = evaluate_index_integrity(
            request.root,
            source,
            int(phase_timing["indexed_count"]),
            backend_identity=backend_identity,
        )
    repair_job_id = note_integrity_verdict(request.root, source, integrity.verdict)
    return integrity, repair_job_id


def _empty_search_diagnostics(
    index_state: dict[str, object],
    *,
    port: int | None,
    path_filter: dict[str, object] | None = None,
) -> dict[str, object]:
    source = index_state["source"]
    remediation = [
        index_command(source, IndexCommandOptions(port=port)),
        server_status_command(),
        server_jobs_command(port),
    ]
    if index_state["indexed_count"] == 0:
        reason = "index_missing"
        message = f"No indexed {source} items are available."
    elif path_filter is not None:
        # The search proved this: candidates matched the query and the path
        # patterns removed every one. Saying so, with the patterns, is the
        # difference between a fixable typo and an operator concluding the
        # filter is unsupported. "patterns" is always a list: the search
        # response builds it from the normalized include-glob patterns.
        patterns = ", ".join(
            str(p) for p in cast("list[object]", path_filter["patterns"])
        )
        reason = "no_match_path_filter"
        message = (
            f"{path_filter['candidates_before_filter']} indexed items matched "
            f"the query, and the path filter ({patterns}) excluded every one. "
            "Patterns match project-relative paths; a plain pattern matches "
            "that path and everything under it."
        )
        remediation = [
            "rerun without the path filter to see what the query matches",
            "widen the pattern, or check it against a path from an unfiltered result",
        ]
    else:
        reason = "no_match"
        message = "The index is available, but no indexed item matched the query."

    return {
        "reason": reason,
        "message": message,
        "remediation": remediation,
    }


def classify_search_result(
    result: dict[str, object],
    facts: SearchAvailabilityRequestFacts,
) -> SearchResponseClassification:
    """Apply availability classification and stable-empty diagnostics."""
    from ._routes import canonical_job_snapshot

    # A completed search always builds "index_state" from search_index_state(),
    # which returns a dict; absent means the envelope never carried a search
    # outcome (the quiesce/collection-disappearance synthetic results), which
    # the default covers.
    index_state = cast("dict[str, object]", result.get("index_state", {}))
    classification = classify_search_response(
        result,
        facts.to_context(
            after_snapshot=canonical_job_snapshot(),
            index_state=index_state,
        ),
    )
    source_fact = replace(
        classification.source_fact,
        wait_policy=facts.wait_policy,
    )
    classification = replace(classification, source_fact=source_fact)
    results = classification.response.get("results")
    if classification.status_code == 200 and isinstance(results, list) and not results:
        if source_fact.absence_authority is not AbsenceAuthority.AUTHORITATIVE:
            failure = _non_authoritative_empty_result(
                classification.response,
                source_fact=source_fact,
                request_id=facts.request_id,
            )
            return replace(classification, response=failure, status_code=503)
        raw_path_filter = classification.response.get("path_filter")
        classification.response["empty"] = _empty_search_diagnostics(
            index_state,
            port=facts.port,
            path_filter=cast("dict[str, object]", raw_path_filter)
            if isinstance(raw_path_filter, dict)
            else None,
        )
    if classification.status_code == 200:
        classification.response["readiness"] = _readiness_block(source_fact)
    return classification


def readiness_snapshot(
    registry: ServiceRegistry,
    root: Path,
    source: IndexSource,
) -> ReadinessRevisionSnapshot | None:
    """Read canonical evidence when this runtime owns a readiness lifetime."""
    from ._search_readiness import ReadinessRegistryClosedError

    try:
        readiness = registry.readiness_registry
    except RuntimeError as exc:
        if str(exc) != "readiness registry is not started":
            raise
        return None
    try:
        return readiness.snapshot(root, source)
    except ReadinessRegistryClosedError:
        return None


def _readiness_block(source_fact: SearchSourceFact) -> dict[str, object]:
    """Serialize one canonical source fact and its derived aggregate."""
    return search_readiness_block((source_fact,))


def _non_authoritative_empty_result(
    result: dict[str, object],
    *,
    source_fact: SearchSourceFact,
    request_id: str,
) -> dict[str, object]:
    """Suppress an empty result list that cannot prove absence."""
    stable_error = (
        source_fact.reason_code
        if source_fact.reason_code
        in {
            "index_unavailable",
            "index_unverifiable",
            "rebuild_required",
            "capacity_limited",
        }
        else "index_unverifiable"
    )
    return {
        key: value
        for key, value in result.items()
        if key not in {"results", "summary", "empty"}
    } | {
        "ok": False,
        "error": stable_error,
        "message": "The empty search result is not authoritative for this source.",
        "retryable": source_fact.retryable,
        "request_id": request_id,
        "readiness": _readiness_block(source_fact),
        "remediation": source_fact.remediation,
    }


def _classify_collection_disappearance(
    exc: UnexpectedResponse,
    facts: SearchAvailabilityRequestFacts,
) -> SearchResponseClassification | None:
    """Classify one instantaneous missing-collection search observation."""
    from .._index_integrity import evaluate_index_integrity
    from ..store_runtime import configured_backend_identity
    from ._routes import canonical_job_snapshot

    return classify_qdrant_collection_disappearance(
        exc,
        facts.to_context(
            after_snapshot=canonical_job_snapshot(),
            index_state=search_index_state_for_route(
                SearchIndexStateInput(
                    indexed_count=0,
                    requested_root=facts.root,
                    # The collection vanished mid-flight, so there is no live
                    # count to reconcile: the verdict is honestly unverifiable,
                    # and carrying it keeps the daemon envelope uniform - every
                    # route response has the block, so absence still means only
                    # "old daemon".
                    integrity=evaluate_index_integrity(
                        facts.root,
                        PublicSourceType(facts.source),
                        None,
                        backend_identity=configured_backend_identity(facts.root),
                    ),
                    search_type=facts.source,
                )
            ),
        ),
    )


async def run_search_with_availability(
    run: Callable[[], dict[str, object]],
    facts: SearchAvailabilityRequestFacts,
) -> tuple[dict[str, object], SearchResponseClassification | None]:
    """Run retrieval and recover only an evidenced collection disappearance."""
    try:
        return await _run_in_thread(run, limiter=get_search_limiter()), None
    except UnexpectedResponse as exc:
        classification = _classify_collection_disappearance(
            exc,
            facts,
        )
        if classification is None:
            raise
        return classification.response, classification
