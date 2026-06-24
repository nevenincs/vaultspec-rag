"""Managed-Qdrant identity sidecar write/validate tests (plan W02.P03).

No mocks, no GPU: the sidecar is written and read back through the real config
resolution (a temp storage dir set via the genuine ``VAULTSPEC_RAG_QDRANT_STORAGE_DIR``
env knob with finally-cleanup, the same way the service is configured), and the
attach verifier is exercised across its gates with constructed inputs.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ..config import EnvVar, reset_config
from ..qdrant_runtime._resolve import (
    QdrantEndpointProbe,
    QdrantIdentity,
    qdrant_identity_path,
    read_qdrant_identity,
    verify_attachable,
    write_qdrant_identity,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def temp_storage(tmp_path: Path) -> Iterator[Path]:
    """Point qdrant_storage_dir at a temp dir via the real env knob."""
    storage = tmp_path / "qdrant-server" / "storage"
    key = EnvVar.QDRANT_STORAGE_DIR.value
    previous = os.environ.get(key)
    os.environ[key] = str(storage)
    reset_config()
    try:
        yield storage
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous
        reset_config()


class TestIdentityRoundTrip:
    def test_write_then_read_roundtrips(self, temp_storage: Path) -> None:
        path = write_qdrant_identity(
            storage_path=str(temp_storage),
            version="1.18.2",
            owner_pid=4242,
            http_port=8765,
        )
        assert path == temp_storage.parent / "identity.json"
        assert path == qdrant_identity_path()

        ident = read_qdrant_identity()
        assert ident is not None
        assert ident.storage_path == str(temp_storage)
        assert ident.version == "1.18.2"
        assert ident.owner_pid == 4242
        assert ident.http_port == 8765

    def test_read_missing_sidecar_is_none(self, temp_storage: Path) -> None:
        assert qdrant_identity_path() == temp_storage.parent / "identity.json"
        assert not qdrant_identity_path().exists()
        assert read_qdrant_identity() is None


class TestVerifyAttachable:
    def _identity(self, storage: str) -> QdrantIdentity:
        return QdrantIdentity(
            storage_path=storage, version="1.18.2", owner_pid=1, http_port=8765
        )

    def test_attachable_when_ready_owned_and_capable(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.18.2")
        ok, reason = verify_attachable(
            probe,
            self._identity("/srv/storage"),
            expected_version="1.18.2",
            expected_storage="/srv/storage",
        )
        assert ok is True, reason

    def test_refuse_when_not_ready(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=False, version="1.18.2")
        ok, reason = verify_attachable(
            probe,
            self._identity("/srv/storage"),
            expected_version="1.18.2",
            expected_storage="/srv/storage",
        )
        assert ok is False
        assert "ready" in reason

    def test_refuse_when_no_identity(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.18.2")
        ok, reason = verify_attachable(
            probe, None, expected_version="1.18.2", expected_storage="/srv/storage"
        )
        assert ok is False
        assert "not ours" in reason or "identity" in reason

    def test_refuse_on_version_mismatch(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.17.0")
        ok, reason = verify_attachable(
            probe,
            self._identity("/srv/storage"),
            expected_version="1.18.2",
            expected_storage="/srv/storage",
        )
        assert ok is False
        assert "version" in reason

    def test_refuse_on_storage_mismatch(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.18.2")
        ok, reason = verify_attachable(
            probe,
            self._identity("/srv/other-storage"),
            expected_version="1.18.2",
            expected_storage="/srv/storage",
        )
        assert ok is False
        assert "storage" in reason

    def test_refuse_on_empty_unreadable_version(self) -> None:
        # An unreadable (empty) version is a capability-gate FAILURE, not a pass:
        # attaching to a server whose version we could not confirm defeats the
        # version check.
        probe = QdrantEndpointProbe(listening=True, ready=True, version="")
        ok, reason = verify_attachable(
            probe,
            self._identity("/srv/storage"),
            expected_version="1.18.2",
            expected_storage="/srv/storage",
        )
        assert ok is False
        assert "version" in reason
