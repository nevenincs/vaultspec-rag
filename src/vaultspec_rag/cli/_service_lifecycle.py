"""``server`` lifecycle commands: start, stop, status, warmup."""

from __future__ import annotations

import contextlib
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import typer

import vaultspec_rag.cli as _cli

from ..config import EnvVar, get_config
from ._app import _global_target, server_app
from ._core import logger
from ._gpu_errors import _handle_gpu_error
from ._http_search import _try_http_admin
from ._process import (
    _HEARTBEAT_STALENESS_SECONDS,
    DaemonBreakawayError,
    _health_probe,
    _heartbeat_age_seconds,
    _port_is_available,
    _port_is_listening,
    _probe_daemon_cuda,
    _resolve_daemon_interpreter,
    _spawn_service,
)
from ._render import _emit_json
from ._service_jobs import (
    _human_progress,
    _operation_label,
    _project_label,
    _stale_progress_label,
)
from ._service_status import (
    _default_service_port,
    _log_file,
    _read_service_status,
    _status_file,
    _update_service_metadata,
    _update_service_token,
    _write_service_status,
)

__all__ = [
    "_evaluate_service_signals",
    "_existing_service_running",
    "_should_unlink_discovery_file",
    "_status_busy_label",
    "_status_jobs_label",
    "_status_queue_label",
    "service_start",
    "service_status",
    "service_stop",
    "service_warmup",
]


def _ensure_qdrant_binary(*, auto_provision: bool, json_mode: bool = False) -> None:
    """Fail fast (or provision with consent) before a server-mode start.

    Server mode is the default backend, so this guard runs by default and
    only ``--local-only`` (or an explicit ``--no-qdrant``) skips it. Never
    downloads silently: an absent executable without ``auto_provision`` prints
    the exact install command and exits non-zero. In ``--json`` mode the absent/
    failed outcomes are emitted as start envelopes so a broker reads one document.
    """
    from ..qdrant_runtime import QdrantProvisionAction, provision, resolve_binary

    if resolve_binary() is not None:
        return
    if not auto_provision:
        raise _fail_start(
            json_mode,
            error="qdrant_missing",
            message="Service start failed",
            human_lines=(
                "Qdrant server mode needs the managed Qdrant server, "
                "which is not installed.",
                "Run: vaultspec-rag server qdrant install",
                "(or re-run with --qdrant-auto-provision to consent to the download)",
                "Local-only option: vaultspec-rag server start --local-only",
            ),
        )
    report = provision()
    if report.action == QdrantProvisionAction.FAILED or resolve_binary() is None:
        raise _fail_start(
            json_mode,
            error="qdrant_provision_failed",
            message="Service start failed",
            human_lines=(f"Qdrant install failed: {report.message}",),
            detail=str(report.message),
        )
    if not json_mode:
        _print_lifecycle_lines(
            "Installed Qdrant server",
            f"Version: {report.version}",
            f"Install: {report.binary}",
        )


def _health_service_pid(health: dict[str, object], fallback_pid: int) -> int:
    serving_pid = health.get("pid")
    if isinstance(serving_pid, int) and serving_pid > 0:
        return serving_pid
    return fallback_pid


def _status_metadata_from_health(
    health: dict[str, object],
    *,
    pid: int,
) -> dict[str, object]:
    return {
        "pid": pid,
        "parent_pid": health.get("parent_pid"),
        "executable": health.get("executable"),
        "prefix": health.get("prefix"),
        "base_prefix": health.get("base_prefix"),
        "virtual_env": health.get("virtual_env"),
    }


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


def _tail_daemon_log(log_path: Path, max_lines: int = 6) -> list[str]:
    """Return the last few non-empty lines of the daemon log, best-effort.

    Surfaces why a detached daemon died during startup (e.g. the model-load
    RuntimeError or a qdrant failure) instead of only pointing at the log file.
    Bounded tail read; any IO failure yields an empty list and the caller still
    prints the log path.
    """
    try:
        with log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 8192))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = [ln.rstrip() for ln in tail.splitlines() if ln.strip()]
    return lines[-max_lines:]


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


def _existing_service_running() -> tuple[int, int] | None:
    """Return the ``(pid, port)`` of a healthy owned running service, else ``None``.

    Detection only - it no longer prints, so the caller renders the human
    "already running" lines or the JSON envelope from one shared detection path
    (the idempotent-start contract). Removes the status file only when its
    recorded PID is confirmed dead; an ambiguous identity/health miss on a *live*
    PID leaves the file untouched so a transient probe failure cannot erase a
    running daemon's discovery file (issue #204).
    """
    status = _read_service_status()
    if status is None:
        return None
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
            return (existing_pid, existing_port)
    # Identity or health did not confirm a live service we own. Remove the
    # status file only when the recorded PID is confirmed dead; leave it in
    # place on an ambiguous miss against a live PID (issue #204).
    if _should_unlink_discovery_file(_cli._is_pid_alive(existing_pid)):
        _status_file().unlink(missing_ok=True)
    return None


_START_COMMAND = "service.start"


def _start_success(
    json_mode: bool,
    *,
    status: str,
    human_title: str,
    human_lines: tuple[str, ...],
    **data: object,
) -> None:
    """Emit a successful start outcome (``already_running`` / ``started``).

    In ``--json`` mode emits one ``{ok, command, data:{status, ...}}`` envelope;
    otherwise the bespoke human lines. The caller returns after this (exit 0).
    """
    if json_mode:
        _emit_json(True, _START_COMMAND, data={"status": status, **data})
    else:
        _print_lifecycle_lines(human_title, *human_lines)


def _fail_start(
    json_mode: bool,
    *,
    error: str,
    message: str,
    human_lines: tuple[str, ...],
    next_actions: tuple[str, ...] = (),
    **data: object,
) -> typer.Exit:
    """Render a failed start outcome and RETURN the ``typer.Exit`` to raise.

    In ``--json`` mode emits one ``ok:false`` error envelope (``error`` is the
    machine status, ``data`` the structured fields); otherwise the bespoke human
    lines and next actions. Returns the ``Exit`` so the call site keeps an
    explicit ``raise`` for control-flow clarity.
    """
    if json_mode:
        _emit_json(
            False,
            _START_COMMAND,
            error=error,
            message=message,
            data=dict(data) or None,
        )
    else:
        _print_lifecycle_lines(message, *human_lines)
        if next_actions:
            _print_lifecycle_next_actions(*next_actions)
    return typer.Exit(code=1)


