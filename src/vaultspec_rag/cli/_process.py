"""Process, port, and health-probe helpers for the background service.

Liveness (``_is_pid_alive``), identity (``_is_our_service`` via a
``/health`` service-token round-trip with an executable-name
fallback), port probes, heartbeat staleness, the SSRF-safe health
probe, the detached-daemon spawn, and graceful termination all live
here. Helpers that tests monkeypatch on ``vaultspec_rag.cli`` (e.g.
``_is_pid_alive``, ``_health_probe``) are referenced through the
package namespace at call time so the substitution is observed.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import sysconfig
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import vaultspec_rag.cli as _cli

from .._machine_lock import (
    acquire_machine_lock,
    machine_lock_live_holder,
    machine_lock_path,
    release_machine_lock,
)
from ..config import EnvVar
from ._core import logger

__all__ = [
    "_HEARTBEAT_STALENESS_SECONDS",
    "DaemonBreakawayError",
    "_health_probe",
    "_heartbeat_age_seconds",
    "_is_our_service",
    "_is_pid_alive",
    "_port_is_available",
    "_port_is_listening",
    "_service_child_env",
    "_spawn_service",
    "_terminate_pid",
    "acquire_machine_lock",
    "machine_lock_live_holder",
    "machine_lock_path",
    "release_machine_lock",
]


class DaemonBreakawayError(RuntimeError):
    """The launching shell's Job Object denied daemon breakaway.

    Raised when ``CREATE_BREAKAWAY_FROM_JOB`` is refused so the daemon cannot
    be detached from the parent's Windows Job Object. Spawning anyway would
    create a daemon doomed to die when the launching shell closes (the flapping
    symptom of issue #204), so the spawn fails loudly with this actionable
    error instead of silently producing a shell-bound process.
    """


def _is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running.

    Args:
        pid: Process ID to check.

    Returns:
        True if the process exists and is running.

    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            0x1000,  # PROCESS_QUERY_LIMITED_INFORMATION
            False,
            pid,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == 259  # STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError as exc:
        logger.debug("pid %s not running: %s", pid, exc)
        return False
    except PermissionError as exc:
        # Permission denied means the process exists but isn't
        # owned by us - still "alive" for liveness purposes.
        logger.debug("pid %s alive but signal denied: %s", pid, exc)
        return True
    return True


def _is_our_service(
    pid: int,
    port: int | None = None,
    expected_token: str | None = None,
) -> bool:
    """Check if PID belongs to the daemon currently named in ``service.json``.

    Primary identity check (``port`` + ``expected_token`` supplied):
    probes ``/health`` on the port, compares ``service_token`` to
    ``expected_token``. Mismatch → False (positively not ours); match
    → True (positively ours); token-absent in the response → falls
    back to the executable-name check (pre-upgrade daemon, or an
    unrelated HTTP server returning 200 without a token).

    Fallback identity check (no port/token supplied, or
    token-absent in the response): on Windows uses
    ``QueryFullProcessImageNameW`` via ctypes to verify the process
    executable contains ``"python"``; on Unix inspects
    ``/proc/{pid}/cmdline`` for the module name; falls back to basic
    PID liveness when verification is unavailable.

    Args:
        pid: Process ID to verify.
        port: TCP port to probe ``/health`` on. When ``None``, only
            the fallback executable-name check runs.
        expected_token: Token value from ``service.json`` to match
            against the ``/health`` response. When ``None``, only
            the fallback check runs.

    Returns:
        True if the process appears to be the daemon named in
        ``service.json``.

    """
    if not _cli._is_pid_alive(pid):
        return False

    # Primary check: token round-trip via /health. Gated on both
    # port and expected_token being non-empty; the CLI passes
    # status.get("service_token") which is None for pre-upgrade
    # daemons and falsy for daemons whose first heartbeat tick has
    # not landed yet.
    if port is not None and expected_token:
        probe = _cli._health_probe(port)
        if probe is not None:
            response_token = probe.get("service_token")
            if isinstance(response_token, str) and response_token:
                # Both sides reported a token - the comparison is
                # authoritative regardless of outcome.
                return response_token == expected_token
            # Probe answered but with no token (pre-upgrade daemon,
            # or unrelated server returning 200). Fall back to the
            # executable-name path. Debug-log per the no-swallow
            # rule so the fallback is observable.
            logger.debug(
                "service_token absent on /health for pid=%d port=%d; "
                "falling back to executable-name check",
                pid,
                port,
            )
        # probe is None: connection failed. Fall back to exe-name
        # check (the daemon may be alive but port-bound late).

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFO
        if not handle:
            return True  # can't query → fall back to PID-alive trust
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return "python" in buf.value.lower()
            return True  # API call failed → fall back to trust
        finally:
            kernel32.CloseHandle(handle)
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
        return "vaultspec_rag" in cmdline
    except (OSError, ValueError) as exc:
        # Non-procfs systems (BSD, macOS without /proc) - fall back
        # to PID-alive trust. Debug-log per the no-swallow rule.
        logger.debug(
            "cmdline read failed for pid=%d: %s; falling back to PID-alive trust",
            pid,
            exc,
            exc_info=True,
        )
        return True


def _port_is_available(port: int) -> bool:
    """Check whether a TCP port is available for binding.

    Attempts to bind to ``127.0.0.1:port``. Used as a lightweight
    lock to prevent concurrent ``service start`` races: the port
    itself is the mutex.

    Args:
        port: TCP port to probe.

    Returns:
        True if the port is free, False if already in use.

    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError as exc:
            logger.debug("port %d not bindable: %s", port, exc)
            return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Reject HTTP redirects to prevent SSRF via health endpoint."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        _ = req, fp, code, msg, headers, newurl
        return None


# Mirrored from server._HEARTBEAT_STALENESS_SECONDS - kept as a
# local constant so cli.py does not import server (which would
# pull in FastMCP + heavy deps at CLI startup time). Bump both in
# lockstep if the contract changes.
_HEARTBEAT_STALENESS_SECONDS = 60


def _port_is_listening(port: int) -> bool:
    """Return True when ``127.0.0.1:port`` accepts a TCP connection.

    Cheaper than ``_health_probe`` (no HTTP round-trip, no JSON
    parsing) and answers the "is anything listening" question that
    ``service status`` needs to distinguish "PID alive but socket
    silent" from "PID alive and serving".
    """
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def _heartbeat_age_seconds(status: dict[str, Any]) -> float | None:
    """Compute seconds since the daemon's last heartbeat write.

    Returns ``None`` when the field is missing (pre-upgrade
    ``service.json`` or daemon that crashed before its first tick) or
    when the timestamp is unparseable. Callers treat ``None`` as
    "no heartbeat data" rather than "fresh".
    """
    raw = status.get("last_heartbeat")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError as exc:
        logger.debug("last_heartbeat %r unparseable: %s", raw, exc)
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - ts
    return delta.total_seconds()


def _health_probe(port: int) -> dict[str, Any] | None:
    """Probe the service health endpoint via HTTP GET.

    Args:
        port: TCP port to connect to on 127.0.0.1.

    Returns:
        Parsed JSON dict on success, a dict with ``status``
        ``"error"`` and ``http_code`` for HTTP errors (server
        running but unhealthy), or None for connection errors
        (server not running).

    """
    url = f"http://127.0.0.1:{port}/health"
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # HTTP errors mean the server answered but unhealthy - surface
        # the structured shape so callers can render the http code.
        return {"status": "error", "http_code": exc.code}
    except Exception as exc:
        # Connection failures (no server, bad SSL, timeout, malformed
        # JSON) yield None so callers can render "unreachable". The
        # broad catch is intentional because urllib raises many
        # distinct exception classes here; the debug log keeps the
        # swallow observable per the no-swallow rule. The narrower
        # codebase-wide sweep is filed as gh #130.
        logger.debug(
            "health probe failed for port=%d: %s",
            port,
            exc,
            exc_info=True,
        )
        return None


def _service_child_env(
    watch: bool | None = None,
    watch_debounce_ms: int | None = None,
    watch_cooldown_s: float | None = None,
    qdrant: bool | None = None,
    local_only: bool | None = None,
) -> dict[str, str]:
    """Build the environment for the detached daemon process.

    The daemon inherits configuration only through the environment (it
    parses no argv beyond ``--port``), so watcher flags passed to
    ``service start`` are translated into ``VAULTSPEC_RAG_WATCH*`` here,
    the qdrant server-mode flag into ``VAULTSPEC_RAG_QDRANT_SERVER``, and
    the local-only opt-out into ``VAULTSPEC_RAG_LOCAL_ONLY`` so the
    daemon's ``effective_server_mode()`` resolves the on-disk store.
    A flag left unset (``None``) is not written, so an operator-set env
    var of the same name survives untouched.

    Args:
        watch: Tri-state watcher toggle; ``None`` leaves it unset.
        watch_debounce_ms: Debounce override in ms; ``None`` leaves it unset.
        watch_cooldown_s: Cooldown override in s; ``None`` leaves it unset.
        qdrant: Tri-state qdrant server-mode toggle; ``None`` leaves it
            unset.
        local_only: Tri-state local-backend opt-out; ``None`` leaves it
            unset so an operator-set ``VAULTSPEC_RAG_LOCAL_ONLY`` survives.

    Returns:
        The child-process environment mapping.
    """
    # Strip VAULTSPEC_RAG_ROOT from the daemon env - the HTTP service is
    # multi-tenant and must not fall back to a baked-in project root.
    # Case-insensitive compare: Windows os.environ stores original case
    # but is case-insensitive for lookups.
    _excluded = str(EnvVar.RAG_ROOT).upper()
    env = {k: v for k, v in os.environ.items() if k.upper() != _excluded}
    if watch is not None:
        env[EnvVar.WATCH_ENABLED.value] = "1" if watch else "0"
    if watch_debounce_ms is not None:
        env[EnvVar.WATCH_DEBOUNCE_MS.value] = str(watch_debounce_ms)
    if watch_cooldown_s is not None:
        env[EnvVar.WATCH_COOLDOWN_S.value] = str(watch_cooldown_s)
    if qdrant is not None:
        env[EnvVar.QDRANT_SERVER.value] = "1" if qdrant else "0"
    if local_only is not None:
        env[EnvVar.LOCAL_ONLY.value] = "1" if local_only else "0"
    return env


# Windows process-creation flags used when spawning the detached daemon.
# Defined as named constants so tests can assert their values without
# hard-coding magic numbers.
_WIN_CREATE_NEW_PROCESS_GROUP = 0x00000200
_WIN_CREATE_NO_WINDOW = 0x08000000
# Detaches the new process from the launching shell's Windows Job Object so the
# daemon survives when the parent shell exits.  Some restricted Job Objects deny
# breakaway; _spawn_service then attempts a console-detached spawn and, if that
# is also refused, fails loudly rather than silently producing a shell-bound
# daemon doomed to die with the launching shell.
_WIN_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
# Detaches the child from the parent's console.  Combined with a new process
# group this is the best-effort fallback when breakaway is denied: it severs the
# console association and the CTRL_BREAK group so an interactive shell exit is
# less likely to reach the daemon, though a Job Object configured to kill on
# close can still terminate it (which is why breakaway denial fails loudly).
_WIN_DETACHED_PROCESS = 0x00000008


def _resolve_daemon_interpreter() -> str:
    """Return the venv interpreter path for spawning the daemon.

    Uses ``sysconfig.get_path("scripts")`` to locate the venv Scripts/bin
    directory and returns the ``python.exe`` (win32) or ``python`` binary
    inside it.  Falls back to ``sys.executable`` when the venv scripts
    directory cannot be determined or the expected binary is absent — this
    keeps the spawn working in editable installs and bare-interpreter
    invocations at the cost of not guaranteeing the venv Python.

    Why not ``sys.executable`` directly: on Windows, ``sys.executable``
    can resolve to the system launcher (Python 3.14) rather than the
    project-pinned venv (3.13), triggering a ``protobuf`` metaclass
    ``TypeError`` on daemon import.
    """
    scripts = sysconfig.get_path("scripts")
    if scripts:
        name = "python.exe" if sys.platform == "win32" else "python"
        candidate = Path(scripts) / name
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _spawn_service(
    port: int,
    log_path: Path,
    watch: bool | None = None,
    watch_debounce_ms: int | None = None,
    watch_cooldown_s: float | None = None,
    qdrant: bool | None = None,
    local_only: bool | None = None,
) -> int:
    """Spawn the RAG service as a detached background process.

    Args:
        port: TCP port for the HTTP server.
        log_path: File path for stdout/stderr redirection.
        watch: Optional watcher enable/disable forwarded to the daemon env.
        watch_debounce_ms: Optional debounce override forwarded to the env.
        watch_cooldown_s: Optional cooldown override forwarded to the env.
        qdrant: Optional qdrant server-mode toggle forwarded to the env.
        local_only: Optional local-backend opt-out forwarded to the env.

    Returns:
        PID of the spawned process.

    """
    interpreter = _resolve_daemon_interpreter()
    cmd = [interpreter, "-m", "vaultspec_rag.server", "--port", str(port)]
    env = _service_child_env(
        watch=watch,
        watch_debounce_ms=watch_debounce_ms,
        watch_cooldown_s=watch_cooldown_s,
        qdrant=qdrant,
        local_only=local_only,
    )
    # Owner-only log, refusing a pre-planted symlink at the path where the
    # platform offers O_NOFOLLOW (local log-tamper / redirect hardening).
    _log_flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    log_fd = os.open(log_path, _log_flags, 0o600)
    try:
        if sys.platform == "win32":
            proc = _spawn_windows(cmd, env, log_fd)
        else:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
    finally:
        os.close(log_fd)  # child has the fd now (or the spawn failed)
    return proc.pid


def _spawn_windows(
    cmd: list[str],
    env: dict[str, str],
    log_fd: int,
) -> subprocess.Popen[bytes]:
    """Spawn the daemon on Windows, detaching it from the launching shell.

    The preferred path breaks the daemon out of the parent's Job Object with
    ``CREATE_BREAKAWAY_FROM_JOB`` so it survives the launching shell's exit.
    When the parent Job Object denies breakaway (common in terminal emulators,
    VS Code integrated terminals, and CI runners), this attempts a
    console-detached spawn (``DETACHED_PROCESS`` + a new process group) as a
    best-effort survival path. If that too is refused, it raises
    :class:`DaemonBreakawayError` rather than silently spawning a daemon bound
    to the shell's Job Object - the previous behaviour, which produced the
    flapping daemon of issue #204 (it died minutes later when the shell closed).
    """
    flags_with_breakaway = (
        _WIN_CREATE_NEW_PROCESS_GROUP
        | _WIN_CREATE_NO_WINDOW
        | _WIN_CREATE_BREAKAWAY_FROM_JOB
    )
    try:
        return subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=flags_with_breakaway,
        )
    except OSError as breakaway_exc:
        logger.warning(
            "CREATE_BREAKAWAY_FROM_JOB denied by parent Job Object (%s); "
            "attempting a console-detached spawn so the daemon is not "
            "bound to the launching shell",
            breakaway_exc,
        )

    flags_detached = (
        _WIN_CREATE_NEW_PROCESS_GROUP | _WIN_CREATE_NO_WINDOW | _WIN_DETACHED_PROCESS
    )
    try:
        return subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=flags_detached,
        )
    except OSError as detached_exc:
        # Neither breakaway nor console detachment is permitted. Spawning
        # without them would leave the daemon a member of the parent shell's
        # Job Object, doomed to die when the shell exits. Fail loudly so the
        # operator can start the daemon from an environment that permits it
        # (or via a service manager) instead of seeing a daemon that flaps.
        raise DaemonBreakawayError(
            "Could not detach the background service from the launching shell: "
            "the parent Job Object denied both CREATE_BREAKAWAY_FROM_JOB and a "
            "console-detached spawn. A daemon started here would be killed when "
            "this shell exits. Start the service from a plain console or a "
            "service manager that permits process breakaway."
        ) from detached_exc


def _terminate_pid(pid: int) -> None:
    """Send a termination signal to a process.

    On Windows sends ``CTRL_BREAK_EVENT`` for graceful uvicorn
    shutdown, then force-kills if the process survives. On Unix
    sends ``SIGTERM``, falling back to ``SIGKILL``.

    Args:
        pid: Process ID to terminate.

    """
    if sys.platform == "win32":
        with contextlib.suppress(OSError):
            os.kill(pid, signal.CTRL_BREAK_EVENT)
    else:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
    # Allow graceful drain before force-killing
    time.sleep(2)
    if _cli._is_pid_alive(pid):
        with contextlib.suppress(OSError):
            if sys.platform == "win32":
                os.kill(pid, signal.SIGTERM)  # TerminateProcess on Windows
            else:
                os.kill(pid, signal.SIGKILL)
