"""``server start``: spawn, guard, and await the background search service.

Owns the start path end to end: the qdrant-binary and machine-singleton
preconditions, the GPU pre-flight of the daemon interpreter, the idempotent
"already running" success, the spawn, and the health-wait that emits the
terminal outcome. Every terminal branch converges on ``_start_success`` /
``_fail_start`` so a broker in ``--json`` mode reads exactly one envelope.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import typer

import vaultspec_rag.cli as _cli

from ..config import EnvVar, get_config
from ._app import _global_target, server_app
from ._core import logger
from ._gpu_errors import (
    RuntimeEnvKind,
    classify_interpreter_env,
    durable_tool_install_command,
    gpu_escape_hatch_command,
)
from ._http_search import _try_http_health
from ._process import (
    DaemonBreakawayError,
    _port_is_available,
    _probe_daemon_cuda,
    _resolve_daemon_interpreter,
    _spawn_service,
)
from ._render import _emit_json
from ._service_lifecycle import (
    _address_line,
    _print_lifecycle_lines,
    _print_lifecycle_next_actions,
    _process_line,
    _should_unlink_discovery_file,
)
from ._service_status import (
    SERVICE_PHASE_WARMING,
    _delete_service_status,
    _log_file,
    _read_service_status,
    _service_phase,
    _update_service_metadata,
    _update_service_token,
    _write_service_status,
)

if TYPE_CHECKING:
    from rich.status import Status

__all__ = [
    "_caller_ephemeral_warning",
    "_ephemeral_env_warning",
    "_existing_service_running",
    "_fail_start",
    "_start_success",
    "_tail_daemon_log",
    "service_start",
]

_START_COMMAND = "service.start"


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


def _existing_service_running() -> tuple[int, int, str] | None:
    """Return ``(pid, port, health_status)`` of an owned serving daemon, else ``None``.

    Detection only - it no longer prints, so the caller renders the human
    "already running" lines or the JSON envelope from one shared detection path
    (the idempotent-start contract). ``health_status`` is the daemon's own
    ``/health`` status (``ready`` / ``degraded`` / ``error``) so the caller can
    distinguish a serving-and-healthy daemon from one that answers but cannot
    serve yet (issue #237) instead of calling every response "running".
    Removes the status file only when its recorded PID is confirmed dead; an
    ambiguous identity/health miss on a *live* PID leaves the file untouched so
    a transient probe failure cannot erase a running daemon's discovery file
    (issue #204).
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
        health = _try_http_health(existing_port)
        if health is not None:
            raw_status = health.get("status")
            health_status = (
                raw_status if isinstance(raw_status, str) and raw_status else "error"
            )
            return (existing_pid, existing_port, health_status)
    # Identity or health did not confirm a live service we own. Remove the
    # status file only when the recorded PID is confirmed dead; leave it in
    # place on an ambiguous miss against a live PID (issue #204).
    if _should_unlink_discovery_file(_cli._is_pid_alive(existing_pid)):
        _delete_service_status()
    return None


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
        kind = classify_interpreter_env(interpreter)
        if kind is RuntimeEnvKind.PROJECT_VENV:
            next_actions = (
                "Install/repair GPU torch in the service environment: "
                "vaultspec-rag install, then uv sync --reinstall-package torch",
                "Confirm the GPU is visible: nvidia-smi",
            )
        else:
            next_actions = (
                "Repair this environment now (undone by the next tool "
                f"upgrade): {gpu_escape_hatch_command(interpreter)}",
                "Make upgrades keep the GPU wheel (stop the service first): "
                f"{durable_tool_install_command()}",
                "Confirm the GPU is visible: nvidia-smi",
            )
        raise _fail_start(
            json_mode,
            error="service_env_no_gpu",
            message="Service start failed",
            human_lines=(
                f"Service interpreter: {interpreter} ({kind.label})",
                f"That environment cannot run the GPU-only service: {reason}.",
                "The service runs in the environment that launches it and does "
                "not provision its own python.",
            ),
            next_actions=next_actions,
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
        warming = _service_phase(_read_service_status()) == SERVICE_PHASE_WARMING
        owner_line = (
            f"A vaultspec-rag service already owns this machine "
            f"(pid {machine_holder}) and is warming up (loading models); "
            "it will serve shortly."
            if warming
            else f"A vaultspec-rag service already owns this machine "
            f"(pid {machine_holder})."
        )
        raise _fail_start(
            json_mode,
            error="machine_owned",
            message="Service start failed",
            human_lines=(
                owner_line,
                "One service owns the machine's GPU and managed Qdrant; a second "
                "resident service is not supported.",
            ),
            next_actions=(
                "vaultspec-rag server status",
                "vaultspec-rag server stop",
            ),
            holder_pid=machine_holder,
            **({"holder_phase": "warming"} if warming else {}),
        )


def _attach_existing_service(
    json_mode: bool,
    caller_warnings: tuple[str, ...],
) -> bool:
    """Attach to an owned serving daemon and emit the idempotent outcome."""
    existing = _existing_service_running()
    if existing is None:
        return False
    if caller_warnings and not json_mode:
        _print_lifecycle_lines(*caller_warnings)
    attach_extra: dict[str, object] = (
        {"warnings": list(caller_warnings)} if caller_warnings else {}
    )
    existing_pid, existing_port, health_status = existing
    if health_status == "ready":
        _start_success(
            json_mode,
            status="already_running",
            human_title="Service already running",
            human_lines=(
                _process_line(existing_pid),
                _address_line(existing_port),
            ),
            pid=existing_pid,
            port=existing_port,
            **attach_extra,
        )
        return True
    _start_success(
        json_mode,
        status="already_running",
        human_title=f"Service already running (health: {health_status})",
        human_lines=(
            _process_line(existing_pid),
            _address_line(existing_port),
            "The service is serving but not fully ready; searches may "
            "fail or queue until it recovers.",
            "Watch: vaultspec-rag server status",
        ),
        pid=existing_pid,
        port=existing_port,
        health=health_status,
        **attach_extra,
    )
    return True


def _attach_warming_service(json_mode: bool) -> bool:
    """Attach to a live owned daemon that has not bound its port yet."""
    warming_status = _read_service_status()
    if warming_status is None or (
        _service_phase(warming_status) != SERVICE_PHASE_WARMING
    ):
        return False
    warming_pid = int(warming_status["pid"])
    warming_port = int(warming_status["port"])
    if not _cli._is_pid_alive(warming_pid) or not _cli._is_our_service(warming_pid):
        return False
    _start_success(
        json_mode,
        status="already_starting",
        human_title="Service already starting",
        human_lines=(
            _process_line(warming_pid),
            "Warming up (loading models, not yet serving); it will serve shortly.",
            "Watch: vaultspec-rag server status",
        ),
        pid=warming_pid,
        port=warming_port,
        phase="warming",
    )
    return True


def _spawn_prepared_service(
    port: int,
    log_path: Path,
    *,
    updates: bool | None,
    update_delay_ms: int | None,
    repeat_update_delay_s: float | None,
    qdrant: bool | None,
    local_only: bool,
    preprocess_forward: Literal["off"] | None,
    json_mode: bool,
) -> int:
    """Spawn one prepared daemon or translate breakaway denial."""
    try:
        return _spawn_service(
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
    # The attach paths below never resolve a daemon interpreter, so the
    # daemon-side ephemeral warning cannot fire for them. The caller's own env
    # is the condition that matters here: an operator invoking from a uvx cache
    # env still walks into the forced-reinstall trap, and `already_running` is
    # the outcome a long-lived daemon returns almost every time.
    caller_warnings = _caller_ephemeral_warning()
    if _attach_existing_service(json_mode, caller_warnings):
        return

    # A live owned daemon that stamped ``warming`` holds the machine lock but
    # is not yet serving (models loading, port silent), so the health-based
    # check above misses it. That is a start already in progress - an
    # attachable success, not the machine_owned fault the guard below would
    # report (issue #237). A reused pid must not resurrect a stale stamp,
    # hence the liveness + identity checks.
    if _attach_warming_service(json_mode):
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
    interpreter = _resolve_daemon_interpreter()
    env_warnings = _ephemeral_env_warning(interpreter)
    if env_warnings and not json_mode:
        _print_lifecycle_lines(*env_warnings)
    _preflight_daemon_cuda(interpreter, json_mode=json_mode)
    t0 = time.perf_counter()
    pid = _spawn_prepared_service(
        port,
        log_path,
        updates=updates,
        update_delay_ms=update_delay_ms,
        repeat_update_delay_s=repeat_update_delay_s,
        qdrant=qdrant,
        local_only=local_only,
        preprocess_forward=preprocess_forward,
        json_mode=json_mode,
    )
    _write_service_status(pid, port)
    _await_service_ready(
        pid,
        port,
        log_path,
        json_mode=json_mode,
        t0=t0,
        env_warnings=env_warnings,
    )


def _ephemeral_env_warning(interpreter: str) -> tuple[str, ...]:
    """Warning lines when the daemon interpreter is a uvx ephemeral cache env.

    A uvx run silently falls back to a cached ephemeral environment when the
    installed tool env is broken (e.g. a forced reinstall failed mid-removal
    because the running service held the Scripts dir) or the request does not
    match the installed spec. Nothing else distinguishes that env from the
    installed tool, so the start surface names it loudly. Returns ``()`` for
    every other environment kind.
    """
    if classify_interpreter_env(interpreter) is not RuntimeEnvKind.UVX_EPHEMERAL:
        return ()
    return (
        "WARNING: the service interpreter is a uvx EPHEMERAL cache "
        "environment - not the installed tool:",
        f"  {interpreter}",
        "uvx falls back to a cached environment when the installed tool env "
        "is broken or the request does not match it.",
        "Reinstall the tool with the service stopped (the Scripts lock during "
        "a forced reinstall is the running service itself):",
        f"  {durable_tool_install_command()}",
    )


def _caller_ephemeral_warning(interpreter: str | None = None) -> tuple[str, ...]:
    """Warning lines when *this* CLI process runs from a uvx ephemeral env.

    Distinct from :func:`_ephemeral_env_warning`, which describes the daemon
    interpreter of a service being spawned. On the attach paths no daemon is
    spawned and the running service may be entirely healthy, so the subject is
    the caller: a forced reinstall from here still fails mid-removal while the
    service holds the Scripts dir. Returns ``()`` for every other env kind.

    ``interpreter`` defaults to the running interpreter; it is a parameter so
    the classification can be exercised against real path shapes.
    """
    resolved = sys.executable if interpreter is None else interpreter
    if classify_interpreter_env(resolved) is not RuntimeEnvKind.UVX_EPHEMERAL:
        return ()
    return (
        "WARNING: this command is running from a uvx EPHEMERAL cache "
        "environment - not the installed tool:",
        f"  {resolved}",
        "The already-running service was started from a different "
        "environment; this env disappears when the uvx run ends.",
        "Reinstall the tool with the service stopped (the Scripts lock during "
        "a forced reinstall is the running service itself):",
        f"  {durable_tool_install_command()}",
    )


def _startup_phase_label(health: dict[str, object] | None) -> str:
    """Describe what the spawned daemon is doing right now, for the wait spinner.

    Once the daemon serves, its own ``/health`` status is authoritative; before
    the port binds, the ``warming`` phase stamped in the discovery file
    distinguishes model loading from a daemon that never came up.
    """
    if health is not None:
        raw = health.get("status")
        if isinstance(raw, str) and raw:
            return f"serving, health: {raw}"
    if _service_phase(_read_service_status()) == SERVICE_PHASE_WARMING:
        return "warming (loading models)"
    return "waiting for the daemon to come up"


def _await_service_ready(
    pid: int,
    port: int,
    log_path: Path,
    *,
    json_mode: bool,
    t0: float,
    env_warnings: tuple[str, ...] = (),
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
    spinner: contextlib.AbstractContextManager[Status | None] = (
        contextlib.nullcontext()
        if json_mode
        else _cli.console.status("Starting service...")
    )
    try:
        with spinner as spinner_status:
            while elapsed < deadline:
                time.sleep(delay)
                elapsed = time.perf_counter() - t0

                # Check if process died (port conflict, etc.)
                if not _cli._is_pid_alive(pid):
                    _delete_service_status()
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

                health = _try_http_health(port)
                if health is not None and health.get("status") == "ready":
                    # Persist the token from /health into service.json so
                    # auto-delegation auth works before the first heartbeat
                    # tick overwrites the file.
                    token_from_health = health.get("service_token")
                    if isinstance(token_from_health, str) and token_from_health:
                        _update_service_token(token_from_health)
                    pid = _health_service_pid(health, pid)
                    _update_service_metadata(
                        _status_metadata_from_health(health, pid=pid)
                    )
                    startup_s = time.perf_counter() - t0
                    extra: dict[str, object] = (
                        {"warnings": list(env_warnings)} if env_warnings else {}
                    )
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
                        **extra,
                    )
                    return

                # Surface the cold-start phase instead of a static spinner:
                # the daemon stamps ``warming`` while models load, and once
                # serving /health reports its own status - a minutes-long cold
                # start must be distinguishable from a wedged daemon.
                if spinner_status is not None:
                    spinner_status.update(
                        f"Starting service... {_startup_phase_label(health)} "
                        f"({elapsed:.0f}s elapsed, log: {log_path})"
                    )

                delay = min(delay * 2, 5.0)
    except KeyboardInterrupt:
        # The foreground wait ended but the detached daemon keeps starting -
        # say so instead of exiting silently while it warms invisibly
        # (issue #237). The requested state (ready) is unconfirmed, so this
        # is a non-zero outcome per the lifecycle contract.
        raise _fail_start(
            json_mode,
            error="start_interrupted",
            message="Service start interrupted",
            human_lines=(
                _process_line(pid),
                "The detached daemon continues starting in the background.",
                f"Log: {log_path}",
            ),
            next_actions=("vaultspec-rag server status",),
            pid=pid,
            log=str(log_path),
        ) from None

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
