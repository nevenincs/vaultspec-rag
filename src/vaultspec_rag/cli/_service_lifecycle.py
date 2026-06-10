"""``server`` lifecycle commands: start, stop, status, warmup."""

from __future__ import annotations

import os
import sys
import time
from typing import Annotated, Any, cast

import typer
from rich.panel import Panel
from rich.table import Table

import vaultspec_rag.cli as _cli

from ..config import EnvVar, get_config
from ._app import server_app
from ._gpu_errors import _handle_gpu_error
from ._process import (
    _HEARTBEAT_STALENESS_SECONDS,
    _health_probe,
    _heartbeat_age_seconds,
    _port_is_available,
    _port_is_listening,
    _spawn_service,
)
from ._render import _add_backend_contract_rows, _emit_json
from ._service_status import (
    _log_file,
    _read_service_status,
    _status_file,
    _update_service_token,
    _write_service_status,
)


@server_app.command(
    "start",
    help=(
        "Start the background RAG service as a detached process. "
        "Polls /health until ready and writes a status record to "
        "~/.vaultspec-rag/service.json."
    ),
)
def service_start(
    port: Annotated[
        int,
        typer.Option(
            "--port",
            help="TCP port for the HTTP service.",
            envvar=EnvVar.PORT,
        ),
    ] = 8766,
    watch: Annotated[
        bool | None,
        typer.Option(
            "--watch/--no-watch",
            help="Enable or disable filesystem auto-reindex (default: enabled). "
            "Unset leaves VAULTSPEC_RAG_WATCH_ENABLED untouched.",
        ),
    ] = None,
    watch_debounce_ms: Annotated[
        int | None,
        typer.Option(
            "--watch-debounce-ms",
            help="Watcher debounce window in milliseconds (default 2000).",
        ),
    ] = None,
    watch_cooldown_s: Annotated[
        float | None,
        typer.Option(
            "--watch-cooldown-s",
            help="Per-source re-index cooldown in seconds (default 30).",
        ),
    ] = None,
) -> None:
    """Start the background RAG service as a detached process."""
    # Port-level guard: prevents concurrent start races (ADR D1)
    if not _port_is_available(port):
        _cli.console.print(
            Panel(
                f"Port {port} is already in use.",
                title="Service Start",
                border_style="yellow",
            ),
        )
        raise typer.Exit(code=1)

    # Check for existing service
    status = _read_service_status()
    if status is not None:
        existing_pid = int(status["pid"])
        existing_port = int(status["port"])
        existing_token = status.get("service_token")
        existing_token_str = existing_token if isinstance(existing_token, str) else None
        if _cli._is_our_service(
            existing_pid,
            port=existing_port,
            expected_token=existing_token_str,
        ):
            health = _health_probe(existing_port)
            if health is not None:
                _cli.console.print(
                    Panel(
                        f"Service already running (PID {existing_pid}, "
                        f"port {existing_port}).",
                        title="Service Start",
                        border_style="yellow",
                    ),
                )
                return
        # Stale PID -- remove status file
        _status_file().unlink(missing_ok=True)

    log_path = _log_file()
    t0 = time.perf_counter()
    pid = _spawn_service(
        port,
        log_path,
        watch=watch,
        watch_debounce_ms=watch_debounce_ms,
        watch_cooldown_s=watch_cooldown_s,
    )
    _write_service_status(pid, port)

    # Poll health with exponential backoff
    delay = 0.1
    deadline = 30.0
    elapsed = 0.0
    with _cli.console.status("[bold green]Starting service..."):
        while elapsed < deadline:
            time.sleep(delay)
            elapsed = time.perf_counter() - t0

            # Check if process died (port conflict, etc.)
            if not _cli._is_pid_alive(pid):
                _status_file().unlink(missing_ok=True)
                _cli.console.print(
                    Panel(
                        f"Service process exited immediately (PID {pid}).\n"
                        f"Port {port} may be in use. Check {log_path}",
                        title="Service Start Failed",
                        border_style="red",
                    ),
                )
                raise typer.Exit(code=1)

            health = _health_probe(port)
            if health is not None and health.get("status") == "ready":
                # Persist the token from /health into service.json so
                # auto-delegation auth works before the first heartbeat
                # tick overwrites the file (S10 / #181 A5).
                token_from_health = health.get("service_token")
                if isinstance(token_from_health, str) and token_from_health:
                    _update_service_token(token_from_health)
                startup_s = time.perf_counter() - t0
                _cli.console.print(
                    Panel(
                        f"PID: {pid}\n"
                        f"Port: {port}\n"
                        f"Startup: {startup_s:.1f}s\n"
                        f"Log: {log_path}",
                        title="Service Started",
                        border_style="green",
                    ),
                )
                return

            delay = min(delay * 2, 5.0)

    _cli.console.print(
        Panel(
            f"Timed out waiting for service health after {deadline:.0f}s.\n"
            f"PID {pid} is running but not ready. Check {log_path}",
            title="Service Start Timeout",
            border_style="red",
        ),
    )
    raise typer.Exit(code=1)


