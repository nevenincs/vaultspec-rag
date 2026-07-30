"""CPU-only borrower lease tests using real OS lock holders and HTTP routes."""

from __future__ import annotations

import asyncio
import base64
import os
import secrets
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, Protocol

import pytest
from starlette.testclient import TestClient

from ..config._settings import reset_config
from ..config._types import EnvVar
from ..gpu_borrow_lease import (
    BorrowerLeaseStatus,
    acquire_gpu_borrow_lease,
    borrower_lease_status,
    release_gpu_borrow_lease,
)
from ..server import ServerRouteRuntime, create_http_app
from ..server._lifespan import _borrower_lease_recovery_tick
from ..service import ServiceRegistry

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = [pytest.mark.unit]

_TOKEN = "gpu-borrow-lease-test-token"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}
_PROCESS_TIMEOUT_SECONDS = 10.0


class BorrowerProcess(NamedTuple):
    """One spawned process holding the production borrower lease."""

    process: subprocess.Popen[str]
    capability: str


class BorrowerRoutes(NamedTuple):
    """A real no-lifespan route client and the registry it controls."""

    client: TestClient
    registry: ServiceRegistry


class _RouteResponse(Protocol):
    """The TestClient response surface this test needs without an HTTPX alias."""

    status_code: int

    def json(self) -> object:
        """Return the decoded response payload."""


_HOLD_GPU_BORROW_LEASE = """
from pathlib import Path
import sys
import time
from vaultspec_rag.gpu_borrow_lease import (
    acquire_gpu_borrow_lease,
    release_gpu_borrow_lease,
)

lease = acquire_gpu_borrow_lease()
if lease is None:
    raise RuntimeError("child could not acquire the GPU borrower lease")
Path(sys.argv[1]).write_text(lease.capability, encoding="ascii")
try:
    time.sleep(120)
finally:
    release_gpu_borrow_lease(lease)
"""


@contextmanager
def _isolated_borrower_anchor(tmp_path: Path) -> Generator[None]:
    """Relocate the machine-global borrower anchor under the pytest root."""
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    previous_storage = os.environ.get(storage_key)
    os.environ[storage_key] = str(tmp_path / "qdrant" / "storage")
    reset_config()
    try:
        yield
    finally:
        if previous_storage is None:
            os.environ.pop(storage_key, None)
        else:
            os.environ[storage_key] = previous_storage
        reset_config()


@contextmanager
def _unavailable_borrower_anchor(tmp_path: Path) -> Generator[None]:
    """Point the borrower anchor under a real file, so its parent cannot exist."""
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    previous_storage = os.environ.get(storage_key)
    blocked_parent = tmp_path / "borrower-anchor-parent-file"
    blocked_parent.write_text("not a directory", encoding="ascii")
    os.environ[storage_key] = str(blocked_parent / "storage")
    reset_config()
    try:
        yield
    finally:
        if previous_storage is None:
            os.environ.pop(storage_key, None)
        else:
            os.environ[storage_key] = previous_storage
        reset_config()


