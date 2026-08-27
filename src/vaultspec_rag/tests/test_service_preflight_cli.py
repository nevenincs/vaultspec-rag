"""Real transport coverage for the non-authorizing service preflight CLI."""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import uvicorn
from typer.testing import CliRunner

from ..cli import app
from ..config._paths import SERVICE_STATUS_FILENAME
from ..service import ServiceRegistry
from ..serviceclient._compat import SERVICE_VERSION_FIELD, local_package_version
from ..serviceclient._discovery import (
    HEARTBEAT_STALENESS_SECONDS,
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
    _replace_service_status,
)
from ..serviceclient._transport import _try_http_admin
from ._child_signal import await_marker, child_stderr
from ._import_probe import assert_fresh_import_excludes, import_probe_source
from ._ports import free_loopback_port
from ._production_service import CHILD_PROCESS_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = [pytest.mark.unit]

_SERVICE_TOKEN = "service-preflight-route-token"
_AMBIENT_SERVICE_TOKEN = "isolated-ambient-status-token"
runner = CliRunner()


def _publish_discovery(
    status_dir: Path,
    *,
    port: int,
    overrides: dict[str, object] | None = None,
) -> None:
    """Publish the real route host through the production discovery writer."""
    payload: dict[str, object] = {
        "pid": os.getpid(),
        "port": port,
        "schema": SERVICE_DISCOVERY_SCHEMA,
        "version": SERVICE_DISCOVERY_VERSION,
        SERVICE_VERSION_FIELD: local_package_version(),
        "service_token": _SERVICE_TOKEN,
        "last_heartbeat": datetime.now(UTC).isoformat(timespec="seconds"),
        "stale_after_s": HEARTBEAT_STALENESS_SECONDS,
    }
    if overrides is not None:
        payload.update(overrides)
    _replace_service_status(payload, path=status_dir / SERVICE_STATUS_FILENAME)


_MACHINE_POINTER_ROUTE_HOST = """
import os
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from vaultspec_rag._machine_lock import (
    acquire_machine_lock_lease,
    delete_machine_discovery,
    publish_machine_discovery,
    release_machine_lock_lease,
)
from vaultspec_rag.server import ServerRouteRuntime, create_http_app
from vaultspec_rag.service import ServiceRegistry
from vaultspec_rag.serviceclient._compat import (
    SERVICE_VERSION_FIELD,
    local_package_version,
)
from vaultspec_rag.serviceclient._discovery import (
    HEARTBEAT_STALENESS_SECONDS,
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
)
from vaultspec_rag.tests._child_signal import publish_marker

port = int(sys.argv[1])
ready_path = Path(sys.argv[2])
stop_path = Path(sys.argv[3])
token = "service-preflight-route-token"
lease, holder = acquire_machine_lock_lease()
assert lease is not None, holder
server = uvicorn.Server(
    uvicorn.Config(
        create_http_app(
            ServerRouteRuntime(token=token, registry=ServiceRegistry(), port=port),
            lifespan=None,
        ),
        host="127.0.0.1",
        port=port,
        log_config=None,
        access_log=False,
        lifespan="off",
    )
)
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
try:
    deadline = time.monotonic() + 10.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started, "production route server did not start"
    publish_machine_discovery(
        lease,
        {
            "pid": os.getpid(),
            "port": port,
            "schema": SERVICE_DISCOVERY_SCHEMA,
            "version": SERVICE_DISCOVERY_VERSION,
            SERVICE_VERSION_FIELD: local_package_version(),
            "service_token": token,
            "last_heartbeat": datetime.now(UTC).isoformat(timespec="seconds"),
            "stale_after_s": HEARTBEAT_STALENESS_SECONDS,
        },
    )
    publish_marker(ready_path, "ready")
    while not stop_path.exists():
        time.sleep(0.01)
finally:
    server.should_exit = True
    thread.join(timeout=10.0)
    delete_machine_discovery(lease)
    release_machine_lock_lease(lease)
"""


@contextlib.contextmanager
def _machine_pointer_service(
    tmp_path: Path,
    *,
    server_root: Path | None = None,
) -> Generator[int]:
    """Host real routes behind a contended, machine-global discovery pointer."""
    ready_path = tmp_path / "machine-route-ready"
    stop_path = tmp_path / "machine-route-stop"
    ready_path.unlink(missing_ok=True)
    stop_path.unlink(missing_ok=True)
    port = free_loopback_port()
    environment = os.environ.copy()
    source_root = str(Path.cwd() / "src")
    inherited_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_root if not inherited_path else source_root + os.pathsep + inherited_path
    )
    with child_stderr() as diagnostics:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _MACHINE_POINTER_ROUTE_HOST,
                str(port),
                str(ready_path),
                str(stop_path),
            ],
            cwd=server_root or Path.cwd(),
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=diagnostics.sink,
            text=True,
        )
        try:
            ready = await_marker(
                ready_path, process, timeout=CHILD_PROCESS_TIMEOUT_SECONDS
            )
            assert ready == "ready", (
                f"machine route host did not publish discovery: {diagnostics.read()}"
            )
            yield port
        finally:
            if process.poll() is None:
                stop_path.write_text("stop", encoding="ascii")
            try:
                process.wait(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)
            assert process.returncode == 0, diagnostics.read()