@server_app.command("stop")
def service_stop() -> None:
    """Stop the background RAG service.

    Reads the status file from ``~/.vaultspec-rag/service.json``, verifies
    the PID is still alive and belongs to a vaultspec-rag process, sends
    a graceful termination signal (SIGTERM on Unix, CTRL_BREAK_EVENT on
    Windows), waits briefly for graceful shutdown, and removes the status file.
    Force-kills (SIGKILL/TerminateProcess) if graceful shutdown fails.
    """
    status = _read_service_status()
    if status is None:
        # No service.json => nothing to stop for this config. We do NOT probe
        # the port: on the shared default port another project's healthy
        # service would otherwise be misreported as this config's orphan.
        _cli.console.print(
            Panel(
                "No service status file found. Service is not running.",
                title="Service Stop",
                border_style="yellow",
            ),
        )
        return

    pid = int(status["pid"])
    port = int(status["port"])
    raw_token = status.get("service_token")
    expected_token = raw_token if isinstance(raw_token, str) else None
    if not _cli._is_our_service(pid, port=port, expected_token=expected_token):
        _status_file().unlink(missing_ok=True)
        _cli.console.print(
            Panel(
                f"Service PID {pid} is no longer running. Cleaned up status file.",
                title="Service Stop",
                border_style="yellow",
            ),
        )
        return

    _cli._terminate_pid(pid)

    # Wait briefly for process to exit
    for _ in range(50):
        if not _cli._is_pid_alive(pid):
            break
        time.sleep(0.1)

    _status_file().unlink(missing_ok=True)
    if sys.platform == "win32":
        # On Windows, os.kill(SIGTERM) is TerminateProcess so the
        # daemon's atexit handler and lifespan ``finally`` never
        # fire. POSIX flows through uvicorn's signal handler →
        # lifespan finally → ``_record_shutdown("clean")`` which
        # emits ``service.lifecycle event=shutdown reason=clean``.
        # The CLI parent emits a mirror line here so Windows
        # operators get the same audit trail.
        _cli._append_lifecycle_shutdown_log(
            "cli_terminate",
            pid=pid,
            platform="win32",
        )
    _cli.console.print(
        Panel(
            f"Service stopped (PID {pid}).",
            title="Service Stop",
            border_style="green",
        ),
    )


def _compute_token_match(
    expected_token: str | None,
    pid_alive: bool,
    port_listening: bool,
    port: int,
) -> bool | None:
    if expected_token is None or not pid_alive:
        return None
    probe_for_token = _health_probe(port) if port_listening else None
    if probe_for_token is not None and isinstance(
        probe_for_token.get("service_token"),
        str,
    ):
        response_token = probe_for_token["service_token"]
        return bool(response_token) and response_token == expected_token
    return None


def _compute_state(
    pid_alive: bool,
    pid_is_ours: bool,
    port_listening: bool,
    heartbeat_stale: bool,
) -> tuple[str, str, int]:
    if not pid_alive:
        _status_file().unlink(missing_ok=True)
        return (
            "crashed_pid_dead",
            "[red]crashed (PID dead, stale service.json cleaned)[/]",
            4,
        )
    if not pid_is_ours:
        return (
            "crashed_pid_reused",
            "[red]crashed (PID reused by unrelated process)[/]",
            4,
        )
    if not port_listening:
        return "crashed_port_silent", "[red]crashed (port silent)[/]", 4
    if heartbeat_stale:
        return "crashed_heartbeat_stale", "[red]crashed (heartbeat stale)[/]", 4
    return "running", "[green]running[/]", 0


def _evaluate_service_signals(
    status: dict[str, Any],
) -> tuple[
    int, int, str, bool, bool, bool, float | None, bool, bool | None, str, str, int
]:
    pid = int(status.get("pid", 0))
    port = int(status.get("port", 0))
    started_at = str(status.get("started_at", "unknown"))

    raw_token = status.get("service_token")
    expected_token = raw_token if isinstance(raw_token, str) and raw_token else None
    pid_alive = _cli._is_pid_alive(pid)
    pid_is_ours = (
        _cli._is_our_service(pid, port=port, expected_token=expected_token)
        if pid_alive
        else False
    )
    port_listening = _port_is_listening(port) if pid_alive else False
    heartbeat_age = _heartbeat_age_seconds(status)
    heartbeat_stale = (
        pid_alive
        if heartbeat_age is None
        else heartbeat_age > _HEARTBEAT_STALENESS_SECONDS
    )

    token_match = _compute_token_match(expected_token, pid_alive, port_listening, port)
    state, state_label, exit_code = _compute_state(
        pid_alive, pid_is_ours, port_listening, heartbeat_stale
    )

    return (
        pid,
        port,
        started_at,
        pid_alive,
        pid_is_ours,
        port_listening,
        heartbeat_age,
        heartbeat_stale,
        token_match,
        state,
        state_label,
        exit_code,
    )


