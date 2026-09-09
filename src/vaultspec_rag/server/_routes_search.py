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
from math import ceil, isfinite
from typing import TYPE_CHECKING, Any, Literal, cast

from anyio.to_thread import run_sync as _run_in_thread
from qdrant_client.http.exceptions import (
    ApiException,
    ResponseHandlingException,
)
from starlette.responses import JSONResponse

import vaultspec_rag.server as _m

from .._operator_commands import (
    server_status_command,
)
from .._search_state import (
    MAX_SEARCH_EVIDENCE_ITEMS,
    AbsenceAuthority,
    FreshnessWaitPolicy,
    GenerationEvidence,
    SearchAvailability,
    SearchFreshness,
    SearchSourceFact,
    SearchWaitCause,
    WaitObservation,
    search_readiness_block,
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
from ..search._outcomes import (
    COMBINED_SEARCH_FAILED,
    COMBINED_SEARCH_FAILED_MESSAGE,
)
from ..search._result_shaping import (
    PHASE_EMBEDDING,
    PHASE_MODEL_LOAD,
    PHASE_POSTPROCESS,
    PHASE_PROJECT_LEASE,
    PHASE_QDRANT,
    PHASE_RERANK,
)
from ..service import RegistryFullError, ServiceRegistry
from ..service_quiesce import QuiesceAdmissionClosedError
from ._auth import require_token
from ._runtime import get_request_runtime
from ._search_activity import (
    SearchActivityAdmissionError,
    SearchActivityCompletion,
    SearchActivityStart,
    SearchActivityTicket,
)
from ._search_route_availability import (
    SearchAvailabilityRequestFacts,
    SearchIndexStateInput,
)
from ._search_route_availability import (
    classify_search_result as _classify_search_result,
)
from ._search_route_availability import (
    readiness_snapshot as _readiness_snapshot,
)
from ._search_route_availability import (
    run_search_with_availability as _run_search_with_availability,
)
from ._search_route_availability import (
    search_index_state_for_route as _search_index_state,
)
from ._search_route_availability import (
    search_integrity_for_route as _search_integrity,
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
    from pathlib import Path

    from starlette.requests import Request

    from ..service import ServiceRegistry
    from ..service_quiesce import QuiesceSnapshot
    from ._search_availability import SearchResponseClassification
    from ._search_readiness import (
        PublicationTarget,
        ReadinessRevisionRegistry,
        ReadinessRevisionSnapshot,
    )

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
class SearchRequest:
    """Normalized user input for one search execution."""

    root: Path
    query: str
    top_k: int
    payload: dict[str, Any]
    search_type: PublicSourceType
    request_id: str
    freshness_policy: FreshnessWaitPolicy = FreshnessWaitPolicy.IMMEDIATE
    freshness_wait_seconds: float = 0.0


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


def _attach_route_waits(
    result: dict[str, object], waits: tuple[WaitObservation, ...]
) -> None:
    """Append route-owned waits to every carried concrete source fact."""
    readiness = result.get("readiness")
    if not isinstance(readiness, dict):
        return
    readiness_block = cast("dict[str, object]", readiness)
    sources = readiness_block.get("sources")
    if not isinstance(sources, list):
        return
    additions = [wait.as_dict() for wait in waits]

    def attach(source: dict[object, object]) -> None:
        source["waits"] = _merged_route_waits(source.get("waits"), additions)

    for source in cast("list[object]", sources):
        if isinstance(source, dict):
            attach(cast("dict[object, object]", source))
    domains = result.get("domains")
    if isinstance(domains, dict):
        for domain in cast("dict[object, object]", domains).values():
            if not isinstance(domain, dict):
                continue
            domain_block = cast("dict[str, object]", domain)
            source = domain_block.get("readiness")
            if isinstance(source, dict):
                attach(cast("dict[object, object]", source))


def _merged_route_waits(
    existing: object, additions: list[dict[str, object]]
) -> list[object]:
    carried = list(cast("list[object]", existing)) if isinstance(existing, list) else []
    route_owned: list[dict[str, object]] = []
    for addition in additions:
        if addition not in route_owned:
            route_owned.append(addition)
    route_owned = route_owned[-MAX_SEARCH_EVIDENCE_ITEMS:]
    prior = [item for item in carried if item not in route_owned]
    prior_capacity = MAX_SEARCH_EVIDENCE_ITEMS - len(route_owned)
    return [*prior[:prior_capacity], *route_owned]


def _backend_unavailable_result(
    request: SearchRequest, port: int | None
) -> dict[str, object]:
    """Render a proven backend refusal without inferring index state."""
    sources: tuple[IndexSource, ...] = (
        cast("tuple[IndexSource, ...]", tuple(INDEX_SOURCES))
        if request.search_type is PublicSourceType.COMBINED
        else (request.search_type.value,)
    )
    remediation = server_status_command(port, verbose=True)
    facts = tuple(
        SearchSourceFact(
            source=source,
            availability=SearchAvailability.UNAVAILABLE,
            freshness=SearchFreshness.UNVERIFIABLE,
            absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
            reason_code="backend_unavailable",
            retryable=True,
            remediation=remediation,
        )
        for source in sources
    )
    return {
        "ok": False,
        "error": "backend_unavailable",
        "message": "The search storage backend is temporarily unavailable.",
        "request_id": request.request_id,
        "retryable": True,
        "readiness": search_readiness_block(facts),
        "remediation": remediation,
    }


def _complete_backend_unavailable(
    request: SearchRequest,
    port: int | None,
    exc: BaseException,
    *,
    total_seconds: float,
    activity_waits: tuple[WaitObservation, ...],
) -> SearchRouteResult:
    """Finish one proven storage refusal as a stable route outcome."""
    result = _backend_unavailable_result(request, port)
    _attach_route_waits(result, activity_waits)
    _m.incr("search_total")
    _m.observe("search_last_duration_seconds", total_seconds)
    log_event(
        logger,
        "service.search",
        "unavailable",
        fields={
            "status_code": 503,
            "error": "backend_unavailable",
            "request_id": request.request_id,
            "source": request.search_type.value,
            "search_type": request.search_type.value,
            "root": request.root,
            "results": 0,
            "exception_type": type(exc).__name__,
            "total_seconds": f"{total_seconds:.3f}",
        },
    )
    return SearchRouteResult(
        result=result,
        status_code=503,
        total_seconds=total_seconds,
        availability_cause="storage_backend",
    )


@dataclass(frozen=True, slots=True)
class FreshnessAdmission:
    """One request's result from one exact readiness-registry lifetime."""

    outcome: Literal["immediate", "satisfied", "timeout", "unverifiable", "unavailable"]
    readiness: ReadinessRevisionRegistry | None = None
    target: PublicationTarget | None = None
    snapshot: ReadinessRevisionSnapshot | None = None
    targets: tuple[PublicationTarget, ...] = ()
    snapshots: tuple[ReadinessRevisionSnapshot, ...] = ()
    waited_seconds: float = 0.0


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


def _complete_classified_search(
    classification: SearchResponseClassification,
    *,
    facts: SearchAvailabilityRequestFacts,
    registry: ServiceRegistry,
    total_seconds: float,
) -> tuple[dict[str, object], Literal[200, 409, 503]]:
    """Complete watcher and log effects from one classification decision."""
    result = classification.response
    # The classifier owns the canonical failure code and evidence. HTTP owns
    # only the protocol mapping of that code; it must not inherit the legacy
    # classifier's blanket 503 when the canonical state is a rebuild conflict.
    # Capacity remains 503 while no canonical reset deadline can justify 429.
    response_status = _search_response_status(result)
    root = facts.root
    source = facts.source
    _m._ensure_watcher_soon(root, registry)
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
            "request_id": facts.request_id,
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
    if error in ("index_unavailable", "quiesce_admission_closed"):
        return "unavailable"
    if error == COMBINED_SEARCH_FAILED:
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
    registry: ServiceRegistry,
    notes: dict[str, object],
) -> tuple[list[Any], dict[str, float], Any | None]:
    """Dispatch one canonical source without adapter fallback."""
    from .._public_search import (
        CodeCombinedSearchFilters,
        CombinedSearchRequest,
        DocumentCombinedSearchFilters,
        DocumentSearchRequest,
        VaultCombinedSearchFilters,
        search_combined_timed,
        search_documents_timed,
    )
    from ..api import (
        CodebaseSearchRequest,
        VaultSearchRequest,
        search_codebase_timed,
        search_vault_timed,
    )

    if request.search_type is PublicSourceType.VAULT:
        results, timings = search_vault_timed(
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
            ),
            registry=registry,
        )
        return results, timings, None
    if request.search_type is PublicSourceType.CODE:
        results, timings = search_codebase_timed(
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
            ),
            registry=registry,
        )
        return results, timings, None
    if request.search_type is PublicSourceType.DOCUMENT:
        results, timings = search_documents_timed(
            DocumentSearchRequest(
                root_dir=request.root,
                query=request.query,
                top_k=request.top_k,
                source_path=request.payload.get("source_path"),
                extractor_id=request.payload.get("extractor_id"),
                extractor_version=request.payload.get("extractor_version"),
                locator_kind=request.payload.get("locator_kind"),
            ),
            registry=registry,
        )
        return results, timings, None
    combined, timings = search_combined_timed(
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
        ),
        registry=registry,
    )
    return combined.results, timings, combined


