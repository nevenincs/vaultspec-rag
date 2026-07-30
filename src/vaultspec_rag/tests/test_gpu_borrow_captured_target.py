"""CPU-only coverage for captured borrower service identity."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = [pytest.mark.unit]

_PROCESS_TIMEOUT_SECONDS = 10.0
_RESIDENT_ROUTE_HOST = """
import json
import os
import subprocess
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

_MACHINE_LOCK_OWNER_PROBE = '''
import json
import sys
from pathlib import Path

from vaultspec_rag._anchor_claim import claim_anchor, release_anchor_claim

claim = claim_anchor(Path(sys.argv[1]), pid_record=True)
try:
    assert claim.fault is None, repr(claim.fault)
    assert claim.descriptor is None, "the resident machine lock was not contended"
    print(json.dumps({"holder_pid": claim.holder_pid}), flush=True)
finally:
    if claim.descriptor is not None:
        release_anchor_claim(claim.descriptor, pid_record=True)
'''

port = int(sys.argv[1])
ready_path = Path(sys.argv[2])
stop_path = Path(sys.argv[3])
trace_path = Path(sys.argv[4])
reject_first_pause = sys.argv[5] == "1"
token = "captured-target-real-route-token"
lease, holder = acquire_machine_lock_lease()
assert lease is not None, holder
owner_probe = subprocess.run(
    [sys.executable, "-c", _MACHINE_LOCK_OWNER_PROBE, str(lease.path)],
    capture_output=True,
    check=False,
    text=True,
    timeout=10.0,
)
assert owner_probe.returncode == 0, owner_probe.stderr
owner_observation = json.loads(owner_probe.stdout)
assert owner_observation == {"holder_pid": os.getpid()}, owner_observation
registry = ServiceRegistry()
route_app = create_http_app(
    ServerRouteRuntime(token=token, registry=registry, port=port),
    lifespan=None,
)
first_pause_rejected = False

async def app(scope, receive, send):
    global first_pause_rejected
    if scope["type"] == "http" and scope["path"] == "/pause":
        authorization = next(
            (
                value.decode("latin-1")
                for name, value in scope["headers"]
                if name == b"authorization"
            ),
            "",
        )
        with trace_path.open("a", encoding="utf-8") as trace:
            trace.write(authorization + "\\n")
        if reject_first_pause and not first_pause_rejected:
            first_pause_rejected = True
            body = b'{"ok": false, "error": "unauthorized"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
    await route_app(scope, receive, send)

