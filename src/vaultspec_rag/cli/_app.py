"""Typer application objects, sub-app nesting, state, and root callback.

This submodule MUST be imported first by the package ``__init__`` so
the ``app`` / ``server_app`` / ``mcp_app`` / ``service_app`` /
``service_projects_app`` / ``service_watcher_app`` objects exist and
are nested before any command submodule's ``@*.command()`` decorator
runs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

import typer

import vaultspec_rag.cli as _cli

from ..config import EnvVar
from ..logging_config import configure_logging
from ..workspace import WorkspaceError, WorkspaceLayout, resolve_workspace

app = typer.Typer(
    help="VaultSpec RAG: Unified search over documentation and code.",
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
)

# Command Groups
server_app = typer.Typer(help="Manage RAG servers and backend services.")
mcp_app = typer.Typer(help="Control the Model Context Protocol (MCP) server.")
service_app = typer.Typer(help="Manage local or containerized RAG services.")
service_projects_app = typer.Typer(
    help="Inspect and evict project slots on a running RAG service.",
)
service_watcher_app = typer.Typer(
    help="Inspect and control the filesystem auto-reindex watcher.",
)

app.add_typer(server_app, name="server")
server_app.add_typer(mcp_app, name="mcp")
server_app.add_typer(service_app, name="service")
service_app.add_typer(service_projects_app, name="projects")
service_app.add_typer(service_watcher_app, name="watcher")


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
        _cli.console.print(f"[bold red]Error:[/] {e}")
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
        value = obj.get("target")
        if isinstance(value, Path):
            return value
    return None
