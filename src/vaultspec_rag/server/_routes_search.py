"""The ``POST /search`` route: dispatch, availability classification, timing.

Owns everything specific to serving one search request: canonical-source
dispatch (``vault``/``code``/``document``/``combined``), the index-state and
summary shaping a response carries, empty-result diagnostics, and the
availability classification that recovers an instantaneous missing-collection
observation into a stable 503 rather than surfacing a raw client exception.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, cast

from anyio.to_thread import run_sync as _run_in_thread
from qdrant_client.http.exceptions import UnexpectedResponse
from starlette.responses import JSONResponse

import vaultspec_rag.server as _m

from .._operator_commands import (
    IndexCommandOptions,
    index_command,
    server_jobs_command,
    server_status_command,
)
from .._source_types import (
    INDEX_SOURCES,
    IndexSource,
    PublicSourceType,
    SourceTypeParseError,
    parse_source_type,
    unsupported_feedback_envelope,
)
from .._store_locks import VaultStoreLockedError
from ..concurrency import get_search_limiter
from ..logging_config import log_event
from ..search._result_shaping import (
    PHASE_EMBEDDING,
    PHASE_MODEL_LOAD,
    PHASE_POSTPROCESS,
    PHASE_PROJECT_LEASE,
    PHASE_QDRANT,
    PHASE_RERANK,
)
from ..service import RegistryFullError
from ._auth import require_token
from ._search_activity import (
    SearchActivityCompletion,
    SearchActivityStart,
    SearchActivityTicket,
)
from ._search_availability import (
    SearchResponseClassification,
    classify_qdrant_collection_disappearance,
    classify_search_response,
)
from ._state import search_activity_ledger
from ._utils import (
    _BAD_REQUEST_MISSING_ROOT,
    ProjectRootRequiredError,
    _clamp_top_k,
    _resolve_root,
    _validate_query,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from starlette.requests import Request

    from .._index_integrity import IndexIntegrity
logger = logging.getLogger("vaultspec_rag.server")

__all__ = ["search_route"]

_BAD_REQUEST_EMPTY_QUERY = JSONResponse(
    {
        "ok": False,
        "error": "bad_request",
        "message": (
            "query is empty - supply search text, or filter tokens such as "
            "'lang:python class:Engine' when searching by metadata alone."
        ),
    },
    status_code=400,
)


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


@dataclass(frozen=True, slots=True)
class SearchAvailabilityContext:
    """Stable request facts used while classifying search availability."""

    job_snapshot_before: list[dict[str, object]]
    root: Path
    source: IndexSource
    request_id: str
    port: int | None


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Normalized user input for one search execution."""

    root: Path
    query: str
    top_k: int
    payload: dict[str, Any]
    search_type: PublicSourceType
    request_id: str


@dataclass(frozen=True, slots=True)
class SearchRouteError:
    """A validation response and the review metadata that explains it."""

    response: JSONResponse
    error_code: str
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class SearchRouteResult:
    """One completed search response and its bounded-review measurements."""

    result: dict[str, object]
    status_code: int
    total_seconds: float
    availability_cause: str | None


@dataclass(slots=True)
class SearchActivityFinalization:
    """Mutable route-local state finalized exactly once at route exit."""

    result: dict[str, object] | None = None
    status_code: int = 500
    total_seconds: float | None = None
    outcome: str | None = None
    availability_cause: str | None = None
    error_code: str | None = "unhandled_search_route_exception"
    error_message: str | None = None


def _bad_request_invalid_root(exc: ValueError) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "error": "bad_request",
            "message": str(exc),
        },
        status_code=400,
    )


def _normalise_search_type(value: object) -> PublicSourceType | JSONResponse:
    try:
        return parse_source_type(value, allow_aliases=False)
    except SourceTypeParseError as exc:
        return JSONResponse(exc.as_error_envelope(), status_code=400)