def _dominant_combined_failure(
    source_facts: tuple[SearchSourceFact, ...],
) -> tuple[str, bool, str | None]:
    """Select the strongest carried failure without erasing its retry policy."""
    priority = (
        "rebuild_required",
        "rebuild_refused",
        "capacity_limited",
        "backend_unavailable",
        "freshness_wait_timeout",
        "index_unavailable",
        "index_updating",
        "index_unverifiable",
    )
    selected_reason = next(
        (
            reason
            for reason in priority
            if any(fact.reason_code == reason for fact in source_facts)
        ),
        "index_unverifiable",
    )
    selected = next(
        (fact for fact in source_facts if fact.reason_code == selected_reason),
        source_facts[0],
    )
    remediation = next(
        (
            fact.remediation
            for fact in source_facts
            if fact.reason_code == selected_reason and fact.remediation is not None
        ),
        selected.remediation,
    )
    stable_error = (
        "index_unavailable" if selected_reason == "index_updating" else selected_reason
    )
    return stable_error, selected.retryable, remediation


def _execute_search_request(
    request: SearchRequest, registry: ServiceRegistry
) -> dict[str, object]:
    """Execute and serialize one search off the event loop."""
    compute_wait_started = time.perf_counter()
    ticket = registry.acquire_compute_ticket()
    compute_ticket_wait_seconds = time.perf_counter() - compute_wait_started
    try:
        notes: dict[str, object] = {}
        phase_started = time.perf_counter()
        results, phase_timing, combined = _dispatch_public_search(
            request,
            registry,
            notes,
        )
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
                result_paths=tuple(result.path for result in results),
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
                "compute_ticket_wait_seconds": compute_ticket_wait_seconds,
                "timing_scope": "server_route",
                "phases": phase_timing,
            },
            "index_state": index_state,
        }
        if combined is not None:
            dominant_error, dominant_retryable, dominant_remediation = (
                _dominant_combined_failure(combined.source_facts)
            )
            response["ok"] = combined.ok
            response["partial"] = combined.partial
            response["domains"] = combined.domain_status_payload()
            response["readiness"] = search_readiness_block(combined.source_facts)
            if not combined.ok:
                response.pop("results", None)
                response.update(
                    {
                        "error": COMBINED_SEARCH_FAILED,
                        "message": COMBINED_SEARCH_FAILED_MESSAGE,
                        "summary": "Combined search failed in every domain.",
                        "retryable": dominant_retryable,
                        "remediation": dominant_remediation,
                    }
                )
            elif not items and (
                combined.partial
                or combined.readiness.absence_authority
                is not AbsenceAuthority.AUTHORITATIVE
            ):
                response.pop("results", None)
                response.pop("summary", None)
                response.update(
                    {
                        "ok": False,
                        "error": dominant_error,
                        "message": (
                            "The empty combined search is not authoritative for "
                            "every requested source."
                        ),
                        "retryable": dominant_retryable,
                        "remediation": dominant_remediation,
                    }
                )
        return response
    except RegistryFullError as exc:
        return _m._registry_full_error_dict(exc, registry)
    except VaultStoreLockedError as exc:
        return _m._local_store_locked_error_dict(exc)
    finally:
        ticket.release()


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
    wait_policy = _freshness_wait_policy(payload)
    policy_error = (
        SearchRouteError(unsupported_feedback, error_code="unsupported_feedback")
        if unsupported_feedback is not None
        else wait_policy
        if isinstance(wait_policy, SearchRouteError)
        else None
    )
    if policy_error is not None:
        return policy_error
    assert not isinstance(wait_policy, SearchRouteError)
    query = payload.get("query", "")
    top_k = payload.get("top_k", 5)
    project_root = payload.get("project_root")
    # _search_field_error narrows query to str, top_k to a non-bool int, and
    # project_root to str | None; a None return means every field already
    # has the type each cast below asserts.
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
        payload=payload,
        search_type=search_type,
        request_id=request_id,
        freshness_policy=wait_policy[0],
        freshness_wait_seconds=wait_policy[1],
    )


