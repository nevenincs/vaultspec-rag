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
    _resolve_monitor_executable,
    stop_recorded_monitor,
)
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
            # Match the compiled server's listener outside Windows' ephemeral
            # range, where the runtime's own sockets can consume a freed port.
            port = random.randrange(20000, 40000)
            try:
                sockets[0].bind(("0.0.0.0", port))
                for offset in range(1, count):
                    listener = socket.socket()
                    if os.name == "nt":
                        listener.setsockopt(
                            socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
                        )
                    sockets.append(listener)
                    listener.bind(("0.0.0.0", port + offset))
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
        process.wait(timeout=5)
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
        process.wait(timeout=5)
        assert not path.exists()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
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
            process.wait(timeout=5)
        path.unlink(missing_ok=True)
