"""Primary CLI application for vaultspec-rag."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import typer
from rich.console import Console

# Force UTF-8 on Windows to handle Unicode progress spinners
if sys.platform == "win32":
    from io import TextIOWrapper

    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if isinstance(sys.stderr, TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
from rich.panel import Panel
from rich.table import Table

load_dotenv()

from .embeddings import EmbeddingModel  # noqa: E402
from .indexer import CodebaseIndexer, VaultIndexer  # noqa: E402
from .logging_config import configure_logging  # noqa: E402
from .search import VaultSearcher  # noqa: E402
from .store import VaultStore  # noqa: E402
from .workspace import WorkspaceError, WorkspaceLayout, resolve_workspace  # noqa: E402

console = Console(legacy_windows=False)


def _handle_gpu_error(exc: Exception) -> None:
    """Print a user-friendly message for GPU/torch errors and exit.

    Args:
        exc: The caught exception (ImportError or RuntimeError).

    Raises:
        typer.Exit: Always exits with code 1.
    """
    if isinstance(exc, ImportError):
        console.print(
            "[bold red]Error:[/] GPU dependencies not installed.\n"
            "Run: [cyan]uv pip install sentence-transformers torch[/]",
        )
    elif "CUDA" in str(exc) or "cuda" in str(exc):
        console.print(
            "[bold red]Error:[/] No CUDA GPU detected.\n"
            "vaultspec-rag requires a CUDA-capable NVIDIA GPU.",
        )
    else:
        console.print(f"[bold red]Error:[/] {exc}")
    raise typer.Exit(code=1)


app = typer.Typer(
    help="VaultSpec RAG: Unified search over documentation and code.",
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
)

# Command Groups
server_app = typer.Typer(help="Manage RAG servers and backend services.")
mcp_app = typer.Typer(help="Control the Model Context Protocol (MCP) server.")
service_app = typer.Typer(help="Manage local or containerized RAG services.")

app.add_typer(server_app, name="server")
server_app.add_typer(mcp_app, name="mcp")
server_app.add_typer(service_app, name="service")


class CLIState:
    """Shared state for CLI commands.

    Attributes:
        layout: The resolved workspace layout.
        target: The target directory path from the layout.
    """

    def __init__(self, layout: WorkspaceLayout) -> None:
        """Initialize CLI state from a resolved workspace layout.

        Args:
            layout: Validated workspace layout containing
                target, vault, and vaultspec directories.
        """
        self.layout = layout
        self.target = layout.target_dir
        os.environ["VAULTSPEC_ROOT"] = str(self.target)


def version_callback(value: bool) -> None:
    """Show the version and exit when ``--version`` is passed.

    Args:
        value: True when the ``--version`` flag is provided.

    Raises:
        typer.Exit: Exits after printing the version.
    """
    if value:
        import importlib.metadata

        try:
            version = importlib.metadata.version("vaultspec-rag")
            console.print(f"vaultspec-rag v{version}")
        except importlib.metadata.PackageNotFoundError:
            console.print("vaultspec-rag (unknown version)")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    target: Annotated[
        Path | None,
        typer.Option(
            "--target",
            "-t",
            help="Directory containing .vault and .vaultspec",
            dir_okay=True,
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable INFO logging"),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", "-d", help="Enable DEBUG logging"),
    ] = False,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show version",
            callback=version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Global callback that configures logging and workspace.

    Args:
        ctx: Typer context carrying invoked subcommand info.
        target: Directory containing ``.vault`` and
            ``.vaultspec``. Resolved to absolute path.
        verbose: Enable INFO-level logging.
        debug: Enable DEBUG-level logging.
        _version: Eagerly print version and exit.

    Raises:
        typer.Exit: On workspace resolution failure (code 1)
            or when no subcommand is given (code 0).
    """
    configure_logging(debug=debug, level="INFO" if verbose else None)

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

    if ctx.invoked_subcommand in ("test", "quality", "server"):
        return

    try:
        layout = resolve_workspace(target_override=target)
        ctx.obj = CLIState(layout)
    except WorkspaceError as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1) from None


