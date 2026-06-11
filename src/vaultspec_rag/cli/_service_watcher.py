"""``server watcher`` commands: status, start, stop, reconfigure."""

from __future__ import annotations

from typing import Annotated, cast

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ._app import server_watcher_app
from ._http_search import _try_http_admin
from ._render import _emit_json, _emit_json_error_and_exit
from ._service_projects import _truncate_root
from ._service_status import _default_service_port


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
        "[red]Service is not running.[/] "
        "Start it with [bold]vaultspec-rag server start[/].",
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
        typer.Option("--json", help="Emit one JSON envelope instead of a table."),
    ] = False,
) -> None:
    """Show watcher config and which roots are being watched."""
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
    mode = "enabled" if enabled else "disabled (pull-only)"
    _cli.console.print(
        f"Auto-reindex: [bold]{mode}[/]  "
        f"debounce={result.get('debounce_ms')}ms  "
        f"cooldown={result.get('cooldown_s')}s",
    )
    if not watching:
        _cli.console.print("No roots currently watched.")
        return
    table = Table(title="Watched roots")
    table.add_column("Root", overflow="ellipsis")
    for entry in watching:
        table.add_row(_truncate_root(str(entry)))
    _cli.console.print(table)


@server_watcher_app.command("start")
def service_watcher_start(
    root: Annotated[str, typer.Argument(help="Project root to watch.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope instead of prose."),
    ] = False,
) -> None:
    """Eagerly start the watcher for a project root."""
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
        _cli.console.print(f"[green]Watching[/]: {root}")
    elif not enabled:
        _cli.console.print(
            f"[yellow]Auto-reindex is disabled[/] (pull-only); not watching {root}. "
            "Start the service with --watch to enable.",
        )
    else:
        _cli.console.print(f"[red]Could not start watcher[/]: {root}")
    raise typer.Exit(0)


@server_watcher_app.command("stop")
def service_watcher_stop(
    root: Annotated[str, typer.Argument(help="Project root to stop watching.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope instead of prose."),
    ] = False,
) -> None:
    """Stop the watcher for a project root (pull-only for that root)."""
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
        _cli.console.print(f"[green]Stopped[/] watching: {root}")
    else:
        _cli.console.print(f"No watcher was running for: {root}")
    raise typer.Exit(0)


@server_watcher_app.command("reconfigure")
def service_watcher_reconfigure(
    root: Annotated[str, typer.Argument(help="Project root to reconfigure.")],
    debounce_ms: Annotated[
        int | None,
        typer.Option("--debounce-ms", help="New debounce window (ms)."),
    ] = None,
    cooldown_s: Annotated[
        float | None,
        typer.Option("--cooldown-s", help="New per-source cooldown (s)."),
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
    """Restart a root's watcher with new debounce/cooldown values."""
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
        _cli.console.print(
            f"[green]Reconfigured[/] {root}: "
            f"debounce={result.get('debounce_ms')}ms "
            f"cooldown={result.get('cooldown_s')}s",
        )
    else:
        _cli.console.print(
            f"[yellow]Not restarted[/] (auto-reindex disabled): {root}",
        )
    raise typer.Exit(0)