def _preflight_daemon_cuda(interpreter: str, *, json_mode: bool) -> None:
    """Fail fast if the daemon interpreter cannot run the GPU-only service.

    The daemon inherits this interpreter and is GPU-only, so a missing /
    CPU-only / no-GPU torch should fail legibly here rather than as a background
    model-load crash. The service does not provision its own python environment.
    An inconclusive probe (CPU-only host, torch absent in a way we cannot
    classify) is logged and allowed to proceed.
    """
    cuda_probe = _probe_daemon_cuda(interpreter)
    if cuda_probe is None:
        return
    blocking, reason = cuda_probe
    if blocking:
        raise _fail_start(
            json_mode,
            error="service_env_no_gpu",
            message="Service start failed",
            human_lines=(
                f"Service interpreter: {interpreter}",
                f"That environment cannot run the GPU-only service: {reason}.",
                "The service runs in the environment that launches it and does "
                "not provision its own python.",
                "Provision GPU (cu130) torch into that environment, then retry.",
            ),
            next_actions=(
                "Install/repair GPU torch in the service environment: "
                "vaultspec-rag install, then uv sync",
                "Confirm the GPU is visible: nvidia-smi",
            ),
            detail=reason,
        )
    logger.warning(
        "daemon torch pre-flight inconclusive for %s (%s); proceeding",
        interpreter,
        reason,
    )


def _print_preprocess_start_notice(root: Path, effective_mode: str) -> None:
    """Print a best-effort notice about the target root's preprocess rules.

    Operator visibility: when the resolved root defines preprocess rules, say
    whether they will run under the effective mode. Rules run directly for any
    root; the ``off`` kill switch skips them. Never raises - a missing or
    invalid config simply yields no notice. Imports are function-local so this
    stays off the module import path (the CLI service-control surface stays
    torch-free).
    """
    from ..indexer._preprocess_config import (
        PREPROCESS_CONFIG_FILENAME,
        PreprocessConfigError,
        load_preprocess_rules,
    )

    if not (root / PREPROCESS_CONFIG_FILENAME).is_file():
        return
    try:
        config = load_preprocess_rules(root, strict=True)
    except PreprocessConfigError:
        return
    rules = config.rules
    if not rules:
        return
    count = len(rules)
    word = "rule" if count == 1 else "rules"
    if effective_mode == "off":
        _print_lifecycle_lines(
            f"Preprocess: {count} {word} at {root} will be skipped (mode is off)."
        )
        return
    _print_lifecycle_lines(
        f"Preprocess: {count} {word} at {root} will run; their commands "
        "execute with the service's privileges."
    )


def _guard_start_preconditions(port: int, json_mode: bool) -> None:
    """Fail fast on a taken port or an owned machine, one envelope each.

    Port-level guard: prevents concurrent start races. A foreign process
    holding the port (NOT our service, which the caller's idempotent check
    already handled) is a genuine failure. Machine-level guard: one resident
    service per machine - it owns the single GPU and the single managed
    Qdrant; a live holder on ANY port or status dir refuses a second daemon,
    while a stale lock from a dead holder is reclaimed by the daemon's own
    acquire. The machine check catches a second instance that a port-scoped
    check (different --port / status dir) misses.
    """
    if not _port_is_available(port):
        raise _fail_start(
            json_mode,
            error="port_in_use",
            message="Service start failed",
            human_lines=(
                f"Port {port} is already in use.",
                "Another process is already using this service address.",
            ),
            next_actions=(
                f"vaultspec-rag server status --port {port}",
                f"vaultspec-rag server jobs --state active --port {port}",
                "vaultspec-rag server start --port <free-port>",
            ),
            port=port,
        )

    from .._machine_lock import machine_lock_live_holder

    machine_holder = machine_lock_live_holder()
    if machine_holder:
        raise _fail_start(
            json_mode,
            error="machine_owned",
            message="Service start failed",
            human_lines=(
                f"A vaultspec-rag service already owns this machine "
                f"(pid {machine_holder}).",
                "One service owns the machine's GPU and managed Qdrant; a second "
                "resident service is not supported.",
            ),
            next_actions=(
                "vaultspec-rag server status",
                "vaultspec-rag server stop",
            ),
            holder_pid=machine_holder,
        )


@server_app.command(
    "start",
    help=(
        "Start the background search service. Defaults to the managed Qdrant "
        "server backend (server mode); pass --local-only for the on-disk store. "
        "Waits until it is ready and records how the CLI can reach it."
    ),
)
def service_start(
    ctx: typer.Context,
    port: Annotated[
        int,
        typer.Option(
            "--port",
            help="Port for the background search service.",
            envvar=EnvVar.PORT,
        ),
    ] = 8766,
    updates: Annotated[
        bool | None,
        typer.Option(
            "--updates/--no-updates",
            help=(
                "Enable or disable automatic index updates when files change "
                "(default: enabled)."
            ),
        ),
    ] = None,
    update_delay_ms: Annotated[
        int | None,
        typer.Option(
            "--update-delay-ms",
            help="Delay before indexing a burst of file changes, in milliseconds.",
        ),
    ] = None,
    repeat_update_delay_s: Annotated[
        float | None,
        typer.Option(
            "--repeat-update-delay-s",
            help=(
                "Minimum wait before automatically updating a project again, "
                "in seconds."
            ),
        ),
    ] = None,
    local_only: Annotated[
        bool,
        typer.Option(
            "--local-only",
            help=(
                "Use the on-disk local store instead of the default managed "
                "Qdrant server. This is the first-class opt-out for CI, "
                "offline, and small-project hosts."
            ),
        ),
    ] = False,
    qdrant: Annotated[
        bool | None,
        typer.Option(
            "--qdrant/--no-qdrant",
            help=(
                "Explicitly opt in to (or out of) the managed Qdrant server. "
                "Server mode is already the default, so --qdrant is redundant; "
                "use --local-only to select the on-disk store. Unset leaves "
                "the current Qdrant setting unchanged."
            ),
        ),
    ] = None,
    qdrant_auto_provision: Annotated[
        bool,
        typer.Option(
            "--qdrant-auto-provision",
            help=(
                "Download the managed Qdrant server if it is missing. "
                "Without this flag, start prints the install command."
            ),
        ),
    ] = False,
    no_preprocess: Annotated[
        bool,
        typer.Option(
            "--no-preprocess",
            help=(
                "Kill switch: the service loads no document-preprocessing rules "
                "for any root (forwards VAULTSPEC_RAG_PREPROCESS=off)."
            ),
        ),
    ] = False,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit one machine-readable outcome envelope instead of human "
                "text. An already-running owned service is the success "
                "`already_running` (exit 0), so a supervising broker can attach "
                "rather than treating it as a fault."
            ),
        ),
    ] = False,
) -> None:
    """Start the background search service."""
    preprocess_forward: Literal["off"] | None = "off" if no_preprocess else None
    # Idempotent check FIRST: a healthy owned service already running is a
    # SUCCESS (`already_running`, exit 0), decided before the port/machine guards
    # so the friendly path is no longer shadowed by the port-guard exit 1 - a
    # supervising broker attaches instead of seeing a gateway fault.
    existing = _existing_service_running()
    if existing is not None:
        existing_pid, existing_port = existing
        _start_success(
            json_mode,
            status="already_running",
            human_title="Service already running",
            human_lines=(_process_line(existing_pid), _address_line(existing_port)),
            pid=existing_pid,
            port=existing_port,
        )
        return

    _guard_start_preconditions(port, json_mode)

    # Server mode is the default backend, so the qdrant-binary guard runs
    # by default. --local-only (and an explicit --no-qdrant) select the
    # on-disk store and skip it, so a default start fails fast on a missing
    # binary while the local opt-out never touches the server.
    if not local_only and qdrant is not False:
        _ensure_qdrant_binary(auto_provision=qdrant_auto_provision, json_mode=json_mode)

    # Operator visibility for the target root's preprocess rules.
    # Best-effort and human-only so the --json envelope stays a single document.
    if not json_mode:
        effective_mode = preprocess_forward or get_config().preprocess_mode
        _print_preprocess_start_notice(
            _global_target(ctx) or Path.cwd(),
            effective_mode,
        )

    log_path = _log_file()
    _preflight_daemon_cuda(_resolve_daemon_interpreter(), json_mode=json_mode)
    t0 = time.perf_counter()
    try:
        pid = _spawn_service(
            port,
            log_path,
            watch=updates,
            watch_debounce_ms=update_delay_ms,
            watch_cooldown_s=repeat_update_delay_s,
            qdrant=qdrant,
            local_only=local_only,
            preprocess_mode=preprocess_forward,
        )
    except DaemonBreakawayError as exc:
        # The launching shell's Job Object denied detachment, so a daemon
        # started here would die when the shell exits (the issue #204 flapping
        # symptom). Surface the actionable guidance rather than spawning a
        # doomed daemon. No status file was written, so nothing to clean up.
        raise _fail_start(
            json_mode,
            error="daemon_breakaway",
            message="Service start failed",
            human_lines=(str(exc),),
            next_actions=(
                "Start from a plain console (cmd.exe or powershell.exe) outside a "
                "restricted terminal",
                "Or run the service under a service manager that permits breakaway",
            ),
            detail=str(exc),
        ) from exc
    _write_service_status(pid, port)
    _await_service_ready(pid, port, log_path, json_mode=json_mode, t0=t0)


