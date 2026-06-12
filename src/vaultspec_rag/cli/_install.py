"""``install`` and ``uninstall`` commands: workspace enrollment mirror."""

from pathlib import Path
from typing import Annotated

import typer

import vaultspec_rag.cli as _cli

from ._app import _global_target, app
from ._render import _render_install_report, _render_uninstall_report


@app.command("install")
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
                "Patch pyproject.toml with the cu130 torch index. "
                "--no-torch-config takes precedence over --force / --yes."
            ),
        ),
    ] = True,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help=(
                "Skip the torch-config confirmation prompt (required on "
                "non-TTY runs). --no-torch-config opts out without "
                "applying."
            ),
        ),
    ] = False,
    sync_after: Annotated[
        bool,
        typer.Option(
            "--sync",
            help=(
                "Run `uv sync --reinstall-package torch` after the patch "
                "lands. Silently no-ops when the patch step did not apply."
            ),
        ),
    ] = False,
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

    Torch-config gating (highest precedence first):

    - ``--no-torch-config`` always wins. The patch is not applied
      regardless of any other flag, and ``torch_config_action`` is
      reported as ``disabled``.
    - On a non-TTY without ``--yes`` or ``--force``, the patch is
      skipped with a warning naming the bypass flags.
      ``torch_config_action`` is ``skipped-non-tty`` and the command
      exits with a non-zero code so CI fails loudly.
    - ``--yes`` and ``--force`` both bypass the confirmation prompt.
      They differ elsewhere: ``--force`` also re-seeds bundled files
      and prunes orphaned sync state.
    - On a TTY without ``--yes`` / ``--force``, the user is prompted.
      Pressing Enter declines (default-no) - pass ``--yes`` to say
      yes to all confirmations in one shot.
    - The command exits non-zero (code 2) when torch-config terminates
      in ``error``, ``skipped-eof``, or ``skipped-non-tty``. Other
      non-applied terminal states (``declined``, ``conflict``,
      ``absent``, ``disabled``) exit 0 because they reflect user
      intent or expected workspace state.

    Flag names mirror ``vaultspec-core install`` exactly. The
    positional ``provider`` argument core takes is omitted because
    rag has no provider concept of its own - propagation flows
    through core's existing per-provider sync.
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

        _cli.console.print_json(_json.dumps(report.to_dict(), default=str))
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
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip confirmation prompts (reserved for forward compat).",
        ),
    ] = False,
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

        _cli.console.print_json(_json.dumps(report.to_dict(), default=str))
        return

    _render_uninstall_report(report)
