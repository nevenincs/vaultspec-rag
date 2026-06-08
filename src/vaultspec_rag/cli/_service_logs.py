"""``server logs``: tail the rotated service log.

Tier-2a observability subcommand (``service-observability`` ADR, plan
P03). Calls the ``get_logs`` MCP tool over the ``_try_http_admin`` seam
and prints the lines (or the JSON envelope). Service-not-running yields
exit code 3.
"""

from __future__ import annotations

from typing import Annotated

import typer

import vaultspec_rag.cli as _cli

from ._app import server_app
from ._http_search import _try_http_admin
from ._render import _emit_json, _emit_json_error_and_exit
from ._service_status import _default_service_port


@server_app.command("logs")
def service_logs(
    lines: Annotated[
        int,
        typer.Option("--lines", help="Number of trailing log lines to show."),
    ] = 200,
    port: Annotated[
        int | None,
        typer.Option("--port", help="MCP port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope instead of plain text."),
    ] = False,
) -> None:
    """Show the last N lines of the running service's rotated log."""
    resolved_port = port if port is not None else _default_service_port()
    result = _try_http_admin("get_logs", {"lines": lines}, resolved_port)
    if result is None:
        if json_mode:
            _emit_json_error_and_exit(
                "service.logs",
                "service_not_running",
                "Service is not running. Start it with `vaultspec-rag server start`.",
                3,
            )
        _cli.console.print(
            "[red]Service is not running.[/] "
            "Start it with [bold]vaultspec-rag server start[/].",
        )
        raise typer.Exit(3)

    if json_mode:
        _emit_json(True, "service.logs", data=result)
        return

    raw_lines = result.get("lines")
    log_lines: list[object] = list(raw_lines) if isinstance(raw_lines, list) else []
    if not log_lines:
        _cli.console.print("[dim]No log lines available.[/]")
        return
    for line in log_lines:
        _cli.console.print(str(line), markup=False, highlight=False)
