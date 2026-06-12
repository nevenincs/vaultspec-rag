"""``server updates`` commands: automatic index update controls."""

from __future__ import annotations

from typing import Annotated, cast

import typer

import vaultspec_rag.cli as _cli

from ._app import server_watcher_app
from ._http_search import _try_http_admin
from ._render import _emit_json, _emit_json_error_and_exit
from ._service_status import _default_service_port


def _format_milliseconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "unknown"
    milliseconds = max(0.0, float(raw))
    if milliseconds == 0:
        return "immediately"
    if milliseconds < 1000:
        return f"{int(milliseconds)}ms"
    seconds = milliseconds / 1000.0
    if seconds.is_integer():
        return f"{int(seconds)}s"
    return f"{seconds:.1f}s"


def _format_seconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "unknown"
    seconds = max(0.0, float(raw))
    if seconds == 0:
        return "immediately"
    if seconds < 60:
        if seconds.is_integer():
            return f"{int(seconds)}s"
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(seconds), 60)
    if remainder:
        return f"{minutes}m {remainder}s"
    return f"{minutes}m"


def _print_update_timing(result: dict[str, object]) -> None:
    _cli.console.print(
        f"File changes: wait {_format_milliseconds(result.get('debounce_ms'))} "
        "before updating.",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"Same source: wait {_format_seconds(result.get('cooldown_s'))} "
        "before updating again.",
        markup=False,
        highlight=False,
    )


def _watcher_service_unreachable(
    command: str,
    json_mode: bool,
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
    _cli.console.print(
        "Service is not running. Start it with `vaultspec-rag server start`.",
        markup=False,
        highlight=False,
    )
    raise typer.Exit(3)


_UPDATES_STATUS_COMMAND = "service.updates.status"
_UPDATES_START_COMMAND = "service.updates.start"
_UPDATES_STOP_COMMAND = "service.updates.stop"
_UPDATES_RECONFIGURE_COMMAND = "service.updates.reconfigure"


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
    result = _try_http_admin("get_watcher_state", {}, resolved_port)
    if result is None:
        _watcher_service_unreachable(_UPDATES_STATUS_COMMAND, json_mode)
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
    _cli.console.print(f"Automatic index updates: {mode}", markup=False)
    _print_update_timing(result)
    if not watching:
        _cli.console.print("No projects currently have automatic index updates.")
        return
    _cli.console.print(f"Projects updating automatically: {len(watching)}")
    for entry in watching:
        _cli.console.print(f"- {entry}", markup=False, highlight=False)


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
    result = _try_http_admin("start_watcher", {"root": project}, resolved_port)
    if result is None:
        _watcher_service_unreachable(_UPDATES_START_COMMAND, json_mode, root=project)
        return
    started = bool(result.get("started", False))
    enabled = bool(result.get("watch_enabled", False))
    if json_mode:
        _emit_json(True, _UPDATES_START_COMMAND, data=result)
        return
    if started:
        _cli.console.print(
            f"Automatic index updates started for: {project}", markup=False
        )
    elif not enabled:
        _cli.console.print(
            f"Automatic index updates are disabled; {project} will update on demand. "
            "Start the service with --updates to enable.",
            markup=False,
            highlight=False,
        )
    else:
        _cli.console.print(
            f"Could not start automatic index updates for: {project}",
            markup=False,
        )
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
    result = _try_http_admin("stop_watcher", {"root": project}, resolved_port)
    if result is None:
        _watcher_service_unreachable(_UPDATES_STOP_COMMAND, json_mode, root=project)
        return
    stopped = bool(result.get("stopped", False))
    if json_mode:
        _emit_json(True, _UPDATES_STOP_COMMAND, data=result)
        return
    if stopped:
        _cli.console.print(
            f"Automatic index updates stopped for: {project}", markup=False
        )
    else:
        _cli.console.print(f"No automatic index updates were running for: {project}")
    raise typer.Exit(0)


@server_watcher_app.command("reconfigure")
def service_watcher_reconfigure(
    project: Annotated[str, typer.Argument(help="Project to reconfigure.")],
    update_delay_ms: Annotated[
        int | None,
        typer.Option(
            "--update-delay-ms",
            help="Delay before indexing a burst of file changes, in milliseconds.",
        ),
    ] = None,
    debounce_ms: Annotated[
        int | None,
        typer.Option(
            "--debounce-ms",
            help="Legacy name for --update-delay-ms.",
            hidden=True,
        ),
    ] = None,
    same_source_delay_s: Annotated[
        float | None,
        typer.Option(
            "--same-source-delay-s",
            help="Minimum wait before indexing the same source again, in seconds.",
        ),
    ] = None,
    cooldown_s: Annotated[
        float | None,
        typer.Option(
            "--cooldown-s",
            help="Legacy name for --same-source-delay-s.",
            hidden=True,
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
    args: dict[str, object] = {"root": project}
    selected_update_delay_ms = (
        update_delay_ms if update_delay_ms is not None else debounce_ms
    )
    selected_same_source_delay_s = (
        same_source_delay_s if same_source_delay_s is not None else cooldown_s
    )
    if selected_update_delay_ms is not None:
        args["debounce_ms"] = selected_update_delay_ms
    if selected_same_source_delay_s is not None:
        args["cooldown_s"] = selected_same_source_delay_s
    result = _try_http_admin("reconfigure_watcher", args, resolved_port)
    if result is None:
        _watcher_service_unreachable(
            _UPDATES_RECONFIGURE_COMMAND,
            json_mode,
            root=project,
        )
        return
    restarted = bool(result.get("restarted", False))
    if json_mode:
        _emit_json(True, _UPDATES_RECONFIGURE_COMMAND, data=result)
        return
    if restarted:
        _cli.console.print(f"Automatic index updates reconfigured for: {project}")
        _print_update_timing(result)
    else:
        _cli.console.print(
            f"Automatic index updates are disabled; {project} will update on demand.",
            markup=False,
            highlight=False,
        )
    raise typer.Exit(0)
