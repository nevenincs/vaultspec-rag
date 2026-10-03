"""Client over the daemon's admin and job routes, for the service tests.

These are not MCP tools: the MCP surface is search, index refresh and
read-only retrieval, and the admin verbs are CLI-only in production. The
wrappers here shape a tool name and its arguments onto the same ``/admin``
routes the CLI reaches, so a service test can drive a route and assert on
what the daemon did.

The create-job wrapper belongs here for the same reason. ``/jobs`` accepts a
paused start and an idempotency key that the CLI's reindex path cannot send,
so no production caller reaches that request shape; building it beside the
tests keeps the production client free of a surface it never issues.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, TypedDict, Unpack

from ..mcp._tools import (
    _delegate,  # pyright: ignore[reportPrivateUsage]  # test client over the delegation seam
    _require_port,  # pyright: ignore[reportPrivateUsage]  # test client over the delegation seam
)
from ..serviceclient._transport import (
    _try_http_admin,
    _try_http_job_call,  # pyright: ignore[reportPrivateUsage]  # test client over the jobs-route seam
)

if TYPE_CHECKING:
    from ..indexer._run_ledger_models import RunAuthority
    from ..job_models import JobMode, JobSource


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


async def get_watcher_state(
    project_root: str | None = None,
    *,
    root: str | None = None,
    source: str | None = None,
    state: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Report filesystem-watcher configuration and running state."""
    args: dict[str, object] = {}
    for key, value in (
        ("project_root", project_root),
        ("root", root),
        ("source", source),
        ("state", state),
        ("limit", limit),
    ):
        if value is not None:
            args[key] = value
    return await _admin("get_watcher_state", args)


async def start_watcher(root: str) -> dict[str, Any]:
    """Eagerly start the filesystem watcher for *root*."""
    return await _admin("start_watcher", {"root": root})


async def stop_watcher(root: str) -> dict[str, Any]:
    """Stop the filesystem watcher for *root* (pull-only for that root)."""
    return await _admin("stop_watcher", {"root": root})


async def get_service_state(project_root: str | None = None) -> dict[str, Any]:
    """Return a consolidated read-only snapshot of the service's state."""
    return await _admin_for_root("get_service_state", project_root)


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


class CreateJobOptions(TypedDict, total=False):
    """Optional fields for a create-job request."""

    mode: JobMode | None
    start_paused: bool
    initiator_kind: str
    command: str
    idempotency_key: str | None
    timeout: float | None


@dataclass(frozen=True)
class _CreateJobRequest:
    """A create-job request before it is serialized to the jobs endpoint."""

    source: JobSource
    project_root: str
    port: int | None
    authority: RunAuthority
    mode: JobMode | None = None
    start_paused: bool = False
    initiator_kind: str = "cli"
    command: str = "server_job_create"
    idempotency_key: str | None = None
    timeout: float | None = None


def _default_job_mode() -> str:
    """Return the convergence mode a job takes when the caller names none."""
    from ..job_models import JobMode

    return JobMode.INCREMENTAL.value


def _try_http_create_job(
    source: JobSource,
    project_root: str,
    port: int | None,
    *,
    authority: RunAuthority,
    **options: Unpack[CreateJobOptions],
) -> dict[str, object] | None:
    """Post one create-job request to the running service's jobs route."""
    request = _CreateJobRequest(source, project_root, port, authority, **options)
    payload: dict[str, object] = {
        "operation": "index",
        "source": request.source,
        "project_root": request.project_root,
        "authority": request.authority.value,
        # Resolved here, not in the signature: the enum stays annotation-only
        # so this module keeps the domain out of its import graph.
        "mode": request.mode if request.mode is not None else _default_job_mode(),
        "start_paused": request.start_paused,
        "initiator": {"kind": request.initiator_kind, "command": request.command},
    }
    headers = (
        {"Idempotency-Key": request.idempotency_key}
        if request.idempotency_key is not None
        else None
    )
    return _try_http_job_call(
        request.port,
        "/jobs",
        "POST",
        payload=payload,
        headers=headers,
        timeout=request.timeout,
    )
