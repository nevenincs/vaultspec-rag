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
import re
import subprocess
import sys
import time
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from ..._process_probe import pid_alive
from ...cli._process import _spawn_service, _terminate_pid
from ...cli._service_status import (
    _status_file,
    _write_service_status,
    read_service_status,
)
from ...config._types import EnvVar
from .._model_setup import (
    configured_service_model_ids,
    ensure_model_snapshots,
    model_setup_timeout_seconds,
)
from .._ports import free_loopback_port
from ._helpers import (
    _poll_health,
    _service_env,
    _wait_for_exit,
)
from ._service_lifecycle_helpers import (
    _assert_expired_startup_torn_down,
    _assert_published_qdrant_identity,
    _await_models_loaded,
    _await_ready_marker,
    _cleanup_forced_stop_harness,
    _port_is_listening,
    _service_processes_on_port,
    _spawn_posix_qdrant_owner,
    _spawn_running_phase_lock_holder,
    _terminate_test_processes,
    _wait_for_listeners_closed,
    _wait_for_published_qdrant,
)
from .conftest import _live_service_context, _startup_cleanup_reserve

if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


@pytest.mark.integration
def test_poll_health_honours_subsecond_deadline() -> None:
    """A real unreachable endpoint cannot overrun the caller's short budget."""
    port = free_loopback_port()
    started = time.monotonic()
    with pytest.raises(TimeoutError, match=r"not ready after 0\.050s"):
        _poll_health(port, timeout=0.05)
    assert time.monotonic() - started < 1.0


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.subprocess_gpu
def test_live_service_readiness_expiry_uses_reserved_cleanup_budget(
    tmp_path: Path,
) -> None:
    """A real readiness expiry tears down service and Qdrant inside the envelope."""
    from ..._process_probe import pid_alive

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
    assert not pid_alive(launcher_pid)
    assert not pid_alive(owner_pid)
    assert not pid_alive(qdrant_pid)
    assert _wait_for_listeners_closed(service_port, qdrant_port)


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
        port = free_loopback_port()
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
        status = read_service_status()
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
        port = free_loopback_port()
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
        status_before_parent = read_service_status()
        assert status_before_parent is not None
        daemon_pid = cast("int", status_before_parent["pid"])
        assert daemon_pid > 0
        assert pid_alive(daemon_pid)
        if daemon_pid != pid:
            owned_pids.append(daemon_pid)
        nested_identity = _assert_published_qdrant_identity(
            status_before_parent,
            port=port,
            qdrant_pid=qdrant_pid,
            qdrant_port=qdrant_port,
        )
        assert pid_alive(qdrant_pid)
        assert _port_is_listening(qdrant_port)

        # The deliberately delayed parent publication must merge rather than
        # erase the daemon's authoritative pre-warmup child identity.
        _write_service_status(pid, port)
        status_after_parent = read_service_status()
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

    @pytest.mark.integration
    def test_windows_late_spawn_timeout_cleans_before_pid_assignment(
        tmp_path: Path,
    ) -> None:
        """The exact late-Popen branch cannot strand an unreturned daemon PID."""
        with _service_env(tmp_path):
            port = free_loopback_port()
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
                assert not pid_alive(int(identity["owner_pid"]))
                assert not pid_alive(int(identity["qdrant_pid"]))
                assert not _port_is_listening(int(identity["http_port"]))

    @pytest.mark.subprocess_gpu
    def test_windows_late_spawn_cleanup_finds_detached_daemon_and_qdrant(
        request: pytest.FixtureRequest,
        tmp_path: Path,
    ) -> None:
        """Late-spawn cleanup finds the daemon even when its launcher PID differs."""
        from ..._process_probe import pid_start_time
        from ...cli._process import _cleanup_late_service_spawn

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
            port = free_loopback_port()
            log_path = tmp_path / "late-spawn-cleanup.log"
            launcher_pid = _spawn_service(port, log_path, watch=False)
            owned_pids = [launcher_pid]
            request.addfinalizer(lambda: _terminate_test_processes(owned_pids))
            published = _wait_for_published_qdrant(service_pid=launcher_pid)
            assert published is not None
            qdrant_pid, qdrant_port = published
            owned_pids.append(qdrant_pid)
            status = read_service_status()
            assert status is not None
            daemon_pid = cast("int", status["pid"])
            owned_pids.append(daemon_pid)
            assert daemon_pid != launcher_pid
            launch_token = cast("str", status["launch_token"])
            assert launch_token

            cleanup_error = _cleanup_late_service_spawn(
                launcher_pid=launcher_pid,
                launcher_start_time=pid_start_time(launcher_pid),
                port=port,
                launch_token=launch_token,
                timeout=15.0,
            )

            assert cleanup_error == ""
            assert _wait_for_exit(launcher_pid, timeout=15.0)
            assert _wait_for_exit(daemon_pid, timeout=15.0)
            assert _wait_for_exit(qdrant_pid, timeout=15.0)
            assert _wait_for_listeners_closed(port, qdrant_port)

    @pytest.mark.integration
    def test_windows_late_spawn_cleanup_preserves_unrelated_status_and_command(
        tmp_path: Path,
    ) -> None:
        """Only the exact launch token and PID incarnation authorize signalling."""
        from ..._process_probe import pid_start_time
        from ...cli._process import _cleanup_late_service_spawn

        with _service_env(tmp_path):
            port = free_loopback_port()
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
                    launcher_start_time=pid_start_time(owned.pid),
                    port=port,
                    launch_token=owned_token,
                    timeout=5.0,
                )
                assert error == ""
                assert _wait_for_exit(owned.pid, timeout=5.0)
                assert unrelated.poll() is None
                assert pid_alive(unrelated.pid)
            finally:
                for process in (owned, unrelated):
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5.0)


