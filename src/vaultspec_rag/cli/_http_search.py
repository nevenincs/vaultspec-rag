"""HTTP REST client helpers for the CLI fast path.

Each `_try_http_*` helper talks to a running RAG service over HTTP
and discriminates "service unreachable" (connection refused -> `None`)
from "live but broken" (structured error dict). `_is_connection_refused`
walks the exception chain to make that call.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Literal, cast

from ._core import logger


def _is_connection_refused(exc: BaseException) -> bool:
    import errno

    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ConnectionRefusedError):
            return True
        if isinstance(reason, OSError) and getattr(reason, "errno", None) in (
            errno.ECONNREFUSED,
            getattr(errno, "WSAECONNREFUSED", 10061),
        ):
            return True
    if isinstance(exc, ConnectionRefusedError):
        return True
    return False


def _do_http_call(
    port: int, path: str, payload: dict | None, timeout: float | None = None
) -> dict | None:
    from ._service_status import _read_service_status

    status = _read_service_status()
    token = status.get("service_token", status.get("token", "")) if status else ""

    url = f"http://127.0.0.1:{port}{path}"
    headers = {}
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
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return json.loads(body)
        except:
            return {"ok": False, "error": "http_error", "message": f"{e.code}: {body}"}


def _try_http_reindex(
    tool_name: str,
    clean: bool,
    port: int,
    project_root: str,
) -> dict[str, object] | None:
    try:
        search_type = "vault" if "vault" in tool_name else "codebase"
        payload = {"type": search_type, "clean": clean, "project_root": project_root}
        res = _do_http_call(port, "/reindex", payload)
        if res is not None:
            return res
        return {}
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug("HTTP reindex on port %s: connection refused (%s)", port, exc)
            return None
        return {
            "ok": False,
            "error": "http_call_failed",
            "message": f"HTTP reindex on port {port} failed: {exc.__class__.__name__}: {exc}",
        }


def _try_http_admin(
    tool_name: str,
    args: dict[str, Any],
    port: int | None,
) -> dict[str, Any] | None:
    if port is None:
        return None
    try:
        # map admin tools to REST paths
        if tool_name == "get_logs":
            url_path = "/logs"
            if "lines" in args:
                url_path += f"?lines={args['lines']}"
            res = _do_http_call(port, url_path, None)
        elif tool_name == "get_jobs":
            url_path = "/jobs"
            if "limit" in args:
                url_path += f"?limit={args['limit']}"
            res = _do_http_call(port, url_path, None)
        elif tool_name == "get_index_status":
            url_path = "/status"
            if args.get("project_root"):
                import urllib.parse

                url_path += "?project_root=" + urllib.parse.quote(args["project_root"])
            res = _do_http_call(port, url_path, None)
        elif tool_name == "get_code_file":
            res = _do_http_call(port, "/code-file", args)
        else:
            # Fallback for others if any
            res = {
                "ok": False,
                "error": "unknown_admin_tool",
                "message": f"Tool {tool_name} not mapped",
            }
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
    import os

    if timeout is None:
        env_timeout = os.environ.get("VAULTSPEC_RAG_SEARCH_TIMEOUT")
        if env_timeout:
            try:
                return float(env_timeout)
            except ValueError:
                return 10.0
        return 10.0
    return timeout


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
            return res["results"]
        return []
    except TimeoutError:
        logger.debug("HTTP search on port %s timed out after %ss", port, timeout)
        return {
            "ok": False,
            "error": "http_search_timeout",
            "message": f"HTTP search on port {port} timed out after {timeout}s.",
        }
    except Exception as exc:
        if isinstance(exc, TimeoutError) or (
            isinstance(exc, urllib.error.URLError)
            and isinstance(exc.reason, TimeoutError)
        ):
            return {
                "ok": False,
                "error": "http_search_timeout",
                "message": f"HTTP search on port {port} timed out after {timeout}s.",
            }
        if _is_connection_refused(exc):
            logger.debug("HTTP search on port %s: connection refused (%s)", port, exc)
            return None
        return {
            "ok": False,
            "error": "http_call_failed",
            "message": f"HTTP search on port {port} failed: {exc.__class__.__name__}: {exc}",
        }
