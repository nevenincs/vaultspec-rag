"""The ``POST /search`` route: dispatch, availability classification, timing.

Owns everything specific to serving one search request: canonical-source
dispatch (``vault``/``code``/``document``/``combined``), the index-state and
summary shaping a response carries, empty-result diagnostics, and the
availability classification that recovers an instantaneous missing-collection
observation into a stable 503 rather than surfacing a raw client exception.
"""

from __future__ import annotations

import logging
import time
import uuid
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
from ._search_availability import (
    SearchResponseClassification,
    classify_qdrant_collection_disappearance,
    classify_search_response,
)
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


def _search_index_state(
    *,
    indexed_count: int | float,
    requested_root: object,
    search_type: PublicSourceType | str,
    published_points: float | None = None,
    named_files: float | None = None,
    covered_files: float | None = None,
) -> dict[str, object]:
    """Adapt this route's carried figures onto the service-domain block.

    The route owns no part of the shape. It converts the published-point
    figure it carries on the timing channel back into the shortfall the
    domain builder expects, and renders whatever that returns.
    """
    from .._index_breadth import BreadthShortfall, FileBreadthShortfall
    from .._search_state import search_index_state

    count = int(indexed_count)
    shortfall = (
        None
        if published_points is None
        else BreadthShortfall(published=int(published_points), live=count)
    )
    file_shortfall = (
        None
        if named_files is None or covered_files is None
        else FileBreadthShortfall(named=int(named_files), covered=int(covered_files))
    )
    return search_index_state(
        indexed_count=count,
        requested_root=requested_root,
        search_type=search_type,
        shortfall=shortfall,
        file_shortfall=file_shortfall,
    )


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
    *,
    job_snapshot_before: list[dict[str, object]],
    root: Path,
    source: IndexSource,
    request_id: str,
    port: int | None,
) -> SearchResponseClassification:
    """Apply availability classification and stable-empty diagnostics."""
    from ._routes import canonical_job_snapshot

    index_state = cast("dict[str, object]", result.get("index_state", {}))
    classification = classify_search_response(
        result,
        before_snapshot=job_snapshot_before,
        after_snapshot=canonical_job_snapshot(),
        requested_root=root,
        source=source,
        request_id=request_id,
        index_state=index_state,
        port=port,
    )
    if classification.status_code == 200 and not classification.response["results"]:
        raw_path_filter = classification.response.get("path_filter")
        classification.response["empty"] = _empty_search_diagnostics(
            index_state,
            port=port,
            path_filter=cast("dict[str, object]", raw_path_filter)
            if isinstance(raw_path_filter, dict)
            else None,
        )
    return classification


def _classify_collection_disappearance(
    exc: UnexpectedResponse,
    *,
    job_snapshot_before: list[dict[str, object]],
    root: Path,
    source: IndexSource,
    request_id: str,
    port: int | None,
) -> SearchResponseClassification | None:
    """Classify one instantaneous missing-collection search observation."""
    from ._routes import canonical_job_snapshot

    return classify_qdrant_collection_disappearance(
        exc,
        before_snapshot=job_snapshot_before,
        after_snapshot=canonical_job_snapshot(),
        requested_root=root,
        source=source,
        request_id=request_id,
        index_state=_search_index_state(
            indexed_count=0,
            requested_root=root,
            search_type=source,
        ),
        port=port,
    )


