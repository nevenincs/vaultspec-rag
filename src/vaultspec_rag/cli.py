"""CLI application for vaultspec-rag.

VaultSpec RAG is a GPU-accelerated Retrieval-Augmented Generation (RAG) engine
that provides unified hybrid search over project documentation and source code.
It uses dense embeddings (Qwen3), sparse embeddings (SPLADE), and learned
reranking (CrossEncoder) to find the most relevant context for code generation,
code review, and documentation discovery.

This module provides command handlers for indexing, searching, and managing the
RAG engine, including support for background service operation via MCP (Model
Context Protocol).
"""

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

from .config import EnvVar  # noqa: E402
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
    """Shared state container for CLI commands and sub-applications.

    Initialized by the main callback and passed via ``typer.Context.obj``
    to all subcommands. Holds validated workspace metadata and sets the
    ``VAULTSPEC_ROOT`` environment variable for downstream services.

    Attributes:
        layout: The resolved workspace layout containing validated
            directories (.vault, .vaultspec, target).
        target: The target directory path (project root) from the layout.

    """

    def __init__(self, layout: WorkspaceLayout) -> None:
        """Initialize CLI state from a resolved workspace layout.

        Args:
            layout: Validated workspace layout containing
                target, vault, and vaultspec directories.

        """
        self.layout = layout
        self.target = layout.target_dir
        os.environ[EnvVar.RAG_ROOT] = str(self.target)


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
    data_dir: Annotated[
        str | None,
        typer.Option(
            "--data-dir",
            help="RAG data root (default: .vault/data/search-data)",
        ),
    ] = None,
    qdrant_dir: Annotated[
        str | None,
        typer.Option(
            "--qdrant-dir",
            help="Qdrant storage directory relative to data-dir",
        ),
    ] = None,
    index_meta: Annotated[
        str | None,
        typer.Option(
            "--index-meta",
            help="Vault index metadata filename",
        ),
    ] = None,
    code_index_meta: Annotated[
        str | None,
        typer.Option(
            "--code-index-meta",
            help="Code index metadata filename",
        ),
    ] = None,
    status_dir: Annotated[
        str | None,
        typer.Option(
            "--status-dir",
            help="Service status directory (default: ~/.vaultspec-rag)",
        ),
    ] = None,
    log_file: Annotated[
        str | None,
        typer.Option(
            "--log-file",
            help="Service log filename relative to status-dir",
        ),
    ] = None,
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
        data_dir: Override RAG data root directory.
        qdrant_dir: Override Qdrant storage subdirectory.
        index_meta: Override vault index metadata filename.
        code_index_meta: Override code index metadata filename.
        status_dir: Override service status directory.
        log_file: Override service log filename.
        _version: Eagerly print version and exit.

    Raises:
        typer.Exit: On workspace resolution failure (code 1)
            or when no subcommand is given (code 0).

    """
    configure_logging(debug=debug, level="INFO" if verbose else None)

    # Wire CLI overrides into the config system.
    from .config import get_config

    cli_overrides: dict[str, Any] = {}
    if data_dir is not None:
        cli_overrides["data_dir"] = data_dir
    if qdrant_dir is not None:
        cli_overrides["qdrant_dir"] = qdrant_dir
    if index_meta is not None:
        cli_overrides["index_metadata_file"] = index_meta
    if code_index_meta is not None:
        cli_overrides["code_index_metadata_file"] = code_index_meta
    if status_dir is not None:
        cli_overrides["status_dir"] = status_dir
    if log_file is not None:
        cli_overrides["log_file"] = log_file
    if cli_overrides:
        get_config(cli_overrides)

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

    if ctx.invoked_subcommand in (
        "test",
        "quality",
        "server",
        "install",
        "uninstall",
    ):
        # These subcommands either operate without a resolved
        # workspace (test/quality/server) or resolve their own via
        # core's resolver (install/uninstall).
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
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="List files that would be indexed without indexing.",
        ),
    ] = False,
    exclude: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude",
            help="Ad-hoc exclusion pattern (repeatable, gitignore syntax).",
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
        dry_run: List files that would be indexed without
            actually indexing.  Codebase only.
        exclude: Ad-hoc exclusion patterns (gitignore syntax,
            repeatable).  Combined with ``.vaultragignore``.

    Raises:
        typer.Exit: On GPU errors or locked index files.

    """
    state: CLIState = ctx.obj
    target = state.target

    # --dry-run: list codebase files without loading GPU or Qdrant.
    # Must come before --port MCP delegation (D9).
    if dry_run:
        if index_type not in ("code", "all"):
            console.print("[yellow]--dry-run only applies to codebase indexing.[/]")
            return
        # Bypass __init__ to avoid loading GPU model and Qdrant store;
        # scan_files() only needs root_dir and _extra_excludes.
        c_indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        c_indexer.root_dir = target
        c_indexer._extra_excludes = exclude or []
        files = c_indexer.scan_files()
        console.print(f"[bold]{len(files)}[/] files would be indexed:")
        for f in sorted(files):
            console.print(f"  {f.relative_to(target)}")
        return

    if port is not None:
        if exclude:
            console.print(
                "[yellow]--exclude is ignored when delegating to MCP server.[/]",
            )
        do_vault = index_type in ("vault", "all")
        do_code = index_type in ("code", "all")
        v_data = None
        c_data = None

        if do_vault:
            v_data = _try_mcp_reindex(
                "reindex_vault",
                clean,
                port,
                str(target),
            )
        if do_code:
            c_data = _try_mcp_reindex(
                "reindex_codebase",
                clean,
                port,
                str(target),
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
            c_indexer = (
                CodebaseIndexer(target, emb_model, store, extra_excludes=exclude or [])
                if do_code
                else None
            )
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
    project_root: str,
) -> dict[str, object] | None:
    """Reindex via a running MCP server over HTTP.

    Args:
        tool_name: MCP tool to call (``reindex_vault`` or
            ``reindex_codebase``).
        clean: Whether to drop and recreate the collection.
        port: TCP port of the running MCP server.
        project_root: Absolute path to the target project. The
            HTTP service is multi-tenant and has no default
            project, so every tool call must carry this value.

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
                    {"clean": clean, "project_root": project_root},
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
    project_root: str,
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
        project_root: Absolute path to the target project. The
            HTTP service is multi-tenant and has no default
            project, so every tool call must carry this value.

    Returns:
        List of result dicts on success, or None if the server
        is unavailable or an error occurs.

    """
    import asyncio

    tool_map = {"vault": "search_vault", "code": "search_codebase"}
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
                    {
                        "query": query,
                        "top_k": top_k,
                        "project_root": project_root,
                    },
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
        Literal["vault", "code"],
        typer.Option(
            "--type",
            help="Search source: 'vault' (docs) or 'code' (source).",
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
        search_type: Search source: ``vault`` or ``code``.
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
    state: CLIState = ctx.obj
    target = state.target

    if port is not None:
        mcp_results = _try_mcp_search(
            query,
            search_type,
            max_results,
            port,
            str(target),
        )
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

    store = VaultStore(target)
    try:
        with console.status(f"[bold green]Searching {search_type}..."):
            try:
                model = EmbeddingModel()
            except (ImportError, RuntimeError) as e:
                _handle_gpu_error(e)
            searcher = VaultSearcher(target, model, store)

            if search_type == "code":
                results = searcher.search_codebase(
                    query,
                    top_k=max_results,
                    language=language,
                    node_type=node_type,
                    function_name=function_name,
                    class_name=class_name,
                )
            else:
                results = searcher.search_vault(query, top_k=max_results)
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
    from .mcp_server import main as run_mcp

    # Propagate --target to the MCP server via env var (stdio only).
    # HTTP mode is multi-tenant — project context comes per-request.
    root_target = ctx.find_root().params.get("target")
    if root_target is not None:
        if port is not None:
            console.print(
                "[yellow]Warning:[/] --target is ignored in HTTP mode "
                "(project_root must be passed per-request)",
            )
        else:
            os.environ[EnvVar.RAG_ROOT] = str(root_target)

    transport = f"streamable-http on port {port}" if port else "stdio"
    console.print(f"[bold green]Launching FastMCP server ({transport})...[/]")
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
    console.print(table)


# --- Service helpers ---


def _status_dir() -> Path:
    """Return the global service status directory, creating it if needed.

    Resolved via ``cfg.status_dir`` (which checks CLI override, then
    ``VAULTSPEC_RAG_STATUS_DIR`` env var, then default
    ``~/.vaultspec-rag/``).

    Returns:
        Path to the service status directory.
    """
    from .config import get_config

    cfg = get_config()
    d = Path(cfg.status_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _status_file() -> Path:
    """Return the path to the service status JSON file.

    Returns:
        Path to ``{status_dir}/service.json``.
    """
    return _status_dir() / "service.json"


def _log_file() -> Path:
    """Return the path to the service log file.

    Resolved via ``cfg.log_file`` relative to the status directory.

    Returns:
        Path to ``{status_dir}/{log_file}``.
    """
    from .config import get_config

    cfg = get_config()
    return _status_dir() / cfg.log_file


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


def _is_our_service(pid: int) -> bool:
    """Check if PID belongs to a vaultspec-rag MCP server process.

    On Windows, uses ``QueryFullProcessImageNameW`` via ctypes to
    verify the process executable contains ``"python"``.  On Unix,
    inspects ``/proc/{pid}/cmdline`` for the module name.  Falls
    back to basic PID liveness when verification is unavailable.

    Args:
        pid: Process ID to verify.

    Returns:
        True if the process appears to be a vaultspec-rag service.

    """
    if not _is_pid_alive(pid):
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[union-attr]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFO
        if not handle:
            return True  # can't query → fall back to PID-alive trust
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return "python" in buf.value.lower()
            return True  # API call failed → fall back to trust
        finally:
            kernel32.CloseHandle(handle)
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
        return "vaultspec_rag" in cmdline
    except (OSError, ValueError):
        return True  # fallback to basic liveness on non-procfs systems


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
    # Strip VAULTSPEC_RAG_ROOT from the daemon env — the HTTP service is
    # multi-tenant and must not fall back to a baked-in project root.
    # Case-insensitive compare: Windows os.environ stores original case
    # but is case-insensitive for lookups.
    _excluded = str(EnvVar.RAG_ROOT).upper()
    env = {k: v for k, v in os.environ.items() if k.upper() != _excluded}
    log_fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    if sys.platform == "win32":
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=0x00000200 | 0x08000000,  # NEW_PROCESS_GROUP | NO_WINDOW
        )
    else:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    log_fh.close()  # child has the fd now
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
            envvar=EnvVar.PORT,
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
        existing_port = int(status["port"])
        if _is_our_service(existing_pid):
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

    Reads the status file from ``~/.vaultspec-rag/service.json``, verifies
    the PID is still alive and belongs to a vaultspec-rag process, sends
    a graceful termination signal (SIGTERM on Unix, CTRL_BREAK_EVENT on
    Windows), waits briefly for graceful shutdown, and removes the status file.
    Force-kills (SIGKILL/TerminateProcess) if graceful shutdown fails.
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
    if not _is_our_service(pid):
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
    """Display the current status of the background RAG service.

    Reads the status file from ``~/.vaultspec-rag/service.json``, checks if
    the stored PID belongs to an active vaultspec-rag process, probes the
    HTTP health endpoint (``/health``) to retrieve realtime metrics (uptime,
    CUDA status, models loaded, projects indexed), and displays a Rich table
    with process state, port, startup time, and health details. Returns
    appropriate status messages for stopped, stale, unreachable, or healthy
    service instances.
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
    port = int(status["port"])
    started_at = status.get("started_at", "unknown")

    if not _is_our_service(pid):
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

    os.environ.setdefault(EnvVar.HF_HUB_DOWNLOAD_TIMEOUT, "300")

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
                table.add_row(
                    label,
                    repo_id,
                    f"[red]failed[/]: {exc}"
                    " (partial cache may remain in ~/.cache/huggingface)",
                )

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
            searcher.search_vault("warmup", top_k=1)

        latencies: list[float] = []
        with console.status(
            f"[bold green]Running {n_queries} benchmark queries...",
        ):
            for i in range(n_queries):
                q = _bench_queries[i % len(_bench_queries)]
                t0 = time.perf_counter()
                searcher.search_vault(q, top_k=5)
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


@app.command("quality")
def handle_quality() -> None:
    """Run quality-scoring probes against a synthetic test corpus.

    Generates a temporary synthetic vault, indexes it, runs
    needle-based precision probes, and reports results. Exits 1
    if fewer than 75% of probes pass.

    This is a developer regression tool -- not tied to a specific
    user vault.

    Raises:
        typer.Exit: On GPU errors or when precision drops below 75%.
    """
    import tempfile

    from .synthetic import build_synthetic_vault

    with tempfile.TemporaryDirectory(prefix="vaultspec-quality-") as _tmp:
        root = Path(_tmp)
        manifest = build_synthetic_vault(root, n_docs=24, seed=42)

        try:
            model = EmbeddingModel()
        except (ImportError, RuntimeError) as e:
            _handle_gpu_error(e)

        store = VaultStore(root)

        try:
            indexer = VaultIndexer(root, model, store)
            with console.status("[bold green]Indexing synthetic corpus..."):
                indexer.full_index()

            searcher = VaultSearcher(root, model, store)

            # Build probes from the manifest's needle keywords.
            probes: list[tuple[str, int, str, str]] = []
            for needle, doc_id in list(manifest.needles.items())[:8]:
                probes.append((needle, 5, f"Needle → {doc_id}", doc_id))

            table = Table(
                title="Quality Probes — Synthetic Corpus",
                show_header=True,
            )
            table.add_column("#", style="bold", justify="right")
            table.add_column("Label")
            table.add_column("Query", style="italic")
            table.add_column("Result", justify="center")

            passed = 0
            for i, (query, top_k, label, expected_id) in enumerate(
                probes,
                1,
            ):
                results = searcher.search_vault(query, top_k=top_k)
                ok = any(expected_id in r.id for r in results)
                if ok:
                    passed += 1
                status = "[green]PASS[/]" if ok else "[red]FAIL[/]"
                table.add_row(str(i), label, query, status)

            total = len(probes)
            precision = passed / total if total else 0
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


@app.command("install")
def handle_install(
    target: Annotated[
        Path | None,
        typer.Option(
            "--target",
            "-t",
            help="Workspace path (default: current working directory).",
        ),
    ] = None,
    upgrade: Annotated[
        bool,
        typer.Option(
            "--upgrade",
            help="Re-seed bundled rule and MCP files even if present.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Preview changes without writing.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Override contents if already installed.",
        ),
    ] = False,
    skip: Annotated[
        list[str] | None,
        typer.Option(
            "--skip",
            help="Skip a component (repeatable).",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON."),
    ] = False,
) -> None:
    """Install vaultspec-rag enrollment into a workspace.

    Seeds rag's bundled rule and MCP source files into
    ``.vaultspec/rules/`` and invokes vaultspec-core's sync to
    propagate them to ``.mcp.json`` and provider directories. The
    workspace is created if it does not yet exist; rag is fully
    self-sufficient and does not require core to have run install
    first.

    Flag names mirror ``vaultspec-core install`` exactly. The
    positional ``provider`` argument core takes is omitted because
    rag has no provider concept of its own — propagation flows
    through core's existing per-provider sync.
    """
    from .commands import install_run

    try:
        report = install_run(
            path=target,
            upgrade=upgrade,
            dry_run=dry_run,
            force=force,
            skip=set(skip or []),
        )
    except Exception as exc:
        console.print(f"[bold red]install failed:[/] {exc}")
        raise typer.Exit(code=1) from exc

    if json_output:
        import json as _json

        console.print_json(_json.dumps(report.to_dict(), default=str))
        return

    _render_install_report(report)


@app.command("uninstall")
def handle_uninstall(
    target: Annotated[
        Path | None,
        typer.Option(
            "--target",
            "-t",
            help="Workspace path (default: current working directory).",
        ),
    ] = None,
    remove_data: Annotated[
        bool,
        typer.Option(
            "--remove-data",
            help="Also remove .vault/data/ (rag's index, preserved by default).",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Preview changes without removing.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Required to execute. Uninstall is destructive.",
        ),
    ] = False,
    skip: Annotated[
        list[str] | None,
        typer.Option(
            "--skip",
            help="Skip a component (repeatable).",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON."),
    ] = False,
) -> None:
    """Remove vaultspec-rag enrollment from a workspace.

    Symmetric mirror of ``install``: removes rag's bundled rule and
    MCP source files from ``.vaultspec/rules/`` and invokes
    vaultspec-core's sync to propagate the removal to ``.mcp.json``
    and provider directories.

    Without ``--force``, returns a dry-run preview only. ``.vault/``
    documents are always preserved. The rag index under
    ``.vault/data/`` is preserved unless ``--remove-data`` is set.
    rag never touches vaultspec-core's installation.
    """
    from .commands import uninstall_run

    try:
        report = uninstall_run(
            path=target,
            remove_data=remove_data,
            dry_run=dry_run,
            force=force,
            skip=set(skip or []),
        )
    except Exception as exc:
        console.print(f"[bold red]uninstall failed:[/] {exc}")
        raise typer.Exit(code=1) from exc

    if json_output:
        import json as _json

        console.print_json(_json.dumps(report.to_dict(), default=str))
        return

    _render_uninstall_report(report)


def _render_install_report(report: Any) -> None:
    """Render an install report to the Rich console."""
    title = {
        "install": "[bold green]vaultspec-rag installed[/]",
        "upgrade": "[bold green]vaultspec-rag upgraded[/]",
        "dry_run": "[bold yellow]vaultspec-rag install (dry-run)[/]",
    }.get(report.action, "[bold]vaultspec-rag install[/]")
    console.print(title)
    console.print(f"target: [cyan]{report.target}[/]")
    if report.created_dirs:
        console.print(f"created [bold]{len(report.created_dirs)}[/] directories")
    if report.seeded:
        console.print(f"seeded [bold]{len(report.seeded)}[/] bundled files:")
        for rel in report.seeded:
            console.print(f"  [green]+[/] {rel}")
    sync_added = sum(getattr(r, "added", 0) for r in report.sync_results)
    sync_updated = sum(getattr(r, "updated", 0) for r in report.sync_results)
    sync_pruned = sum(getattr(r, "pruned", 0) for r in report.sync_results)
    if sync_added or sync_updated or sync_pruned:
        console.print(
            f"core sync: [green]+{sync_added}[/] "
            f"[yellow]~{sync_updated}[/] [red]-{sync_pruned}[/]"
        )
    for warning in report.warnings:
        console.print(f"[yellow]warning:[/] {warning}")


def _render_uninstall_report(report: Any) -> None:
    """Render an uninstall report to the Rich console."""
    title = {
        "uninstall": "[bold green]vaultspec-rag uninstalled[/]",
        "dry_run": "[bold yellow]vaultspec-rag uninstall (dry-run; "
        "use --force to apply)[/]",
    }.get(report.action, "[bold]vaultspec-rag uninstall[/]")
    console.print(title)
    console.print(f"target: [cyan]{report.target}[/]")
    if report.removed:
        console.print(f"removed [bold]{len(report.removed)}[/] bundled source files:")
        for rel in report.removed:
            console.print(f"  [red]-[/] {rel}")
    if report.data_removed:
        console.print("[red]-[/] .vault/data/ (rag index purged)")
    sync_pruned = sum(getattr(r, "pruned", 0) for r in report.sync_results)
    if sync_pruned:
        console.print(f"core sync pruned: [red]-{sync_pruned}[/]")
    for warning in report.warnings:
        console.print(f"[yellow]warning:[/] {warning}")


if __name__ == "__main__":
    app()
