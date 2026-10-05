"""``install`` and ``uninstall`` commands: workspace enrollment mirror."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast

import click
import typer
from tomlkit.exceptions import ParseError
from typer._types import TyperChoice
from typer.core import TyperCommand, TyperOption
from typer.models import TyperPath
from vaultspec_core.config import is_unattended
from vaultspec_core.core.enums import (
    InstallMode,
)

import vaultspec_rag.cli as _cli

from ._app import JSON_OPTION_HELP, _global_target, app
from ._progress import StartupStatusReporter
from ._provision_progress import ReporterProvisionProgress
from ._render import _plain, _render_install_report, _render_uninstall_report

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import TextIO

    from typer._click import Context as ClickContext

    from ..commands._models import ConfirmFn, InstallReport, UninstallReport

    # Click types ``Context.params`` as ``dict[str, Any]`` because the keys
    # and value types are only known once a command's options are parsed at
    # runtime. Each TypedDict below is the producer-side cast target for one
    # command's ``invoke``: the field types mirror the ``TyperOption``
    # declarations the corresponding ``__init__`` registers, so a single
    # cast on ``ctx.params`` replaces every per-field ``Any`` read below it.
    class _InstallParams(TypedDict):
        target: Path | None
        upgrade: bool
        dry_run: bool
        force: bool
        skip: tuple[str, ...]
        mode: str | None
        torch_config: bool
        tool_repair: bool
        torch_group: str | None
        yes: bool
        sync: bool
        provision: bool
        mcp: bool
        local_only: bool
        skip_torch: bool
        skip_models: bool
        skip_qdrant: bool
        json: bool
        no_hints: bool

    class _UninstallParams(TypedDict):
        target: Path | None
        remove_data: bool
        dry_run: bool
        force: bool
        skip: tuple[str, ...]
        yes: bool
        json: bool


# Group name used when ``--torch-group`` is passed without an explicit
# value. Surfaced both in the help text and as the Click ``flag_value``.
_DEFAULT_TORCH_GROUP = "dev"

# ``--skip``'s empty default, shared by both commands below. Bound to an
# explicitly-typed name rather than passed as the inline literal ``()``:
# ``TyperOption.__init__``'s ``default`` parameter is typed ``Any | None``
# upstream, and pyright's bidirectional inference widens an inline literal
# passed there to ``Any``; a pre-typed local keeps the tuple's real type.
_NO_SKIP: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _InstallOptions:
    target: Path | None
    upgrade: bool
    dry_run: bool
    force: bool
    skip: tuple[str, ...]
    mode: InstallMode | None
    configure_torch: bool
    tool_repair: bool
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
    no_hints: bool


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
        # ``*args``/``**kwargs`` forward whatever ``TyperCommand.__init__``
        # (typer instantiates this class directly as its ``cls=``) is
        # called with. A field-for-field mirror of that constructor was
        # tried and reverted: it exceeds the project's 5-argument cap
        # (PLR0913), which is enforced with no per-call suppression
        # allowed. Genuinely dynamic; left as ``Any``.
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
                    help="Override existing files. Never answers the torch-config "
                    "confirmation prompt; use --yes for that.",
                ),
                TyperOption(
                    param_decls=["--skip"],
                    type=str,
                    multiple=True,
                    default=_NO_SKIP,
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
                        "--no-torch-config takes precedence over --yes."
                    ),
                ),
                TyperOption(
                    param_decls=["--tool-repair/--no-tool-repair"],
                    default=True,
                    is_flag=True,
                    help=(
                        "Check whether a persistent uv tool environment holds a "
                        "processor-only torch build, and report the command that "
                        "repairs it. Nothing is installed or replaced by this "
                        "check. --no-tool-repair skips it entirely."
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
                TyperOption(
                    param_decls=["--no-hints"],
                    default=False,
                    is_flag=True,
                    help="Suppress next-step advisory hints.",
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

    def invoke(self, ctx: "ClickContext") -> None:
        """Dispatch parsed Click parameters as one install request."""
        params = cast("_InstallParams", ctx.params)
        mode = params["mode"]
        return _run_install(
            ctx,
            _InstallOptions(
                target=params["target"],
                upgrade=params["upgrade"],
                dry_run=params["dry_run"],
                force=params["force"],
                skip=params["skip"],
                mode=InstallMode(mode) if mode is not None else None,
                configure_torch=params["torch_config"],
                tool_repair=params["tool_repair"],
                torch_group=params["torch_group"],
                yes=params["yes"],
                sync_after=params["sync"],
                provision=params["provision"],
                install_mcp=params["mcp"],
                local_only=params["local_only"],
                skip_torch=params["skip_torch"],
                skip_models=params["skip_models"],
                skip_qdrant=params["skip_qdrant"],
                json_output=params["json"],
                no_hints=params["no_hints"],
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


def _run_install(ctx: "ClickContext", options: _InstallOptions) -> None:
    """Enrol the workspace and provision dependencies for one install request."""

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

    confirm_fn = _confirmation_hook(_confirm, json_output=options.json_output)

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
        # See _InstallCommand.__init__: a field-for-field mirror of
        # TyperCommand's constructor was tried and reverted (exceeds the
        # project's 5-argument cap, PLR0913, with no suppression allowed).
        # Genuinely dynamic; left as ``Any``.
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
                    default=_NO_SKIP,
                    help="Skip a component (repeatable).",
                ),
                TyperOption(
                    param_decls=["--yes", "-y"],
                    default=False,
                    is_flag=True,
                    hidden=True,
                    help=(
                        "Deprecated: uninstall has no prompt to bypass. "
                        "Accepted for backward compatibility only."
                    ),
                ),
                TyperOption(
                    param_decls=["--json"],
                    default=False,
                    is_flag=True,
                    help=JSON_OPTION_HELP,
                ),
            )
        )

    def invoke(self, ctx: "ClickContext") -> None:
        """Dispatch parsed Click parameters as one uninstall request."""
        params = cast("_UninstallParams", ctx.params)
        return _run_uninstall(
            ctx,
            _UninstallOptions(
                target=params["target"],
                remove_data=params["remove_data"],
                dry_run=params["dry_run"],
                force=params["force"],
                skip=params["skip"],
                yes=params["yes"],
                json_output=params["json"],
            ),
        )


@app.command(
    "uninstall",
    cls=_UninstallCommand,
    help=(
        "Remove vaultspec-rag setup from a workspace. Requires --force to "
        "execute; use --dry-run to preview what would be removed instead."
    ),
)
def handle_uninstall() -> None:
    """Register the custom command; it dispatches through ``_UninstallCommand``."""


def _run_uninstall(ctx: "ClickContext", options: _UninstallOptions) -> None:
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
            skip=set(options.skip),
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