def _freshness_wait_policy(
    payload: dict[str, object],
) -> tuple[FreshnessWaitPolicy, float] | SearchRouteError:
    """Validate the opt-in publication wait without changing immediate defaults."""
    from ..config._settings import get_config

    configured_maximum = float(get_config().search_freshness_wait_max_seconds)
    raw_policy = payload.get("freshness_policy", FreshnessWaitPolicy.IMMEDIATE.value)
    if not isinstance(raw_policy, str):
        return _bad_search_field(
            "invalid_freshness_policy",
            "freshness_policy must be 'immediate' or 'bounded'",
        )
    try:
        policy = FreshnessWaitPolicy(raw_policy)
    except ValueError:
        return _bad_search_field(
            "invalid_freshness_policy",
            "freshness_policy must be 'immediate' or 'bounded'",
        )
    raw_seconds = payload.get("freshness_wait_seconds")
    if policy is FreshnessWaitPolicy.IMMEDIATE:
        if raw_seconds is not None:
            return _bad_search_field(
                "invalid_freshness_wait_seconds",
                "freshness_wait_seconds requires freshness_policy 'bounded'",
            )
        return policy, 0.0
    if (
        isinstance(raw_seconds, bool)
        or not isinstance(raw_seconds, (int, float))
        or not isfinite(raw_seconds)
        or raw_seconds < 0
        or raw_seconds > configured_maximum
    ):
        return _bad_search_field(
            "invalid_freshness_wait_seconds",
            "freshness_wait_seconds must be a finite number between 0 and "
            f"{configured_maximum:g}",
        )
    return policy, float(raw_seconds)


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
    # Only reached after _search_field_error confirmed project_root is str | None.
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


