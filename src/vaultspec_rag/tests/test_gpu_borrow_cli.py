"""CPU-only production coverage for explicit borrower CLI coordination."""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest
import uvicorn
from typer.testing import CliRunner

from ..cli import app
from ..cli._gpu_lease import run_with_borrowed_gpu
from ..cli._service_preflight import _quiesce_is_safe, _strict_quiesce
from ..config._paths import SERVICE_STATUS_FILENAME
from ..gpu_borrow_lease import acquire_gpu_borrow_lease, release_gpu_borrow_lease
from ..service import ServiceRegistry
from ..serviceclient._compat import SERVICE_VERSION_FIELD, local_package_version
from ..serviceclient._discovery import (
    HEARTBEAT_STALENESS_SECONDS,
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
    _replace_service_status,
)
from ..serviceclient._transport import _try_http_admin
from ._import_probe import assert_fresh_import_excludes, import_probe_source
from ._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = [pytest.mark.unit]

_SERVICE_TOKEN = "gpu-borrow-cli-route-token"
_PROCESS_TIMEOUT_SECONDS = 10.0
runner = CliRunner()


class _ProductionService(NamedTuple):
    """One real route host and the registry whose state it exposes."""

    registry: ServiceRegistry
    port: int
    server: uvicorn.Server
    thread: threading.Thread

    def stop(self) -> None:
        """Stop the real HTTP listener without changing registry state."""
        self.server.should_exit = True
        self.thread.join(timeout=_PROCESS_TIMEOUT_SECONDS)
        assert not self.thread.is_alive(), "production route server did not stop"


def _publish_discovery(status_dir: Path, *, port: int) -> None:
    """Publish the real route host through the production discovery writer."""
    _replace_service_status(
        {
            "pid": os.getpid(),
            "port": port,
            "schema": SERVICE_DISCOVERY_SCHEMA,
            "version": SERVICE_DISCOVERY_VERSION,
            SERVICE_VERSION_FIELD: local_package_version(),
            "service_token": _SERVICE_TOKEN,
            "last_heartbeat": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
            "stale_after_s": HEARTBEAT_STALENESS_SECONDS,
        },
        path=status_dir / SERVICE_STATUS_FILENAME,
    )


