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
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

import vaultspec_rag.server as _m

from ..cli._service_status import _write_service_status
from ..config import EnvVar
from ..server._state import (
    _HEARTBEAT_INTERVAL_SECONDS,
    _HEARTBEAT_STALENESS_SECONDS,
)
from ..serviceclient._discovery import (
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
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


@pytest.fixture
def status_dir(tmp_path: Path) -> Iterator[Path]:
    """Point the discovery file at an isolated temp status dir."""
    key = EnvVar.STATUS_DIR.value
    previous = os.environ.get(key)
    os.environ[key] = str(tmp_path)
    try:
        yield tmp_path
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


@pytest.mark.usefixtures("status_dir")
class TestDiscoverySchema:
    def test_parent_write_carries_schema_version_and_second_precision_timestamp(
        self,
    ) -> None:
        _write_service_status(1234, 8766)
        data = json.loads(_status_file().read_text(encoding="utf-8"))
        assert data["schema"] == SERVICE_DISCOVERY_SCHEMA
        assert data["version"] == SERVICE_DISCOVERY_VERSION
        assert _is_second_precision_offset_iso(data["started_at"])

    def test_heartbeat_preserves_version_and_matches_timestamp_format(self) -> None:
        _write_service_status(os.getpid(), 8766)
        token_prev = _m._SERVICE_TOKEN
        _m._SERVICE_TOKEN = "test-token"
        try:
            _m._heartbeat_tick_sync()
        finally:
            _m._SERVICE_TOKEN = token_prev
        data = json.loads(_status_file().read_text(encoding="utf-8"))
        assert data["schema"] == SERVICE_DISCOVERY_SCHEMA
        assert data["version"] == SERVICE_DISCOVERY_VERSION
        # Both writers emit the one declared format for both timestamp fields.
        assert _is_second_precision_offset_iso(data["started_at"])
        assert _is_second_precision_offset_iso(data["last_heartbeat"])
        # The staleness contract is surfaced in the file, sourced from config.
        assert data["heartbeat_interval_s"] == _HEARTBEAT_INTERVAL_SECONDS
        assert data["stale_after_s"] == _HEARTBEAT_STALENESS_SECONDS

    def test_atomic_write_leaves_no_tmp_and_parses(self, status_dir: Path) -> None:
        _write_service_status(1234, 8766)
        assert list(status_dir.glob("*.tmp")) == []
        data = json.loads(_status_file().read_text(encoding="utf-8"))
        assert data["version"] == SERVICE_DISCOVERY_VERSION

    def test_unversioned_file_is_upgraded_on_first_heartbeat_tick(self) -> None:
        # A file written by an older parent (no schema/version) must gain the
        # discriminator on the first tick (ADR D2). Seed a bare legacy file
        # directly, then tick.
        legacy = {
            "pid": os.getpid(),
            "port": 8766,
            "started_at": "2026-06-24T10:23:52+00:00",
        }
        _status_file().write_text(json.dumps(legacy), encoding="utf-8")
        token_prev = _m._SERVICE_TOKEN
        _m._SERVICE_TOKEN = "test-token"
        try:
            _m._heartbeat_tick_sync()
        finally:
            _m._SERVICE_TOKEN = token_prev
        data = json.loads(_status_file().read_text(encoding="utf-8"))
        assert data["schema"] == SERVICE_DISCOVERY_SCHEMA
        assert data["version"] == SERVICE_DISCOVERY_VERSION
        assert _is_second_precision_offset_iso(data["last_heartbeat"])
