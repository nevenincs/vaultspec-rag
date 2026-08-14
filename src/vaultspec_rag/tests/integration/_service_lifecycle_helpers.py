"""Integration tests for service daemon lifecycle.

Exercises real subprocess spawning, real GPU model loading, and real
Qdrant operations.  No mocks, patches, stubs, or skips.

Closes TESTGAP-001 (_terminate_pid), TESTGAP-002 (_spawn_service),
TESTGAP-003 (service_start), TESTGAP-004 (service_stop happy path),
TESTGAP-005 (service_status running), TESTGAP-009 (multi-project MCP).
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from ..._job_values import count
from ..._loopback_http import probe_loopback_connect
from ..._process_probe import pid_alive
from ...cli._process import _terminate_pid
from ...cli._service_status import (
    _write_service_status,
    read_service_status,
)
from ...config._types import EnvVar
from ...qdrant_runtime._constants import QDRANT_SERVER_VERSION
from .._model_setup import (
    model_setup_timeout_seconds,
)
from .._ports import free_loopback_port
from ._helpers import (
    _poll_health,
    _poll_own_health,
    _service_env,
    _wait_for_exit,
)

__all__ = [
    "_assert_discovery_absent",
    "_assert_expired_startup_torn_down",
    "_assert_interrupted_after_release",
    "_assert_published_qdrant_identity",
    "_assert_shutdown_log_order",
    "_await_models_loaded",
    "_await_ready_marker",
    "_cleanup_forced_stop_harness",
    "_identity_health_process",
    "_job_owns_full_pipeline",
    "_port_is_listening",
    "_ports_listening",
    "_service_processes_on_port",
    "_signal_service_shutdown",
    "_signalable_live_service",
    "_spawn_posix_qdrant_owner",
    "_spawn_running_phase_lock_holder",
    "_terminate_test_processes",
    "_wait_for_discovery_repair",
    "_wait_for_listeners_closed",
    "_wait_for_persisted_job",
    "_wait_for_published_qdrant",
]

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from ...job_models import JobSnapshot

runner = CliRunner()

pytestmark = [pytest.mark.integration]


def _assert_expired_startup_torn_down(
    *,
    daemon_pid: int,
    launcher_pid: int,
    qdrant_pid: int,
    qdrant_start_time: float,
) -> None:
    """Assert an expired startup reaps its daemon, launcher, and Qdrant child."""
    from ...qdrant_runtime._resolve import reap_qdrant_orphan

    termination_started = time.monotonic()
    _terminate_pid(daemon_pid, timeout=0.200)
    assert time.monotonic() - termination_started < 0.700
    if pid_alive(daemon_pid):
        _terminate_pid(daemon_pid, timeout=15.0)
    assert _wait_for_exit(daemon_pid, timeout=30.0), (
        f"startup-expired service process {daemon_pid} did not exit"
    )
    assert _wait_for_exit(launcher_pid, timeout=30.0), (
        f"startup-expired service launcher {launcher_pid} did not exit"
    )
    if pid_alive(qdrant_pid):
        assert reap_qdrant_orphan(
            qdrant_pid,
            wait_seconds=15.0,
            expected_start_time=qdrant_start_time,
        )
    assert _wait_for_exit(qdrant_pid, timeout=30.0), (
        f"startup-expired Qdrant process {qdrant_pid} did not exit"
    )


def _await_ready_marker(
    ready_path: Path,
    *,
    launcher_pid: int,
    timeout: float = 90.0,
) -> None:
    """Block until the readiness marker appears or its launcher dies."""
    deadline = time.monotonic() + timeout
    while not ready_path.exists() and time.monotonic() < deadline:
        if not pid_alive(launcher_pid):
            break
        time.sleep(0.05)


def _await_models_loaded(
    daemon_log: Path,
    *,
    daemon_pid: int,
    timeout: float = 120.0,
) -> str:
    """Block until the daemon logs model readiness; return the final log text."""
    deadline = time.monotonic() + timeout
    output = ""
    while time.monotonic() < deadline and pid_alive(daemon_pid):
        if daemon_log.is_file():
            output = daemon_log.read_text(encoding="utf-8", errors="replace")
        if "All models loaded" in output:
            break
        time.sleep(0.2)
    return daemon_log.read_text(encoding="utf-8", errors="replace")


def _assert_published_qdrant_identity(
    status: dict[str, object],
    *,
    port: int,
    qdrant_pid: int,
    qdrant_port: int,
    version: str = QDRANT_SERVER_VERSION,
) -> dict[str, object]:
    """Assert a published status carries a complete managed-child witness.

    Returns the nested identity so callers can compare it after a republish.
    """
    assert status["port"] == port
    assert status["phase"] == "warming"
    assert status["qdrant_version"] == version
    assert float(cast("float", status["qdrant_start_time"])) > 0.0
    nested_identity = cast("dict[str, object]", status["qdrant_identity"])
    assert nested_identity["pid"] == qdrant_pid
    assert nested_identity["port"] == qdrant_port
    assert nested_identity["version"] == version
    assert nested_identity["start_time"] == status["qdrant_start_time"]
    return nested_identity


def _wait_for_published_qdrant(
    *,
    service_pid: int,
    timeout: float = 90.0,
) -> tuple[int, int] | None:
    """Wait for the warming daemon to publish its supervised child identity."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = read_service_status()
        published_pid = count(status.get("qdrant_pid") if status else None)
        published_port = count(status.get("qdrant_port") if status else None)
        # A count reads zero as a legitimate quantity; neither a process
        # identifier nor a listening port ever is.
        if published_pid and published_port:
            return published_pid, published_port
        if not pid_alive(service_pid):
            return None
        time.sleep(0.1)
    return None


