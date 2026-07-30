"""Typer application objects, sub-app nesting, state, and root callback.

This submodule MUST be imported first by the package ``__init__`` so
the ``app`` / ``server_root_app`` / ``server_app`` /
``server_job_app`` / ``server_projects_app`` / ``server_watcher_app`` objects
exist and are nested before any command submodule's ``@*.command()`` decorator
runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

import typer
from typer.core import TyperGroup, TyperOption
from typer.models import TyperPath
from vaultspec_core.config.workspace import (
    WorkspaceError,
    WorkspaceLayout,
    resolve_workspace,
)

import vaultspec_rag.cli as _cli

from .._named_root import env_named_root
from ..config._types import EnvVar
from ..logging_config import configure_logging
from ._render import _plain

if TYPE_CHECKING:
    import click
    from typer._click import Context as ClickContext

__all__ = [
    "JOBS_WATCH_OPTION_HELP",
    "JSON_ENVELOPE_OPTION_HELP",
    "JSON_OPTION_HELP",
    "PORT_OPTION_HELP",
    "SERVER_WATCH_OPTION_HELP",
    "WATCH_INTERVAL_OPTION_HELP",
    "CLIState",
    "JobIdArgument",
    "JsonEnvelopeMode",
    "JsonMode",
    "PortOption",
    "RepeatUpdateDelayOption",
    "SkipOption",
    "TargetOption",
    "UpdateDelayOption",
    "_global_target",
    "app",
    "main",
    "preprocess_app",
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

#: How every verb describes ``--port``. Eighteen declarations spelled it out,
#: and they had already split into two sentences for one flag: sixteen said
#: this, while ``index`` and ``search`` said "Use the service running on this
#: port." Both mean the same thing, so an operator comparing two ``--help``
#: screens was reading a difference that was not there. The majority wording is
#: kept because it also documents what omitting the flag does.
PORT_OPTION_HELP = "Service port (defaults to running service)."

#: The service-address flag. Every verb that can talk to a running daemon takes
#: it with the same name, the same type, and the same optional-means-discover
#: default, so it is one declaration rather than one per verb.
PortOption = Annotated[int | None, typer.Option("--port", help=PORT_OPTION_HELP)]

#: The job selector the job verbs share. Six of them accepted it and each
#: repeated the sentence explaining that a prefix is allowed in human mode -
#: a rule about the id format, so it belongs to the argument and not to any
#: one verb that reads it.
JobIdArgument = Annotated[
    str, typer.Argument(help="Exact job id or human-mode prefix.")
]

#: The two entry points into the interactive watch open different screens, so
#: each names the one it opens. ``server --watch`` opens the balanced server
#: mode, which weighs indexing against served searches; ``server jobs --watch``
#: opens the jobs-focused mode with the filters that verb parsed. One shared
#: sentence would have promised every operator the screen only one of them gets.
SERVER_WATCH_OPTION_HELP = (
    "Open the interactive server watch with indexing and served searches."
)
JOBS_WATCH_OPTION_HELP = "Open the interactive jobs interface with per-job controls."
#: The refresh cadence is one knob with one meaning in either mode.
WATCH_INTERVAL_OPTION_HELP = "Seconds between refreshes in the interactive interface."

#: Watcher tuning, declared once for the two verbs that accept it. ``server
#: start`` and ``server watch`` set the same two knobs, and a default or a
#: unit changed in one of them would have left the other describing the old
#: contract in ``--help`` while still forwarding to the same service route.
UpdateDelayOption = Annotated[
    int | None,
    typer.Option(
        "--update-delay-ms",
        help="Delay before indexing a burst of file changes, in milliseconds.",
    ),
]
RepeatUpdateDelayOption = Annotated[
    float | None,
    typer.Option(
        "--repeat-update-delay-s",
        help="Minimum wait before automatically updating a project again, in seconds.",
    ),
]

#: The install verbs' shared workspace and component selectors. ``install`` and
#: ``uninstall`` must agree on what ``--target`` resolves and what ``--skip``
#: names, or the pair stops being symmetric.
TargetOption = Annotated[
    Path | None,
    typer.Option(
        "--target",
        "-t",
        help="Workspace path (default: current working directory).",
        dir_okay=True,
        file_okay=False,
        resolve_path=True,
    ),
]
SkipOption = Annotated[
    list[str] | None,
    typer.Option("--skip", help="Skip a component (repeatable)."),
]


@dataclass(frozen=True, slots=True)
class _RootOptions:
    target: Path | None
    verbose: bool
    debug: bool
    data_dir: str | None
    storage_dir: str | None
    status_dir: str | None
    log_file: str | None


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


def _version_option_callback(
    _ctx: click.Context, _param: click.Parameter, value: bool
) -> bool:
    """Adapt the public one-value callback to Click's option callback API."""
    version_callback(value)
    return value


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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.params.extend(
            (
                TyperOption(
                    param_decls=["--target", "-t"],
                    type=TyperPath(
                        path_type=Path,
                        dir_okay=True,
                        file_okay=False,
                        resolve_path=True,
                    ),
                    default=None,
                    help="Directory containing .vault and .vaultspec",
                ),
                TyperOption(
                    param_decls=["--verbose", "-v"],
                    default=False,
                    is_flag=True,
                    help="Enable INFO logging",
                ),
                TyperOption(
                    param_decls=["--debug", "-d"],
                    default=False,
                    is_flag=True,
                    help="Enable DEBUG logging",
                ),
                TyperOption(
                    param_decls=["--data-dir"],
                    type=str,
                    default=None,
                    help="Index data directory (default: .vault/data/search-data)",
                ),
                TyperOption(
                    param_decls=["--storage-dir"],
                    type=str,
                    default=None,
                    help="Index data subdirectory relative to --data-dir",
                ),
                TyperOption(
                    param_decls=["--status-dir"],
                    type=str,
                    default=None,
                    help=(
                        "Directory for service runtime files "
                        "(default: ~/.vaultspec-rag)"
                    ),
                ),
                TyperOption(
                    param_decls=["--log-file"],
                    type=str,
                    default=None,
                    help="Service log filename inside --status-dir",
                ),
                TyperOption(
                    param_decls=["--version", "-V"],
                    default=False,
                    is_flag=True,
                    help="Show version",
                    callback=_version_option_callback,
                    is_eager=True,
                ),
            )
        )

    def invoke(self, ctx: ClickContext) -> Any:
        """Invoke the empty registration callback without root option kwargs."""
        params = ctx.params
        ctx.meta[_ROOT_OPTIONS_CONTEXT_KEY] = _RootOptions(
            target=params["target"],
            verbose=params["verbose"],
            debug=params["debug"],
            data_dir=params["data_dir"],
            storage_dir=params["storage_dir"],
            status_dir=params["status_dir"],
            log_file=params["log_file"],
        )
        ctx.params = {}
        try:
            return super().invoke(ctx)
        finally:
            ctx.params = params


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