@contextlib.contextmanager
def _production_service(
    status_dir: Path,
    *,
    reported_port_offset: int = 0,
) -> Generator[tuple[ServiceRegistry, int]]:
    """Serve the real authenticated route table without the daemon lifespan."""
    from ..server import ServerRouteRuntime, create_http_app

    registry = ServiceRegistry()
    port = free_loopback_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_http_app(
                ServerRouteRuntime(
                    token=_SERVICE_TOKEN,
                    registry=registry,
                    port=port + reported_port_offset,
                ),
                lifespan=None,
            ),
            host="127.0.0.1",
            port=port,
            log_config=None,
            access_log=False,
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        _publish_discovery(status_dir, port=port)
        yield registry, port
    finally:
        _try_http_admin("resume_service", {}, port)
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_preflight_observes_safe_service_but_never_authorizes_gpu(
    isolated_status_dir: Path,
) -> None:
    """A safe remote snapshot succeeds only as an observation, never a grant."""
    with _production_service(isolated_status_dir) as (_registry, port):
        pause = _try_http_admin("pause_service", {}, port)
        assert pause is not None, "the real pause route did not answer"
        assert pause["status"] == "quiesced", pause
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 0, result.output
    assert len(result.output.splitlines()) == 1, result.output
    assert '"ok": true' in result.output
    assert '"source": "service"' in result.output
    assert f'"port": {port}' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output
    assert (
        '"authorization": "A borrower lease is required before GPU work may begin."'
        in result.output
    )
    assert '"state": "quiesced"' in result.output
    assert '"safe_to_borrow_gpu": true' in result.output
    assert '"capacity": {' in result.output