def _await_service_ready(
    pid: int,
    port: int,
    log_path: Path,
    *,
    json_mode: bool,
    t0: float,
) -> None:
    """Poll the spawned daemon's health until it is ready, or fail/time out.

    Extracted from :func:`service_start` so the guard sequence and the health
    wait each read as one unit. Emits the terminal outcome itself: the success
    envelope on readiness, a typed failure if the process dies, and a timeout
    failure if it never reports ready within the deadline. Health is polled with
    exponential backoff; the live spinner is suppressed in ``--json`` mode so a
    single clean envelope reaches stdout.

    Args:
        pid: The spawned daemon process id.
        port: The port the daemon was started on.
        log_path: The daemon log file, surfaced in failure output.
        json_mode: Whether to emit a machine-readable outcome envelope.
        t0: The ``time.perf_counter`` reading taken just before the spawn, for
            the reported startup duration.
    """
    delay = 0.1
    deadline = 300.0
    elapsed = 0.0
    spinner: contextlib.AbstractContextManager[object] = (
        contextlib.nullcontext()
        if json_mode
        else _cli.console.status("Starting service...")
    )
    with spinner:
        while elapsed < deadline:
            time.sleep(delay)
            elapsed = time.perf_counter() - t0

            # Check if process died (port conflict, etc.)
            if not _cli._is_pid_alive(pid):
                _status_file().unlink(missing_ok=True)
                tail = _tail_daemon_log(log_path)
                human = [_process_line(pid), _address_line(port)]
                if tail:
                    human.append("Last log lines:")
                    human.extend(f"  {ln}" for ln in tail)
                human.append(f"Log: {log_path}")
                raise _fail_start(
                    json_mode,
                    error="start_died",
                    message="Service start failed",
                    human_lines=tuple(human),
                    pid=pid,
                    port=port,
                    log=str(log_path),
                )

            health = _health_probe(port)
            if health is not None and health.get("status") == "ready":
                # Persist the token from /health into service.json so
                # auto-delegation auth works before the first heartbeat
                # tick overwrites the file (S10 / #181 A5).
                token_from_health = health.get("service_token")
                if isinstance(token_from_health, str) and token_from_health:
                    _update_service_token(token_from_health)
                pid = _health_service_pid(health, pid)
                _update_service_metadata(_status_metadata_from_health(health, pid=pid))
                startup_s = time.perf_counter() - t0
                _start_success(
                    json_mode,
                    status="started",
                    human_title="Service started",
                    human_lines=(
                        _process_line(pid),
                        _address_line(port),
                        f"Startup: {startup_s:.1f}s",
                        f"Log: {log_path}",
                    ),
                    pid=pid,
                    port=port,
                    startup_s=round(startup_s, 1),
                    log=str(log_path),
                )
                return

            delay = min(delay * 2, 5.0)

    raise _fail_start(
        json_mode,
        error="start_timeout",
        message="Service start timed out",
        human_lines=(
            f"Waited: {deadline:.0f}s",
            _process_line(pid),
            "Server: process is running but not ready",
            f"Log: {log_path}",
        ),
        pid=pid,
        waited_s=deadline,
        log=str(log_path),
    )


def _reclaim_machine_singleton() -> int | None:
    """Reclaim a resident machine-lock holder that has no discoverable status file.

    The machine singleton lock is vaultspec-rag-exclusive and machine-scoped, so
    a live holder is THE resident service even when it never registered (or lost)
    a ``service.json`` in this status directory. Such a holder otherwise
    deadlocks the machine: ``server start`` refuses it (lock held), ``server
    stop`` reports "not running" (no discovery), and ``server status`` reports
    stopped - leaving a manual OS kill as the only escape (the very orphan the
    ``mcp-conformance`` research recorded). Terminating the confirmed holder
    makes ``server stop`` the real recovery the start refusal points to.

    Returns the reclaimed holder pid, or ``None`` when no reclaimable
    vaultspec-rag holder is found. The ``_is_our_service`` executable check
    guards against terminating an unrelated process after pid reuse.
    """
    from .._machine_lock import machine_lock_live_holder

    holder = machine_lock_live_holder()
    if (
        holder
        and holder != os.getpid()
        and _cli._is_pid_alive(holder)
        and _cli._is_our_service(holder)
    ):
        _terminate_and_confirm(holder)
        return holder
    return None


