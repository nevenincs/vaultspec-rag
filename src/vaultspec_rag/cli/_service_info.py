"""``server info``: consolidated read-only service state.

Tier-1 observability subcommand (``service-observability`` ADR, plan
P02). Calls the ``get_service_state`` MCP tool over the
``_try_http_admin`` seam and renders a Rich summary (or the JSON
envelope). Service-not-running yields exit code 3.
"""

from __future__ import annotations

from typing import Annotated, cast

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ._app import server_app
from ._http_search import _try_http_admin
from ._render import _emit_json, _emit_json_error_and_exit
from ._service_projects import _truncate_root
from ._service_status import _default_service_port


@server_app.command("info")
def service_info(
    port: Annotated[
        int | None,
        typer.Option("--port", help="MCP port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope instead of a summary."),
    ] = False,
) -> None:
    """Show a consolidated snapshot of the running service's state."""
    resolved_port = port if port is not None else _default_service_port()
    result = _try_http_admin("get_service_state", {}, resolved_port)
    if result is None:
        if json_mode:
            _emit_json_error_and_exit(
                "service.info",
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
        _emit_json(True, "service.info", data=result)
        return

    raw_index = result.get("index")
    index = cast("dict[str, object]", raw_index) if isinstance(raw_index, dict) else {}
    raw_projects = result.get("projects")
    projects_data = (
        cast("dict[str, object]", raw_projects)
        if isinstance(raw_projects, dict)
        else {}
    )
    raw_watcher = result.get("watcher")
    watcher = (
        cast("dict[str, object]", raw_watcher) if isinstance(raw_watcher, dict) else {}
    )

    table = Table(title="Service state", show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Vault docs", str(index.get("vault_count", "?")))
    table.add_row("Code chunks", str(index.get("code_count", "?")))
    table.add_row("Target", _truncate_root(str(index.get("target_dir", ""))))
    table.add_row("GPU VRAM (GB)", str(index.get("vram_gb", "?")))

    raw_slots = projects_data.get("projects")
    slots: list[object] = list(raw_slots) if isinstance(raw_slots, list) else []
    table.add_row(
        "Project slots",
        f"{len(slots)}/{projects_data.get('max_projects', '?')}",
    )

    enabled = bool(watcher.get("watch_enabled", False))
    raw_watching = watcher.get("watching")
    watching: list[object] = (
        list(raw_watching) if isinstance(raw_watching, list) else []
    )
    table.add_row(
        "Watcher",
        f"{'enabled' if enabled else 'disabled (pull-only)'}; {len(watching)} root(s)",
    )
    _cli.console.print(table)
