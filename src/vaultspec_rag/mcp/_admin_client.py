"""Async admin/observability client for the running RAG daemon.

These are **not** MCP tools. The MCP search surface is narrowed to search,
index-refresh, and read-only retrieval; the
mutating and observability admin verbs - project listing/eviction, watcher
control, service-state, storage survey, jobs, and logs - are CLI-only on the
public surface and are not registered on the MCPServer instance.

The thin async wrappers below survive only as a programmatic client over the
daemon's admin routes (the same ``/admin`` routes the CLI uses through
:func:`vaultspec_rag.serviceclient._try_http_admin`). They centralise the
tool-name-to-route argument shaping in one place for the service integration
tests that drive those routes; production lifecycle and observability flow
through the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, TypedDict, Unpack

from ..serviceclient._transport import _try_http_admin
from ._tools import (
    _delegate,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module: shared delegation seam
    _require_port,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module: shared delegation seam
)


class _JobQueryOptions(TypedDict, total=False):
    limit: int | None
    phase: str | None
    source: str | None
    trigger: str | None
    query: str | None
    failed: bool
    job_id: str | None
    since: float | None
    timeout: float


@dataclass(frozen=True)
class _JobQuery:
    limit: int | None = None
    phase: str | None = None
    source: str | None = None
    trigger: str | None = None
    query: str | None = None
    failed: bool = False
    job_id: str | None = None
    since: float | None = None
    timeout: float = 30.0


async def _admin(
    tool_name: str,
    args: dict[str, object],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Resolve the port and delegate *tool_name* through the admin client."""
    port = _require_port()
    return await _delegate(
        partial(_try_http_admin, tool_name, args, port, timeout=timeout)
    )


async def list_projects() -> dict[str, Any]:
    """Return a snapshot of every active project slot."""
    return await _admin("list_projects", {})


async def evict_project(root: str) -> dict[str, Any]:
    """Force-evict the project slot for *root*."""
    return await _admin("evict_project", {"root": root})


async def _admin_for_root(tool: str, project_root: str | None) -> dict[str, Any]:
    """Call *tool*, passing ``project_root`` only when the caller supplied one.

    An empty or absent root must be OMITTED rather than sent as ``""``: the
    service resolves its own default root for an absent argument, and an empty
    string would be a request to resolve nothing.
    """
    args: dict[str, object] = {}
    if project_root:
        args["project_root"] = project_root
    return await _admin(tool, args)


async def get_watcher_state(project_root: str | None = None) -> dict[str, Any]:
    """Report filesystem-watcher configuration and running state."""
    return await _admin_for_root("get_watcher_state", project_root)


async def start_watcher(root: str) -> dict[str, Any]:
    """Eagerly start the filesystem watcher for *root*."""
    return await _admin("start_watcher", {"root": root})


async def stop_watcher(root: str) -> dict[str, Any]:
    """Stop the filesystem watcher for *root* (pull-only for that root)."""
    return await _admin("stop_watcher", {"root": root})


async def get_service_state(project_root: str | None = None) -> dict[str, Any]:
    """Return a consolidated read-only snapshot of the service's state."""
    return await _admin_for_root("get_service_state", project_root)


async def survey_storage(
    status: str | None = None,
    limit: int | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    """Survey stored RAG index namespaces (live / orphaned / unknown).

    With ``root``, the survey narrows to that root's namespace and the
    response carries ``queried_root`` with the authoritative collection
    prefix computed by the service - callers never derive the hash
    themselves.
    """
    args: dict[str, object] = {}
    if status:
        args["status"] = status
    if limit is not None:
        args["limit"] = limit
    if root:
        args["root"] = root
    return await _admin("get_storage_survey", args)


async def get_logs(
    lines: int = 200,
    job_id: str | None = None,
    contains: str | None = None,
) -> dict[str, Any]:
    """Return the last *lines* of the rotated service log."""
    args: dict[str, object] = {"lines": lines}
    if job_id:
        args["job_id"] = job_id
    if contains:
        args["contains"] = contains
    return await _admin("get_logs", args)


async def get_jobs(**options: Unpack[_JobQueryOptions]) -> dict[str, Any]:
    """Return recent index/reindex activity from the in-flight registry."""
    return await _get_jobs(_JobQuery(**options))


async def _get_jobs(query: _JobQuery) -> dict[str, Any]:
    """Shape one job query for the running service's admin route."""
    limit, phase, source, trigger, text, failed, job_id, since, timeout = (
        query.limit,
        query.phase,
        query.source,
        query.trigger,
        query.query,
        query.failed,
        query.job_id,
        query.since,
        query.timeout,
    )
    args: dict[str, object] = {}
    if limit is not None:
        args["limit"] = limit
    if phase:
        args["phase"] = phase
    if source:
        args["source"] = source
    if trigger:
        args["trigger"] = trigger
    if text:
        args["query"] = text
    if failed:
        args["failed"] = "true"
    if job_id:
        args["job_id"] = job_id
    if since is not None:
        args["since"] = since
    return await _admin("get_jobs", args, timeout=timeout)


async def reconfigure_watcher(
    root: str,
    debounce_ms: int | None = None,
    cooldown_s: float | None = None,
) -> dict[str, Any]:
    """Restart *root*'s watcher with new tuning values."""
    args: dict[str, object] = {"root": root}
    if debounce_ms is not None:
        args["debounce_ms"] = debounce_ms
    if cooldown_s is not None:
        args["cooldown_s"] = cooldown_s
    return await _admin("reconfigure_watcher", args)