def _service_processes_on_port(port: int) -> dict[int, list[str]]:
    """Return real process argv containing the resident-server port command."""
    import psutil

    expected = ["-m", "vaultspec_rag.server", "--port", str(port)]
    found: dict[int, list[str]] = {}
    for process in psutil.process_iter(["pid", "cmdline"]):
        info = cast("dict[str, object]", process.info)
        raw = info.get("cmdline")
        if not isinstance(raw, list):
            continue
        argv = [str(item) for item in cast("list[object]", raw)]
        if any(
            argv[index : index + len(expected)] == expected
            for index in range(len(argv) - len(expected) + 1)
        ):
            pid = count(info.get("pid"))
            if pid is not None:
                found[pid] = argv
    return found


def _terminate_test_processes(pids: list[int]) -> None:
    """Best-effort finalizer for only the process identifiers this test owns."""
    for pid in pids:
        if pid_alive(pid):
            _terminate_pid(pid)
            _wait_for_exit(pid, timeout=15.0)


def _port_is_listening(port: int) -> bool:
    """Whether anything accepts a loopback connect, at the conservative bound.

    Lifecycle asserts here claim a listener is present or gone, so they wait
    out the full pre-existing deadline rather than trading accuracy for speed.
    """
    return probe_loopback_connect(port, timeout=1.0) == "accepted"


def _ports_listening(*ports: int) -> dict[int, bool]:
    """Probe several ports at once, each at the full single-port deadline.

    An unbound loopback port costs the whole deadline here: nothing completes
    the handshake and nothing refuses it fast enough to shortcut the wait, so
    probing in sequence pays that deadline once per port. Fanning out keeps
    every port's deadline intact and spends one deadline of wall time total.
    """
    with ThreadPoolExecutor(max_workers=len(ports)) as pool:
        return dict(zip(ports, pool.map(_port_is_listening, ports), strict=True))