@app.command("index")
def handle_index(
    ctx: typer.Context,
    index_type: Annotated[
        Literal["vault", "code", "all"],
        typer.Option(
            "--type",
            help="What to index: 'vault' (docs), 'code' (source), or 'all'.",
            show_default=True,
        ),
    ] = "all",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override the embedding model name."),
    ] = None,
    clean: Annotated[
        bool,
        typer.Option(
            "--clean",
            help="Delete the existing index before starting.",
        ),
    ] = False,
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            help="Port of running MCP server (fast path).",
        ),
    ] = None,
) -> None:
    """Index vault documents and/or codebase chunks.

    When ``--port`` is given, delegates to a running MCP server
    via ``_try_mcp_reindex``. Falls back to in-process indexing
    if the server is unavailable.

    Args:
        ctx: Typer context carrying ``CLIState``.
        index_type: What to index: ``vault``, ``code``, or
            ``all``.
        model: Override the default embedding model name.
        clean: Delete the existing index before rebuilding.
        port: Port of a running MCP server for fast-path
            delegation.

    Raises:
        typer.Exit: On GPU errors or locked index files.
    """
    if port is not None:
        do_vault = index_type in ("vault", "all")
        do_code = index_type in ("code", "all")
        v_data = None
        c_data = None

        if do_vault:
            v_data = _try_mcp_reindex(
                "reindex_vault",
                clean,
                port,
            )
        if do_code:
            c_data = _try_mcp_reindex(
                "reindex_codebase",
                clean,
                port,
            )

        if v_data is not None or c_data is not None:
            table = Table(
                title="Indexing Summary (via MCP)",
                show_header=True,
            )
            table.add_column("Source", style="bold")
            table.add_column("Added", style="green", justify="right")
            table.add_column(
                "Updated",
                style="yellow",
                justify="right",
            )
            table.add_column(
                "Removed",
                style="red",
                justify="right",
            )
            table.add_column(
                "Total",
                style="cyan",
                justify="right",
            )
            table.add_column("Time", justify="right")
            if v_data:
                table.add_row(
                    "Vault",
                    str(v_data.get("added", 0)),
                    str(v_data.get("updated", 0)),
                    str(v_data.get("removed", 0)),
                    str(v_data.get("total", 0)),
                    f"{v_data.get('duration_ms', 0)}ms",
                )
            if c_data:
                table.add_row(
                    "Codebase",
                    str(c_data.get("added", 0)),
                    str(c_data.get("updated", 0)),
                    str(c_data.get("removed", 0)),
                    str(c_data.get("total", 0)),
                    f"{c_data.get('duration_ms', 0)}ms",
                )
            console.print(table)
            return

        console.print(
            "[yellow]MCP server unavailable, falling back to in-process indexing...[/]",
        )

    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

    state: CLIState = ctx.obj
    target = state.target

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    )

    do_vault = index_type in ("vault", "all")
    do_code = index_type in ("code", "all")

    with progress:
        # Phase 0: Initialize
        init_task = progress.add_task("Initializing RAG components...", total=3)
        store = VaultStore(target)

        if clean:
            console.log(f"Cleaning existing index at [cyan]{store.db_path}[/]...")
            store.close()
            if store.db_path.exists():
                try:
                    shutil.rmtree(store.db_path)
                except PermissionError as e:
                    console.print(
                        f"[bold red]Error:[/] Cannot delete index — a file is locked "
                        f"by another process.\n{e}\n"
                        "Close any other processes using the index and retry.",
                    )
                    raise typer.Exit(code=1) from None
            store = VaultStore(target)

        try:
            progress.advance(init_task)
            try:
                emb_model = EmbeddingModel(model_name=model)
            except (ImportError, RuntimeError) as e:
                _handle_gpu_error(e)
            progress.advance(init_task)
            v_indexer = VaultIndexer(target, emb_model, store) if do_vault else None
            c_indexer = CodebaseIndexer(target, emb_model, store) if do_code else None
            progress.advance(init_task)

            v_res = None
            c_res = None

            # Phase 1: Vault indexing
            if do_vault:
                assert v_indexer is not None
                vault_task = progress.add_task(
                    "Indexing documentation vault...", total=1
                )
                v_res = (
                    v_indexer.full_index(clean=True)
                    if clean
                    else v_indexer.incremental_index()
                )
                progress.advance(vault_task)
                console.log(
                    f"Vault: [green]{v_res.added}[/] added, "
                    f"[yellow]{v_res.updated}[/] updated, "
                    f"[red]{v_res.removed}[/] removed "
                    f"({v_res.duration_ms}ms)",
                )

            # Phase 2: Codebase indexing
            if do_code:
                assert c_indexer is not None
                code_task = progress.add_task("Indexing codebase...", total=1)
                c_res = (
                    c_indexer.full_index(clean=True)
                    if clean
                    else c_indexer.incremental_index()
                )
                progress.advance(code_task)
                console.log(
                    f"Codebase: [green]{c_res.added}[/] added, "
                    f"[yellow]{c_res.updated}[/] updated, "
                    f"[red]{c_res.removed}[/] removed "
                    f"({c_res.duration_ms}ms)",
                )
        finally:
            store.close()

    # Summary table
    table = Table(title="Indexing Summary", show_header=True)
    table.add_column("Source", style="bold")
    table.add_column("Added", style="green", justify="right")
    table.add_column("Updated", style="yellow", justify="right")
    table.add_column("Removed", style="red", justify="right")
    table.add_column("Total", style="cyan", justify="right")
    table.add_column("Time", justify="right")
    if v_res is not None:
        table.add_row(
            "Vault",
            str(v_res.added),
            str(v_res.updated),
            str(v_res.removed),
            str(v_res.total),
            f"{v_res.duration_ms}ms",
        )
    if c_res is not None:
        table.add_row(
            "Codebase",
            str(c_res.added),
            str(c_res.updated),
            str(c_res.removed),
            str(c_res.total),
            f"{c_res.duration_ms}ms",
        )
    console.print(table)


