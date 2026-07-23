"""Integration tests for service daemon lifecycle.

Exercises real subprocess spawning, real GPU model loading, and real
Qdrant operations.  No mocks, patches, stubs, or skips.

Closes TESTGAP-001 (_terminate_pid), TESTGAP-002 (_spawn_service),
TESTGAP-003 (service_start), TESTGAP-004 (service_stop happy path),
TESTGAP-005 (service_status running), TESTGAP-009 (multi-project MCP).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from ...cli import (
    _is_pid_alive,
    _port_is_listening,
    _read_service_status,
    _spawn_service,
    _status_file,
    _terminate_pid,
    _write_service_status,
    app,
)
from ...config import EnvVar
from .._model_setup import (
    configured_service_model_ids,
    ensure_model_snapshots,
    model_setup_timeout_seconds,
)
from ._helpers import (
    _get_ephemeral_port,
    _poll_health,
    _poll_own_health,
    _service_env,
    _wait_for_exit,
)
from .conftest import _live_service_context, _startup_cleanup_reserve

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
    if _is_pid_alive(daemon_pid):
        _terminate_pid(daemon_pid, timeout=15.0)
    assert _wait_for_exit(daemon_pid, timeout=30.0), (
        f"startup-expired service process {daemon_pid} did not exit"
    )
    assert _wait_for_exit(launcher_pid, timeout=30.0), (
        f"startup-expired service launcher {launcher_pid} did not exit"
    )
    if _is_pid_alive(qdrant_pid):
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
        if not _is_pid_alive(launcher_pid):
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
    while time.monotonic() < deadline and _is_pid_alive(daemon_pid):
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
    version: str = "1.18.2",
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
        status = _read_service_status()
        raw_pid = status.get("qdrant_pid") if status else None
        raw_port = status.get("qdrant_port") if status else None
        valid_pid = (
            isinstance(raw_pid, int) and not isinstance(raw_pid, bool) and raw_pid > 0
        )
        valid_port = (
            isinstance(raw_port, int)
            and not isinstance(raw_port, bool)
            and raw_port > 0
        )
        if valid_pid and valid_port:
            return cast("int", raw_pid), cast("int", raw_port)
        if not _is_pid_alive(service_pid):
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
            pid = info.get("pid")
            if isinstance(pid, int) and not isinstance(pid, bool):
                found[pid] = argv
    return found


def _terminate_test_processes(pids: list[int]) -> None:
    """Best-effort finalizer for only the process identifiers this test owns."""
    for pid in pids:
        if _is_pid_alive(pid):
            _terminate_pid(pid)
            _wait_for_exit(pid, timeout=15.0)


def _wait_for_listeners_closed(*ports: int, timeout: float = 10.0) -> bool:
    """Return whether every test-owned listener closes within the bound."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_port_is_listening(port) for port in ports):
            return True
        time.sleep(0.1)
    return not any(_port_is_listening(port) for port in ports)


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
    from ...cli import _write_service_status
    from ...cli._process import _service_child_env
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
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        command = [
            sys.executable,
            "-m",
            "vaultspec_rag.server",
            "--port",
            str(port),
        ]
        child_env = _service_child_env(watch=False)
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
    from ...qdrant_runtime._resolve import pid_alive, reap_qdrant_orphan

    if _is_pid_alive(service.pid):
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
                "from vaultspec_rag.qdrant_runtime import "
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


def test_poll_health_honours_subsecond_deadline() -> None:
    """A real unreachable endpoint cannot overrun the caller's short budget."""
    port = _get_ephemeral_port()
    started = time.monotonic()
    with pytest.raises(TimeoutError, match=r"not ready after 0\.050s"):
        _poll_health(port, timeout=0.05)
    assert time.monotonic() - started < 1.0


def test_live_service_spawn_failure_has_shared_deadline_diagnostics(
    tmp_path: Path,
) -> None:
    """A real invalid log node fails at spawn inside the shared envelope."""
    (tmp_path / "service.log").mkdir()
    started = time.monotonic()
    with (
        pytest.raises(AssertionError) as caught,
        _live_service_context(tmp_path, startup_budget=10.0),
    ):
        pytest.fail("a directory at the log path must fail real process spawn")
    elapsed = time.monotonic() - started

    message = str(caught.value)
    # The staged diagnostics below are the invariant; the elapsed ceiling is
    # only a hang-guard sized to the budget plus the guaranteed cleanup
    # reserve, never a race against machine load.
    assert elapsed < 10.0 + _startup_cleanup_reserve(10.0) + 1.0
    assert "stage=service spawn" in message
    assert "deadline=10.000s" in message
    assert "remaining=" in message
    assert "Service output:" in message


