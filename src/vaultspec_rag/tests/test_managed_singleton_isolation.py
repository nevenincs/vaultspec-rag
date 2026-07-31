"""Real-behavior regressions for pytest-owned machine-singleton containment."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from vaultspec_core.config import (
    reset_config as reset_core_config,
)

from .._machine_lock import (
    MachineLockLease,
    acquire_machine_lock,
    delete_machine_discovery,
    machine_lock_live_holder,
    machine_lock_path,
    publish_machine_discovery,
    release_machine_lock,
)
from .._test_isolation import (
    PYTEST_MANAGED_SINGLETON_ACTIVE_ENV,
    PYTEST_MANAGED_SINGLETON_BOOTSTRAP_ENV,
    PYTEST_MANAGED_SINGLETON_ROOT_ENV,
    ManagedSingletonIsolationError,
    register_pytest_singleton_root,
)
from ..cli._process import _spawn_service, _terminate_pid
from ..config._settings import reset_config as reset_rag_config
from ..config._types import EnvVar
from ..qdrant_runtime._resolve import (
    qdrant_identity_path,
    reap_qdrant_orphan,
    write_qdrant_identity,
)
from ..qdrant_runtime._supervise import (
    QdrantSupervisor,
    set_active_supervisor,
    start_supervised_from_config,
)
from ..server._lifecycle import _resolve_log_path
from ..serviceclient._discovery import (
    _delete_service_status,
    _merge_service_status,
)

if TYPE_CHECKING:
    from collections.abc import Generator

# Tiers are declared per test rather than for the module: the live-supervised
# case needs real infrastructure, and a module-level default would be ADDED to
# its `integration` mark rather than overridden by it, leaving it in the fast lane.

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SINGLETON_ENV_NAMES = (
    PYTEST_MANAGED_SINGLETON_ACTIVE_ENV,
    PYTEST_MANAGED_SINGLETON_ROOT_ENV,
    EnvVar.STATUS_DIR.value,
    EnvVar.QDRANT_STORAGE_DIR.value,
)

_AMBIENT_CHILD_PROGRAM = r"""
import json
import os

from vaultspec_rag._machine_lock import (  # absolute-import-ok
    MachineLockLease,
    acquire_machine_lock,
    machine_lock_path,
    publish_machine_discovery,
)
from vaultspec_rag._test_isolation import (  # absolute-import-ok
    ManagedSingletonIsolationError,
)
from vaultspec_rag.qdrant_runtime._resolve import (  # absolute-import-ok
    write_qdrant_identity,
)
from vaultspec_rag.serviceclient._discovery import (  # absolute-import-ok
    _merge_service_status,
)

operations = (
    ("status", lambda: _merge_service_status({"pid": os.getpid(), "port": 1})),
    ("lock", acquire_machine_lock),
    (
        "identity",
        lambda: write_qdrant_identity(
            storage_path=os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"],
            version="test",
            owner_pid=os.getpid(),
            http_port=1,
            owner_start_time=0.0,
            qdrant_start_time=0.0,
        ),
    ),
    (
        "pointer",
        lambda: publish_machine_discovery(
            MachineLockLease(machine_lock_path(), os.getpid(), 0),
            {"pid": os.getpid(), "port": 1},
        ),
    ),
)

outcomes = {}
for name, operation in operations:
    try:
        operation()
    except ManagedSingletonIsolationError as exc:
        outcomes[name] = exc.__class__.__name__
    else:
        outcomes[name] = "unguarded"
