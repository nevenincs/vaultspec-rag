"""``server mcp`` commands: start, stop, and status for the MCP server."""

from __future__ import annotations

import os
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

import vaultspec_rag.cli as _cli

from ..config import EnvVar
from ._app import mcp_app


@mcp_app.command("start")
def mcp_start(
    ctx: typer.Context,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Run on HTTP port instead of stdio"),
    ] = None,
) -> None:
    """Start the MCP server in the foreground.

    Launches the Model Context Protocol (MCP) server which provides tools for
    searching and reindexing the RAG engine. By default uses stdio transport
    (suitable for LLM integration), or HTTP on the specified port for standalone
    use. Propagates the ``--target`` root option to the server via the
    ``VAULTSPEC_ROOT`` environment variable.

    Args:
        ctx: Typer context for reading root ``--target`` parameter.
        port: TCP port for HTTP transport. If omitted, uses stdio.

    Raises:
        SystemExit: When the MCP server process exits (typically via Ctrl+C).

    """
    from ..server import main as run_mcp

    # Propagate --target to the MCP server via env var (stdio only).
    # HTTP mode is multi-tenant - project context comes per-request.
    root_target = ctx.find_root().params.get("target")
    if root_target is not None:
        if port is not None:
            _cli.console.print(
                "[yellow]Warning:[/] --target is ignored in HTTP mode "
                "(project_root must be passed per-request)",
            )
        else:
            os.environ[EnvVar.RAG_ROOT] = str(root_target)

    transport = f"streamable-http on port {port}" if port else "stdio"
    _cli.console.print(f"[bold green]Launching FastMCP server ({transport})...[/]")
    run_mcp(port=port)


@mcp_app.command("stop")
def mcp_stop() -> None:
    """Provide guidance for stopping the MCP server.

    The MCP server uses stdio transport and runs in the foreground by default.
    It does not have a built-in stop mechanism; instead, terminate it via
    Ctrl+C in the terminal where it was started, or stop the parent process
    manager (e.g., systemd, Docker, or your IDE).

    Note:
        For the background service (``service`` commands), use ``service stop``
        which sends graceful termination signals and manages the process
        lifecycle automatically.

    """
    _cli.console.print(
        Panel(
            "The MCP server uses stdio transport and runs in the foreground.\n"
            "Terminate it via [bold]Ctrl+C[/] or the parent process manager.",
            title="MCP Stop",
            border_style="yellow",
        ),
    )


@mcp_app.command("status")
def mcp_status() -> None:
    """Display the MCP server configuration, available tools, and entry points.

    Shows a table with server name, transport mode, registered tools
    (search_vault, search_codebase, reindex_vault, reindex_codebase,
    get_index_status, get_code_file), available resources, and prompts.
    """
    table = Table(title="MCP Server Configuration", show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Server Name", "VaultSpec Search")
    table.add_row("Transport", "stdio (default), HTTP via service start")
    table.add_row(
        "Tools",
        "search_vault, search_codebase, "
        "get_index_status, get_code_file, "
        "reindex_vault, reindex_codebase",
    )
    table.add_row("Resources", "vault://{doc_id}")
    table.add_row("Prompts", "analyze_feature")
    table.add_row("Entry Point", "vaultspec-search-mcp")
    _cli.console.print(table)
