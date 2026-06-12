"""``server projects`` commands: list and unload active projects."""

from __future__ import annotations

from typing import Annotated, Any, NoReturn, cast

import typer

import vaultspec_rag.cli as _cli

from ._app import server_projects_app
from ._http_search import _try_http_admin
from ._render import _emit_json, _emit_json_error_and_exit
from ._service_status import _default_service_port

__all__ = [
    "_truncate_root",
    "service_projects_evict",
    "service_projects_list",
]


def _humanize_idle(seconds: float) -> str:
    """Format an idle duration as ``1h 5m``, ``2m 14s``, or ``12s``."""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h {m}m"


def _humanize_duration(seconds: int) -> str:
    """Format a configuration duration for user-facing output."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes, remainder = divmod(seconds, 60)
        if remainder:
            return f"{minutes}m {remainder}s"
        return f"{minutes}m"
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if minutes:
        return f"{hours}h {minutes}m"
    return f"{hours}h"


def _truncate_root(root: str, width: int = 60) -> str:
    if len(root) <= width:
        return root
    return "…" + root[-(width - 1) :]


def _handle_list_not_running(json_mode: bool) -> NoReturn:
    if json_mode:
        _emit_json_error_and_exit(
            "service.projects.list",
            "service_not_running",
            "Service is not running. Start it with `vaultspec-rag server start`.",
            3,
        )
    _cli.console.print(
        "Service is not running. Start it with `vaultspec-rag server start`.",
        markup=False,
        highlight=False,
    )
    raise typer.Exit(3)


def _project_summary(raw_entry: object) -> tuple[str, str] | None:
    if not isinstance(raw_entry, dict):
        return None
    entry = cast("dict[str, object]", raw_entry)
    root_str = str(entry.get("root", ""))
    idle_raw = entry.get("idle_seconds", 0.0)
    idle_s = float(idle_raw) if isinstance(idle_raw, int | float) else 0.0
    refs_raw = entry.get("ref_count", 0)
    refs = int(refs_raw) if isinstance(refs_raw, int | float) else 0
    iso = str(entry.get("last_access_iso", ""))
    hms = iso.split("T", 1)[1][:8] if "T" in iso else iso
    last_access = hms or "unknown"
    request_word = "request" if refs == 1 else "requests"
    metadata = (
        f"unused for {_humanize_idle(idle_s)}; in use by {refs} {request_word}; "
        f"last used {last_access}"
    )
    return root_str, metadata


def _print_projects_summary(
    projects: list[object], max_projects: int, idle_ttl: int
) -> None:
    if not projects:
        _cli.console.print(
            "No projects are loaded. "
            f"Capacity: 0/{max_projects}; unloaded after "
            f"{_humanize_duration(idle_ttl)} unused.",
        )
        return

    _cli.console.print(
        f"Loaded projects: {len(projects)}/{max_projects}; unloaded after "
        f"{_humanize_duration(idle_ttl)} unused.",
    )
    for raw_entry in projects:
        summary = _project_summary(raw_entry)
        if summary:
            root, metadata = summary
            _cli.console.print(
                f"- {root}", markup=False, highlight=False, soft_wrap=True
            )
            _cli.console.print(f"  {metadata}", markup=False, highlight=False)


@server_projects_app.command("list")
def service_projects_list(
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit one JSON envelope to stdout instead of text.",
        ),
    ] = False,
) -> None:
    """List projects currently loaded by the running search service."""
    resolved_port = port if port is not None else _default_service_port()
    result = _try_http_admin("list_projects", {}, resolved_port)
    if result is None:
        _handle_list_not_running(json_mode)

    raw_projects = result.get("projects")
    projects: list[object] = (
        cast("list[object]", raw_projects) if isinstance(raw_projects, list) else []
    )
    max_projects = result.get("max_projects", 0)
    idle_ttl = result.get("idle_ttl_seconds", 0)

    if json_mode:
        _emit_json(
            True,
            "service.projects.list",
            data={
                "projects": projects,
                "max_projects": max_projects,
                "idle_ttl_seconds": idle_ttl,
            },
        )
        return

    _print_projects_summary(projects, int(max_projects), int(idle_ttl))


def _handle_evict_not_running(json_mode: bool, root: str) -> NoReturn:
    if json_mode:
        _emit_json_error_and_exit(
            "service.projects.evict",
            "service_not_running",
            "Service is not running. Start it with `vaultspec-rag server start`.",
            3,
            root=root,
        )
    _cli.console.print(
        "Service is not running. Start it with `vaultspec-rag server start`.",
        markup=False,
        highlight=False,
    )
    raise typer.Exit(3)


def _handle_evict_json(
    evicted: bool, reason: str, root: str, result: dict[str, Any]
) -> None:
    if evicted:
        _emit_json(
            True,
            "service.projects.evict",
            data={"evicted": True, "reason": reason or "ok", "root": root},
        )
        raise typer.Exit(0)
    exit_code = 1 if reason == "busy" else 2 if reason == "not_found" else 1
    _emit_json_error_and_exit(
        "service.projects.evict",
        reason or "unexpected_response",
        f"Eviction failed for {root}: reason={reason or 'unknown'}.",
        exit_code,
        root=root,
        evicted=False,
        raw_response=result,
    )


@server_projects_app.command("evict", hidden=True)
@server_projects_app.command("unload")
def service_projects_evict(
    root: Annotated[str, typer.Argument(help="Project root to unload.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit one JSON envelope to stdout instead of prose.",
        ),
    ] = False,
) -> None:
    """Unload a project from the running search service."""
    resolved_port = port if port is not None else _default_service_port()
    result = _try_http_admin(
        "evict_project",
        {"root": root},
        resolved_port,
    )
    if result is None:
        _handle_evict_not_running(json_mode, root)

    reason = str(result.get("reason", ""))
    evicted = bool(result.get("evicted", False))

    if json_mode:
        _handle_evict_json(evicted, reason, root, result)

    if evicted:
        _cli.console.print(f"Project unloaded: {root}", markup=False)
        raise typer.Exit(0)
    if reason == "busy":
        _cli.console.print(
            f"Project is in use: {root}. Retry shortly.",
            markup=False,
        )
        raise typer.Exit(1)
    if reason == "not_found":
        _cli.console.print(f"Project is not loaded: {root}", markup=False)
        raise typer.Exit(2)
    _cli.console.print(f"Unexpected response: {result}", markup=False)
    raise typer.Exit(1)
