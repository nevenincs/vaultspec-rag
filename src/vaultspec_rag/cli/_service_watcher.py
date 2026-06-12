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


@server_watcher_app.command("status")
def service_watcher_status(
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope instead of text."),
    ] = False,
) -> None:
    """Show automatic index update settings and active roots."""
    resolved_port = port if port is not None else _default_service_port()
    result = _try_http_admin("get_watcher_state", {}, resolved_port)
    if result is None:
        _watcher_service_unreachable("service.watcher.status", json_mode)
        return
    raw_watching = result.get("watching")
    watching: list[object] = (
        cast("list[object]", raw_watching) if isinstance(raw_watching, list) else []
    )
    enabled = bool(result.get("watch_enabled", False))
    if json_mode:
        _emit_json(True, "service.watcher.status", data=result)
        return
    mode = "enabled" if enabled else "disabled; indexes update when requested"
    _cli.console.print(f"Automatic index updates: {mode}", markup=False)
    _print_update_timing(result)
    if not watching:
        _cli.console.print("No roots currently have automatic index updates.")
        return
    _cli.console.print(f"Projects updating automatically: {len(watching)}")
    for entry in watching:
        _cli.console.print(f"- {entry}", markup=False, highlight=False)


@server_watcher_app.command("start")
def service_watcher_start(
    root: Annotated[str, typer.Argument(help="Project root to keep indexed.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope instead of prose."),
    ] = False,
) -> None:
    """Start automatic index updates for a project root."""
    resolved_port = port if port is not None else _default_service_port()
    result = _try_http_admin("start_watcher", {"root": root}, resolved_port)
    if result is None:
        _watcher_service_unreachable("service.watcher.start", json_mode, root=root)
        return
    started = bool(result.get("started", False))
    enabled = bool(result.get("watch_enabled", False))
    if json_mode:
        _emit_json(True, "service.watcher.start", data=result)
        return
    if started:
        _cli.console.print(f"Automatic index updates started for: {root}", markup=False)
    elif not enabled:
        _cli.console.print(
            f"Automatic index updates are disabled; {root} will update on demand. "
            "Start the service with --watch to enable.",
            markup=False,
            highlight=False,
        )
    else:
        _cli.console.print(
            f"Could not start automatic index updates for: {root}",
            markup=False,
        )
    raise typer.Exit(0)


@server_watcher_app.command("stop")
def service_watcher_stop(
    root: Annotated[
        str,
        typer.Argument(help="Project root to stop updating automatically."),
    ],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope instead of prose."),
    ] = False,
) -> None:
    """Stop automatic index updates for a project root."""
    resolved_port = port if port is not None else _default_service_port()
    result = _try_http_admin("stop_watcher", {"root": root}, resolved_port)
    if result is None:
        _watcher_service_unreachable("service.watcher.stop", json_mode, root=root)
        return
    stopped = bool(result.get("stopped", False))
    if json_mode:
        _emit_json(True, "service.watcher.stop", data=result)
        return
    if stopped:
        _cli.console.print(f"Automatic index updates stopped for: {root}", markup=False)
    else:
        _cli.console.print(f"No automatic index updates were running for: {root}")
    raise typer.Exit(0)


@server_watcher_app.command("reconfigure")
def service_watcher_reconfigure(
    root: Annotated[str, typer.Argument(help="Project root to reconfigure.")],
    debounce_ms: Annotated[
        int | None,
        typer.Option(
            "--debounce-ms",
            help="Delay before indexing a burst of file changes, in milliseconds.",
        ),
    ] = None,
    cooldown_s: Annotated[
        float | None,
        typer.Option(
            "--cooldown-s",
            help="Minimum wait before indexing the same source again, in seconds.",
        ),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope instead of prose."),
    ] = False,
) -> None:
    """Change automatic index update timing."""
    resolved_port = port if port is not None else _default_service_port()
    args: dict[str, object] = {"root": root}
    if debounce_ms is not None:
        args["debounce_ms"] = debounce_ms
    if cooldown_s is not None:
        args["cooldown_s"] = cooldown_s
    result = _try_http_admin("reconfigure_watcher", args, resolved_port)
    if result is None:
        _watcher_service_unreachable(
            "service.watcher.reconfigure",
            json_mode,
            root=root,
        )
        return
    restarted = bool(result.get("restarted", False))
    if json_mode:
        _emit_json(True, "service.watcher.reconfigure", data=result)
        return
    if restarted:
        _cli.console.print(f"Automatic index updates reconfigured for: {root}")
        _print_update_timing(result)
    else:
        _cli.console.print(
            f"Automatic index updates are disabled; {root} will update on demand.",
            markup=False,
            highlight=False,
        )
    raise typer.Exit(0)
