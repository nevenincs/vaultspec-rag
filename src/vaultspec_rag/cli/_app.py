"""Typer application objects, sub-app nesting, state, and root callback.

This submodule MUST be imported first by the package ``__init__`` so
the ``app`` / ``server_root_app`` / ``server_app`` /
``server_job_app`` / ``server_projects_app`` / ``server_watcher_app`` objects
exist and are nested before any command submodule's ``@*.command()`` decorator
runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, cast

import typer
from typer.core import TyperGroup
from vaultspec_core.config.workspace import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    WorkspaceError,
    WorkspaceLayout,
    resolve_workspace,
)

import vaultspec_rag.cli as _cli

from .._named_root import env_named_root
from ..config import EnvVar
from ..logging_config import configure_logging
from ._render import _plain

__all__ = [
    "JSON_ENVELOPE_OPTION_HELP",
    "JSON_OPTION_HELP",
    "CLIState",
    "JsonEnvelopeMode",
    "JsonMode",
    "_global_target",
    "app",
    "main",
    "preprocess_app",
    "run_cli",
    "server_app",
    "server_job_app",
    "server_projects_app",
    "server_qdrant_app",
    "server_storage_app",
    "server_watcher_app",
    "version_callback",
]


#: How every verb describes ``--json``. Thirty-three declarations spelled this
#: for themselves and had reached four wordings, so the same flag was
#: documented differently depending on which verb an operator ran ``--help``
#: on - including two declaration STYLES, with the storage verbs still on the
#: pre-``Annotated`` form and a terser sentence.
JSON_OPTION_HELP = "Emit JSON for scripts instead of human text."

#: The lifecycle verbs promise something stronger and say so: exactly one
#: structured envelope on every exit path, success or failure. That is a
#: different contract from "machine-readable output", not a reworded one, so
#: it stays a separate sentence rather than being flattened into the above.
JSON_ENVELOPE_OPTION_HELP = "Emit one structured JSON outcome."

#: The ``--json`` flag itself. A verb that needs to say more about its own
#: JSON behaviour composes on top of the shared sentence rather than restating
#: it, so the first clause an operator reads is the same everywhere.
JsonMode = Annotated[bool, typer.Option("--json", help=JSON_OPTION_HELP)]
JsonEnvelopeMode = Annotated[
    bool, typer.Option("--json", help=JSON_ENVELOPE_OPTION_HELP)
]


class _LiteralArgvGroup(TyperGroup):
    """Root command group that hands ``sys.argv`` to the parser verbatim.

    On Windows, Click and Typer simulate Unix shell expansion before parsing:
    every argument read from ``sys.argv`` goes through ``glob``,
    ``expanduser``, and ``expandvars``. That is wrong for this CLI. Its path
    options carry patterns matched against *indexed* project-relative paths,
    not against files on disk, so filesystem expansion destroys them - a
    quoted ``--include-path "src/**"`` arrives as one existing file per match,
    the option keeps the first, and the rest reach the parser as unexpected
    positional arguments. Quoting cannot prevent it, because the expansion
    runs after the shell has already delivered the argument intact.

    Refusing the behaviour here covers every entry point, because they all
    funnel through this group's ``main``. Nothing is lost: the options that do
    name real filesystem paths are expanded explicitly where they resolve.
    """

    def main(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["windows_expand_args"] = False
        return super().main(*args, **kwargs)


app = typer.Typer(
    cls=_LiteralArgvGroup,
    help=(
        "VaultSpec RAG: search project documentation and source code by "
        "meaning.\n"
        "\n"
        "\b\n"
        "Query markers - write them anywhere in the query text:\n"
        "  documents  type:adr feature:rag date:2026-07 tag:research\n"
        "  code       lang:python path:src/ func:encode class:Searcher\n"
        "  noise      only:prod exclude:tests,docs include:locale\n"
        "  ranking    status:active intent:debugging\n"
        "\n"
        "\b\n"
        "Examples:\n"
        '  vaultspec-rag search "auth token validation only:prod" --type code\n'
        '  vaultspec-rag search "fixture helpers exclude:tests" --type code\n'
        '  vaultspec-rag search "gpu lock decision type:adr status:active"\n'
        "\n"
        "Run 'vaultspec-rag search --help' for the full marker reference.\n"
    ),
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)

# Command Groups
server_root_app = typer.Typer(
    help="Manage the background search service.",
    rich_markup_mode=None,
    no_args_is_help=False,
)
# Alias kept for backward-compatible decorator references in command modules.
server_app = server_root_app
server_job_app = typer.Typer(
    help="Inspect and control one exact service job.",
    rich_markup_mode=None,
    no_args_is_help=False,
)
server_projects_app = typer.Typer(
    help="Inspect and unload projects held by the running search service.",
    rich_markup_mode=None,
    no_args_is_help=False,
)
server_watcher_app = typer.Typer(
    help="Inspect and control automatic index updates.",
    rich_markup_mode=None,
    no_args_is_help=False,
)
server_qdrant_app = typer.Typer(
    help="Install and inspect the managed Qdrant server.",
    rich_markup_mode=None,
    no_args_is_help=False,
)
server_storage_app = typer.Typer(
    help="Survey and reclaim per-root RAG index storage.",
    rich_markup_mode=None,
    no_args_is_help=False,
)
preprocess_app = typer.Typer(
    help="Inspect and validate document preprocessing rules.",
    rich_markup_mode=None,
    no_args_is_help=False,
)

app.add_typer(server_root_app, name="server")
server_root_app.add_typer(server_job_app, name="job")
server_root_app.add_typer(server_projects_app, name="projects")
server_root_app.add_typer(server_watcher_app, name="updates")
server_root_app.add_typer(server_qdrant_app, name="qdrant")
server_root_app.add_typer(server_storage_app, name="storage")
app.add_typer(preprocess_app, name="preprocess")


def _show_group_help_if_no_command(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@server_root_app.callback(invoke_without_command=True)
def server_main(ctx: typer.Context) -> None:
    """Show server command help when no server subcommand is provided."""
    _show_group_help_if_no_command(ctx)


@server_projects_app.callback(invoke_without_command=True)
def server_projects_main(ctx: typer.Context) -> None:
    """Show project command help when no project subcommand is provided."""
    _show_group_help_if_no_command(ctx)


@server_job_app.callback(invoke_without_command=True)
def server_job_main(ctx: typer.Context) -> None:
    """Show singular job command help when no subcommand is provided."""
    _show_group_help_if_no_command(ctx)


@server_watcher_app.callback(invoke_without_command=True)
def server_updates_main(ctx: typer.Context) -> None:
    """Show update command help when no update subcommand is provided."""
    _show_group_help_if_no_command(ctx)


@server_qdrant_app.callback(invoke_without_command=True)
def server_qdrant_main(ctx: typer.Context) -> None:
    """Show Qdrant command help when no Qdrant subcommand is provided."""
    _show_group_help_if_no_command(ctx)


@server_storage_app.callback(invoke_without_command=True)
def server_storage_main(ctx: typer.Context) -> None:
    """Show storage command help when no storage subcommand is provided."""
    _show_group_help_if_no_command(ctx)


@preprocess_app.callback(invoke_without_command=True)
def preprocess_main(ctx: typer.Context) -> None:
    """Show preprocess command help when no preprocess subcommand is provided."""
    _show_group_help_if_no_command(ctx)


class CLIState:
    """Shared state container for CLI commands and sub-applications.

    Initialized by the main callback and passed via ``typer.Context.obj``
    to all subcommands. Holds validated workspace metadata.

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
            help="Index data directory (default: .vault/data/search-data)",
        ),
    ] = None,
    storage_dir: Annotated[
        str | None,
        typer.Option(
            "--storage-dir",
            help="Index data subdirectory relative to --data-dir",
        ),
    ] = None,
    status_dir: Annotated[
        str | None,
        typer.Option(
            "--status-dir",
            help="Directory for service runtime files (default: ~/.vaultspec-rag)",
        ),
    ] = None,
    log_file: Annotated[
        str | None,
        typer.Option(
            "--log-file",
            help="Service log filename inside --status-dir",
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
    if storage_dir is not None:
        cli_overrides["qdrant_dir"] = storage_dir
    if status_dir is not None:
        cli_overrides["status_dir"] = status_dir
    if log_file is not None:
        cli_overrides["log_file"] = log_file
    if cli_overrides:
        get_config(cli_overrides)

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

    # Precedence for the project this invocation addresses: the flag, then the
    # environment, then whatever the workspace resolver makes of the working
    # directory. The environment sits in the middle because exporting
    # ``VAULTSPEC_RAG_ROOT`` names a project as deliberately as typing the
    # flag does, and the working directory names nothing - it is wherever the
    # shell happened to be. Reading it here, before any workspace is resolved,
    # is what makes that possible: the variable decides *which* project a
    # configuration is built for, so it cannot be resolved alongside the
    # settings that are read out of that project.
    named_target = target if target is not None else env_named_root()

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
        # named root (if any) on ctx.obj so the install / uninstall
        # handlers can read it. Click consumes group options before
        # subcommand options, so the global value would otherwise be
        # silently dropped if the user invoked
        # ``vaultspec-rag --target /path install`` instead of
        # ``vaultspec-rag install --target /path``.
        ctx.obj = {"target": named_target}
        return

    try:
        layout = resolve_workspace(target_override=named_target)
        ctx.obj = CLIState(layout)
    except WorkspaceError as e:
        if target is None and named_target is not None:
            # Attribute the failure to the variable: an operator who passed no
            # flag has no other way to learn that the environment chose the
            # directory being complained about.
            _plain(
                f"Error: {EnvVar.RAG_ROOT.value} names {named_target}, which is "
                f"not a usable workspace: {e}"
            )
        else:
            _plain(f"Error: {e}")
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


def run_cli() -> None:
    """Run the CLI over the process command line.

    Every program invocation of the application goes through here, because
    the command line reaches the parser verbatim only when it is invoked this
    way.

    Click emulates a POSIX shell on Windows: unless disabled, it applies user
    expansion, environment-variable expansion and a recursive glob to every
    argument it reads from ``sys.argv``. An argument that matches nothing
    survives, so the damage is invisible until an operator passes something
    that does match. A pattern option is then replaced by the files it matched
    at the time - one match silently narrows the filter to a single file, and
    several turn the remainder into stray positionals. The same pass rewrites
    a query carrying ``~`` or a variable reference into a filesystem path.

    None of that is wanted here. The interactive shells this runs under expand
    their own arguments already, so the pass is at best a second expansion of
    something the user deliberately quoted, and the arguments it corrupts are
    exactly the pattern options whose value must reach the search service
    verbatim - the same value the non-shell callers of that service already
    send. Turning it off is what keeps the two on one contract.
    """
    app(windows_expand_args=False)
