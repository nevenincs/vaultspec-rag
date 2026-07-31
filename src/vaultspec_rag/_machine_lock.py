"""Machine-scoped service singleton lock.

The resident RAG service owns the machine's single GPU and the single managed
Qdrant (one port, one single-writer storage), so exactly one resident service
may run per machine. This module provides the crash-safe lock that enforces it.

It is a neutral leaf - it depends only on the config - so both the CLI
(pre-flight refusal in ``server start``) and the daemon lifespan (the
authoritative hold) can import it without a ``server`` <-> ``cli`` import cycle.

The lock is an **OS advisory lock** (``fcntl.flock`` on POSIX, ``msvcrt.locking``
on Windows) held on a lock file for the lifetime of the holding process. The OS
guarantees mutual exclusion with no create/reclaim race, and releases the lock
automatically when the process dies - so a crashed daemon never strands the
lock (no manual cleanup, no stale-file reclaim heuristic). The file's body
records the holder pid purely for a human-readable refusal message; the lock,
not the file content, is the authority.

The lock file lives alongside the machine-global managed Qdrant storage (the
shared hardware), NOT under the per-instance status dir, so it is machine-wide
even when ``VAULTSPEC_RAG_STATUS_DIR`` is overridden (the dashboard's
project-local case) - while ``VAULTSPEC_RAG_QDRANT_STORAGE_DIR`` still relocates
it, because the lock belongs with the storage it guards.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, SupportsIndex, cast

from ._atomic_write import JsonWriteOptions, write_json_atomically

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "CapturedMachineLockWitness",
    "MachineLockLease",
    "PreIsolationMachineLock",
    "acquire_machine_lock",
    "acquire_machine_lock_lease",
    "capture_pre_isolation_machine_lock",
    "delete_machine_discovery",
    "machine_discovery_path",
    "machine_lock_live_holder",
    "machine_lock_path",
    "publish_machine_discovery",
    "read_machine_discovery",
    "release_machine_lock",
    "release_machine_lock_lease",
    "revalidate_captured_machine_lock",
]

_MACHINE_LOCK_FILENAME = "service.lock"

# The machine-global discovery pointer sits beside the lock, so it is
# STATUS_DIR-independent like the lock: a consumer that does not share rag's
# VAULTSPEC_RAG_STATUS_DIR can still find the one running service. It is distinct
# from the per-STATUS_DIR ``service.json`` (a different directory), and the daemon
# writes the SAME versioned discovery payload to both on each heartbeat.


@dataclass(frozen=True, slots=True, eq=False)
class MachineLockLease:
    """Process-local proof that this process owns one machine lock.

    A lease is valid only while it is the exact object retained in this
    module's active-lease registry.  Reconstructing the same path, PID, and
    descriptor therefore cannot manufacture publication authority.
    """

    path: Path
    pid: int
    descriptor: int


@dataclass(frozen=True, slots=True, init=False)
class PreIsolationMachineLock:
    """Read-only projection of one registry-owned pre-root lock capture.

    Callers can use the projected paths for diagnostics and discovery reads,
    but cannot construct a record that the witness registry will recognize.
    """

    witness: CapturedMachineLockWitness
    identity_lock_path: Path
    discovery_path: Path
    holder_pid: int


@dataclass(frozen=True, slots=True, init=False, repr=False, eq=False)
class CapturedMachineLockWitness:
    """A redacted in-process reference to one captured machine lock identity."""

    def __init__(self) -> None:
        raise TypeError("captured machine lock witnesses are minted internally")

    def __repr__(self) -> str:
        """Keep diagnostics useful without exposing retained original paths."""
        return "CapturedMachineLockWitness(<redacted>)"

    def __reduce__(self) -> NoReturn:
        """Forbid serializing a process-local original machine identity."""
        raise TypeError("captured machine lock witnesses are not serializable")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        """Forbid every pickle protocol without exposing a fallback state."""
        del protocol
        return self.__reduce__()


@dataclass(frozen=True, slots=True)
class _CapturedMachineLockRecord:
    """The registry-only original paths and expected owner for one witness."""

    identity_lock_path: Path
    discovery_path: Path
    holder_pid: int


def _project_captured_machine_lock(
    witness: CapturedMachineLockWitness,
    record: _CapturedMachineLockRecord,
) -> PreIsolationMachineLock:
    """Return the immutable public projection for one private registry record."""
    projection = object.__new__(PreIsolationMachineLock)
    object.__setattr__(projection, "witness", witness)
    object.__setattr__(projection, "identity_lock_path", record.identity_lock_path)
    object.__setattr__(projection, "discovery_path", record.discovery_path)
    object.__setattr__(projection, "holder_pid", record.holder_pid)
    return projection


# Keeping the descriptor reachable through the retained lease is what keeps
# the OS lock held.  Pointer mutation and release are serialized with this
# registry so a lease cannot be released between its authority check and the
# filesystem operation it authorizes.
_held_leases: dict[str, MachineLockLease] = {}
_lease_guard = threading.RLock()
_captured_machine_lock_records: dict[
    CapturedMachineLockWitness, _CapturedMachineLockRecord
] = {}
_captured_machine_lock_minted: set[CapturedMachineLockWitness] = set()
_captured_machine_lock_guard = threading.RLock()


def machine_lock_path() -> Path:
    """Path of the machine-scoped service lock (alongside the shared storage)."""
    from .config._settings import get_config

    storage = Path(str(get_config().qdrant_storage_dir)).expanduser()
    return storage.parent / _MACHINE_LOCK_FILENAME


def machine_discovery_path() -> Path:
    """Path of the machine-global discovery pointer (beside the lock).

    STATUS_DIR-independent (anchored to the machine-global Qdrant storage, like the
    lock), so a consumer that does not share rag's ``VAULTSPEC_RAG_STATUS_DIR`` can
    discover the one running service. The daemon writes the versioned discovery
    payload here on each heartbeat and removes it on shutdown.
    """
    from .config._paths import SERVICE_STATUS_FILENAME

    return machine_lock_path().parent / SERVICE_STATUS_FILENAME


def read_machine_discovery() -> dict[str, object] | None:
    """Read the machine-global discovery pointer, or ``None`` when absent.

    Tolerant by design (mirroring a consumer's own discovery): a missing or
    unreadable/non-JSON file is truthful absence, never an error - the caller
    applies the heartbeat staleness contract the payload carries (it is discovery,
    not the singleton authority; the OS lock remains that). Returns the parsed
    object, or ``None`` when the file is absent, unreadable, or not a JSON object.
    """
    try:
        raw = machine_discovery_path().read_text(encoding="utf-8")
        parsed: object = json.loads(raw)
    except (OSError, ValueError):
        return None
    return cast("dict[str, object]", parsed) if isinstance(parsed, dict) else None


def _lease_discovery_path(lease: MachineLockLease) -> Path:
    """Return the discovery pointer governed by *lease*."""
    from .config._paths import SERVICE_STATUS_FILENAME

    return lease.path.parent / SERVICE_STATUS_FILENAME


def _require_active_lease(
    lease: MachineLockLease,
    *,
    operation: str,
) -> None:
    """Reject pointer mutation without the exact retained live lease."""
    active = _held_leases.get(str(lease.path))
    if active is not lease or lease.pid != os.getpid():
        msg = f"cannot {operation} without the active machine-lock lease"
        raise PermissionError(msg)
    try:
        os.fstat(lease.descriptor)
    except OSError as exc:
        msg = f"cannot {operation} after the machine-lock lease was closed"
        raise PermissionError(msg) from exc


def publish_machine_discovery(
    lease: MachineLockLease,
    payload: Mapping[str, object],
) -> None:
    """Atomically publish *payload* while *lease* proves owner authority.

    The payload must name the lease-owning PID.  Serialization happens before
    filesystem mutation, and replacement uses a unique temporary file in the
    pointer directory so concurrent or interrupted writes cannot expose a
    partial document or collide on a shared temporary name.
    """
    payload_pid = payload.get("pid")
    if type(payload_pid) is not int or payload_pid != lease.pid:
        msg = "machine discovery payload PID must match the machine-lock lease"
        raise ValueError(msg)
    pointer = _lease_discovery_path(lease)
    from ._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="publish the machine service discovery pointer",
        targets=(lease.path, pointer),
    )
    with _lease_guard:
        _require_active_lease(lease, operation="publish machine discovery")
        write_json_atomically(
            pointer, payload, JsonWriteOptions(indent=2, durable=True)
        )


def delete_machine_discovery(lease: MachineLockLease) -> None:
    """Delete the machine pointer only while *lease* remains authoritative."""
    pointer = _lease_discovery_path(lease)
    from ._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="delete the machine service discovery pointer",
        targets=(lease.path, pointer),
    )
    with _lease_guard:
        _require_active_lease(lease, operation="delete machine discovery")
        pointer.unlink(missing_ok=True)


def acquire_machine_lock_lease() -> tuple[MachineLockLease | None, int]:
    """Acquire and retain the machine lock; return its owner capability.

    Takes a non-blocking exclusive OS lock. Returns ``(lease, our_pid)`` on
    success or ``(None, holder_pid)`` when another process holds the lock, where
    ``holder_pid`` is the recorded pid for the refusal message (0 if
    unreadable). Crash-safe: a dead holder's lock is released by the OS, so a
    later acquire simply succeeds with no stale-file reclaim.
    """
    path = machine_lock_path()
    from ._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="acquire the machine service lock",
        targets=(path,),
    )
    with _lease_guard:
        retained = _held_leases.get(str(path))
        if retained is not None:
            _require_active_lease(retained, operation="reuse the machine lock")
            return (retained, retained.pid)
    from ._anchor_claim import (
        claim_anchor,
        record_claim_owner,
        release_anchor_claim,
    )

    claim = claim_anchor(path, pid_record=True, create_parent=True)
    if claim.fault is not None:
        # Proceeding without the claim is the one outcome this lock cannot
        # have: two daemons would each believe they own the machine's single
        # GPU and single-writer storage, so a mechanism that cannot be used
        # fails the caller rather than admitting it.
        raise claim.fault
    if claim.descriptor is None:
        return (None, claim.holder_pid)
    # The durable PID witness is required for a contender to correlate this
    # holder with its discovery record. If it cannot be written, release the
    # OS lock before failing rather than admit an unverifiable singleton.
    try:
        record_claim_owner(claim.descriptor)
    except BaseException:
        release_anchor_claim(claim.descriptor, pid_record=True)
        raise
    lease = MachineLockLease(path=path, pid=os.getpid(), descriptor=claim.descriptor)
    with _lease_guard:
        _held_leases[str(path)] = lease
    return (lease, lease.pid)


def acquire_machine_lock() -> tuple[bool, int]:
    """Acquire the machine lock for callers not yet carrying the lease object."""
    lease, holder = acquire_machine_lock_lease()
    return (lease is not None, holder)


def release_machine_lock_lease(lease: MachineLockLease) -> None:
    """Release *lease* if it is the exact capability currently retained."""
    from ._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="release the machine service lock",
        targets=(lease.path,),
    )
    from ._anchor_claim import release_anchor_claim

    with _lease_guard:
        if _held_leases.get(str(lease.path)) is not lease:
            return
        _held_leases.pop(str(lease.path))
        release_anchor_claim(lease.descriptor, pid_record=True)


def release_machine_lock() -> None:
    """Release the machine-scoped service lock if this process holds it.

    Unlocks and closes the fd; deliberately does NOT unlink the lock file. The
    file's existence is not the authority (the OS lock is), and unlinking after
    unlocking is racy: a contender that acquires in the unlock->unlink window
    would have its freshly-locked file deleted out from under it, and the next
    acquire would create a fresh inode and lock it uncontended - two live
    holders. The lingering file is harmless; the next acquirer overwrites the
    stale pid, and a dead/empty file is always acquirable.
    """
    path = machine_lock_path()
    from ._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="release the machine service lock",
        targets=(path,),
    )
    with _lease_guard:
        lease = _held_leases.get(str(path))
    if lease is None:
        return
    release_machine_lock_lease(lease)


def _probe_existing_machine_lock_holder(identity_lock_path: Path) -> int | None:
    """Read a positive PID from one preselected, already-existing lock path.

    This is the narrow pre-registration captured-target observer. Unlike the
    configured-path probe below, it neither resolves configuration nor creates
    an anchor; callers receive no lease or path-selection capability.
    """
    from ._anchor_claim import probe_existing_anchor_holder

    return probe_existing_anchor_holder(identity_lock_path, pid_record=True)


def capture_pre_isolation_machine_lock() -> PreIsolationMachineLock | None:
    """Capture one existing original machine lock without path input or writes.

    This is the only public bridge to the private raw-path probe. It derives
    the configured machine identity and discovery paths before pytest redirects
    them, then returns evidence only when a positive owner PID is recovered
    from a currently contended lock.
    """
    from ._test_isolation import (
        ManagedSingletonIsolationError,
        pytest_singleton_bootstrap_window,
    )

    try:
        with pytest_singleton_bootstrap_window(
            operation="capture a pre-isolation machine lock witness"
        ):
            try:
                identity_lock_path = machine_lock_path().resolve(strict=False)
                discovery_path = machine_discovery_path().resolve(strict=False)
            except (OSError, RuntimeError, ValueError):
                return None
            holder_pid = _probe_existing_machine_lock_holder(identity_lock_path)
            if holder_pid is None:
                return None
            witness = object.__new__(CapturedMachineLockWitness)
            record = _CapturedMachineLockRecord(
                identity_lock_path=identity_lock_path,
                discovery_path=discovery_path,
                holder_pid=holder_pid,
            )
            with _captured_machine_lock_guard:
                _captured_machine_lock_records[witness] = record
    except ManagedSingletonIsolationError:
        return None
    return _project_captured_machine_lock(witness, record)


def revalidate_captured_machine_lock(
    witness: object,
) -> PreIsolationMachineLock | None:
    """Return a fresh projection only for its original live captured holder."""
    if not isinstance(witness, CapturedMachineLockWitness):
        return None
    with _captured_machine_lock_guard:
        record = _captured_machine_lock_records.get(witness)
    if record is None:
        return None
    holder_pid = _probe_existing_machine_lock_holder(record.identity_lock_path)
    if holder_pid != record.holder_pid:
        return None
    return _project_captured_machine_lock(witness, record)


def consume_captured_machine_lock_for_borrower_authority(
    witness: object,
) -> Path:
    """Consume one witness for a borrower authority and derive its sibling."""
    if not isinstance(witness, CapturedMachineLockWitness):
        raise PermissionError(
            "a captured GPU borrower lease requires a machine witness"
        )
    with _captured_machine_lock_guard:
        record = _captured_machine_lock_records.get(witness)
        if record is None or witness in _captured_machine_lock_minted:
            raise PermissionError(
                "the captured machine lock witness is stale or consumed"
            )
        _captured_machine_lock_minted.add(witness)
    return record.identity_lock_path.with_name("gpu-borrower.lock")


def machine_lock_live_holder() -> int:
    """Return the pid of a *live* lock holder, or 0 when free/stale.

    A fast, side-effect-free pre-flight for ``server start``: probes the OS lock
    (acquire-then-immediately-release) without disturbing a real holder. A
    non-zero result means a resident service is already running on this machine
    and a second must not be spawned.
    """
    path = machine_lock_path()
    from ._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="probe the machine service lock",
        targets=(path,),
    )
    with _lease_guard:
        retained = _held_leases.get(str(path))
        if retained is not None:
            _require_active_lease(retained, operation="probe the machine lock")
            return retained.pid
    if not path.exists():
        return 0
    from ._anchor_claim import claim_anchor, release_anchor_claim

    # No owner pid is recorded here: this probe answers a question and must
    # leave the lock file exactly as it found it, so a later contender reads
    # the real holder's record rather than one a probe left behind.
    claim = claim_anchor(path, pid_record=True)
    if claim.fault is not None:
        # An anchor that cannot be opened is truthful absence - there is
        # nothing there to hold. A platform with no advisory-lock primitive is
        # not: it cannot answer at all, and reporting the lock free would tell
        # the caller it may spawn a second resident service.
        if isinstance(claim.fault, ImportError):
            raise claim.fault
        return 0
    if claim.descriptor is None:
        return claim.holder_pid
    # Nobody holds it (free, or a dead holder the OS already released).
    release_anchor_claim(claim.descriptor, pid_record=True)
    return 0