print(json.dumps(outcomes, sort_keys=True))
"""


def _reset_singleton_configs() -> None:
    """Make direct environment transitions visible to both production caches."""
    reset_core_config()
    reset_rag_config()


@contextmanager
def _redirect_singletons_to_trap(
    trap: Path,
    *,
    redirect_status: bool = True,
    redirect_storage: bool = True,
) -> Generator[None]:
    """Aim selected configured anchors and mutable guard transport at *trap*."""
    prior = {name: os.environ.get(name) for name in _SINGLETON_ENV_NAMES}
    os.environ[PYTEST_MANAGED_SINGLETON_ACTIVE_ENV] = "0"
    os.environ[PYTEST_MANAGED_SINGLETON_ROOT_ENV] = str(trap)
    if redirect_status:
        os.environ[EnvVar.STATUS_DIR.value] = str(trap / "status")
    if redirect_storage:
        os.environ[EnvVar.QDRANT_STORAGE_DIR.value] = str(
            trap / "qdrant-server" / "storage"
        )
    _reset_singleton_configs()
    try:
        yield
    finally:
        for name, value in prior.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _reset_singleton_configs()


@contextmanager
def _outside_session_trap() -> Generator[Path]:
    """Create a test-owned directory beside, never beneath, the session root."""
    session_root = Path(os.environ[PYTEST_MANAGED_SINGLETON_ROOT_ENV]).resolve()
    with tempfile.TemporaryDirectory(
        prefix="vaultspec-rag-singleton-trap-",
        dir=session_root.parent,
    ) as raw_trap:
        trap = Path(raw_trap).resolve()
        assert trap != session_root
        assert session_root not in trap.parents
        yield trap


@contextmanager
def _isolated_qdrant_runtime(storage_dir: Path, http_port: int) -> Generator[None]:
    """Select unique contained storage and a verified provisioned binary."""
    names = (
        EnvVar.QDRANT_STORAGE_DIR.value,
        EnvVar.QDRANT_PORT.value,
        EnvVar.QDRANT_BINARY.value,
    )
    prior = {name: os.environ.get(name) for name in names}
    os.environ[EnvVar.QDRANT_STORAGE_DIR.value] = str(storage_dir)
    os.environ[EnvVar.QDRANT_PORT.value] = str(http_port)
    os.environ.pop(EnvVar.QDRANT_BINARY.value, None)
    _reset_singleton_configs()
    try:
        yield
    finally:
        for name, value in prior.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _reset_singleton_configs()


def _free_adjacent_qdrant_ports() -> int:
    """Return a currently free HTTP port whose preceding gRPC port is free."""
    for _attempt in range(100):
        with socket.socket() as http_socket, socket.socket() as grpc_socket:
            http_socket.bind(("127.0.0.1", 0))
            http_port = int(http_socket.getsockname()[1])
            if http_port <= 1024:
                continue
            try:
                grpc_socket.bind(("127.0.0.1", http_port - 1))
            except OSError:
                continue
            return http_port
    raise RuntimeError("could not reserve adjacent Qdrant test ports")


@pytest.mark.unit
def test_hostile_ambient_paths_cannot_redirect_exec_child_writers() -> None:
    """An activated exec child rejects unsafe paths present before import."""
    with _outside_session_trap() as trap:
        safe_root = trap.parent / f"{trap.name}-safe-root"
        safe_root.mkdir()
        try:
            env = os.environ.copy()
            env.pop("PYTEST_CURRENT_TEST", None)
            env.pop(PYTEST_MANAGED_SINGLETON_BOOTSTRAP_ENV, None)
            env[PYTEST_MANAGED_SINGLETON_ACTIVE_ENV] = "1"
            env[PYTEST_MANAGED_SINGLETON_ROOT_ENV] = str(safe_root)
            env[EnvVar.STATUS_DIR.value] = str(trap / "status")
            env[EnvVar.QDRANT_STORAGE_DIR.value] = str(
                trap / "qdrant-server" / "storage"
            )

            completed = subprocess.run(
                [sys.executable, "-c", _AMBIENT_CHILD_PROGRAM],
                cwd=_REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=20.0,
            )

            assert completed.returncode == 0, completed.stderr
            assert json.loads(completed.stdout) == {
                "identity": "ManagedSingletonIsolationError",
                "lock": "ManagedSingletonIsolationError",
                "pointer": "ManagedSingletonIsolationError",
                "status": "ManagedSingletonIsolationError",
            }
            assert list(trap.iterdir()) == []
        finally:
            safe_root.rmdir()


@pytest.mark.unit
def test_in_test_path_changes_cannot_redirect_singleton_writers() -> None:
    """Pinned process authority rejects re-anchoring and every writer trap."""
    with _outside_session_trap() as trap:
        with pytest.raises(ManagedSingletonIsolationError, match="re-anchor"):
            register_pytest_singleton_root(trap)

        with _redirect_singletons_to_trap(trap):
            with pytest.raises(ManagedSingletonIsolationError):
                _merge_service_status({"pid": os.getpid(), "port": 1})
            with pytest.raises(ManagedSingletonIsolationError):
                acquire_machine_lock()
            with pytest.raises(ManagedSingletonIsolationError):
                machine_lock_live_holder()
            with pytest.raises(ManagedSingletonIsolationError):
                release_machine_lock()
            with pytest.raises(ManagedSingletonIsolationError):
                write_qdrant_identity(
                    storage_path=str(trap / "qdrant-server" / "storage"),
                    version="test",
                    owner_pid=os.getpid(),
                    http_port=1,
                    owner_start_time=0.0,
                    qdrant_start_time=0.0,
                )
            with pytest.raises(ManagedSingletonIsolationError):
                publish_machine_discovery(
                    MachineLockLease(machine_lock_path(), os.getpid(), 0),
                    {"pid": os.getpid(), "port": 1},
                )
            with pytest.raises(ManagedSingletonIsolationError):
                _resolve_log_path()

        assert list(trap.iterdir()) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("redirect_status", "redirect_storage"),
    ((True, False), (False, True)),
)
def test_each_configured_anchor_fails_closed_independently(
    redirect_status: bool,
    redirect_storage: bool,
) -> None:
    """Either unsafe configured anchor blocks even a non-mutating lock probe."""
    with _outside_session_trap() as trap:
        with (
            _redirect_singletons_to_trap(
                trap,
                redirect_status=redirect_status,
                redirect_storage=redirect_storage,
            ),
            pytest.raises(ManagedSingletonIsolationError),
        ):
            machine_lock_live_holder()

        assert list(trap.iterdir()) == []


@pytest.mark.unit
def test_in_test_path_changes_cannot_delete_singleton_records() -> None:
    """Status and pointer deletion fail before touching an unsafe target."""
    with _outside_session_trap() as trap:
        status = trap / "status" / "service.json"
        pointer = trap / "qdrant-server" / "service.json"
        status.parent.mkdir(parents=True)
        pointer.parent.mkdir(parents=True)
        status.write_text("status-owned-by-test", encoding="utf-8")
        pointer.write_text("pointer-owned-by-test", encoding="utf-8")

        with _redirect_singletons_to_trap(trap):
            with pytest.raises(ManagedSingletonIsolationError):
                _delete_service_status()
            with pytest.raises(ManagedSingletonIsolationError):
                delete_machine_discovery(
                    MachineLockLease(machine_lock_path(), os.getpid(), 0)
                )

        assert status.read_text(encoding="utf-8") == "status-owned-by-test"
        assert pointer.read_text(encoding="utf-8") == "pointer-owned-by-test"


@pytest.mark.unit
def test_in_test_path_changes_cannot_control_processes() -> None:
    """A real child remains alive when managed process control is uncontained."""
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    sentinel = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    try:
        with _outside_session_trap() as trap:
            status_dir = trap / "status"
            status_dir.mkdir()
            with _redirect_singletons_to_trap(trap):
                with pytest.raises(ManagedSingletonIsolationError):
                    _terminate_pid(sentinel.pid, timeout=0.1)
                with pytest.raises(ManagedSingletonIsolationError):
                    reap_qdrant_orphan(sentinel.pid, wait_seconds=0.1)
                with pytest.raises(ManagedSingletonIsolationError):
                    _spawn_service(
                        1,
                        status_dir,
                        timeout=0.1,
                    )

                supervisor = QdrantSupervisor(
                    trap / "missing-qdrant",
                    http_port=2,
                    storage_dir=trap / "qdrant-server" / "storage",
                    log_path=trap / "qdrant.log",
                )
                with pytest.raises(ManagedSingletonIsolationError):
                    supervisor.spawn()
                assert supervisor.pid is None

            assert sentinel.poll() is None
            assert sorted(path.name for path in trap.iterdir()) == ["status"]
    finally:
        if sentinel.poll() is None:
            sentinel.terminate()
            try:
                sentinel.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                sentinel.kill()
                sentinel.wait(timeout=5.0)


@pytest.mark.integration
def test_in_test_path_changes_cannot_stop_live_supervised_qdrant(
    required_host_provisioned_qdrant_source: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    """The live owned Qdrant child survives an uncontained stop attempt."""
    binary, manifest = required_host_provisioned_qdrant_source
    assert binary.is_file()
    assert manifest.is_file()

    supervisor: QdrantSupervisor | None = None
    http_port = _free_adjacent_qdrant_ports()
    storage_dir = tmp_path / "qdrant-server" / "storage"
    with _isolated_qdrant_runtime(storage_dir, http_port):
        identity_path = qdrant_identity_path()
        try:
            supervisor = start_supervised_from_config()
            child_pid = supervisor.pid
            assert child_pid is not None
            assert supervisor.is_alive()

            with _outside_session_trap() as trap:
                with (
                    _redirect_singletons_to_trap(trap),
                    pytest.raises(ManagedSingletonIsolationError),
                ):
                    supervisor.stop(timeout=0.1)

                assert supervisor.pid == child_pid
                assert supervisor.is_alive()

            supervisor.stop()
            assert supervisor.pid is None
        finally:
            if supervisor is not None:
                supervisor.stop()
            set_active_supervisor(None)
            identity_path.unlink(missing_ok=True)
