"""Supervision of the qdrant server child process.

The resident daemon spawns exactly one loopback-bound qdrant child,
configured entirely through ``QDRANT__*`` environment variables, polls
its readiness endpoint with exponential backoff, and terminates it
last among data components on shutdown. On Windows the child is
assigned to a kill-on-close Job Object so a hard daemon death (kill,
OOM, crash before atexit) can never orphan a qdrant process - the OS
closes the job handle with the daemon and tears the child down with
it.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, cast

from ._constants import QDRANT_SERVER_VERSION, QdrantRuntimeState

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "QdrantSupervisor",
    "active_supervisor",
    "runtime_state",
    "set_active_supervisor",
    "start_supervised_from_config",
]

_READY_TIMEOUT_SECONDS = 60.0
_STOP_TIMEOUT_SECONDS = 10.0

# Windows process-creation flags for the qdrant child. Unlike the
# daemon spawn, the child must NOT break away from the daemon's Job
# Object - membership is exactly the no-orphan guarantee.
_WIN_CREATE_NEW_PROCESS_GROUP = 0x00000200
_WIN_CREATE_NO_WINDOW = 0x08000000

# Job Object constants (WinBase.h / winnt.h).
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


def _win_kill_on_close_job() -> object | None:
    """Create a Windows Job Object configured to kill members on close.

    Returns:
        The job handle (kept alive by the caller for the daemon's
        lifetime), or ``None`` off-Windows or when creation fails.
    """
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        logger.warning("CreateJobObjectW failed; qdrant orphan guard disabled")
        return None
    info = _ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        logger.warning("SetInformationJobObject failed; qdrant orphan guard disabled")
        kernel32.CloseHandle(job)
        return None
    return job


def _win_assign_to_job(job: object, proc: subprocess.Popen[bytes]) -> bool:
    """Assign *proc* to *job*; True on success (logged otherwise)."""
    if sys.platform != "win32" or job is None:
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    # Popen exposes the raw Windows process handle as ``_handle``;
    # typeshed does not declare it, hence the Any cast.
    handle = int(cast("Any", proc)._handle)
    if kernel32.AssignProcessToJobObject(job, handle):
        return True
    logger.warning(
        "AssignProcessToJobObject failed for qdrant pid %d; orphan guard "
        "disabled for this child",
        proc.pid,
    )
    return False


class QdrantSupervisor:
    """Owns one loopback-bound qdrant child process.

    Attributes:
        binary: The executable to spawn.
        http_port: REST listener port (loopback).
        grpc_port: gRPC listener port (loopback); defaults to one
            below ``http_port`` so the pair never collides with the
            RAG service's own port one above.
        storage_dir: Shared multi-root storage directory.
        log_path: File qdrant stdout/stderr is appended to.
        restart_count: Heartbeat-initiated restarts performed so far.
    """

    def __init__(
        self,
        binary: Path,
        *,
        http_port: int,
        storage_dir: Path,
        grpc_port: int | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.binary = binary
        self.http_port = int(http_port)
        self.grpc_port = int(grpc_port) if grpc_port is not None else self.http_port - 1
        self.storage_dir = storage_dir
        self.log_path = log_path
        self.restart_count = 0
        self._proc: subprocess.Popen[bytes] | None = None
        self._job_handle: object | None = None

    @property
    def url(self) -> str:
        """The REST URL stores connect to."""
        return f"http://127.0.0.1:{self.http_port}"

    @property
    def pid(self) -> int | None:
        """PID of the running child, or ``None``."""
        return self._proc.pid if self._proc is not None else None

    def _child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "QDRANT__SERVICE__HOST": "127.0.0.1",
                "QDRANT__SERVICE__HTTP_PORT": str(self.http_port),
                "QDRANT__SERVICE__GRPC_PORT": str(self.grpc_port),
                "QDRANT__STORAGE__STORAGE_PATH": str(self.storage_dir),
                "QDRANT__STORAGE__SNAPSHOTS_PATH": str(
                    self.storage_dir.parent / "snapshots"
                ),
                "QDRANT__TELEMETRY_DISABLED": "true",
            }
        )
        return env

    def spawn(self) -> None:
        """Start the qdrant child (without waiting for readiness).

        Raises:
            RuntimeError: If a child is already running.
            OSError: If the spawn itself fails.
        """
        if self.is_alive():
            raise RuntimeError(f"qdrant child pid={self.pid} is already running")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        (self.storage_dir.parent / "snapshots").mkdir(parents=True, exist_ok=True)

        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            log_fd = os.open(
                self.log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o666
            )
        else:
            log_fd = os.open(os.devnull, os.O_WRONLY)

        try:
            if sys.platform == "win32":
                self._proc = subprocess.Popen(
                    [str(self.binary)],
                    stdin=subprocess.DEVNULL,
                    stdout=log_fd,
                    stderr=subprocess.STDOUT,
                    env=self._child_env(),
                    creationflags=(
                        _WIN_CREATE_NEW_PROCESS_GROUP | _WIN_CREATE_NO_WINDOW
                    ),
                )
                if self._job_handle is None:
                    self._job_handle = _win_kill_on_close_job()
                if self._job_handle is not None:
                    _win_assign_to_job(self._job_handle, self._proc)
            else:
                self._proc = subprocess.Popen(
                    [str(self.binary)],
                    stdin=subprocess.DEVNULL,
                    stdout=log_fd,
                    stderr=subprocess.STDOUT,
                    env=self._child_env(),
                    start_new_session=True,
                )
        finally:
            os.close(log_fd)
        logger.info(
            "qdrant child spawned: pid=%d http=%d grpc=%d storage=%s",
            self._proc.pid,
            self.http_port,
            self.grpc_port,
            self.storage_dir,
        )

    def _ready_probe(self) -> bool:
        url = f"{self.url}/readyz"
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                return int(resp.status) == 200
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.debug("qdrant readyz probe failed: %s", exc)
            return False

    def wait_ready(self, timeout: float = _READY_TIMEOUT_SECONDS) -> bool:
        """Poll ``/readyz`` with backoff until ready or *timeout*.

        Returns:
            True once the server answers ready; False on timeout or
            child death (both logged).
        """
        deadline = time.monotonic() + timeout
        delay = 0.1
        while time.monotonic() < deadline:
            if not self.is_alive():
                logger.error("qdrant child died during startup; see %s", self.log_path)
                return False
            if self._ready_probe():
                return True
            time.sleep(delay)
            delay = min(delay * 2, 2.0)
        logger.error("qdrant child pid=%s not ready after %.0fs", self.pid, timeout)
        return False

    def start(self, timeout: float = _READY_TIMEOUT_SECONDS) -> None:
        """Spawn the child and wait for readiness.

        Raises:
            RuntimeError: If the server does not become ready in time
                (the child is terminated before raising).
        """
        self.spawn()
        if not self.wait_ready(timeout):
            self.stop()
            raise RuntimeError(
                f"qdrant server on port {self.http_port} failed to become "
                f"ready within {timeout:.0f}s; see {self.log_path}"
            )

    def restart(self, timeout: float = _READY_TIMEOUT_SECONDS) -> bool:
        """One supervised restart attempt; increments the counter.

        Returns:
            True when the restarted child reports ready.
        """
        self.restart_count += 1
        self.stop()
        try:
            self.spawn()
        except OSError:
            logger.exception("qdrant restart spawn failed")
            return False
        return self.wait_ready(timeout)

    def is_alive(self) -> bool:
        """True while the child process is running."""
        return self._proc is not None and self._proc.poll() is None

    def stop(self, timeout: float = _STOP_TIMEOUT_SECONDS) -> None:
        """Terminate the child gracefully, force-killing on timeout.

        Idempotent; safe to call with no child running.
        """
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            try:
                if sys.platform == "win32":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGTERM)
            except OSError as exc:
                logger.debug("qdrant terminate signal failed: %s", exc)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "qdrant pid=%d did not exit in %.0fs; killing",
                    proc.pid,
                    timeout,
                )
                proc.kill()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    logger.error("qdrant pid=%d survived kill", proc.pid)
        logger.info("qdrant child pid=%d stopped", proc.pid)
        self._proc = None

    def state(self) -> QdrantRuntimeState:
        """Service-domain snapshot for operability surfaces."""
        return QdrantRuntimeState(
            mode="server",
            url=self.url,
            pid=self.pid,
            alive=self.is_alive(),
            port=self.http_port,
            version=QDRANT_SERVER_VERSION,
            restarts=self.restart_count,
        )

    def server_version(self) -> str:
        """Read the running server's reported version from its root route.

        Returns:
            The version string, or ``""`` when unreachable.
        """
        try:
            with urllib.request.urlopen(self.url, timeout=2.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return str(payload.get("version", ""))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.debug("qdrant version probe failed: %s", exc)
            return ""


def start_supervised_from_config() -> QdrantSupervisor:
    """Resolve, verify, spawn, and ready-wait the qdrant child per config.

    Resolution follows the env-var > provisioned > PATH order. A
    provisioned binary is re-hashed against its manifest digest before
    execution so a tampered managed dir never runs. The started
    supervisor is installed as the process-wide active supervisor.

    Returns:
        The running, ready supervisor.

    Raises:
        RuntimeError: When no binary is resolvable (the message names
            the exact install command), when the provisioned binary
            fails its pre-execution hash check, or when the server
            does not become ready.
    """
    from pathlib import Path

    from ..config import get_config
    from ._provision import file_sha256
    from ._resolve import resolve_binary

    cfg = get_config()
    resolved = resolve_binary()
    if resolved is None:
        raise RuntimeError(
            "qdrant server mode is enabled but no server binary is "
            "available. Run: vaultspec-rag server qdrant install"
        )
    if resolved.source == "provisioned" and resolved.sha256:
        actual = file_sha256(resolved.path)
        if actual.lower() != resolved.sha256.lower():
            raise RuntimeError(
                f"Provisioned qdrant binary at {resolved.path} does not "
                "match its manifest digest; refusing to execute. Re-run: "
                "vaultspec-rag server qdrant install --upgrade"
            )

    storage_dir = Path(str(cfg.qdrant_storage_dir)).expanduser()
    log_path = Path(str(cfg.status_dir)).expanduser() / "qdrant.log"
    supervisor = QdrantSupervisor(
        resolved.path,
        http_port=int(cfg.qdrant_port),
        storage_dir=storage_dir,
        log_path=log_path,
    )
    logger.info("Starting qdrant server (%s binary %s)", resolved.source, resolved.path)
    supervisor.start()
    set_active_supervisor(supervisor)
    return supervisor


# The daemon's active supervisor. Reassigned by the service lifespan;
# read by the health handler, the heartbeat loop, and the
# service-state surface so every adapter reports the same qdrant
# state (service domain owns operability).
_active_supervisor: QdrantSupervisor | None = None


def set_active_supervisor(supervisor: QdrantSupervisor | None) -> None:
    """Install (or clear) the process-wide active supervisor."""
    global _active_supervisor
    _active_supervisor = supervisor


def active_supervisor() -> QdrantSupervisor | None:
    """Return the process-wide active supervisor, if any."""
    return _active_supervisor


def runtime_state() -> QdrantRuntimeState:
    """Snapshot the qdrant runtime for the current process.

    A process supervising a child reports ``server`` mode with live
    child telemetry; a process pointed at an external server via the
    URL knob reports ``remote``; everything else is ``local``.
    """
    supervisor = _active_supervisor
    if supervisor is not None:
        return supervisor.state()

    from ..config import get_config

    cfg = get_config()
    url = str(cfg.qdrant_url or "")
    if url:
        return QdrantRuntimeState(mode="remote", url=url)
    return QdrantRuntimeState(mode="local")