def _unsupported_search_feedback(
    search_type: PublicSourceType,
    payload: dict[str, object],
) -> JSONResponse | None:
    """Reject feedback where no cross-collection identity contract exists."""
    envelope = unsupported_feedback_envelope(
        search_type,
        has_point_ids=bool(payload.get("like_ids") or payload.get("unlike_ids")),
    )
    if envelope is None:
        return None
    return JSONResponse(envelope, status_code=400)


def _search_index_state(input: SearchIndexStateInput) -> dict[str, object]:
    """Adapt this route's carried figures onto the service-domain block.

    The route owns no part of the shape. It converts the published-point
    figure it carries on the timing channel back into the shortfall the
    domain builder expects, and renders whatever that returns.
    """
    from .._index_breadth import BreadthShortfall, FileBreadthShortfall
    from .._search_state import BreadthFindings, search_index_state

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
        ),
    )


def _search_integrity(
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

    if request.search_type is PublicSourceType.COMBINED:
        code_count = phase_timing.get("code_indexed_count")
        source = PublicSourceType.CODE
        integrity = evaluate_index_integrity(
            request.root,
            source,
            None if code_count is None else int(code_count),
        )
    else:
        source = request.search_type
        integrity = evaluate_index_integrity(
            request.root,
            source,
            int(phase_timing["indexed_count"]),
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
        # filter is unsupported.
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


def _classify_search_result(
    result: dict[str, object],
    context: SearchAvailabilityContext,
) -> SearchResponseClassification:
    """Apply availability classification and stable-empty diagnostics."""
    from ._routes import canonical_job_snapshot

    index_state = cast("dict[str, object]", result.get("index_state", {}))
    classification = classify_search_response(
        result,
        before_snapshot=context.job_snapshot_before,
        after_snapshot=canonical_job_snapshot(),
        requested_root=context.root,
        source=context.source,
        request_id=context.request_id,
        index_state=index_state,
        port=context.port,
    )
    if classification.status_code == 200 and not classification.response["results"]:
        raw_path_filter = classification.response.get("path_filter")
        classification.response["empty"] = _empty_search_diagnostics(
            index_state,
            port=context.port,
            path_filter=cast("dict[str, object]", raw_path_filter)
            if isinstance(raw_path_filter, dict)
            else None,
        )
    return classification


def _classify_collection_disappearance(
    exc: UnexpectedResponse,
    context: SearchAvailabilityContext,
) -> SearchResponseClassification | None:
    """Classify one instantaneous missing-collection search observation."""
    from .._index_integrity import evaluate_index_integrity
    from ._routes import canonical_job_snapshot

    return classify_qdrant_collection_disappearance(
        exc,
        before_snapshot=context.job_snapshot_before,
        after_snapshot=canonical_job_snapshot(),
        requested_root=context.root,
        source=context.source,
        request_id=context.request_id,
        index_state=_search_index_state(
            SearchIndexStateInput(
                indexed_count=0,
                requested_root=context.root,
                # The collection vanished mid-flight, so there is no live
                # count to reconcile: the verdict is honestly unverifiable,
                # and carrying it keeps the daemon envelope uniform - every
                # route response has the block, so absence still means only
                # "old daemon".
                integrity=evaluate_index_integrity(
                    context.root,
                    PublicSourceType(context.source),
                    None,
                ),
                search_type=context.source,
            )
        ),
        port=context.port,
    )


async def _run_search_with_availability(
    run: Callable[[], dict[str, object]],
    context: SearchAvailabilityContext,
) -> tuple[dict[str, object], SearchResponseClassification | None]:
    """Run retrieval and recover only an evidenced collection disappearance."""
    try:
        return await _run_in_thread(run, limiter=get_search_limiter()), None
    except UnexpectedResponse as exc:
        classification = _classify_collection_disappearance(
            exc,
            context,
        )
        if classification is None:
            raise
        return classification.response, classification


def _complete_classified_search(
    classification: SearchResponseClassification,
    *,
    root: Path,
    source: IndexSource,
    request_id: str,
    total_seconds: float,
) -> tuple[dict[str, object], Literal[200, 503]]:
    """Complete watcher and log effects from one classification decision."""
    result = classification.response
    response_status = classification.status_code
    _m._ensure_watcher_soon(root)
    hits = result.get("results")
    hit_count = len(cast("list[object]", hits)) if isinstance(hits, list) else 0
    unavailable = response_status == 503 and result.get("error") == "index_unavailable"
    log_event(
        logger,
        "service.search",
        "unavailable" if unavailable else "completed",
        fields={
            "status_code": response_status,
            **({"error": "index_unavailable"} if unavailable else {}),
            **(
                {"availability_cause": classification.availability_cause}
                if classification.availability_cause is not None
                else {}
            ),
            "request_id": request_id,
            "source": source,
            "search_type": source,
            "root": root,
            "results": hit_count,
            "matching_index_jobs": len(classification.matching_jobs),
            "matching_index_job_ids": ",".join(
                job.id for job in classification.matching_jobs
            ),
            "matching_index_jobs_truncated": classification.matching_jobs_truncated,
            "total_seconds": f"{total_seconds:.3f}",
        },
    )
    return result, response_status


def _activity_timings(
    result: dict[str, object],
    total_seconds: float,
) -> dict[str, object]:
    """Extract scalar route and phase timing without retaining a result body."""
    timings: dict[str, object] = {"server_total_seconds": total_seconds}
    timing = result.get("timing")
    if not isinstance(timing, dict):
        return timings
    timing_values = cast("dict[object, object]", timing)
    for key, value in timing_values.items():
        if key != "phases":
            timings[str(key)] = value
    phases = timing_values.get("phases")
    if isinstance(phases, dict):
        phase_values = cast("dict[object, object]", phases)
        timings.update({str(key): value for key, value in phase_values.items()})
    return timings


def _activity_outcome(result: dict[str, object], status_code: int) -> str:
    """Classify one terminal response for bounded activity review."""
    error = result.get("error")
    if error == "index_unavailable":
        return "unavailable"
    if error == "combined_search_failed":
        return "combined_failed"
    if error in ("registry_full", "local_store_locked"):
        return "admission_failed"
    if status_code >= 500 or error is not None:
        return "failed"
    return "partial_success" if result.get("partial") is True else "success"


def _finish_search_activity(
    ticket: SearchActivityTicket,
    finalization: SearchActivityFinalization,
) -> None:
    """Converge every route exit on the process-owned ledger terminal write."""
    body = finalization.result or {}
    hits = body.get("results")
    count = len(cast("list[object]", hits)) if isinstance(hits, list) else None
    resolved_status = finalization.status_code
    resolved_outcome = finalization.outcome or _activity_outcome(body, resolved_status)
    resolved_error = finalization.error_code
    if resolved_error is None:
        raw_error = body.get("error")
        resolved_error = raw_error if isinstance(raw_error, str) else None
    resolved_message = finalization.error_message
    if resolved_message is None:
        raw_message = body.get("message")
        resolved_message = raw_message if isinstance(raw_message, str) else None
    timings = (
        _activity_timings(body, finalization.total_seconds)
        if finalization.total_seconds is not None
        else None
    )
    search_activity_ledger().finish(
        ticket,
        completion=SearchActivityCompletion(
            outcome=resolved_outcome,
            status_code=resolved_status,
            result_count=count,
            timings=timings,
            availability_cause=finalization.availability_cause,
            error_code=resolved_error,
            error_message=resolved_message,
        ),
    )


def _dispatch_public_search(
    request: SearchRequest,
    notes: dict[str, object],
) -> tuple[list[Any], dict[str, float], Any | None]:
    """Dispatch one canonical source without adapter fallback."""
    import vaultspec_rag

    from .._public_search import (
        CodeCombinedSearchFilters,
        CombinedSearchRequest,
        DocumentCombinedSearchFilters,
        DocumentSearchRequest,
        VaultCombinedSearchFilters,
    )
    from ..api import CodebaseSearchRequest, VaultSearchRequest

    if request.search_type is PublicSourceType.VAULT:
        results, timings = vaultspec_rag.search_vault_timed(
            VaultSearchRequest(
                root_dir=request.root,
                query=request.query,
                top_k=request.top_k,
                doc_type=request.payload.get("doc_type"),
                feature=request.payload.get("feature"),
                date=request.payload.get("date"),
                tag=request.payload.get("tag"),
                intent=request.payload.get("intent"),
                like_ids=request.payload.get("like_ids"),
                unlike_ids=request.payload.get("unlike_ids"),
            )
        )
        return results, timings, None
    if request.search_type is PublicSourceType.CODE:
        results, timings = vaultspec_rag.search_codebase_timed(
            CodebaseSearchRequest(
                root_dir=request.root,
                query=request.query,
                top_k=request.top_k,
                language=request.payload.get("language"),
                path=request.payload.get("path"),
                node_type=request.payload.get("node_type"),
                function_name=request.payload.get("function_name"),
                class_name=request.payload.get("class_name"),
                include_paths=request.payload.get("include_paths"),
                exclude_paths=request.payload.get("exclude_paths"),
                dedup_locales=request.payload.get("dedup_locales"),
                prefer=request.payload.get("prefer"),
                exclude_domains=request.payload.get("exclude_domains"),
                only_domains=request.payload.get("only_domains"),
                include_domains=request.payload.get("include_domains"),
                like_ids=request.payload.get("like_ids"),
                unlike_ids=request.payload.get("unlike_ids"),
                notes=notes,
            )
        )
        return results, timings, None
    if request.search_type is PublicSourceType.DOCUMENT:
        results, timings = vaultspec_rag.search_documents_timed(
            DocumentSearchRequest(
                root_dir=request.root,
                query=request.query,
                top_k=request.top_k,
                source_path=request.payload.get("source_path"),
                extractor_id=request.payload.get("extractor_id"),
                extractor_version=request.payload.get("extractor_version"),
                locator_kind=request.payload.get("locator_kind"),
            )
        )
        return results, timings, None
    combined, timings = vaultspec_rag.search_combined_timed(
        CombinedSearchRequest(
            root_dir=request.root,
            query=request.query,
            top_k=request.top_k,
            vault_filters=VaultCombinedSearchFilters(
                doc_type=request.payload.get("doc_type"),
                feature=request.payload.get("feature"),
                date=request.payload.get("date"),
                tag=request.payload.get("tag"),
                intent=request.payload.get("intent"),
            ),
            code_filters=CodeCombinedSearchFilters(
                language=request.payload.get("language"),
                path=request.payload.get("path"),
                node_type=request.payload.get("node_type"),
                function_name=request.payload.get("function_name"),
                class_name=request.payload.get("class_name"),
                include_paths=tuple(request.payload.get("include_paths") or ()),
                exclude_paths=tuple(request.payload.get("exclude_paths") or ()),
                dedup_locales=request.payload.get("dedup_locales"),
                prefer=request.payload.get("prefer"),
                exclude_domains=tuple(request.payload.get("exclude_domains") or ()),
                only_domains=tuple(request.payload.get("only_domains") or ()),
                include_domains=tuple(request.payload.get("include_domains") or ()),
            ),
            document_filters=DocumentCombinedSearchFilters(
                source_path=request.payload.get("source_path"),
                extractor_id=request.payload.get("extractor_id"),
                extractor_version=request.payload.get("extractor_version"),
                locator_kind=request.payload.get("locator_kind"),
            ),
        )
    )
    return combined.results, timings, combined


def _execute_search_request(request: SearchRequest) -> dict[str, object]:
    """Execute and serialize one search off the event loop."""
    try:
        notes: dict[str, object] = {}
        phase_started = time.perf_counter()
        results, phase_timing, combined = _dispatch_public_search(request, notes)
        search_seconds = time.perf_counter() - phase_started
        phase_started = time.perf_counter()
        indexed_count = (
            sum(
                int(phase_timing.get(f"{source}_indexed_count", 0.0))
                for source in INDEX_SOURCES
            )
            if request.search_type is PublicSourceType.COMBINED
            else int(phase_timing["indexed_count"])
        )
        integrity, integrity_repair_job_id = _search_integrity(request, phase_timing)
        index_state = _search_index_state(
            SearchIndexStateInput(
                indexed_count=indexed_count,
                requested_root=request.root,
                search_type=request.search_type,
                published_points=phase_timing.get("published_points"),
                named_files=phase_timing.get("named_files"),
                covered_files=phase_timing.get("covered_files"),
                integrity=integrity,
                integrity_repair_job_id=integrity_repair_job_id,
            )
        )
        index_state_seconds = time.perf_counter() - phase_started
        phase_started = time.perf_counter()
        from ._models import SearchResultItem
        from ._routes import search_summary

        items = [
            SearchResultItem.model_validate(result, from_attributes=True).model_dump(
                mode="json"
            )
            for result in results
        ]
        response: dict[str, object] = {
            "request_id": request.request_id,
            "results": items,
            "summary": search_summary(len(results), index_state),
            "filtered": notes.get("dropped_domains"),
            "path_filter": notes.get("path_filter"),
            "timing": {
                "index_state_seconds": index_state_seconds,
                "search_seconds": search_seconds,
                "embedding_seconds": phase_timing.get(PHASE_EMBEDDING),
                "qdrant_seconds": phase_timing.get(PHASE_QDRANT),
                "rerank_seconds": phase_timing.get(PHASE_RERANK),
                "postprocess_seconds": phase_timing.get(PHASE_POSTPROCESS),
                # Promoted alongside the phases above, not nested only. A
                # reshape of this dict carried the other phase keys up and left
                # these two reachable solely through "phases", which silently
                # broke the diagnostic contract a consumer reads to tell a cold
                # model load apart from a slow query.
                "model_load_seconds": phase_timing.get(PHASE_MODEL_LOAD),
                "project_lease_seconds": phase_timing.get(PHASE_PROJECT_LEASE),
                "serialization_seconds": time.perf_counter() - phase_started,
                "queue_wait_seconds": phase_timing.get("queue_wait_seconds", 0.0),
                "timing_scope": "server_route",
                "phases": phase_timing,
            },
            "index_state": index_state,
        }
        if combined is not None:
            response["ok"] = combined.ok
            response["partial"] = combined.partial
            response["domains"] = combined.domain_status_payload()
            if not combined.ok:
                response.update(
                    {
                        "error": "combined_search_failed",
                        "message": "Every combined-search domain failed.",
                        "summary": "Combined search failed in every domain.",
                    }
                )
        return response
    except RegistryFullError as exc:
        return _m._registry_full_error_dict(exc)
    except VaultStoreLockedError as exc:
        return _m._local_store_locked_error_dict(exc)


async def search_route(request: Request) -> JSONResponse:
    """Authenticate then dispatch one normalized search request."""
    denied = require_token(request)
    if denied is not None:
        return denied
    return await _search_route_response(request)


async def _search_payload(request: Request) -> dict[str, object] | SearchRouteError:
    """Read the request body into the one shape the route accepts."""
    try:
        payload = await request.json()
    except Exception as exc:
        return SearchRouteError(
            JSONResponse(
                {
                    "ok": False,
                    "error": "bad_request",
                    "message": "search request body must be valid JSON",
                },
                status_code=400,
            ),
            error_code="invalid_json",
            error_message=str(exc),
        )
    if isinstance(payload, dict):
        return cast("dict[str, object]", payload)
    return SearchRouteError(
        JSONResponse(
            {
                "ok": False,
                "error": "bad_request",
                "message": "search request body must be a JSON object",
            },
            status_code=400,
        ),
        error_code="bad_request",
        error_message="search request body must be a JSON object",
    )


def _record_provisional_activity(
    ticket: SearchActivityTicket,
    payload: dict[str, object],
) -> None:
    """Write inspectable request fields before validation refines them."""
    raw_query = payload.get("query", "")
    raw_search_type = payload.get("type", "vault")
    raw_top_k = payload.get("top_k", 5)
    raw_root = payload.get("project_root")
    search_activity_ledger().update_request(
        ticket,
        query=raw_query if isinstance(raw_query, str) else "",
        search_type=raw_search_type if isinstance(raw_search_type, str) else "unknown",
        root=raw_root if isinstance(raw_root, str) else None,
        top_k=(
            raw_top_k
            if isinstance(raw_top_k, int) and not isinstance(raw_top_k, bool)
            else None
        ),
    )


def _normalise_search_request(
    payload: dict[str, object],
    request_id: str,
) -> SearchRequest | SearchRouteError:
    """Validate public payload data and form the dispatched search request."""
    search_type = _normalise_search_type(payload.get("type", "vault"))
    if isinstance(search_type, JSONResponse):
        return SearchRouteError(search_type, error_code="bad_request")
    unsupported_feedback = _unsupported_search_feedback(search_type, payload)
    if unsupported_feedback is not None:
        return SearchRouteError(unsupported_feedback, error_code="unsupported_feedback")
    query = payload.get("query", "")
    top_k = payload.get("top_k", 5)
    project_root = payload.get("project_root")
    field_error = _search_field_error(query, top_k, project_root)
    if field_error is not None:
        return field_error
    query = _validate_query(cast("str", query))
    if not query.strip():
        return SearchRouteError(
            _BAD_REQUEST_EMPTY_QUERY,
            error_code="bad_request",
            error_message="query is empty",
        )
    root = _search_root(project_root)
    if isinstance(root, SearchRouteError):
        return root
    return SearchRequest(
        root=root,
        query=query,
        top_k=_clamp_top_k(cast("int", top_k)),
        payload=cast("dict[str, Any]", payload),
        search_type=search_type,
        request_id=request_id,
    )


def _search_field_error(
    query: object,
    top_k: object,
    project_root: object,
) -> SearchRouteError | None:
    """Return the first scalar request-shape error, if any."""
    if not isinstance(query, str):
        return _bad_search_field("invalid_query", "query must be a string")
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        return _bad_search_field("invalid_top_k", "top_k must be an integer")
    if project_root is not None and not isinstance(project_root, str):
        return _bad_search_field(
            "invalid_project_root", "project_root must be a string"
        )
    return None


def _bad_search_field(error_code: str, message: str) -> SearchRouteError:
    """Build one client-visible scalar validation failure."""
    return SearchRouteError(
        JSONResponse(
            {"ok": False, "error": "bad_request", "message": message},
            status_code=400,
        ),
        error_code=error_code,
        error_message=message,
    )


def _search_root(project_root: object) -> Path | SearchRouteError:
    """Resolve the validated root while preserving the established envelopes."""
    try:
        return _resolve_root(cast("str | None", project_root))
    except ProjectRootRequiredError:
        return SearchRouteError(
            _BAD_REQUEST_MISSING_ROOT,
            error_code="bad_request",
            error_message="project_root is required",
        )
    except ValueError as exc:
        return SearchRouteError(
            _bad_request_invalid_root(exc),
            error_code="bad_request",
            error_message=str(exc),
        )


def _record_normalized_activity(
    ticket: SearchActivityTicket,
    search_request: SearchRequest,
) -> None:
    """Replace provisional activity metadata with validated request facts."""
    search_activity_ledger().update_request(
        ticket,
        query=search_request.query,
        search_type=search_request.search_type.value,
        root=str(search_request.root),
        top_k=search_request.top_k,
    )


def _record_validation_rejection(
    finalization: SearchActivityFinalization,
    error: SearchRouteError,
) -> None:
    """Set the single terminal review state for a rejected request."""
    finalization.status_code = error.response.status_code
    finalization.outcome = "validation_rejected"
    finalization.error_code = error.error_code
    finalization.error_message = error.error_message


async def _execute_search_route(
    search_request: SearchRequest,
    port: int | None,
) -> SearchRouteResult:
    """Run, classify, and record the public response for one valid search."""
    from ._routes import canonical_job_snapshot

    availability_context = SearchAvailabilityContext(
        job_snapshot_before=canonical_job_snapshot(),
        root=search_request.root,
        source=cast(
            'Literal["vault", "code", "document"]', search_request.search_type.value
        ),
        request_id=search_request.request_id,
        port=port,
    )
    run = partial(_execute_search_request, search_request)
    started = time.perf_counter()
    if search_request.search_type is PublicSourceType.COMBINED:
        result = await _run_in_thread(run, limiter=get_search_limiter())
        classification = None
    else:
        result, classification = await _run_search_with_availability(
            run,
            availability_context,
        )
    total_seconds = time.perf_counter() - started
    _m.incr("search_total")
    _m.observe("search_last_duration_seconds", total_seconds)
    response_status = _search_response_status(search_request, result)
    classification = _classify_completed_search(
        result,
        search_request,
        availability_context,
        classification,
        total_seconds,
    )
    if classification is not None:
        result, response_status = _complete_classified_search(
            classification,
            root=search_request.root,
            source=availability_context.source,
            request_id=search_request.request_id,
            total_seconds=total_seconds,
        )
    return SearchRouteResult(
        result=result,
        status_code=response_status,
        total_seconds=total_seconds,
        availability_cause=(
            classification.availability_cause if classification is not None else None
        ),
    )


def _search_response_status(
    search_request: SearchRequest,
    result: dict[str, object],
) -> int:
    """Apply the combined-search response status rule before classification."""
    if (
        search_request.search_type is PublicSourceType.COMBINED
        and result.get("ok") is False
    ):
        return 503
    return 200


def _classify_completed_search(
    result: dict[str, object],
    search_request: SearchRequest,
    context: SearchAvailabilityContext,
    classification: SearchResponseClassification | None,
    total_seconds: float,
) -> SearchResponseClassification | None:
    """Classify an ordinary completed source search after adding route timing."""
    if (
        classification is not None
        or "results" not in result
        or search_request.search_type is PublicSourceType.COMBINED
    ):
        return classification
    result["request_id"] = search_request.request_id
    timing = result.get("timing")
    if isinstance(timing, dict):
        cast("dict[str, object]", timing)["server_total_seconds"] = total_seconds
    return _classify_search_result(result, context)


async def _search_route_response(request: Request) -> JSONResponse:
    request_id = uuid.uuid4().hex
    # The route owns this ticket before the synchronous bounded admission
    # starts.  If asyncio cancels the await while its worker is still in
    # ``ledger.start``, the finally below can mark this same ticket terminal;
    # the worker then wakes and leaves without acquiring a phantom slot.
    activity_ticket = SearchActivityTicket(request_id=request_id)
    finalization = SearchActivityFinalization()
    try:
        await _run_in_thread(
            partial(
                search_activity_ledger().start,
                SearchActivityStart(
                    request_id=request_id,
                    query="",
                    search_type="unknown",
                    root=None,
                    top_k=None,
                    ticket=activity_ticket,
                ),
            )
        )
        payload = await _search_payload(request)
        if isinstance(payload, SearchRouteError):
            _record_validation_rejection(finalization, payload)
            return payload.response
        _record_provisional_activity(activity_ticket, payload)
        search_request = _normalise_search_request(payload, request_id)
        if isinstance(search_request, SearchRouteError):
            _record_validation_rejection(finalization, search_request)
            return search_request.response
        _record_normalized_activity(activity_ticket, search_request)
        completed = await _execute_search_route(search_request, request.url.port)
        finalization.result = completed.result
        finalization.status_code = completed.status_code
        finalization.total_seconds = completed.total_seconds
        finalization.availability_cause = completed.availability_cause
        finalization.error_code = None
        return JSONResponse(completed.result, status_code=completed.status_code)
    except BaseException as exc:
        cancelled = isinstance(exc, asyncio.CancelledError)
        finalization.status_code = 499 if cancelled else 500
        finalization.outcome = "cancelled" if cancelled else "failed"
        finalization.error_code = exc.__class__.__name__
        finalization.error_message = str(exc)
        raise
    finally:
        _finish_search_activity(activity_ticket, finalization)
