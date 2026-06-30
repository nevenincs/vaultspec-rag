"""Machine-singleton discovery resolution (real lock, real pointer files).

Exercises ``serviceclient._discovery`` against a relocated machine-global managed
directory: a real OS advisory lock for liveness and a real on-disk discovery
pointer for the address. No mocks - the lock is acquired and released for real
and the pointer is a real JSON file, so the staleness and authority contract is
verified against the same primitives production uses. The
``VAULTSPEC_RAG_QDRANT_STORAGE_DIR`` and ``VAULTSPEC_RAG_STATUS_DIR`` knobs are
relocated under a temp dir so the test never touches the real machine singleton.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from .._machine_lock import (
    acquire_machine_lock,
    machine_discovery_path,
    machine_lock_path,
    release_machine_lock,
)
from ..config import EnvVar, reset_config
from ..serviceclient._discovery import (
    _default_service_port,
    _machine_service_resolution,
    _status_file,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture
def isolated_machine_dir(tmp_path: Path) -> Iterator[Path]:
    """Relocate the machine lock/pointer and the status dir under a temp dir."""
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    status_key = EnvVar.STATUS_DIR.value
    previous = {k: os.environ.get(k) for k in (storage_key, status_key)}
    os.environ[storage_key] = str(tmp_path / "qdrant-server" / "storage")
    os.environ[status_key] = str(tmp_path / "status")
    reset_config()
    try:
        yield tmp_path
    finally:
        release_machine_lock()
        lock = machine_lock_path()
        if lock.exists():
            lock.unlink()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


def _write_pointer(port: int, *, heartbeat_age_s: float, token: str = "tok") -> None:
    """Write a real machine-global discovery pointer with the given heartbeat age."""
    pointer = machine_discovery_path()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    stamp = (datetime.now(UTC) - timedelta(seconds=heartbeat_age_s)).isoformat(
        timespec="seconds"
    )
    pointer.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "port": port,
                "service_token": token,
                "last_heartbeat": stamp,
                "stale_after_s": 60,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.usefixtures("isolated_machine_dir")
class TestMachineDiscoveryResolution:
    """Resolution against a relocated machine-global managed directory."""

    def test_no_live_service_resolves_to_none(self) -> None:
        """With no lock holder and no pointer, machine resolution is absence."""
        assert _machine_service_resolution() is None
        assert _default_service_port() is None

    def test_live_lock_and_fresh_pointer_resolves_the_port(self) -> None:
        """A live lock holder plus a fresh pointer resolves to the pointer's port."""
        acquired, _holder = acquire_machine_lock()
        assert acquired
        _write_pointer(8812, heartbeat_age_s=1)

        resolution = _machine_service_resolution()
        assert resolution is not None
        assert resolution["port"] == 8812
        assert _default_service_port() == 8812

    def test_stale_pointer_is_treated_as_absent(self) -> None:
        """A live lock holder with a stale (orphaned) pointer is absence.

        This is the orphaned-pointer case the research found on the live box: a
        days-old heartbeat must not mislead a consumer into connecting to a dead
        address. Resolution returns ``None`` so the caller fails fast.
        """
        acquired, _holder = acquire_machine_lock()
        assert acquired
        _write_pointer(8813, heartbeat_age_s=7200)

        assert _machine_service_resolution() is None
        assert _default_service_port() is None

    def test_machine_resolution_outranks_a_foreign_status_dir(self) -> None:
        """A live machine pointer wins over a present but foreign status-dir file.

        The frozen-singleton bug: a long-lived consumer's own status directory
        holds a ``service.json`` naming a different port. The machine-global
        resolution is authoritative, so the live machine service is reached
        instead of the stale foreign port.
        """
        acquired, _holder = acquire_machine_lock()
        assert acquired
        _write_pointer(8814, heartbeat_age_s=1)

        status = _status_file()
        status.write_text(json.dumps({"pid": 4242, "port": 9999}), encoding="utf-8")

        assert _default_service_port() == 8814

    def test_status_dir_is_the_fallback_when_no_machine_service(self) -> None:
        """With no live machine service, a status-dir file is the compat fallback."""
        status = _status_file()
        status.write_text(json.dumps({"pid": 4242, "port": 9777}), encoding="utf-8")

        assert _machine_service_resolution() is None
        assert _default_service_port() == 9777
