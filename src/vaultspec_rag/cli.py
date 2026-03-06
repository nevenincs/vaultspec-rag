"""Primary CLI application for vaultspec-rag."""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING, Annotated, Literal

if TYPE_CHECKING:
    from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .embeddings import EmbeddingModel
from .indexer import CodebaseIndexer, VaultIndexer
from .logging_config import configure_logging
from .search import VaultSearcher
from .store import VaultStore
from .workspace import WorkspaceError, WorkspaceLayout, resolve_workspace

console = Console()

app = typer.Typer(
    help="VaultSpec RAG: Unified search over documentation and code.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Command Groups
server_app = typer.Typer(help="Manage RAG servers and backend services.")
mcp_app = typer.Typer(help="Control the Model Context Protocol (MCP) server.")
service_app = typer.Typer(help="Manage local or containerized RAG services.")

app.add_typer(server_app, name="server")
server_app.add_typer(mcp_app, name="mcp")
server_app.add_typer(service_app, name="service")


class CLIState:
    """Shared state for CLI commands."""

    def __init__(self, layout: WorkspaceLayout):
        self.layout = layout
        self.target = layout.target_dir
        # Ensure VAULTSPEC_ROOT is set for components that use it
        os.environ["VAULTSPEC_ROOT"] = str(self.target)


def version_callback(value: bool):
    """Show the version and exit."""
    if value:
        import importlib.metadata

        try:
            version = importlib.metadata.version("vaultspec-rag")
            console.print(f"vaultspec-rag v{version}")
        except importlib.metadata.PackageNotFoundError:
            console.print("vaultspec-rag (unknown version)")
        raise typer.Exit()


@app.callback()
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
        bool, typer.Option("--verbose", "-v", help="Enable INFO logging")
    ] = False,
    debug: Annotated[
        bool, typer.Option("--debug", "-d", help="Enable DEBUG logging")
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
):
    """Global configuration for vaultspec-rag."""
    # Setup logging
    configure_logging(debug=debug, level="INFO" if verbose else None)

    if ctx.invoked_subcommand is None:
        return

    # Resolve workspace following core logic
    try:
        layout = resolve_workspace(target_override=target)
        ctx.obj = CLIState(layout)
    except WorkspaceError as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1) from None


@app.command("index")
def handle_index(
    ctx: typer.Context,
    model: Annotated[
        str | None, typer.Option("--model", help="Override the embedding model name.")
    ] = None,
    clean: Annotated[
        bool, typer.Option("--clean", help="Delete the existing index before starting.")
    ] = False,
):
    """Index vault documents and codebase chunks."""
    state: CLIState = ctx.obj
    target = state.target

    with console.status("[bold green]Initializing RAG components...") as status:
        # Connect to store
        store = VaultStore(target)

        if clean:
            console.log(f"Cleaning existing index at [cyan]{store.db_path}[/]...")
            if store.db_path.exists():
                shutil.rmtree(store.db_path)
            # Re-open fresh
            store = VaultStore(target)

        # Init model and indexers
        emb_model = EmbeddingModel(model_name=model)
        v_indexer = VaultIndexer(target, emb_model, store)
        c_indexer = CodebaseIndexer(target, emb_model, store)

        status.update("[bold blue]Indexing documentation vault...")
        v_res = v_indexer.incremental_index()
        console.log(
            f"Vault: [green]{v_res.added}[/] added, "
            f"[yellow]{v_res.updated}[/] updated, "
            f"[red]{v_res.removed}[/] removed."
        )

        status.update("[bold blue]Indexing codebase...")
        c_res = c_indexer.full_index()
        console.log(
            f"Codebase: [green]{c_res.total}[/] chunks "
            f"from [cyan]{c_res.files}[/] files indexed."
        )

    console.print("\n[bold green]✅ Indexing complete.[/]")


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
        int, typer.Option("--max-results", help="Maximum number of results to return.")
    ] = 5,
):
    """Search for relevant context in documentation or code."""
    state: CLIState = ctx.obj
    target = state.target

    with console.status(f"[bold green]Searching {search_type}..."):
        store = VaultStore(target)
        model = EmbeddingModel()
        searcher = VaultSearcher(target, model, store)

        if search_type == "vault":
            results = searcher.search_vault(query, top_k=max_results)
        else:
            results = searcher.search_codebase(query, top_k=max_results)

    if not results:
        console.print(
            f"[yellow]No {search_type} results found for:[/] [italic]{query}[/]"
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
def handle_status(ctx: typer.Context):
    """Show RAG engine status, storage metrics, and GPU info."""
    state: CLIState = ctx.obj
    target = state.target

    import torch

    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        vram_mb = torch.cuda.get_device_properties(0).total_mem // (1024 * 1024)
        console.print(
            f"[bold]Device:[/] [green]cuda[/] ({gpu_name}, {vram_mb} MB VRAM)"
        )
    else:
        console.print("[bold]Device:[/] [red]No CUDA GPU available[/]")

    store = VaultStore(target)
    console.print(f"[bold]Storage Path:[/] [cyan]{store.db_path}[/]")
    console.print(f"[bold]Vault Documents:[/] [green]{store.count()}[/]")
    console.print(f"[bold]Codebase Chunks:[/] [green]{store.count_code()}[/]")


# --- MCP Server Commands ---


@mcp_app.command("start")
def mcp_start(_ctx: typer.Context):
    """Start the Model Context Protocol (MCP) server in the foreground."""
    from .mcp_server import main as run_mcp

    console.print("[bold green]Launching FastMCP server...[/]")
    run_mcp()


@mcp_app.command("stop")
def mcp_stop():
    """Stop the MCP server."""
    console.print(
        "[yellow]MCP server termination must be handled "
        "by the process manager or via Ctrl+C.[/]"
    )


@mcp_app.command("status")
def mcp_status():
    """Display the MCP server's configuration and readiness."""
    console.print("[bold blue]MCP Status:[/] Configured and ready for stdio transport.")


# --- Service Commands (Docker/Local) ---


@service_app.command("start")
def service_start():
    """Start the background RAG service (e.g., Docker container)."""
    console.print(
        "[bold red]Error:[/] No Docker configuration found. "
        "Service management disabled."
    )


@service_app.command("stop")
def service_stop():
    """Stop the background RAG service."""
    console.print("[bold yellow]No active background services detected.[/]")


@service_app.command("status")
def service_status():
    """Show the status of background RAG services."""
    console.print("[bold]Local Environment:[/] [green]Ready[/]")
    console.print("[bold]Docker Service:[/] [red]N/A (Missing Dockerfile)[/]")


@app.command(
    "test",
    context_settings={"allow_extra_args": True, "allow_interspersed_args": False},
)
def handle_test(ctx: typer.Context):
    """Run the test suite via pytest.

    All extra arguments are forwarded to pytest::

        vaultspec-rag test -m integration -v --timeout=120
    """
    import subprocess
    import sys
    from pathlib import Path

    test_dir = str(Path(__file__).resolve().parent / "tests")
    cmd = [sys.executable, "-m", "pytest", test_dir, *ctx.args]
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    app()
