"""Compiled launcher admission and verified process cleanup without models."""

from __future__ import annotations

import json
import os
import random
import socket
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from .._atomic_write import write_json_atomically
from .._ports import next_available_port
from .._process_probe import pid_alive, pid_start_time
from ..cli import app
from ..config._types import EnvVar
from ..monitor_process import (
    MonitorIdentity,
    MonitorProcess,
    _access_link_port,
    _resolve_monitor_executable,
    stop_recorded_monitor,
)
from ._child_signal import PROCESS_TIMEOUT_SECONDS
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = pytest.mark.unit


@contextmanager
def _ports(count: int = 1) -> Generator[list[socket.socket]]:
    sockets: list[socket.socket] = []
    try:
        for _ in range(100):
            for listener in sockets:
                listener.close()
            sockets = [socket.socket()]
            if os.name == "nt":
                sockets[0].setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            # Reserve loopback outside Windows' ephemeral range, where the
            # runtime's own sockets can consume a freed port.
            port = random.randrange(20000, 40000)
            try:
                sockets[0].bind(("127.0.0.1", port))
                for offset in range(1, count):
                    listener = socket.socket()
                    if os.name == "nt":
                        listener.setsockopt(
                            socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
                        )
                    sockets.append(listener)
                    listener.bind(("127.0.0.1", port + offset))
                break
            except OSError:
                continue
        else:
            raise RuntimeError("No consecutive test ports available")
        for listener in sockets:
            listener.listen()
        yield sockets
    finally:
        for listener in sockets:
            listener.close()


def test_monitor_start_failure_rolls_back_child_and_assignment(
    isolated_singleton_dirs: Path,
) -> None:
    """Disabling process reset failed the rollback assertion (exit 1);
    restoring it passed this test (exit 0).
    """
    with (
        _ports() as listeners,
        managed_env(**{EnvVar.MONITOR_BINARY.value: sys.executable}),
    ):
        monitor = MonitorProcess(listeners[0].getsockname()[1])
        with pytest.raises(RuntimeError, match="exited before becoming ready"):
            monitor.start()
        assert monitor.process is None
        assert monitor.discovery_fields() == {}
        assert not (isolated_singleton_dirs / "monitor.json").exists()


def test_allocator_advances_past_occupied_backend_neighbors() -> None:
    with _ports(4) as listeners:
        backend = listeners[0].getsockname()[1]
        listeners[-1].close()
        assert next_available_port(backend + 1) == backend + 3


def test_monitor_rejects_relative_executable_override() -> None:
    """Accepting a relative override failed the error assertion (exit 1);
    restoring the absolute-path guard passed this test (exit 0).
    """
    with (
        managed_env(**{EnvVar.MONITOR_BINARY.value: "vaultspec-rag-monitor.exe"}),
        pytest.raises(RuntimeError, match="override must be absolute"),
    ):
        _resolve_monitor_executable()


def test_monitor_rejects_missing_compiled_executable(
    isolated_singleton_dirs: Path,
) -> None:
    """Removing file admission failed the error assertion (exit 1);
    restoring it passed this test (exit 0).
    """
    missing = isolated_singleton_dirs / "missing-monitor.exe"
    with (
        managed_env(**{EnvVar.MONITOR_BINARY.value: str(missing)}),
        pytest.raises(RuntimeError, match="compiled monitor executable is missing"),
    ):
        _resolve_monitor_executable()


def test_monitor_requires_installed_compiled_command() -> None:
    """Accepting a missing command failed the error assertion (exit 1);
    restoring command admission passed this test (exit 0).
    """
    with (
        managed_env(PATH="", **{EnvVar.MONITOR_BINARY.value: ""}),
        pytest.raises(RuntimeError, match=r"compiled .* executable is required"),
    ):
        _resolve_monitor_executable()


