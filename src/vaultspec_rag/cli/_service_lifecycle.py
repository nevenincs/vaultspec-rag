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

import typer

import vaultspec_rag.cli as _cli

from ..config import EnvVar, get_config
from ._app import server_app
from ._gpu_errors import _handle_gpu_error

__all__ = [
    "_address_line",
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
    _cli.console.print(title, markup=False, highlight=False)
    for line in lines:
        _cli.console.print(line, markup=False, highlight=False, soft_wrap=True)


def _print_lifecycle_next_actions(*commands: str) -> None:
    _cli.console.print("Next actions:", markup=False, highlight=False)
    for command in commands:
        _cli.console.print(f"  {command}", markup=False, highlight=False)


def _process_line(pid: object) -> str:
    return f"Process ID: {pid}"


def _address_line(port: object) -> str:
    return f"Address: http://127.0.0.1:{port}"


def _print_detail_line(label: str, value: object) -> None:
    _cli.console.print(f"{label}: {value}", markup=False, highlight=False)


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


@server_app.command(
    "warmup",
    help=(
        "Download GPU model files before they are needed. "
        "Run once before the first index to avoid model download latency at "
        "search time. "
        "See the indexing architecture guide: docs/indexing.md"
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

    _cli.console.print("Model warmup")
    token = get_token()
    if token:
        _print_detail_line("HuggingFace auth", "configured")
    else:
        _print_detail_line(
            "HuggingFace auth",
            "missing; run huggingface-cli login if downloads fail",
        )

    for label, repo_id in models:
        # Check if already cached
        cached = try_to_load_from_cache(repo_id, "config.json")
        if cached is not None:
            _print_detail_line(label, f"{repo_id} cached")
            continue

        try:
            with _cli.console.status(f"Downloading {label}..."):
                snapshot_download(repo_id)
            _print_detail_line(label, f"{repo_id} downloaded")
        except Exception as exc:
            msg = str(exc)
            if "401" in msg or "403" in msg or "GatedRepo" in msg:
                _print_detail_line(
                    label,
                    f"{repo_id} auth required; run huggingface-cli login",
                )
            else:
                _print_detail_line(
                    label,
                    f"{repo_id} failed: {exc}"
                    " (partial cache may remain in ~/.cache/huggingface)",
                )


# Facade: import the split command modules so their ``server_app`` commands
# register on import, and re-export every name that tests and ``cli.__init__``
# continue to import from ``cli._service_lifecycle``. These imports sit below
# the primitives above so the leaf modules can import those primitives from
# here without an unresolved-name cycle.
from ._service_start import (  # noqa: E402
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
