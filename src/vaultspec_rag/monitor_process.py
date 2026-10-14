"""Daemon-owned local monitor process and verified orphan cleanup."""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, cast
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
from .config._settings import managed_status_dir
from .config._types import EnvVar
from .monitor_runtime._errors import MonitorError
from .monitor_runtime._launch import confirm_launch, verified_monitor
from .monitor_runtime._resolve import monitor_for_launch, resolve_monitor
from .serviceclient._discovery import status_write_lock

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)
_READY_PREFIX = "vaultspec.monitor.ready "
#: Written down the ownership pipe before a restart releases the monitor, so
#: the EOF that follows keeps it alive for the next daemon to adopt.
_HANDOFF_LINE = "vaultspec.monitor.handoff\n"
#: How long a released monitor waits for adoption. A restart provisions nothing
#: new and starts the monitor before warming any model, so a successor that has
#: not adopted by then is not coming.
HANDOFF_SECONDS = 120.0


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
    backend_port: int = 0
    executable: str = ""
    executable_sha256: str = ""
    #: Wall-clock deadline of an unadopted handoff; zero while owned.
    handoff_until: float = 0.0
    #: The access link, recorded only for the successor while a handoff is
    #: pending, in the same protected directory as service discovery.
    access: str = ""

    def handoff_pending(self) -> bool:
        return self.handoff_until > time.time()


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
    backend_port = fields.get("backend_port", 0)
    handoff_until = fields.get("handoff_until", 0.0)
    texts = [
        fields.get(name, "") for name in ("executable", "executable_sha256", "access")
    ]
    if (
        type(backend_port) is not int
        or type(handoff_until) not in (float, int)
        or not math.isfinite(cast("float", handoff_until))
        or not all(isinstance(value, str) for value in texts)
    ):
        raise RuntimeError("The recorded monitor identity is invalid.")
    executable, executable_sha256, access = cast("list[str]", texts)
    identity = MonitorIdentity(
        owner_pid=cast("int", fields["owner_pid"]),
        owner_start_time=float(cast("float", fields["owner_start_time"])),
        pid=cast("int", fields["pid"]),
        start_time=float(cast("float", fields["start_time"])),
        port=cast("int", fields["port"]),
        backend_port=backend_port,
        executable=executable,
        executable_sha256=executable_sha256,
        handoff_until=float(cast("float", handoff_until)),
        access=access,
    )
    if (
        identity.owner_pid <= 0
        or identity.pid <= 0
        or not 0 <= identity.port <= 65535
        or not 0 <= identity.backend_port <= 65535
    ):
        raise RuntimeError("The recorded monitor identity is invalid.")
    return identity


def _terminate_verified(identity: MonitorIdentity) -> bool:
    """End the recorded monitor process if it is still that incarnation."""
    if not pid_alive(identity.pid):
        return True
    if not pid_matches_start_time(identity.pid, identity.start_time):
        raise RuntimeError("Cannot verify the recorded monitor process.")
    send_signal(identity.pid, signal.SIGTERM)
    if wait_for_exit(identity.pid, timeout=5):
        return True
    if not pid_matches_start_time(identity.pid, identity.start_time):
        raise RuntimeError("Cannot verify the surviving monitor process.")
    send_signal(
        identity.pid,
        signal.SIGTERM if sys.platform == "win32" else signal.SIGKILL,
    )
    return wait_for_exit(identity.pid, timeout=5)


def stop_recorded_monitor() -> bool:
    """Reap a monitor whose owner is dead, retaining unverifiable identities.

    A monitor released by a restart outlives its owner on purpose. It is kept
    while its handoff is unexpired and the process is still that incarnation;
    after the deadline it closes itself, and anything left is reaped here.
    """
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
        if (
            identity.handoff_pending()
            and pid_alive(identity.pid)
            and pid_matches_start_time(identity.pid, identity.start_time)
        ):
            return True
        if not _terminate_verified(identity):
            return False
        path.unlink(missing_ok=True)
    return True


def recorded_monitor_exited() -> bool:
    """Whether the recorded monitor process is known to have exited.

    Read without the status lock: the record is replaced atomically, so it
    is read whole, and nothing here changes it. A caller that could not take
    the lock asks this to tell a record that merely outlived its process from
    a monitor that is still running. A live process under the recorded pid is
    never taken as gone, whatever its incarnation.
    """
    identity = _read_identity(_identity_path())
    return identity is None or not pid_alive(identity.pid)