_ROOT_OPTIONS_CONTEXT_KEY = "vaultspec_rag.root_options"


def _show_group_help_if_no_command(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@server_root_app.callback(invoke_without_command=True)
def server_main(
    ctx: typer.Context,
    watch: Annotated[
        bool, typer.Option("--watch", help=SERVER_WATCH_OPTION_HELP)
    ] = False,
    interval: Annotated[
        float, typer.Option("--interval", help=WATCH_INTERVAL_OPTION_HELP)
    ] = 2.0,
    port: PortOption = None,
) -> None:
    """Open the interactive server watch, else show server command help."""
    if watch and ctx.invoked_subcommand is None:
        # Function-local: the jobs module registers its command against the app
        # objects this module owns, so importing it at module scope is a cycle.
        from ._service_jobs_collection import ServiceJobsOptions, run_service_jobs

        run_service_jobs(
            ServiceJobsOptions(
                port=port,
                interval=interval,
                watch=True,
                watch_mode="server",
            )
        )
        return
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


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Register root options through ``_LiteralArgvGroup``."""
    options = ctx.meta.get(_ROOT_OPTIONS_CONTEXT_KEY)
    if not isinstance(options, _RootOptions):
        raise RuntimeError("root CLI options were not initialized")
    _configure_root_context(ctx, options)


def _configure_root_context(ctx: ClickContext, options: _RootOptions) -> None:
    """Configure logging, resolve workspace, and dispatch to a subcommand."""
    configure_logging(debug=options.debug, level="INFO" if options.verbose else None)

    # Wire CLI overrides into the config system.
    from ..config._settings import get_config

    cli_overrides: dict[str, Any] = {}
    if options.data_dir is not None:
        cli_overrides["data_dir"] = options.data_dir
    if options.storage_dir is not None:
        cli_overrides["qdrant_dir"] = options.storage_dir
    if options.status_dir is not None:
        cli_overrides["status_dir"] = options.status_dir
    if options.log_file is not None:
        cli_overrides["log_file"] = options.log_file
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
    named_target = options.target if options.target is not None else env_named_root()

    if ctx.invoked_subcommand in (
        "server",
        "install",
        "uninstall",
    ):
        # These subcommands either operate without a resolved
        # workspace (server) or resolve their own via
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
        if options.target is None and named_target is not None:
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


def _global_target(ctx: ClickContext) -> Path | None:
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