def _initiator_fields() -> dict[str, str]:
    """Return the identity of the process performing the stop, for attribution.

    Carries the terminating process' own pid, command line, and cwd so "who
    stopped the machine service" is answerable from one shutdown record rather
    than only naming the terminated pid. The command line is bounded so a long
    argv cannot bloat the audit line or the envelope. The argv is logged
    verbatim, which constrains future stop flags: none may ever carry a
    secret without revisiting this field.
    """
    cmd = " ".join(sys.argv)
    if len(cmd) > 300:
        cmd = f"{cmd[:297]}..."
    return {
        "initiator_pid": str(os.getpid()),
        "initiator_cmd": cmd,
        "initiator_cwd": os.getcwd(),
    }


def _terminate_and_confirm(pid: int) -> None:
    """Terminate *pid*, wait briefly, and emit the shutdown audit trail."""
    _cli._terminate_pid(pid)

    # Wait briefly for process to exit
    for _ in range(50):
        if not _cli._is_pid_alive(pid):
            break
        time.sleep(0.1)

    # On Windows, os.kill(SIGTERM) is TerminateProcess so the daemon's atexit
    # handler and lifespan ``finally`` never fire; the CLI parent emits this
    # mirror line so Windows operators get the audit trail. POSIX flows through
    # uvicorn's signal handler → lifespan finally → ``_record_shutdown("clean")``
    # and logs its own clean shutdown, but the CLI-side initiator attribution is
    # valuable on every platform, so the line is emitted unconditionally.
    _cli._append_lifecycle_shutdown_log(
        "cli_terminate",
        pid=pid,
        platform=sys.platform,
        **_initiator_fields(),
    )


def _service_pid_on_port(port: int) -> tuple[int, str | None] | None:
    """Resolve the live serving pid (and token) on *port* via ``/health``.

    The service domain owns identity: ``/health`` reports the serving pid and
    the per-process token, so a service on a non-default port is resolvable
    without the status file (which is keyed per status dir and may diverge from
    the running instance - research F7). Returns ``None`` when nothing healthy
    is serving the port.
    """
    if not _port_is_listening(port):
        return None
    health = _health_probe(port)
    if health is None:
        return None
    serving_pid = health.get("pid")
    if not isinstance(serving_pid, int) or serving_pid <= 0:
        return None
    raw_token = health.get("service_token")
    token = raw_token if isinstance(raw_token, str) and raw_token else None
    return serving_pid, token


_STOP_COMMAND = "service.stop"


def _stop_success(
    json_mode: bool,
    *,
    status: str,
    human_title: str,
    human_lines: tuple[str, ...] = (),
    **data: object,
) -> None:
    """Emit a successful stop outcome (``stopped`` / ``already_stopped`` / ...).

    In ``--json`` mode emits one ``{ok, command, data:{status, ...}}`` envelope;
    otherwise the bespoke human lines. The caller returns after this (exit 0).
    An already-stopped service is a success so a supervising broker treats the
    idempotent case as satisfied rather than as a fault.
    """
    if json_mode:
        _emit_json(True, _STOP_COMMAND, data={"status": status, **data})
    else:
        _print_lifecycle_lines(human_title, *human_lines)


def _fail_stop(
    json_mode: bool,
    *,
    error: str,
    message: str,
    human_lines: tuple[str, ...],
    next_actions: tuple[str, ...] = (),
    **data: object,
) -> typer.Exit:
    """Render a failed stop outcome and RETURN the ``typer.Exit`` to raise.

    A stop that leaves the service running did not do its job, so it exits 1
    in BOTH human and ``--json`` modes - a broker or script must never read a
    skipped stop as success. Mirrors ``_fail_start``.
    """
    if json_mode:
        _emit_json(
            False,
            _STOP_COMMAND,
            error=error,
            message=message,
            data=dict(data) or None,
        )
    else:
        _print_lifecycle_lines(message, *human_lines)
        if next_actions:
            _print_lifecycle_next_actions(*next_actions)
    return typer.Exit(code=1)


def _stop_service_on_port(port: int, json_mode: bool = False) -> None:
    """Stop the service answering on *port*, status-file independent.

    Targets the running instance the operator named with ``--port`` even when
    the status file is missing or records a divergent port (research F7). The
    discovery file is only removed when it actually points at this port, so
    stopping one config's service never erases another's discovery file.
    """
    resolved = _service_pid_on_port(port)
    if resolved is None:
        _stop_success(
            json_mode,
            status="already_stopped",
            human_title="Service is not running.",
            human_lines=(f"No service is answering on http://127.0.0.1:{port}.",),
            port=port,
        )
        return
    pid, token = resolved
    if not _cli._is_our_service(pid, port=port, expected_token=token):
        raise _fail_stop(
            json_mode,
            error="identity_unconfirmed",
            message="Service stop skipped",
            human_lines=(
                f"A process is answering on port {port} but its identity could "
                "not be confirmed as a vaultspec-rag service; it was left "
                "running.",
            ),
            next_actions=(f"vaultspec-rag server status --port {port} --verbose",),
            pid=pid,
            port=port,
        )

    _terminate_and_confirm(pid)

    # Remove the discovery file only when it points at the port we just stopped,
    # so stopping a non-default-port service never erases a different config's
    # status file.
    status = _read_service_status()
    if status is not None and int(status.get("port", 0)) == port:
        _status_file().unlink(missing_ok=True)
    _stop_success(
        json_mode,
        status="stopped",
        human_title="Service stopped",
        human_lines=(_process_line(pid),),
        pid=pid,
        port=port,
        **_initiator_fields(),
    )


