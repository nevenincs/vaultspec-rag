"""Daemon-owned local monitor process and verified orphan cleanup."""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import signal
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from ._atomic_write import write_json_atomically
from ._ports import next_available_port
from ._process_probe import (
    pid_alive,
    pid_matches_start_time,
    pid_start_time,
    send_signal,
    wait_for_exit,
)
from ._program_lookup import Where, find_program
from .config._settings import managed_status_dir
from .config._types import EnvVar
from .serviceclient._discovery import status_write_lock

logger = logging.getLogger(__name__)
_READY_PREFIX = "vaultspec.monitor.ready "


def _resolve_monitor_executable() -> Path:
    override = os.environ.get(EnvVar.MONITOR_BINARY.value)
    if override:
        executable = Path(override).expanduser()
        if not executable.is_absolute():
            raise RuntimeError("The monitor executable override must be absolute.")
    else:
        # The monitor ships in the same archive as this package's commands and
        # is otherwise put on PATH by the operator. It is started on every
        # service start, so it is never looked for in the directory that start
        # was typed in.
        installed = find_program(
            "vaultspec-rag-monitor", Where.INSTALLATION, Where.SEARCH_PATH
        )
        if installed is None:
            raise RuntimeError(
                "The compiled vaultspec-rag-monitor executable is required. "
                "Install it alongside vaultspec-rag or set "
                "VAULTSPEC_RAG_MONITOR_BINARY to its absolute path."
            )
        executable = Path(installed).resolve()
    if not executable.is_file():
        raise RuntimeError(f"The compiled monitor executable is missing: {executable}")
    return executable


def _access_link_port(link: str) -> int:
    """Return the port of a loopback link carrying a capability, else zero.

    A monitor that reports a bare port enforces no caller credential, so its
    line must never be accepted as readiness.
    """
    try:
        parts = urlsplit(link)
        port = parts.port
    except ValueError:
        return 0
    if (
        parts.scheme != "http"
        or parts.hostname != "127.0.0.1"
        or port is None
        or not parts.fragment
    ):
        return 0
    return port


@dataclass(frozen=True, slots=True)
class MonitorIdentity:
    """Incarnation witnesses retained even if daemon discovery is removed."""

    owner_pid: int
    owner_start_time: float
    pid: int
    start_time: float
    port: int = 0


def _identity_path() -> Path:
    path = managed_status_dir() / "monitor.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_identity(path: Path) -> MonitorIdentity | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(data, dict):
        raise RuntimeError("The recorded monitor identity is invalid.")
    fields = cast("dict[str, object]", data)
    for name in ("owner_pid", "pid", "port"):
        if type(fields.get(name)) is not int:
            raise RuntimeError("The recorded monitor identity is invalid.")
    for name in ("owner_start_time", "start_time"):
        value = fields.get(name)
        if (
            type(value) not in (float, int)
            or not math.isfinite(cast("float", value))
            or float(cast("float", value)) <= 0
        ):
            raise RuntimeError("The recorded monitor incarnation is invalid.")
    identity = MonitorIdentity(
        owner_pid=cast("int", fields["owner_pid"]),
        owner_start_time=float(cast("float", fields["owner_start_time"])),
        pid=cast("int", fields["pid"]),
        start_time=float(cast("float", fields["start_time"])),
        port=cast("int", fields["port"]),
    )
    if identity.owner_pid <= 0 or identity.pid <= 0 or not 0 <= identity.port <= 65535:
        raise RuntimeError("The recorded monitor identity is invalid.")
    return identity


def stop_recorded_monitor() -> bool:
    """Reap a monitor whose owner is dead, retaining unverifiable identities."""
    path = _identity_path()
    with status_write_lock(path):
        identity = _read_identity(path)
        if identity is None:
            return True
        if pid_alive(identity.owner_pid):
            owner_start = pid_start_time(identity.owner_pid)
            if owner_start <= 0:
                raise RuntimeError("Cannot verify the recorded monitor owner.")
            if owner_start == identity.owner_start_time:
                return True
        if pid_alive(identity.pid):
            if not pid_matches_start_time(identity.pid, identity.start_time):
                raise RuntimeError("Cannot verify the recorded monitor process.")
            send_signal(identity.pid, signal.SIGTERM)
            if not wait_for_exit(identity.pid, timeout=5):
                if not pid_matches_start_time(identity.pid, identity.start_time):
                    raise RuntimeError("Cannot verify the surviving monitor process.")
                send_signal(
                    identity.pid,
                    signal.SIGTERM if sys.platform == "win32" else signal.SIGKILL,
                )
                if not wait_for_exit(identity.pid, timeout=5):
                    return False
        path.unlink(missing_ok=True)
    return True