def _capture_publication_targets(
    search_request: SearchRequest,
    readiness: ReadinessRevisionRegistry,
) -> tuple[PublicationTarget, ...] | None:
    """Capture immutable per-source convergence targets at request admission."""
    from ._search_readiness import PublicationTarget, ReadinessSourceKey

    sources: tuple[IndexSource, ...] = (
        cast("tuple[IndexSource, ...]", tuple(INDEX_SOURCES))
        if search_request.search_type is PublicSourceType.COMBINED
        else (search_request.search_type.value,)
    )
    targets: list[PublicationTarget] = []
    for source in sources:
        snapshot = readiness.snapshot(search_request.root, source)
        if snapshot.controller_revision is not None:
            revision = snapshot.controller_revision
            generation = snapshot.desired_generation
        elif snapshot.publication_revision is not None:
            revision = snapshot.publication_revision
            generation = snapshot.published_generation
        else:
            return None
        targets.append(
            PublicationTarget(
                key=ReadinessSourceKey.from_root(search_request.root, source),
                revision=revision,
                generation=generation,
            )
        )
    return tuple(targets)


async def _admit_requested_freshness(
    search_request: SearchRequest,
    registry: ServiceRegistry,
) -> FreshnessAdmission:
    """Apply the caller policy while preserving native task cancellation."""
    if search_request.freshness_policy is FreshnessWaitPolicy.IMMEDIATE:
        return FreshnessAdmission("immediate")
    from ._search_readiness import ReadinessRegistryClosedError

    try:
        readiness = registry.readiness_registry
    except RuntimeError as exc:
        if str(exc) != "readiness registry is not started":
            raise
        return FreshnessAdmission("unavailable")
    try:
        targets = _capture_publication_targets(search_request, readiness)
        if targets is None:
            return FreshnessAdmission("unverifiable", readiness=readiness)
        wait_started = time.perf_counter()
        satisfied = await readiness.published_at_least(
            targets,
            timeout_seconds=search_request.freshness_wait_seconds,
        )
        waited_seconds = time.perf_counter() - wait_started
        if not satisfied:
            snapshots = tuple(
                readiness.snapshot(target.key.canonical_root, target.key.source)
                for target in targets
            )
            return FreshnessAdmission(
                "timeout",
                readiness=readiness,
                targets=targets,
                snapshots=snapshots,
                waited_seconds=waited_seconds,
            )
        target = targets[0] if len(targets) == 1 else None
        snapshot = (
            readiness.snapshot(search_request.root, target.key.source)
            if target is not None
            else None
        )
    except ReadinessRegistryClosedError:
        return FreshnessAdmission("unavailable", readiness=readiness)
    return FreshnessAdmission(
        "satisfied",
        readiness=readiness,
        target=target,
        snapshot=snapshot,
    )