def _render_status_json(
    pid: int,
    port: int,
    started_at: str,
    pid_alive: bool,
    pid_is_ours: bool,
    port_listening: bool,
    heartbeat_age: float | None,
    heartbeat_stale: bool,
    token_match: bool | None,
    state: str,
    exit_code: int,
    health: dict[str, object] | None,
) -> None:
    payload: dict[str, object] = {
        "service_json_present": True,
        "pid": pid,
        "port": port,
        "started_at": started_at,
        "pid_alive": pid_alive,
        "pid_matches_service": pid_is_ours,
        "port_listening": port_listening,
        "heartbeat_age_seconds": heartbeat_age,
        "heartbeat_stale": heartbeat_stale,
        "service_token_match": token_match,
        "state": state,
    }
    if isinstance(health, dict):
        payload["health"] = health
    _emit_json(
        exit_code == 0,
        "service.status",
        data=payload,
        **(
            {"error": state, "message": f"Service state: {state}"}
            if exit_code != 0
            else {}
        ),
    )
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _get_token_label(token_match: bool | None) -> str:
    if token_match is None:
        return "[yellow]n/a[/]"
    if token_match:
        return "[green]yes[/]"
    return "[red]no[/]"


def _add_health_rows(
    table: Table, health: dict[str, object] | None, port_listening: bool
) -> None:
    if isinstance(health, dict):
        table.add_row("Health", str(health.get("status", "unknown")))
        table.add_row("CUDA", str(health.get("cuda", "unknown")))
        table.add_row("Models loaded", str(health.get("models_loaded", "unknown")))
        table.add_row("Projects", str(health.get("project_count", "unknown")))
        uptime = health.get("uptime_s", 0.0)
        table.add_row("Uptime", f"{float(cast('float', uptime)):.0f}s")
        caps = health.get("backend_capabilities")
        if isinstance(caps, dict):
            _add_backend_contract_rows(table, cast("dict[str, object]", caps))
    elif port_listening:
        table.add_row("Health", "[yellow]unreachable[/]")


def _render_status_table(
    pid: int,
    port: int,
    started_at: str,
    pid_alive: bool,
    pid_is_ours: bool,
    port_listening: bool,
    heartbeat_age: float | None,
    heartbeat_stale: bool,
    token_match: bool | None,
    state_label: str,
    exit_code: int,
    health: dict[str, object] | None,
) -> None:
    table = Table(title="Service Status", show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Service JSON", "[green]present[/]")
    table.add_row("PID", str(pid))
    table.add_row("Port", str(port))
    table.add_row("Started", started_at)
    table.add_row(
        "PID Alive",
        "[green]yes[/]" if pid_alive else "[red]no[/]",
    )
    table.add_row(
        "PID Matches Service",
        "[green]yes[/]" if pid_is_ours else "[red]no[/]" if pid_alive else "n/a",
    )
    table.add_row("Service Token Match", _get_token_label(token_match))
    table.add_row(
        "Port Listening",
        "[green]yes[/]" if port_listening else "[red]no[/]" if pid_alive else "n/a",
    )
    if heartbeat_age is None:
        table.add_row("Heartbeat", "[yellow]absent[/]")
    else:
        colour = "red" if heartbeat_stale else "green"
        table.add_row(
            "Heartbeat",
            f"[{colour}]{heartbeat_age:.0f}s ago[/]",
        )
    table.add_row("State", state_label)

    _add_health_rows(table, health, port_listening)

    _cli.console.print(table)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


@server_app.command("status")
def service_status(
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit one JSON envelope to stdout instead of a Rich "
                "table. Preserves exit codes 0 (running) / 3 (stopped) "
                "/ 4 (crashed-* or divergent)."
            ),
        ),
    ] = False,
) -> None:
    """Display the current status of the background RAG service.

    Gathers four signals before rendering - ``service.json`` present,
    PID alive, port listening, heartbeat fresh - and surfaces each as
    its own row plus a derived ``State`` row. Avoids the previous
    "pick one source of truth" behaviour where conflicting signals
    rendered as a misleading verdict.

    Exit codes:
      - 0: ``running`` (all signals green).
      - 3: ``stopped`` (no ``service.json``).
      - 4: ``divergent`` or ``crashed-*`` (file present but at least
        one signal contradicts the others). Lets scripts branch on
        "known-bad state" without parsing the prose.
    """
    status = _read_service_status()

    if status is None:
        # No service.json in the configured status dir => this config's
        # service is stopped (exit 3), per the documented contract (exit 4
        # is reserved for a *present* service.json that diverges). We do
        # NOT probe the port here: on the shared default port another
        # project's healthy service would otherwise be misreported as this
        # config's orphan/divergent state (a multi-project false positive).
        # `server start` keeps its own port guard against double-starts.
        if json_mode:
            _emit_json(
                False,
                "service.status",
                error="stopped",
                message="No service.json - service is not running.",
                data={"service_json_present": False, "state": "stopped"},
            )
            raise typer.Exit(code=3)
        table = Table(title="Service Status", show_header=False, padding=(0, 2))
        table.add_column("Key", style="bold")
        table.add_column("Value")
        table.add_row("Service JSON", "[red]missing[/]")
        table.add_row("State", "[red]stopped[/]")
        _cli.console.print(table)
        raise typer.Exit(code=3)

    (
        pid,
        port,
        started_at,
        pid_alive,
        pid_is_ours,
        port_listening,
        heartbeat_age,
        heartbeat_stale,
        token_match,
        state,
        state_label,
        exit_code,
    ) = _evaluate_service_signals(status)

    health = _health_probe(port) if port_listening else None

    if json_mode:
        _render_status_json(
            pid,
            port,
            started_at,
            pid_alive,
            pid_is_ours,
            port_listening,
            heartbeat_age,
            heartbeat_stale,
            token_match,
            state,
            exit_code,
            health,
        )
        return

    _render_status_table(
        pid,
        port,
        started_at,
        pid_alive,
        pid_is_ours,
        port_listening,
        heartbeat_age,
        heartbeat_stale,
        token_match,
        state_label,
        exit_code,
        health,
    )