def _wait_for_listeners_closed(*ports: int, timeout: float = 10.0) -> bool:
    """Return whether every test-owned listener closes within the bound."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_ports_listening(*ports).values()):
            return True
        time.sleep(0.1)
    return not any(_ports_listening(*ports).values())


def _wait_for_persisted_job(
    state_path: Path,
    job_id: str,
    predicate: Callable[[JobSnapshot], bool],
    description: str,
    *,
    timeout: float = 90.0,
) -> JobSnapshot:
    """Poll canonical durable state through the production decoder."""
    from ...job_persistence import load_persisted_state

    deadline = time.monotonic() + timeout
    last: JobSnapshot | None = None
    while time.monotonic() < deadline:
        try:
            persisted = load_persisted_state(state_path)
        except OSError:
            time.sleep(0.01)
            continue
        last = next((job for job in persisted.jobs if job.id == job_id), None)
        if last is not None and predicate(last):
            return last
        time.sleep(0.01)
    raise AssertionError(
        f"{description} within {timeout:g}s; last canonical snapshot={last!r}"
    )


def _signal_service_shutdown(pid: int) -> None:
    """Request the daemon's real graceful signal path without early escalation."""
    if sys.platform == "win32":
        os.kill(pid, signal.CTRL_BREAK_EVENT)
    else:
        os.kill(pid, signal.SIGTERM)


@contextmanager
def _signalable_live_service(
    tmp_path: Path,
    qdrant_source: tuple[Path, Path],
) -> Generator[tuple[int, int]]:
    """Run the real daemon in a Windows-signalable process group."""
    from ...cli._process import _build_service_child_env, _ServiceChildEnvRequest
    from .conftest import _cleanup_service_process

    offline_env = {
        EnvVar.HF_HUB_OFFLINE.value: "1",
        EnvVar.TRANSFORMERS_OFFLINE.value: "1",
    }
    with _service_env(
        tmp_path,
        env_overrides=offline_env,
        qdrant_source=qdrant_source,
    ):
        port = free_loopback_port()
        log_path = tmp_path / "service.log"
        command = [
            sys.executable,
            "-m",
            "vaultspec_rag.server",
            "--port",
            str(port),
        ]
        child_env = _build_service_child_env(_ServiceChildEnvRequest(watch=False))
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if sys.platform == "win32"
            else 0
        )
        with log_path.open("ab") as output:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=child_env,
                cwd=tmp_path,
                creationflags=creationflags,
                start_new_session=sys.platform != "win32",
            )
        try:
            _write_service_status(process.pid, port)
            _poll_health(port, timeout=model_setup_timeout_seconds())
            yield port, process.pid
        finally:
            _cleanup_service_process(
                pid=process.pid,
                port=port,
                log_path=log_path,
                timeout=30.0,
            )


def _job_owns_full_pipeline(job: JobSnapshot) -> bool:
    """Observe every manager-tracked owner on one real code attempt."""
    from ...job_models import JobState

    return job.state is JobState.RUNNING and all(
        (
            job.runtime.task_active,
            job.runtime.worker_active,
            job.resources.index_capacity_held,
            job.resources.project_lease_held,
            job.resources.writer_lock_held,
            job.resources.pipeline_active,
        )
    )


def _assert_interrupted_after_release(job: JobSnapshot) -> None:
    """Require interruption to carry complete worker-release evidence."""
    assert job.runtime.task_active is False
    assert job.runtime.worker_active is False
    assert job.resources.started is not None
    assert job.resources.finished is not None
    assert job.resources.index_capacity_held is False
    assert job.resources.project_lease_held is False
    assert job.resources.writer_lock_held is False
    assert job.resources.pipeline_active is False
    assert job.timestamps.finished_at is not None
    assert job.error_kind == "interrupted"


def _assert_shutdown_log_order(
    output: str,
    *,
    job_id: str,
    qdrant_pid: int,
) -> None:
    """Require attempt release before stores and stores before Qdrant."""
    finished_at = output.index(f"service.job event=finished job_id={job_id}")
    assert "phase=interrupted" in output[finished_at : finished_at + 600]
    slot_closed_at = output.index("ProjectSlot closed for", finished_at)
    registry_closed_at = output.index("ServiceRegistry shut down", slot_closed_at)
    qdrant_closed_at = output.index(
        f"qdrant child pid={qdrant_pid} stopped",
        registry_closed_at,
    )
    assert finished_at < slot_closed_at < registry_closed_at < qdrant_closed_at
    assert "Service shutdown complete" in output[qdrant_closed_at:]


