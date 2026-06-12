"""Typer application objects, sub-app nesting, state, and root callback.

This submodule MUST be imported first by the package ``__init__`` so
the ``app`` / ``server_root_app`` / ``server_app`` / ``mcp_app`` /
``server_projects_app`` / ``server_watcher_app`` objects exist and
are nested before any command submodule's ``@*.command()`` decorator
runs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, cast

import typer

import vaultspec_rag.cli as _cli

from ..config import EnvVar
from ..logging_config import configure_logging
from ..workspace import WorkspaceError, WorkspaceLayout, resolve_workspace

__all__ = [
    "CLIState",
    "_global_target",
    "app",
    "main",
    "mcp_app",
    "preprocess_app",
    "server_app",
    "server_projects_app",
    "server_qdrant_app",
    "server_watcher_app",
    "version_callback",
]

app = typer.Typer(
    help="VaultSpec RAG: Unified search over documentation and code.",
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)

# Command Groups
server_root_app = typer.Typer(
    help="Manage the HTTP RAG service and the MCP protocol adapter.",
    rich_markup_mode=None,
)
# Alias kept for backward-compatible decorator references in command modules.
server_app = server_root_app
mcp_app = typer.Typer(
    help="Control the Model Context Protocol (MCP) server.",
    rich_markup_mode=None,
)
server_projects_app = typer.Typer(
    help="Inspect and evict project slots on a running RAG service.",
    rich_markup_mode=None,
)
server_watcher_app = typer.Typer(
    help="Inspect and control the filesystem auto-reindex watcher.",
    rich_markup_mode=None,
)
server_qdrant_app = typer.Typer(
    help="Provision and inspect the supervised qdrant server binary.",
    rich_markup_mode=None,
)
preprocess_app = typer.Typer(
    help="Inspect and validate document-preprocessing rules (#185).",
    rich_markup_mode=None,
)

app.add_typer(server_root_app, name="server")
server_root_app.add_typer(mcp_app, name="mcp")
server_root_app.add_typer(server_projects_app, name="projects")
server_root_app.add_typer(server_watcher_app, name="watcher")
server_root_app.add_typer(server_qdrant_app, name="qdrant")
app.add_typer(preprocess_app, name="preprocess")


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
    """Print the installed vaultspec-rag version and exit."""
    if value:
        import importlib.metadata

        try:
            version = importlib.metadata.version("vaultspec-rag")
            _cli.console.print(f"vaultspec-rag v{version}")
        except importlib.metadata.PackageNotFoundError:
            _cli.console.print("vaultspec-rag (unknown version)")
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
    """Configure logging, resolve workspace, and dispatch to a subcommand."""
    configure_logging(debug=debug, level="INFO" if verbose else None)

    # Wire CLI overrides into the config system.
    from ..config import get_config

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
        # core's resolver (install/uninstall). Even so, stash the
        # global ``--target`` (if any) on ctx.obj so the install /
        # uninstall handlers can read it. Click consumes group
        # options before subcommand options, so the global value
        # would otherwise be silently dropped if the user invoked
        # ``vaultspec-rag --target /path install`` instead of
        # ``vaultspec-rag install --target /path``.
        ctx.obj = {"target": target}
        return

    try:
        layout = resolve_workspace(target_override=target)
        ctx.obj = CLIState(layout)
    except WorkspaceError as e:
        _cli.console.print(f"Error: {e}", markup=False, highlight=False)
        raise typer.Exit(code=1) from None


def _global_target(ctx: typer.Context) -> Path | None:
    """Read the global ``--target`` value the root callback stashed
    on ``ctx.obj`` for short-circuited subcommands (install /
    uninstall).

    Returns ``None`` if the user did not pass a global target. The
    callback only sets a dict here for the install/uninstall path;
    other subcommands receive a ``CLIState`` instance instead, which
    we ignore.
    """
    obj = ctx.obj
    if isinstance(obj, dict):
        obj_dict = cast("dict[str, object]", obj)
        value = obj_dict.get("target")
        if isinstance(value, Path):
            return value
    return None
