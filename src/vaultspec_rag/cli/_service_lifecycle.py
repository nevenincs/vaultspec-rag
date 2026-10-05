"""``server`` lifecycle: the shared primitives and the ``warmup`` command.

Holds the console primitives and the discovery-file decision helper the start,
stop, and status renderers share, plus ``warmup``. Those verbs live in
``_service_start``, ``_service_stop``, and ``_status_render``, and import these
primitives from here; nothing is imported back, so this module exports only
what it defines and the cycle that used to need a trailing import block is
gone. ``cli.__init__`` registers the verb modules for their decorators.
"""

from __future__ import annotations

from dataclasses import dataclass

import typer

from ._app import server_root_app
from ._gpu_errors import _handle_gpu_error
from ._progress import StartupStatusReporter
from ._render import _emit_json, _plain

__all__ = [
    "_LifecycleFailure",
    "_fail_lifecycle",
    "_lifecycle_success",
    "_print_detail_line",
    "_print_lifecycle_lines",
    "_print_lifecycle_next_actions",
    "_process_line",
    "_should_unlink_discovery_file",
    "service_warmup",
]


def _print_lifecycle_lines(title: str, *lines: str) -> None:
    _plain(title)
    for line in lines:
        _plain(line, soft_wrap=True)


def _print_lifecycle_next_actions(*commands: str) -> None:
    _plain("Next actions:")
    for command in commands:
        _plain(f"  {command}")


@dataclass(frozen=True, slots=True)
class _LifecycleFailure:
    """The fixed fields every failed lifecycle outcome carries."""

    command: str
    error: str
    message: str
    human_lines: tuple[str, ...]
    next_actions: tuple[str, ...] = ()


def _fail_lifecycle(
    json_mode: bool,
    request: _LifecycleFailure,
    **data: object,
) -> typer.Exit:
    """Render a failed lifecycle outcome and RETURN the ``typer.Exit`` to raise.

    One renderer for every terminal failure of every lifecycle verb. A verb a
    broker drives owes exactly one structured envelope on stdout per exit path,
    so the branch that decides envelope-versus-human-lines exists once: a second
    copy is free to drift into emitting two envelopes, or none, on some path
    nobody re-checked.

    Failure is always exit 1, in both modes. An outcome that leaves the
    requested state unachieved must not read as success to a script.

    Returns the ``Exit`` rather than raising it so the call site keeps an
    explicit ``raise`` and its control flow stays legible.
    """
    if json_mode:
        _emit_json(
            False,
            request.command,
            error=request.error,
            message=request.message,
            data=dict(data) or None,
        )
    else:
        _print_lifecycle_lines(request.message, *request.human_lines)
        if request.next_actions:
            _print_lifecycle_next_actions(*request.next_actions)
    return typer.Exit(code=1)


def _lifecycle_success(
    json_mode: bool,
    *,
    command: str,
    status: str,
    human_title: str,
    human_lines: tuple[str, ...] = (),
    **data: object,
) -> None:
    """Emit a successful lifecycle outcome. The caller returns after this.

    The success twin of :func:`_fail_lifecycle`, and one renderer for every
    terminal success of every lifecycle verb. The envelope-versus-human-lines
    branch exists once for the same reason it does on the failure side: a
    second copy is free to drift into emitting two envelopes, or none, on some
    path nobody re-checked.

    An already-satisfied request is a success and reaches here with an
    already-done ``status``, so a supervising broker reads the idempotent case
    as satisfied rather than as a fault.
    """
    if json_mode:
        _emit_json(True, command, data={"status": status, **data})
    else:
        _print_lifecycle_lines(human_title, *human_lines)


def _process_line(pid: object) -> str:
    return f"Process ID: {pid}"


def _print_detail_line(label: str, value: object) -> None:
    _plain(f"{label}: {value}")


def _should_unlink_discovery_file(pid_alive: bool) -> bool:
    """Decide whether a lifecycle command may remove the discovery file.

    The discovery file is removed only when the recorded holder is *confirmed
    dead* - its PID is not alive. An ambiguous result (the PID is alive but a
    ``/health`` token round-trip or PID-identity heuristic transiently missed)
    must never delete a possibly-live service's discovery file, which is the
    issue #204 flapping cause where a routine ``status`` or second ``start``
    erased a running daemon's file. Pure and unit-testable: the caller passes
    the already-computed liveness signal.
    """
    return not pid_alive


@server_root_app.command(
    "warmup",
    help=(
        "Download GPU model files before they are needed. "
        "Run once before the first index to avoid model download latency at "
        "search time."
    ),
)
def service_warmup() -> None:
    """Download GPU model files before they are needed."""
    from .._sync_vocabulary import ProvisionAction
    from ..commands._provision import ProvisionStep, client_skip, provision_models
    from ._provision_progress import ReporterProvisionProgress

    # Asked before the accelerator is loaded: a client holds no model and has
    # no torch to load, and reporting that as a missing GPU build would send
    # it to install one.
    not_needed = client_skip(ProvisionStep.MODELS)
    if not_needed is not None:
        _print_detail_line("Models", not_needed.detail)
        return

    try:
        from .._gpu import load_accelerator

        load_accelerator()
    except (ImportError, RuntimeError) as exc:
        _handle_gpu_error(exc)

    # No ``--json`` mode on this verb, so the reporter always speaks; it is the
    # only thing an operator sees during a multi-gigabyte, effectively
    # unbounded download. The per-model lines are the verb's result, so they
    # are printed once the fetch returns rather than through the reporter,
    # whose lines are progress and leave stdout alone off a terminal.
    with (
        StartupStatusReporter(json_mode=False) as reporter,
        ReporterProvisionProgress(reporter) as progress,
    ):
        reporter.announce("Model warmup")
        result = provision_models(progress=progress)

    for repo in result.repos:
        _print_detail_line(repo.label, f"{repo.repo} {repo.detail}")
    if result.action == ProvisionAction.FAILED:
        _plain(f"Error: {result.detail}", soft_wrap=True)
        raise typer.Exit(code=1)
