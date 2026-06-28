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

from .._machine_lock import (
    machine_discovery_path,
    machine_lock_path,
    read_machine_discovery,
)
from ..config import EnvVar, reset_config
from ..server._lifecycle import _unlink_status_file_silently, _write_machine_discovery

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture
def _isolated_machine_paths(  # pyright: ignore[reportUnusedFunction]
    tmp_path: Path,
) -> Iterator[None]:
    status_key = EnvVar.STATUS_DIR.value
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    prior = {
        status_key: os.environ.get(status_key),
        storage_key: os.environ.get(storage_key),
    }
    os.environ[status_key] = str(tmp_path / "status")
    os.environ[storage_key] = str(tmp_path / "qdrant" / "storage")
    reset_config()
    try:
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


@pytest.mark.usefixtures("_isolated_machine_paths")
class TestMachineDiscoveryPointer:
    def test_pointer_sits_beside_the_lock(self) -> None:
        pointer = machine_discovery_path()
        assert pointer.parent == machine_lock_path().parent
        assert pointer.name == "service.json"

    def test_read_is_none_when_absent(self) -> None:
        assert read_machine_discovery() is None

    def test_write_then_read_round_trips_the_payload(self) -> None:
        payload: dict[str, object] = {
            "schema": "vaultspec-rag.service-discovery",
            "version": 1,
            "port": 8766,
            "pid": 4242,
            "service_token": "tok-abc",
            "last_heartbeat": "2026-06-27T00:00:00+00:00",
        }
        _write_machine_discovery(payload)
        got = read_machine_discovery()
        assert got is not None
        assert got["port"] == 8766
        assert got["service_token"] == "tok-abc"
        assert got["pid"] == 4242

    def test_read_tolerates_garbage_and_non_object_json(self) -> None:
        pointer = machine_discovery_path()
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text("}{ not json", encoding="utf-8")
        assert read_machine_discovery() is None
        pointer.write_text("[1, 2, 3]", encoding="utf-8")  # valid JSON, not an object
        assert read_machine_discovery() is None

    def test_shutdown_cleanup_removes_the_pointer(self) -> None:
        _write_machine_discovery({"port": 8766})
        assert machine_discovery_path().exists()
        _unlink_status_file_silently()
        assert not machine_discovery_path().exists()