class MonitorProcess:
    """Own the compiled monitor and publish the port it actually bound."""

    def __init__(self, backend_port: int) -> None:
        self.backend_port = backend_port
        self.process: subprocess.Popen[str] | None = None
        self.identity: MonitorIdentity | None = None
        self.access: str | None = None
        self.reader: threading.Thread | None = None
        self.handed_off = False

    def _running(self) -> bool:
        identity = self.identity
        if identity is None:
            return False
        if self.process is not None:
            return self.process.poll() is None
        return pid_alive(identity.pid)

    def discovery_fields(self) -> dict[str, object]:
        identity = self.identity
        if identity is None or self.handed_off or not self._running():
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
        if self._adopt():
            return
        if not stop_recorded_monitor():
            raise RuntimeError("The previous monitor process did not stop.")
        if _identity_path().exists():
            raise RuntimeError("A live monitor owner is already recorded.")
        starting_port = next_available_port(self.backend_port + 1)
        monitor = monitor_for_launch()
        environment = dict(os.environ)
        environment[EnvVar.PORT.value] = str(self.backend_port)
        environment[EnvVar.STATUS_DIR.value] = str(managed_status_dir())
        environment[EnvVar.MONITOR_PYTHON.value] = sys.executable
        # The file is held across the process creation and asked again
        # afterwards, so the monitor that runs is the one that was verified.
        # ``executable`` names the file itself: left to the command line, a
        # name is completed and looked for, and a sibling file runs instead.
        with verified_monitor(monitor) as held:
            process = subprocess.Popen(
                [str(monitor.path), "--managed", "--port", str(starting_port)],
                executable=held.launch_path,
                pass_fds=held.inherited,
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
            confirm_launch(monitor, held, process)
        self.process = process
        try:
            owner_start = pid_start_time(os.getpid())
            child_start = pid_start_time(process.pid)
            if owner_start <= 0:
                raise RuntimeError("Cannot record the monitor process incarnation.")
            if child_start <= 0:
                raise RuntimeError("The monitor exited before becoming ready.")
            self.identity = MonitorIdentity(
                os.getpid(),
                owner_start,
                process.pid,
                child_start,
                backend_port=self.backend_port,
                executable=str(monitor.path),
                executable_sha256=monitor.sha256,
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

    def _adopt(self) -> bool:
        """Take over a monitor a restart released, when it verifies.

        Adoption keeps the one process holding the access capability, so an
        open page survives the restart. A released monitor that does not verify
        - another port, a different executable than this release would launch,
        or a reused pid - is ended here, because the reap that follows spares an
        unexpired handoff and would leave it holding the record.
        """
        path = _identity_path()
        with status_write_lock(path):
            identity = _read_identity(path)
            if identity is None or not identity.handoff_pending():
                return False
            alive = pid_alive(identity.pid) and pid_matches_start_time(
                identity.pid, identity.start_time
            )
            owner_start = pid_start_time(os.getpid())
            try:
                expected = resolve_monitor()
            except MonitorError:
                # An executable this release cannot verify is not adopted.
                expected = None
            if (
                alive
                and owner_start > 0
                and identity.backend_port == self.backend_port
                and _access_link_port(identity.access) == identity.port
                and expected is not None
                and identity.executable_sha256 == expected.sha256
            ):
                self.identity = replace(
                    identity,
                    owner_pid=os.getpid(),
                    owner_start_time=owner_start,
                    handoff_until=0.0,
                    access="",
                )
                self.access = identity.access
                self.process = None
                write_json_atomically(path, asdict(self.identity))
                logger.info(
                    "adopted the monitor a restart released (pid %d)", identity.pid
                )
                return True
            if alive and not _terminate_verified(identity):
                raise RuntimeError("The released monitor did not stop.")
            path.unlink(missing_ok=True)
        return False

    def hand_off(self, *, seconds: float = HANDOFF_SECONDS) -> bool:
        """Release the running monitor for the next daemon to adopt.

        The handoff line goes down the ownership pipe before the record
        changes, so the EOF this daemon's exit produces no longer closes the
        monitor. An adopted monitor has no pipe; it reads the record instead.
        """
        identity = self.identity
        if identity is None or self.access is None or not self._running():
            return False
        if self.process is not None:
            if self.process.stdin is None:
                return False
            try:
                self.process.stdin.write(_HANDOFF_LINE)
                self.process.stdin.flush()
            except OSError:
                return False
        self.identity = replace(
            identity, handoff_until=time.time() + seconds, access=self.access
        )
        self._publish_identity()
        self.handed_off = True
        return True

    def reclaim(self) -> bool:
        """Take back a monitor this daemon released, when it is not stopping after all.

        A restart releases the monitor before its stop step, and that step can
        fail with this daemon still serving. Clearing the release returns the
        monitor to discovery and to this daemon's own stop, and the record no
        longer keeps it open for a successor or carries its access link.
        """
        identity = self.identity
        if not self.handed_off or identity is None or not self._running():
            return False
        self.identity = replace(identity, handoff_until=0.0, access="")
        self._publish_identity()
        self.handed_off = False
        return True

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
        if self.handed_off:
            # Released to a successor: closing the pipe is all that is left,
            # and the monitor reads that EOF as the handoff taking effect.
            if self.process is not None and self.process.stdin is not None:
                with contextlib.suppress(OSError):
                    self.process.stdin.close()
            self.identity = None
            self.access = None
            self.process = None
            return True
        process = self.process
        if process is None:
            return self._stop_adopted()
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

    def _stop_adopted(self) -> bool:
        """End an adopted monitor, which this daemon holds no pipe to."""
        identity = self.identity
        if identity is None:
            return True
        if not _terminate_verified(identity):
            return False
        path = _identity_path()
        try:
            with status_write_lock(path):
                if _read_identity(path) == identity:
                    path.unlink(missing_ok=True)
        except TimeoutError as exc:
            logger.warning(
                "monitor stopped; its identity record is left for the next "
                "start or stop to clear: %s",
                exc,
            )
        self.identity = None
        self.access = None
        return True