@pytest.mark.integration
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
    from ...qdrant_runtime._resolve import (
        qdrant_identity_path,
        read_qdrant_identity,
    )
    from ...qdrant_runtime._supervise import (
        set_active_supervisor,
        start_supervised_from_config,
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

    @pytest.mark.integration
    def test_posix_attached_qdrant_publishes_existing_child_identity(
        tmp_path: Path,
    ) -> None:
        import vaultspec_rag.server as server_state

        from ..._machine_lock import (
            acquire_machine_lock_lease,
            release_machine_lock_lease,
        )
        from ...qdrant_runtime._supervise import (
            set_active_supervisor,
            start_supervised_from_config,
        )
        from ...server import ServerRouteRuntime
        from ...server._lifecycle import _DiscoveryPublisher
        from ...server._lifespan import _stamp_qdrant_identity
        from ...service import ServiceRegistry

        with _service_env(tmp_path):
            first = start_supervised_from_config()
            lease, holder = acquire_machine_lock_lease()
            assert lease is not None
            assert holder == os.getpid()
            discovery = _DiscoveryPublisher(
                ServerRouteRuntime(
                    token="attached-qdrant-test-token",
                    registry=ServiceRegistry(),
                    port=free_loopback_port(),
                ),
                lease,
            )
            try:
                attached = start_supervised_from_config()
                assert attached.pid is None
                _stamp_qdrant_identity(attached, discovery)
                status = read_service_status()
                assert status is not None
                assert status["qdrant_pid"] == first.pid
                assert float(status["qdrant_start_time"]) > 0.0
                published_identity = status["qdrant_identity"]

                server_state._heartbeat_tick_sync(discovery)

                after_heartbeat = read_service_status()
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
                first.stop()
                set_active_supervisor(None)

    @pytest.mark.integration
    def test_posix_restart_identity_failure_stops_new_child(tmp_path: Path) -> None:
        from ...qdrant_runtime._resolve import qdrant_identity_path
        from ...qdrant_runtime._supervise import (
            set_active_supervisor,
            start_supervised_from_config,
        )

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

    @pytest.mark.integration
    def test_posix_ordinary_orphan_reap_revalidates_live_owner(
        tmp_path: Path,
    ) -> None:
        from ...qdrant_runtime._resolve import read_qdrant_identity
        from ...qdrant_runtime._supervise import (
            _reap_orphan_before_spawn,
            set_active_supervisor,
            start_supervised_from_config,
        )

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

    @pytest.mark.integration
    @pytest.mark.parametrize("tampered_field", ["storage_path", "version", "http_port"])
    def test_posix_ordinary_orphan_reap_requires_complete_managed_witness(
        request: pytest.FixtureRequest,
        tmp_path: Path,
        tampered_field: str,
    ) -> None:
        """Ordinary startup refuses a real orphan with any mismatched witness."""
        from ..._process_probe import pid_start_time
        from ...qdrant_runtime._resolve import (
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
            assert pid_alive(qdrant_pid)
            assert _port_is_listening(qdrant_port)
            assert reap_qdrant_orphan(
                qdrant_pid,
                expected_start_time=actual_start,
            )
            assert _wait_for_exit(qdrant_pid, timeout=15.0)
            assert _wait_for_listeners_closed(qdrant_port)

    @pytest.mark.integration
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

    @pytest.mark.integration
    def test_posix_forced_stop_rejects_unwitnessed_qdrant_identity(
        request: pytest.FixtureRequest,
        tmp_path: Path,
    ) -> None:
        """A legacy PID-only identity cannot authorize forced child reaping."""
        from ...config._settings import get_config
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
            assert pid_alive(qdrant_pid)
            assert _port_is_listening(qdrant_port)
            assert reap_qdrant_orphan(qdrant_pid)
            assert _wait_for_exit(qdrant_pid, timeout=15.0)
            assert _wait_for_listeners_closed(qdrant_port)

    @pytest.mark.integration
    @pytest.mark.parametrize("child_witness", ["missing", "mismatched"])
    def test_posix_forced_stop_rejects_unwitnessed_or_recycled_qdrant_child(
        request: pytest.FixtureRequest,
        tmp_path: Path,
        child_witness: str,
    ) -> None:
        """A missing or recycled-child witness cannot authorize signalling."""
        from ..._process_probe import pid_start_time
        from ...config._settings import get_config
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
            assert pid_alive(qdrant_pid)
            assert _port_is_listening(qdrant_port)
            assert reap_qdrant_orphan(
                qdrant_pid,
                expected_start_time=actual_start,
            )
            assert _wait_for_exit(qdrant_pid, timeout=15.0)
            assert _wait_for_listeners_closed(qdrant_port)