@pytest.mark.parametrize(
    "line",
    [
        "",
        "5421",
        "http://127.0.0.1:5421/",
        "http://127.0.0.1/#capability=owner",
        "http://127.0.0.1:99999/#capability=owner",
        "https://127.0.0.1:5421/#capability=owner",
        "http://localhost:5421/#capability=owner",
        "http://192.0.2.1:5421/#capability=owner",
    ],
)
def test_readiness_without_a_loopback_access_link_is_refused(line: str) -> None:
    """Dropping the fragment requirement failed the capability-free link case
    (exit 1); restoring it passed every case (exit 0).

    A bare port is the readiness line of a monitor that authenticates no
    caller, so the supervisor must not publish it as a started monitor.
    """
    assert _access_link_port(line) == 0


def test_readiness_access_link_reports_its_port() -> None:
    assert _access_link_port("http://127.0.0.1:5421/#capability=owner") == 5421


def test_monitor_port_exhaustion_is_a_start_failure(
    isolated_singleton_dirs: Path,
) -> None:
    """Removing the port-range guard failed the error assertion (exit 1);
    restoring it passed this test (exit 0).
    """
    monitor = MonitorProcess(65535)
    with pytest.raises(RuntimeError, match="No monitor port exists above"):
        monitor.start()
    assert not (isolated_singleton_dirs / "monitor.json").exists()


def test_stop_refuses_a_reused_monitor_pid_and_emits_one_failure(
    isolated_singleton_dirs: Path,
) -> None:
    """Removing the incarnation check failed the exit-code assertion (exit 1);
    restoring it passed this test (exit 0).
    """
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        started = pid_start_time(process.pid)
        assert started > 0
        identity = MonitorIdentity(
            # This impossible pid represents a confirmed-dead owner.
            2**30,
            1.0,
            process.pid,
            started + 10,
            54321,
        )
        path = isolated_singleton_dirs / "monitor.json"
        write_json_atomically(path, asdict(identity))
        result = CliRunner().invoke(app, ["server", "stop", "--json"])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"] == "monitor_stop_failed"
        assert pid_alive(process.pid)
        assert path.exists()
    finally:
        process.terminate()
        process.wait(timeout=PROCESS_TIMEOUT_SECONDS)
        (isolated_singleton_dirs / "monitor.json").unlink(missing_ok=True)


def test_stop_reaps_verified_orphan_and_clears_assignment(
    isolated_singleton_dirs: Path,
) -> None:
    """Disabling orphan record deletion failed the cleanup assertion (exit 1);
    restoring it passed this test (exit 0).
    """
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    path = isolated_singleton_dirs / "monitor.json"
    try:
        identity = MonitorIdentity(
            2**30, 1.0, process.pid, pid_start_time(process.pid), 54321
        )
        write_json_atomically(path, asdict(identity))
        assert stop_recorded_monitor() is True
        process.wait(timeout=PROCESS_TIMEOUT_SECONDS)
        assert not path.exists()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=PROCESS_TIMEOUT_SECONDS)
        path.unlink(missing_ok=True)


_HOLDS_THE_STATUS_LOCK = """
import sys
from pathlib import Path

from vaultspec_rag.serviceclient._discovery import status_write_lock

with status_write_lock(Path(sys.argv[1]), timeout=30.0):
    print("held", flush=True)
    sys.stdin.readline()
"""


def test_a_stopped_monitor_is_stopped_even_when_its_record_cannot_be_withdrawn(
    isolated_singleton_dirs: Path,
) -> None:
    """A held status lock delays the record's removal, not the stop.

    The monitor process has exited by the time its record is withdrawn, so a
    lock another process holds leaves a record naming a dead process. That is
    what the next start or stop reaps; reporting the stop as failed made a
    daemon that had released everything end its shutdown as unclean.

    Mutation: let the lock's timeout escape ``stop``. Observed this fail on
    the ``TimeoutError`` raised out of the call. Restored; passes.
    """
    path = isolated_singleton_dirs / "monitor.json"
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDS_THE_STATUS_LOCK, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    try:
        identity = MonitorIdentity(
            os.getpid(),
            pid_start_time(os.getpid()),
            child.pid,
            pid_start_time(child.pid),
            54321,
        )
        write_json_atomically(path, asdict(identity))
        monitor = MonitorProcess(54320)
        monitor.process = child
        monitor.identity = identity
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"

        stopped = monitor.stop()

        assert stopped is True
        assert child.poll() is not None, "the monitor process was left running"
        assert monitor.process is None
        assert monitor.identity is None
        assert path.exists(), "the record was removed without the lock"
    finally:
        for process in (holder, child):
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
        path.unlink(missing_ok=True)


