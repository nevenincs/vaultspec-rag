"""Unit tests for the machine-global discovery pointer (rag-broker-affordances).

The pointer lets a consumer that does not share rag's ``VAULTSPEC_RAG_STATUS_DIR``
find the one running service. No mocks: the tests write and read a real file at a
temp-isolated machine-global path (the managed-singleton isolation rule), and clean
it through the real shutdown hook.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from .. import server as server_state
from .._machine_lock import (
    acquire_machine_lock_lease,
    machine_discovery_path,
    machine_lock_path,
    read_machine_discovery,
    release_machine_lock_lease,
)
from ..config import EnvVar, reset_config
from ..server._lifecycle import _DiscoveryPublisher

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture
def owner_publisher(
    tmp_path: Path,
) -> Iterator[_DiscoveryPublisher]:
    status_key = EnvVar.STATUS_DIR.value
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    prior = {
        status_key: os.environ.get(status_key),
        storage_key: os.environ.get(storage_key),
    }
    os.environ[status_key] = str(tmp_path / "status")
    os.environ[storage_key] = str(tmp_path / "qdrant" / "storage")
    reset_config()
    prior_port = server_state._service_port
    prior_token = server_state._SERVICE_TOKEN
    prior_launch_token = server_state._launch_token
    server_state._service_port = 8766
    server_state._SERVICE_TOKEN = "test-owner-token"
    server_state._launch_token = "test-launch-token"
    lease, holder = acquire_machine_lock_lease()
    assert lease is not None
    assert holder == os.getpid()
    publisher = _DiscoveryPublisher(lease)
    try:
        yield publisher
    finally:
        publisher.quiesce()
        publisher.cleanup()
        release_machine_lock_lease(lease)
        server_state._service_port = prior_port
        server_state._SERVICE_TOKEN = prior_token
        server_state._launch_token = prior_launch_token
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


@pytest.mark.usefixtures("owner_publisher")
class TestMachineDiscoveryPointer:
    def test_pointer_sits_beside_the_lock(self) -> None:
        pointer = machine_discovery_path()
        assert pointer.parent == machine_lock_path().parent
        assert pointer.name == "service.json"

    def test_read_is_none_when_absent(self) -> None:
        assert read_machine_discovery() is None

    def test_owner_publish_then_read_round_trips_the_payload(
        self,
        owner_publisher: _DiscoveryPublisher,
    ) -> None:
        payload = owner_publisher.publish_phase("warming")
        assert payload is not None
        got = read_machine_discovery()
        assert got is not None
        assert got == payload
        assert got["port"] == 8766
        assert got["service_token"] == "test-owner-token"
        assert got["pid"] == os.getpid()

    def test_read_tolerates_garbage_and_non_object_json(self) -> None:
        pointer = machine_discovery_path()
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text("}{ not json", encoding="utf-8")
        assert read_machine_discovery() is None
        pointer.write_text("[1, 2, 3]", encoding="utf-8")  # valid JSON, not an object
        assert read_machine_discovery() is None

    def test_shutdown_cleanup_removes_the_pointer(
        self,
        owner_publisher: _DiscoveryPublisher,
    ) -> None:
        owner_publisher.heartbeat()
        assert machine_discovery_path().exists()
        assert owner_publisher.cleanup() is True
        assert not machine_discovery_path().exists()


class TestBoundedShutdownGuard:
    """Shutdown-time discovery guard waits are bounded, not unbounded."""

    def test_quiesce_does_not_block_on_a_wedged_publish_guard(self) -> None:
        """A heartbeat worker wedged mid-publish must not strand teardown.

        ``quiesce`` is the first step of daemon shutdown and holds the same
        ``_guard`` a synchronous heartbeat tick takes across its file I/O. If a
        tick wedges (slow or contended status/pointer write), an unbounded
        ``with self._guard:`` would block quiesce forever before any shutdown
        line is logged. The bounded form abandons the join past its deadline,
        sets the stop flag anyway, and returns. Reverting to the unbounded
        acquire makes this block until the wedged holder releases at ~15s and
        the timing assertion fails - so it guards the bound, not merely the
        call.
        """
        import threading
        import time

        from .._machine_lock import MachineLockLease

        publisher = _DiscoveryPublisher(
            MachineLockLease(machine_lock_path(), os.getpid(), 0)
        )
        held = threading.Event()
        release = threading.Event()

        def wedged_publish() -> None:
            # A different thread holds the guard (the mid-publish tick) and does
            # not release it within the bound.
            publisher._guard.acquire()  # pyright: ignore[reportPrivateUsage]
            held.set()
            release.wait(timeout=15.0)
            publisher._guard.release()  # pyright: ignore[reportPrivateUsage]

        worker = threading.Thread(target=wedged_publish)
        worker.start()
        try:
            assert held.wait(timeout=5.0), "holder never took the publish guard"
            started = time.monotonic()
            publisher.quiesce(timeout=1.0)
            elapsed = time.monotonic() - started
            assert elapsed < 3.0, f"quiesce blocked for {elapsed:.1f}s"
            assert elapsed >= 1.0, "quiesce should honour its acquire bound"
            # Stop is flagged even though the guard was abandoned, so a later
            # tick that finishes observes it and goes inert.
            assert publisher._stopping is True  # pyright: ignore[reportPrivateUsage]
        finally:
            release.set()
            worker.join(timeout=5.0)