def _freshness_wait_failure(
    admission: FreshnessAdmission,
    search_request: SearchRequest,
    *,
    port: int | None,
    total_seconds: float,
) -> SearchRouteResult:
    """Return a stable typed pre-retrieval freshness failure."""
    if admission.outcome == "timeout":
        error = "freshness_wait_timeout"
        message = "The index did not reach the requested publication before the bound."
    elif admission.outcome == "unavailable":
        error = "index_unavailable"
        message = "The admitted readiness lifetime closed before search could run."
    else:
        error = "index_unverifiable"
        message = (
            "No canonical publication or controller target is available to wait for."
        )
    _m.incr("search_total")
    _m.observe("search_last_duration_seconds", total_seconds)
    result: dict[str, object] = {
        "ok": False,
        "error": error,
        "message": message,
        "retryable": True,
        "request_id": search_request.request_id,
    }
    if admission.outcome == "timeout":
        bound = search_request.freshness_wait_seconds
        waited = min(admission.waited_seconds, bound)
        facts = tuple(
            SearchSourceFact(
                source=target.key.source,
                availability=(
                    SearchAvailability.USABLE
                    if snapshot.publication_revision is not None
                    else SearchAvailability.UNAVAILABLE
                ),
                freshness=(
                    SearchFreshness.UPDATING
                    if snapshot.publication_revision is not None
                    else SearchFreshness.UNVERIFIABLE
                ),
                absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
                generation=GenerationEvidence(
                    served_generation=snapshot.published_generation,
                    desired_generation=target.generation,
                    served_revision=snapshot.publication_revision,
                    desired_revision=target.revision,
                ),
                wait_policy=FreshnessWaitPolicy.BOUNDED,
                waits=(
                    WaitObservation(
                        cause=(
                            SearchWaitCause.CONTROLLER_DEFERRAL
                            if snapshot.controller_revision is not None
                            and (
                                snapshot.publication_revision is None
                                or snapshot.controller_revision
                                > snapshot.publication_revision
                            )
                            else SearchWaitCause.INDEX_TRANSITION
                        ),
                        waited_seconds=waited,
                        configured_bound_seconds=bound,
                        remaining_bound_seconds=max(0.0, bound - waited),
                    ),
                ),
                evidence=(f"target_revision:{target.revision}",),
                reason_code=error,
                retryable=True,
                remediation=server_status_command(port, verbose=True),
            )
            for target, snapshot in zip(
                admission.targets, admission.snapshots, strict=True
            )
        )
        result["readiness"] = search_readiness_block(facts)
        result["remediation"] = server_status_command(port, verbose=True)
    return SearchRouteResult(
        result=result,
        status_code=503,
        total_seconds=total_seconds,
        availability_cause=None,
    )


