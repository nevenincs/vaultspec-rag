"""Process and port helpers for the background service.

Liveness (``_is_pid_alive``), identity (``_is_our_service`` via a
``/health`` service-token round-trip through the service client, with an
executable-name fallback), port probes, heartbeat staleness, the
detached-daemon spawn, and graceful termination all live here. Helpers that
tests monkeypatch on ``vaultspec_rag.cli`` (e.g. ``_is_pid_alive``) are
referenced through the package namespace at call time so the substitution is
observed.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import sysconfig
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import vaultspec_rag.cli as _cli

from .._machine_lock import (
    acquire_machine_lock,
    machine_lock_live_holder,
    machine_lock_path,
    release_machine_lock,
)
from ..config import EnvVar
from ..serviceclient._transport import _try_http_health
from ._core import logger

if TYPE_CHECKING:
    from ..qdrant_runtime._resolve import QdrantIdentity

__all__ = [
    "_DEFAULT_GRACEFUL_DRAIN_SECONDS",
    "_HEARTBEAT_STALENESS_SECONDS",
    "DaemonBreakawayError",
    "_heartbeat_age_seconds",
    "_is_our_service",
    "_is_pid_alive",
    "_port_is_available",
    "_port_is_listening",
    "_probe_daemon_cuda",
    "_resolve_daemon_interpreter",
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
        probe = _try_http_health(port)
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


# Mirrored from server._HEARTBEAT_STALENESS_SECONDS - kept as a
# local constant so cli.py does not import server (which would
# pull in FastMCP + heavy deps at CLI startup time). Bump both in
# lockstep if the contract changes.
_HEARTBEAT_STALENESS_SECONDS = 60

# Post-signal drain bound before a forced kill. The short default serves
# callers that only need the process gone; an operator stop overrides it so the
# daemon can finish owner-authenticated discovery cleanup, which no other
# process is authorized to perform.
_DEFAULT_GRACEFUL_DRAIN_SECONDS = 2.0

# Per-probe budget for a single OS-inspection call inside the late-spawn
# cleanup. A psutil read (a process's create-time, or a full process-table
# scan reading each cmdline) can stall on Windows for a protected or wedged
# process, and the enclosing deadline loop cannot interrupt a call already
# blocked mid-iteration - only a bound on the call itself can. Kept well under
# the whole-cleanup timeout so a healthy probe always completes within it.
_PROBE_BUDGET_SECONDS = 1.0


def _port_is_listening(port: int) -> bool:
    """Return True when ``127.0.0.1:port`` accepts a TCP connection.

    Cheaper than a health probe (no HTTP round-trip, no JSON
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


def _service_child_env(
    watch: bool | None = None,
    watch_debounce_ms: int | None = None,
    watch_cooldown_s: float | None = None,
    qdrant: bool | None = None,
    local_only: bool | None = None,
    preprocess_mode: Literal["off"] | None = None,
) -> dict[str, str]:
    """Build the environment for the detached daemon process.

    The daemon inherits configuration only through the environment (it
    parses no argv beyond ``--port``), so watcher flags passed to
    ``service start`` are translated into ``VAULTSPEC_RAG_WATCH*`` here,
    the qdrant server-mode flag into ``VAULTSPEC_RAG_QDRANT_SERVER``, the
    local-only opt-out into ``VAULTSPEC_RAG_LOCAL_ONLY`` so the daemon's
    ``effective_server_mode()`` resolves the on-disk store, and the
    preprocess kill switch into the env var the daemon's ``preprocess_mode``
    property reads. A flag left unset (``None``) is not written, so an
    operator-set env var of the same name survives untouched.

    Args:
        watch: Tri-state watcher toggle; ``None`` leaves it unset.
        watch_debounce_ms: Debounce override in ms; ``None`` leaves it unset.
        watch_cooldown_s: Cooldown override in s; ``None`` leaves it unset.
        qdrant: Tri-state qdrant server-mode toggle; ``None`` leaves it
            unset.
        local_only: Tri-state local-backend opt-out; ``None`` leaves it
            unset so an operator-set ``VAULTSPEC_RAG_LOCAL_ONLY`` survives.
        preprocess_mode: ``"off"`` forwards ``VAULTSPEC_RAG_PREPROCESS=off``.
            ``None`` leaves it unset so an operator-set preprocess env
            survives.

    Returns:
        The child-process environment mapping.
    """
    # Strip VAULTSPEC_RAG_ROOT from the daemon env - the HTTP service is
    # multi-tenant and must not fall back to a baked-in project root.
    # Case-insensitive compare: Windows os.environ stores original case
    # but is case-insensitive for lookups.
    _excluded = str(EnvVar.RAG_ROOT).upper()
    env = {k: v for k, v in os.environ.items() if k.upper() != _excluded}
    # Mark this as the resident daemon so code running inside the service can
    # distinguish itself from an interactive in-process CLI, independent of the
    # storage backend.
    env[EnvVar.SERVICE_DAEMON.value] = "1"
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
    if preprocess_mode == "off":
        env[EnvVar.PREPROCESS.value] = "off"
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


def _probe_daemon_cuda(
    interpreter: str, timeout: float = 60.0
) -> tuple[bool, str] | None:
    """Probe the resolved daemon interpreter for a working CUDA torch.

    The service runs in ``interpreter`` (it inherits the launcher's env and does
    not provision its own python), and it is GPU-only, so a pre-flight here turns
    a background model-load crash into a fast, legible refusal. Runs the probe in
    a subprocess so the torch-free CLI never imports torch itself.

    Returns ``None`` when the interpreter has a CUDA-capable torch (the service
    can run). Otherwise returns ``(blocking, reason)``:

    - ``blocking=True`` for definitive misconfigurations - torch absent, a
      CPU-only wheel, no visible GPU, or the interpreter missing - where spawning
      would only produce a doomed daemon;
    - ``blocking=False`` for ambiguous outcomes (the probe timed out or failed
      opaquely) where the caller should warn and proceed rather than block on an
      inconclusive signal, leaving the spawn-and-detect path as the backstop.
    """
    probe = (
        "import sys\n"
        "try:\n"
        "    import torch\n"
        "except Exception:\n"
        "    sys.exit(3)\n"
        "try:\n"
        "    avail = bool(torch.cuda.is_available())\n"
        "    cuda = torch.version.cuda\n"
        "except Exception:\n"
        "    sys.exit(6)\n"
        "sys.exit(0 if avail else (5 if cuda else 4))\n"
    )
    try:
        proc = subprocess.run(
            [interpreter, "-c", probe],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return (True, f"the service interpreter does not exist: {interpreter}")
    except subprocess.TimeoutExpired:
        return (
            False,
            f"probing torch in the service interpreter timed out ({timeout:.0f}s)",
        )
    except OSError as exc:
        return (False, f"could not probe the service interpreter ({exc})")
    code = proc.returncode
    if code == 0:
        return None
    if code == 3:
        return (True, "torch is not installed in the service interpreter")
    if code == 4:
        return (True, "the service interpreter has a CPU-only torch wheel (no CUDA)")
    if code == 5:
        return (
            True,
            "torch is a CUDA build but no CUDA device is visible (driver/GPU)",
        )
    return (False, f"the torch pre-flight returned an unexpected exit code {code}")


def _spawn_service(
    port: int,
    log_path: Path,
    watch: bool | None = None,
    watch_debounce_ms: int | None = None,
    watch_cooldown_s: float | None = None,
    qdrant: bool | None = None,
    local_only: bool | None = None,
    preprocess_mode: Literal["off"] | None = None,
    timeout: float | None = None,
    cleanup_timeout: float = 15.0,
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
        preprocess_mode: Optional preprocess kill switch (``off``) forwarded
            to the env.

    Returns:
        PID of the spawned process.

    """
    from .._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="spawn the managed service process",
        targets=(log_path,),
    )
    deadline = time.monotonic() + timeout if timeout is not None else None
    launch_token = uuid.uuid4().hex
    if deadline is not None and deadline <= time.monotonic():
        raise TimeoutError("service spawn received no remaining startup budget")
    interpreter = _resolve_daemon_interpreter()
    cmd = [
        interpreter,
        "-m",
        "vaultspec_rag.server",
        "--port",
        str(port),
        "--launch-token",
        launch_token,
    ]
    env = _service_child_env(
        watch=watch,
        watch_debounce_ms=watch_debounce_ms,
        watch_cooldown_s=watch_cooldown_s,
        qdrant=qdrant,
        local_only=local_only,
        preprocess_mode=preprocess_mode,
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
    if deadline is not None and time.monotonic() >= deadline:
        launcher_start_time = _process_start_time(proc.pid)
        cleanup_error = _cleanup_late_service_spawn(
            launcher_pid=proc.pid,
            launcher_start_time=launcher_start_time,
            port=port,
            launch_token=launch_token,
            timeout=cleanup_timeout,
        )
        detail = f"; cleanup_error={cleanup_error}" if cleanup_error else ""
        raise TimeoutError(
            f"service spawn exceeded its {timeout:.3f}s remaining startup "
            f"budget{detail}"
        )
    return proc.pid


def _cleanup_late_service_spawn(
    *,
    launcher_pid: int,
    launcher_start_time: float,
    port: int,
    launch_token: str,
    timeout: float,
) -> str:
    """Find and stop a late launcher, detached daemon, and witnessed Qdrant."""
    deadline = time.monotonic() + max(0.0, timeout)
    candidates: dict[int, float] = {}
    if launcher_start_time > 0.0:
        candidates[launcher_pid] = launcher_start_time
    last_error = ""

    discovery_deadline = min(
        deadline,
        time.monotonic() + min(2.0, max(0.0, timeout * 0.5)),
    )
    while time.monotonic() < discovery_deadline:
        discovered, last_error = _discover_late_service_pids(
            port=port,
            launch_token=launch_token,
            budget=discovery_deadline - time.monotonic(),
        )
        candidates.update(discovered)
        if any(pid != launcher_pid for pid in candidates):
            break
        time.sleep(min(0.02, max(0.0, discovery_deadline - time.monotonic())))

    for candidate in sorted(candidates, key=lambda pid: pid == launcher_pid):
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            break
        if _pid_matches_start_time(candidate, candidates[candidate]):
            # Arbitrary discovered pid, not a known process-group leader: a
            # Windows CTRL_BREAK to it is unsafe (see _terminate_pid).
            _terminate_pid(candidate, timeout=remaining, console_group_signal=False)

    while time.monotonic() < deadline:
        discovered, last_error = _discover_late_service_pids(
            port=port,
            launch_token=launch_token,
            budget=deadline - time.monotonic(),
        )
        candidates.update(discovered)
        live = [
            pid
            for pid, start_time in candidates.items()
            if _pid_matches_start_time(pid, start_time)
        ]
        if not live:
            return ""
        for candidate in sorted(live, key=lambda pid: pid == launcher_pid):
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                break
            _terminate_pid(candidate, timeout=remaining, console_group_signal=False)
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
    survivors = sorted(
        pid
        for pid, start_time in candidates.items()
        if _pid_matches_start_time(pid, start_time)
    )
    if survivors:
        detail = f"late service processes survived: {survivors}; {last_error}"
        return detail.rstrip("; ")
    return last_error


def _discover_late_service_pids(
    *,
    port: int,
    launch_token: str,
    budget: float = _PROBE_BUDGET_SECONDS,
) -> tuple[dict[int, float], str]:
    """Discover exact late-launch members by their unguessable argv witness.

    ``budget`` is the caller's remaining deadline, and bounds the process-table
    scan so it can never outrun that deadline. A scan that exceeds it yields no
    candidates and a legible reason - the launcher itself is always handled
    through the known-candidate path, so a slow or stalled scan degrades extra
    discovery rather than blocking the cleanup.
    """
    candidates: dict[int, float] = {}
    status = _cli._read_service_status()
    status_pid = 0
    if (
        status is not None
        and status.get("port") == port
        and status.get("launch_token") == launch_token
    ):
        raw_pid = status.get("pid")
        if isinstance(raw_pid, int) and not isinstance(raw_pid, bool) and raw_pid > 0:
            status_pid = raw_pid
    # The process-table scan reads every process's cmdline, which can stall on
    # Windows for a protected or wedged process. Run it under the caller's
    # remaining budget on a daemon thread so a single stuck read cannot block
    # the cleanup past its deadline; a timed-out scan yields no candidates and a
    # legible reason, exactly as an errored scan does.
    from ..qdrant_runtime._resolve import _bounded_call

    scanned = _bounded_call(
        lambda: _scan_witness_pids(port=port, launch_token=launch_token),
        timeout=max(0.0, budget),
        fallback=_SCAN_TIMED_OUT,
        label="late-spawn-scan",
    )
    if scanned == _SCAN_TIMED_OUT:
        return candidates, "late-service process scan exceeded its probe budget"
    if isinstance(scanned, str):
        return candidates, scanned
    candidates.update(scanned)
    if status_pid and status_pid not in candidates:
        return (
            candidates,
            "matching launch-token status pid did not carry the same "
            "launch-token command witness",
        )
    return candidates, ""


#: Sentinel distinguishing a scan that ran out of budget from one that
#: legitimately found no witnesses; never a real error string.
_SCAN_TIMED_OUT = "__late_spawn_scan_timed_out__"


def _scan_witness_pids(*, port: int, launch_token: str) -> dict[int, float] | str:
    """Return witness pids by argv, or an error string. Runs under a budget."""
    import psutil

    found: dict[int, float] = {}
    try:
        for process in psutil.process_iter(["pid", "cmdline", "create_time"]):
            info = cast("dict[str, object]", process.info)
            created = info.get("create_time")
            if (
                not isinstance(created, int | float)
                or created <= 0.0
                or not _is_service_command(
                    info.get("cmdline"),
                    port,
                    launch_token=launch_token,
                )
            ):
                continue
            raw_pid = info.get("pid")
            if isinstance(raw_pid, int) and not isinstance(raw_pid, bool):
                found[raw_pid] = float(created)
    except Exception as exc:
        return f"{exc.__class__.__name__}: {exc}"
    return found


def _is_service_command(
    raw_cmdline: object,
    port: int,
    *,
    launch_token: str,
) -> bool:
    """Return whether argv carries this exact resident-server launch witness."""
    if not isinstance(raw_cmdline, list):
        return False
    argv = [str(item) for item in cast("list[object]", raw_cmdline)]
    expected = [
        "-m",
        "vaultspec_rag.server",
        "--port",
        str(port),
        "--launch-token",
        launch_token,
    ]
    return any(
        argv[index : index + len(expected)] == expected
        for index in range(len(argv) - len(expected) + 1)
    )


def _process_start_time(pid: int) -> float:
    """Return a process-incarnation witness, or zero when it is unreadable.

    Delegates to the shared, time-bounded ``pid_start_time`` rather than reading
    ``psutil`` directly: the direct read is unbounded and a stalled probe would
    block the whole late-spawn cleanup past its deadline. A read that exceeds
    the per-probe budget returns zero, which callers already treat as "cannot
    confirm this incarnation".
    """
    if pid <= 0:
        return 0.0
    from ..qdrant_runtime._resolve import pid_start_time

    return pid_start_time(pid, timeout=_PROBE_BUDGET_SECONDS)


def _pid_matches_start_time(pid: int, expected: float) -> bool:
    """Return whether *pid* is still the exact witnessed launch member."""
    if expected <= 0.0:
        return False
    current = _process_start_time(pid)
    return current > 0.0 and abs(current - expected) <= 1e-6


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


def _terminate_pid(
    pid: int,
    timeout: float = 4.0,
    *,
    graceful_drain: float = _DEFAULT_GRACEFUL_DRAIN_SECONDS,
    console_group_signal: bool = True,
) -> None:
    """Send a termination signal to a process.

    On Windows sends ``CTRL_BREAK_EVENT`` for graceful uvicorn
    shutdown, then force-kills if the process survives. On Unix
    sends ``SIGTERM``, falling back to ``SIGKILL``. Before signalling,
    captures any Qdrant child whose managed identity is pinned to this
    exact service-process incarnation. If forced daemon termination
    bypasses lifespan cleanup, the validated child is reaped explicitly;
    unrelated, attached, stale, or unverifiable Qdrant processes are never
    targeted.

    Args:
        pid: Process ID to terminate.
        timeout: Whole termination budget, including child validation,
            graceful service drain, escalation, and owned-Qdrant reap.
        graceful_drain: Upper bound on the post-signal wait before escalating
            to a forced kill. Only the daemon itself holds the machine-lock
            lease that authorizes deleting the machine discovery pointer, so a
            forced kill necessarily orphans that view. An operator-driven stop
            therefore passes a drain budget large enough for the lifespan
            ``finally`` to complete its owner cleanup; callers that only need
            the process gone keep the short default.
        console_group_signal: Whether a Windows ``CTRL_BREAK_EVENT`` is a
            legitimate graceful signal for *pid*. True only when the caller
            knows *pid* is a daemon it spawned with ``CREATE_NEW_PROCESS_GROUP``
            (the operator-driven stop). It MUST be False for an arbitrary
            discovered pid - a late-spawn cleanup target has no known process
            group, and ``GenerateConsoleCtrlEvent`` addressed to a pid that is
            not a group leader is undefined on Windows: it can block the caller
            or deliver the break to the caller's own console group instead. When
            False, Windows goes straight to a pid-targeted ``TerminateProcess``.

    """
    from .._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="signal the managed service process",
    )
    deadline = time.monotonic() + max(0.0, timeout)
    qdrant_identity = _owned_qdrant_identity(pid, deadline=deadline)
    if sys.platform == "win32":
        with contextlib.suppress(OSError):
            if console_group_signal:
                os.kill(pid, signal.CTRL_BREAK_EVENT)
            else:
                # TerminateProcess: targets this exact pid, never a console
                # group, so a stray with no known process group cannot block
                # the caller or signal it by accident.
                os.kill(pid, signal.SIGTERM)
    else:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
    # Allow graceful drain before force-killing. On POSIX this CLI is normally
    # the daemon's parent, so reap an exited child promptly instead of treating
    # its zombie record as a live process that still needs SIGKILL.
    remaining = max(0.0, deadline - time.monotonic())
    graceful_wait = min(graceful_drain, remaining / 2.0)
    if _wait_for_child_exit(pid, timeout=graceful_wait):
        _reap_owned_qdrant(qdrant_identity, deadline=deadline)
        return
    if _cli._is_pid_alive(pid):
        with contextlib.suppress(OSError):
            if sys.platform == "win32":
                os.kill(pid, signal.SIGTERM)  # TerminateProcess on Windows
            else:
                os.kill(pid, signal.SIGKILL)
        _wait_for_child_exit(
            pid,
            timeout=max(0.0, deadline - time.monotonic()),
        )
    _reap_owned_qdrant(qdrant_identity, deadline=deadline)


def _wait_for_child_exit(pid: int, *, timeout: float) -> bool:
    """Wait boundedly for process exit, reaping a POSIX child when applicable."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sys.platform != "win32":
            try:
                waited, _status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                waited = 0
            if waited == pid:
                return True
        if not _cli._is_pid_alive(pid):
            return True
        time.sleep(0.05)
    return False


def _owned_qdrant_identity(
    service_pid: int,
    *,
    deadline: float,
) -> QdrantIdentity | None:
    """Capture the exact validated managed child owned by this service."""
    from pathlib import Path

    from ..config import get_config
    from ..qdrant_runtime._constants import QDRANT_SERVER_VERSION
    from ..qdrant_runtime._resolve import (
        pid_image_is_qdrant,
        pid_listens_on_loopback_port,
        pid_matches_start_time,
        probe_qdrant_endpoint,
        read_qdrant_identity,
    )

    identity = read_qdrant_identity()
    if (
        identity is None
        or identity.owner_pid != service_pid
        or identity.owner_start_time <= 0.0
        or identity.qdrant_pid <= 0
        or identity.qdrant_start_time <= 0.0
    ):
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    if not pid_matches_start_time(
        identity.owner_pid,
        identity.owner_start_time,
        timeout=remaining,
    ):
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not pid_matches_start_time(
        identity.qdrant_pid,
        identity.qdrant_start_time,
        timeout=remaining,
    ):
        return None
    cfg = get_config()
    expected_storage = Path(str(cfg.qdrant_storage_dir)).expanduser().resolve()
    recorded_storage = Path(identity.storage_path).expanduser().resolve()
    remaining = deadline - time.monotonic()
    if (
        remaining <= 0
        or recorded_storage != expected_storage
        or identity.version != QDRANT_SERVER_VERSION
        or not pid_image_is_qdrant(identity.qdrant_pid, timeout=remaining)
    ):
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not pid_listens_on_loopback_port(
        identity.qdrant_pid, identity.http_port, timeout=remaining
    ):
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    probe = probe_qdrant_endpoint(
        identity.http_port,
        timeout=max(0.001, min(2.0, remaining / 2.0)),
    )
    if not probe.ready or probe.version != QDRANT_SERVER_VERSION:
        return None
    return identity


def _reap_owned_qdrant(
    identity: QdrantIdentity | None,
    *,
    deadline: float,
) -> None:
    """Revalidate and reap the same previously captured Qdrant incarnation."""
    if identity is None:
        return
    from pathlib import Path

    from ..config import get_config
    from ..qdrant_runtime._constants import QDRANT_SERVER_VERSION
    from ..qdrant_runtime._resolve import (
        pid_alive,
        pid_image_is_qdrant,
        pid_listens_on_loopback_port,
        pid_matches_start_time,
        probe_qdrant_endpoint,
        read_qdrant_identity,
        reap_qdrant_orphan,
    )

    qdrant_pid = identity.qdrant_pid
    if not pid_alive(qdrant_pid):
        return
    current = read_qdrant_identity()
    expected_storage = Path(str(get_config().qdrant_storage_dir)).expanduser().resolve()
    recorded_storage = Path(identity.storage_path).expanduser().resolve()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return
    if (
        current != identity
        or identity.qdrant_start_time <= 0.0
        or recorded_storage != expected_storage
        or identity.version != QDRANT_SERVER_VERSION
    ):
        return
    if not pid_matches_start_time(
        qdrant_pid,
        identity.qdrant_start_time,
        timeout=remaining,
    ):
        return
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not pid_image_is_qdrant(qdrant_pid, timeout=remaining):
        return
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not pid_listens_on_loopback_port(
        qdrant_pid,
        identity.http_port,
        timeout=remaining,
    ):
        return
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return
    probe = probe_qdrant_endpoint(
        identity.http_port,
        timeout=max(0.001, min(2.0, remaining / 2.0)),
    )
    if not probe.ready or probe.version != QDRANT_SERVER_VERSION:
        return
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return
    if not reap_qdrant_orphan(
        qdrant_pid,
        wait_seconds=remaining,
        expected_start_time=identity.qdrant_start_time,
    ):
        logger.warning(
            "validated service-owned qdrant pid %d survived forced service stop",
            qdrant_pid,
        )
