"""``server updates`` commands: automatic index update controls."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer

import vaultspec_rag.cli as _cli

from ._app import server_watcher_app
from ._http_search import _try_http_admin
from ._render import (
    _display_service_not_running,
    _emit_json,
    _emit_json_error_and_exit,
)
from ._service_status import _default_service_port


def _counted_unit(value: int, singular: str, plural: str | None = None) -> str:
    unit = singular if value == 1 else plural or f"{singular}s"
    return f"{value} {unit}"


def _format_milliseconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported"
    milliseconds = max(0.0, float(raw))
    if milliseconds == 0:
        return "immediately"
    if milliseconds < 1000:
        return _counted_unit(int(milliseconds), "millisecond")
    seconds = milliseconds / 1000.0
    if seconds.is_integer():
        return _counted_unit(int(seconds), "second")
    return f"{seconds:.1f} seconds"


def _format_seconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported"
    seconds = max(0.0, float(raw))
    if seconds == 0:
        return "immediately"
    if seconds < 60:
        if seconds.is_integer():
            return _counted_unit(int(seconds), "second")
        return f"{seconds:.1f} seconds"
    minutes, remainder = divmod(int(seconds), 60)
    if remainder:
        return (
            f"{_counted_unit(minutes, 'minute')} {_counted_unit(remainder, 'second')}"
        )
    return _counted_unit(minutes, "minute")


def _project_name(root: object) -> str:
    value = str(root)
    parts = value.replace("\\", "/").rstrip("/").split("/")
    return parts[-1] if parts and parts[-1] else value


def _resolve_project_argument(project: str) -> str:
    return str(Path(project).expanduser().resolve())


def _print_update_address(port: int) -> None:
    _cli.console.print(
        f"Address: http://127.0.0.1:{port}",
        markup=False,
        highlight=False,
    )


def _print_update_project(project: str) -> None:
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


def _print_update_result(port: int, status: str, project: str) -> None:
    _print_update_address(port)
    _cli.console.print(
        f"Automatic index updates: {status}",
        markup=False,
        highlight=False,
    )
    _print_update_project(project)


def _print_update_timing(result: dict[str, object]) -> None:
    update_delay = _format_milliseconds(result.get("debounce_ms"))
    repeat_update_delay = _format_seconds(result.get("cooldown_s"))
    if update_delay == "not reported":
        _cli.console.print(
            "File changes: not reported by service.",
            markup=False,
            highlight=False,
        )
    else:
        _cli.console.print(
            f"File changes: wait {update_delay} before updating.",
            markup=False,
            highlight=False,
        )
    if repeat_update_delay == "not reported":
        _cli.console.print(
            "Repeat updates: not reported by service.",
            markup=False,
            highlight=False,
        )
        return
    _cli.console.print(
        f"Repeat updates: wait {repeat_update_delay} before updating a project again.",
        markup=False,
        highlight=False,
    )


def _watcher_service_unreachable(
    command: str,
    json_mode: bool,
    port: int | None = None,
    **extra: object,
) -> None:
    """Emit the standard 'service not running' result and exit 3."""
    if json_mode:
        _emit_json_error_and_exit(
            command,
            "service_not_running",
            "Service is not running. Start it with `vaultspec-rag server start`.",
            3,
            **extra,
        )
    _display_service_not_running(port)
    raise typer.Exit(3)


def _watcher_admin_error(
    command: str,
    json_mode: bool,
    result: dict[str, object],
    port: int,
    *,
    root: str | None = None,
) -> None:
    error = str(result.get("error") or "service_error")
    message = str(result.get("message") or "Service did not complete the request.")
    if json_mode:
        _emit_json_error_and_exit(command, error, message, 1, root=root, port=port)
    _print_update_address(port)
    _cli.console.print(f"Automatic index updates: {message}", markup=False)
    if root is not None:
        _print_update_project(root)
    _cli.console.print("Next actions:", markup=False, highlight=False)
    _cli.console.print(
        f"  vaultspec-rag server status --port {port}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"  vaultspec-rag server logs --limit 200 --port {port}",
        markup=False,
        highlight=False,
    )
    raise typer.Exit(1)


_UPDATES_STATUS_COMMAND = "service.updates.status"
_UPDATES_START_COMMAND = "service.updates.start"
_UPDATES_STOP_COMMAND = "service.updates.stop"
_UPDATES_TIMING_COMMAND = "service.updates.timing"


@server_watcher_app.command("status")
def service_watcher_status(
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Show automatic index update settings and projects."""
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _watcher_service_unreachable(_UPDATES_STATUS_COMMAND, json_mode)
        return
    result = _try_http_admin("get_watcher_state", {}, resolved_port)
    if result is None:
        _watcher_service_unreachable(
            _UPDATES_STATUS_COMMAND, json_mode, port=resolved_port
        )
        return
    if result.get("ok") is False:
        _watcher_admin_error(_UPDATES_STATUS_COMMAND, json_mode, result, resolved_port)
        return
    raw_watching = result.get("watching")
    watching: list[object] = (
        cast("list[object]", raw_watching) if isinstance(raw_watching, list) else []
    )
    enabled = bool(result.get("watch_enabled", False))
    if json_mode:
        _emit_json(True, _UPDATES_STATUS_COMMAND, data=result)
        return
    mode = "enabled" if enabled else "disabled; indexes update when requested"
    _print_update_address(resolved_port)
    _cli.console.print(f"Automatic index updates: {mode}", markup=False)
    _print_update_timing(result)
    if not watching:
        _cli.console.print("No projects currently have automatic index updates.")
        return
    _cli.console.print(f"Projects updating automatically: {len(watching)}")
    for entry in watching:
        _cli.console.print(
            f"- Project: {_project_name(entry)}",
            markup=False,
            highlight=False,
        )
        _cli.console.print(
            f"  Path: {entry}",
            markup=False,
            highlight=False,
            soft_wrap=True,
        )