def _record_worker_timing(result: dict[str, object], started_at: float) -> None:
    timing = result.get("timing")
    if not isinstance(timing, dict):
        return
    timing_block = cast("dict[str, object]", timing)
    compute_wait = timing_block.get("compute_ticket_wait_seconds")
    if isinstance(compute_wait, (int, float)) and not isinstance(compute_wait, bool):
        timing_block["worker_service_seconds"] = max(
            0.0, time.perf_counter() - started_at - float(compute_wait)
        )
    storage_seconds = timing_block.get("qdrant_seconds")
    if isinstance(storage_seconds, (int, float)) and not isinstance(
        storage_seconds, bool
    ):
        timing_block["storage_backend_seconds"] = float(storage_seconds)


async def _execute_search_route(
    search_request: SearchRequest,
    port: int | None,
    registry: ServiceRegistry,
    activity_waits: tuple[WaitObservation, ...] = (),
) -> SearchRouteResult:
    """Run, classify, and record the public response for one valid search."""
    from ._routes import canonical_job_snapshot

    started = time.perf_counter()
    admission = await _admit_requested_freshness(search_request, registry)
    if admission.outcome in ("timeout", "unverifiable", "unavailable"):
        return _freshness_wait_failure(
            admission,
            search_request,
            port=port,
            total_seconds=time.perf_counter() - started,
        )

    # The fan-out has no single index to classify against, so it builds no
    # availability facts at all. Deriving ``source`` only on this branch is
    # what lets it stay typed as one concrete corpus: the checker narrows
    # ``search_type.value`` here and rejects the fan-out anywhere else, which
    # a cast at an unconditional construction site could only assert.
    availability_facts = (
        None
        if search_request.search_type is PublicSourceType.COMBINED
        else SearchAvailabilityRequestFacts(
            job_snapshot_before=canonical_job_snapshot(),
            root=search_request.root,
            source=search_request.search_type.value,
            request_id=search_request.request_id,
            port=port,
            readiness_snapshot=(
                admission.snapshot
                if admission.readiness is not None
                else _readiness_snapshot(
                    registry,
                    search_request.root,
                    search_request.search_type.value,
                )
            ),
            readiness_target=admission.target,
            wait_policy=search_request.freshness_policy,
        )
    )
    run = partial(_execute_search_request, search_request, registry)
    limiter_submitted = time.perf_counter()
    worker_started: list[float] = []

    def witnessed_run() -> dict[str, object]:
        started_at = time.perf_counter()
        worker_started.append(started_at)
        result = run()
        _record_worker_timing(result, started_at)
        return result

    try:
        if availability_facts is None:
            result = await _run_in_thread(witnessed_run, limiter=get_search_limiter())
            classification = None
        else:
            result, classification = await _run_search_with_availability(
                witnessed_run,
                availability_facts,
            )
    except QuiesceAdmissionClosedError as exc:
        total_seconds = time.perf_counter() - started
        result = _quiesce_admission_closed_result(
            exc.snapshot,
            request_id=search_request.request_id,
        )
        _m.incr("search_total")
        _m.observe("search_last_duration_seconds", total_seconds)
        log_event(
            logger,
            "service.search",
            "unavailable",
            fields={
                "status_code": 503,
                "error": "quiesce_admission_closed",
                "request_id": search_request.request_id,
                "source": search_request.search_type.value,
                "search_type": search_request.search_type.value,
                "root": search_request.root,
                "results": 0,
                "total_seconds": f"{total_seconds:.3f}",
            },
        )
        return SearchRouteResult(
            result=result,
            status_code=503,
            total_seconds=total_seconds,
            availability_cause=None,
        )
    except (ApiException, ResponseHandlingException) as exc:
        total_seconds = time.perf_counter() - started
        return _complete_backend_unavailable(
            search_request,
            port,
            exc,
            total_seconds=total_seconds,
            activity_waits=activity_waits,
        )
    total_seconds = time.perf_counter() - started
    limiter_wait = worker_started[0] - limiter_submitted if worker_started else 0.0
    timing = result.get("timing")
    if isinstance(timing, dict):
        timing["search_limiter_wait_seconds"] = limiter_wait
    _m.incr("search_total")
    _m.observe("search_last_duration_seconds", total_seconds)
    response_status = _search_response_status(result)
    if availability_facts is not None:
        classification = _classify_completed_search(
            result,
            search_request,
            availability_facts,
            classification,
            total_seconds,
        )
        if classification is not None:
            result, response_status = _complete_classified_search(
                classification,
                facts=availability_facts,
                registry=registry,
                total_seconds=total_seconds,
            )
    _attach_route_waits(result, activity_waits)
    return SearchRouteResult(
        result=result,
        status_code=response_status,
        total_seconds=total_seconds,
        availability_cause=(
            classification.availability_cause if classification is not None else None
        ),
    )