@server_app.command(
    "warmup",
    help=(
        "Pre-download GPU model files to the HuggingFace cache. "
        "Run once before the first index to avoid model-download latency at "
        "search time. "
        "See the indexing architecture guide: docs/indexing.md"
    ),
)
def service_warmup() -> None:
    """Pre-download GPU model files to the HuggingFace cache."""
    try:
        import torch
    except ImportError:
        _cli.console.print("[bold red]Error:[/] torch is not installed.")
        raise typer.Exit(code=1) from None

    if not torch.cuda.is_available():
        _handle_gpu_error(RuntimeError("CUDA runtime unavailable"))

    try:
        from huggingface_hub import (
            get_token,
            snapshot_download,  # pyright: ignore[reportUnknownVariableType]  # huggingface_hub stubs partially unknown
            try_to_load_from_cache,
        )
    except ImportError:
        _cli.console.print("[bold red]Error:[/] huggingface_hub is not installed.")
        raise typer.Exit(code=1) from None

    os.environ.setdefault(EnvVar.HF_HUB_DOWNLOAD_TIMEOUT, "300")

    cfg = get_config()
    models = [
        ("Dense (Qwen3)", cfg.embedding_model),
        ("Sparse (SPLADE)", cfg.sparse_model),
        ("Reranker (CrossEncoder)", cfg.reranker_model),
    ]

    table = Table(title="Model Warmup", show_header=True)
    table.add_column("Model", style="bold")
    table.add_column("Repo", style="cyan")
    table.add_column("Status")

    token = get_token()
    if token:
        table.add_row("HuggingFace auth", "token", "[green]configured[/]")
    else:
        table.add_row(
            "HuggingFace auth",
            "token",
            "[yellow]missing[/]: run huggingface-cli login if downloads fail",
        )

    for label, repo_id in models:
        # Check if already cached
        cached = try_to_load_from_cache(repo_id, "config.json")
        if cached is not None:
            table.add_row(label, repo_id, "[green]cached[/]")
            continue

        try:
            with _cli.console.status(f"[bold green]Downloading {label}..."):
                snapshot_download(repo_id)
            table.add_row(label, repo_id, "[green]downloaded[/]")
        except Exception as exc:
            msg = str(exc)
            if "401" in msg or "403" in msg or "GatedRepo" in msg:
                table.add_row(
                    label,
                    repo_id,
                    "[red]auth required[/]: run huggingface-cli login",
                )
            else:
                table.add_row(
                    label,
                    repo_id,
                    f"[red]failed[/]: {exc}"
                    " (partial cache may remain in ~/.cache/huggingface)",
                )

    _cli.console.print(table)