def test_preflight_refuses_a_discovered_service_that_is_not_safe(
    isolated_status_dir: Path,
) -> None:
    """Running is observable, but only acknowledged quiescence is safe."""
    with _production_service(isolated_status_dir) as (_registry, _port):
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"ok": false' in result.output
    assert '"error": "service_not_safe_to_borrow_gpu"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_stale_discovery_without_a_local_fallback(
    isolated_status_dir: Path,
) -> None:
    """A stale discovery record fails before any remote observation is trusted."""
    with _production_service(isolated_status_dir) as (_registry, port):
        _publish_discovery(
            isolated_status_dir,
            port=port,
            overrides={
                "last_heartbeat": (
                    datetime.now(UTC)
                    - timedelta(seconds=HEARTBEAT_STALENESS_SECONDS + 5)
                ).isoformat(timespec="seconds"),
            },
        )
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_discovery_stale"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_a_future_discovery_heartbeat(
    isolated_status_dir: Path,
) -> None:
    """A future heartbeat has no trustworthy freshness interpretation."""
    with _production_service(isolated_status_dir) as (_registry, port):
        _publish_discovery(
            isolated_status_dir,
            port=port,
            overrides={
                "last_heartbeat": (datetime.now(UTC) + timedelta(seconds=5)).isoformat(
                    timespec="seconds"
                ),
            },
        )
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_discovery_unknown"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_an_incomplete_discovery_heartbeat(
    isolated_status_dir: Path,
) -> None:
    """An unparsable heartbeat never becomes a local-device fallback."""
    with _production_service(isolated_status_dir) as (_registry, port):
        _publish_discovery(
            isolated_status_dir,
            port=port,
            overrides={"last_heartbeat": "not-a-timestamp"},
        )
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_discovery_incomplete"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_an_unreported_discovery_package_version(
    isolated_status_dir: Path,
) -> None:
    """An unreported discovery release is not compatible by implication."""
    with _production_service(isolated_status_dir) as (_registry, port):
        _publish_discovery(
            isolated_status_dir,
            port=port,
            overrides={SERVICE_VERSION_FIELD: None},
        )
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_version_unreported"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_a_version_skewed_discovery(
    isolated_status_dir: Path,
) -> None:
    """Discovery release compatibility is required before probing health."""
    with _production_service(isolated_status_dir) as (_registry, port):
        _publish_discovery(
            isolated_status_dir,
            port=port,
            overrides={SERVICE_VERSION_FIELD: "incompatible-service-release"},
        )
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_version_mismatch"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_an_unreachable_discovered_service(
    isolated_status_dir: Path,
) -> None:
    """A valid discovery record does not authorize probing the local device."""
    _publish_discovery(isolated_status_dir, port=free_loopback_port())
    result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_unreachable"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_reports_a_silent_discovered_service_as_timed_out(
    isolated_status_dir: Path,
) -> None:
    """A held-but-silent port is presence without an answer, never absence."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    previous = os.environ.get("VAULTSPEC_RAG_ADMIN_TIMEOUT")
    os.environ["VAULTSPEC_RAG_ADMIN_TIMEOUT"] = "0.4"
    try:
        _publish_discovery(isolated_status_dir, port=port)
        result = runner.invoke(app, ["server", "preflight", "--json"])
    finally:
        if previous is None:
            os.environ.pop("VAULTSPEC_RAG_ADMIN_TIMEOUT", None)
        else:
            os.environ["VAULTSPEC_RAG_ADMIN_TIMEOUT"] = previous
        listener.close()

    assert result.exit_code == 1, result.output
    # The kernel accepted the connection, so the service is demonstrably
    # there; only the answer is missing. Proven able to fail: collapsing the
    # probe timeout back into the unreachable sentinel emits
    # service_unreachable here and fails the verdict assertion.
    assert '"error": "service_health_timeout"' in result.output
    assert '"error": "service_unreachable"' not in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_a_requested_port_that_differs_from_discovery(
    isolated_status_dir: Path,
) -> None:
    """The CLI cannot redirect a discovered observation to another service."""
    with _production_service(isolated_status_dir) as (_registry, port):
        result = runner.invoke(
            app,
            ["server", "preflight", "--port", str(port + 1), "--json"],
        )

    assert result.exit_code == 1, result.output
    assert '"error": "service_port_mismatch"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_a_health_pid_mismatch(
    isolated_status_dir: Path,
) -> None:
    """Health must corroborate the discovered process identity exactly."""
    with _production_service(isolated_status_dir) as (_registry, port):
        _publish_discovery(
            isolated_status_dir,
            port=port,
            overrides={"pid": os.getpid() + 1},
        )
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_identity_mismatch"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_a_zero_discovered_pid(
    isolated_status_dir: Path,
) -> None:
    """A syntactically ready but zero process identity cannot be trusted."""
    with _production_service(isolated_status_dir) as (_registry, port):
        _publish_discovery(
            isolated_status_dir,
            port=port,
            overrides={"pid": 0},
        )
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_identity_mismatch"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_a_health_port_mismatch(
    isolated_status_dir: Path,
) -> None:
    """Health cannot bind a discovered address to a different reported port."""
    with _production_service(
        isolated_status_dir,
        reported_port_offset=1,
    ) as (_registry, _port):
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_identity_mismatch"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_a_health_token_mismatch(
    isolated_status_dir: Path,
) -> None:
    """Health's identity bearer must equal the discovered bearer exactly."""
    with _production_service(isolated_status_dir) as (_registry, port):
        _publish_discovery(
            isolated_status_dir,
            port=port,
            overrides={"service_token": "mismatched-discovery-token"},
        )
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_identity_mismatch"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_an_empty_discovered_token(
    isolated_status_dir: Path,
) -> None:
    """An empty discovery bearer cannot bind a real authenticated route."""
    with _production_service(isolated_status_dir) as (_registry, port):
        _publish_discovery(
            isolated_status_dir,
            port=port,
            overrides={"service_token": ""},
        )
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_identity_mismatch"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_an_authenticated_state_route_without_a_project_root(
    isolated_singleton_dirs: Path,
    tmp_path: Path,
) -> None:
    """An authenticated route error remains unavailable, never a safe state."""
    del isolated_singleton_dirs
    server_root = tmp_path / "empty-service-root"
    server_root.mkdir()
    with _machine_pointer_service(tmp_path, server_root=server_root):
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_state_unavailable"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_pins_authenticated_state_to_the_machine_pointer_token(
    isolated_singleton_dirs: Path,
    tmp_path: Path,
) -> None:
    """A different isolated status token cannot replace a contended pointer bearer."""
    with _machine_pointer_service(tmp_path) as port:
        pause = _try_http_admin(
            "pause_service",
            {},
            port,
            initial_bearer_token=_SERVICE_TOKEN,
        )
        assert pause is not None, "the real machine-pointer pause route did not answer"
        assert pause["status"] == "quiesced", pause
        _publish_discovery(
            isolated_singleton_dirs,
            port=port,
            overrides={"service_token": _AMBIENT_SERVICE_TOKEN},
        )
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 0, result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_when_no_service_is_discovered(
    isolated_status_dir: Path,
) -> None:
    """A missing service is never replaced with a local device probe."""
    del isolated_status_dir
    result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_discovery_unavailable"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


class TestTorchFreedom:
    """The CLI observation surface must remain torch-free on import."""

    def test_importing_the_verb_loads_no_torch(self) -> None:
        assert_fresh_import_excludes(
            import_probe_source("vaultspec_rag.cli._service_preflight")
        )