def test_live_service_status_failure_cleans_up_inside_startup_budget(
    tmp_path: Path,
) -> None:
    """A real status-path collision fails with stage and teardown evidence."""
    (tmp_path / "service.json").mkdir()
    started = time.monotonic()
    with (
        pytest.raises(AssertionError) as caught,
        _live_service_context(tmp_path, startup_budget=15.0),
    ):
        pytest.fail("a directory at service.json must fail status publication")
    elapsed = time.monotonic() - started

    message = str(caught.value)
    # Staged diagnostics are the invariant; elapsed is a hang-guard sized to
    # the budget plus the guaranteed cleanup reserve.
    assert elapsed < 15.0 + _startup_cleanup_reserve(15.0) + 1.0
    assert "stage=status publication" in message
    assert "deadline=15.000s" in message
    assert "startup failure teardown" in message
    assert "remaining=" in message
    assert "Service output:" in message


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_live_service_readiness_expiry_uses_reserved_cleanup_budget(
    tmp_path: Path,
) -> None:
    """A real readiness expiry tears down service and Qdrant inside the envelope."""
    from ...qdrant_runtime._resolve import pid_alive

    acquisition_env = {
        EnvVar.HF_HUB_OFFLINE.value: None,
        EnvVar.TRANSFORMERS_OFFLINE.value: None,
    }
    with _service_env(tmp_path, env_overrides=acquisition_env):
        ensure_model_snapshots(
            configured_service_model_ids(),
            timeout_seconds=model_setup_timeout_seconds(),
        )

    budget = 15.0
    started = time.monotonic()
    with (
        pytest.raises(AssertionError) as caught,
        _live_service_context(tmp_path, startup_budget=budget),
    ):
        pytest.fail("the deliberately short readiness budget must expire")
    elapsed = time.monotonic() - started

    message = str(caught.value)
    # Cleanup is now guaranteed at least its full reserved window even if
    # earlier stages overran their own nominal deadlines under machine load,
    # so the ceiling here allows for that guaranteed floor plus a margin -
    # not just the bare startup budget - while still catching a genuine hang.
    assert elapsed < budget + _startup_cleanup_reserve(budget) + 1.0
    assert "stage=health readiness" in message
    assert "startup failure teardown" in message
    assert "cleanup_error=" not in message, message
    spawned = re.search(r"pid=(\d+) port=(\d+)", message)
    assert spawned is not None
    launcher_pid = int(spawned.group(1))
    service_port = int(spawned.group(2))
    identity_path = tmp_path / "qdrant-server" / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    owner_pid = int(identity["owner_pid"])
    qdrant_pid = int(identity["qdrant_pid"])
    qdrant_port = int(identity["http_port"])
    assert not _is_pid_alive(launcher_pid)
    assert not _is_pid_alive(owner_pid)
    assert not pid_alive(qdrant_pid)
    assert _wait_for_listeners_closed(service_port, qdrant_port)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_running_phase_status_failure_rolls_back_all_started_components(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """A real running-phase lock failure cancels tasks and releases all owners."""
    from ..._machine_lock import acquire_machine_lock, release_machine_lock

    acquisition_env = {
        EnvVar.HF_HUB_OFFLINE.value: None,
        EnvVar.TRANSFORMERS_OFFLINE.value: None,
    }
    with _service_env(tmp_path, env_overrides=acquisition_env):
        ensure_model_snapshots(
            configured_service_model_ids(),
            timeout_seconds=model_setup_timeout_seconds(),
        )

    offline_env = {
        EnvVar.HF_HUB_OFFLINE.value: "1",
        EnvVar.TRANSFORMERS_OFFLINE.value: "1",
    }
    with _service_env(tmp_path, env_overrides=offline_env):
        port = _get_ephemeral_port()
        log_path = tmp_path / "running-phase-failure.log"
        ready_path = tmp_path / "status-lock.ready"
        holder = _spawn_running_phase_lock_holder(
            status_path=tmp_path / "service.json",
            ready_path=ready_path,
        )
        request.addfinalizer(
            lambda: (
                (
                    holder.kill(),
                    holder.wait(timeout=5),
                )
                if holder.poll() is None
                else None
            )
        )
        launcher_pid = _spawn_service(port, log_path, watch=False)
        owned_pids = [launcher_pid]
        request.addfinalizer(lambda: _terminate_test_processes(owned_pids))

        _await_ready_marker(ready_path, launcher_pid=launcher_pid)
        assert ready_path.exists(), log_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        status = _read_service_status()
        assert status is not None
        daemon_pid = cast("int", status["pid"])
        qdrant_pid = cast("int", status["qdrant_pid"])
        qdrant_port = cast("int", status["qdrant_port"])
        owned_pids.extend([daemon_pid, qdrant_pid])

        daemon_log = tmp_path / "service.log"
        output = _await_models_loaded(daemon_log, daemon_pid=daemon_pid)
        assert "All models loaded" in output, output
        assert _wait_for_exit(daemon_pid, timeout=30.0)
        assert _wait_for_exit(launcher_pid, timeout=30.0)
        assert _wait_for_exit(qdrant_pid, timeout=30.0)
        assert _wait_for_listeners_closed(port, qdrant_port)
        output = daemon_log.read_text(encoding="utf-8", errors="replace")
        assert "ServiceRegistry shut down" in output
        assert f"qdrant child pid={qdrant_pid} stopped" in output
        assert "Service shutdown complete" in output
        acquired, owner = acquire_machine_lock()
        assert acquired is True
        assert owner == os.getpid()
        release_machine_lock()

        holder.kill()
        holder.wait(timeout=5)
        heartbeat_before = (
            json.loads((tmp_path / "service.json").read_text(encoding="utf-8")).get(
                "last_heartbeat"
            )
            if (tmp_path / "service.json").is_file()
            else None
        )
        time.sleep(1.1)
        heartbeat_after = (
            json.loads((tmp_path / "service.json").read_text(encoding="utf-8")).get(
                "last_heartbeat"
            )
            if (tmp_path / "service.json").is_file()
            else None
        )
        assert heartbeat_after == heartbeat_before


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_startup_expiry_reaps_pre_readiness_qdrant(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """An expired real startup has bounded validation and leaves no processes."""

    acquisition_env = {
        EnvVar.HF_HUB_OFFLINE.value: None,
        EnvVar.TRANSFORMERS_OFFLINE.value: None,
    }
    with _service_env(tmp_path, env_overrides=acquisition_env):
        ensure_model_snapshots(
            configured_service_model_ids(),
            timeout_seconds=model_setup_timeout_seconds(),
        )

    offline_env = {
        EnvVar.HF_HUB_OFFLINE.value: "1",
        EnvVar.TRANSFORMERS_OFFLINE.value: "1",
    }
    with _service_env(tmp_path, env_overrides=offline_env):
        port = _get_ephemeral_port()
        log_path = tmp_path / "startup-expiry.log"
        pid = _spawn_service(port, log_path, watch=False)
        owned_pids = [pid]
        request.addfinalizer(lambda: _terminate_test_processes(owned_pids))
        identity = _wait_for_published_qdrant(service_pid=pid)
        output = (
            log_path.read_text(encoding="utf-8", errors="replace")
            if log_path.is_file()
            else "<no service log>"
        )
        assert identity is not None, (
            "Qdrant identity was not published during startup.\n"
            f"Service output:\n{output}"
        )
        qdrant_pid, qdrant_port = identity
        owned_pids.append(qdrant_pid)
        status_before_parent = _read_service_status()
        assert status_before_parent is not None
        daemon_pid = cast("int", status_before_parent["pid"])
        assert daemon_pid > 0
        assert _is_pid_alive(daemon_pid)
        if daemon_pid != pid:
            owned_pids.append(daemon_pid)
        nested_identity = _assert_published_qdrant_identity(
            status_before_parent,
            port=port,
            qdrant_pid=qdrant_pid,
            qdrant_port=qdrant_port,
        )
        assert _is_pid_alive(qdrant_pid)
        assert _port_is_listening(qdrant_port)

        # The deliberately delayed parent publication must merge rather than
        # erase the daemon's authoritative pre-warmup child identity.
        _write_service_status(pid, port)
        status_after_parent = _read_service_status()
        assert status_after_parent is not None
        assert status_after_parent["pid"] == daemon_pid
        assert status_after_parent["qdrant_identity"] == nested_identity
        assert (
            status_after_parent["qdrant_start_time"]
            == status_before_parent["qdrant_start_time"]
        )

        with pytest.raises(TimeoutError, match=r"not ready after 0\.050s"):
            _poll_health(port, timeout=0.05)

        _assert_expired_startup_torn_down(
            daemon_pid=daemon_pid,
            launcher_pid=pid,
            qdrant_pid=qdrant_pid,
            qdrant_start_time=float(
                cast("float", status_before_parent["qdrant_start_time"])
            ),
        )
        assert _wait_for_listeners_closed(port, qdrant_port)


if sys.platform == "win32":

    def test_windows_late_spawn_timeout_cleans_before_pid_assignment(
        tmp_path: Path,
    ) -> None:
        """The exact late-Popen branch cannot strand an unreturned daemon PID."""
        with _service_env(tmp_path):
            port = _get_ephemeral_port()
            log_path = tmp_path / "late-spawn-timeout.log"
            started = time.monotonic()
            with pytest.raises(TimeoutError) as caught:
                _spawn_service(
                    port,
                    log_path,
                    watch=False,
                    timeout=0.000001,
                    cleanup_timeout=15.0,
                )
            assert time.monotonic() - started < 15.5
            assert "cleanup_error=" not in str(caught.value)
            assert _service_processes_on_port(port) == {}
            assert not _port_is_listening(port)
            identity_path = tmp_path / "identity.json"
            if identity_path.is_file():
                identity = json.loads(identity_path.read_text(encoding="utf-8"))
                assert not _is_pid_alive(int(identity["owner_pid"]))
                assert not _is_pid_alive(int(identity["qdrant_pid"]))
                assert not _port_is_listening(int(identity["http_port"]))

    @pytest.mark.integration
    @pytest.mark.subprocess_gpu
    def test_windows_late_spawn_cleanup_finds_detached_daemon_and_qdrant(
        request: pytest.FixtureRequest,
        tmp_path: Path,
    ) -> None:
        """Late-spawn cleanup finds the daemon even when its launcher PID differs."""
        from ...cli._process import (
            _cleanup_late_service_spawn,
            _process_start_time,
        )

        acquisition_env = {
            EnvVar.HF_HUB_OFFLINE.value: None,
            EnvVar.TRANSFORMERS_OFFLINE.value: None,
        }
        with _service_env(tmp_path, env_overrides=acquisition_env):
            ensure_model_snapshots(
                configured_service_model_ids(),
                timeout_seconds=model_setup_timeout_seconds(),
            )

        offline_env = {
            EnvVar.HF_HUB_OFFLINE.value: "1",
            EnvVar.TRANSFORMERS_OFFLINE.value: "1",
        }
        with _service_env(tmp_path, env_overrides=offline_env):
            port = _get_ephemeral_port()
            log_path = tmp_path / "late-spawn-cleanup.log"
            launcher_pid = _spawn_service(port, log_path, watch=False)
            owned_pids = [launcher_pid]
            request.addfinalizer(lambda: _terminate_test_processes(owned_pids))
            published = _wait_for_published_qdrant(service_pid=launcher_pid)
            assert published is not None
            qdrant_pid, qdrant_port = published
            owned_pids.append(qdrant_pid)
            status = _read_service_status()
            assert status is not None
            daemon_pid = cast("int", status["pid"])
            owned_pids.append(daemon_pid)
            assert daemon_pid != launcher_pid
            launch_token = cast("str", status["launch_token"])
            assert launch_token

            cleanup_error = _cleanup_late_service_spawn(
                launcher_pid=launcher_pid,
                launcher_start_time=_process_start_time(launcher_pid),
                port=port,
                launch_token=launch_token,
                timeout=15.0,
            )

            assert cleanup_error == ""
            assert _wait_for_exit(launcher_pid, timeout=15.0)
            assert _wait_for_exit(daemon_pid, timeout=15.0)
            assert _wait_for_exit(qdrant_pid, timeout=15.0)
            assert _wait_for_listeners_closed(port, qdrant_port)

    def test_windows_late_spawn_cleanup_preserves_unrelated_status_and_command(
        tmp_path: Path,
    ) -> None:
        """Only the exact launch token and PID incarnation authorize signalling."""
        from ...cli._process import (
            _cleanup_late_service_spawn,
            _process_start_time,
        )

        with _service_env(tmp_path):
            port = _get_ephemeral_port()
            owned_token = "owned-" + os.urandom(12).hex()
            unrelated_token = "unrelated-" + os.urandom(12).hex()
            sleeper = "import time; time.sleep(60)"
            owned = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    sleeper,
                    "-m",
                    "vaultspec_rag.server",
                    "--port",
                    str(port),
                    "--launch-token",
                    owned_token,
                ]
            )
            unrelated = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    sleeper,
                    "-m",
                    "vaultspec_rag.server",
                    "--port",
                    str(port),
                    "--launch-token",
                    unrelated_token,
                ]
            )
            try:
                _status_file().write_text(
                    json.dumps(
                        {
                            "pid": unrelated.pid,
                            "port": port,
                            "launch_token": owned_token,
                        }
                    ),
                    encoding="utf-8",
                )
                error = _cleanup_late_service_spawn(
                    launcher_pid=owned.pid,
                    launcher_start_time=_process_start_time(owned.pid),
                    port=port,
                    launch_token=owned_token,
                    timeout=5.0,
                )
                assert error == ""
                assert _wait_for_exit(owned.pid, timeout=5.0)
                assert unrelated.poll() is None
                assert _is_pid_alive(unrelated.pid)
            finally:
                for process in (owned, unrelated):
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5.0)


