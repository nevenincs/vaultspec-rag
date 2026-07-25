"""Managed-Qdrant identity sidecar write/validate tests.

No mocks, no GPU: the sidecar is written and read back through the real config
resolution (a temp storage dir set via the genuine ``VAULTSPEC_RAG_QDRANT_STORAGE_DIR``
env knob with finally-cleanup, the same way the service is configured), and the
attach verifier is exercised across its gates with constructed inputs.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from ..config import EnvVar, reset_config
from ..qdrant_runtime._resolve import (
    QdrantEndpointProbe,
    QdrantIdentity,
    classify_qdrant_state,
    owner_pid_is_live_owner,
    owner_pid_witness_state,
    pid_start_time,
    qdrant_identity_path,
    read_qdrant_identity,
    verify_attachable,
    write_qdrant_identity,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


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
            owner_start_time=1234.5,
            qdrant_start_time=6789.25,
        )
        assert path == temp_storage.parent / "identity.json"
        assert path == qdrant_identity_path()

        ident = read_qdrant_identity()
        assert ident is not None
        assert ident.storage_path == str(temp_storage)
        assert ident.version == "1.18.2"
        assert ident.owner_pid == 4242
        assert ident.http_port == 8765
        assert ident.owner_start_time == 1234.5
        assert ident.qdrant_start_time == 6789.25

    def test_legacy_sidecar_without_child_witness_reads_as_unwitnessed(
        self,
        temp_storage: Path,
    ) -> None:
        qdrant_identity_path().parent.mkdir(parents=True, exist_ok=True)
        qdrant_identity_path().write_text(
            json.dumps(
                {
                    "storage_path": str(temp_storage),
                    "version": "1.18.2",
                    "owner_pid": 4242,
                    "http_port": 8765,
                    "qdrant_pid": 4343,
                    "owner_start_time": 1234.5,
                }
            ),
            encoding="utf-8",
        )

        ident = read_qdrant_identity()

        assert ident is not None
        assert ident.qdrant_pid == 4343
        assert ident.qdrant_start_time == 0.0

    def test_read_missing_sidecar_is_none(self, temp_storage: Path) -> None:
        assert qdrant_identity_path() == temp_storage.parent / "identity.json"
        assert not qdrant_identity_path().exists()
        assert read_qdrant_identity() is None


class TestVerifyAttachable:
    def _identity(self, storage: str) -> QdrantIdentity:
        live_start = pid_start_time(os.getpid())
        return QdrantIdentity(
            storage_path=storage,
            version="1.18.2",
            owner_pid=os.getpid(),
            http_port=8765,
            qdrant_pid=os.getpid(),
            owner_start_time=live_start,
            qdrant_start_time=live_start,
        )

    def test_refuse_when_witnessed_child_is_not_qdrant(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.18.2")
        ok, reason = verify_attachable(
            probe,
            self._identity("/srv/storage"),
            expected_port=8765,
            expected_version="1.18.2",
            expected_storage="/srv/storage",
        )
        assert ok is False
        assert "image" in reason.lower()

    def test_refuse_when_not_ready(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=False, version="1.18.2")
        ok, reason = verify_attachable(
            probe,
            self._identity("/srv/storage"),
            expected_port=8765,
            expected_version="1.18.2",
            expected_storage="/srv/storage",
        )
        assert ok is False
        assert "ready" in reason

    def test_refuse_when_no_identity(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.18.2")
        ok, reason = verify_attachable(
            probe,
            None,
            expected_port=8765,
            expected_version="1.18.2",
            expected_storage="/srv/storage",
        )
        assert ok is False
        assert "not ours" in reason or "identity" in reason

    def test_refuse_on_version_mismatch(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.17.0")
        ok, reason = verify_attachable(
            probe,
            self._identity("/srv/storage"),
            expected_port=8765,
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
            expected_port=8765,
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
            expected_port=8765,
            expected_version="1.18.2",
            expected_storage="/srv/storage",
        )
        assert ok is False
        assert "version" in reason


class TestOwnerPidReuseWitness:
    """The owner start-time pins ownership to one process incarnation.

    A dead owner's pid recycled by an unrelated live process must NOT read as a
    live owner: data safety already holds via the health/version/storage gates,
    but the ownership proof itself must reject a recycled pid so a foreign
    process is never classified ``managed_running``.
    """

    def _identity(self, owner_pid: int, owner_start_time: float) -> QdrantIdentity:
        return QdrantIdentity(
            storage_path="/srv/storage",
            version="1.18.2",
            owner_pid=owner_pid,
            http_port=8765,
            qdrant_pid=owner_pid,
            owner_start_time=owner_start_time,
        )

    def test_pid_start_time_is_readable_for_self(self) -> None:
        # The witness must actually be readable for a live process, or the whole
        # gate degenerates. This process is alive, so its start time is positive.
        assert pid_start_time(os.getpid()) > 0.0

    def test_pid_start_time_zero_for_dead_pid(self) -> None:
        assert pid_start_time(2_000_000_000) == 0.0

    def test_matching_start_time_is_the_live_owner(self) -> None:
        live = pid_start_time(os.getpid())
        identity = self._identity(os.getpid(), live)
        assert owner_pid_is_live_owner(identity) is True

    def test_mismatched_start_time_is_not_the_owner(self) -> None:
        # A live pid (this process) but a recorded start time from a DIFFERENT
        # incarnation: the recycled-pid case. The owner is NOT this process.
        live = pid_start_time(os.getpid())
        identity = self._identity(os.getpid(), live + 10_000.0)
        assert owner_pid_is_live_owner(identity) is False

    def test_unreadable_live_owner_is_unverified_not_orphaned(self) -> None:
        live = pid_start_time(os.getpid())
        identity = self._identity(os.getpid(), live)
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.18.2")

        assert owner_pid_witness_state(identity, timeout=0.0) == "unknown"
        assert (
            classify_qdrant_state(probe, identity, owner_timeout=0.0)
            == "owner_unverified"
        )

    def test_legacy_record_without_witness_is_unverified(self) -> None:
        """A live PID cannot substitute for a missing incarnation witness."""
        identity = self._identity(os.getpid(), 0.0)
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.18.2")
        assert owner_pid_is_live_owner(identity) is False
        assert owner_pid_witness_state(identity) == "unknown"
        assert classify_qdrant_state(probe, identity) == "owner_unverified"

    def test_dead_owner_is_never_the_live_owner(self) -> None:
        identity = self._identity(2_000_000_000, 0.0)
        assert owner_pid_is_live_owner(identity) is False

    def test_classify_running_requires_matching_witness(self) -> None:
        # A listening server whose recorded owner pid is live but whose start
        # time mismatches (recycled pid) classifies as managed_orphan, NOT
        # managed_running - so it is reaped, never attached/competed with.
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.18.2")
        live = pid_start_time(os.getpid())
        recycled = self._identity(os.getpid(), live + 10_000.0)
        assert classify_qdrant_state(probe, recycled) == "managed_orphan"

        matched = self._identity(os.getpid(), live)
        assert classify_qdrant_state(probe, matched) == "managed_running"
