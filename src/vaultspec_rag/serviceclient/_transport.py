"""Import-light HTTP wire client for the resident RAG service.

Both the CLI and the MCP consume this one transport: every call funnels
through :func:`_do_http_call`, which reads ``service.json`` for the port and
bearer token and returns the decoded daemon JSON. The ``_try_http_*`` helpers
discriminate "service unreachable" (connection refused -> ``None``) from "live
but broken" (a structured ``ok=False`` error dict); :func:`_is_connection_refused`
walks the exception chain to make that call.

This module imports only stdlib plus the lightweight filter validator from
``..search._validation`` (which itself imports nothing heavy). It loads no
Torch, no models, and no store, so importing it is import-light.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal, cast

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_SEARCH_TIMEOUT_SECONDS",
    "_do_http_call",
    "_get_search_timeout",
    "_is_connection_refused",
    "_logs_route_path",
    "_timeout_diagnostics",
    "_try_http_admin",
    "_try_http_benchmark",
    "_try_http_code_file",
    "_try_http_quality",
    "_try_http_reindex",
    "_try_http_search",
    "_try_http_vault_document",
]

DEFAULT_SEARCH_TIMEOUT_SECONDS = 300.0
DEFAULT_ADMIN_TIMEOUT_SECONDS = 10.0


def _is_connection_refused(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ConnectionRefusedError):
            return True
        if isinstance(reason, OSError) and getattr(reason, "errno", None) in (
            errno.ECONNREFUSED,
            getattr(errno, "WSAECONNREFUSED", 10061),
        ):
            return True
    return bool(isinstance(exc, ConnectionRefusedError))


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError | socket.timeout):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        return isinstance(reason, TimeoutError | socket.timeout)
    return False


def _get_admin_timeout(timeout: float | None = None) -> float:
    if timeout is not None:
        return timeout
    env_timeout = os.environ.get("VAULTSPEC_RAG_ADMIN_TIMEOUT")
    if env_timeout:
        try:
            parsed = float(env_timeout)
        except ValueError:
            return DEFAULT_ADMIN_TIMEOUT_SECONDS
        return parsed if parsed > 0 else DEFAULT_ADMIN_TIMEOUT_SECONDS
    return DEFAULT_ADMIN_TIMEOUT_SECONDS


def _format_timeout_seconds(timeout: float) -> str:
    value = f"{timeout:g}"
    noun = "second" if timeout == 1 else "seconds"
    return f"{value} {noun}"


def _status_file_token() -> str:
    """Return the ``service_token`` recorded in the local status file, or ``""``."""
    from ._discovery import _read_service_status

    status = _read_service_status()
    if not status:
        return ""
    token = status.get("service_token", status.get("token", ""))
    return token if isinstance(token, str) else ""


def _fetch_health_token(port: int, timeout: float | None = None) -> str:
    """Read the live ``service_token`` from the target port's ``/health``.

    ``/health`` is ungated and echoes the running service's per-process
    ``service_token``, so a CLI invocation that points ``--port`` at a service
    started out-of-band (e.g. by another project, under a different status
    directory) can still authenticate against the token-gated routes. Returns
    ``""`` on any failure - including connection refused - so the caller's
    normal request still runs and the existing unreachable/error handling
    applies.
    """
    url = f"http://127.0.0.1:{port}/health"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(
            req, timeout=timeout or DEFAULT_ADMIN_TIMEOUT_SECONDS
        ) as resp:
            data: object = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("health token probe on port %s failed: %s", port, exc)
        return ""
    if isinstance(data, dict):
        token = cast("dict[str, object]", data).get("service_token")
        if isinstance(token, str):
            return token
    return ""


def _build_call_request(
    port: int,
    path: str,
    payload: dict[str, object] | None,
    token: str,
) -> urllib.request.Request:
    url = f"http://127.0.0.1:{port}{path}"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
        return urllib.request.Request(url, data=data, headers=headers, method="POST")
    return urllib.request.Request(url, headers=headers, method="GET")


def _send_call(
    req: urllib.request.Request, timeout: float | None
) -> tuple[int, dict[str, object]]:
    """Send *req*; return ``(status_code, parsed_body)``.

    HTTP error responses (e.g. a 401 from the token gate) are parsed and
    returned alongside their status code rather than raised, so the caller can
    react to a 401 by refreshing the token. Connection-level failures still
    propagate to the caller's unreachable handling.
    """
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = cast("dict[str, object]", json.loads(resp.read().decode("utf-8")))
            return int(resp.status), body
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, cast("dict[str, object]", json.loads(raw))
        except json.JSONDecodeError:
            return e.code, {
                "ok": False,
                "error": "http_error",
                "message": f"{e.code}: {raw}",
            }


def _do_http_call(
    port: int,
    path: str,
    payload: dict[str, object] | None,
    timeout: float | None = None,
) -> dict[str, object] | None:
    """Call a service route, recovering the auth token on a 401.

    The token from the local status file is sent first (it may be empty or
    stale). Only if the route rejects it with 401 does the client fetch the
    live token from the target port's ungated ``/health`` and retry once. This
    keeps the happy path a single request while letting ``--port`` authenticate
    against a service started out-of-band (missing status file) or restarted
    (rotated token), without an extra round-trip when the first call succeeds.
    """
    token = _status_file_token()
    status_code, result = _send_call(
        _build_call_request(port, path, payload, token), timeout
    )

    if status_code == 401:
        fresh = _fetch_health_token(port, timeout)
        if fresh and fresh != token:
            logger.debug(
                "token rejected on port %s; retrying with the /health token", port
            )
            _, result = _send_call(
                _build_call_request(port, path, payload, fresh), timeout
            )
    return result


def _try_http_reindex(
    tool_name: str,
    clean: bool,
    port: int,
    project_root: str,
) -> dict[str, object] | None:
    try:
        search_type = "vault" if "vault" in tool_name else "codebase"
        payload: dict[str, object] = {
            "type": search_type,
            "clean": clean,
            "project_root": project_root,
            "initiator_kind": "cli",
        }
        res = _do_http_call(port, "/reindex", payload)
        if res is not None:
            return res
        return {}
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug("HTTP reindex on port %s: connection refused (%s)", port, exc)
            return None
        cls = exc.__class__.__name__
        return {
            "ok": False,
            "error": "http_call_failed",
            "message": f"HTTP reindex on port {port} failed: {cls}: {exc}",
        }


def _admin_url_with_root(base: str, args: dict[str, Any]) -> str:
    """Append ?project_root=... to base when args contains it."""
    project_root = args.get("project_root")
    if project_root:
        return base + "?project_root=" + urllib.parse.quote(str(project_root))
    return base


def _logs_route_path(args: dict[str, Any]) -> str:
    """Build the JSON logs route path with optional bounded filters.

    The daemon's ``/logs/json`` route returns ``{"lines": [...]}`` which the
    JSON-parsing ``_do_http_call`` can decode; the plaintext ``/logs`` route
    would fail JSON decoding and silently yield no lines.
    """
    path = "/logs/json"
    params = {
        key: value
        for key, value in args.items()
        if key in {"lines", "job_id", "contains"} and value is not None
    }
    if params:
        path += "?" + urllib.parse.urlencode(params)
    return path


# GET admin tools that accept only an optional ``?project_root=`` query.
_GET_ROOT_ROUTES: dict[str, str] = {
    "list_projects": "/projects",
    "get_watcher_state": "/watcher",
    "get_service_state": "/service-state",
}

# POST admin tools whose full ``args`` dict is the JSON body.
_POST_BODY_ROUTES: dict[str, str] = {
    "get_code_file": "/code-file",
    "get_vault_document": "/vault-document",
    "evict_project": "/projects/evict",
}

_JOBS_PARAMS = {
    "limit",
    "phase",
    "source",
    "trigger",
    "query",
    "failed",
    "job_id",
    "since",
}


def _jobs_route_path(args: dict[str, Any]) -> str:
    """Build the ``/jobs`` route path with its bounded query filters."""
    url_path = "/jobs"
    params = {
        key: value
        for key, value in args.items()
        if key in _JOBS_PARAMS and value is not None
    }
    if params:
        url_path += "?" + urllib.parse.urlencode(params)
    return url_path


def _resolve_admin_call(
    tool_name: str, args: dict[str, Any]
) -> tuple[str, dict[str, Any] | None] | None:
    """Resolve an admin tool to its ``(path, body)`` pair, or ``None`` if unknown."""
    if tool_name == "get_logs":
        return _logs_route_path(args), None
    if tool_name == "get_jobs":
        return _jobs_route_path(args), None
    if tool_name in _GET_ROOT_ROUTES:
        return _admin_url_with_root(_GET_ROOT_ROUTES[tool_name], args), None
    if tool_name in _POST_BODY_ROUTES:
        return _POST_BODY_ROUTES[tool_name], args
    if tool_name in ("start_watcher", "stop_watcher", "reconfigure_watcher"):
        verb = tool_name.split("_")[0]
        return f"/watcher/{verb}", args
    return None


def _route_admin_tool(
    tool_name: str,
    args: dict[str, Any],
    port: int,
) -> dict[str, Any] | None:
    """Map an admin tool name to an HTTP call and return the raw result."""
    raw_timeout = args.get("_timeout")
    timeout = float(raw_timeout) if isinstance(raw_timeout, int | float) else None
    args = {key: value for key, value in args.items() if key != "_timeout"}
    resolved = _resolve_admin_call(tool_name, args)
    if resolved is None:
        return {
            "ok": False,
            "error": "unknown_admin_tool",
            "message": f"Tool {tool_name} not mapped",
        }
    path, body = resolved
    return _do_http_call(port, path, body, timeout=timeout)


def _try_http_admin(
    tool_name: str,
    args: dict[str, Any],
    port: int | None,
    timeout: float | None = None,
) -> dict[str, Any] | None:
    if port is None:
        return None
    resolved_timeout = _get_admin_timeout(timeout)
    try:
        res = _route_admin_tool(tool_name, {**args, "_timeout": resolved_timeout}, port)
        return res if res is not None else {}
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug(
                "HTTP admin call on port %s: connection refused (%s)", port, exc
            )
            return None
        if _is_timeout(exc):
            logger.debug(
                "HTTP admin call on port %s timed out after %ss",
                port,
                resolved_timeout,
            )
            return {
                "ok": False,
                "error": "admin_timeout",
                "message": (
                    f"The service on port {port} did not answer within "
                    f"{_format_timeout_seconds(resolved_timeout)}."
                ),
            }
        logger.debug(
            "HTTP admin call on port %s raised non-refused exception",
            port,
            exc_info=True,
        )
        return {}


def _try_http_code_file(
    path: str,
    project_root: str,
    port: int | None,
    timeout: float | None = None,
) -> dict[str, object] | None:
    """Fetch a code file's contents from the daemon's ``/code-file`` route.

    Thin forwarder over :func:`_do_http_call` with no business logic; mirrors
    the admin-call discrimination (refused -> ``None``).
    """
    return _try_http_admin(
        "get_code_file",
        {"path": path, "project_root": project_root},
        port,
        timeout=timeout,
    )


def _try_http_vault_document(
    doc_id: str,
    project_root: str,
    port: int | None,
    timeout: float | None = None,
) -> dict[str, object] | None:
    """Fetch a vault document from the daemon's ``/vault-document`` route.

    Thin forwarder over :func:`_do_http_call` with no business logic; mirrors
    the admin-call discrimination (refused -> ``None``). Empty ``project_root``
    is omitted so the daemon resolves its default root.
    """
    args: dict[str, Any] = {"doc_id": doc_id}
    if project_root:
        args["project_root"] = project_root
    return _try_http_admin(
        "get_vault_document",
        args,
        port,
        timeout=timeout,
    )


def _try_http_benchmark(
    project_root: str,
    n_queries: int,
    port: int,
    timeout: float | None = None,
) -> dict[str, object] | None:
    """POST the daemon's ``/benchmark`` route.

    Thin forwarder over :func:`_do_http_call`; the daemon owns the benchmark
    logic. Refused connections fall through to ``None``.
    """
    try:
        payload: dict[str, object] = {
            "project_root": project_root,
            "n_queries": n_queries,
        }
        res = _do_http_call(port, "/benchmark", payload, timeout=timeout)
        return res if res is not None else {}
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug(
                "HTTP benchmark on port %s: connection refused (%s)", port, exc
            )
            return None
        cls = exc.__class__.__name__
        return {
            "ok": False,
            "error": "http_call_failed",
            "message": f"HTTP benchmark on port {port} failed: {cls}: {exc}",
        }


def _try_http_quality(
    port: int,
    timeout: float | None = None,
) -> dict[str, object] | None:
    """POST the daemon's ``/quality`` route.

    Thin forwarder over :func:`_do_http_call`; the daemon owns the quality
    probe. Refused connections fall through to ``None``.
    """
    try:
        res = _do_http_call(port, "/quality", {}, timeout=timeout)
        return res if res is not None else {}
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug("HTTP quality on port %s: connection refused (%s)", port, exc)
            return None
        cls = exc.__class__.__name__
        return {
            "ok": False,
            "error": "http_call_failed",
            "message": f"HTTP quality on port {port} failed: {cls}: {exc}",
        }


def _get_search_timeout(timeout: float | None) -> float:
    if timeout is None:
        env_timeout = os.environ.get("VAULTSPEC_RAG_SEARCH_TIMEOUT")
        if env_timeout:
            try:
                return float(env_timeout)
            except ValueError:
                return DEFAULT_SEARCH_TIMEOUT_SECONDS
        return DEFAULT_SEARCH_TIMEOUT_SECONDS
    return timeout


def _probe_unavailable(kind: str, exc: Exception) -> dict[str, object]:
    logger.debug("%s diagnostic probe failed: %s", kind, exc, exc_info=True)
    return {
        "available": False,
        "error": exc.__class__.__name__,
        "message": str(exc),
    }


def _running_jobs_summary(port: int) -> dict[str, object]:
    try:
        jobs = _do_http_call(port, "/jobs?limit=5&phase=running", None, timeout=1.0)
    except Exception as exc:
        return _probe_unavailable("jobs", exc)
    if not isinstance(jobs, dict):
        return {"available": False}
    if jobs.get("ok") is False:
        return {
            "available": False,
            "error": jobs.get("error", "service_error"),
            "message": jobs.get("message", "Jobs probe returned an error."),
        }
    raw_jobs = jobs.get("jobs")
    summary = jobs.get("summary")
    running_count: object = jobs.get("returned", 0)
    if isinstance(summary, dict):
        running_count = cast("dict[str, object]", summary).get("running", running_count)
    return {
        "available": True,
        "running_count": running_count,
        "jobs": raw_jobs if isinstance(raw_jobs, list) else [],
    }


def _health_summary(port: int) -> dict[str, object]:
    try:
        health = _do_http_call(port, "/health", None, timeout=1.0)
    except Exception as exc:
        return _probe_unavailable("health", exc)
    if not isinstance(health, dict):
        return {"available": False}
    if health.get("ok") is False:
        return {
            "available": False,
            "error": health.get("error", "service_error"),
            "message": health.get("message", "Readiness check returned an error."),
        }
    return {
        "available": True,
        "status": health.get("status", "unknown"),
        "project_count": health.get("project_count", 0),
        "backend_capabilities": health.get("backend_capabilities", {}),
    }


def _active_indexing_conflict(running_count: object) -> bool | None:
    if isinstance(running_count, bool):
        return None
    if isinstance(running_count, int):
        return running_count > 0
    if isinstance(running_count, str):
        try:
            return int(running_count) > 0
        except ValueError:
            return None
    return None


def _timeout_diagnostics(port: int, timeout: float) -> dict[str, object]:
    health = _health_summary(port)
    jobs = _running_jobs_summary(port)
    raw_caps = health.get("backend_capabilities")
    caps: dict[str, object] = (
        cast("dict[str, object]", raw_caps) if isinstance(raw_caps, dict) else {}
    )
    running_count = jobs.get("running_count", "unknown")
    strategy = caps.get("same_project_search_strategy", "unknown")
    retry_timeout = max(DEFAULT_SEARCH_TIMEOUT_SECONDS, timeout * 2)
    return {
        "ok": False,
        "error": "http_search_timeout",
        "message": (
            f"The search request to the service on port {port} timed out "
            f"after {timeout:g} seconds. The service may still be working "
            "on that request; check service status and active index jobs "
            "before retrying."
        ),
        "port": port,
        "timeout_seconds": timeout,
        "backend_capabilities": caps,
        "diagnostics": {
            "health": health,
            "jobs": jobs,
            "backpressure": {
                "same_project_search_strategy": strategy,
                "active_indexing_conflict": _active_indexing_conflict(running_count),
                "observation": "jobs endpoint snapshot",
            },
        },
        "remediation": [
            f"vaultspec-rag server status --port {port}",
            f"vaultspec-rag server jobs --state active --port {port}",
            f"Rerun the same search with --timeout {retry_timeout:g}",
        ],
    }


def _build_http_search_payload(
    query: str,
    search_type: str,
    top_k: int,
    project_root: str,
    language: str | None,
    path: str | None,
    node_type: str | None,
    function_name: str | None,
    class_name: str | None,
    doc_type: str | None,
    feature: str | None,
    date: str | None,
    tag: str | None,
    intent: str | None,
    include_paths: list[str] | None,
    exclude_paths: list[str] | None,
    dedup_locales: bool,
    prefer: str | None,
    like_ids: list[str | int] | None,
    unlike_ids: list[str | int] | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "query": query,
        "top_k": top_k,
        "project_root": project_root,
    }
    if like_ids:
        payload["like_ids"] = list(like_ids)
    if unlike_ids:
        payload["unlike_ids"] = list(unlike_ids)
    if search_type == "code":
        payload["type"] = "codebase"
        code_filters = {
            "language": language,
            "path": path,
            "node_type": node_type,
            "function_name": function_name,
            "class_name": class_name,
        }
        for key, value in code_filters.items():
            if value is not None:
                payload[key] = value
        if include_paths:
            payload["include_paths"] = list(include_paths)
        if exclude_paths:
            payload["exclude_paths"] = list(exclude_paths)
        if dedup_locales:
            payload["dedup_locales"] = True
        if prefer is not None:
            payload["prefer"] = prefer
    elif search_type == "vault":
        payload["type"] = "vault"
        vault_filters = {
            "doc_type": doc_type,
            "feature": feature,
            "date": date,
            "tag": tag,
            "intent": intent,
        }
        for key, value in vault_filters.items():
            if value is not None:
                payload[key] = value
    return payload


def _try_http_search(
    query: str,
    search_type: str,
    top_k: int,
    port: int,
    project_root: str,
    *,
    timeout: float | None = None,
    language: str | None = None,
    path: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
    doc_type: str | None = None,
    feature: str | None = None,
    date: str | None = None,
    tag: str | None = None,
    intent: str | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    dedup_locales: bool = False,
    prefer: str | None = None,
    like_ids: list[str | int] | None = None,
    unlike_ids: list[str | int] | None = None,
) -> list[dict[str, object]] | dict[str, object] | None:
    # Import the lightweight validator from the leaf module rather than the
    # ``..search`` package, whose __init__ pulls the heavy VaultSearcher (and
    # thus store/embeddings). ``_validation`` imports only stdlib, so this keeps
    # the service-client transport import-light.
    from ..search._validation import (
        InvalidFilterForSearchTypeError,
        InvalidPreferValueError,
        validate_search_filters,
    )

    try:
        validate_search_filters(
            cast("Literal['vault', 'code']", search_type),
            language=language,
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            dedup_locales=dedup_locales,
            prefer=prefer,
        )
    except InvalidFilterForSearchTypeError as exc:
        return {
            "ok": False,
            "error": "invalid_filter_for_search_type",
            "message": str(exc),
        }
    except InvalidPreferValueError as exc:
        return {"ok": False, "error": "invalid_prefer_value", "message": str(exc)}

    timeout = _get_search_timeout(timeout)
    payload = _build_http_search_payload(
        query,
        search_type,
        top_k,
        project_root,
        language,
        path,
        node_type,
        function_name,
        class_name,
        doc_type,
        feature,
        date,
        tag,
        intent,
        include_paths,
        exclude_paths,
        dedup_locales,
        prefer,
        like_ids,
        unlike_ids,
    )

    try:
        res = _do_http_call(port, "/search", payload, timeout=timeout)
        if res and res.get("ok") is False:
            return res
        if res and "results" in res:
            return res
        return []
    except TimeoutError:
        logger.debug("HTTP search on port %s timed out after %ss", port, timeout)
        return _timeout_diagnostics(port, timeout)
    except Exception as exc:
        if isinstance(exc, TimeoutError) or (
            isinstance(exc, urllib.error.URLError)
            and isinstance(exc.reason, TimeoutError)
        ):
            return _timeout_diagnostics(port, timeout)
        if _is_connection_refused(exc):
            logger.debug("HTTP search on port %s: connection refused (%s)", port, exc)
            return None
        cls = exc.__class__.__name__
        return {
            "ok": False,
            "error": "http_call_failed",
            "message": f"HTTP search on port {port} failed: {cls}: {exc}",
        }