server = uvicorn.Server(
    uvicorn.Config(
        app,
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
    ready_path.write_text(str(lease.path), encoding="utf-8")
    while not stop_path.exists():
        time.sleep(0.01)
finally:
    server.should_exit = True
    thread.join(timeout=10.0)
    delete_machine_discovery(lease)
    release_machine_lock_lease(lease)
"""

_CAPTURED_TARGET_PROBE = """
import json
import os
import sys
from pathlib import Path

mode = sys.argv[1]
marker_path = Path(sys.argv[2])
trace_path = Path(sys.argv[3])
host_storage_path = sys.argv[4]
root = Path(sys.argv[5])

os.environ.pop("_VAULTSPEC_RAG_PYTEST_SINGLETON_ACTIVE", None)
os.environ.pop("_VAULTSPEC_RAG_PYTEST_SINGLETON_ROOT", None)
os.environ.pop("PYTEST_CURRENT_TEST", None)
os.environ["_VAULTSPEC_RAG_PYTEST_SINGLETON_BOOTSTRAP"] = "1"
os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = host_storage_path

from vaultspec_rag._test_isolation import register_pytest_singleton_root
from vaultspec_rag.cli._gpu_lease import (
    BorrowGPUError,
    BorrowerServiceTarget,
    capture_borrower_service_target,
    run_with_borrowed_gpu,
)
from vaultspec_rag.config._settings import reset_config
from vaultspec_rag._machine_lock import machine_discovery_path
from vaultspec_rag.serviceclient._discovery import resolve_machine_service

if mode == "health-token-mismatch":
    payload = json.loads(machine_discovery_path().read_text(encoding="utf-8"))
    payload["service_token"] = "captured-target-pointer-only-token"
    machine_discovery_path().write_text(json.dumps(payload), encoding="utf-8")
    assert capture_borrower_service_target() is None
    assert not trace_path.exists()
    raise SystemExit(0)

target = capture_borrower_service_target()
assert isinstance(target, BorrowerServiceTarget), resolve_machine_service().evidence()
assert not hasattr(target, "borrower_lease_path")
assert target.identity_lock_path.is_absolute()
assert target.discovery_path.is_absolute()
assert target.pointer.resolution.service_token is None
assert "captured-target-real-route-token" not in repr(target)

status_dir = root / "machine-singleton" / "status"
storage_dir = root / "machine-singleton" / "qdrant-server" / "storage"
status_dir.mkdir(parents=True)
storage_dir.mkdir(parents=True)
os.environ["_VAULTSPEC_RAG_PYTEST_SINGLETON_ACTIVE"] = "1"
os.environ["_VAULTSPEC_RAG_PYTEST_SINGLETON_ROOT"] = str(root)
os.environ["VAULTSPEC_RAG_STATUS_DIR"] = str(status_dir)
os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = str(storage_dir)
register_pytest_singleton_root(root)
reset_config()

if mode == "same-token-401":
    run_with_borrowed_gpu(
        requested_port=None,
        work=lambda: marker_path.write_text("ran", encoding="ascii"),
        target=target,
    )
    assert marker_path.read_text(encoding="ascii") == "ran"
    assert trace_path.read_text(encoding="utf-8").splitlines() == [
        "Bearer captured-target-real-route-token",
        "Bearer captured-target-real-route-token",
    ]
elif mode == "rotated-token":
    payload = json.loads(target.discovery_path.read_text(encoding="utf-8"))
    payload["service_token"] = "captured-target-rotated-token"
    target.discovery_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        run_with_borrowed_gpu(requested_port=None, work=lambda: None, target=target)
    except BorrowGPUError as exc:
        assert exc.error == "borrow_gpu_service_target_changed"
    else:
        raise AssertionError("rotated captured bearer unexpectedly admitted work")
    assert not trace_path.exists()
elif mode == "stale-pointer":
    payload = json.loads(target.discovery_path.read_text(encoding="utf-8"))
    payload["last_heartbeat"] = "2000-01-01T00:00:00+00:00"
    target.discovery_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        run_with_borrowed_gpu(requested_port=None, work=lambda: None, target=target)
    except BorrowGPUError as exc:
        assert exc.error == "borrow_gpu_service_target_changed"
    else:
        raise AssertionError("stale captured pointer unexpectedly admitted work")
    assert not trace_path.exists()
else:
    raise AssertionError(f"unexpected captured-target proof mode: {mode}")
"""

_MISSING_ORIGINAL_LOCK_PROBE = """
import os
import sys
from pathlib import Path

storage_path = Path(sys.argv[1])
os.environ.pop("_VAULTSPEC_RAG_PYTEST_SINGLETON_ACTIVE", None)
os.environ.pop("_VAULTSPEC_RAG_PYTEST_SINGLETON_ROOT", None)
os.environ.pop("PYTEST_CURRENT_TEST", None)
os.environ["_VAULTSPEC_RAG_PYTEST_SINGLETON_BOOTSTRAP"] = "1"
os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = str(storage_path)

from vaultspec_rag._machine_lock import machine_lock_path
from vaultspec_rag.cli._gpu_lease import capture_borrower_service_target
from vaultspec_rag.config._settings import reset_config

reset_config()
original_lock = machine_lock_path()
assert not original_lock.exists()
assert capture_borrower_service_target() is None
assert not original_lock.exists(), "captured target observation created an absent lock"
original_lock.parent.mkdir(parents=True)
original_lock.write_text("retired anchor", encoding="utf-8")
original_lock.unlink()
assert capture_borrower_service_target() is None
assert not original_lock.exists(), (
    "captured target observation recreated a deleted lock"
)
"""


@contextlib.contextmanager
def _captured_resident_routes(
    tmp_path: Path,
    *,
    trace_path: Path,
    reject_first_pause: bool,
) -> Generator[Path]:
    """Run a real no-lifespan route host holding the original machine identity."""
    ready_path = tmp_path / "resident-ready"
    stop_path = tmp_path / "resident-stop"
    ready_path.unlink(missing_ok=True)
    stop_path.unlink(missing_ok=True)
    port = free_loopback_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _RESIDENT_ROUTE_HOST,
            str(port),
            str(ready_path),
            str(stop_path),
            str(trace_path),
            "1" if reject_first_pause else "0",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
        while not ready_path.is_file() and process.poll() is None:
            assert time.monotonic() < deadline, "resident route host did not start"
            time.sleep(0.01)
        host_lock_path = Path(ready_path.read_text(encoding="utf-8"))
        assert host_lock_path.is_absolute()
        assert host_lock_path.is_absolute()
        yield host_lock_path
    finally:
        if process.poll() is None:
            stop_path.write_text("stop", encoding="ascii")
        try:
            process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
        assert process.stderr is not None
        stderr = process.stderr.read()
        process.stderr.close()
        assert process.returncode == 0, stderr


def _run_captured_target_proof(
    *,
    mode: str,
    marker_path: Path,
    trace_path: Path,
    host_lock_path: Path,
) -> None:
    """Exercise capture, root registration, redirection, and borrower work."""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd() / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _CAPTURED_TARGET_PROBE,
            mode,
            str(marker_path),
            str(trace_path),
            str(host_lock_path.parent / "storage"),
            str(marker_path.parent / f"{mode}-redirected-root"),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        env=environment,
        timeout=_PROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_captured_target_uses_original_lease_after_singleton_paths_redirect(
    tmp_path: Path,
) -> None:
    """Pin first bearer, retry, post-root refusal, and isolated storage."""
    proofs = (
        ("same-token-401", True),
        ("rotated-token", False),
        ("stale-pointer", False),
        ("health-token-mismatch", False),
    )
    for mode, reject_first_pause in proofs:
        marker_path = tmp_path / f"{mode}-work"
        trace_path = tmp_path / f"{mode}-pause-trace"
        with _captured_resident_routes(
            tmp_path,
            trace_path=trace_path,
            reject_first_pause=reject_first_pause,
        ) as host_lock_path:
            _run_captured_target_proof(
                mode=mode,
                marker_path=marker_path,
                trace_path=trace_path,
                host_lock_path=host_lock_path,
            )


def test_capture_missing_original_lock_never_creates_an_anchor(tmp_path: Path) -> None:
    """The original-path observation refuses missing or deleted anchors intact."""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd() / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _MISSING_ORIGINAL_LOCK_PROBE,
            str(tmp_path / "missing-lock-storage" / "storage"),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        env=environment,
        timeout=_PROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