class MonitorProcess:
    """Own the compiled monitor and publish the port it actually bound."""

    def __init__(self, backend_port: int) -> None:
        self.backend_port = backend_port
        self.process: subprocess.Popen[str] | None = None
        self.identity: MonitorIdentity | None = None
        self.access: str | None = None
        self.reader: threading.Thread | None = None

    def discovery_fields(self) -> dict[str, object]:
        identity = self.identity
        if identity is None or self.process is None or self.process.poll() is not None:
            return {}
        fields: dict[str, object] = {
            "monitor_port": identity.port,
            "monitor_pid": identity.pid,
            "monitor_start_time": identity.start_time,
        }
        if self.access is not None:
            fields["monitor_url"] = self.access
        return fields

    def start(self, *, timeout: float = 30) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        if self.process is not None:
            self.stop()
        if not stop_recorded_monitor():
            raise RuntimeError("The previous monitor process did not stop.")
        if _identity_path().exists():
            raise RuntimeError("A live monitor owner is already recorded.")
        starting_port = next_available_port(self.backend_port + 1)
        executable = _resolve_monitor_executable()
        environment = dict(os.environ)
        environment[EnvVar.PORT.value] = str(self.backend_port)
        environment[EnvVar.STATUS_DIR.value] = str(managed_status_dir())
        environment[EnvVar.MONITOR_PYTHON.value] = sys.executable
        process = subprocess.Popen(
            [str(executable), "--managed", "--port", str(starting_port)],
            cwd=managed_status_dir(),
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.process = process
        try:
            owner_start = pid_start_time(os.getpid())
            child_start = pid_start_time(process.pid)
            if owner_start <= 0:
                raise RuntimeError("Cannot record the monitor process incarnation.")
            if child_start <= 0:
                raise RuntimeError("The monitor exited before becoming ready.")
            self.identity = MonitorIdentity(
                os.getpid(), owner_start, process.pid, child_start
            )
            self._publish_identity()
            ready: queue.Queue[str] = queue.Queue()
            self.reader = threading.Thread(
                target=self._read_output,
                args=(ready,),
                name="monitor-output",
                daemon=True,
            )
            self.reader.start()
            try:
                access = ready.get(timeout=timeout)
            except queue.Empty as exc:
                raise RuntimeError("The monitor did not become ready in time.") from exc
            if not access or process.poll() is not None:
                raise RuntimeError("The monitor exited before becoming ready.")
            port = _access_link_port(access)
            if port <= self.backend_port:
                raise RuntimeError("The monitor reported no usable access link.")
            self.identity = replace(self.identity, port=port)
            self.access = access
            self._publish_identity()
        except BaseException:
            if not self.stop():
                logger.error("The monitor survived startup rollback")
            raise

    def _publish_identity(self) -> None:
        if self.identity is None:
            return
        path = _identity_path()
        with status_write_lock(path):
            write_json_atomically(path, asdict(self.identity))

    def _read_output(self, ready: queue.Queue[str]) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                # The readiness line carries the capability and is never logged.
                if line.startswith(_READY_PREFIX):
                    ready.put(line.removeprefix(_READY_PREFIX).strip())
                else:
                    logger.info("monitor: %s", line.rstrip()[:4096])
        finally:
            ready.put("")

    def stop(self) -> bool:
        process = self.process
        if process is None:
            return True
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                return False
        if self.reader is not None:
            self.reader.join(timeout=1)
        if process.stdout is not None:
            process.stdout.close()
        path = _identity_path()
        try:
            with status_write_lock(path):
                if _read_identity(path) == self.identity:
                    path.unlink(missing_ok=True)
        except TimeoutError as exc:
            # The monitor has exited; only its record could not be withdrawn,
            # because another process holds the status lock. What is left
            # names a dead process, and the next start or stop reaps exactly
            # that, so the stop that was asked for has still happened.
            logger.warning(
                "monitor stopped; its identity record is left for the next "
                "start or stop to clear: %s",
                exc,
            )
        self.identity = None
        self.access = None
        self.process = None
        return True
