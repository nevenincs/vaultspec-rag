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
    DISCOVERY_REASON_POINTER_FOREIGN,
    DISCOVERY_REASON_POINTER_INVALID,
    DISCOVERY_REASON_POINTER_MISSING,
    DISCOVERY_REASON_POINTER_STALE,
    DISCOVERY_SOURCE_MACHINE_POINTER,
    DISCOVERY_SOURCE_NONE,
    DISCOVERY_SOURCE_STATUS_FILE,
    DISCOVERY_STATE_ABSENT,
    DISCOVERY_STATE_DEGRADED,
    DISCOVERY_STATE_READY,
    _default_service_port,
    _status_file,
    resolve_machine_service,
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


def _write_raw_pointer(text: str) -> None:
    """Write arbitrary bytes to the machine pointer (corruption cases)."""
    pointer = machine_discovery_path()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(text, encoding="utf-8")


def _write_pointer(
    port: int,
    *,
    heartbeat_age_s: float,
    token: str = "tok",
    pid: int | None = None,
) -> None:
    """Write a real machine-global discovery pointer with the given heartbeat age."""
    pointer = machine_discovery_path()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    stamp = (datetime.now(UTC) - timedelta(seconds=heartbeat_age_s)).isoformat(
        timespec="seconds"
    )
    pointer.write_text(
        json.dumps(
            {
                "pid": os.getpid() if pid is None else pid,
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
        resolution = resolve_machine_service()
        assert not resolution.is_ready
        assert _default_service_port() is None

    def test_live_lock_and_fresh_pointer_resolves_the_port(self) -> None:
        """A live lock holder plus a fresh pointer resolves to the pointer's port."""
        acquired, _holder = acquire_machine_lock()
        assert acquired
        _write_pointer(8812, heartbeat_age_s=1)

        resolution = resolve_machine_service()
        assert resolution.is_ready
        assert resolution.source == DISCOVERY_SOURCE_MACHINE_POINTER
        assert resolution.payload is not None
        assert resolution.payload["port"] == 8812
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

        resolution = resolve_machine_service()
        assert not resolution.is_ready
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

        # The resolution IS ready here - from the status file, which is the
        # fallback this test is about. The deleted compatibility view
        # collapsed "not from the machine pointer" into None, which read as
        # "nothing resolved"; naming the source says which one is meant.
        assert resolve_machine_service().source != DISCOVERY_SOURCE_MACHINE_POINTER
        assert _default_service_port() == 9777


@pytest.mark.usefixtures("isolated_machine_dir")
class TestTypedMachineResolution:
    """Typed resolution preserves holder, pointer, freshness, and reason."""

    def test_no_holder_and_no_status_file_is_absent(self) -> None:
        """Absence is the only state with no live holder and no address."""
        resolution = resolve_machine_service()

        assert resolution.state == DISCOVERY_STATE_ABSENT
        assert resolution.source == DISCOVERY_SOURCE_NONE
        assert resolution.is_ready is False
        assert resolution.is_degraded is False
        assert resolution.port is None
        assert resolution.reason is None

    def test_live_holder_and_fresh_pointer_is_ready_with_evidence(self) -> None:
        """A holder that published a fresh pointer resolves ready with identity."""
        acquired, _holder = acquire_machine_lock()
        assert acquired
        _write_pointer(8821, heartbeat_age_s=1, token="tok-ready")

        resolution = resolve_machine_service()

        assert resolution.state == DISCOVERY_STATE_READY
        assert resolution.source == DISCOVERY_SOURCE_MACHINE_POINTER
        assert resolution.is_ready is True
        assert resolution.port == 8821
        assert resolution.holder_pid == os.getpid()
        assert resolution.pointer_pid == os.getpid()
        assert resolution.service_token == "tok-ready"
        assert resolution.heartbeat_age_s is not None
        assert resolution.stale_after_s == 60
        assert resolution.reason is None

    def test_live_holder_without_a_pointer_is_degraded_not_absent(self) -> None:
        """A holder that never published must not read as stopped.

        Reporting absence here would invite a caller to start a second daemon
        that can only lose the singleton race.
        """
        acquired, _holder = acquire_machine_lock()
        assert acquired

        resolution = resolve_machine_service()

        assert resolution.state == DISCOVERY_STATE_DEGRADED
        assert resolution.reason == DISCOVERY_REASON_POINTER_MISSING
        assert resolution.holder_pid == os.getpid()
        assert resolution.port is None
        assert resolution.is_degraded is True

    def test_unparseable_pointer_is_degraded(self) -> None:
        """Corrupt pointer bytes under a live holder never resolve an address."""
        acquired, _holder = acquire_machine_lock()
        assert acquired
        _write_raw_pointer("{not json at all")

        resolution = resolve_machine_service()

        assert resolution.state == DISCOVERY_STATE_DEGRADED
        # An unreadable pointer is indistinguishable from an absent one to the
        # tolerant reader, so either refusal is correct: both are degraded and
        # neither yields an address.
        assert resolution.reason in {
            DISCOVERY_REASON_POINTER_MISSING,
            DISCOVERY_REASON_POINTER_INVALID,
        }
        assert resolution.port is None

    def test_portless_pointer_is_degraded_invalid(self) -> None:
        """A well-formed pointer with no usable port resolves invalid."""
        acquired, _holder = acquire_machine_lock()
        assert acquired
        _write_raw_pointer(json.dumps({"pid": os.getpid(), "service_token": "t"}))

        resolution = resolve_machine_service()

        assert resolution.state == DISCOVERY_STATE_DEGRADED
        assert resolution.reason == DISCOVERY_REASON_POINTER_INVALID
        assert resolution.port is None

    def test_stale_pointer_is_degraded_with_freshness_evidence(self) -> None:
        """A hours-old heartbeat under a live holder resolves stale, not ready."""
        acquired, _holder = acquire_machine_lock()
        assert acquired
        _write_pointer(8822, heartbeat_age_s=7200)

        resolution = resolve_machine_service()

        assert resolution.state == DISCOVERY_STATE_DEGRADED
        assert resolution.reason == DISCOVERY_REASON_POINTER_STALE
        assert resolution.heartbeat_age_s is not None
        assert resolution.stale_after_s is not None
        assert resolution.heartbeat_age_s > resolution.stale_after_s
        # The refused address is still reported as evidence.
        assert resolution.port == 8822

    def test_pointer_naming_another_process_is_degraded_foreign(self) -> None:
        """A pointer whose pid is not the live holder is a leftover, not truth.

        The publisher refuses any payload whose pid is not the lease owner's, so
        a disagreeing pid can only be a previous incarnation's file.
        """
        acquired, _holder = acquire_machine_lock()
        assert acquired
        foreign_pid = os.getppid()
        assert foreign_pid != os.getpid()
        _write_pointer(8823, heartbeat_age_s=1, pid=foreign_pid)

        resolution = resolve_machine_service()

        assert resolution.state == DISCOVERY_STATE_DEGRADED
        assert resolution.reason == DISCOVERY_REASON_POINTER_FOREIGN
        assert resolution.holder_pid == os.getpid()
        assert resolution.pointer_pid == foreign_pid

    def test_status_file_is_the_legacy_fallback_without_a_holder(self) -> None:
        """With no singleton held, the status file still resolves an address."""
        _status_file().write_text(
            json.dumps({"pid": 4242, "port": 9788, "service_token": "legacy"}),
            encoding="utf-8",
        )

        resolution = resolve_machine_service()

        assert resolution.state == DISCOVERY_STATE_READY
        assert resolution.source == DISCOVERY_SOURCE_STATUS_FILE
        assert resolution.port == 9788
        assert resolution.pointer_pid == 4242
        assert resolution.holder_pid == 0
        assert _default_service_port() == 9788

    def test_degraded_resolution_never_falls_back_to_the_status_file(self) -> None:
        """A live holder's degraded pointer must not be papered over.

        The status file can name an address the singleton owner never published;
        accepting it here would send a caller to the wrong daemon rather than
        surfacing that the owner's own publication is untrustworthy.
        """
        acquired, _holder = acquire_machine_lock()
        assert acquired
        _write_pointer(8824, heartbeat_age_s=7200)
        _status_file().write_text(
            json.dumps({"pid": 4242, "port": 9999}), encoding="utf-8"
        )

        resolution = resolve_machine_service()

        assert resolution.state == DISCOVERY_STATE_DEGRADED
        assert resolution.source == DISCOVERY_SOURCE_MACHINE_POINTER
        assert _default_service_port() is None
        assert not resolution.is_ready

    def test_evidence_names_the_disagreement(self) -> None:
        """Degraded evidence carries the reason and both identities."""
        acquired, _holder = acquire_machine_lock()
        assert acquired
        _write_pointer(8825, heartbeat_age_s=1, pid=os.getppid())

        evidence = resolve_machine_service().evidence()

        assert DISCOVERY_REASON_POINTER_FOREIGN in evidence
        assert str(os.getpid()) in evidence
        assert str(os.getppid()) in evidence
