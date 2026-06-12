"""``server mcp`` commands: start, stop, and status for the MCP server."""

from __future__ import annotations

import os
from typing import Annotated

import typer

import vaultspec_rag.cli as _cli

from ..config import EnvVar
from ._app import mcp_app


@mcp_app.command(
    "start",
    help=(
        "Start the MCP server in the foreground. "
        "Uses stdio transport by default (for LLM tool integration); "
        "pass --port to run HTTP instead."
    ),
)
def mcp_start(
    ctx: typer.Context,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Run on HTTP port instead of stdio"),
    ] = None,
) -> None:
    """Start the MCP server in the foreground."""
    from ..server import main as run_mcp

    # Propagate --target to the MCP server via env var (stdio only).
    # HTTP mode is multi-tenant - project context comes per-request.
    root_target = ctx.find_root().params.get("target")
    if root_target is not None:
        if port is not None:
            _cli.console.print(
                "Warning: --target is ignored in HTTP mode "
                "(project_root must be passed per request).",
                markup=False,
                highlight=False,
            )
        else:
            os.environ[EnvVar.RAG_ROOT] = str(root_target)

    transport = f"streamable-http on port {port}" if port else "stdio"
    _cli.console.print(f"Launching MCP service ({transport})...", markup=False)
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
    _cli.console.print("MCP server: foreground stdio process")
    _cli.console.print("Stop it with Ctrl+C or the parent process manager.")


@mcp_app.command("status")
def mcp_status() -> None:
    """Display the MCP server configuration, available tools, and entry points.

    Shows server name, transport mode, registered tools, available resources, and
    prompts.
    """
    _cli.console.print("Server: VaultSpec Search")
    _cli.console.print("Transport: stdio by default; HTTP through server start")
    _cli.console.print("Tools:")
    for tool in (
        "search_vault",
        "search_codebase",
        "get_index_status",
        "get_code_file",
        "reindex_vault",
        "reindex_codebase",
    ):
        _cli.console.print(f"- {tool}", markup=False, highlight=False)
    _cli.console.print("Resources: vault://{doc_id}")
    _cli.console.print("Prompts: analyze_feature")
    _cli.console.print("Entry point: vaultspec-search-mcp")