@contextlib.contextmanager
def _production_service(status_dir: Path) -> Generator[_ProductionService]:
    """Serve authenticated production routes with no daemon lifespan or GPU."""
    from ..server import ServerRouteRuntime, create_http_app

    registry = ServiceRegistry()
    port = free_loopback_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_http_app(
                ServerRouteRuntime(
                    token=_SERVICE_TOKEN,
                    registry=registry,
                    port=port,
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
    service = _ProductionService(registry, port, server, thread)
    thread.start()
    try:
        deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "production route server did not start"
        _publish_discovery(status_dir, port=port)
        yield service
    finally:
        if thread.is_alive():
            service.stop()


def _safe_remote_snapshot(port: int) -> dict[str, object]:
    """Read the service's real state while borrower work is admitted."""
    result = _try_http_admin("get_service_state", {}, port)
    assert result is not None, "the real service-state route did not answer"
    quiesce = _strict_quiesce(result.get("quiesce"))
    assert quiesce is not None, result
    assert _quiesce_is_safe(quiesce), result
    return quiesce


def _assert_lease_is_available() -> None:
    """Prove the coordinator released its OS-backed borrower lease."""
    successor = acquire_gpu_borrow_lease()
    assert successor is not None, "the borrower lease was not released"
    release_gpu_borrow_lease(successor)


def test_borrowed_work_runs_only_during_safe_pause_then_resumes_and_releases(
    isolated_singleton_dirs: Path,
) -> None:
    """The actual coordinator binds the real route lifecycle around its work."""
    observed_states: list[str] = []
    with _production_service(isolated_singleton_dirs) as service:

        def work() -> None:
            quiesce = _safe_remote_snapshot(service.port)
            observed_states.append(str(quiesce["state"]))

        run_with_borrowed_gpu(requested_port=service.port, work=work)

        assert service.registry.quiesce_snapshot().state.value == "running"

    assert observed_states == ["quiesced"]
    _assert_lease_is_available()


def test_borrowed_work_failure_still_resumes_then_releases(
    isolated_singleton_dirs: Path,
) -> None:
    """A real child-work exception cannot leave a recoverable service paused."""
    with _production_service(isolated_singleton_dirs) as service:

        def failing_work() -> None:
            _safe_remote_snapshot(service.port)
            raise RuntimeError("intentional borrower child failure")

        with pytest.raises(RuntimeError, match="intentional borrower child failure"):
            run_with_borrowed_gpu(requested_port=service.port, work=failing_work)

        assert service.registry.quiesce_snapshot().state.value == "running"

    _assert_lease_is_available()


_RESUME_FAILURE_PROBE = """
import sys
import time
from pathlib import Path

from vaultspec_rag.cli._gpu_lease import BorrowGPUError, run_with_borrowed_gpu

marker = Path(sys.argv[1])
port = int(sys.argv[2])

def work():
    marker.write_text("safe", encoding="ascii")
    time.sleep(1.0)

try:
    run_with_borrowed_gpu(requested_port=port, work=work)
except BorrowGPUError as exc:
    print(exc.error)
    raise SystemExit(1)
raise SystemExit("borrower coordinator unexpectedly resumed")
"""


def test_unacknowledged_resume_retains_lease_until_child_exit_for_heartbeat_recovery(
    isolated_singleton_dirs: Path,
    tmp_path: Path,
) -> None:
    """A real lost response retains ownership until process death triggers recovery."""
    marker = tmp_path / "borrower-safe.marker"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd() / "src")
    with _production_service(isolated_singleton_dirs) as service:
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _RESUME_FAILURE_PROBE,
                str(marker),
                str(service.port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        try:
            deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
            while not marker.is_file() and child.poll() is None:
                assert time.monotonic() < deadline, "borrower child never reached work"
                time.sleep(0.01)
            assert marker.read_text(encoding="ascii") == "safe"
            assert service.registry.quiesce_snapshot().state.value == "quiesced"

            service.stop()
            stdout, stderr = child.communicate(timeout=_PROCESS_TIMEOUT_SECONDS)
            assert child.returncode == 1, stderr
            assert stdout == "borrow_gpu_resume_unacknowledged\n"
            assert service.registry.quiesce_snapshot().state.value == "quiesced"
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=_PROCESS_TIMEOUT_SECONDS)

        _assert_lease_is_available()
        from ..server._lifespan import _borrower_lease_recovery_tick

        asyncio.run(_borrower_lease_recovery_tick(service.registry))
        assert service.registry.quiesce_snapshot().state.value == "running"


def test_index_requires_explicit_borrow_gpu_when_no_service_is_available(
    tmp_path: Path,
) -> None:
    """The no-service default refuses before importing local GPU indexing."""
    target = tmp_path / "project"
    target.mkdir()
    (target / ".vaultspec").mkdir()

    result = runner.invoke(
        app,
        ["--target", str(target), "index", "--type", "vault", "--json"],
    )

    assert result.exit_code == 1, result.output
    assert result.output == (
        '{"ok": false, "command": "index", "error": "borrow_gpu_required", '
        '"message": "No compatible running service is available for delegated '
        'indexing. Start a compatible service, or explicitly rerun with '
        '--borrow-gpu."}\n'
    )


def test_index_no_longer_accepts_allow_fallback(tmp_path: Path) -> None:
    """The obsolete local-fallback flag cannot grant GPU authority."""
    target = tmp_path / "project"
    target.mkdir()
    (target / ".vaultspec").mkdir()

    result = runner.invoke(
        app,
        ["--target", str(target), "index", "--allow-fallback"],
    )

    assert result.exit_code == 2, result.output
    assert "No such option: --allow-fallback" in result.output


class TestTorchFreedom:
    """Borrower orchestration must not initialize the GPU before work runs."""

    def test_importing_borrower_modules_loads_no_torch(self) -> None:
        assert_fresh_import_excludes(
            import_probe_source(
                "vaultspec_rag.cli._gpu_lease",
                "vaultspec_rag.cli._index",
            )
        )