def _try_mcp_reindex(
    tool_name: str,
    clean: bool,
    port: int,
) -> dict[str, object] | None:
    """Reindex via a running MCP server over HTTP.

    Args:
        tool_name: MCP tool to call (``reindex_vault`` or
            ``reindex_codebase``).
        clean: Whether to drop and recreate the collection.
        port: TCP port of the running MCP server.

    Returns:
        Parsed JSON response dict on success, or None if the
        server is unavailable or an error occurs.
    """
    import asyncio

    async def _call() -> dict[str, object] | None:
        try:
            import json

            from mcp.client.session import ClientSession
            from mcp.client.streamable_http import (
                streamable_http_client,
            )
            from mcp.types import TextContent

            url = f"http://127.0.0.1:{port}/mcp"
            async with (
                streamable_http_client(url) as (
                    read,
                    write,
                    _,
                ),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(
                    tool_name,
                    {"clean": clean},
                )
                if result.content:
                    first = result.content[0]
                    if isinstance(first, TextContent):
                        return json.loads(first.text)
                return {}
        except Exception:
            return None

    try:
        return asyncio.run(_call())
    except Exception:
        return None


def _try_mcp_search(
    query: str,
    search_type: str,
    top_k: int,
    port: int,
) -> list[dict[str, object]] | None:
    """Search via a running MCP server over HTTP.

    Uses ``asyncio.run()`` which is safe here because Typer
    command handlers are always synchronous — there is no outer
    event loop to conflict with.

    Args:
        query: The search query text.
        search_type: One of ``vault``, ``code``, or ``all``.
        top_k: Maximum number of results to return.
        port: TCP port of the running MCP server.

    Returns:
        List of result dicts on success, or None if the server
        is unavailable or an error occurs.
    """
    import asyncio

    tool_map = {"vault": "search_vault", "code": "search_codebase", "all": "search_all"}
    tool_name = tool_map.get(search_type, "search_vault")

    async def _call() -> list[dict[str, object]] | None:
        try:
            import json

            from mcp.client.session import ClientSession
            from mcp.client.streamable_http import streamable_http_client
            from mcp.types import TextContent

            url = f"http://127.0.0.1:{port}/mcp"
            async with (
                streamable_http_client(url) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(
                    tool_name,
                    {"query": query, "top_k": top_k},
                )
                if result.content:
                    first = result.content[0]
                    if isinstance(first, TextContent):
                        data = json.loads(first.text)
                        return data.get("results", [])
                return []
        except Exception:
            return None

    try:
        return asyncio.run(_call())
    except Exception:
        return None


def _display_search_results(
    results: list[dict[str, object]],
    search_type: str,
) -> None:
    """Display MCP search results as a Rich table.

    Args:
        results: List of result dicts with ``score``, ``path``,
            ``snippet``, and optional ``line_start`` keys.
        search_type: Label for the table title (e.g.
            ``vault``, ``code``, ``all``).
    """
    table = Table(title=f"Search Results: {search_type}", box=None)
    table.add_column("Score", justify="right", style="cyan", no_wrap=True)
    table.add_column("Location", style="green")
    table.add_column("Snippet", style="white")

    for r in results:
        snippet = str(r.get("snippet", "")).replace("\n", " ")[:120]
        location = str(r.get("path", ""))
        line_start = r.get("line_start")
        if line_start:
            location += f":{line_start}"
        raw_score = r.get("score", 0.0)
        score = float(raw_score) if isinstance(raw_score, (int, float, str)) else 0.0
        table.add_row(f"{score:.2f}", location, snippet)

    console.print(table)


@app.command("search")
def handle_search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="The search query text.")],
    search_type: Annotated[
        Literal["vault", "code", "all"],
        typer.Option(
            "--type",
            help="Search source: 'vault' (docs), 'code' (source), or 'all' (both).",
            show_default=True,
        ),
    ] = "vault",
    max_results: Annotated[
        int,
        typer.Option("--max-results", help="Maximum number of results to return."),
    ] = 5,
    language: Annotated[
        str | None,
        typer.Option(
            "--language",
            help="Language filter for code search.",
        ),
    ] = None,
    node_type: Annotated[
        str | None,
        typer.Option(
            "--node-type",
            help="AST node type filter.",
        ),
    ] = None,
    function_name: Annotated[
        str | None,
        typer.Option("--function-name", help="Function/method name filter."),
    ] = None,
    class_name: Annotated[
        str | None,
        typer.Option("--class-name", help="Class/struct name filter."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Port of running MCP server (fast path)."),
    ] = None,
) -> None:
    """Search for relevant context in documentation or code.

    When ``--port`` is given, delegates to a running MCP server.
    Falls back to in-process search if the server is unavailable.

    Args:
        ctx: Typer context carrying ``CLIState``.
        query: The search query text.
        search_type: Search source: ``vault``, ``code``, or
            ``all``.
        max_results: Maximum number of results to return.
        language: Language filter for code search.
        node_type: AST node type filter for code search.
        function_name: Function/method name filter for code
            search.
        class_name: Class/struct name filter for code search.
        port: Port of a running MCP server for fast-path
            delegation.

    Raises:
        typer.Exit: On GPU initialization errors.
    """
    if port is not None:
        mcp_results = _try_mcp_search(query, search_type, max_results, port)
        if mcp_results is not None:
            if not mcp_results:
                console.print(
                    f"[yellow]No {search_type} results found for:[/] "
                    f"[italic]{query}[/]",
                )
                return
            _display_search_results(mcp_results, search_type)
            return
        console.print(
            "[yellow]MCP server unavailable, falling back to in-process search...[/]",
        )

    state: CLIState = ctx.obj
    target = state.target

    store = VaultStore(target)
    try:
        with console.status(f"[bold green]Searching {search_type}..."):
            try:
                model = EmbeddingModel()
            except (ImportError, RuntimeError) as e:
                _handle_gpu_error(e)
            searcher = VaultSearcher(target, model, store)

            if search_type == "vault":
                results = searcher.search_vault(query, top_k=max_results)
            elif search_type == "code":
                results = searcher.search_codebase(
                    query,
                    top_k=max_results,
                    language=language,
                    node_type=node_type,
                    function_name=function_name,
                    class_name=class_name,
                )
            else:
                results = searcher.search_all(query, top_k=max_results)
    finally:
        store.close()

    if not results:
        console.print(
            f"[yellow]No {search_type} results found for:[/] [italic]{query}[/]",
        )
        return

    table = Table(title=f"Search Results: {search_type}", box=None)
    table.add_column("Score", justify="right", style="cyan", no_wrap=True)
    table.add_column("Location", style="green")
    table.add_column("Snippet", style="white")

    for r in results:
        snippet = r.snippet.replace("\n", " ")[:120]
        location = r.path
        if r.line_start:
            location += f":{r.line_start}"
        table.add_row(f"{r.score:.2f}", location, snippet)

    console.print(table)


