"""Discovery-file schema, version, and timestamp-format contract tests (#190).

No mocks: the real CLI-parent writer and the real daemon heartbeat tick are driven
against an isolated status dir, and the written ``service.json`` is read back. The
contract under test is that both writers agree on the ``(schema, version)``
discriminator and on one declared timestamp format (ISO-8601 with offset, second
precision) for ``started_at`` and ``last_heartbeat`` - the divergence that broke a
consumer that parsed the heartbeat as an epoch number.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

import vaultspec_rag.server as _m

from .._atomic_write import JsonWriteOptions, write_json_atomically
from .._machine_lock import acquire_machine_lock_lease, release_machine_lock_lease
from ..cli._service_status import _write_service_status
from ..config._settings import reset_config
from ..config._types import EnvVar
from ..server._lifecycle import _DiscoveryPublisher
from ..server._state import (
    _HEARTBEAT_INTERVAL_SECONDS,
)
from ..serviceclient._discovery import (
    HEARTBEAT_STALENESS_SECONDS,
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
    SERVICE_PHASE_WARMING,
    _delete_service_status,
    _merge_service_status,
    _status_file,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _is_second_precision_offset_iso(value: str) -> bool:
    """True iff value is ISO-8601, timezone-aware, with no fractional seconds."""
    parsed = datetime.fromisoformat(value)
    return (
        parsed.utcoffset() is not None and parsed.microsecond == 0 and "." not in value
    )


def test_atomic_json_options_publish_exact_bytes_and_clean_up(tmp_path: Path) -> None:
    """The production writer retains each observable serialization choice."""
    target = tmp_path / "state.json"
    target.write_bytes(b"obsolete")

    write_json_atomically(
        target,
        {"z": 1, "a": "value"},
        JsonWriteOptions(indent=2, sort_keys=True, compact=True, durable=True),
    )

    assert target.read_bytes() == b'{\n  "a":"value",\n  "z":1\n}'
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


@pytest.fixture
def status_dir(tmp_path: Path) -> Iterator[Path]:
    """Point the discovery file at an isolated temp status dir."""
    status_key = EnvVar.STATUS_DIR.value
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    previous = {
        status_key: os.environ.get(status_key),
        storage_key: os.environ.get(storage_key),
    }
    os.environ[status_key] = str(tmp_path / "status")
    os.environ[storage_key] = str(tmp_path / "qdrant" / "storage")
    reset_config()
    try:
        yield tmp_path / "status"
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


@pytest.fixture
def owner_publisher(status_dir: Path) -> Iterator[_DiscoveryPublisher]:
    """Retain the real isolated machine owner for daemon publications."""
    assert status_dir == _status_file().parent
    prior_port = _m._service_port
    prior_token = _m._SERVICE_TOKEN
    prior_launch = _m._launch_token
    _m._service_port = 8766
    _m._SERVICE_TOKEN = "test-token"
    _m._launch_token = "test-launch-token"
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
        _m._service_port = prior_port
        _m._SERVICE_TOKEN = prior_token
        _m._launch_token = prior_launch


@pytest.mark.usefixtures("owner_publisher")
class TestDiscoverySchema:
    def test_parent_write_carries_schema_version_and_second_precision_timestamp(
        self,
    ) -> None:
        _write_service_status(1234, 8766)
        data = json.loads(_status_file().read_text(encoding="utf-8"))
        assert data["schema"] == SERVICE_DISCOVERY_SCHEMA
        assert data["version"] == SERVICE_DISCOVERY_VERSION
        assert _is_second_precision_offset_iso(data["started_at"])

    def test_heartbeat_preserves_version_and_matches_timestamp_format(
        self,
        owner_publisher: _DiscoveryPublisher,
    ) -> None:
        _write_service_status(os.getpid(), 8766)
        _m._heartbeat_tick_sync(owner_publisher)
        data = json.loads(_status_file().read_text(encoding="utf-8"))
        assert data["schema"] == SERVICE_DISCOVERY_SCHEMA
        assert data["version"] == SERVICE_DISCOVERY_VERSION
        # Both writers emit the one declared format for both timestamp fields.
        assert _is_second_precision_offset_iso(data["started_at"])
        assert _is_second_precision_offset_iso(data["last_heartbeat"])
        # The staleness contract is surfaced in the file, sourced from config.
        assert data["heartbeat_interval_s"] == _HEARTBEAT_INTERVAL_SECONDS
        assert data["stale_after_s"] == HEARTBEAT_STALENESS_SECONDS

    def test_atomic_write_leaves_no_tmp_and_parses(self, status_dir: Path) -> None:
        _write_service_status(1234, 8766)
        assert list(status_dir.glob("*.tmp")) == []
        data = json.loads(_status_file().read_text(encoding="utf-8"))
        assert data["version"] == SERVICE_DISCOVERY_VERSION

    def test_late_parent_preserves_same_port_daemon_identity(self) -> None:
        daemon_started = "2026-07-16T10:00:00+00:00"
        _merge_service_status(
            {
                "schema": SERVICE_DISCOVERY_SCHEMA,
                "version": SERVICE_DISCOVERY_VERSION,
                "pid": 9001,
                "port": 8766,
                "started_at": daemon_started,
                "phase": SERVICE_PHASE_WARMING,
                "qdrant_pid": 9002,
                "qdrant_start_time": 1234.5,
            }
        )

        _write_service_status(8001, 8766)

        data = json.loads(_status_file().read_text(encoding="utf-8"))
        assert data["pid"] == 9001
        assert data["started_at"] == daemon_started
        assert data["phase"] == SERVICE_PHASE_WARMING
        assert data["qdrant_pid"] == 9002
        assert data["qdrant_start_time"] == 1234.5

    def test_parent_write_obeys_remaining_status_lock_budget(self) -> None:
        lock_path = _status_file().with_name("service.json.lock")
        ready_path = lock_path.with_suffix(".ready")
        lock_call = (
            "import msvcrt;msvcrt.locking(f.fileno(),msvcrt.LK_LOCK,1);"
            if sys.platform == "win32"
            else "import fcntl;fcntl.flock(f.fileno(),fcntl.LOCK_EX);"
        )
        script = (
            "import os,sys,time;"
            "p=sys.argv[1];r=sys.argv[2];"
            "f=open(p,'a+b');"
            "f.write(b'0') if os.path.getsize(p)==0 else None;"
            "f.flush();f.seek(0);"
            f"{lock_call}"
            "open(r,'w').close();time.sleep(5)"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", script, str(lock_path), str(ready_path)]
        )
        try:
            deadline = time.monotonic() + 5.0
            while not ready_path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready_path.exists()
            started = time.monotonic()
            with pytest.raises(TimeoutError, match="status write lock"):
                _write_service_status(1234, 8766, timeout=0.050)
            assert time.monotonic() - started < 0.250
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_locked_delete_cannot_be_resurrected_by_cross_process_merge(
        self,
        status_dir: Path,
    ) -> None:
        """A waiting require-existing publisher observes the deletion tombstone."""
        _write_service_status(os.getpid(), 8766)
        ready_path = status_dir / "merge-ready"
        result_path = status_dir / "merge-result"
        script = (
            "import sys;"
            "from pathlib import Path;"
            "from vaultspec_rag.serviceclient._discovery import "
            "_merge_service_status;"
            "status=Path(sys.argv[1]);ready=Path(sys.argv[2]);"
            "result=Path(sys.argv[3]);"
            "ready.write_text('ready',encoding='utf-8');"
            "i=0;"
            "\nwhile i < 10000:\n"
            " try:\n"
            "  _merge_service_status({'race_seq':i},path=status,"
            "require_existing=True,timeout=5.0)\n"
            " except FileNotFoundError:\n"
            "  result.write_text(f'deleted:{i}',encoding='utf-8');break\n"
            " i+=1\n"
            "else:\n"
            " result.write_text('never-deleted',encoding='utf-8')\n"
        )
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(_status_file()),
                str(ready_path),
                str(result_path),
            ]
        )
        try:
            deadline = time.monotonic() + 5.0
            while not ready_path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready_path.exists()
            assert _delete_service_status(timeout=5.0) is True
            proc.wait(timeout=10.0)
            assert proc.returncode == 0
            assert result_path.read_text(encoding="utf-8").startswith("deleted:")
            assert not _status_file().exists()
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5.0)

    def test_unversioned_file_is_upgraded_on_first_heartbeat_tick(
        self,
        owner_publisher: _DiscoveryPublisher,
    ) -> None:
        # A file written by an older parent (no schema/version) must gain the
        # discriminator on the first tick. Seed a bare legacy file
        # directly, then tick.
        legacy = {
            "pid": os.getpid(),
            "port": 8766,
            "started_at": "2026-06-24T10:23:52+00:00",
        }
        _status_file().write_text(json.dumps(legacy), encoding="utf-8")
        _m._heartbeat_tick_sync(owner_publisher)
        data = json.loads(_status_file().read_text(encoding="utf-8"))
        assert data["schema"] == SERVICE_DISCOVERY_SCHEMA
        assert data["version"] == SERVICE_DISCOVERY_VERSION
        assert _is_second_precision_offset_iso(data["last_heartbeat"])