@pytest.mark.parametrize(
    ("witness_field", "expected_reason"),
    [
        ("owner_start_time", "owner"),
        ("qdrant_start_time", "child"),
    ],
)
def test_attached_qdrant_requires_complete_live_incarnation_witness(
    tmp_path: Path,
    witness_field: str,
    expected_reason: str,
) -> None:
    """A real ready Qdrant is never attached through a missing/recycled witness."""
    from ...qdrant_runtime import (
        set_active_supervisor,
        start_supervised_from_config,
    )
    from ...qdrant_runtime._resolve import (
        qdrant_identity_path,
        read_qdrant_identity,
    )

    with _service_env(tmp_path):
        first = start_supervised_from_config()
        try:
            identity = read_qdrant_identity()
            assert identity is not None
            tampered_value = (
                0.0
                if witness_field == "owner_start_time"
                else identity.qdrant_start_time + 10_000.0
            )
            tampered = replace(identity, **{witness_field: tampered_value})
            qdrant_identity_path().write_text(
                json.dumps(
                    {
                        "storage_path": tampered.storage_path,
                        "version": tampered.version,
                        "owner_pid": tampered.owner_pid,
                        "http_port": tampered.http_port,
                        "qdrant_pid": tampered.qdrant_pid,
                        "qdrant_start_time": tampered.qdrant_start_time,
                        "owner_start_time": tampered.owner_start_time,
                    }
                ),
                encoding="utf-8",
            )

            with pytest.raises(RuntimeError, match=expected_reason):
                start_supervised_from_config()
            assert first.is_alive()
            assert _port_is_listening(first.http_port)
        finally:
            first.stop()
            set_active_supervisor(None)


