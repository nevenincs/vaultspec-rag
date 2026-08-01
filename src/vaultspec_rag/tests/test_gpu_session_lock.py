"""CPU-only coverage for the borrower coordinator used by GPU pytest tiers."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING, NamedTuple

import pytest
import uvicorn

from ..cli._gpu_lease import BorrowGPUError, run_with_borrowed_gpu
from ..config._paths import SERVICE_STATUS_FILENAME
from ..gpu_borrow_lease import (
    acquire_gpu_borrow_lease,
    gpu_borrow_lease_path,
    release_gpu_borrow_lease,
)
from ..server import ServerRouteRuntime, create_http_app
from ..service import ServiceRegistry
from ..serviceclient._compat import SERVICE_VERSION_FIELD, local_package_version
from ..serviceclient._discovery import (
    HEARTBEAT_STALENESS_SECONDS,
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
    _replace_service_status,
)
from ._child_signal import await_marker, child_stderr
from ._import_probe import assert_fresh_import_excludes, import_probe_source
from ._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_SERVICE_TOKEN = "gpu-pytest-session-route-token"
_PROCESS_TIMEOUT_SECONDS = 10.0

# A nested pytest session costs one interpreter start, one plugin load, and
# the repository conftest's configure hooks. Bounding that at the ten seconds
# the other children in this file use would be a bound on normal cost rather
# than on a hang, so it is stated separately and generously: it exists only to
# stop a genuinely wedged session, and stays well inside pytest's own per-test
# ceiling.
_NESTED_PYTEST_TIMEOUT_SECONDS = 60.0
_HOLDER_PROGRAM = """
import sys

from vaultspec_rag.gpu_borrow_lease import (
    acquire_gpu_borrow_lease,
    release_gpu_borrow_lease,
)
from vaultspec_rag.tests._child_signal import publish_marker

lease = acquire_gpu_borrow_lease()
if lease is None:
    raise RuntimeError("holder could not acquire the borrower lease")
publish_marker(sys.argv[1], "held")
try:
    sys.stdin.readline()
finally:
    release_gpu_borrow_lease(lease)
"""
_QDRANT_SELECTION_PROGRAM = """
import pytest


@pytest.mark.subprocess_gpu
def test_selected_qdrant_runner_prerequisite(
    required_host_provisioned_qdrant_source: object,
) -> None:
    raise AssertionError("selected Qdrant prerequisite test body ran")
"""
_BORROWER_CONTENTION_PROBE = """
from vaultspec_rag.gpu_borrow_lease import (
    acquire_gpu_borrow_lease,
    release_gpu_borrow_lease,
)

lease = acquire_gpu_borrow_lease()
if lease is None:
    print("contended", flush=True)
else:
    try:
        print("acquired", flush=True)
    finally:
        release_gpu_borrow_lease(lease)
"""


class _ProductionRoutes(NamedTuple):
    """One real no-lifespan route host and the registry it exposes."""

    registry: ServiceRegistry
    server: uvicorn.Server
    thread: threading.Thread

    def stop(self) -> None:
        """Stop the loopback listener after its borrower has resumed."""
        self.server.should_exit = True
        self.thread.join(timeout=_PROCESS_TIMEOUT_SECONDS)
        assert not self.thread.is_alive(), "production route server did not stop"


@contextlib.contextmanager
def _production_routes(status_dir: Path) -> Generator[_ProductionRoutes]:
    """Expose the production pause and resume routes without a daemon lifespan."""
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
    routes = _ProductionRoutes(registry, server, thread)
    thread.start()
    try:
        deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "production route server did not start"
        _replace_service_status(
            {
                "pid": os.getpid(),
                "port": port,
                "schema": SERVICE_DISCOVERY_SCHEMA,
                "version": SERVICE_DISCOVERY_VERSION,
                SERVICE_VERSION_FIELD: local_package_version(),
                "service_token": _SERVICE_TOKEN,
                "last_heartbeat": time.strftime(
                    "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
                ),
                "stale_after_s": HEARTBEAT_STALENESS_SECONDS,
            },
            path=status_dir / SERVICE_STATUS_FILENAME,
        )
        yield routes
    finally:
        if thread.is_alive():
            routes.stop()


@contextlib.contextmanager
def _borrower_holder(tmp_path: Path) -> Generator[subprocess.Popen[str]]:
    """Hold the production borrower lease in a real child process."""
    marker = tmp_path / "borrower-holder-ready"
    with child_stderr() as diagnostics:
        process = subprocess.Popen(
            [sys.executable, "-c", _HOLDER_PROGRAM, str(marker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=diagnostics.sink,
            text=True,
        )
        try:
            reported = await_marker(marker, process, timeout=_PROCESS_TIMEOUT_SECONDS)
            assert reported == "held", (
                f"borrower holder did not take the lease: {diagnostics.read()}"
            )
            yield process
        finally:
            if process.poll() is None:
                assert process.stdin is not None
                process.stdin.close()
            try:
                process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
            assert process.returncode == 0, diagnostics.read()


def _assert_borrower_lease_released() -> None:
    """Prove the coordinator released its exact production lease."""
    successor = acquire_gpu_borrow_lease()
    assert successor is not None, "the borrower coordinator retained its lease"
    release_gpu_borrow_lease(successor)


def _child_borrower_lease_outcome() -> str:
    """Observe the real configured borrower anchor from a separate process."""
    process = subprocess.run(
        [sys.executable, "-c", _BORROWER_CONTENTION_PROBE],
        capture_output=True,
        check=False,
        text=True,
        timeout=_PROCESS_TIMEOUT_SECONDS,
    )
    assert process.returncode == 0, process.stderr
    return process.stdout.strip()


def test_coordinator_quiesces_real_routes_then_resumes_before_lease_release(
    isolated_singleton_dirs: Path,
) -> None:
    """The pytest coordinator's production path owns one safe pause window."""
    observed_states: list[str] = []
    with _production_routes(isolated_singleton_dirs) as routes:

        def observe_safe_pause() -> None:
            snapshot = routes.registry.quiesce_snapshot()
            observed_states.append(snapshot.state.value)
            assert snapshot.safe_to_borrow_gpu is True

        run_with_borrowed_gpu(requested_port=None, work=observe_safe_pause)

        assert routes.registry.quiesce_snapshot().state.value == "running"

    assert observed_states == ["quiesced"]
    _assert_borrower_lease_released()


