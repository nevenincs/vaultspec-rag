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
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import vaultspec_rag.cli as _cli

from ..config import EnvVar
from ._core import logger


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

        kernel32 = ctypes.windll.kernel32  # type: ignore[union-attr]
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
        # owned by us — still "alive" for liveness purposes.
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
                # Both sides reported a token — the comparison is
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

        kernel32 = ctypes.windll.kernel32  # type: ignore[union-attr]
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
        # Non-procfs systems (BSD, macOS without /proc) — fall back
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

    def redirect_request(  # type: ignore[override]
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


# Mirrored from mcp_server._HEARTBEAT_STALENESS_SECONDS — kept as a
# local constant so cli.py does not import mcp_server (which would
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
        # HTTP errors mean the server answered but unhealthy — surface
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
) -> dict[str, str]:
    """Build the environment for the detached daemon process.

    The daemon inherits configuration only through the environment (it
    parses no argv beyond ``--port``), so watcher flags passed to
    ``service start`` are translated into ``VAULTSPEC_RAG_WATCH*`` here.
    A flag left unset (``None``) is not written, so an operator-set env
    var of the same name survives untouched.

    Args:
        watch: Tri-state watcher toggle; ``None`` leaves it unset.
        watch_debounce_ms: Debounce override in ms; ``None`` leaves it unset.
        watch_cooldown_s: Cooldown override in s; ``None`` leaves it unset.

    Returns:
        The child-process environment mapping.
    """
    # Strip VAULTSPEC_RAG_ROOT from the daemon env — the HTTP service is
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
    return env


def _spawn_service(
    port: int,
    log_path: Path,
    watch: bool | None = None,
    watch_debounce_ms: int | None = None,
    watch_cooldown_s: float | None = None,
) -> int:
    """Spawn the MCP server as a detached background process.

    Args:
        port: TCP port for the HTTP server.
        log_path: File path for stdout/stderr redirection.
        watch: Optional watcher enable/disable forwarded to the daemon env.
        watch_debounce_ms: Optional debounce override forwarded to the env.
        watch_cooldown_s: Optional cooldown override forwarded to the env.

    Returns:
        PID of the spawned process.

    """
    cmd = [sys.executable, "-m", "vaultspec_rag.mcp_server", "--port", str(port)]
    env = _service_child_env(
        watch=watch,
        watch_debounce_ms=watch_debounce_ms,
        watch_cooldown_s=watch_cooldown_s,
    )
    log_fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    if sys.platform == "win32":
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=0x00000200 | 0x08000000,  # NEW_PROCESS_GROUP | NO_WINDOW
        )
    else:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    log_fh.close()  # child has the fd now
    return proc.pid


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
