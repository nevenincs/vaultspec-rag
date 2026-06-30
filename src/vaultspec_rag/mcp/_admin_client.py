"""Async admin/observability client for the running RAG daemon.

These are **not** MCP tools. The MCP search surface is narrowed to search,
index-refresh, and read-only retrieval (see the ``mcp-search-scope`` ADR); the
mutating and observability admin verbs - project listing/eviction, watcher
control, service-state, storage survey, jobs, and logs - are CLI-only on the
public surface and are not registered on the FastMCP instance.

The thin async wrappers below survive only as a programmatic client over the
daemon's admin routes (the same ``/admin`` routes the CLI uses through
:func:`vaultspec_rag.serviceclient._try_http_admin`). They centralise the
tool-name-to-route argument shaping in one place for the service integration
tests that drive those routes; production lifecycle and observability flow
through the CLI.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from ..serviceclient import _try_http_admin
from ._tools import (
    _delegate,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module: shared delegation seam
    _require_port,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module: shared delegation seam
)


async def _admin(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Resolve the port and delegate *tool_name* through the admin client."""
    port = _require_port()
    return await _delegate(partial(_try_http_admin, tool_name, args, port))


async def list_projects() -> dict[str, Any]:
    """Return a snapshot of every active project slot."""
    return await _admin("list_projects", {})


async def evict_project(root: str) -> dict[str, Any]:
    """Force-evict the project slot for *root*."""
    return await _admin("evict_project", {"root": root})


async def get_watcher_state(project_root: str | None = None) -> dict[str, Any]:
    """Report filesystem-watcher configuration and running state."""
    args: dict[str, Any] = {}
    if project_root:
        args["project_root"] = project_root
    return await _admin("get_watcher_state", args)


async def start_watcher(root: str) -> dict[str, Any]:
    """Eagerly start the filesystem watcher for *root*."""
    return await _admin("start_watcher", {"root": root})


async def stop_watcher(root: str) -> dict[str, Any]:
    """Stop the filesystem watcher for *root* (pull-only for that root)."""
    return await _admin("stop_watcher", {"root": root})


async def get_service_state(project_root: str | None = None) -> dict[str, Any]:
    """Return a consolidated read-only snapshot of the service's state."""
    args: dict[str, Any] = {}
    if project_root:
        args["project_root"] = project_root
    return await _admin("get_service_state", args)


async def survey_storage(
    status: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Survey stored RAG index namespaces (live / orphaned / unknown)."""
    args: dict[str, Any] = {}
    if status:
        args["status"] = status
    if limit is not None:
        args["limit"] = limit
    return await _admin("get_storage_survey", args)


async def get_logs(
    lines: int = 200,
    job_id: str | None = None,
    contains: str | None = None,
) -> dict[str, Any]:
    """Return the last *lines* of the rotated service log."""
    args: dict[str, Any] = {"lines": lines}
    if job_id:
        args["job_id"] = job_id
    if contains:
        args["contains"] = contains
    return await _admin("get_logs", args)


async def get_jobs(
    limit: int | None = None,
    phase: str | None = None,
    source: str | None = None,
    trigger: str | None = None,
    query: str | None = None,
    failed: bool = False,
    job_id: str | None = None,
    since: float | None = None,
) -> dict[str, Any]:
    """Return recent index/reindex activity from the in-flight registry."""
    args: dict[str, Any] = {}
    if limit is not None:
        args["limit"] = limit
    if phase:
        args["phase"] = phase
    if source:
        args["source"] = source
    if trigger:
        args["trigger"] = trigger
    if query:
        args["query"] = query
    if failed:
        args["failed"] = "true"
    if job_id:
        args["job_id"] = job_id
    if since is not None:
        args["since"] = since
    return await _admin("get_jobs", args)


async def reconfigure_watcher(
    root: str,
    debounce_ms: int | None = None,
    cooldown_s: float | None = None,
) -> dict[str, Any]:
    """Restart *root*'s watcher with new tuning values."""
    args: dict[str, Any] = {"root": root}
    if debounce_ms is not None:
        args["debounce_ms"] = debounce_ms
    if cooldown_s is not None:
        args["cooldown_s"] = cooldown_s
    return await _admin("reconfigure_watcher", args)