def _cleanup_forced_stop_harness(
    service: subprocess.Popen[str],
    qdrant_pid: int,
) -> None:
    """Clean only the real processes owned by the POSIX forced-stop harness."""
    from ..._process_probe import pid_alive
    from ...qdrant_runtime._resolve import reap_qdrant_orphan

    if pid_alive(service.pid):
        service.kill()
        service.wait(timeout=15)
    if pid_alive(qdrant_pid):
        reap_qdrant_orphan(qdrant_pid)


def _spawn_posix_qdrant_owner() -> tuple[subprocess.Popen[str], int, int]:
    """Start a real SIGTERM-resistant service owner and supervised Qdrant."""
    service = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import signal,time;"
                "from vaultspec_rag.qdrant_runtime._supervise import "
                "start_supervised_from_config;"
                "supervisor=start_supervised_from_config();"
                "signal.signal(signal.SIGTERM,lambda *_:None);"
                "print("
                "f'ready {supervisor.pid} {supervisor.http_port}',"
                "flush=True);"
                "time.sleep(60)"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    assert service.stdout is not None
    output: list[str] = []
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [service.stdout],
            [],
            [],
            max(0.0, deadline - time.monotonic()),
        )
        if not readable:
            break
        line = service.stdout.readline()
        if not line:
            break
        output.append(line.rstrip())
        parts = line.split()
        if len(parts) == 3 and parts[0] == "ready":
            return service, int(parts[1]), int(parts[2])
    raise AssertionError(
        "real POSIX Qdrant owner did not publish readiness\n" + "\n".join(output)
    )


def _spawn_running_phase_lock_holder(
    *,
    status_path: Path,
    ready_path: Path,
) -> subprocess.Popen[str]:
    """Hold the real status lock after Qdrant publication but before readiness."""
    script = (
        "import json,os,sys,time;"
        "s=sys.argv[1];r=sys.argv[2];"
        "d=time.monotonic()+90;"
        "\nwhile time.monotonic()<d:\n"
        " try:\n"
        "  x=json.load(open(s,encoding='utf-8'))\n"
        "  if x.get('qdrant_pid') and x.get('qdrant_start_time'): break\n"
        " except (OSError,ValueError): pass\n"
        " time.sleep(.02)\n"
        "else: raise SystemExit(3)\n"
        "p=os.path.join(os.path.dirname(s),'service.json.lock');"
        "f=open(p,'a+b');"
        "f.write(b'0') if os.path.getsize(p)==0 else None;"
        "f.flush();f.seek(0);"
        "\nif sys.platform=='win32':\n"
        " import msvcrt;msvcrt.locking(f.fileno(),msvcrt.LK_LOCK,1)\n"
        "else:\n"
        " import fcntl;fcntl.flock(f.fileno(),fcntl.LOCK_EX)\n"
        "open(r,'w').close();time.sleep(180)"
    )
    return subprocess.Popen(
        [sys.executable, "-c", script, str(status_path), str(ready_path)],
        text=True,
    )


# -- Tests -------------------------------------------------------------------


def _wait_for_discovery_repair(
    path: Path,
    *,
    timeout: float,
) -> dict[str, object]:
    """Return the republished discovery document at *path* within *timeout*."""
    deadline = time.monotonic() + timeout
    last_error = "never reappeared"
    while time.monotonic() < deadline:
        try:
            parsed: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if isinstance(parsed, dict):
                payload = cast("dict[str, object]", parsed)
                if payload.get("pid"):
                    return payload
            last_error = f"incomplete document: {parsed!r}"
        time.sleep(0.5)
    raise AssertionError(
        f"{path} was not repaired within {timeout:.1f}s ({last_error})"
    )


