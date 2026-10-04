"""Lifecycle integration against the real compiled monitor executable."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
from http.client import HTTPConnection
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from .._loopback_http import LOOPBACK_OPENER
from .._machine_lock import (
    acquire_machine_lock_lease,
    read_machine_discovery,
    release_machine_lock_lease,
)
from .._process_probe import wait_for_exit
from ..cli import app
from ..cli._service_start import _start_success
from ..config._types import EnvVar
from ..monitor_process import MonitorProcess, stop_recorded_monitor
from ..server._lifecycle import _DiscoveryPublisher
from ..server._lifespan import _shutdown_components
from ..server._runtime import ServerRouteRuntime
from ..service import ServiceRegistry
from ..serviceclient._discovery import read_service_status
from ._ports import bind_released_loopback_port
from .test_monitor_logs import monitor_http as monitor_http
from .test_monitor_process import _ports

if TYPE_CHECKING:
    from pathlib import Path

# The repository's unit tier covers every accelerator-free test, including
# real subprocesses. Its integration tier acquires the machine's GPU lease.
pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def compiled_monitor_required() -> None:
    binary = os.environ.get(EnvVar.MONITOR_BINARY.value) or shutil.which(
        "vaultspec-rag-monitor"
    )
    assert binary, (
        "Build/install the compiled monitor or provide its absolute path in "
        "VAULTSPEC_RAG_MONITOR_BINARY before running compiled lifecycle integration."
    )


def test_monitor_allocates_after_custom_backend_and_republishes_discovery(
    isolated_singleton_dirs: Path,
) -> None:
    """Removing owned identity deletion failed its cleanup assertion (exit 1)
    against the compiled executable; restoring it passed (exit 0).
    """
    with _ports(4) as listeners:
        backend_port = listeners[0].getsockname()[1]
        listeners[-1].close()
        monitor = MonitorProcess(backend_port)
        lease, _ = acquire_machine_lock_lease()
        assert lease is not None
        publisher = _DiscoveryPublisher(
            ServerRouteRuntime(
                "monitor-owner", ServiceRegistry(), backend_port, monitor
            ),
            lease,
        )
        try:
            monitor.start()
            fields = monitor.discovery_fields()
            assert fields["monitor_port"] == backend_port + 3
            process = monitor.process
            assert process is not None
            monitor.start()
            assert monitor.process is process
            with LOOPBACK_OPENER.open(
                f"http://127.0.0.1:{fields['monitor_port']}/", timeout=15
            ) as response:
                assert response.status == 200
                assert b'<div id="root">' in response.read()
            publisher.publish_phase("running", require=True)
            status = read_service_status()
            assert status is not None
            assert status["monitor_port"] == backend_port + 3
            pointer = read_machine_discovery()
            assert pointer is not None
            assert pointer["monitor_pid"] == process.pid
            (isolated_singleton_dirs / "service.json").unlink()
            publisher.heartbeat()
            status = read_service_status()
            assert status is not None
            assert status["monitor_port"] == backend_port + 3
            with CliRunner().isolation() as (stdout, _, _):
                _start_success(
                    True,
                    status="started",
                    human_title="Service started",
                    human_lines=(),
                    port=backend_port,
                )
                envelope = json.loads(stdout.getvalue())
                assert envelope["data"]["monitor_port"] == backend_port + 3
            with pytest.raises(OSError):
                bind_released_loopback_port(backend_port + 3)
            asyncio.run(
                _shutdown_components([], None, publisher, publisher.runtime.registry)
            )
            assert process.poll() is not None
            assert not (isolated_singleton_dirs / "monitor.json").exists()
            bind_released_loopback_port(backend_port + 3)
        finally:
            monitor.stop()
            publisher.quiesce()
            publisher.cleanup()
            release_machine_lock_lease(lease)


def test_managed_monitor_connects_to_backend_and_canonical_lifecycle(
    monitor_http: tuple[int, Path],
) -> None:
    backend_port, _ = monitor_http
    monitor = MonitorProcess(backend_port)
    try:
        monitor.start()
        port = monitor.discovery_fields()["monitor_port"]
        with LOOPBACK_OPENER.open(
            f"http://127.0.0.1:{port}/api/monitor/health", timeout=15
        ) as response:
            assert response.status == 200
            assert json.load(response)["pid"] == os.getpid()
        with LOOPBACK_OPENER.open(
            f"http://127.0.0.1:{port}/api/monitor/lifecycle", timeout=15
        ) as response:
            assert response.status == 200
            assert json.load(response)["command"] == "service.status"
    finally:
        monitor.stop()


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_managed_monitor_confines_requests_and_listener_to_loopback() -> None:
    """A compiled wildcard listener fails the destination refusal assertion;
    restoring loopback passes. Removing admission fails the request assertion.
    """
    with _ports(1) as listeners:
        monitor = MonitorProcess(listeners[0].getsockname()[1])
        try:
            monitor.start()
            port = cast("int", monitor.discovery_fields()["monitor_port"])
            with (
                pytest.raises(ConnectionRefusedError),
                socket.create_connection(("127.0.0.2", port), timeout=3),
            ):
                pass
            for path in ("/", "/index.html", "/monitor.json"):
                with LOOPBACK_OPENER.open(
                    f"http://127.0.0.1:{port}{path}", timeout=8
                ) as response:
                    assert response.status == 200
            for source, host in (
                ("127.0.0.2", "127.0.0.1"),
                ("127.0.0.1", "100.84.254.21"),
            ):
                for path in ("/", "/monitor.json", "/api/monitor/jobs"):
                    connection = HTTPConnection(
                        "127.0.0.1", port, timeout=8, source_address=(source, 0)
                    )
                    try:
                        connection.request(
                            "GET",
                            path,
                            headers={"Host": host, "Origin": f"http://{host}"},
                        )
                        response = connection.getresponse()
                        assert response.status == 403
                        response.read()
                    finally:
                        connection.close()
        finally:
            monitor.stop()


def test_forced_parent_death_closes_frontend_and_stop_clears_assignment(
    isolated_singleton_dirs: Path,
) -> None:
    """Removing orphan identity deletion failed its cleanup assertion (exit 1)
    against the compiled executable; restoring it passed (exit 0).
    """
    with _ports() as listeners:
        backend_port = listeners[0].getsockname()[1]
        script = (
            "import json,sys; "
            "from vaultspec_rag.monitor_process import MonitorProcess; "
            f"monitor=MonitorProcess({backend_port}); monitor.start(); "
            "print(json.dumps(monitor.discovery_fields()),flush=True); sys.stdin.read()"
        )
        parent = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert parent.stdout is not None
        output = parent.stdout
        answers: queue.Queue[str] = queue.Queue()
        reader = threading.Thread(
            target=lambda: answers.put(output.readline()), daemon=True
        )
        reader.start()
        try:
            fields = json.loads(answers.get(timeout=35))
            child_pid = cast("int", fields["monitor_pid"])
            parent.kill()
            parent.wait(timeout=5)
            assert wait_for_exit(child_pid, timeout=10)
            result = CliRunner().invoke(app, ["server", "stop", "--json"])
            assert result.exit_code == 0, result.output
            envelope = json.loads(result.stdout)
            assert envelope["ok"] is True
            assert not (isolated_singleton_dirs / "monitor.json").exists()
            bind_released_loopback_port(cast("int", fields["monitor_port"]))
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=5)
            for pipe in (parent.stdin, parent.stdout, parent.stderr):
                if pipe is not None:
                    pipe.close()
            stop_recorded_monitor()
