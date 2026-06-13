"""``server projects`` commands: list and unload active projects."""

from __future__ import annotations

from typing import Annotated, Any, NoReturn, cast

import typer

import vaultspec_rag.cli as _cli

from ._app import server_projects_app
from ._http_search import _try_http_admin
from ._render import (
    _display_service_not_running,
    _emit_json,
    _emit_json_error_and_exit,
)
from ._service_status import _default_service_port

__all__ = [
    "_truncate_root",
    "service_projects_list",
    "service_projects_unload",
]


def _counted_unit(value: int, singular: str, plural: str | None = None) -> str:
    unit = singular if value == 1 else plural or f"{singular}s"
    return f"{value} {unit}"


def _humanize_idle(seconds: float) -> str:
    """Format an idle duration with full unit names."""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return _counted_unit(int(seconds), "second")
    if seconds < 3600:
        m, s = divmod(int(seconds), 60)
        if s:
            return f"{_counted_unit(m, 'minute')} {_counted_unit(s, 'second')}"
        return _counted_unit(m, "minute")
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    if m:
        return f"{_counted_unit(h, 'hour')} {_counted_unit(m, 'minute')}"
    return _counted_unit(h, "hour")


def _humanize_duration(seconds: int) -> str:
    """Format a configuration duration for user-facing output."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return _counted_unit(seconds, "second")
    if seconds < 3600:
        minutes, remainder = divmod(seconds, 60)
        if remainder:
            return (
                f"{_counted_unit(minutes, 'minute')} "
                f"{_counted_unit(remainder, 'second')}"
            )
        return _counted_unit(minutes, "minute")
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if minutes:
        return f"{_counted_unit(hours, 'hour')} {_counted_unit(minutes, 'minute')}"
    return _counted_unit(hours, "hour")


def _truncate_root(root: str, width: int = 60) -> str:
    if len(root) <= width:
        return root
    return "…" + root[-(width - 1) :]


def _project_name(root: str) -> str:
    parts = root.replace("\\", "/").rstrip("/").split("/")
    return parts[-1] if parts and parts[-1] else root


def _handle_list_not_running(json_mode: bool, port: int | None = None) -> NoReturn:
    if json_mode:
        _emit_json_error_and_exit(
            "service.projects.list",
            "service_not_running",
            "Service is not running. Start it with `vaultspec-rag server start`.",
            3,
        )
    _display_service_not_running(port)
    raise typer.Exit(3)


def _project_summary(raw_entry: object) -> list[str] | None:
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
    use_text = "none" if refs <= 0 else str(refs)
    lines = [
        f"- Project: {_project_name(root_str)}",
        f"  Path: {root_str}",
        f"  Active requests: {use_text}",
        f"  Last activity: {_humanize_idle(idle_s)} ago",
    ]
    if hms:
        lines.append(f"  Last request: {hms}")
    return lines


def _print_projects_summary(
    projects: list[object],
    max_projects: int,
    idle_ttl: int,
    *,
    port: int | None = None,
) -> None:
    if port is not None:
        _cli.console.print(
            f"Address: http://127.0.0.1:{port}",
            markup=False,
            highlight=False,
        )
    if not projects:
        _cli.console.print(
            f"Capacity: 0 of {max_projects} projects loaded",
        )
        _cli.console.print(
            f"Automatic unload: after {_humanize_duration(idle_ttl)} idle",
        )
        return

    _cli.console.print(
        f"Capacity: {len(projects)} of {max_projects} projects loaded",
    )
    _cli.console.print(
        f"Automatic unload: after {_humanize_duration(idle_ttl)} idle",
    )
    for raw_entry in projects:
        summary = _project_summary(raw_entry)
        if summary:
            for line in summary:
                _cli.console.print(
                    line,
                    markup=False,
                    highlight=False,
                    soft_wrap=True,
                )


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
            help="Emit JSON for scripts instead of human text.",
        ),
    ] = False,
) -> None:
    """List projects currently loaded by the running search service."""
    resolved_port = port if port is not None else _default_service_port()
    result = _try_http_admin("list_projects", {}, resolved_port)
    if result is None:
        _handle_list_not_running(json_mode, resolved_port)

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

    _print_projects_summary(
        projects,
        int(max_projects),
        int(idle_ttl),
        port=resolved_port,
    )


def _handle_unload_not_running(
    json_mode: bool, root: str, port: int | None = None
) -> NoReturn:
    if json_mode:
        _emit_json_error_and_exit(
            "service.projects.unload",
            "service_not_running",
            "Service is not running. Start it with `vaultspec-rag server start`.",
            3,
            root=root,
        )
    _display_service_not_running(port)
    raise typer.Exit(3)


def _project_unload_failure_message(root: str, reason: str) -> str:
    if reason == "busy":
        return f"Project is in use: {root}. Retry shortly."
    if reason == "not_found":
        return f"Project is not loaded: {root}."
    return (
        f"The service could not confirm that the project was unloaded: {root}. "
        "Run `vaultspec-rag server status` and retry."
    )


def _print_project_unload_result(
    *,
    port: int,
    project: str,
    status: str,
    next_action: str | None = None,
) -> None:
    _cli.console.print(
        f"Address: http://127.0.0.1:{port}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"Project: {_project_name(project)}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"Path: {project}",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    _cli.console.print(f"Unload: {status}", markup=False, highlight=False)
    if next_action:
        _cli.console.print(
            f"Next action: {next_action}",
            markup=False,
            highlight=False,
        )


def _handle_evict_json(
    evicted: bool, reason: str, root: str, result: dict[str, Any]
) -> None:
    if evicted:
        _emit_json(
            True,
            "service.projects.unload",
            data={"evicted": True, "reason": reason or "ok", "root": root},
        )
        raise typer.Exit(0)
    exit_code = 1 if reason == "busy" else 2 if reason == "not_found" else 1
    _emit_json_error_and_exit(
        "service.projects.unload",
        reason or "unexpected_response",
        _project_unload_failure_message(root, reason),
        exit_code,
        root=root,
        evicted=False,
        raw_response=result,
    )


@server_projects_app.command("unload")
def service_projects_unload(
    project: Annotated[str, typer.Argument(help="Project to unload.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit JSON for scripts instead of human text.",
        ),
    ] = False,
) -> None:
    """Unload a project from the running search service."""
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _handle_unload_not_running(json_mode, project)
    result = _try_http_admin(
        "evict_project",
        {"root": project},
        resolved_port,
    )
    if result is None:
        _handle_unload_not_running(json_mode, project, resolved_port)

    reason = str(result.get("reason", ""))
    evicted = bool(result.get("evicted", False))

    if json_mode:
        _handle_evict_json(evicted, reason, project, result)

    if evicted:
        _print_project_unload_result(
            port=resolved_port,
            project=project,
            status="unloaded",
        )
        raise typer.Exit(0)
    if reason == "busy":
        _print_project_unload_result(
            port=resolved_port,
            project=project,
            status="project is in use; retry shortly",
        )
        raise typer.Exit(1)
    if reason == "not_found":
        _print_project_unload_result(
            port=resolved_port,
            project=project,
            status="project is not loaded",
        )
        raise typer.Exit(2)
    _print_project_unload_result(
        port=resolved_port,
        project=project,
        status="service could not confirm unload",
        next_action=f"vaultspec-rag server status --port {resolved_port}",
    )
    raise typer.Exit(1)