@server_app.command("stop", help="Stop the background search service.")
def service_stop(
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            help=(
                "Stop the service answering on this port, resolving its identity "
                "from /health rather than the status file. Use when the service "
                "runs on a non-default port or the status file diverges from the "
                "running instance."
            ),
        ),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit one machine-readable outcome envelope instead of human "
                "text. An already-stopped service is the success "
                "`already_stopped` (exit 0); a stop that leaves the service "
                "running (unconfirmed identity) is `identity_unconfirmed` "
                "(exit 1) in both output modes."
            ),
        ),
    ] = False,
) -> None:
    """Stop the background search service.

    Reads the status file from ``~/.vaultspec-rag/service.json``, verifies
    the PID is still alive and belongs to a vaultspec-rag process, sends
    a graceful termination signal (SIGTERM on Unix, CTRL_BREAK_EVENT on
    Windows), waits briefly for graceful shutdown, and removes the status file.
    Force-kills (SIGKILL/TerminateProcess) if graceful shutdown fails.

    With ``--port`` the running instance on that port is targeted directly via
    its ``/health`` identity, so a non-default-port service whose status file is
    missing or divergent (research F7) is still stoppable.

    Exit codes: 0 for every satisfied outcome (``stopped``, ``already_stopped``,
    ``cleaned``, ``reclaimed``); 1 when the stop is skipped because a live
    recorded process could not be confirmed as ours - the one outcome that
    leaves a service running.
    """
    if port is not None:
        _stop_service_on_port(port, json_mode)
        return

    status = _read_service_status()
    if status is None:
        # No service.json for this config. Before reporting "not running", fall
        # back to the machine-global singleton lock: a live holder is the
        # resident service even when it left no discovery file here, and
        # reclaiming it is the documented recovery for a wedged/undiscoverable
        # singleton that would otherwise deadlock `server start`.
        reclaimed = _reclaim_machine_singleton()
        if reclaimed is not None:
            _stop_success(
                json_mode,
                status="reclaimed",
                human_title="Service stopped",
                human_lines=(
                    f"Reclaimed the resident machine service (pid {reclaimed}); "
                    "it held the singleton lock without a discoverable status "
                    "file.",
                ),
                pid=reclaimed,
                **_initiator_fields(),
            )
            return
        # No reclaimable holder. We do NOT probe the port: on the shared default
        # port another project's healthy service would otherwise be misreported
        # as this config's orphan.
        _stop_success(
            json_mode,
            status="already_stopped",
            human_title="Service is not running.",
        )
        return

    pid = int(status["pid"])
    port = int(status["port"])
    raw_token = status.get("service_token")
    expected_token = raw_token if isinstance(raw_token, str) else None
    if not _cli._is_our_service(pid, port=port, expected_token=expected_token):
        # Identity not confirmed. Remove the discovery file only when the PID
        # is confirmed dead; an alive-but-unconfirmed PID (a transient
        # /health/identity miss) must not have its file erased, which would
        # both mis-report a live daemon as gone and break discovery (#204).
        if _should_unlink_discovery_file(_cli._is_pid_alive(pid)):
            _status_file().unlink(missing_ok=True)
            _stop_success(
                json_mode,
                status="cleaned",
                human_title="Service status cleaned",
                human_lines=(f"Recorded process {pid} is no longer running.",),
                pid=pid,
            )
            return
        raise _fail_stop(
            json_mode,
            error="identity_unconfirmed",
            message="Service stop skipped",
            human_lines=(
                f"Recorded process {pid} is alive but its identity could not "
                "be confirmed; the discovery file was left in place.",
            ),
            next_actions=("vaultspec-rag server status --verbose",),
            pid=pid,
            port=port,
        )

    _terminate_and_confirm(pid)
    _status_file().unlink(missing_ok=True)
    _stop_success(
        json_mode,
        status="stopped",
        human_title="Service stopped",
        human_lines=(_process_line(pid),),
        pid=pid,
        port=port,
        **_initiator_fields(),
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
        # Confirmed dead: the only state in which the discovery file may be
        # removed (#204). The ambiguous branches below keep the file and only
        # report a degraded state.
        if _should_unlink_discovery_file(pid_alive):
            _status_file().unlink(missing_ok=True)
        return (
            "crashed_pid_dead",
            "crashed (PID dead, stale service.json cleaned)",
            4,
        )
    if not pid_is_ours:
        return (
            "crashed_pid_reused",
            "crashed (PID reused by unrelated process)",
            4,
        )
    if not port_listening:
        return "crashed_port_silent", "crashed (port silent)", 4
    if heartbeat_stale:
        return "crashed_heartbeat_stale", "crashed (heartbeat stale)", 4
    return "running", "running", 0


def _evaluate_service_signals(
    status: dict[str, Any],
) -> tuple[
    int, int, str, bool, bool, bool, float | None, bool, bool | None, str, str, int
]:
    pid = int(status.get("pid", 0))
    port = int(status.get("port", 0))
    started_at = str(status.get("started_at", ""))

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
    operational: dict[str, object] | None,
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
    if isinstance(operational, dict):
        payload["operational"] = operational
    _emit_json(
        exit_code == 0,
        "service.status",
        data=payload,
        **(
            {"error": state, "message": f"Service status: {state}"}
            if exit_code != 0
            else {}
        ),
    )
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _get_token_label(token_match: bool | None) -> str:
    if token_match is None:
        return "not verified by this status check"
    if token_match:
        return "verified"
    return "does not match the recorded service"


def _model_ready_label(value: object) -> str:
    if value is True:
        return "ready"
    if value is False:
        return "not ready"
    return "not reported by service"


def _process_identity_label(pid_alive: bool, pid_is_ours: bool) -> str:
    if pid_is_ours:
        return "verified"
    if pid_alive:
        return "does not match the recorded service"
    return "not verified because the process is not running"


def _network_label(port_listening: bool, pid_alive: bool) -> str:
    if port_listening:
        return "accepting connections"
    if pid_alive:
        return "not accepting connections"
    return "not accepting connections"


def _plain_status_label(state: str) -> str:
    return re.sub(r"\[[^]]*\]", "", state)


def _counted_unit(value: int, singular: str, plural: str | None = None) -> str:
    unit = singular if value == 1 else plural or f"{singular}s"
    return f"{value} {unit}"


def _format_status_duration(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported by service"
    seconds = max(0, int(float(raw)))
    if seconds < 60:
        return _counted_unit(seconds, "second")
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        if seconds:
            return (
                f"{_counted_unit(minutes, 'minute')} {_counted_unit(seconds, 'second')}"
            )
        return _counted_unit(minutes, "minute")
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        if minutes:
            return f"{_counted_unit(hours, 'hour')} {_counted_unit(minutes, 'minute')}"
        return _counted_unit(hours, "hour")
    days, hours = divmod(hours, 24)
    if hours:
        return f"{_counted_unit(days, 'day')} {_counted_unit(hours, 'hour')}"
    return _counted_unit(days, "day")


def _format_started_label(raw: object) -> str:
    if not isinstance(raw, str) or not raw or raw == "unknown":
        return "not reported by local record"
    try:
        started = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    return f"{started.astimezone().strftime('%H:%M:%S')} local time"


def _job_progress_summary(job: dict[str, object]) -> str:
    parts: list[str] = []
    progress = _human_progress(job)
    if progress:
        parts.append(progress)
    stale_progress = _stale_progress_label(job)
    if stale_progress:
        parts.append(stale_progress)
    return f", {', '.join(parts)}" if parts else ""


def _job_command_name(job: dict[str, object]) -> str:
    operation = _operation_label(job)
    project = _project_label(job)
    if project != "project not reported":
        return f"{operation} for {project}"
    return operation


def _current_job_summary(job: dict[str, object] | None) -> str:
    if job is None:
        return "none"
    started_at = job.get("started_at")
    age = (
        _format_status_duration(time.time() - float(started_at))
        if isinstance(started_at, int | float)
        else "not reported by service"
    )
    return f"{_job_command_name(job)} ({age}{_job_progress_summary(job)})"


def _active_job_records(
    job_records: list[dict[str, object]],
) -> list[dict[str, object]]:
    active: list[dict[str, object]] = []
    for entry in job_records:
        if entry.get("phase") != "running":
            continue
        progress = entry.get("progress")
        if (
            isinstance(progress, dict)
            and cast("dict[str, object]", progress).get("step") == "queued"
        ):
            continue
        active.append(entry)
    return sorted(active, key=_job_started_timestamp)


def _job_started_timestamp(job: dict[str, object]) -> float:
    started_at = job.get("started_at")
    return float(started_at) if isinstance(started_at, int | float) else 0.0


def _running_job_line(job: dict[str, object]) -> str:
    return f"  * {_current_job_summary(job)}"


def _current_job_detail_lines(jobs: dict[str, object] | None) -> list[str]:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return ["Current job: not reported by service"]
    raw_current_jobs = jobs.get("current_jobs")
    current_jobs = (
        cast("list[object]", raw_current_jobs)
        if isinstance(raw_current_jobs, list)
        else None
    )
    if current_jobs is not None and len(current_jobs) > 1:
        return [
            "Active jobs:",
            *[
                _running_job_line(cast("dict[str, object]", job))
                for job in current_jobs
                if isinstance(job, dict)
            ],
        ]
    current_job = jobs.get("current_job")
    if not isinstance(current_job, dict):
        return ["Current job: none active"]
    job = cast("dict[str, object]", current_job)
    started_at = job.get("started_at")
    runtime = (
        _format_status_duration(time.time() - float(started_at))
        if isinstance(started_at, int | float)
        else "not reported by service"
    )
    lines = [
        "Current job:",
        f"  Operation: {_operation_label(job)}",
    ]
    project = _project_label(job)
    if project != "project not reported":
        lines.append(f"  Project: {project}")
    lines.append(f"  Runtime: {runtime}")
    progress = _human_progress(job)
    if progress:
        lines.append(f"  Progress: {progress}")
    warning = _stale_progress_label(job)
    if warning:
        lines.append(f"  Warning: {warning}")
    return lines


def _print_current_job_detail(jobs: dict[str, object] | None) -> None:
    for line in _current_job_detail_lines(jobs):
        _cli.console.print(line, markup=False, highlight=False, soft_wrap=True)


def _print_detail_line(label: str, value: object) -> None:
    _cli.console.print(f"{label}: {value}", markup=False, highlight=False)


def _print_health_detail(
    health: dict[str, object] | None, port_listening: bool
) -> None:
    if isinstance(health, dict):
        _print_detail_line(
            "Requests",
            _status_health_label(health, port_listening=port_listening),
        )
        compute = (
            "GPU available"
            if health.get("cuda") is True
            else "no supported GPU detected"
            if health.get("cuda") is False
            else "not reported by service"
        )
        _print_detail_line("Compute", compute)
        env_exe = health.get("executable")
        if isinstance(env_exe, str) and env_exe:
            _print_detail_line("Service env", env_exe)
        _print_detail_line(
            "Search models", _model_ready_label(health.get("models_loaded"))
        )
        _print_detail_line(
            "Reranking", _model_ready_label(health.get("reranker_loaded"))
        )
        _print_detail_line(
            "Loaded projects",
            health.get("project_count", "not reported by service"),
        )
        _print_detail_line("Uptime", _format_status_duration(health.get("uptime_s")))
    elif port_listening:
        _print_detail_line("Requests", "not reachable")


def _job_records_from_result(result: dict[str, object]) -> list[dict[str, object]]:
    jobs = result.get("jobs")
    if not isinstance(jobs, list):
        return []
    return [
        cast("dict[str, object]", entry)
        for entry in cast("list[object]", jobs)
        if isinstance(entry, dict)
    ]


def _queued_job_count(job_records: list[dict[str, object]]) -> int:
    queued = 0
    for entry in job_records:
        progress = entry.get("progress")
        if entry.get("phase") == "running" and isinstance(progress, dict):
            queued += int(cast("dict[str, object]", progress).get("step") == "queued")
    return queued


def _summary_count(
    value: object,
    *,
    fallback: int = 0,
) -> int:
    return value if isinstance(value, int) and value > 0 else fallback


def _running_job_count(
    summary: dict[str, object],
    job_records: list[dict[str, object]],
) -> int:
    fallback = sum(1 for entry in job_records if entry.get("phase") == "running")
    return _summary_count(summary.get("running"), fallback=fallback)


def _jobs_summary_from_result(result: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(result, dict):
        return {"available": False}
    if result.get("ok") is False:
        return {
            "available": False,
            "error": result.get("error", "service_error"),
            "message": result.get("message", "Jobs route returned an error."),
        }
    summary = result.get("summary")
    summary_dict = (
        cast("dict[str, object]", summary) if isinstance(summary, dict) else {}
    )
    job_records = _job_records_from_result(result)
    active_job_records = _active_job_records(job_records)
    total_count = _summary_count(result.get("total"), fallback=len(job_records))
    returned_count = _summary_count(result.get("returned"), fallback=len(job_records))
    return {
        "available": True,
        "running": _running_job_count(summary_dict, job_records),
        "total": total_count,
        "returned": returned_count,
        "queued": _queued_job_count(job_records),
        "current_job": next(iter(active_job_records), None),
        "current_jobs": active_job_records,
        "phases": summary_dict.get("phases", {}),
        "sources": summary_dict.get("sources", {}),
        "triggers": summary_dict.get("triggers", {}),
        "initiators": summary_dict.get("initiators", {}),
        "active_initiators": summary_dict.get("active_initiators", {}),
        "users": summary_dict.get("users", {}),
    }


def _status_jobs_summary(port: int, port_listening: bool) -> dict[str, object]:
    if not port_listening:
        return {"available": False}
    try:
        return _jobs_summary_from_result(
            _try_http_admin("get_jobs", {"limit": 5}, port),
        )
    except Exception as exc:
        return {
            "available": False,
            "error": exc.__class__.__name__,
            "message": str(exc),
        }


def _status_next_action(
    state: str,
    health: dict[str, object] | None,
    jobs: dict[str, object],
    *,
    port: int | None = None,
) -> str:
    port_arg = f" --port {port}" if port is not None else ""
    if state == "stopped":
        return f"vaultspec-rag server start{port_arg}"
    if state != "running":
        return f"vaultspec-rag server logs --limit 80{port_arg}"
    if not isinstance(health, dict) or health.get("status") != "ready":
        return f"vaultspec-rag server status --verbose{port_arg}"
    running_jobs = jobs.get("running")
    if isinstance(running_jobs, int) and running_jobs > 0:
        return f"vaultspec-rag server jobs --state active{port_arg}"
    return f'vaultspec-rag search "<query>" --type code{port_arg} --timeout 120'


def _status_operational_summary(
    state: str,
    port: int,
    port_listening: bool,
    health: dict[str, object] | None,
    *,
    explicit_port: bool = False,
) -> dict[str, object]:
    jobs = _status_jobs_summary(port, port_listening)
    return {
        "jobs": jobs,
        "next_action": _status_next_action(
            state,
            health,
            jobs,
            port=port if explicit_port else None,
        ),
    }


def _print_operational_detail(
    operational: dict[str, object] | None,
) -> None:
    if operational is None:
        return
    status_file_port = operational.get("status_file_port")
    if status_file_port:
        _print_detail_line("Status file port", status_file_port)
    jobs = operational.get("jobs")
    if isinstance(jobs, dict):
        jobs_dict = cast("dict[str, object]", jobs)
        if jobs_dict.get("available") is True:
            _print_detail_line("Busy", _status_busy_label(jobs_dict))
            _print_detail_line("Queue", _status_queue_label(jobs_dict))
            _print_detail_line("Processed jobs", _status_jobs_label(jobs_dict))
            _print_current_job_detail(jobs_dict)
        else:
            _print_detail_line("Processed jobs", "not reported by service")
    next_action = operational.get("next_action")
    if next_action:
        _print_next_action(next_action)


def _print_next_action(next_action: object) -> None:
    if next_action:
        _cli.console.print("Next action:", markup=False, highlight=False)
        _cli.console.print(f"  {next_action}", markup=False, highlight=False)


def _status_health_label(
    health: dict[str, object] | None,
    *,
    port_listening: bool,
) -> str:
    if isinstance(health, dict):
        raw_status = health.get("status")
        if not isinstance(raw_status, str) or not raw_status or raw_status == "unknown":
            return "not reported by service"
        status = raw_status
        if status == "ready":
            return "ready for requests"
        if status == "starting":
            return "starting up"
        return status.replace("_", " ")
    return "not reachable" if port_listening else "not available"


def _status_busy_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "not reported by service"
    running = jobs.get("running")
    queued = jobs.get("queued")
    running_count = running if isinstance(running, int) else 0
    queued_count = queued if isinstance(queued, int) else 0
    if running_count <= 0:
        return "idle"
    active_count = max(0, running_count - queued_count)
    if active_count <= 0 and queued_count > 0:
        return (
            "1 job waiting to write"
            if queued_count == 1
            else f"{queued_count} jobs waiting to write"
        )
    if active_count > 0 and queued_count > 0:
        active_text = (
            "processing 1 job"
            if active_count == 1
            else f"processing {active_count} jobs"
        )
        waiting_text = "1 waiting" if queued_count == 1 else f"{queued_count} waiting"
        return f"{active_text}; {waiting_text}"
    if active_count == 1:
        return "processing 1 job"
    return f"processing {active_count} jobs"


def _status_queue_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "not reported by service"
    running = jobs.get("running")
    queued = jobs.get("queued")
    running_count = running if isinstance(running, int) else 0
    queued_count = queued if isinstance(queued, int) else 0
    if running_count <= 0:
        return "nothing waiting"
    active_count = max(0, running_count - queued_count)
    if queued_count > 0:
        active_text = (
            "1 active job" if active_count == 1 else f"{active_count} active jobs"
        )
        queued_text = (
            "1 waiting job" if queued_count == 1 else f"{queued_count} waiting jobs"
        )
        return f"{queued_text}; {active_text}"
    running_text = (
        "1 active job" if running_count == 1 else f"{running_count} active jobs"
    )
    return f"nothing waiting; {running_text}"


def _status_jobs_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "not reported by service"
    phases = jobs.get("phases")
    running = jobs.get("running")
    queued = jobs.get("queued")
    running_count = running if isinstance(running, int) else 0
    queued_count = queued if isinstance(queued, int) else 0
    active_count = max(0, running_count - queued_count)
    finished_count = 0
    failed_count = 0
    if isinstance(phases, dict):
        phase_dict = cast("dict[str, object]", phases)
        done = phase_dict.get("done")
        error = phase_dict.get("error")
        failed = phase_dict.get("failed")
        if isinstance(done, int):
            finished_count = done
        if isinstance(error, int):
            failed_count += error
        if isinstance(failed, int):
            failed_count += failed
    return (
        f"{finished_count} finished, {active_count} active, "
        f"{queued_count} waiting, {failed_count} failed"
    )


def _status_uptime_label(health: dict[str, object] | None) -> str:
    if not isinstance(health, dict):
        return "not reported by service"
    return _format_status_duration(health.get("uptime_s"))


def _status_env_label(health: dict[str, object] | None) -> str:
    """Return the daemon's python interpreter from /health, or a clear miss.

    The service runs in whatever interpreter launched ``server start`` (it does
    not provision its own python), so surfacing it makes the service<->env
    coupling visible at a glance.
    """
    if isinstance(health, dict):
        exe = health.get("executable")
        if isinstance(exe, str) and exe:
            return exe
    return "not reported by service"


def _render_status_summary(
    *,
    state_label: str,
    port: int,
    port_listening: bool,
    health: dict[str, object] | None,
    operational: dict[str, object] | None,
    exit_code: int,
) -> None:
    jobs = operational.get("jobs") if isinstance(operational, dict) else None
    jobs_dict = cast("dict[str, object]", jobs) if isinstance(jobs, dict) else None
    lines = [
        f"Server: {_plain_status_label(state_label)}",
        f"Requests: {_status_health_label(health, port_listening=port_listening)}",
        f"Busy: {_status_busy_label(jobs_dict)}",
        f"Address: http://127.0.0.1:{port}",
        f"Service env: {_status_env_label(health)}",
        f"Uptime: {_status_uptime_label(health)}",
        f"Queue: {_status_queue_label(jobs_dict)}",
        f"Processed jobs: {_status_jobs_label(jobs_dict)}",
    ]
    for line in lines:
        _cli.console.print(line, markup=False, highlight=False)
    _print_current_job_detail(jobs_dict)
    if isinstance(operational, dict):
        _print_next_action(operational.get("next_action"))
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _render_status_detail(
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
    operational: dict[str, object] | None,
) -> None:
    _cli.console.print("Service status")
    _print_detail_line("Local record", "found")
    _print_detail_line("Process ID", pid)
    _print_detail_line("Address", f"http://127.0.0.1:{port}")
    _print_detail_line("Started", _format_started_label(started_at))
    _print_detail_line("Process", "running" if pid_alive else "not running")
    _print_detail_line(
        "Process check",
        _process_identity_label(pid_alive, pid_is_ours),
    )
    _print_detail_line("Identity check", _get_token_label(token_match))
    _print_detail_line("Network", _network_label(port_listening, pid_alive))
    if heartbeat_age is None:
        _print_detail_line("Heartbeat", "absent")
    else:
        suffix = " (stale)" if heartbeat_stale else ""
        _print_detail_line("Heartbeat", f"{heartbeat_age:.0f}s ago{suffix}")
    _print_detail_line("Server", _plain_status_label(state_label))

    _print_health_detail(health, port_listening)
    _print_operational_detail(operational)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _render_port_only_status(
    port: int,
    *,
    json_mode: bool,
    verbose: bool = False,
) -> None:
    port_listening = _port_is_listening(port)
    health = _health_probe(port) if port_listening else None
    state = (
        "running"
        if isinstance(health, dict) and health.get("status") == "ready"
        else "stopped"
        if not port_listening
        else "unreachable"
    )
    exit_code = 0 if state == "running" else 3 if state == "stopped" else 4
    operational = _status_operational_summary(
        state,
        port,
        port_listening,
        health,
        explicit_port=True,
    )
    payload: dict[str, object] = {
        "service_json_present": False,
        "pid": None,
        "port": port,
        "pid_alive": None,
        "pid_matches_service": None,
        "port_listening": port_listening,
        "heartbeat_age_seconds": None,
        "heartbeat_stale": None,
        "service_token_match": None,
        "state": state,
    }
    if isinstance(health, dict):
        payload["health"] = health
    payload["operational"] = operational

    if json_mode:
        _emit_json(
            exit_code == 0,
            "service.status",
            data=payload,
            **(
                {"error": state, "message": f"Service status: {state}"}
                if exit_code != 0
                else {}
            ),
        )
        if exit_code != 0:
            raise typer.Exit(code=exit_code)
        return

    if not verbose:
        rendered_state = "running" if state == "running" else state
        _render_status_summary(
            state_label=rendered_state,
            port=port,
            port_listening=port_listening,
            health=health,
            operational=operational,
            exit_code=exit_code,
        )
        return

    _cli.console.print("Service status")
    _print_detail_line("Local record", "not found")
    _print_detail_line("Process", "not reported")
    _print_detail_line("Address", f"http://127.0.0.1:{port}")
    _print_detail_line(
        "Network",
        "accepting connections" if port_listening else "not accepting connections",
    )
    _print_detail_line("Server", state)
    _print_health_detail(health, port_listening)
    _print_operational_detail(operational)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _explicit_port_state(
    port_listening: bool,
    health: dict[str, object] | None,
) -> tuple[str, str, int, bool]:
    if isinstance(health, dict) and health.get("status") == "ready":
        return "running", "running", 0, False
    if port_listening:
        return "unreachable", "unreachable", 4, False
    return "stopped", "stopped", 3, False


def _status_response_token_match(
    expected_token: str | None,
    health: dict[str, object] | None,
) -> bool | None:
    response_token = health.get("service_token") if isinstance(health, dict) else None
    if isinstance(response_token, str) and expected_token:
        return bool(response_token) and response_token == expected_token
    return None


def _render_explicit_port_status(
    status: dict[str, Any],
    target_port: int,
    *,
    json_mode: bool,
    verbose: bool = False,
) -> None:
    pid = int(status.get("pid", 0))
    status_file_port = int(status.get("port", 0))
    started_at = str(status.get("started_at", "unknown"))
    raw_token = status.get("service_token")
    expected_token = raw_token if isinstance(raw_token, str) else None
    pid_alive = _cli._is_pid_alive(pid)
    pid_is_ours = (
        _cli._is_our_service(pid, port=status_file_port, expected_token=expected_token)
        if pid_alive
        else False
    )
    heartbeat_age = _heartbeat_age_seconds(status)
    port_listening = _port_is_listening(target_port)
    health = _health_probe(target_port) if port_listening else None
    state, state_label, exit_code, heartbeat_stale = _explicit_port_state(
        port_listening,
        health,
    )
    token_match = _status_response_token_match(expected_token, health)
    operational = _status_operational_summary(
        state,
        target_port,
        port_listening,
        health,
        explicit_port=True,
    )
    if target_port != status_file_port:
        operational["status_file_port"] = status_file_port

    if json_mode:
        _render_status_json(
            pid,
            target_port,
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
            operational,
        )
        return

    if target_port != status_file_port:
        _cli.console.print(
            "Local record points to "
            f"http://127.0.0.1:{status_file_port}; "
            f"checking http://127.0.0.1:{target_port}.",
            markup=False,
            highlight=False,
        )
    if verbose:
        _render_status_detail(
            pid,
            target_port,
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
            operational,
        )
        return
    _render_status_summary(
        state_label=state_label,
        port=target_port,
        port_listening=port_listening,
        health=health,
        operational=operational,
        exit_code=exit_code,
    )


@server_app.command(
    "status",
    help=(
        "Show the human operator summary for server readiness, work, and next checks."
    ),
)
def service_status(
    requested_port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit JSON for scripts instead of human text. Preserves exit "
                "codes 0 (running), 3 (stopped), and 4 (crashed or divergent)."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help=(
                "Show process, heartbeat, service identity, model, and extra "
                "diagnostic details in the human output."
            ),
        ),
    ] = False,
) -> None:
    """Display the current status of the background search service.

    Gathers four signals before rendering - ``service.json`` present,
    PID alive, port listening, heartbeat fresh - and surfaces each as
    its own row plus a derived ``Server`` row. Avoids the previous
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
        if requested_port is not None:
            _render_port_only_status(
                requested_port,
                json_mode=json_mode,
                verbose=verbose,
            )
            return
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
        if verbose:
            _cli.console.print("Service status")
            _print_detail_line("Local record", "not found")
            _print_detail_line("Server", "stopped")
        else:
            _render_status_summary(
                state_label="stopped",
                port=_default_service_port() or 8766,
                port_listening=False,
                health=None,
                operational=None,
                exit_code=3,
            )
            return
        raise typer.Exit(code=3)

    if requested_port is not None:
        _render_explicit_port_status(
            status,
            requested_port,
            json_mode=json_mode,
            verbose=verbose,
        )
        return

    (
        pid,
        status_file_port,
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

    target_port = status_file_port
    health = _health_probe(target_port) if port_listening else None
    operational = _status_operational_summary(
        state,
        target_port,
        port_listening,
        health,
        explicit_port=False,
    )

    if json_mode:
        _render_status_json(
            pid,
            target_port,
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
            operational,
        )
        return

    if verbose:
        _render_status_detail(
            pid,
            target_port,
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
            operational,
        )
        return
    _render_status_summary(
        state_label=state_label,
        port=target_port,
        port_listening=port_listening,
        health=health,
        operational=operational,
        exit_code=exit_code,
    )


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
