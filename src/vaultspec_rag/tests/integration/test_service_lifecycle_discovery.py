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
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ..._process_probe import pid_alive
from ...cli import app
from ...cli._process import _spawn_service, _terminate_pid
from ...cli._service_status import (
    _status_file,
    _write_service_status,
)
from .._ports import free_loopback_port
from ._helpers import (
    _poll_health,
    _service_env,
    _wait_for_exit,
)
from ._service_lifecycle_helpers import (
    _assert_discovery_absent,
    _identity_health_process,
    _wait_for_discovery_repair,
)

if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()

pytestmark = [pytest.mark.integration]


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
        assert pid_alive(pid)


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
        assert pid_alive(pid)


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
        port = free_loopback_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        health = _poll_health(port)
        serving_pid = int(str(health["pid"]))
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
        port = free_loopback_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        health = _poll_health(port)
        serving_pid = int(str(health["pid"]))
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
        port = free_loopback_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        health = _poll_health(port)
        serving_pid = int(str(health["pid"]))
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
            assert pid_alive(serving_pid), (
                f"daemon died during the {label} reconcile round"
            )
            live = _poll_health(port)
            assert int(str(live["pid"])) == serving_pid, (
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


# The witness the daemon's forced-exit backstop logs immediately before calling
# ``os._exit``. A daemon that reached a natural interpreter exit never writes it,
# which is what makes its presence positive evidence that the backstop fired
# rather than that the process happened to end on its own.
_FORCED_DAEMON_EXIT_WITNESS = "Forcing daemon process exit after bounded shutdown"

# The daemon spends most of a lost race importing: a cold interpreter reaches the
# singleton claim in roughly forty seconds on a developer machine, and the claim
# itself refuses immediately once reached. The bound is generous against that
# measurement so a slow host reports a real hang, never a tight deadline.
_LOSING_DAEMON_EXIT_BOUND_SECONDS = 180.0


@pytest.mark.timeout(300)
def test_race_losing_daemon_self_exits(tmp_path: Path) -> None:
    """A daemon that loses the machine-singleton claim forces its own exit.

    This process holds the machine lock, so the spawned daemon must fail its
    claim, and it must leave through the forced-exit backstop rather than by
    whatever the interpreter would have done next. The distinction is the whole
    point: an unguarded failure path also ends this particular process (nothing
    is wedged this early in startup), so asserting only that the process died
    would pass with the backstop deleted. The log witness is what binds - remove
    the backstop and the daemon leaves without it, exiting zero besides, because
    a lifespan startup failure is something uvicorn returns from rather than
    raises.

    The cause is asserted too. Without it a daemon that died of an unrelated
    startup failure - a port already taken, a missing binary - would satisfy
    every other assertion here and report the singleton path as covered.
    """
    from ..._machine_lock import (
        acquire_machine_lock_lease,
        machine_lock_path,
        release_machine_lock_lease,
    )

    with _service_env(tmp_path):
        machine_lock_path().parent.mkdir(parents=True, exist_ok=True)
        lease, _holder = acquire_machine_lock_lease()
        assert lease is not None, "test must hold the machine lock"
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if sys.platform == "win32"
            else 0
        )
        port = free_loopback_port()
        # The daemon redirects its own captured output into the managed log at
        # this same path, so one file carries both the spawn pipe and the
        # daemon's own lines.
        log_path = tmp_path / "service.log"
        try:
            with log_path.open("ab") as output:
                process = subprocess.Popen(
                    [sys.executable, "-m", "vaultspec_rag.server", "--port", str(port)],
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    cwd=tmp_path,
                    creationflags=creationflags,
                    start_new_session=sys.platform != "win32",
                )
            try:
                deadline = time.monotonic() + _LOSING_DAEMON_EXIT_BOUND_SECONDS
                while time.monotonic() < deadline and process.poll() is None:
                    time.sleep(0.1)
                assert process.poll() is not None, (
                    "a race-losing daemon must self-exit, not linger"
                )
                assert process.returncode != 0, "a failed claim must exit non-zero"
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
            log = log_path.read_text(encoding="utf-8", errors="replace")
            assert "already owns this machine" in log, (
                f"the daemon did not exit on the singleton claim; log:\n{log[-3000:]}"
            )
            assert str(os.getpid()) in log, (
                f"the refusal did not name this test as the holder; log:\n{log[-3000:]}"
            )
            assert f"{_FORCED_DAEMON_EXIT_WITNESS} (code=1)" in log, (
                "the daemon did not leave through the forced-exit backstop; "
                f"log:\n{log[-3000:]}"
            )
        finally:
            release_machine_lock_lease(lease)
