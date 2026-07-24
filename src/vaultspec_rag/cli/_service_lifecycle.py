"""``server`` lifecycle: shared primitives, ``warmup``, and the command facade.

Holds the console primitives and the discovery-file decision helper shared by
the start, stop, and status renderers, plus the ``warmup`` command. The start,
stop, and status paths live in ``_service_start``, ``_service_stop``, and
``_status_render``; this module imports them at the bottom so their
``server_app`` commands register and re-exports the names that tests and
``cli.__init__`` continue to import from ``cli._service_lifecycle``.

The primitives are defined before the facade imports so the intentional cycle
resolves: the leaf modules import these primitives from here while this module
imports the leaf commands from them.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

import typer

import vaultspec_rag.cli as _cli

from ..config import EnvVar, get_config
from ._app import server_app
from ._gpu_errors import _handle_gpu_error
from ._progress import StartupStatusReporter
from ._render import _plain

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "_address_line",
    "_caller_ephemeral_warning",
    "_compute_state",
    "_ephemeral_env_warning",
    "_evaluate_service_signals",
    "_existing_service_running",
    "_explicit_port_state",
    "_fail_start",
    "_fail_stop",
    "_initiator_fields",
    "_print_detail_line",
    "_print_lifecycle_lines",
    "_print_lifecycle_next_actions",
    "_process_line",
    "_reclaim_machine_singleton",
    "_service_pid_on_port",
    "_should_unlink_discovery_file",
    "_start_success",
    "_status_busy_label",
    "_status_env_label",
    "_status_jobs_label",
    "_status_next_action",
    "_status_queue_label",
    "_stop_service_on_port",
    "_stop_success",
    "_tail_daemon_log",
    "_terminate_and_confirm",
    "service_start",
    "service_status",
    "service_stop",
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


def _process_line(pid: object) -> str:
    return f"Process ID: {pid}"


def _address_line(port: object) -> str:
    return f"Address: http://127.0.0.1:{port}"


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
    """Explain a failed model fetch as an operator-actionable line."""
    msg = str(exc)
    if "401" in msg or "403" in msg or "GatedRepo" in msg:
        return f"{repo_id} auth required; run huggingface-cli login"
    return f"{repo_id} failed: {exc} (partial cache may remain in ~/.cache/huggingface)"


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

    cfg = get_config()
    models = [
        ("Dense (Qwen3)", cfg.embedding_model),
        ("Sparse (SPLADE)", cfg.sparse_model),
        ("Reranker (CrossEncoder)", cfg.reranker_model),
    ]

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


# Facade: import the split command modules so their ``server_app`` commands
# register on import, and re-export every name that tests and ``cli.__init__``
# continue to import from ``cli._service_lifecycle``. These imports sit below
# the primitives above so the leaf modules can import those primitives from
# here without an unresolved-name cycle.
from ._service_start import (  # noqa: E402
    _caller_ephemeral_warning,
    _ephemeral_env_warning,
    _existing_service_running,
    _fail_start,
    _start_success,
    _tail_daemon_log,
    service_start,
)
from ._service_stop import (  # noqa: E402
    _fail_stop,
    _initiator_fields,
    _reclaim_machine_singleton,
    _service_pid_on_port,
    _stop_service_on_port,
    _stop_success,
    _terminate_and_confirm,
    service_stop,
)
from ._status_render import (  # noqa: E402
    _compute_state,
    _evaluate_service_signals,
    _explicit_port_state,
    _status_busy_label,
    _status_env_label,
    _status_jobs_label,
    _status_next_action,
    _status_queue_label,
    service_status,
)
