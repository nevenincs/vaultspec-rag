"""``install`` and ``uninstall`` commands: workspace enrollment mirror."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import click
import typer
from tomlkit.exceptions import ParseError
from typer._types import TyperChoice
from typer.core import TyperCommand, TyperOption
from typer.models import TyperPath
from vaultspec_core.core.enums import (
    InstallMode,
)

import vaultspec_rag.cli as _cli

from ._app import JSON_OPTION_HELP, _global_target, app
from ._render import _plain, _render_install_report, _render_uninstall_report

if TYPE_CHECKING:
    from typer._click import Context as ClickContext

# Group name used when ``--torch-group`` is passed without an explicit
# value. Surfaced both in the help text and as the Click ``flag_value``.
_DEFAULT_TORCH_GROUP = "dev"


@dataclass(frozen=True, slots=True)
class _InstallOptions:
    target: Path | None
    upgrade: bool
    dry_run: bool
    force: bool
    skip: tuple[str, ...]
    mode: InstallMode | None
    configure_torch: bool
    torch_group: str | None
    yes: bool
    sync_after: bool
    provision: bool
    install_mcp: bool
    local_only: bool
    skip_torch: bool
    skip_models: bool
    skip_qdrant: bool
    json_output: bool


class _InstallCommand(TyperCommand):
    """Install command that gives ``--torch-group`` an optional value.

    Typer 0.25's option builder does not forward ``flag_value`` to the
    underlying Click option, so ``--torch-group`` cannot be expressed as
    an optional-value flag through ``typer.Option`` alone. This command
    class re-enables Click's native optional-value behaviour after the
    params are built: ``--torch-group`` with no value resolves to the
    default group name, ``--torch-group NAME`` to ``NAME``, and an
    omitted flag stays ``None`` (the historic ``[project].dependencies``
    placement). Running per build keeps it effective across every
    ``get_command`` invocation rather than mutating a throwaway instance.
    """

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
                    help="Workspace path (default: current working directory).",
                ),
                TyperOption(
                    param_decls=["--upgrade"],
                    default=False,
                    is_flag=True,
                    help="Refresh bundled rules and integration files even if present.",
                ),
                TyperOption(
                    param_decls=["--dry-run"],
                    default=False,
                    is_flag=True,
                    help="Preview changes without writing.",
                ),
                TyperOption(
                    param_decls=["--force"],
                    default=False,
                    is_flag=True,
                    help=(
                        "Override existing files. Also bypasses the torch-config "
                        "confirmation prompt (implies --yes for that step). "
                        "--no-torch-config still wins."
                    ),
                ),
                TyperOption(
                    param_decls=["--skip"],
                    type=str,
                    multiple=True,
                    default=(),
                    help="Skip a component (repeatable).",
                ),
                TyperOption(
                    param_decls=["--mode"],
                    type=TyperChoice([member.value for member in InstallMode]),
                    default=None,
                    help=(
                        "Provisioning mode: 'tool' (default, launched via uvx), "
                        "'dependency' (a runtime project dependency resolved "
                        "through the project's own venv, ships in built "
                        "distributions), or 'dev' (the default dev dependency "
                        "group; renders like dependency but "
                        "does not ship in built distributions). Auto-detected from "
                        "pyproject.toml when omitted."
                    ),
                ),
                TyperOption(
                    param_decls=["--torch-config/--no-torch-config"],
                    default=True,
                    is_flag=True,
                    help=(
                        "Configure the CUDA PyTorch package source in pyproject.toml. "
                        "--no-torch-config takes precedence over --force / --yes."
                    ),
                ),
                TyperOption(
                    param_decls=["--torch-group"],
                    type=str,
                    default=None,
                    help=(
                        "Place the managed CUDA torch direct-dependency under the "
                        "PEP 735 [dependency-groups].NAME surface instead of "
                        "[project].dependencies, so a dev-only consumer does not "
                        "leak torch into its published requirements. Defaults the "
                        "group name to 'dev' when passed without a value. Omit the "
                        "flag entirely to keep the historic [project].dependencies "
                        "placement. The group must be enabled for the resolve "
                        "(`uv sync --group NAME`) for the cu130 pin to apply."
                    ),
                ),
                TyperOption(
                    param_decls=["--yes", "-y"],
                    default=False,
                    is_flag=True,
                    help=(
                        "Skip the PyTorch configuration prompt. Required for "
                        "non-interactive installs unless --no-torch-config is used."
                    ),
                ),
                TyperOption(
                    param_decls=["--sync"],
                    default=False,
                    is_flag=True,
                    help=(
                        "Run `uv sync --reinstall-package torch` after PyTorch "
                        "configuration changes are applied."
                    ),
                ),
                TyperOption(
                    param_decls=["--provision/--no-provision"],
                    default=True,
                    is_flag=True,
                    help=(
                        "Provision external dependencies (models and the Qdrant "
                        "server binary) after enrollment. On by default; "
                        "--no-provision sets up the workspace only."
                    ),
                ),
                TyperOption(
                    param_decls=["--mcp/--no-mcp"],
                    default=True,
                    is_flag=True,
                    help=(
                        "Enroll the agent-facing MCP search surface and reconcile its "
                        "optional dependency at RAG's existing project placement. On "
                        "by default; --no-mcp sets up a CLI-only workspace without the "
                        "mcp dependency (and, on Windows, without pywin32)."
                    ),
                ),
                TyperOption(
                    param_decls=["--local-only"],
                    default=False,
                    is_flag=True,
                    help=(
                        "Use the on-disk store instead of the supervised Qdrant "
                        "server: skips the Qdrant binary download and persists the "
                        "local backend so `server start` honours it. The minimal / "
                        "CI / air-gapped alternative to the server-first default."
                    ),
                ),
                TyperOption(
                    param_decls=["--skip-torch"],
                    default=False,
                    is_flag=True,
                    help=(
                        "Skip the PyTorch provisioning step (finer than --local-only)."
                    ),
                ),
                TyperOption(
                    param_decls=["--skip-models"],
                    default=False,
                    is_flag=True,
                    help="Skip the embedding/reranker model provisioning step.",
                ),
                TyperOption(
                    param_decls=["--skip-qdrant"],
                    default=False,
                    is_flag=True,
                    help="Skip the Qdrant server binary provisioning step.",
                ),
                TyperOption(
                    param_decls=["--json"],
                    default=False,
                    is_flag=True,
                    help=JSON_OPTION_HELP,
                ),
            )
        )
        for param in self.params:
            if isinstance(param, click.Option) and param.name == "torch_group":
                param.is_flag = False
                param.flag_value = _DEFAULT_TORCH_GROUP
                # Click computes ``_flag_needs_value`` in ``Option.__init__``
                # from the original (no-flag-value) construction; recompute
                # it so the parser consumes ``--torch-group`` standalone as
                # the default group rather than demanding an argument.
                param._flag_needs_value = True  # pyright: ignore[reportPrivateUsage]  # Click optional-value mechanism

    def invoke(self, ctx: "ClickContext") -> Any:
        """Dispatch parsed Click parameters as one install request."""
        params = ctx.params
        mode = cast("str | None", params["mode"])
        return _run_install(
            ctx,
            _InstallOptions(
                target=cast("Path | None", params["target"]),
                upgrade=cast("bool", params["upgrade"]),
                dry_run=cast("bool", params["dry_run"]),
                force=cast("bool", params["force"]),
                skip=cast("tuple[str, ...]", params["skip"]),
                mode=InstallMode(mode) if mode is not None else None,
                configure_torch=cast("bool", params["torch_config"]),
                torch_group=cast("str | None", params["torch_group"]),
                yes=cast("bool", params["yes"]),
                sync_after=cast("bool", params["sync"]),
                provision=cast("bool", params["provision"]),
                install_mcp=cast("bool", params["mcp"]),
                local_only=cast("bool", params["local_only"]),
                skip_torch=cast("bool", params["skip_torch"]),
                skip_models=cast("bool", params["skip_models"]),
                skip_qdrant=cast("bool", params["skip_qdrant"]),
                json_output=cast("bool", params["json"]),
            ),
        )


@app.command(
    "install",
    cls=_InstallCommand,
    help=(
        "Set up vaultspec-rag in a workspace.\n\n"
        "Creates the required workspace folders, installs bundled rules and "
        "integration files, and syncs the files used by supported tools. By "
        "default, install also provisions the external dependencies the "
        "server-first default needs - the embedding/reranker models and the "
        "pinned Qdrant server binary - and ensures the optional MCP extra so "
        "the agent-facing MCP search surface can run, and asks before changing "
        "PyTorch package configuration. Use --local-only for the minimal local "
        "backend (skips the binary), the finer "
        "--skip-torch/--skip-models/--skip-qdrant flags for partial opt-out, "
        "--no-mcp for a CLI-only workspace without the mcp dependency, and "
        "--no-provision to set up the workspace only; use --yes or "
        "--no-torch-config for non-interactive runs."
    ),
)
def handle_install() -> None:
    """Register the custom command; it dispatches through ``_InstallCommand``."""


def _run_install(ctx: "ClickContext", options: _InstallOptions) -> None:
    """Enrol the workspace and provision dependencies for one install request."""
    import sys as _sys

    from rich.prompt import Confirm

    from ..commands._install import install_run

    # Honour the global ``--target`` from the root callback. Click
    # consumes group options before subcommand options, so the user
    # invoking ``vaultspec-rag --target /path install`` would lose
    # the path entirely if we only read the local ``target``.
    effective_target = options.target or _global_target(ctx)

    def _confirm(prompt: str) -> bool:
        # Default-no on a destructive write - pressing Enter on the
        # ``Patch <pyproject>?`` prompt without reading it must NOT
        # mutate the user's pyproject. Users who want to bypass the
        # prompt can pass ``--yes`` or ``--force``. CLI3-04.
        return Confirm.ask(prompt, default=False, console=_cli.console)

    # Non-TTY detection lives at the CLI edge: only interactive TTYs
    # can produce meaningful confirmation answers. In CI / pipes,
    # leaving confirm=None forces the "skipped-non-tty" branch, which
    # instructs the user to pass --yes or --no-torch-config.
    confirm_fn = _confirm if _sys.stdin.isatty() else None

    # Map the per-dependency opt-out flags onto the front door's skip
    # token set. ``--local-only`` already drops the qdrant binary in the
    # front door, so the explicit ``--skip-qdrant`` is the redundant-but-
    # honest finer control; both are unioned here.
    provision_skip: set[str] = set()
    if options.skip_torch:
        provision_skip.add("torch")
    if options.skip_models:
        provision_skip.add("models")
    if options.skip_qdrant:
        provision_skip.add("qdrant")

    try:
        report = install_run(
            path=effective_target,
            upgrade=options.upgrade,
            dry_run=options.dry_run,
            force=options.force,
            skip=set(options.skip),
            configure_torch=options.configure_torch,
            assume_yes=options.yes,
            sync_after=options.sync_after,
            confirm=confirm_fn,
            provision=options.provision,
            local_only=options.local_only,
            provision_skip=provision_skip,
            torch_group=options.torch_group,
            install_mcp=options.install_mcp,
            mode=options.mode,
        )
    except ParseError as exc:
        _plain(f"Install failed: {exc}", soft_wrap=True)
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        _plain(f"Install failed: {exc}", soft_wrap=True)
        raise typer.Exit(code=1) from exc

    if options.json_output:
        import json as _json

        _cli.console.print_json(
            _json.dumps(report.to_dict(), default=str), highlight=False
        )
    else:
        _render_install_report(report)
        # The report's "PyTorch configuration" line describes pyproject.toml,
        # not the wheel in the active interpreter. When torch was meant to be
        # provisioned (not an explicit opt-out), probe the real wheel and warn
        # loudly if it is CPU-only or absent - a GPU-only project must never
        # report success over a CPU torch. An explicit opt-out is respected.
        if options.configure_torch:
            from ._gpu_errors import warn_if_active_torch_not_gpu

            warn_if_active_torch_not_gpu()

    # Issue #83 finding 3 ("Bonus: exit non-zero when the patch was
    # wanted but couldn't be applied"). The configure_torch=True path
    # ended in an outcome the user clearly did not opt into - surface
    # it via a non-zero exit so CI consumers fail loudly instead of
    # reading "torch-config: skipped-eof" buried in stdout.
    #
    # ``DECLINED`` is the user's own answer to a prompt - keep that 0.
    # ``CONFLICT`` is by-definition the user's own customised state -
    # keep that 0 too (the warning is the signal). ``ABSENT`` and
    # ``DISABLED`` are intentional opt-outs; both 0.
    from ..torch_config._constants import TorchConfigAction

    if (
        report.mcp_extra_action == "error"
        or report.mcp_sync_failed
        or (
            options.configure_torch
            and report.torch_config_action
            in {
                TorchConfigAction.ERROR,
                TorchConfigAction.SKIPPED_EOF,
                TorchConfigAction.SKIPPED_NON_TTY,
            }
        )
    ):
        raise typer.Exit(code=2)


@dataclass(frozen=True, slots=True)
class _UninstallOptions:
    target: Path | None
    remove_data: bool
    dry_run: bool
    force: bool
    skip: tuple[str, ...]
    yes: bool
    json_output: bool


class _UninstallCommand(TyperCommand):
    """Expose uninstall options without expanding the callback signature."""

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
                    help="Workspace path (default: current working directory).",
                ),
                TyperOption(
                    param_decls=["--remove-data"],
                    default=False,
                    is_flag=True,
                    help="Also remove index data under .vault/data/.",
                ),
                TyperOption(
                    param_decls=["--dry-run"],
                    default=False,
                    is_flag=True,
                    help="Preview changes without removing.",
                ),
                TyperOption(
                    param_decls=["--force"],
                    default=False,
                    is_flag=True,
                    help="Required to execute. Uninstall is destructive.",
                ),
                TyperOption(
                    param_decls=["--skip"],
                    type=str,
                    multiple=True,
                    default=(),
                    help="Skip a component (repeatable).",
                ),
                TyperOption(
                    param_decls=["--yes", "-y"],
                    default=False,
                    is_flag=True,
                    help="Skip confirmation prompts.",
                ),
                TyperOption(
                    param_decls=["--json"],
                    default=False,
                    is_flag=True,
                    help=JSON_OPTION_HELP,
                ),
            )
        )

    def invoke(self, ctx: "ClickContext") -> Any:
        """Dispatch parsed Click parameters as one uninstall request."""
        params = ctx.params
        return _run_uninstall(
            ctx,
            _UninstallOptions(
                target=cast("Path | None", params["target"]),
                remove_data=cast("bool", params["remove_data"]),
                dry_run=cast("bool", params["dry_run"]),
                force=cast("bool", params["force"]),
                skip=cast("tuple[str, ...]", params["skip"]),
                yes=cast("bool", params["yes"]),
                json_output=cast("bool", params["json"]),
            ),
        )


@app.command(
    "uninstall",
    cls=_UninstallCommand,
    help=(
        "Remove vaultspec-rag setup from a workspace. Without --force, this "
        "only previews what would be removed."
    ),
)
def handle_uninstall() -> None:
    """Register the custom command; it dispatches through ``_UninstallCommand``."""


def _run_uninstall(ctx: "ClickContext", options: _UninstallOptions) -> None:
    """Remove vaultspec-rag setup from a workspace.

    Without --force, this only previews what would be removed. Vault
    documents and index data are preserved unless --remove-data is set.
    """
    from ..commands._uninstall import uninstall_run

    # Honour the global ``--target`` from the root callback (see
    # handle_install for the rationale).
    effective_target = options.target or _global_target(ctx)

    try:
        report = uninstall_run(
            path=effective_target,
            remove_data=options.remove_data,
            dry_run=options.dry_run,
            force=options.force,
            skip=set(options.skip),
            assume_yes=options.yes,
        )
    except Exception as exc:
        _plain(f"Uninstall failed: {exc}", soft_wrap=True)
        raise typer.Exit(code=1) from exc

    if options.json_output:
        import json as _json

        _cli.console.print_json(
            _json.dumps(report.to_dict(), default=str), highlight=False
        )
    else:
        _render_uninstall_report(report)

    if report.mcp_sync_failed:
        raise typer.Exit(code=2)