async def _run_search_with_availability(
    run: Callable[[], dict[str, object]],
    *,
    job_snapshot_before: list[dict[str, object]],
    root: Path,
    source: IndexSource,
    request_id: str,
    port: int | None,
) -> tuple[dict[str, object], SearchResponseClassification | None]:
    """Run retrieval and recover only an evidenced collection disappearance."""
    try:
        return await _run_in_thread(run, limiter=get_search_limiter()), None
    except UnexpectedResponse as exc:
        classification = _classify_collection_disappearance(
            exc,
            job_snapshot_before=job_snapshot_before,
            root=root,
            source=source,
            request_id=request_id,
            port=port,
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


def _dispatch_public_search(
    root: Path,
    query: str,
    top_k: int,
    payload: dict[str, Any],
    search_type: PublicSourceType,
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

    if search_type is PublicSourceType.VAULT:
        results, timings = vaultspec_rag.search_vault_timed(
            root,
            query,
            top_k=top_k,
            doc_type=payload.get("doc_type"),
            feature=payload.get("feature"),
            date=payload.get("date"),
            tag=payload.get("tag"),
            intent=payload.get("intent"),
            like_ids=payload.get("like_ids"),
            unlike_ids=payload.get("unlike_ids"),
        )
        return results, timings, None
    if search_type is PublicSourceType.CODE:
        results, timings = vaultspec_rag.search_codebase_timed(
            root,
            query,
            top_k=top_k,
            language=payload.get("language"),
            path=payload.get("path"),
            node_type=payload.get("node_type"),
            function_name=payload.get("function_name"),
            class_name=payload.get("class_name"),
            include_paths=payload.get("include_paths"),
            exclude_paths=payload.get("exclude_paths"),
            dedup_locales=payload.get("dedup_locales"),
            prefer=payload.get("prefer"),
            exclude_domains=payload.get("exclude_domains"),
            only_domains=payload.get("only_domains"),
            include_domains=payload.get("include_domains"),
            like_ids=payload.get("like_ids"),
            unlike_ids=payload.get("unlike_ids"),
            notes=notes,
        )
        return results, timings, None
    if search_type is PublicSourceType.DOCUMENT:
        results, timings = vaultspec_rag.search_documents_timed(
            DocumentSearchRequest(
                root_dir=root,
                query=query,
                top_k=top_k,
                source_path=payload.get("source_path"),
                extractor_id=payload.get("extractor_id"),
                extractor_version=payload.get("extractor_version"),
                locator_kind=payload.get("locator_kind"),
            )
        )
        return results, timings, None
    combined, timings = vaultspec_rag.search_combined_timed(
        CombinedSearchRequest(
            root_dir=root,
            query=query,
            top_k=top_k,
            vault_filters=VaultCombinedSearchFilters(
                doc_type=payload.get("doc_type"),
                feature=payload.get("feature"),
                date=payload.get("date"),
                tag=payload.get("tag"),
                intent=payload.get("intent"),
            ),
            code_filters=CodeCombinedSearchFilters(
                language=payload.get("language"),
                path=payload.get("path"),
                node_type=payload.get("node_type"),
                function_name=payload.get("function_name"),
                class_name=payload.get("class_name"),
                include_paths=tuple(payload.get("include_paths") or ()),
                exclude_paths=tuple(payload.get("exclude_paths") or ()),
                dedup_locales=payload.get("dedup_locales"),
                prefer=payload.get("prefer"),
                exclude_domains=tuple(payload.get("exclude_domains") or ()),
                only_domains=tuple(payload.get("only_domains") or ()),
                include_domains=tuple(payload.get("include_domains") or ()),
            ),
            document_filters=DocumentCombinedSearchFilters(
                source_path=payload.get("source_path"),
                extractor_id=payload.get("extractor_id"),
                extractor_version=payload.get("extractor_version"),
                locator_kind=payload.get("locator_kind"),
            ),
        )
    )
    return combined.results, timings, combined


def _execute_search_request(
    *,
    root: Path,
    query: str,
    top_k: int,
    payload: dict[str, Any],
    search_type: PublicSourceType,
    request_id: str,
) -> dict[str, object]:
    """Execute and serialize one search off the event loop."""
    try:
        notes: dict[str, object] = {}
        phase_started = time.perf_counter()
        results, phase_timing, combined = _dispatch_public_search(
            root, query, top_k, payload, search_type, notes
        )
        search_seconds = time.perf_counter() - phase_started
        phase_started = time.perf_counter()
        indexed_count = (
            sum(
                int(phase_timing.get(f"{source}_indexed_count", 0.0))
                for source in INDEX_SOURCES
            )
            if search_type is PublicSourceType.COMBINED
            else int(phase_timing["indexed_count"])
        )
        index_state = _search_index_state(
            indexed_count=indexed_count,
            requested_root=root,
            search_type=search_type,
            published_points=phase_timing.get("published_points"),
            named_files=phase_timing.get("named_files"),
            covered_files=phase_timing.get("covered_files"),
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
            "request_id": request_id,
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
    from ._routes import canonical_job_snapshot

    denied = require_token(request)
    if denied is not None:
        return denied

    payload = await request.json()
    request_id = uuid.uuid4().hex
    search_type = _normalise_search_type(payload.get("type", "vault"))
    if isinstance(search_type, JSONResponse):
        return search_type
    unsupported_feedback = _unsupported_search_feedback(search_type, payload)
    if unsupported_feedback is not None:
        return unsupported_feedback
    query = payload.get("query", "")
    top_k = payload.get("top_k", 5)
    project_root = payload.get("project_root")

    top_k = _clamp_top_k(top_k)
    query = _validate_query(query)
    # An empty/whitespace query has no text and no filter tokens to act
    # on; encoding it retrieves arbitrary nearest neighbours, so reject
    # it. A filter-only query like "lang:python" is non-empty here and
    # proceeds (its filters drive the search after token stripping).
    if not query.strip():
        return _BAD_REQUEST_EMPTY_QUERY
    try:
        root = _resolve_root(project_root)
    except ProjectRootRequiredError:
        return _BAD_REQUEST_MISSING_ROOT
    except ValueError as exc:
        return _bad_request_invalid_root(exc)

    job_snapshot_before = canonical_job_snapshot()
    search_source = search_type.value
    run = partial(
        _execute_search_request,
        root=root,
        query=query,
        top_k=top_k,
        payload=cast("dict[str, Any]", payload),
        search_type=search_type,
        request_id=request_id,
    )

    started = time.perf_counter()
    if search_type is PublicSourceType.COMBINED:
        result = await _run_in_thread(run, limiter=get_search_limiter())
        classification = None
    else:
        result, classification = await _run_search_with_availability(
            run,
            job_snapshot_before=job_snapshot_before,
            root=root,
            source=cast('Literal["vault", "code", "document"]', search_source),
            request_id=request_id,
            port=request.url.port,
        )
    total_seconds = time.perf_counter() - started
    _m.incr("search_total")
    _m.observe("search_last_duration_seconds", total_seconds)
    response_status = 200
    if search_type is PublicSourceType.COMBINED and result.get("ok") is False:
        response_status = 503
    if (
        classification is None
        and "results" in result
        and search_type is not PublicSourceType.COMBINED
    ):
        result["request_id"] = request_id
        timing = result.get("timing")
        if isinstance(timing, dict):
            cast("dict[str, object]", timing)["server_total_seconds"] = total_seconds
        classification = _classify_search_result(
            result,
            job_snapshot_before=job_snapshot_before,
            root=root,
            source=cast('Literal["vault", "code", "document"]', search_source),
            request_id=request_id,
            port=request.url.port,
        )
    if classification is not None:
        result, response_status = _complete_classified_search(
            classification,
            root=root,
            source=cast('Literal["vault", "code", "document"]', search_source),
            request_id=request_id,
            total_seconds=total_seconds,
        )
    return JSONResponse(result, status_code=response_status)