def test_coordinator_refuses_a_real_cross_process_borrower_then_observes_release(
    isolated_singleton_dirs: Path,
    tmp_path: Path,
) -> None:
    """A temporary-anchor holder blocks the exact coordinator before any work."""
    assert tmp_path in gpu_borrow_lease_path().parents
    work_ran = False
    with _production_routes(isolated_singleton_dirs), _borrower_holder(tmp_path):

        def forbidden_work() -> None:
            nonlocal work_ran
            work_ran = True

        with pytest.raises(BorrowGPUError, match="Another process already holds"):
            run_with_borrowed_gpu(requested_port=None, work=forbidden_work)

    assert work_ran is False
    _assert_borrower_lease_released()


def test_unacknowledged_resume_retains_lease_until_the_borrower_exits(
    isolated_singleton_dirs: Path,
) -> None:
    """A failed resume retains the real lease, so a child cannot borrow early."""
    error: BorrowGPUError | None = None
    with _production_routes(isolated_singleton_dirs) as routes:

        def stop_routes_after_acknowledged_pause() -> None:
            snapshot = routes.registry.quiesce_snapshot()
            assert snapshot.safe_to_borrow_gpu is True
            routes.stop()

        try:
            run_with_borrowed_gpu(
                requested_port=None,
                work=stop_routes_after_acknowledged_pause,
            )
        except BorrowGPUError as exc:
            error = exc

    assert error is not None
    assert error.error == "borrow_gpu_resume_unacknowledged"
    try:
        assert _child_borrower_lease_outcome() == "contended"
    finally:
        retained_lease = acquire_gpu_borrow_lease()
        assert retained_lease is not None
        release_gpu_borrow_lease(retained_lease)
    assert _child_borrower_lease_outcome() == "acquired"


def test_borrower_coordinator_imports_without_torch() -> None:
    """The pytest GPU admission path remains torch-free before it runs work."""
    assert_fresh_import_excludes(
        import_probe_source(
            "vaultspec_rag.gpu_borrow_lease",
            "vaultspec_rag.cli._gpu_lease",
        )
    )


def test_selected_qdrant_fixture_refuses_without_provisioning_before_test_body(
    tmp_path: Path,
) -> None:
    """A selected real Qdrant fixture refuses before borrower or device admission."""
    test_path = tmp_path / "test_selected_qdrant_runner.py"
    test_path.write_text(_QDRANT_SELECTION_PROGRAM, encoding="utf-8")
    host_status_dir = tmp_path / "unprovisioned-host-status"
    host_storage_dir = tmp_path / "unprovisioned-host-storage"
    environment = os.environ.copy()
    environment.pop("VAULTSPEC_RAG_QDRANT_BINARY", None)
    environment.pop("PYTEST_CURRENT_TEST", None)
    environment["HF_TOKEN"] = "test-gpu-tier-token"
    environment["VAULTSPEC_RAG_STATUS_DIR"] = str(host_status_dir)
    environment["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = str(host_storage_dir)

    # A session given an absolute path collects a directory node for every
    # ancestor of it inside the conftest cut-off, listing each entry by entry.
    # The runner lives under the pytest temp tree, so those ancestors include
    # the machine's shared temp directory: without the cut-off below the nested
    # session spent about eight of its nine seconds enumerating tens of
    # thousands of unrelated entries there, and aborted collection outright
    # whenever another process removed one mid-scan. Cutting the search to the
    # runner's own directory costs nothing here - the conftest this guard needs
    # is loaded explicitly by name, and no other conftest sits between the
    # runner and the root.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "conftest",
            f"--confcutdir={tmp_path}",
            str(test_path),
            "-q",
        ],
        capture_output=True,
        check=False,
        cwd=os.getcwd(),
        env=environment,
        text=True,
        timeout=_NESTED_PYTEST_TIMEOUT_SECONDS,
    )

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 1, output
    assert "requires a manifest-verified provisioned Qdrant binary" in output
    assert "selected Qdrant prerequisite test body ran" not in output
