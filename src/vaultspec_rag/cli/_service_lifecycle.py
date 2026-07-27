"""``server`` lifecycle: the shared primitives and the ``warmup`` command.

Holds the console primitives and the discovery-file decision helper the start,
stop, and status renderers share, plus ``warmup``. Those verbs live in
``_service_start``, ``_service_stop``, and ``_status_render``, and import these
primitives from here; nothing is imported back, so this module exports only
what it defines and the cycle that used to need a trailing import block is
gone. ``cli.__init__`` registers the verb modules for their decorators.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

import typer

import vaultspec_rag.cli as _cli

from ..config import EnvVar, configured_model_repos, get_config
from ._app import server_app
from ._gpu_errors import _handle_gpu_error
from ._progress import StartupStatusReporter
from ._render import _emit_json, _plain

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
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


def _fail_lifecycle(
    json_mode: bool,
    *,
    command: str,
    error: str,
    message: str,
    human_lines: tuple[str, ...],
    next_actions: tuple[str, ...] = (),
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
            command,
            error=error,
            message=message,
            data=dict(data) or None,
        )
    else:
        _print_lifecycle_lines(message, *human_lines)
        if next_actions:
            _print_lifecycle_next_actions(*next_actions)
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


def _warmup_failure_detail(repo_id: str, exc: Exception) -> str:
    """Explain a failed model fetch as an operator-actionable line.

    The cache location comes from the config rather than a default spelled
    inline: an operator who set ``HF_HOME`` was previously sent to the
    library's default directory to clean up a partial download that is not
    there.
    """
    msg = str(exc)
    if "401" in msg or "403" in msg or "GatedRepo" in msg:
        return f"{repo_id} auth required; run huggingface-cli login"
    cache = get_config().hf_cache_location
    return f"{repo_id} failed: {exc} (partial cache may remain in {cache})"


def _warmup_fetch_model(
    download: Callable[..., object],
    progress: StartupStatusReporter,
    *,
    repo_id: str,
    label: str,
    position: int,
    total: int,
) -> str:
    """Fetch one model repo with live progress; return its result line.

    The fetch is minutes long and its size is known to the hub, so the stage
    names WHICH repo of how many is running and the tracker turns the hub's own
    counters into bytes-of-bytes. Every failure is reported and none aborts the
    remaining models: a warmup that stops at the first gated repo leaves the
    operator re-running it to discover the next one.
    """
    from ._hf_progress import SnapshotProgress

    heading = f"Downloading {label} ({position}/{total})"
    progress.stage(f"{heading}...")
    try:
        with SnapshotProgress(progress.heartbeat, prefix=heading) as tracker:
            download(repo_id, tqdm_class=tracker.tqdm_class)
    except Exception as exc:
        return _warmup_failure_detail(repo_id, exc)
    return f"{repo_id} downloaded"


@server_app.command(
    "warmup",
    help=(
        "Download GPU model files before they are needed. "
        "Run once before the first index to avoid model download latency at "
        "search time."
    ),
)
def service_warmup() -> None:
    """Download GPU model files before they are needed."""
    try:
        from .._gpu import load_torch

        load_torch()
    except (ImportError, RuntimeError) as exc:
        _handle_gpu_error(exc)

    try:
        from huggingface_hub import (
            get_token,
            snapshot_download,  # pyright: ignore[reportUnknownVariableType]  # huggingface_hub stubs partially unknown
            try_to_load_from_cache,
        )
    except ImportError:
        _cli.console.print("Error: huggingface_hub is not installed.")
        raise typer.Exit(code=1) from None

    os.environ.setdefault(EnvVar.HF_HUB_DOWNLOAD_TIMEOUT, "300")

    models = configured_model_repos()

    # No ``--json`` mode on this verb, so the reporter always speaks; it is the
    # only thing an operator sees during a multi-gigabyte, effectively
    # unbounded download.
    with StartupStatusReporter(json_mode=False) as progress:
        progress.announce("Model warmup")
        token = get_token()
        if token:
            _print_detail_line("HuggingFace auth", "configured")
        else:
            _print_detail_line(
                "HuggingFace auth",
                "missing; run huggingface-cli login if downloads fail",
            )

        for position, (label, repo_id) in enumerate(models, start=1):
            progress.stage(f"Checking the cache for {label} ({position}/{len(models)})")
            if try_to_load_from_cache(repo_id, "config.json") is not None:
                _print_detail_line(label, f"{repo_id} cached")
                continue
            _print_detail_line(
                label,
                _warmup_fetch_model(
                    # The hub ships partial stubs, so the imported symbol is
                    # only partially typed; naming the shape this call site
                    # actually uses is what keeps the strict gate honest.
                    cast("Callable[..., object]", snapshot_download),
                    progress,
                    repo_id=repo_id,
                    label=label,
                    position=position,
                    total=len(models),
                ),
            )