@app.command("status")
def handle_status(ctx: typer.Context) -> None:
    """Show RAG engine status, storage metrics, and GPU info.

    Args:
        ctx: Typer context carrying ``CLIState``.

    Raises:
        typer.Exit: On missing GPU dependencies.
    """
    state: CLIState = ctx.obj
    target = state.target

    try:
        import torch
    except ImportError as e:
        _handle_gpu_error(e)

    # GPU info
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram_mb = props.total_memory // (1024 * 1024)
        gpu_status = f"[green]cuda[/] - {gpu_name} ({vram_mb} MB VRAM)"
    else:
        gpu_status = "[red]No CUDA GPU available[/]"

    # Store metrics
    store = VaultStore(target)
    try:
        vault_count = store.count()
        code_count = store.count_code()

        table = Table(title="RAG Engine Status", show_header=False, padding=(0, 2))
        table.add_column("Key", style="bold")
        table.add_column("Value")
        table.add_row("Device", gpu_status)
        table.add_row("Storage Path", f"[cyan]{store.db_path}[/]")
        table.add_row("Vault Documents", f"[green]{vault_count}[/]")
        table.add_row("Codebase Chunks", f"[green]{code_count}[/]")
        table.add_row("Target Directory", f"[cyan]{target}[/]")
        console.print(table)
    finally:
        store.close()


# --- MCP Server Commands ---


@mcp_app.command("start")
def mcp_start(
    ctx: typer.Context,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Run on HTTP port instead of stdio"),
    ] = None,
) -> None:
    """Start the MCP server in the foreground.

    Args:
        ctx: Typer context for reading root ``--target``.
        port: Run on HTTP port instead of stdio transport.
    """
    from .mcp_server import main as run_mcp

    # Propagate --target from the root callback to the MCP server via env var.
    # The main callback skips workspace resolution for "server" subcommands,
    # so we read --target directly from the root context params here.
    root_target = ctx.find_root().params.get("target")
    if root_target is not None:
        os.environ["VAULTSPEC_ROOT"] = str(root_target)

    transport = f"streamable-http on port {port}" if port else "stdio"
    console.print(f"[bold green]Launching FastMCP server ({transport})...[/]")
    run_mcp(port=port)


@mcp_app.command("stop")
def mcp_stop() -> None:
    """Stop the MCP server.

    The MCP server uses stdio transport and runs in the foreground.
    Terminate it via Ctrl+C or the parent process manager.
    """
    console.print(
        Panel(
            "The MCP server uses stdio transport and runs in the foreground.\n"
            "Terminate it via [bold]Ctrl+C[/] or the parent process manager.",
            title="MCP Stop",
            border_style="yellow",
        ),
    )