@server_watcher_app.command("start")
def service_watcher_start(
    project: Annotated[str, typer.Argument(help="Project to keep indexed.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Start automatic index updates for a project."""
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _watcher_service_unreachable(_UPDATES_START_COMMAND, json_mode, root=project)
        return
    resolved_project = _resolve_project_argument(project)
    result = _try_http_admin(
        "start_watcher",
        {"root": resolved_project},
        resolved_port,
    )
    if result is None:
        _watcher_service_unreachable(
            _UPDATES_START_COMMAND, json_mode, port=resolved_port, root=project
        )
        return
    if result.get("ok") is False:
        _watcher_admin_error(
            _UPDATES_START_COMMAND,
            json_mode,
            result,
            resolved_port,
            root=resolved_project,
        )
        return
    started = bool(result.get("started", False))
    enabled = bool(result.get("watch_enabled", False))
    if json_mode:
        _emit_json(True, _UPDATES_START_COMMAND, data=result)
        return
    if started:
        _print_update_result(resolved_port, "started", resolved_project)
    elif not enabled:
        _print_update_result(
            resolved_port,
            "disabled; this project will update when requested",
            resolved_project,
        )
        _cli.console.print(
            "Next action: vaultspec-rag server start --updates",
            markup=False,
            highlight=False,
        )
    else:
        _print_update_result(resolved_port, "could not start", resolved_project)
    raise typer.Exit(0)


@server_watcher_app.command("stop")
def service_watcher_stop(
    project: Annotated[
        str,
        typer.Argument(help="Project to stop updating automatically."),
    ],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Stop automatic index updates for a project."""
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _watcher_service_unreachable(_UPDATES_STOP_COMMAND, json_mode, root=project)
        return
    resolved_project = _resolve_project_argument(project)
    result = _try_http_admin(
        "stop_watcher",
        {"root": resolved_project},
        resolved_port,
    )
    if result is None:
        _watcher_service_unreachable(
            _UPDATES_STOP_COMMAND, json_mode, port=resolved_port, root=project
        )
        return
    if result.get("ok") is False:
        _watcher_admin_error(
            _UPDATES_STOP_COMMAND,
            json_mode,
            result,
            resolved_port,
            root=resolved_project,
        )
        return
    stopped = bool(result.get("stopped", False))
    if json_mode:
        _emit_json(True, _UPDATES_STOP_COMMAND, data=result)
        return
    if stopped:
        _print_update_result(resolved_port, "stopped", resolved_project)
    else:
        _print_update_result(
            resolved_port,
            "not running for this project",
            resolved_project,
        )
    raise typer.Exit(0)


@server_watcher_app.command("timing")
def service_watcher_timing(
    project: Annotated[str, typer.Argument(help="Project to update timing for.")],
    update_delay_ms: Annotated[
        int | None,
        typer.Option(
            "--update-delay-ms",
            help="Delay before indexing a burst of file changes, in milliseconds.",
        ),
    ] = None,
    repeat_update_delay_s: Annotated[
        float | None,
        typer.Option(
            "--repeat-update-delay-s",
            help=(
                "Minimum wait before automatically updating a project again, "
                "in seconds."
            ),
        ),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Change automatic index update timing."""
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _watcher_service_unreachable(
            _UPDATES_TIMING_COMMAND,
            json_mode,
            root=project,
        )
        return
    resolved_project = _resolve_project_argument(project)
    args: dict[str, object] = {"root": resolved_project}
    if update_delay_ms is not None:
        args["debounce_ms"] = update_delay_ms
    if repeat_update_delay_s is not None:
        args["cooldown_s"] = repeat_update_delay_s
    result = _try_http_admin("reconfigure_watcher", args, resolved_port)
    if result is None:
        _watcher_service_unreachable(
            _UPDATES_TIMING_COMMAND,
            json_mode,
            port=resolved_port,
            root=project,
        )
        return
    if result.get("ok") is False:
        _watcher_admin_error(
            _UPDATES_TIMING_COMMAND,
            json_mode,
            result,
            resolved_port,
            root=resolved_project,
        )
        return
    restarted = bool(result.get("restarted", False))
    if json_mode:
        _emit_json(True, _UPDATES_TIMING_COMMAND, data=result)
        return
    if restarted:
        _print_update_result(resolved_port, "timing updated", resolved_project)
        _print_update_timing(result)
    else:
        _print_update_result(
            resolved_port,
            "disabled; this project will update when requested",
            resolved_project,
        )
    raise typer.Exit(0)