def _search_response_status(
    result: dict[str, object],
) -> Literal[200, 409, 503]:
    """Map canonical search outcomes onto their stable HTTP status.

    Retrieval envelopes carry no ``ok`` key, so only a failure declares one.
    Rebuild-required/refused states conflict with the requested target. Every
    transient availability, capacity, backend, or wait failure remains 503.
    Capacity can become 429 only when a canonical enforced future reset
    deadline exists; no current response fact carries one, so neither 429 nor
    Retry-After can be truthfully emitted here.
    """
    if result.get("ok") is not False:
        return 200
    error = result.get("error")
    if error in {"rebuild_required", "rebuild_refused"}:
        return 409
    return 503


def _quiesce_admission_closed_result(
    snapshot: QuiesceSnapshot,
    *,
    request_id: str,
) -> dict[str, object]:
    """Render retryable admission closure without a local remediation path."""
    return {
        "ok": False,
        "error": "quiesce_admission_closed",
        "message": (
            "Search is temporarily unavailable while service compute admission is "
            "closed; retry after the service returns to running."
        ),
        "retryable": True,
        "request_id": request_id,
        "quiesce": {
            "state": snapshot.state.value,
            "admission_epoch": snapshot.admission_epoch,
            "safe_to_borrow_gpu": snapshot.safe_to_borrow_gpu,
        },
    }


