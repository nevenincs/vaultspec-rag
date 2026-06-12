"""HTTP REST client helpers for the CLI fast path.

Each `_try_http_*` helper talks to a running RAG service over HTTP
and discriminates "service unreachable" (connection refused -> `None`)
from "live but broken" (structured error dict). `_is_connection_refused`
walks the exception chain to make that call.
"""

from __future__ import annotations

import errno
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal, cast

from ._core import logger

__all__ = [
    "DEFAULT_SEARCH_TIMEOUT_SECONDS",
    "_is_connection_refused",
    "_try_http_admin",
    "_try_http_reindex",
    "_try_http_search",
]

DEFAULT_SEARCH_TIMEOUT_SECONDS = 300.0


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


def _do_http_call(
    port: int,
    path: str,
    payload: dict[str, object] | None,
    timeout: float | None = None,
) -> dict[str, object] | None:
    from ._service_status import _read_service_status

    status = _read_service_status()
    token = status.get("service_token", status.get("token", "")) if status else ""

    url = f"http://127.0.0.1:{port}{path}"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    else:
        req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return cast("dict[str, object]", json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return cast("dict[str, object]", json.loads(body))
        except json.JSONDecodeError:
            return {"ok": False, "error": "http_error", "message": f"{e.code}: {body}"}


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


def _route_admin_tool(
    tool_name: str,
    args: dict[str, Any],
    port: int,
) -> dict[str, Any] | None:
    """Map an admin tool name to an HTTP call and return the raw result."""
    if tool_name == "get_logs":
        return _do_http_call(port, _logs_route_path(args), None)

    if tool_name == "get_jobs":
        url_path = "/jobs"
        allowed = {
            "limit",
            "phase",
            "source",
            "trigger",
            "query",
            "failed",
            "job_id",
            "since",
        }
        params = {
            key: value
            for key, value in args.items()
            if key in allowed and value is not None
        }
        if params:
            url_path += "?" + urllib.parse.urlencode(params)
        return _do_http_call(port, url_path, None)

    if tool_name == "get_index_status":
        return _do_http_call(port, _admin_url_with_root("/status", args), None)

    if tool_name == "get_code_file":
        return _do_http_call(port, "/code-file", args)

    if tool_name == "list_projects":
        return _do_http_call(port, _admin_url_with_root("/projects", args), None)

    if tool_name == "evict_project":
        return _do_http_call(port, "/projects/evict", args)

    if tool_name == "get_watcher_state":
        return _do_http_call(port, _admin_url_with_root("/watcher", args), None)

    if tool_name in ("start_watcher", "stop_watcher", "reconfigure_watcher"):
        verb = tool_name.split("_")[0]
        return _do_http_call(port, f"/watcher/{verb}", args)

    if tool_name == "get_service_state":
        return _do_http_call(port, _admin_url_with_root("/service-state", args), None)

    return {
        "ok": False,
        "error": "unknown_admin_tool",
        "message": f"Tool {tool_name} not mapped",
    }


def _try_http_admin(
    tool_name: str,
    args: dict[str, Any],
    port: int | None,
) -> dict[str, Any] | None:
    if port is None:
        return None
    try:
        res = _route_admin_tool(tool_name, args, port)
        return res if res is not None else {}
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug(
                "HTTP admin call on port %s: connection refused (%s)", port, exc
            )
            return None
        logger.debug(
            "HTTP admin call on port %s raised non-refused exception",
            port,
            exc_info=True,
        )
        return {}


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
        running_count = summary.get("running", running_count)
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
            "message": health.get("message", "Health probe returned an error."),
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
    caps = health.get("backend_capabilities")
    if not isinstance(caps, dict):
        caps = {}
    running_count = jobs.get("running_count", "unknown")
    strategy = caps.get("same_project_search_strategy", "unknown")
    retry_timeout = max(DEFAULT_SEARCH_TIMEOUT_SECONDS, timeout * 2)
    return {
        "ok": False,
        "error": "http_search_timeout",
        "message": (
            f"The search request to the service on port {port} timed out "
            f"after {timeout:g} seconds. The service may still be working "
            "on that request; check service status and running jobs before "
            "retrying."
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
            f"vaultspec-rag server jobs --running --port {port}",
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
    include_paths: list[str] | None,
    exclude_paths: list[str] | None,
    dedup_locales: bool,
    prefer: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "query": query,
        "top_k": top_k,
        "project_root": project_root,
    }
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
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    dedup_locales: bool = False,
    prefer: str | None = None,
) -> list[dict[str, object]] | dict[str, object] | None:
    from ..search import (
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
        include_paths,
        exclude_paths,
        dedup_locales,
        prefer,
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