@contextmanager
def _borrower_process() -> Generator[BorrowerProcess]:
    """Spawn a process that holds a real borrower lease and returns its secret."""
    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(delete=False) as marker_file:
        marker = Path(marker_file.name)
    marker.unlink()
    process = subprocess.Popen(
        [sys.executable, "-c", _HOLD_GPU_BORROW_LEASE, str(marker)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
        while not marker.is_file() and process.poll() is None:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        if not marker.is_file():
            process.kill()
            stderr = process.communicate(timeout=_PROCESS_TIMEOUT_SECONDS)[1]
            raise AssertionError(
                f"borrower child did not acquire the OS lease: {stderr}"
            )
        capability = marker.read_text(encoding="ascii")
        yield BorrowerProcess(process, capability)
    finally:
        marker.unlink(missing_ok=True)
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
        assert process.poll() is not None, "borrower child did not exit"
        if process.stderr is not None:
            process.stderr.close()


@contextmanager
def _borrower_routes() -> Generator[BorrowerRoutes]:
    """Serve the production routes with no app lifespan or GPU startup."""
    registry = ServiceRegistry()
    app = create_http_app(
        ServerRouteRuntime(token=_TOKEN, registry=registry, port=8765),
        lifespan=None,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield BorrowerRoutes(client, registry)


def _response_payload(response: _RouteResponse) -> object:
    """Read one successful HTTP response as an opaque JSON value."""
    assert response.status_code == 200
    return response.json()


def _unrelated_capability() -> str:
    """Create a structurally valid capability that no child owns."""
    return (
        base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    )


def _await_borrower_release(capability: str) -> BorrowerLeaseStatus:
    """Wait only for the OS to finish releasing a just-crashed child lock."""
    deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
    status = borrower_lease_status(capability)
    while status is BorrowerLeaseStatus.HELD and time.monotonic() < deadline:
        time.sleep(0.05)
        status = borrower_lease_status(capability)
    return status


def _assert_borrower_refusal(
    response: _RouteResponse,
    reason: str,
    *,
    state: str,
) -> None:
    """Assert the one failure envelope without reading private lease data."""
    match _response_payload(response):
        case {
            "ok": False,
            "status": str() as status,
            "error": str() as error,
            "message": str() as message,
            "retryable": True,
            "quiesce": {"state": str() as quiesce_state},
        }:
            assert status == reason
            assert error == reason
            assert message == reason
            assert quiesce_state == state
        case payload:
            pytest.fail(f"unexpected borrower refusal envelope: {payload!r}")


def _assert_pause_success(response: _RouteResponse) -> None:
    """Assert the achieved safe-quiescence shape from the production route."""
    match _response_payload(response):
        case {
            "ok": True,
            "status": "quiesced",
            "quiesce": {
                "state": "quiesced",
                "safe_to_borrow_gpu": True,
            },
        }:
            return
        case payload:
            pytest.fail(f"unexpected achieved pause envelope: {payload!r}")


def _assert_resume_success(response: _RouteResponse) -> None:
    """Assert the achieved running shape from the production route."""
    match _response_payload(response):
        case {
            "ok": True,
            "status": "running",
            "quiesce": {
                "state": "running",
                "safe_to_borrow_gpu": False,
            },
        }:
            return
        case payload:
            pytest.fail(f"unexpected achieved resume envelope: {payload!r}")


def test_os_lease_contends_and_releases_after_borrower_crash(tmp_path: Path) -> None:
    """A crashed child frees the real OS borrower lock for the next holder."""
    with _isolated_borrower_anchor(tmp_path), _borrower_process() as borrower:
        assert borrower_lease_status(borrower.capability) is BorrowerLeaseStatus.HELD
        assert acquire_gpu_borrow_lease() is None

        borrower.process.kill()
        borrower.process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
        assert borrower.process.poll() is not None, "borrower child did not terminate"

        assert (
            _await_borrower_release(borrower.capability) is BorrowerLeaseStatus.NOT_HELD
        )
        successor = acquire_gpu_borrow_lease()
        assert successor is not None
        release_gpu_borrow_lease(successor)


def test_authenticated_routes_bind_and_require_the_live_borrower_capability(
    tmp_path: Path,
) -> None:
    """Only the holder can bind safe quiescence, then resume it once."""
    with (
        _isolated_borrower_anchor(tmp_path),
        _borrower_process() as borrower,
        _borrower_routes() as routes,
    ):
        invalid = routes.client.post(
            "/pause",
            headers=_HEADERS,
            json={"borrower_capability": ""},
        )
        _assert_borrower_refusal(
            invalid,
            "invalid_borrower_capability",
            state="running",
        )

        wrong_before_bind = routes.client.post(
            "/pause",
            headers=_HEADERS,
            json={"borrower_capability": _unrelated_capability()},
        )
        _assert_borrower_refusal(
            wrong_before_bind,
            "borrower_capability_invalid",
            state="running",
        )

        _assert_pause_success(
            routes.client.post(
                "/pause",
                headers=_HEADERS,
                json={"borrower_capability": borrower.capability},
            )
        )

        wrong_bound_pause = routes.client.post(
            "/pause",
            headers=_HEADERS,
            json={"borrower_capability": _unrelated_capability()},
        )
        _assert_borrower_refusal(
            wrong_bound_pause,
            "borrower_lease_mismatch",
            state="quiesced",
        )

        empty_resume = routes.client.post(
            "/resume",
            headers=_HEADERS,
            json={},
        )
        _assert_borrower_refusal(
            empty_resume,
            "borrower_lease_required",
            state="quiesced",
        )

        wrong_bound_resume = routes.client.post(
            "/resume",
            headers=_HEADERS,
            json={"borrower_capability": _unrelated_capability()},
        )
        _assert_borrower_refusal(
            wrong_bound_resume,
            "borrower_lease_mismatch",
            state="quiesced",
        )

        _assert_resume_success(
            routes.client.post(
                "/resume",
                headers=_HEADERS,
                json={"borrower_capability": borrower.capability},
            )
        )


def test_lost_bound_lease_auto_resumes_but_manual_quiescence_stays_held(
    tmp_path: Path,
) -> None:
    """The heartbeat tick resumes only the quiescence that has a lost binding."""
    with _isolated_borrower_anchor(tmp_path), _borrower_routes() as routes:
        _assert_pause_success(routes.client.post("/pause", headers=_HEADERS))
        assert routes.registry.resume_lost_borrower_lease() is None
        assert routes.registry.quiesce_snapshot().state.value == "quiesced"
        _assert_resume_success(routes.client.post("/resume", headers=_HEADERS))

        with _borrower_process() as borrower:
            _assert_pause_success(
                routes.client.post(
                    "/pause",
                    headers=_HEADERS,
                    json={"borrower_capability": borrower.capability},
                )
            )
            with _unavailable_borrower_anchor(tmp_path):
                assert (
                    borrower_lease_status(borrower.capability)
                    is BorrowerLeaseStatus.UNAVAILABLE
                )
                _assert_borrower_refusal(
                    routes.client.post(
                        "/pause",
                        headers=_HEADERS,
                        json={"borrower_capability": borrower.capability},
                    ),
                    "borrower_lease_unavailable",
                    state="quiesced",
                )
                asyncio.run(_borrower_lease_recovery_tick(routes.registry))
                assert routes.registry.quiesce_snapshot().state.value == "quiesced"
            borrower.process.kill()
            borrower.process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
            assert borrower.process.poll() is not None, (
                "borrower child did not terminate"
            )
            assert (
                _await_borrower_release(borrower.capability)
                is BorrowerLeaseStatus.NOT_HELD
            )

            with _borrower_process():
                assert (
                    borrower_lease_status(borrower.capability)
                    is BorrowerLeaseStatus.CAPABILITY_INVALID
                )
                asyncio.run(_borrower_lease_recovery_tick(routes.registry))
                assert routes.registry.quiesce_snapshot().state.value == "quiesced"

            asyncio.run(_borrower_lease_recovery_tick(routes.registry))

        assert routes.registry.quiesce_snapshot().state.value == "running"


def test_valid_capability_without_a_live_lease_is_refused(tmp_path: Path) -> None:
    """A syntactically valid secret cannot replace active OS lock ownership."""
    with _isolated_borrower_anchor(tmp_path), _borrower_routes() as routes:
        refused = routes.client.post(
            "/pause",
            headers=_HEADERS,
            json={"borrower_capability": _unrelated_capability()},
        )
        _assert_borrower_refusal(
            refused,
            "borrower_lease_not_held",
            state="running",
        )
