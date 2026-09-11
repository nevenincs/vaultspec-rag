"""Calling the service's search route, and reading what comes back.

Building the request from caller arguments, validating it before it leaves,
and narrowing every field of the reply. A search that cannot be served has to
come back as a described refusal rather than an exception, because the callers
are operator surfaces that must say why. Transport failures remain transport
failures rather than being recast as service readiness diagnoses.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Unpack, cast

from .._source_types import (
    PublicSourceType,
    SourceTypeParseError,
    parse_source_type,
    unsupported_feedback_envelope,
)
from ._transport import (
    DEFAULT_SEARCH_TIMEOUT_SECONDS,
    SearchCallRequest,
    _do_http_call,
    _is_connection_refused,
    resolve_timeout,
)

if TYPE_CHECKING:
    from ._transport import DocumentSearchFilters, SearchCallArguments

logger = logging.getLogger(__name__)


def get_search_timeout(timeout: float | None) -> float:
    """Return the search-call bound."""
    return resolve_timeout(
        timeout,
        setting="service_search_timeout_seconds",
        label="search",
        default=DEFAULT_SEARCH_TIMEOUT_SECONDS,
    )


def document_search_filters(
    *,
    source_path: str | None,
    extractor_id: str | None,
    extractor_version: str | None,
    locator_kind: str | None,
) -> DocumentSearchFilters:
    """Return the document filter mapping the service accepts.

    Three call sites - the CLI search verb and both MCP document tools - built
    this dict from the same four arguments. The keys are the schema's
    DOCUMENT_FILTER_KEYS; what was copied is the projection of arguments onto
    them, so a fifth filter would have had to be remembered in three places.
    """
    return {
        "source_path": source_path,
        "extractor_id": extractor_id,
        "extractor_version": extractor_version,
        "locator_kind": locator_kind,
    }


def probe_unavailable(kind: str, exc: Exception) -> dict[str, object]:
    """Describe a failed caller-owned diagnostic probe."""
    logger.debug("%s diagnostic probe failed: %s", kind, exc, exc_info=True)
    return {
        "available": False,
        "error": exc.__class__.__name__,
        "message": str(exc),
    }


def _build_http_search_payload(
    request: SearchCallRequest,
    source: PublicSourceType,
    *,
    freshness_policy: str,
    freshness_wait_seconds: float | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "query": request.query,
        "top_k": request.top_k,
        "project_root": request.project_root,
        "type": source.value,
        "freshness_policy": freshness_policy,
    }
    if freshness_wait_seconds is not None:
        payload["freshness_wait_seconds"] = freshness_wait_seconds
    if request.like_ids:
        payload["like_ids"] = list(request.like_ids)
    if request.unlike_ids:
        payload["unlike_ids"] = list(request.unlike_ids)
    selected_filters: dict[str, object | None] = {}
    if source in {PublicSourceType.CODE, PublicSourceType.COMBINED}:
        selected_filters.update(
            {
                "language": request.language,
                "path": request.path,
                "node_type": request.node_type,
                "function_name": request.function_name,
                "class_name": request.class_name,
            }
        )
        if request.include_paths:
            payload["include_paths"] = list(request.include_paths)
        if request.exclude_paths:
            payload["exclude_paths"] = list(request.exclude_paths)
        # Tri-state: only send when the caller set it explicitly, so the server
        # resolves the configured default when it is absent.
        if request.dedup_locales is not None:
            payload["dedup_locales"] = bool(request.dedup_locales)
        if request.prefer is not None:
            payload["prefer"] = request.prefer
    if source in {PublicSourceType.VAULT, PublicSourceType.COMBINED}:
        selected_filters.update(
            {
                "doc_type": request.doc_type,
                "feature": request.feature,
                "date": request.date,
                "tag": request.tag,
                "intent": request.intent,
            }
        )
    if source in {PublicSourceType.DOCUMENT, PublicSourceType.COMBINED}:
        selected_filters.update(request.document_filters or {})
    for key, value in selected_filters.items():
        if value is not None:
            payload[key] = value
    return payload


def _invalid_search_service_response(port: int) -> dict[str, object]:
    """Return the stable failure envelope for a malformed search response."""
    return {
        "ok": False,
        "error": "invalid_service_response",
        "message": (
            f"HTTP search on port {port} returned an invalid service response; "
            "expected a non-empty JSON object envelope containing results or "
            "a structured error."
        ),
    }


def _search_response_envelope(response: object, port: int) -> dict[str, object]:
    """Return a valid search envelope or the stable malformed-response error."""
    if isinstance(response, dict) and response:
        envelope = cast("dict[str, object]", response)
        if envelope.get("ok") is False or isinstance(envelope.get("results"), list):
            return envelope
    return _invalid_search_service_response(port)


def _str_search_field(values: dict[str, object], key: str) -> str:
    """Return one required string search argument, narrowed from ``object``.

    Positional arguments to ``try_http_search`` arrive typed bare
    ``object`` (there is no way to check a positional value's type before it
    is zipped to its name), so this is where a caller's wrong-typed value is
    caught instead of reaching :class:`SearchCallRequest` through an
    unchecked ``**cast("Any", ...)`` unpack.
    """
    value = values.get(key)
    if not isinstance(value, str):
        raise TypeError(f"try_http_search argument {key!r} must be a string")
    return value


def _optional_str_search_field(values: dict[str, object], key: str) -> str | None:
    """Return one optional string search argument, narrowed from ``object``."""
    value = values.get(key)
    if value is None:
        return None
    return _str_search_field(values, key)


def _int_search_field(values: dict[str, object], key: str) -> int:
    """Return one required integer search argument, narrowed from ``object``."""
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"try_http_search argument {key!r} must be an int")
    return value


def _optional_numeric_search_field(values: dict[str, object], key: str) -> float | None:
    """Return one optional numeric search argument as a float.

    Mirrors the admin-call numeric coercion elsewhere in this module: an
    int literal is a reasonable spelling of a float-typed argument, so both
    are accepted and coerced; anything else is rejected.
    """
    value = values.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"try_http_search argument {key!r} must be a number")
    return float(value)


def _optional_bool_search_field(values: dict[str, object], key: str) -> bool | None:
    """Return one optional boolean search argument, narrowed from ``object``."""
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TypeError(f"try_http_search argument {key!r} must be a bool")
    return value


def _optional_str_list_search_field(
    values: dict[str, object], key: str
) -> list[str] | None:
    """Return one optional string-list search argument, narrowed from ``object``."""
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise TypeError(f"try_http_search argument {key!r} must be a list of strings")
    # A confirmed list's element type is still Unknown to the checker; this
    # names it `object` so the per-element isinstance check just below does
    # the actual narrowing instead of the cast asserting it away.
    raw_list = cast("list[object]", value)
    if not all(isinstance(item, str) for item in raw_list):
        raise TypeError(f"try_http_search argument {key!r} must be a list of strings")
    return cast("list[str]", raw_list)


def _optional_id_list_search_field(
    values: dict[str, object], key: str
) -> list[str | int] | None:
    """Return one optional id-list search argument, narrowed from ``object``."""
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise TypeError(f"try_http_search argument {key!r} must be a list of ids")
    raw_list = cast("list[object]", value)
    if not all(
        isinstance(item, str) or (isinstance(item, int) and not isinstance(item, bool))
        for item in raw_list
    ):
        raise TypeError(f"try_http_search argument {key!r} must be a list of ids")
    return cast("list[str | int]", raw_list)


def _optional_document_filters_search_field(
    values: dict[str, object], key: str
) -> DocumentSearchFilters | None:
    """Return one optional document-filter mapping, narrowed from ``object``."""
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(
            f"try_http_search argument {key!r} must be a string-keyed mapping"
        )
    raw_mapping = cast("dict[object, object]", value)
    if not all(
        isinstance(k, str) and (v is None or isinstance(v, str))
        for k, v in raw_mapping.items()
    ):
        raise TypeError(
            f"try_http_search argument {key!r} must be a string-keyed mapping"
        )
    return cast("DocumentSearchFilters", raw_mapping)


def _search_request_from_arguments(
    positional: tuple[object, ...],
    arguments: SearchCallArguments,
) -> SearchCallRequest:
    """Normalize the stable positional-or-named search surface once."""
    names = ("query", "search_type", "top_k", "port", "project_root")
    if len(positional) > len(names):
        raise TypeError(
            f"try_http_search accepts at most {len(names)} positional arguments"
        )
    values: dict[str, object] = dict(zip(names, positional, strict=False))
    for name, value in arguments.items():
        if name in values:
            raise TypeError(
                f"try_http_search got multiple values for argument {name!r}"
            )
        values[name] = value
    return SearchCallRequest(
        query=_str_search_field(values, "query"),
        search_type=_str_search_field(values, "search_type"),
        top_k=_int_search_field(values, "top_k"),
        port=_int_search_field(values, "port"),
        project_root=_str_search_field(values, "project_root"),
        timeout=_optional_numeric_search_field(values, "timeout"),
        language=_optional_str_search_field(values, "language"),
        path=_optional_str_search_field(values, "path"),
        node_type=_optional_str_search_field(values, "node_type"),
        function_name=_optional_str_search_field(values, "function_name"),
        class_name=_optional_str_search_field(values, "class_name"),
        doc_type=_optional_str_search_field(values, "doc_type"),
        feature=_optional_str_search_field(values, "feature"),
        date=_optional_str_search_field(values, "date"),
        tag=_optional_str_search_field(values, "tag"),
        intent=_optional_str_search_field(values, "intent"),
        include_paths=_optional_str_list_search_field(values, "include_paths"),
        exclude_paths=_optional_str_list_search_field(values, "exclude_paths"),
        dedup_locales=_optional_bool_search_field(values, "dedup_locales"),
        prefer=_optional_str_search_field(values, "prefer"),
        like_ids=_optional_id_list_search_field(values, "like_ids"),
        unlike_ids=_optional_id_list_search_field(values, "unlike_ids"),
        document_filters=_optional_document_filters_search_field(
            values, "document_filters"
        ),
    )


def _validate_search_request(
    request: SearchCallRequest,
) -> tuple[PublicSourceType | None, dict[str, object] | None]:
    """Resolve the source and reject unsupported search-filter combinations."""
    from ..search._validation import (
        InvalidFilterForSearchTypeError,
        InvalidPreferValueError,
        SearchFilterOptions,
        validate_search_filters,
    )

    try:
        source = parse_source_type(request.search_type, allow_aliases=True)
    except SourceTypeParseError as exc:
        return None, exc.as_error_envelope()
    refusal = unsupported_feedback_envelope(
        source, has_point_ids=bool(request.like_ids or request.unlike_ids)
    )
    if refusal is not None:
        return None, refusal
    try:
        validate_search_filters(
            source.value,
            SearchFilterOptions(
                language=request.language,
                path=request.path,
                node_type=request.node_type,
                function_name=request.function_name,
                class_name=request.class_name,
                doc_type=request.doc_type,
                feature=request.feature,
                date=request.date,
                tag=request.tag,
                include_paths=request.include_paths,
                exclude_paths=request.exclude_paths,
                dedup_locales=request.dedup_locales,
                prefer=request.prefer,
                source_path=(request.document_filters or {}).get("source_path"),
                extractor_id=(request.document_filters or {}).get("extractor_id"),
                extractor_version=(request.document_filters or {}).get(
                    "extractor_version"
                ),
                locator_kind=(request.document_filters or {}).get("locator_kind"),
            ),
        )
    except InvalidFilterForSearchTypeError as exc:
        return None, {
            "ok": False,
            "error": "invalid_filter_for_search_type",
            "message": str(exc),
        }
    except InvalidPreferValueError as exc:
        return None, {"ok": False, "error": "invalid_prefer_value", "message": str(exc)}
    return source, None


def _search_transport_failure(
    exc: Exception,
    port: int,
) -> dict[str, object] | None:
    """Translate a genuine transport exception without diagnosing readiness."""
    if _is_connection_refused(exc):
        logger.debug("HTTP search on port %s: connection refused (%s)", port, exc)
        return None
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return _invalid_search_service_response(port)
    cls = exc.__class__.__name__
    return {
        "ok": False,
        "error": "http_call_failed",
        "message": f"HTTP search on port {port} failed: {cls}: {exc}",
    }


def try_http_search(
    *positional: object,
    freshness_policy: str = "immediate",
    freshness_wait_seconds: float | None = None,
    **arguments: Unpack[SearchCallArguments],
) -> dict[str, object] | None:
    request = _search_request_from_arguments(positional, arguments)
    source, refusal = _validate_search_request(request)
    if refusal is not None or source is None:
        return refusal

    timeout = get_search_timeout(request.timeout)
    payload = _build_http_search_payload(
        request,
        source,
        freshness_policy=freshness_policy,
        freshness_wait_seconds=freshness_wait_seconds,
    )

    try:
        response: object = _do_http_call(
            request.port, "/search", payload, timeout=timeout
        )
        return _search_response_envelope(response, request.port)
    except Exception as exc:
        return _search_transport_failure(exc, request.port)