def _holding_the_status_lock(path: Path) -> subprocess.Popen[str]:
    """Start a process that holds the status lock until its stdin closes."""
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDS_THE_STATUS_LOCK, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "held"
    return holder


def _end(*processes: subprocess.Popen[str]) -> None:
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()


def test_the_stop_verb_succeeds_over_a_dead_monitors_record_it_cannot_withdraw(
    isolated_singleton_dirs: Path,
) -> None:
    """The stop verb answers for the monitor process, not for its record.

    The recorded monitor has exited and another process holds the status
    lock, so the record can be neither reaped nor withdrawn. The stop that
    was asked for has happened: the verb exits zero and leaves the record for
    the next start or stop to clear.

    Mutation: let the lock's timeout reach the verb's failure branch.
    Observed this fail on the exit code, with ``monitor_stop_failed``.
    Restored; passes.
    """
    path = isolated_singleton_dirs / "monitor.json"
    exited = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    exited.wait(timeout=30)
    # The impossible pid represents a confirmed-dead owner.
    write_json_atomically(
        path, asdict(MonitorIdentity(2**30, 1.0, exited.pid, 1.0, 54321))
    )
    holder = _holding_the_status_lock(path)
    try:
        result = CliRunner().invoke(app, ["server", "stop", "--json"])

        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["ok"] is True
        assert path.exists(), "the record was removed without the lock"
    finally:
        _end(holder, exited)
        path.unlink(missing_ok=True)


def test_the_stop_verb_fails_over_a_live_monitor_it_cannot_reap(
    isolated_singleton_dirs: Path,
) -> None:
    """A held status lock excuses a leftover record, never a running monitor.

    The recorded monitor is alive, its owner is gone, and another process
    holds the status lock, so it cannot be reaped. The monitor is still
    running, and the verb says so by failing.

    Mutation: take every lock timeout as a stop that happened. Observed this
    fail on the exit code. Restored; passes.
    """
    path = isolated_singleton_dirs / "monitor.json"
    running = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    write_json_atomically(
        path,
        asdict(
            MonitorIdentity(2**30, 1.0, running.pid, pid_start_time(running.pid), 54321)
        ),
    )
    holder = _holding_the_status_lock(path)
    try:
        result = CliRunner().invoke(app, ["server", "stop", "--json"])

        assert result.exit_code == 1, result.stdout
        assert json.loads(result.stdout)["error"] == "monitor_stop_failed"
        assert pid_alive(running.pid)
        assert path.exists()
    finally:
        _end(holder, running)
        path.unlink(missing_ok=True)


def test_orphan_cleanup_preserves_live_successor_owner(
    isolated_singleton_dirs: Path,
) -> None:
    """Removing live-owner protection failed the retained-state assertion
    (exit 1); restoring it passed this test (exit 0).
    """
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    path = isolated_singleton_dirs / "monitor.json"
    try:
        identity = MonitorIdentity(
            os.getpid(),
            pid_start_time(os.getpid()),
            process.pid,
            pid_start_time(process.pid),
            54321,
        )
        write_json_atomically(path, asdict(identity))
        assert stop_recorded_monitor() is True
        assert path.exists()
        assert process.poll() is None
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=PROCESS_TIMEOUT_SECONDS)
        path.unlink(missing_ok=True)
