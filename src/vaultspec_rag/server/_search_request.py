"""Validation of one ``POST /search`` body into a dispatchable request.

Every refusal keeps its established envelope and carries the review metadata
that explains it: a malformed body or field is 400, and a root that no longer
exists is 410 because retrying, indexing or watching it again cannot help.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Any, cast

from starlette.responses import JSONResponse

from .._error_payload import error_payload
from .._root_presence import RootMissingError
from .._search_state import (
    FreshnessWaitPolicy,
    SearchReasonCode,
    root_missing_response,
)
from .._source_types import (
    INDEX_SOURCES,
    IndexSource,
    PublicSourceType,
    SourceTypeParseError,
    parse_source_type,
    unsupported_feedback_envelope,
)
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

__all__ = [
    "SearchRequest",
    "SearchRouteError",
    "normalise_search_request",
    "read_search_payload",
]


_BAD_REQUEST_EMPTY_QUERY = JSONResponse(
    {
        "ok": False,
        "error": SearchReasonCode.BAD_REQUEST,
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

    @property
    def sources(self) -> tuple[IndexSource, ...]:
        """Concrete sources whose availability this request depends on."""
        if self.search_type is PublicSourceType.COMBINED:
            return (
                INDEX_SOURCES
                if self.payload.get("include_documents", True)
                else ("vault", "code")
            )
        return (self.search_type.value,)


@dataclass(frozen=True, slots=True)
class SearchRouteError:
    """A validation response and the review metadata that explains it."""

    response: JSONResponse
    error_code: str
    error_message: str | None = None


def _normalise_search_type(value: object) -> PublicSourceType | JSONResponse:
    try:
        return parse_source_type(value)
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


async def read_search_payload(request: Request) -> dict[str, object] | SearchRouteError:
    """Read the request body into the one shape the route accepts."""
    try:
        payload = await request.json()
    except Exception as exc:
        return SearchRouteError(
            JSONResponse(
                {
                    "ok": False,
                    "error": SearchReasonCode.BAD_REQUEST,
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
                "error": SearchReasonCode.BAD_REQUEST,
                "message": "search request body must be a JSON object",
            },
            status_code=400,
        ),
        error_code=SearchReasonCode.BAD_REQUEST,
        error_message="search request body must be a JSON object",
    )


def normalise_search_request(
    payload: dict[str, object],
    request_id: str,
) -> SearchRequest | SearchRouteError:
    """Validate public payload data and form the dispatched search request."""
    search_type = _normalise_search_type(payload.get("type", "vault"))
    if isinstance(search_type, JSONResponse):
        return SearchRouteError(search_type, error_code=SearchReasonCode.BAD_REQUEST)
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
    field_error = _search_field_error(
        query, top_k, project_root, payload.get("include_documents", True)
    )
    if field_error is not None:
        return field_error
    query = _validate_query(cast("str", query))
    if not query.strip():
        return SearchRouteError(
            _BAD_REQUEST_EMPTY_QUERY,
            error_code=SearchReasonCode.BAD_REQUEST,
            error_message="query is empty",
        )
    root = _search_root(project_root, request_id)
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
    include_documents: object = True,
) -> SearchRouteError | None:
    """Return the first scalar request-shape error, if any."""
    if not isinstance(include_documents, bool):
        return _bad_search_field(
            "invalid_include_documents", "include_documents must be a boolean"
        )
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
            error_payload(SearchReasonCode.BAD_REQUEST, message),
            status_code=400,
        ),
        error_code=error_code,
        error_message=message,
    )


def _search_root(project_root: object, request_id: str) -> Path | SearchRouteError:
    """Resolve the validated root while preserving the established envelopes."""
    # Only reached after _search_field_error confirmed project_root is str | None.
    try:
        return _resolve_root(cast("str | None", project_root))
    except RootMissingError as exc:
        # Gone, not unavailable: 410 tells a caller to stop retrying, and the
        # refusal happens before anything could re-arm the root's watcher.
        return SearchRouteError(
            JSONResponse(
                root_missing_response(exc.root, request_id=request_id, port=None),
                status_code=410,
            ),
            error_code=SearchReasonCode.ROOT_MISSING,
            error_message=str(exc),
        )
    except ProjectRootRequiredError:
        return SearchRouteError(
            _BAD_REQUEST_MISSING_ROOT,
            error_code=SearchReasonCode.BAD_REQUEST,
            error_message="project_root is required",
        )
    except ValueError as exc:
        return SearchRouteError(
            JSONResponse(
                error_payload(SearchReasonCode.BAD_REQUEST, str(exc)), status_code=400
            ),
            error_code=SearchReasonCode.BAD_REQUEST,
            error_message=str(exc),
        )