def _activity_admission_response(exc: SearchActivityAdmissionError) -> JSONResponse:
    """Render bounded ledger capacity refusal from its canonical deadline."""
    result: dict[str, object] = {
        "ok": False,
        "error": "capacity_limited",
        "message": "Search activity capacity is temporarily unavailable.",
        "retryable": True,
        "request_id": exc.request_id,
        "waits": [exc.wait.as_dict()],
        "remediation": "Retry after active searches complete.",
    }
    headers: dict[str, str] | None = None
    status = 503
    now = time.time()
    if (
        exc.reason == "deadline_exceeded"
        and exc.deadline is not None
        and exc.deadline > now
    ):
        status = 429
        headers = {"Retry-After": str(max(1, ceil(exc.deadline - now)))}
    return JSONResponse(result, status_code=status, headers=headers)


def _classify_completed_search(
    result: dict[str, object],
    search_request: SearchRequest,
    facts: SearchAvailabilityRequestFacts,
    classification: SearchResponseClassification | None,
    total_seconds: float,
) -> SearchResponseClassification | None:
    """Classify an ordinary completed source search after adding route timing.

    Availability classification refines a successful retrieval into an
    index-unavailable verdict, so a failed envelope is skipped on its own
    declaration.  Skipping on an absent ``results`` key instead would tie
    "did this fail" to "does the payload carry hits", which silently held
    every failure envelope at the success status.

    The ``combined`` fan-out is excluded before this point rather than tested
    here: it builds no :class:`SearchAvailabilityRequestFacts`, so the route
    cannot reach this function with it, and the exclusion is now carried by a
    type the checker enforces instead of by a condition a reader can mistake
    for redundant and drop.
    """
    if classification is not None or result.get("ok") is False:
        return classification
    result["request_id"] = search_request.request_id
    timing = result.get("timing")
    if isinstance(timing, dict):
        cast("dict[str, object]", timing)["server_total_seconds"] = total_seconds
    return _classify_search_result(result, facts)


async def _search_route_response(request: Request) -> JSONResponse:
    request_id = uuid.uuid4().hex
    # The route owns this ticket before the synchronous bounded admission
    # starts.  If asyncio cancels the await while its worker is still in
    # ``ledger.start``, the finally below can mark this same ticket terminal;
    # the worker then wakes and leaves without acquiring a phantom slot.
    activity_ticket = SearchActivityTicket(request_id=request_id)
    finalization = SearchActivityFinalization()
    try:
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
        except SearchActivityAdmissionError as exc:
            response = _activity_admission_response(exc)
            finalization.status_code = response.status_code
            finalization.outcome = "admission_failed"
            finalization.error_code = "capacity_limited"
            finalization.error_message = str(exc)
            return response
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
        completed = await _execute_search_until_disconnect(
            request,
            search_request,
            request.url.port,
            get_request_runtime(request).registry,
            activity_ticket.admission_waits,
        )
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


async def _execute_search_until_disconnect(
    request: Request,
    search_request: SearchRequest,
    port: int | None,
    registry: ServiceRegistry,
    activity_waits: tuple[WaitObservation, ...] = (),
) -> SearchRouteResult:
    """Cancel route work when the already-read ASGI request disconnects."""
    executing = asyncio.create_task(
        _execute_search_route(search_request, port, registry, activity_waits)
    )
    disconnected = asyncio.create_task(_wait_for_http_disconnect(request))
    try:
        done, _ = await asyncio.wait(
            (executing, disconnected),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if disconnected in done:
            # A transport failure is not a client disconnect. Observe the listener
            # first so its exception escapes unchanged; only its normal completion
            # represents ``http.disconnect``.
            await disconnected
            raise asyncio.CancelledError
        return await executing
    finally:
        for task in (executing, disconnected):
            if not task.done():
                task.cancel()
        await asyncio.gather(executing, disconnected, return_exceptions=True)


async def _wait_for_http_disconnect(request: Request) -> None:
    """Wait for the transport's terminal message after request-body consumption."""
    while True:
        message = await request.receive()
        if message["type"] == "http.disconnect":
            return
