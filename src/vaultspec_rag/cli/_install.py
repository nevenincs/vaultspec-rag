"""``install`` and ``uninstall`` commands: workspace enrollment mirror."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from tomlkit.exceptions import ParseError
from typer.core import TyperCommand
from vaultspec_core.config import is_unattended
from vaultspec_core.core.enums import (
    InstallMode,
)

import vaultspec_rag.cli as _cli

from ._app import JsonMode, _global_target, app
from ._option_groups import with_option_group
from ._progress import StartupStatusReporter
from ._provision_progress import ReporterProvisionProgress
from ._render import _plain, _render_install_report, _render_uninstall_report

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import TextIO

    from typer._click import Context as ClickContext

    from ..commands._models import ConfirmFn, InstallReport, UninstallReport


# Group name used when ``--torch-group`` is passed without an explicit
# value. Surfaced in the help text and substituted for the missing value.
_DEFAULT_TORCH_GROUP = "dev"

_TORCH_GROUP_FLAG = "--torch-group"

_SKIP_HELP = "Skip a component (repeatable)."


@dataclass(frozen=True, slots=True)
class _InstallOptions:
    target: Annotated[
        Path | None,
        typer.Option(
            "--target",
            "-t",
            dir_okay=True,
            file_okay=False,
            resolve_path=True,
            help="Workspace path (default: current working directory).",
        ),
    ] = None
    upgrade: Annotated[
        bool,
        typer.Option(
            "--upgrade",
            help="Refresh bundled rules and integration files even if present.",
        ),
    ] = False
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview changes without writing.")
    ] = False
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite setup files that already exist.")
    ] = False
    skip: Annotated[
        list[str] | None, typer.Option("--skip", hidden=True, help=_SKIP_HELP)
    ] = None
    mode: Annotated[
        InstallMode | None,
        typer.Option(
            "--mode",
            help=(
                "How your AI assistant launches vaultspec-rag: 'tool', "
                "or from this project's environment as a 'dependency' "
                "or 'dev' dependency. Detected from pyproject.toml when "
                "omitted."
            ),
        ),
    ] = None
    configure_torch: Annotated[
        bool,
        typer.Option(
            "--torch-config/--no-torch-config",
            hidden=True,
            help=(
                "Configure the CUDA PyTorch package source in pyproject.toml. "
                "--no-torch-config takes precedence over --yes."
            ),
        ),
    ] = True
    tool_repair: Annotated[
        bool,
        typer.Option(
            "--tool-repair/--no-tool-repair",
            hidden=True,
            help=(
                "Check whether a persistent uv tool environment holds a "
                "processor-only torch build, and report the command that "
                "repairs it. Nothing is installed or replaced by this "
                "check. --no-tool-repair skips it entirely."
            ),
        ),
    ] = True
    torch_group: Annotated[
        str | None,
        typer.Option(
            _TORCH_GROUP_FLAG,
            hidden=True,
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
    ] = None
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help=(
                "Answer yes to setup prompts, for runs without a terminal. "
                "Never approves the MCP launch: run install at a terminal "
                "to review and approve it."
            ),
        ),
    ] = False
    sync_after: Annotated[
        bool,
        typer.Option(
            "--sync",
            hidden=True,
            help=(
                "Run `uv sync --reinstall-package torch` after PyTorch "
                "configuration changes are applied."
            ),
        ),
    ] = False
    provision: Annotated[
        bool,
        typer.Option(
            "--provision/--no-provision",
            help=(
                "Download the search models and the Qdrant server now, "
                "when this installation carries the GPU packages "
                "(default). Otherwise `server start` downloads them."
            ),
        ),
    ] = True
    install_mcp: Annotated[
        bool,
        typer.Option(
            "--mcp/--no-mcp",
            help=(
                "Connect your AI assistant through MCP (default). With "
                "--no-mcp, only the command line is set up."
            ),
        ),
    ] = True
    local_only: Annotated[
        bool,
        typer.Option(
            "--local-only",
            help=(
                "Keep the index in an on-disk store instead of the Qdrant "
                "server, for CI, offline or small projects. `server start` "
                "remembers the choice."
            ),
        ),
    ] = False
    skip_models: Annotated[
        bool,
        typer.Option(
            "--skip-models",
            hidden=True,
            help="Skip the embedding/reranker model provisioning step.",
        ),
    ] = False
    skip_qdrant: Annotated[
        bool,
        typer.Option(
            "--skip-qdrant",
            hidden=True,
            help="Skip the Qdrant server binary provisioning step.",
        ),
    ] = False
    json_output: JsonMode = False
    no_hints: Annotated[
        bool,
        typer.Option(
            "--no-hints", hidden=True, help="Suppress next-step advisory hints."
        ),
    ] = False


class _InstallCommand(TyperCommand):
    """Install command that gives ``--torch-group`` an optional value.

    Typer declares an option as either a flag or a value-taking option, so a
    bare ``--torch-group`` is completed here before parsing: alone it
    resolves to the default group name, ``--torch-group NAME`` to ``NAME``,
    and an omitted flag stays ``None`` (the historic
    ``[project].dependencies`` placement).
    """

    def parse_args(self, ctx: "ClickContext", args: list[str]) -> list[str]:
        completed = list(args)
        for index, token in enumerate(completed):
            if token == "--":
                break
            following = completed[index + 1] if index + 1 < len(completed) else None
            if token == _TORCH_GROUP_FLAG and (
                following is None or following.startswith("-")
            ):
                completed[index] = f"{_TORCH_GROUP_FLAG}={_DEFAULT_TORCH_GROUP}"
        return super().parse_args(ctx, completed)


def _confirmation_hook(
    confirm: "ConfirmFn",
    *,
    json_output: bool,
    environ: "Mapping[str, str] | None" = None,
    stdin: "TextIO | None" = None,
    stdout: "TextIO | None" = None,
) -> "ConfirmFn | None":
    """Return the prompt callback, or ``None`` when nobody is watching.

    Whether anybody is watching is one framework question with one answer: a
    machine envelope on standard output, a session that declares it, or
    standard streams that are not a terminal. Deciding it from standard input
    alone got two of those wrong - a run under ``--json`` went on prompting
    at a terminal nobody was reading the output of, and a continuous-
    integration run that inherited a terminal prompted into a log.

    Args:
        confirm: The callback that would ask the operator.
        json_output: Whether this invocation emits a machine envelope.
        environ: The environment to read; ``None`` reads the process's own.
        stdin: The stream an answer would be read from; ``None`` uses the
            process's own.
        stdout: The stream a question would be shown on; ``None`` uses the
            process's own.

    Returns:
        *confirm* when a person could answer, ``None`` otherwise. ``None`` is
        what routes the run to the skipped branch, which reports the skip and
        names the flag that would have granted consent.

    Raises:
        ConfigurationError: If the session's own marker carries a word the
            boolean vocabulary does not recognise.
    """
    unattended = is_unattended(
        json_output=json_output, environ=environ, stdin=stdin, stdout=stdout
    )
    return None if unattended else confirm


def _ask_operator(prompt: str) -> bool:
    """Ask the operator one yes-or-no question at the terminal.

    The default is no: pressing Enter on a prompt without reading it must not
    authorise a write, such as patching the user's ``pyproject.toml`` or
    approving an MCP launch.

    The prompt is shown as the literal text it is. A launch under review
    carries brackets, such as ``vaultspec-rag[mcp]``, which Rich would read as
    markup and drop from what the operator is approving.
    """
    from rich.prompt import Confirm
    from rich.text import Text

    return Confirm.ask(Text(prompt), default=False, console=_cli.console)


def _report_command_failure(
    exc: BaseException, *, prefix: str, json_output: bool
) -> None:
    """Report a failure that stopped install or uninstall before any report.

    Under ``--json`` this is core's ``vaultspec.error.v1`` envelope rather
    than a plain line, so a scripted caller parsing every ``--json`` run the
    same way sees a failure rather than empty stdout and a bare exit code.

    Args:
        exc: The exception that stopped the run.
        prefix: ``"Install failed"`` or ``"Uninstall failed"``.
        json_output: Whether this invocation requested ``--json``.
    """
    message = f"{prefix}: {exc}"
    if json_output:
        from vaultspec_core.envelope import render_error_envelope

        typer.echo(render_error_envelope(message))
    else:
        _plain(message, soft_wrap=True)


def _install_outcome(
    report: "InstallReport", *, configure_torch: bool
) -> tuple[str, int]:
    """Classify a completed install run into its envelope status and exit code.

    Both outcomes below exit non-zero so CI fails loudly (issue #83 finding
    3: an operator who wanted the torch-config patch and did not get it must
    not read a green run), but they are not the same outcome and the shared
    exit-code table keeps them apart: 1 is a failure, and 2 is a run that
    completed with a required step skipped for lack of consent. The envelope
    status word says the same thing in words. ``DECLINED`` (the user's own
    answer to a prompt) and ``CONFLICT`` (the user's own customised state,
    the warning is the signal) stay a plain completed status; so do
    ``ABSENT`` and ``DISABLED``, both intentional opt-outs.

    Args:
        report: The completed run's report.
        configure_torch: Whether this run asked to configure PyTorch at all;
            an explicit opt-out never turns its own absence into a failure.

    Returns:
        ``(status, exit_code)``: the canonical outcome word for the
        envelope, and the process exit code that outcome carries.
    """
    from ..torch_config._constants import TorchConfigAction

    torch_errored = (
        configure_torch and report.torch_config_action is TorchConfigAction.ERROR
    )
    # The one place this run declined a required step for lack of consent
    # rather than failing outright - the shared exit-code table's "completed
    # with a required step skipped" (e.g. an unattended run with nobody to
    # answer the torch-config prompt).
    torch_skipped = configure_torch and report.torch_config_action in {
        TorchConfigAction.SKIPPED_EOF,
        TorchConfigAction.SKIPPED_NON_TTY,
    }
    # A dependency the run was asked to provision and could not is a failure of
    # the run, not a remark on it: the models or the Qdrant server are still
    # missing, and a caller that reads only the exit code must learn that.
    # Enrollment has completed by then and the envelope still carries the whole
    # report, so the step that failed and its remedy are both there, and a
    # re-run finds the enrollment unchanged and tries the step again. It
    # outranks a skipped consent step because it is the more serious of the
    # two and the shared table gives failure the lower code.
    provisioning_failed = (
        report.provision_outcome is not None and not report.provision_outcome.ok
    )
    hard_failure = (
        report.mcp_extra_action == "error"
        or report.mcp_sync_failed
        or (
            report.tool_torch_repair is not None
            and report.tool_torch_repair.blocks_install
        )
        or torch_errored
        or provisioning_failed
    )
    if hard_failure:
        return "failed", 1
    if torch_skipped:
        return "skipped", 2
    if report.action == "dry_run":
        return "unchanged", 0
    if report.action == "upgrade":
        return "updated", 0
    return "created", 0


def _install_next_step_hint(status: str, *, no_hints: bool) -> dict[str, object] | None:
    """Return the install envelope's next-step hint, or ``None`` when withheld.

    Withheld under ``--no-hints`` or ``VAULTSPEC_NO_HINTS`` (core's shared
    :func:`~vaultspec_core.envelope.hints_suppressed`, so the one suppression
    contract holds here too), inside a git commit hook (the same function),
    and for every status but a completed enrollment: a dry run previewed
    nothing to check, and a failed or skipped run has a warning to read
    first, not a follow-up command.

    Args:
        status: The envelope's own outcome word for this run.
        no_hints: Whether the invocation passed ``--no-hints``.

    Returns:
        The structured hint, or ``None``.
    """
    from vaultspec_core.envelope import hints_suppressed

    from .._operator_commands import server_status_command

    if status not in {"created", "updated"} or hints_suppressed(no_hints=no_hints):
        return None
    return {
        "text": "Check the resident server and provisioning state",
        "command": server_status_command(),
    }


@app.command(
    "install",
    cls=_InstallCommand,
    help=(
        "Set up vaultspec-rag in this repository.\n\n"
        "Connects your AI assistant and creates the .vault/ folder. At a "
        "terminal it asks you to approve the MCP launch it enrolls. Then run "
        "`vaultspec-rag server start`, which downloads what the service still "
        "needs. Exits non-zero when a step failed."
    ),
)
@with_option_group
def handle_install(ctx: typer.Context, options: _InstallOptions) -> None:
    """Enrol the workspace and provision dependencies for one install request."""

    from ..commands._install import install_run

    # Honour the global ``--target`` from the root callback. Click
    # consumes group options before subcommand options, so the user
    # invoking ``vaultspec-rag --target /path install`` would lose
    # the path entirely if we only read the local ``target``.
    effective_target = options.target or _global_target(ctx)

    confirm_fn = _confirmation_hook(_ask_operator, json_output=options.json_output)

    # Map the per-dependency opt-out flags onto the front door's skip
    # token set. ``--local-only`` already drops the qdrant binary in the
    # front door, so the explicit ``--skip-qdrant`` is the redundant-but-
    # honest finer control; both are unioned here. There is no such flag for
    # torch: the torch step belongs to enrollment, where ``--no-torch-config``
    # skips it, and the front door never runs it for this command.
    provision_skip: set[str] = set()
    if options.skip_models:
        provision_skip.add("models")
    if options.skip_qdrant:
        provision_skip.add("qdrant")

    # The model and Qdrant fetches report through the same reporter the service
    # verbs use, so an install shows the download it is waiting on. The live
    # region opens only when provisioning first reports - after the questions
    # above have been answered - and ``--json`` keeps it silent.
    reporter = StartupStatusReporter(json_mode=options.json_output)
    try:
        with ReporterProvisionProgress(reporter) as provision_progress:
            report = install_run(
                path=effective_target,
                upgrade=options.upgrade,
                dry_run=options.dry_run,
                force=options.force,
                skip=set(options.skip or ()),
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
                repair_tool_torch=options.tool_repair,
                # A multi-gigabyte download with no output reads as a hang,
                # and a broker reading JSON must see one envelope and nothing
                # else.
                stream_repair=not options.json_output,
                provision_progress=provision_progress,
            )
    except ParseError as exc:
        _report_command_failure(
            exc, prefix="Install failed", json_output=options.json_output
        )
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        _report_command_failure(
            exc, prefix="Install failed", json_output=options.json_output
        )
        raise typer.Exit(code=1) from exc

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
    status, exit_code = _install_outcome(
        report, configure_torch=options.configure_torch
    )

    if options.json_output:
        from vaultspec_core.envelope import render_install_envelope

        hints = _install_next_step_hint(status, no_hints=options.no_hints)
        typer.echo(
            render_install_envelope(
                "rag.install", status, report.to_dict(), hints=hints
            )
        )
    else:
        _render_install_report(report)
        # The report's "PyTorch configuration" line describes pyproject.toml,
        # not the wheel in the active interpreter. When torch was meant to be
        # provisioned (not an explicit opt-out), probe the real wheel and warn
        # loudly if it is CPU-only or absent - a GPU-only project must never
        # report success over a CPU torch. An explicit opt-out is respected.
        #
        # A refused run has already described that interpreter, in the repair
        # section, from the same verdict: saying it again in different words
        # is what made one run print two diagnoses and three commands. Where
        # the run did proceed, the repair's verdict is handed over so the
        # child-interpreter probe runs at most once per command.
        if options.configure_torch and not report.refused:
            from ._gpu_errors import warn_if_active_torch_not_accelerator

            repair = report.tool_torch_repair
            warn_if_active_torch_not_accelerator(
                capability=repair.capability if repair is not None else None
            )

    if exit_code:
        raise typer.Exit(code=exit_code)


@dataclass(frozen=True, slots=True)
class _UninstallOptions:
    target: Annotated[
        Path | None,
        typer.Option(
            "--target",
            "-t",
            dir_okay=True,
            file_okay=False,
            resolve_path=True,
            help="Workspace path (default: current working directory).",
        ),
    ] = None
    remove_data: Annotated[
        bool,
        typer.Option(
            "--remove-data", help="Also remove index data under .vault/data/."
        ),
    ] = False
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview changes without removing.")
    ] = False
    force: Annotated[
        bool,
        typer.Option("--force", help="Required to execute. Uninstall is destructive."),
    ] = False
    skip: Annotated[list[str] | None, typer.Option("--skip", help=_SKIP_HELP)] = None
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            hidden=True,
            help=(
                "Deprecated: uninstall has no prompt to bypass. "
                "Accepted for backward compatibility only."
            ),
        ),
    ] = False
    json_output: JsonMode = False


@app.command(
    "uninstall",
    help=(
        "Remove vaultspec-rag setup from a workspace. Requires --force to "
        "execute; use --dry-run to preview what would be removed instead."
    ),
)
@with_option_group
def handle_uninstall(ctx: typer.Context, options: _UninstallOptions) -> None:
    """Remove vaultspec-rag setup from a workspace.

    Requires --force to execute; without it (and without --dry-run to
    preview), the command refuses to run. Vault documents and index data
    are preserved unless --remove-data is set.
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
            skip=set(options.skip or ()),
            assume_yes=options.yes,
        )
    except Exception as exc:
        _report_command_failure(
            exc, prefix="Uninstall failed", json_output=options.json_output
        )
        raise typer.Exit(code=1) from exc

    status = _uninstall_status(report)

    if options.json_output:
        from vaultspec_core.envelope import render_install_envelope

        typer.echo(render_install_envelope("rag.uninstall", status, report.to_dict()))
    else:
        _render_uninstall_report(report)

    if report.mcp_sync_failed:
        raise typer.Exit(code=1)


def _uninstall_status(report: "UninstallReport") -> str:
    """Return the envelope's canonical outcome word for a completed uninstall.

    Args:
        report: The completed run's report.

    Returns:
        ``"failed"`` when any requested MCP lifecycle operation failed,
        ``"unchanged"`` for a preview or a run that removed nothing,
        ``"removed"`` otherwise.
    """
    if report.mcp_sync_failed:
        return "failed"
    if report.action == "dry_run":
        return "unchanged"
    if report.removed:
        return "removed"
    return "unchanged"