if sys.platform != "win32":

    def test_posix_attached_qdrant_publishes_existing_child_identity(
        tmp_path: Path,
    ) -> None:
        import vaultspec_rag.server as server_state

        from ..._machine_lock import (
            acquire_machine_lock_lease,
            release_machine_lock_lease,
        )
        from ...qdrant_runtime import (
            set_active_supervisor,
            start_supervised_from_config,
        )
        from ...server._lifecycle import _DiscoveryPublisher
        from ...server._lifespan import _stamp_qdrant_identity

        with _service_env(tmp_path):
            first = start_supervised_from_config()
            original_port = server_state._service_port
            original_token = server_state._SERVICE_TOKEN
            lease, holder = acquire_machine_lock_lease()
            assert lease is not None
            assert holder == os.getpid()
            discovery = _DiscoveryPublisher(lease)
            try:
                attached = start_supervised_from_config()
                assert attached.pid is None
                server_state._service_port = _get_ephemeral_port()
                server_state._SERVICE_TOKEN = "attached-qdrant-test-token"
                _stamp_qdrant_identity(attached, discovery)
                status = _read_service_status()
                assert status is not None
                assert status["qdrant_pid"] == first.pid
                assert float(status["qdrant_start_time"]) > 0.0
                published_identity = status["qdrant_identity"]

                server_state._heartbeat_tick_sync(discovery)

                after_heartbeat = _read_service_status()
                assert after_heartbeat is not None
                assert after_heartbeat["qdrant_pid"] == first.pid
                assert after_heartbeat["qdrant_identity"] == published_identity
                assert (
                    after_heartbeat["qdrant_start_time"] == status["qdrant_start_time"]
                )
            finally:
                discovery.quiesce()
                discovery.cleanup()
                release_machine_lock_lease(lease)
                server_state._service_port = original_port
                server_state._SERVICE_TOKEN = original_token
                first.stop()
                set_active_supervisor(None)

    def test_posix_restart_identity_failure_stops_new_child(tmp_path: Path) -> None:
        from ...qdrant_runtime import (
            set_active_supervisor,
            start_supervised_from_config,
        )
        from ...qdrant_runtime._resolve import qdrant_identity_path

        with _service_env(tmp_path):
            supervisor = start_supervised_from_config()
            identity_path = qdrant_identity_path()
            try:
                identity_path.unlink()
                identity_path.mkdir()
                assert supervisor.restart(timeout=15.0) is False
                assert supervisor.is_alive() is False
            finally:
                supervisor.stop()
                set_active_supervisor(None)

    def test_posix_ordinary_orphan_reap_revalidates_live_owner(
        tmp_path: Path,
    ) -> None:
        from ...qdrant_runtime import (
            set_active_supervisor,
            start_supervised_from_config,
        )
        from ...qdrant_runtime._resolve import read_qdrant_identity
        from ...qdrant_runtime._supervise import _reap_orphan_before_spawn

        with _service_env(tmp_path):
            supervisor = start_supervised_from_config()
            try:
                identity = read_qdrant_identity()
                assert identity is not None
                with pytest.raises(RuntimeError, match=r"recorded owner pid.*live"):
                    _reap_orphan_before_spawn(
                        supervisor.http_port,
                        identity,
                        "forced ordinary-reap safety regression",
                    )
                assert supervisor.is_alive()
                assert _port_is_listening(supervisor.http_port)
            finally:
                supervisor.stop()
                set_active_supervisor(None)

    @pytest.mark.parametrize("tampered_field", ["storage_path", "version", "http_port"])
    def test_posix_ordinary_orphan_reap_requires_complete_managed_witness(
        request: pytest.FixtureRequest,
        tmp_path: Path,
        tampered_field: str,
    ) -> None:
        """Ordinary startup refuses a real orphan with any mismatched witness."""
        from ...qdrant_runtime._resolve import (
            pid_start_time,
            read_qdrant_identity,
            reap_qdrant_orphan,
        )
        from ...qdrant_runtime._supervise import _reap_orphan_before_spawn

        with _service_env(tmp_path):
            service, qdrant_pid, qdrant_port = _spawn_posix_qdrant_owner()
            request.addfinalizer(
                lambda: _cleanup_forced_stop_harness(service, qdrant_pid)
            )
            identity = read_qdrant_identity()
            assert identity is not None
            actual_start = pid_start_time(qdrant_pid)
            assert actual_start > 0.0
            replacements: dict[str, object] = {
                "storage_path": str(tmp_path / "foreign-storage"),
                "version": "0.0.0",
                "http_port": qdrant_port + 1,
            }
            tampered = replace(
                identity,
                **{tampered_field: replacements[tampered_field]},
            )

            service.kill()
            service.wait(timeout=15.0)

            with pytest.raises(RuntimeError, match="complete managed"):
                _reap_orphan_before_spawn(
                    qdrant_port,
                    tampered,
                    f"tampered {tampered_field}",
                )
            assert _is_pid_alive(qdrant_pid)
            assert _port_is_listening(qdrant_port)
            assert reap_qdrant_orphan(
                qdrant_pid,
                expected_start_time=actual_start,
            )
            assert _wait_for_exit(qdrant_pid, timeout=15.0)
            assert _wait_for_listeners_closed(qdrant_port)

    def test_posix_forced_stop_reaps_validated_detached_qdrant(
        request: pytest.FixtureRequest,
        tmp_path: Path,
    ) -> None:
        """A SIGTERM-resistant owner cannot strand its real detached Qdrant."""
        with _service_env(tmp_path):
            service, qdrant_pid, qdrant_port = _spawn_posix_qdrant_owner()
            request.addfinalizer(
                lambda: _cleanup_forced_stop_harness(service, qdrant_pid)
            )
            assert _port_is_listening(qdrant_port)

            _terminate_pid(service.pid)

            assert service.wait(timeout=15.0) is not None
            assert _wait_for_exit(qdrant_pid, timeout=15.0)
            assert _wait_for_listeners_closed(qdrant_port)
            with pytest.raises(ProcessLookupError):
                os.getpgid(service.pid)
            with pytest.raises(ProcessLookupError):
                os.getpgid(qdrant_pid)

    def test_posix_forced_stop_rejects_unwitnessed_qdrant_identity(
        request: pytest.FixtureRequest,
        tmp_path: Path,
    ) -> None:
        """A legacy PID-only identity cannot authorize forced child reaping."""
        from ...config import get_config
        from ...qdrant_runtime._constants import QDRANT_SERVER_VERSION
        from ...qdrant_runtime._resolve import (
            reap_qdrant_orphan,
            write_qdrant_identity,
        )

        with _service_env(tmp_path):
            service, qdrant_pid, qdrant_port = _spawn_posix_qdrant_owner()
            request.addfinalizer(
                lambda: _cleanup_forced_stop_harness(service, qdrant_pid)
            )
            assert _port_is_listening(qdrant_port)
            write_qdrant_identity(
                storage_path=str(get_config().qdrant_storage_dir),
                version=QDRANT_SERVER_VERSION,
                owner_pid=service.pid,
                http_port=qdrant_port,
                qdrant_pid=qdrant_pid,
                owner_start_time=0.0,
            )

            _terminate_pid(service.pid)

            assert service.wait(timeout=15.0) is not None
            assert _is_pid_alive(qdrant_pid)
            assert _port_is_listening(qdrant_port)
            assert reap_qdrant_orphan(qdrant_pid)
            assert _wait_for_exit(qdrant_pid, timeout=15.0)
            assert _wait_for_listeners_closed(qdrant_port)

    @pytest.mark.parametrize("child_witness", ["missing", "mismatched"])
    def test_posix_forced_stop_rejects_unwitnessed_or_recycled_qdrant_child(
        request: pytest.FixtureRequest,
        tmp_path: Path,
        child_witness: str,
    ) -> None:
        """A missing or recycled-child witness cannot authorize signalling."""
        from ...config import get_config
        from ...qdrant_runtime._constants import QDRANT_SERVER_VERSION
        from ...qdrant_runtime._resolve import (
            pid_start_time,
            reap_qdrant_orphan,
            write_qdrant_identity,
        )

        with _service_env(tmp_path):
            service, qdrant_pid, qdrant_port = _spawn_posix_qdrant_owner()
            request.addfinalizer(
                lambda: _cleanup_forced_stop_harness(service, qdrant_pid)
            )
            actual_start = pid_start_time(qdrant_pid)
            assert actual_start > 0.0
            recorded_start = 0.0 if child_witness == "missing" else actual_start + 60.0
            write_qdrant_identity(
                storage_path=str(get_config().qdrant_storage_dir),
                version=QDRANT_SERVER_VERSION,
                owner_pid=service.pid,
                http_port=qdrant_port,
                qdrant_pid=qdrant_pid,
                qdrant_start_time=recorded_start,
            )

            _terminate_pid(service.pid)

            assert service.wait(timeout=15.0) is not None
            assert _is_pid_alive(qdrant_pid)
            assert _port_is_listening(qdrant_port)
            assert reap_qdrant_orphan(
                qdrant_pid,
                expected_start_time=actual_start,
            )
            assert _wait_for_exit(qdrant_pid, timeout=15.0)
            assert _wait_for_listeners_closed(qdrant_port)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_start_health_stop(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Spawn service, verify health, terminate, verify exit."""
    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))

        health = _poll_health(port)

        assert "status" in health
        assert "cuda" in health
        assert "models_loaded" in health
        assert "reranker_loaded" in health
        assert "uptime_s" in health
        assert "project_count" in health
        assert health["status"] == "ready"
        assert health["reranker_loaded"] is True
        assert health["project_count"] == 0

        _terminate_pid(pid)
        assert _wait_for_exit(pid), f"PID {pid} did not exit after terminate"
        assert not _is_pid_alive(pid)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
@pytest.mark.timeout(600)
def test_daemon_restart_restores_queued_work_and_preserves_paused_intent(
    tmp_path: Path,
    required_host_provisioned_qdrant_source: tuple[Path, Path],
) -> None:
    """Two real daemon lives retain exact durable queued and paused intent."""
    from ...job_manager import JobManager
    from ...job_models import (
        DesiredJobState,
        JobInitiator,
        JobMode,
        JobOperation,
        JobSource,
        JobSpec,
        JobState,
    )
    from ...synthetic import build_synthetic_vault

    queued_root = tmp_path / "queued-vault"
    paused_root = tmp_path / "paused-vault"
    build_synthetic_vault(queued_root, n_docs=24, seed=2201)
    paused_root.mkdir()
    state_path = tmp_path / "jobs-state.json"
    seed_manager = JobManager(state_path=state_path)
    queued = seed_manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            str(queued_root.resolve()),
            JobMode.INCREMENTAL,
        ),
        JobInitiator("integration", "restart queued probe", str(queued_root)),
    )
    paused = seed_manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            str(paused_root.resolve()),
            JobMode.INCREMENTAL,
        ),
        JobInitiator("integration", "restart paused probe", str(paused_root)),
        start_paused=True,
    )
    assert queued.job is not None
    assert paused.job is not None
    queued_id = queued.job.id
    paused_id = paused.job.id

    with _signalable_live_service(tmp_path, required_host_provisioned_qdrant_source):
        completed = _wait_for_persisted_job(
            state_path,
            queued_id,
            lambda job: job.state is JobState.SUCCEEDED,
            "restored queued intent did not execute",
        )
        dormant = _wait_for_persisted_job(
            state_path,
            paused_id,
            lambda job: job.state is JobState.PAUSED,
            "paused intent was not retained",
        )
        assert completed.attempt.number == 1
        assert completed.desired_state is DesiredJobState.RUNNING
        assert dormant.attempt.number == 1
        assert dormant.desired_state is DesiredJobState.PAUSED
        assert dormant.runtime.task_active is False
        assert dormant.runtime.worker_active is False

    stopped_paused = _wait_for_persisted_job(
        state_path,
        paused_id,
        lambda job: job.state is JobState.PAUSED,
        "clean shutdown did not preserve paused intent",
    )
    assert stopped_paused.desired_state is DesiredJobState.PAUSED

    with _signalable_live_service(tmp_path, required_host_provisioned_qdrant_source):
        restored_paused = _wait_for_persisted_job(
            state_path,
            paused_id,
            lambda job: job.state is JobState.PAUSED,
            "second daemon life did not restore paused intent",
        )
        restored_completed = _wait_for_persisted_job(
            state_path,
            queued_id,
            lambda job: job.state is JobState.SUCCEEDED,
            "completed queued work was lost on the second daemon life",
        )
        assert restored_paused.id == paused_id
        assert restored_paused.attempt.number == 1
        assert restored_paused.desired_state is DesiredJobState.PAUSED
        assert restored_paused.runtime.task_active is False
        assert restored_completed.id == queued_id
        assert restored_completed.attempt.number == 1

    output = (tmp_path / "service.log").read_text(encoding="utf-8", errors="replace")
    assert all(
        marker in output
        for marker in (
            "Canonical job manager ready: bound=2 dispatched=1",
            "Canonical job manager ready: bound=1 dispatched=0",
        )
    )


@pytest.mark.integration
@pytest.mark.subprocess_gpu
@pytest.mark.timeout(600)
def test_shutdown_interrupts_only_after_worker_release_then_reopens_store(
    tmp_path: Path,
    required_host_provisioned_qdrant_source: tuple[Path, Path],
) -> None:
    """Graceful daemon stop releases every owner before store teardown."""
    import httpx

    from ...job_models import JobState

    root = tmp_path / "live-code"
    source_dir = root / "src"
    source_dir.mkdir(parents=True)
    (root / ".vault").mkdir()
    for ordinal in range(512):
        (source_dir / f"shutdown_probe_{ordinal:04d}.py").write_text(
            f"def shutdown_probe_{ordinal:04d}() -> str:\n"
            f"    return 'worker release probe {ordinal:04d}'\n",
            encoding="utf-8",
        )

    state_path = tmp_path / "jobs-state.json"
    with _signalable_live_service(
        tmp_path,
        required_host_provisioned_qdrant_source,
    ) as (port, shutdown_pid):
        health = _poll_health(port)
        service_pid = int(health["pid"])
        status = _read_service_status()
        assert status is not None
        qdrant_pid = int(status["qdrant_pid"])
        qdrant_port = int(status["qdrant_port"])
        response = httpx.post(
            f"http://127.0.0.1:{port}/reindex",
            headers={"Authorization": f"Bearer {health['service_token']}"},
            json={
                "type": "code",
                "clean": False,
                "project_root": str(root),
            },
            timeout=30.0,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["ok"] is True
        job_id = str(payload["job_id"])

        live = _wait_for_persisted_job(
            state_path,
            job_id,
            _job_owns_full_pipeline,
            "real code attempt never published complete worker ownership",
        )
        assert live.resources.started is not None
        assert live.resources.finished is None

        _signal_service_shutdown(shutdown_pid)
        interrupted = _wait_for_persisted_job(
            state_path,
            job_id,
            lambda job: job.state is JobState.INTERRUPTED,
            "shutdown-signalled attempt did not become interrupted",
        )
        _assert_interrupted_after_release(interrupted)

        assert _wait_for_exit(service_pid, timeout=90.0)
        assert _wait_for_exit(qdrant_pid, timeout=30.0)
        assert _wait_for_listeners_closed(port, qdrant_port, timeout=30.0)

    output = (tmp_path / "service.log").read_text(encoding="utf-8", errors="replace")
    _assert_shutdown_log_order(output, job_id=job_id, qdrant_pid=qdrant_pid)

    with _signalable_live_service(
        tmp_path,
        required_host_provisioned_qdrant_source,
    ) as (restart_port, _shutdown_pid):
        restarted_health = _poll_health(restart_port)
        restarted_status = _read_service_status()
        assert restarted_status is not None
        assert int(restarted_status["qdrant_pid"]) != qdrant_pid
        restored = _wait_for_persisted_job(
            state_path,
            job_id,
            lambda job: job.state is JobState.INTERRUPTED,
            "interrupted result was not retained after daemon restart",
        )
        assert restored.runtime.task_active is False
        search = httpx.post(
            f"http://127.0.0.1:{restart_port}/search",
            headers={"Authorization": f"Bearer {restarted_health['service_token']}"},
            json={
                "type": "code",
                "query": "worker release probe",
                "top_k": 1,
                "project_root": str(root),
            },
            timeout=30.0,
        )
        assert search.status_code == 200, search.text


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_start_already_running(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Second start on the same port reports 'already in use'."""
    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        _poll_health(port)

        result = runner.invoke(
            app,
            ["server", "start", "--port", str(port)],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        assert "already running" in (result.stdout or "").lower(), (
            f"Expected 'already running' in output, got: {result.stdout!r}"
        )


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_stale_pid_recovery(tmp_path: Path) -> None:
    """Service start recovers from a stale PID in the status file."""
    with _service_env(tmp_path):
        port = _get_ephemeral_port()

        # Write a stale status file with a dead PID
        status_path = tmp_path / "service.json"
        stale_data = {
            "pid": 99999,
            "port": port,
            "started_at": "2026-01-01T00:00:00+00:00",
        }
        status_path.write_text(json.dumps(stale_data), encoding="utf-8")

        try:
            result2 = runner.invoke(
                app,
                ["server", "start", "--port", str(port)],
                env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
            )

            # The command should have started a fresh service
            new_status = _read_service_status()
            assert new_status is not None, (
                f"Expected new status file after stale recovery, got None. "
                f"CLI output: {result2.stdout!r}"
            )
            new_pid = int(new_status["pid"])
            assert new_pid != 99999
            assert _is_pid_alive(new_pid)

            health = _poll_health(port)
            assert health["status"] == "ready"
        finally:
            status = _read_service_status()
            if status is not None:
                pid = int(status["pid"])
                _terminate_pid(pid)
                _wait_for_exit(pid)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_stop_when_not_running(tmp_path: Path) -> None:
    """Stopping when no service is running reports appropriately."""
    with _service_env(tmp_path):
        result = runner.invoke(
            app,
            ["server", "stop"],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        output = (result.stdout or "").lower()
        assert "not running" in output or "no service status file" in output, (
            f"Expected stop message, got: {result.stdout!r}"
        )


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_stop_running_service(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Stop a running service via CLI and verify cleanup."""
    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        _poll_health(port)

        _write_service_status(pid, port)

        runner.invoke(
            app,
            ["server", "stop"],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )

        assert _wait_for_exit(pid), f"PID {pid} did not exit after stop"
        assert not _is_pid_alive(pid)
        assert not _status_file().exists(), "Status file should be removed after stop"


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_stop_running_service_by_port_without_status_file(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """``server stop --port`` stops a running daemon with no status file (F7).

    The status file is keyed per status dir and can diverge from (or be missing
    for) the running instance, so a non-default-port service was unstoppable by
    the verb. With ``--port`` the daemon's own /health identity resolves the
    serving pid and stop succeeds without ever reading the status file.
    """
    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        health = _poll_health(port)
        serving_pid = int(health["pid"])

        # The daemon now publishes before the parent. Remove that authoritative
        # file to recreate the case where discovery is absent even though the
        # daemon is genuinely running.
        _status_file().unlink()
        assert not _status_file().exists()

        result = runner.invoke(
            app,
            ["server", "stop", "--port", str(port)],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        assert "no such option" not in (result.stdout or "").lower()
        assert _wait_for_exit(serving_pid), (
            f"serving PID {serving_pid} did not exit after stop --port"
        )
        assert not _is_pid_alive(serving_pid)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_service_status_running(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """Status command shows running service details."""
    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        # Write service.json BEFORE the daemon finishes starting, mirroring
        # the production `service start` ordering (spawn -> write -> wait).
        # The daemon's initial heartbeat tick (fired after model load, inside
        # the lifespan) then finds the file and writes ``last_heartbeat``,
        # so status reports "running" rather than "crashed (heartbeat stale)".
        _write_service_status(pid, port)
        health = _poll_health(port)
        serving_pid = int(health["pid"])
        assert serving_pid > 0

        # Poll status until the daemon's heartbeat lands (the initial tick
        # races with model load); the loop heartbeat interval is 15s, so allow
        # margin. This asserts the steady-state "running", not a startup blip.
        deadline = time.monotonic() + 30.0
        output = ""
        while time.monotonic() < deadline:
            result2 = runner.invoke(
                app,
                ["server", "status"],
                env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
            )
            output = result2.stdout or ""
            if "running" in output.lower():
                break
            time.sleep(1.0)
        assert str(port) in output, f"Expected port {port} in output: {output!r}"
        assert "running" in output.lower(), f"Expected 'running' in output: {output!r}"

        json_result = runner.invoke(
            app,
            ["server", "status", "--json"],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        assert json_result.exit_code == 0
        payload = json.loads(json_result.stdout)
        data = payload["data"]
        assert data["state"] == "running"
        assert data["pid"] == serving_pid
        assert data["pid"] != pid or data["health"].get("parent_pid") == pid
        operational = data["operational"]
        assert operational["jobs"]["available"] is True
        assert "next_action" in operational


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_multi_project_search_isolation(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """Two projects indexed via MCP have isolated search results."""
    from ...synthetic import build_multi_project_fixture

    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        _poll_health(port)

        manifests = build_multi_project_fixture(
            tmp_path / "projects",
            n_projects=2,
            docs_per_project=6,
            seed=42,
        )

        # Inject a unique marker into project-0 only so we can
        # distinguish its search results from project-1.
        unique_marker = "XYZZY_ISOLATION_MARKER_PROJECT_ZERO"
        marker_doc = manifests[0].root / ".vault" / "adr" / "isolation-probe.md"
        marker_doc.write_text(
            '---\ntags:\n  - "#adr"\n  - "#isolation"\n'
            "date: 2026-01-01\nrelated:\n  []\n---\n\n"
            f"# isolation probe\n\n{unique_marker}\n",
            encoding="utf-8",
        )

        async def _mcp_call(
            test_port: int,
            tool_name: str,
            arguments: dict[str, object],
        ) -> str:
            """One REST call per session (matches production pattern)."""
            import json

            import httpx

            from ._helpers import _poll_health

            health = _poll_health(test_port)
            token = health["service_token"]

            async with httpx.AsyncClient() as client:
                if tool_name == "reindex_vault":
                    resp = await client.post(
                        f"http://127.0.0.1:{test_port}/reindex",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"type": "vault", **arguments},
                        timeout=30.0,
                    )
                    assert resp.status_code == 200, f"reindex_vault failed: {resp.text}"
                    return resp.text
                elif tool_name == "search_vault":
                    resp = await client.post(
                        f"http://127.0.0.1:{test_port}/search",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"type": "vault", **arguments},
                        timeout=30.0,
                    )
                    assert resp.status_code == 200, f"search_vault failed: {resp.text}"
                    # Return string format because the test expects to json.load it
                    return json.dumps(resp.json()["results"])
                elif tool_name == "get_jobs":
                    resp = await client.get(
                        f"http://127.0.0.1:{test_port}/jobs",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"limit": int(str(arguments.get("limit", 50)))},
                        timeout=30.0,
                    )
                    assert resp.status_code == 200, f"get_jobs failed: {resp.text}"
                    return resp.text
                raise ValueError(f"Unknown tool_name: {tool_name}")

        # Index both projects (one session per call)
        for m in manifests:
            try:
                res_text = asyncio.run(
                    _mcp_call(
                        port,
                        "reindex_vault",
                        {"clean": True, "project_root": str(m.root)},
                    ),
                )
                res = json.loads(res_text)
                assert res.get("ok") is True
                job_id = res.get("job_id")
                assert job_id is not None

                # Wait for background job to finish
                for _ in range(100):
                    jobs_text = asyncio.run(
                        _mcp_call(
                            port,
                            "get_jobs",
                            {"limit": 50},
                        ),
                    )
                    jobs_data = json.loads(jobs_text)
                    jobs = jobs_data.get("jobs", [])
                    matched = [j for j in jobs if j.get("id") == job_id]
                    if matched and matched[0].get("phase") in (
                        "done",
                        "error",
                        "failed",
                    ):
                        break
                    time.sleep(0.1)
            except BaseException:
                # Dump service log on failure for diagnosis
                if log_path.exists():
                    log_tail = log_path.read_text(encoding="utf-8")[-2000:]
                    pytest.fail(
                        f"reindex_vault failed for {m.root}.\n"
                        f"Service log (last 2000 chars):\n{log_tail}"
                    )
                raise

        # Search project-0 for the unique marker - must be found
        text_0 = asyncio.run(
            _mcp_call(
                port,
                "search_vault",
                {
                    "query": unique_marker,
                    "top_k": 5,
                    "project_root": str(manifests[0].root),
                },
            ),
        )
        assert unique_marker in text_0 or "isolation-probe" in text_0, (
            "Unique marker not found in project-0 results"
        )

        # Search project-1 for the same marker - must NOT appear
        text_1 = asyncio.run(
            _mcp_call(
                port,
                "search_vault",
                {
                    "query": unique_marker,
                    "top_k": 5,
                    "project_root": str(manifests[1].root),
                },
            ),
        )
        assert unique_marker not in text_1 and "isolation-probe" not in text_1, (
            f"project-0 marker leaked into project-1 results: {text_1[:500]}"
        )


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
from starlette.applications import Starlette
from starlette.routing import Route

import vaultspec_rag.server as server
from vaultspec_rag._machine_lock import (
    acquire_machine_lock_lease,
    release_machine_lock_lease,
)
from vaultspec_rag.server._lifespan import health_handler

server._SERVICE_TOKEN = os.environ["VAULTSPEC_TEST_HEALTH_TOKEN"]
lease = None
if os.environ["VAULTSPEC_TEST_HOLD_MACHINE_LOCK"] == "1":
    lease, holder = acquire_machine_lock_lease()
    if lease is None:
        raise RuntimeError(f"machine lock held by {holder}")
try:
    uvicorn.run(
        Starlette(routes=[Route("/health", health_handler)]),
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
            port = _get_ephemeral_port()
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
            serving_pid = int(health["pid"])
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


def test_reconcile_rejects_live_legacy_status_without_singleton_owner(
    tmp_path: Path,
) -> None:
    """A reachable legacy record cannot stand in for singleton ownership."""
    from ..._machine_lock import machine_lock_live_holder

    with (
        _service_env(tmp_path),
        _identity_health_process(tmp_path, hold_machine_lock=False) as (
            pid,
            port,
            token,
        ),
    ):
        assert machine_lock_live_holder() == 0
        _status_file().write_text(
            json.dumps({"pid": pid, "port": port, "service_token": token}),
            encoding="utf-8",
        )

        result = runner.invoke(
            app,
            ["server", "reconcile", "--json", "--timeout", "0"],
        )

        assert result.exit_code == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"] == "unresolved"
        discovery = payload["data"]["service"]["discovery"]
        assert discovery["source"] == "status_file"
        assert discovery["holder_pid"] == 0
        assert _is_pid_alive(pid)


@pytest.mark.parametrize("missing_field", ["pid", "service_token"])
def test_reconcile_rejects_machine_pointer_with_incomplete_identity(
    tmp_path: Path,
    missing_field: str,
) -> None:
    """A live holder cannot converge until every pointer identity field exists."""
    from datetime import UTC, datetime

    from ..._machine_lock import machine_discovery_path, machine_lock_live_holder

    with (
        _service_env(tmp_path),
        _identity_health_process(tmp_path, hold_machine_lock=True) as (
            pid,
            port,
            token,
        ),
    ):
        assert machine_lock_live_holder() == pid
        pointer = {
            "pid": pid,
            "port": port,
            "service_token": token,
            "last_heartbeat": datetime.now(UTC).isoformat(timespec="seconds"),
            "stale_after_s": 60,
        }
        pointer.pop(missing_field)
        machine_discovery_path().write_text(
            json.dumps(pointer),
            encoding="utf-8",
        )

        result = runner.invoke(
            app,
            ["server", "reconcile", "--json", "--timeout", "0"],
        )

        assert result.exit_code == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"] == "unresolved"
        discovery = payload["data"]["service"]["discovery"]
        assert discovery["source"] == "machine_pointer"
        assert discovery["holder_pid"] == pid
        assert _is_pid_alive(pid)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_deleted_discovery_views_self_heal_on_the_next_heartbeat(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """Both owner-published discovery views repair without a restart.

    Deleting the status file and the machine pointer under a live isolated
    daemon must converge on the next heartbeat from daemon-owned state, and
    each view must repair independently of the other's presence.
    """
    from ..._machine_lock import machine_discovery_path

    # One heartbeat interval is 15s; allow three so a tick that races the
    # deletion cannot fail the assertion.
    repair_timeout = 50.0

    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        health = _poll_health(port)
        serving_pid = int(health["pid"])
        _write_service_status(pid, port)

        status_path = _status_file()
        pointer_path = machine_discovery_path()

        # Both views must exist before the corruption is meaningful.
        _wait_for_discovery_repair(status_path, timeout=repair_timeout)
        _wait_for_discovery_repair(pointer_path, timeout=repair_timeout)

        # Deleting only the pointer must not disturb the status file.
        pointer_path.unlink()
        assert not pointer_path.exists()
        repaired_pointer = _wait_for_discovery_repair(
            pointer_path,
            timeout=repair_timeout,
        )
        assert status_path.exists(), (
            "status view was collaterally removed by pointer repair"
        )
        assert repaired_pointer["pid"] == serving_pid
        assert repaired_pointer["port"] == port
        assert repaired_pointer["phase"] == "running"
        assert repaired_pointer["service_token"], (
            "repaired pointer must carry the daemon identity token"
        )

        # Deleting only the status file must not disturb the pointer.
        status_path.unlink()
        assert not status_path.exists()
        repaired_status = _wait_for_discovery_repair(
            status_path,
            timeout=repair_timeout,
        )
        assert pointer_path.exists(), (
            "machine pointer was collaterally removed by status repair"
        )
        assert repaired_status["pid"] == serving_pid
        assert repaired_status["port"] == port
        assert repaired_status["service_token"] == repaired_pointer["service_token"]

        # Deleting both together must repair both from one snapshot.
        status_path.unlink()
        pointer_path.unlink()
        both_status = _wait_for_discovery_repair(status_path, timeout=repair_timeout)
        both_pointer = _wait_for_discovery_repair(pointer_path, timeout=repair_timeout)
        assert both_status["pid"] == serving_pid
        assert both_pointer["pid"] == serving_pid
        assert both_status["service_token"] == both_pointer["service_token"]


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_shutdown_cleanup_cannot_be_resurrected_by_a_late_heartbeat(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """Owner cleanup is terminal: no later tick republishes either view.

    The publisher quiesces before periodic tasks are cancelled, so an
    already-running heartbeat worker finishes behind the same guard and every
    later tick is inert. After a clean stop both views must stay absent well
    past one heartbeat interval.
    """
    from ..._machine_lock import machine_discovery_path

    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        health = _poll_health(port)
        serving_pid = int(health["pid"])
        _write_service_status(pid, port)

        status_path = _status_file()
        pointer_path = machine_discovery_path()
        _wait_for_discovery_repair(status_path, timeout=50.0)
        _wait_for_discovery_repair(pointer_path, timeout=50.0)

        result = runner.invoke(
            app,
            ["server", "stop"],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        assert result.exit_code == 0, f"stop failed: {result.stdout!r}"
        assert _wait_for_exit(serving_pid), (
            f"serving PID {serving_pid} did not exit after stop"
        )

        assert not status_path.exists(), "status view survived owner cleanup"
        assert not pointer_path.exists(), "machine pointer survived owner cleanup"

        # Hold past one full heartbeat interval so a surviving periodic task
        # would have to republish inside the window.
        _assert_discovery_absent((status_path, pointer_path), held_for=20.0)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_reconcile_recovers_discovery_without_touching_the_daemon(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """Reconcile repairs every corrupted pointer shape non-destructively.

    The singleton owner is the only process permitted to publish its pointer,
    so reconcile waits for that owner's own heartbeat rather than writing
    anything itself. The daemon must therefore survive every round untouched:
    same process, same identity, never restarted.
    """
    import json as _json
    from datetime import UTC, datetime, timedelta

    from ..._machine_lock import machine_discovery_path

    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        health = _poll_health(port)
        serving_pid = int(health["pid"])
        _write_service_status(pid, port)

        pointer_path = machine_discovery_path()
        original = _wait_for_discovery_repair(pointer_path, timeout=50.0)
        assert original["pid"] == serving_pid

        def corrupt_deleted() -> None:
            pointer_path.unlink()

        def corrupt_stale() -> None:
            stale = dict(original)
            stale["last_heartbeat"] = (
                datetime.now(UTC) - timedelta(hours=2)
            ).isoformat(timespec="seconds")
            pointer_path.write_text(_json.dumps(stale), encoding="utf-8")

        def corrupt_foreign() -> None:
            foreign = dict(original)
            foreign["pid"] = 2_000_000_000
            pointer_path.write_text(_json.dumps(foreign), encoding="utf-8")

        for label, corrupt in (
            ("deleted", corrupt_deleted),
            ("stale", corrupt_stale),
            ("foreign", corrupt_foreign),
        ):
            corrupt()
            result = runner.invoke(
                app,
                ["server", "reconcile", "--json", "--timeout", "60"],
                env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
            )
            assert result.exit_code == 0, (
                f"reconcile did not converge after a {label} pointer: {result.stdout!r}"
            )
            payload = json.loads(result.stdout)
            assert payload["ok"] is True
            data = payload["data"]
            assert data["converged"] is True
            assert data["status"] in {"already_converged", "converged"}

            # The owner republished its own pointer, and it names the same
            # live daemon as before.
            repaired = _wait_for_discovery_repair(pointer_path, timeout=50.0)
            assert repaired["pid"] == serving_pid, (
                f"pointer named a different process after the {label} round"
            )
            assert repaired["port"] == port

            # Reconcile is non-destructive: same process, still serving.
            assert _is_pid_alive(serving_pid), (
                f"daemon died during the {label} reconcile round"
            )
            live = _poll_health(port)
            assert int(live["pid"]) == serving_pid, (
                f"daemon was restarted during the {label} reconcile round"
            )

        # Idempotent: a reconcile against an already-agreeing machine is a
        # success, not a no-op failure a caller has to special-case.
        again = runner.invoke(
            app,
            ["server", "reconcile", "--json"],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        assert again.exit_code == 0
        assert json.loads(again.stdout)["data"]["status"] == "already_converged"
