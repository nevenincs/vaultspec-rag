"""Search and index MCP tools.

Split out of the original ``mcp_server.py`` monolith per the
``2026-06-01-module-split-adr``. Importing this module runs the
``@mcp.tool()`` decorators, registering the search/index tools on the
shared :data:`mcp` instance. The registry is read through the package
alias so a test rebind of ``_registry`` is observed.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from ._mcp import mcp
from ..cli._service_status import _read_service_status

def _call_daemon(path: str, payload: dict | None = None) -> dict:
    status = _read_service_status()
    if not status or "port" not in status:
        raise RuntimeError("vaultspec-rag daemon is not running (service.json not found).")
        
    port = status["port"]
    token = status.get("service_token", status.get("token", ""))
    
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
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return json.loads(body)
        except:
            raise RuntimeError(f"REST API call to {url} failed with {e.code}: {body}")
    except Exception as e:
        raise RuntimeError(f"REST API call to {url} failed: {e}")

@mcp.tool()
async def search_vault(
    query: str,
    top_k: int = 5,
    doc_type: str | None = None,
    feature: str | None = None,
    date: str | None = None,
    tag: str | None = None,
    like_ids: list[str | int] | None = None,
    unlike_ids: list[str | int] | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Search the documentation vault for relevant ADRs, plans, and research."""
    payload = {
        "type": "vault",
        "query": query,
        "top_k": top_k,
        "doc_type": doc_type,
        "feature": feature,
        "date": date,
        "tag": tag,
        "like_ids": like_ids,
        "unlike_ids": unlike_ids,
        "project_root": project_root,
    }
    return _call_daemon("/search", {k: v for k, v in payload.items() if v is not None})


@mcp.tool()
async def search_codebase(
    query: str,
    top_k: int = 5,
    language: str | None = None,
    path: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    dedup_locales: bool = False,
    prefer: str | None = None,
    like_ids: list[str | int] | None = None,
    unlike_ids: list[str | int] | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Search the source codebase for relevant functions, classes, or logic."""
    payload = {
        "type": "codebase",
        "query": query,
        "top_k": top_k,
        "language": language,
        "path": path,
        "node_type": node_type,
        "function_name": function_name,
        "class_name": class_name,
        "include_paths": include_paths,
        "exclude_paths": exclude_paths,
        "dedup_locales": dedup_locales,
        "prefer": prefer,
        "like_ids": like_ids,
        "unlike_ids": unlike_ids,
        "project_root": project_root,
    }
    return _call_daemon("/search", {k: v for k, v in payload.items() if v is not None})


@mcp.tool()
async def get_index_status(
    project_root: str | None = None,
) -> dict[str, Any]:
    """Return the current status of the RAG index and GPU hardware."""
    url_path = "/status"
    if project_root:
        import urllib.parse
        url_path += "?project_root=" + urllib.parse.quote(project_root)
    return _call_daemon(url_path)


@mcp.tool()
async def get_code_file(
    path: str,
    project_root: str | None = None,
) -> str:
    """Retrieve the full content of a source file by path."""
    payload = {"path": path, "project_root": project_root}
    res = _call_daemon("/code-file", {k: v for k, v in payload.items() if v is not None})
    if "content" in res:
        return res["content"]
    if "error" in res:
        raise ValueError(res["error"])
    return ""


@mcp.tool()
async def reindex_vault(
    clean: bool = False,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Re-index vault documentation (incremental by default)."""
    payload = {"type": "vault", "clean": clean, "project_root": project_root}
    return _call_daemon("/reindex", {k: v for k, v in payload.items() if v is not None})


@mcp.tool()
async def reindex_codebase(
    clean: bool = False,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Re-index the source codebase (incremental by default)."""
    payload = {"type": "codebase", "clean": clean, "project_root": project_root}
    return _call_daemon("/reindex", {k: v for k, v in payload.items() if v is not None})
