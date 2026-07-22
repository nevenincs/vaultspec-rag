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
from ..server._lifecycle import _DiscoveryPublisher, _unlink_status_file_silently

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
        _unlink_status_file_silently(owner_publisher)
        assert not machine_discovery_path().exists()