def _assert_discovery_absent(paths: tuple[Path, ...], *, held_for: float) -> None:
    """Assert every path in *paths* stays absent for *held_for* seconds."""
    deadline = time.monotonic() + held_for
    while time.monotonic() < deadline:
        for path in paths:
            assert not path.exists(), (
                f"{path} was resurrected after owner cleanup: "
                f"{path.read_text(encoding='utf-8')[:400]!r}"
            )
        time.sleep(0.5)


def _terminate_identity_process(
    process: subprocess.Popen[bytes],
    serving_pid: int,
    log_path: Path,
) -> None:
    """Stop the spawned identity child, and its serving pid when they differ."""
    # A plain ``Popen`` helper is not a process-group leader, so a Windows
    # console-group break must not be addressed to it.
    _terminate_pid(process.pid, console_group_signal=False)
    if serving_pid != process.pid:
        _terminate_pid(serving_pid, console_group_signal=False)
        _wait_for_exit(serving_pid, timeout=15.0)
    assert _wait_for_exit(process.pid, timeout=15.0), (
        "identity health process did not stop; log="
        + log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
    )


@contextmanager
def _identity_health_process(
    tmp_path: Path,
    *,
    hold_machine_lock: bool,
) -> Generator[tuple[int, int, str]]:
    """Run the production health route in a real isolated child process.

    Re-rolls a fresh ephemeral port when a lost bind race or a stray listener
    takes the intended one, and gates readiness on the child's own identity
    token, so a foreign responder on that port can never stand in for the child.
    """
    token = f"reconcile-identity-{uuid.uuid4().hex}"
    child_script = """
import os

import uvicorn
from vaultspec_rag._machine_lock import (  # absolute-import-ok
    acquire_machine_lock_lease,
    release_machine_lock_lease,
)
from vaultspec_rag.server import (  # absolute-import-ok
    ServerRouteRuntime,
    create_http_app,
)
from vaultspec_rag.service import ServiceRegistry  # absolute-import-ok

lease = None
if os.environ["VAULTSPEC_TEST_HOLD_MACHINE_LOCK"] == "1":
    lease, holder = acquire_machine_lock_lease()
    if lease is None:
        raise RuntimeError(f"machine lock held by {holder}")
try:
    uvicorn.run(
        create_http_app(
            ServerRouteRuntime(
                token=os.environ["VAULTSPEC_TEST_HEALTH_TOKEN"],
                registry=ServiceRegistry(),
                port=int(os.environ["VAULTSPEC_TEST_HEALTH_PORT"]),
            ),
            lifespan=None,
        ),
        host="127.0.0.1",
        port=int(os.environ["VAULTSPEC_TEST_HEALTH_PORT"]),
        lifespan="off",
        log_level="critical",
    )
finally:
    if lease is not None:
        release_machine_lock_lease(lease)
"""
    log_path = tmp_path / "identity-health.log"
    with log_path.open("w", encoding="utf-8") as log_stream:
        failures: list[str] = []
        for _ in range(5):
            port = free_loopback_port()
            child_env = os.environ.copy()
            child_env["VAULTSPEC_TEST_HEALTH_PORT"] = str(port)
            child_env["VAULTSPEC_TEST_HEALTH_TOKEN"] = token
            child_env["VAULTSPEC_TEST_HOLD_MACHINE_LOCK"] = (
                "1" if hold_machine_lock else "0"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", child_script],
                env=child_env,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
            )
            health = _poll_own_health(process, port, token=token, timeout=20.0)
            if health is None:
                failures.append(f"port={port} rc={process.poll()}")
                _terminate_pid(process.pid, console_group_signal=False)
                _wait_for_exit(process.pid, timeout=15.0)
                continue
            # The real serving pid equals the Popen pid normally, or a descendant
            # when the interpreter relaunches through a stub; the token match
            # already proved this is the child either way.
            serving_pid = int(str(health["pid"]))
            try:
                yield serving_pid, port, token
            finally:
                _terminate_identity_process(process, serving_pid, log_path)
            return
        raise AssertionError(
            "identity health child never bound its own port in 5 attempts "
            f"({'; '.join(failures)}); log="
            + log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        )
