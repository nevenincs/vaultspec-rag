"""``install`` and ``uninstall`` commands: workspace enrollment mirror."""

from pathlib import Path
from typing import Annotated, Any

import click
import typer
from typer.core import TyperCommand

import vaultspec_rag.cli as _cli

from ._app import _global_target, app
from ._render import _render_install_report, _render_uninstall_report

# Group name used when ``--torch-group`` is passed without an explicit
# value. Surfaced both in the help text and as the Click ``flag_value``.
_DEFAULT_TORCH_GROUP = "dev"


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
        for param in self.params:
            if isinstance(param, click.Option) and param.name == "torch_group":
                param.is_flag = False
                param.flag_value = _DEFAULT_TORCH_GROUP
                # Click computes ``_flag_needs_value`` in ``Option.__init__``
                # from the original (no-flag-value) construction; recompute
                # it so the parser consumes ``--torch-group`` standalone as
                # the default group rather than demanding an argument.
                param._flag_needs_value = True  # pyright: ignore[reportPrivateUsage]  # Click optional-value mechanism


@app.command("install", cls=_InstallCommand)
def handle_install(
    ctx: typer.Context,
    target: Annotated[
        Path | None,
        typer.Option(
            "--target",
            "-t",
            help="Workspace path (default: current working directory).",
            dir_okay=True,
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    upgrade: Annotated[
        bool,
        typer.Option(
            "--upgrade",
            help="Refresh bundled rules and integration files even if present.",
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
            help=(
                "Override existing files. Also bypasses the torch-config "
                "confirmation prompt (implies --yes for that step). "
                "--no-torch-config still wins."
            ),
        ),
    ] = False,
    skip: Annotated[
        list[str] | None,
        typer.Option(
            "--skip",
            help="Skip a component (repeatable).",
        ),
    ] = None,
    configure_torch: Annotated[
        bool,
        typer.Option(
            "--torch-config/--no-torch-config",
            help=(
                "Configure the CUDA PyTorch package source in pyproject.toml. "
                "--no-torch-config takes precedence over --force / --yes."
            ),
        ),
    ] = True,
    torch_group: Annotated[
        str | None,
        typer.Option(
            "--torch-group",
            is_flag=False,
            flag_value="dev",
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
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help=(
                "Skip the PyTorch configuration prompt. Required for "
                "non-interactive installs unless --no-torch-config is used."
            ),
        ),
    ] = False,
    sync_after: Annotated[
        bool,
        typer.Option(
            "--sync",
            help=(
                "Run `uv sync --reinstall-package torch` after PyTorch "
                "configuration changes are applied."
            ),
        ),
    ] = False,
    provision: Annotated[
        bool,
        typer.Option(
            "--provision/--no-provision",
            help=(
                "Provision external dependencies (models and the Qdrant "
                "server binary) after enrollment. On by default; "
                "--no-provision sets up the workspace only."
            ),
        ),
    ] = True,
    local_only: Annotated[
        bool,
        typer.Option(
            "--local-only",
            help=(
                "Use the on-disk store instead of the supervised Qdrant "
                "server: skips the Qdrant binary download and persists the "
                "local backend so `server start` honours it. The minimal / "
                "CI / air-gapped alternative to the server-first default."
            ),
        ),
    ] = False,
    skip_torch: Annotated[
        bool,
        typer.Option(
            "--skip-torch",
            help="Skip the PyTorch provisioning step (finer than --local-only).",
        ),
    ] = False,
    skip_models: Annotated[
        bool,
        typer.Option(
            "--skip-models",
            help="Skip the embedding/reranker model provisioning step.",
        ),
    ] = False,
    skip_qdrant: Annotated[
        bool,
        typer.Option(
            "--skip-qdrant",
            help="Skip the Qdrant server binary provisioning step.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Set up vaultspec-rag in a workspace.

    Creates the required workspace folders, installs bundled rules and
    integration files, and syncs the files used by supported tools. By
    default, install also provisions the external dependencies the
    server-first default needs - the embedding/reranker models and the
    pinned Qdrant server binary - and asks before changing PyTorch package
    configuration. Use --local-only for the minimal local backend (skips
    the binary), the finer --skip-torch/--skip-models/--skip-qdrant flags
    for partial opt-out, and --no-provision to set up the workspace only;
    use --yes or --no-torch-config for non-interactive runs.
    """
    import sys as _sys

    from rich.prompt import Confirm

    from ..commands import install_run

    # Honour the global ``--target`` from the root callback. Click
    # consumes group options before subcommand options, so the user
    # invoking ``vaultspec-rag --target /path install`` would lose
    # the path entirely if we only read the local ``target``.
    effective_target = target or _global_target(ctx)

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
    if skip_torch:
        provision_skip.add("torch")
    if skip_models:
        provision_skip.add("models")
    if skip_qdrant:
        provision_skip.add("qdrant")

    try:
        report = install_run(
            path=effective_target,
            upgrade=upgrade,
            dry_run=dry_run,
            force=force,
            skip=set(skip or []),
            configure_torch=configure_torch,
            assume_yes=yes,
            sync_after=sync_after,
            confirm=confirm_fn,
            provision=provision,
            local_only=local_only,
            provision_skip=provision_skip,
            torch_group=torch_group,
        )
    except Exception as exc:
        _cli.console.print(
            f"Install failed: {exc}",
            markup=False,
            highlight=False,
            soft_wrap=True,
        )
        raise typer.Exit(code=1) from exc

    if json_output:
        import json as _json

        _cli.console.print_json(
            _json.dumps(report.to_dict(), default=str), highlight=False
        )
    else:
        _render_install_report(report)

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
    from ..torch_config import TorchConfigAction

    if configure_torch and report.torch_config_action in {
        TorchConfigAction.ERROR,
        TorchConfigAction.SKIPPED_EOF,
        TorchConfigAction.SKIPPED_NON_TTY,
    }:
        raise typer.Exit(code=2)


@app.command("uninstall")
def handle_uninstall(
    ctx: typer.Context,
    target: Annotated[
        Path | None,
        typer.Option(
            "--target",
            "-t",
            help="Workspace path (default: current working directory).",
            dir_okay=True,
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    remove_data: Annotated[
        bool,
        typer.Option(
            "--remove-data",
            help="Also remove index data under .vault/data/.",
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
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip confirmation prompts.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Remove vaultspec-rag setup from a workspace.

    Without --force, this only previews what would be removed. Vault
    documents and index data are preserved unless --remove-data is set.
    """
    from ..commands import uninstall_run

    # Honour the global ``--target`` from the root callback (see
    # handle_install for the rationale).
    effective_target = target or _global_target(ctx)

    try:
        report = uninstall_run(
            path=effective_target,
            remove_data=remove_data,
            dry_run=dry_run,
            force=force,
            skip=set(skip or []),
            assume_yes=yes,
        )
    except Exception as exc:
        _cli.console.print(
            f"Uninstall failed: {exc}",
            markup=False,
            highlight=False,
            soft_wrap=True,
        )
        raise typer.Exit(code=1) from exc

    if json_output:
        import json as _json

        _cli.console.print_json(
            _json.dumps(report.to_dict(), default=str), highlight=False
        )
        return

    _render_uninstall_report(report)