@mcp_app.command("status")
def mcp_status() -> None:
    """Display the MCP server's configuration and readiness."""
    table = Table(title="MCP Server Configuration", show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Server Name", "VaultSpec Search")
    table.add_row("Transport", "stdio")
    table.add_row(
        "Tools",
        "search_vault, search_codebase, search_all, "
        "get_index_status, get_code_file, "
        "reindex_vault, reindex_codebase",
    )
    table.add_row("Resources", "vault://{doc_id}")
    table.add_row("Prompts", "analyze_feature")
    table.add_row("Entry Point", "vaultspec-search-mcp")
    console.print(table)


# --- Service helpers ---


def _status_dir() -> Path:
    """Return the global service status directory, creating it if needed.

    Returns:
        Path to ``~/.vaultspec-rag/``.
    """
    d = Path.home() / ".vaultspec-rag"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _status_file() -> Path:
    """Return the path to the service status JSON file.

    Returns:
        Path to ``~/.vaultspec-rag/service.json``.
    """
    return _status_dir() / "service.json"


def _log_file() -> Path:
    """Return the path to the service log file.

    Returns:
        Path to ``~/.vaultspec-rag/service.log``.
    """
    return _status_dir() / "service.log"


def _write_service_status(pid: int, port: int) -> None:
    """Write service status to the global status file.

    Args:
        pid: Process ID of the running service.
        port: TCP port the service is listening on.
    """
    data = {
        "pid": pid,
        "port": port,
        "started_at": datetime.now(UTC).isoformat(),
    }
    path = _status_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _read_service_status() -> dict[str, Any] | None:
    """Read and parse the service status file.

    Returns:
        Parsed status dict, or None if the file is missing,
        unreadable, or lacks ``pid``/``port`` keys.
    """
    sf = _status_file()
    if not sf.exists():
        return None
    try:
        data = json.loads(sf.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "pid" not in data or "port" not in data:
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def _is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running.

    Args:
        pid: Process ID to check.

    Returns:
        True if the process exists and is running.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[union-attr]
        handle = kernel32.OpenProcess(
            0x1000,  # PROCESS_QUERY_LIMITED_INFORMATION
            False,
            pid,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == 259  # STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _port_is_available(port: int) -> bool:
    """Check whether a TCP port is available for binding.

    Attempts to bind to ``127.0.0.1:port``. Used as a lightweight
    lock to prevent concurrent ``service start`` races: the port
    itself is the mutex.

    Args:
        port: TCP port to probe.

    Returns:
        True if the port is free, False if already in use.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Reject HTTP redirects to prevent SSRF via health endpoint."""

    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        _ = req, fp, code, msg, headers, newurl
        return None


def _health_probe(port: int) -> dict[str, Any] | None:
    """Probe the service health endpoint via HTTP GET.

    Args:
        port: TCP port to connect to on 127.0.0.1.

    Returns:
        Parsed JSON dict on success, a dict with ``status``
        ``"error"`` and ``http_code`` for HTTP errors (server
        running but unhealthy), or None for connection errors
        (server not running).
    """
    url = f"http://127.0.0.1:{port}/health"
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"status": "error", "http_code": exc.code}
    except Exception:
        return None


def _spawn_service(port: int, log_path: Path) -> int:
    """Spawn the MCP server as a detached background process.

    Args:
        port: TCP port for the HTTP server.
        log_path: File path for stdout/stderr redirection.

    Returns:
        PID of the spawned process.
    """
    cmd = [sys.executable, "-m", "vaultspec_rag.mcp_server", "--port", str(port)]
    log_fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    if sys.platform == "win32":
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            creationflags=0x00000200 | 0x08000000,  # NEW_PROCESS_GROUP | NO_WINDOW
        )
    else:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid


def _terminate_pid(pid: int) -> None:
    """Send a termination signal to a process.

    On Windows sends ``CTRL_BREAK_EVENT`` for graceful uvicorn
    shutdown, then force-kills if the process survives. On Unix
    sends ``SIGTERM``, falling back to ``SIGKILL``.

    Args:
        pid: Process ID to terminate.
    """
    if sys.platform == "win32":
        with contextlib.suppress(OSError):
            os.kill(pid, signal.CTRL_BREAK_EVENT)
    else:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
    # Allow graceful drain before force-killing
    time.sleep(2)
    if _is_pid_alive(pid):
        with contextlib.suppress(OSError):
            if sys.platform == "win32":
                os.kill(pid, signal.SIGTERM)  # TerminateProcess on Windows
            else:
                os.kill(pid, signal.SIGKILL)


# --- Service Commands ---


@service_app.command("start")
def service_start(
    port: Annotated[
        int,
        typer.Option(
            "--port",
            help="TCP port for the HTTP service.",
            envvar="VAULTSPEC_RAG_PORT",
        ),
    ] = 8766,
) -> None:
    """Start the background RAG service as a detached process.

    Spawns the MCP server on the given port, polls ``/health``
    with exponential backoff until ready, and writes a status
    file to ``~/.vaultspec-rag/service.json``.

    Args:
        port: TCP port (default 8766 or ``VAULTSPEC_RAG_PORT``).

    Raises:
        typer.Exit: On failure to start or timeout.
    """
    # Port-level guard: prevents concurrent start races (ADR D1)
    if not _port_is_available(port):
        console.print(
            Panel(
                f"Port {port} is already in use.",
                title="Service Start",
                border_style="yellow",
            ),
        )
        return

    # Check for existing service
    status = _read_service_status()
    if status is not None:
        existing_pid = int(status["pid"])
        existing_port = int(status.get("port", port))
        if _is_pid_alive(existing_pid):
            health = _health_probe(existing_port)
            if health is not None:
                console.print(
                    Panel(
                        f"Service already running (PID {existing_pid}, "
                        f"port {existing_port}).",
                        title="Service Start",
                        border_style="yellow",
                    ),
                )
                return
        # Stale PID -- remove status file
        _status_file().unlink(missing_ok=True)

    log_path = _log_file()
    t0 = time.perf_counter()
    pid = _spawn_service(port, log_path)
    _write_service_status(pid, port)

    # Poll health with exponential backoff
    delay = 0.1
    deadline = 30.0
    elapsed = 0.0
    with console.status("[bold green]Starting service..."):
        while elapsed < deadline:
            time.sleep(delay)
            elapsed = time.perf_counter() - t0

            # Check if process died (port conflict, etc.)
            if not _is_pid_alive(pid):
                _status_file().unlink(missing_ok=True)
                console.print(
                    Panel(
                        f"Service process exited immediately (PID {pid}).\n"
                        f"Port {port} may be in use. Check {log_path}",
                        title="Service Start Failed",
                        border_style="red",
                    ),
                )
                raise typer.Exit(code=1)

            health = _health_probe(port)
            if health is not None and health.get("status") == "ready":
                startup_s = time.perf_counter() - t0
                console.print(
                    Panel(
                        f"PID: {pid}\n"
                        f"Port: {port}\n"
                        f"Startup: {startup_s:.1f}s\n"
                        f"Log: {log_path}",
                        title="Service Started",
                        border_style="green",
                    ),
                )
                return

            delay = min(delay * 2, 5.0)

    console.print(
        Panel(
            f"Timed out waiting for service health after {deadline:.0f}s.\n"
            f"PID {pid} is running but not ready. Check {log_path}",
            title="Service Start Timeout",
            border_style="red",
        ),
    )
    raise typer.Exit(code=1)


@service_app.command("stop")
def service_stop() -> None:
    """Stop the background RAG service.

    Reads the status file, verifies the PID is alive, sends
    a termination signal, waits briefly, and removes the
    status file.
    """
    status = _read_service_status()
    if status is None:
        console.print(
            Panel(
                "No service status file found. Service is not running.",
                title="Service Stop",
                border_style="yellow",
            ),
        )
        return

    pid = int(status["pid"])
    if not _is_pid_alive(pid):
        _status_file().unlink(missing_ok=True)
        console.print(
            Panel(
                f"Service PID {pid} is no longer running. Cleaned up status file.",
                title="Service Stop",
                border_style="yellow",
            ),
        )
        return

    _terminate_pid(pid)

    # Wait briefly for process to exit
    for _ in range(50):
        if not _is_pid_alive(pid):
            break
        time.sleep(0.1)

    _status_file().unlink(missing_ok=True)
    console.print(
        Panel(
            f"Service stopped (PID {pid}).",
            title="Service Stop",
            border_style="green",
        ),
    )


@service_app.command("status")
def service_status() -> None:
    """Show the status of the background RAG service.

    Reads the status file, checks PID liveness, probes the
    health endpoint, and displays a Rich table with service
    state.
    """
    status = _read_service_status()
    table = Table(title="Service Status", show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")

    if status is None:
        table.add_row("State", "[red]stopped[/]")
        console.print(table)
        return

    pid = int(status["pid"])
    port = int(status.get("port", 8766))
    started_at = status.get("started_at", "unknown")

    if not _is_pid_alive(pid):
        _status_file().unlink(missing_ok=True)
        table.add_row("State", "[red]stopped[/] (stale PID cleaned)")
        console.print(table)
        return

    table.add_row("State", "[green]running[/]")
    table.add_row("PID", str(pid))
    table.add_row("Port", str(port))
    table.add_row("Started", started_at)

    health = _health_probe(port)
    if health is not None:
        table.add_row("Health", health.get("status", "unknown"))
        table.add_row("CUDA", str(health.get("cuda", "unknown")))
        table.add_row("Models loaded", str(health.get("models_loaded", "unknown")))
        projects = health.get("projects", [])
        table.add_row("Projects", str(len(projects)))
        for p in projects:
            table.add_row("", str(p))
        uptime = health.get("uptime_s", 0.0)
        table.add_row("Uptime", f"{uptime:.0f}s")
    else:
        table.add_row("Health", "[yellow]unreachable[/]")

    console.print(table)


# --- Model prefetch (warmup) ---


@service_app.command("warmup")
def service_warmup() -> None:
    """Pre-download GPU model files to the HuggingFace cache.

    Checks CUDA availability, then downloads each of the three
    model repositories (dense, sparse, reranker) if not already
    cached. Reports per-model status.

    Raises:
        typer.Exit: If CUDA is not available or huggingface_hub
            is not installed.
    """
    try:
        import torch
    except ImportError:
        console.print("[bold red]Error:[/] torch is not installed.")
        raise typer.Exit(code=1) from None

    if not torch.cuda.is_available():
        console.print("[bold red]Error:[/] No CUDA GPU detected.")
        raise typer.Exit(code=1) from None

    try:
        from huggingface_hub import snapshot_download, try_to_load_from_cache
    except ImportError:
        console.print("[bold red]Error:[/] huggingface_hub is not installed.")
        raise typer.Exit(code=1) from None

    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

    from .config import get_config

    cfg = get_config()
    models = [
        ("Dense (Qwen3)", cfg.embedding_model),
        ("Sparse (SPLADE)", cfg.sparse_model),
        ("Reranker (CrossEncoder)", cfg.reranker_model),
    ]

    table = Table(title="Model Warmup", show_header=True)
    table.add_column("Model", style="bold")
    table.add_column("Repo", style="cyan")
    table.add_column("Status")

    for label, repo_id in models:
        # Check if already cached
        cached = try_to_load_from_cache(repo_id, "config.json")
        if cached is not None:
            table.add_row(label, repo_id, "[green]cached[/]")
            continue

        try:
            with console.status(f"[bold green]Downloading {label}..."):
                snapshot_download(repo_id)
            table.add_row(label, repo_id, "[green]downloaded[/]")
        except Exception as exc:
            msg = str(exc)
            if "401" in msg or "403" in msg or "GatedRepo" in msg:
                table.add_row(
                    label,
                    repo_id,
                    "[red]auth required[/]: run huggingface-cli login",
                )
            else:
                table.add_row(label, repo_id, f"[red]failed[/]: {exc}")

    console.print(table)


@app.command("benchmark")
def handle_benchmark(
    ctx: typer.Context,
    n_queries: Annotated[
        int,
        typer.Option("--n-queries", help="Number of search queries to time."),
    ] = 20,
) -> None:
    """Run search latency benchmarks against the indexed vault.

    Requires an indexed vault (run ``vaultspec-rag index``
    first). Reports p50/p95/p99 latency, store counts, and
    GPU VRAM usage.

    Args:
        ctx: Typer context carrying ``CLIState``.
        n_queries: Number of search queries to time.

    Raises:
        typer.Exit: When vault is empty (code 1) or on GPU
            errors.
    """
    import statistics
    import time

    state: CLIState = ctx.obj
    target = state.target

    store = VaultStore(target)
    try:
        vault_count = store.count()
        if vault_count == 0:
            console.print(
                "[yellow]Warning:[/] No vault documents indexed. "
                "Run [cyan]vaultspec-rag index[/] first.",
            )
            raise typer.Exit(code=1)

        try:
            model = EmbeddingModel()
        except (ImportError, RuntimeError) as e:
            _handle_gpu_error(e)

        searcher = VaultSearcher(target, model, store)

        _bench_queries = [
            "architecture decision",
            "pipeline execution model",
            "connector protocol design",
            "security audit vulnerability",
            "implementation plan phase",
            "type:adr architecture",
            "feature:pipeline-engine execution",
            "scheduler algorithm selection",
            "pipeline executor implementation",
            "dag execution research",
            "data transformation pipeline",
            "worker pool thread",
            "type:plan implementation",
            "semantic search embedding",
            "Qdrant vector store",
            "date:2026-01 decisions",
            "checkpoint storage performance",
            "connector grpc streaming",
            "execution graph dependency",
            "incremental indexing hash",
        ]

        with console.status("[bold green]Warming up..."):
            searcher.search("warmup", top_k=1)

        latencies: list[float] = []
        with console.status(
            f"[bold green]Running {n_queries} benchmark queries...",
        ):
            for i in range(n_queries):
                q = _bench_queries[i % len(_bench_queries)]
                t0 = time.perf_counter()
                searcher.search(q, top_k=5)
                latencies.append((time.perf_counter() - t0) * 1000)

        latencies.sort()
        p50 = latencies[n_queries // 2]
        p95 = latencies[int(n_queries * 0.95)]
        p99 = latencies[int(n_queries * 0.99)]
        mean = statistics.mean(latencies)
        stdev = statistics.stdev(latencies) if len(latencies) > 1 else 0.0

        try:
            import torch

            gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A"
            vram_mb = (
                torch.cuda.memory_allocated(0) / (1024 * 1024)
                if torch.cuda.is_available()
                else 0.0
            )
        except ImportError:
            gpu = "N/A"
            vram_mb = 0.0

        table = Table(
            title=f"Search Latency — {n_queries} queries",
            show_header=True,
        )
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right", style="cyan")
        table.add_row("p50", f"{p50:.1f} ms")
        table.add_row("p95", f"{p95:.1f} ms")
        table.add_row("p99", f"{p99:.1f} ms")
        table.add_row("mean", f"{mean:.1f} ms")
        table.add_row("stdev", f"{stdev:.1f} ms")
        table.add_row("vault docs", str(vault_count))
        table.add_row("code chunks", str(store.count_code()))
        table.add_row("GPU", gpu)
        table.add_row("VRAM allocated", f"{vram_mb:.1f} MB")
        console.print(table)
    finally:
        store.close()


_QUALITY_PROBES: list[tuple[str, int, str]] = [
    # (query, top_k, label)  — check functions defined in handle_quality
    ("nexus security audit vulnerability", 10, "Security audit doc in top 10"),
    ("NexusPipelineExecutor", 5, "NexusPipelineExecutor → pipeline doc in top 5"),
    ("connector api gRPC protocol", 10, "Connector API docs in top 10"),
    ("scheduler EDF worker pool", 10, "Scheduler docs in top 10"),
    ("type:adr architecture", 10, "type:adr returns only ADR docs"),
    ("feature:connector-api protocol", 10, "feature:connector-api filter exact"),
    ("type:nonexistent query", 5, "Invalid type filter returns empty"),
    ("asdfghjkl zxcvbnm", 5, "Nonsense query scores below 0.10"),
]


@app.command("quality")
def handle_quality() -> None:
    """Run quality-scoring probes against the bundled test corpus.

    Indexes the test-project corpus, runs 8 known-answer probes,
    and reports precision@K. Exits 1 if fewer than 75% of probes
    pass.

    This is a developer regression tool -- not tied to a specific
    user vault.

    Raises:
        typer.Exit: When test corpus is missing (code 1),
            on GPU errors, or when precision drops below 75%.
    """
    import shutil
    import tempfile

    test_project = Path(__file__).resolve().parent.parent.parent / "test-project"
    if not test_project.exists():
        console.print(
            f"[bold red]Error:[/] Test corpus not found at {test_project}.\n"
            "The bundled test-project/ directory is required.",
        )
        raise typer.Exit(code=1)

    with tempfile.TemporaryDirectory(prefix="vaultspec-quality-") as _tmp:
        qdrant_dir = Path(_tmp)

        try:
            model = EmbeddingModel()
        except (ImportError, RuntimeError) as e:
            _handle_gpu_error(e)

        store = VaultStore(test_project)
        # Redirect Qdrant client to the temp dir so we don't pollute test-project
        assert store._client is not None
        store._client.close()
        store.db_path = qdrant_dir
        from qdrant_client import QdrantClient

        store._client = QdrantClient(path=str(qdrant_dir))

        try:
            indexer = VaultIndexer(test_project, model, store)
            with console.status("[bold green]Indexing test corpus..."):
                indexer.full_index()

            searcher = VaultSearcher(test_project, model, store)

            def _check(query: str, results: list) -> bool:
                if "type:adr" in query and "nonexistent" not in query:
                    return len(results) > 0 and all(
                        r.doc_type == "adr" for r in results
                    )
                if "feature:connector-api" in query:
                    return len(results) > 0 and all(
                        r.feature == "connector-api" for r in results
                    )
                if "type:nonexistent" in query:
                    return len(results) == 0
                if "asdfghjkl" in query:
                    return not results or max(r.score for r in results) < 0.10
                if "security" in query:
                    return any("security-audit" in r.id for r in results)
                if "NexusPipeline" in query:
                    return any("pipeline" in r.id for r in results)
                if "connector" in query.lower():
                    return any("connector" in r.id for r in results)
                if "scheduler" in query.lower():
                    return any("scheduler" in r.id for r in results)
                return True

            table = Table(
                title="Quality Probes — Test Corpus",
                show_header=True,
            )
            table.add_column("#", style="bold", justify="right")
            table.add_column("Label")
            table.add_column("Query", style="italic")
            table.add_column("Result", justify="center")

            passed = 0
            for i, (query, top_k, label) in enumerate(_QUALITY_PROBES, 1):
                results = searcher.search(query, top_k=top_k)
                ok = _check(query, results)
                if ok:
                    passed += 1
                status = "[green]PASS[/]" if ok else "[red]FAIL[/]"
                table.add_row(str(i), label, query, status)

            total = len(_QUALITY_PROBES)
            precision = passed / total
            console.print(table)
            console.print(
                f"\nPassed [bold]{passed}/{total}[/] probes "
                f"([cyan]{precision:.0%}[/] precision)",
            )

            threshold = 0.75
            if precision < threshold:
                console.print(
                    f"[bold red]FAILED[/] — precision {precision:.0%} "
                    f"below {threshold:.0%} threshold.",
                )
                raise typer.Exit(code=1)
            console.print("[bold green]PASSED[/]")
        finally:
            store.close()
            shutil.rmtree(qdrant_dir, ignore_errors=True)


@app.command(
    "test",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def handle_test(ctx: typer.Context) -> None:
    """Run the test suite via pytest.

    All extra arguments are forwarded to pytest.

    Args:
        ctx: Typer context whose ``args`` are passed through
            to pytest.

    Raises:
        SystemExit: Propagates pytest's exit code.

    Examples::

        vaultspec-rag test
        vaultspec-rag test -m unit
        vaultspec-rag test -m integration -v --timeout=120
    """
    test_dir = str(Path(__file__).resolve().parent / "tests")
    cmd = [sys.executable, "-m", "pytest", test_dir, *ctx.args]
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    app()
