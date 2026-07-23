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
it for tests.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "MachineLockLease",
    "acquire_machine_lock",
    "acquire_machine_lock_lease",
    "delete_machine_discovery",
    "machine_discovery_path",
    "machine_lock_live_holder",
    "machine_lock_path",
    "publish_machine_discovery",
    "read_machine_discovery",
    "release_machine_lock",
    "release_machine_lock_lease",
]

_MACHINE_LOCK_FILENAME = "service.lock"

# The machine-global discovery pointer sits beside the lock, so it is
# STATUS_DIR-independent like the lock: a consumer that does not share rag's
# VAULTSPEC_RAG_STATUS_DIR can still find the one running service. It is distinct
# from the per-STATUS_DIR ``service.json`` (a different directory), and the daemon
# writes the SAME versioned discovery payload to both on each heartbeat.
_MACHINE_DISCOVERY_FILENAME = "service.json"

# The byte offset the OS lock is taken at. On Windows ``msvcrt.locking`` is
# MANDATORY - a locked byte cannot be read by another process - so the lock byte
# must sit well beyond the recorded-pid JSON (which lives at offset 0) so a
# contender can still read the holder pid for its refusal message. Windows
# permits locking a byte past EOF; POSIX ``flock`` is whole-file and ignores the
# offset entirely.
_LOCK_OFFSET = 1 << 20


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


# Keeping the descriptor reachable through the retained lease is what keeps
# the OS lock held.  Pointer mutation and release are serialized with this
# registry so a lease cannot be released between its authority check and the
# filesystem operation it authorizes.
_held_leases: dict[str, MachineLockLease] = {}
_lease_guard = threading.RLock()


def machine_lock_path() -> Path:
    """Path of the machine-scoped service lock (alongside the shared storage)."""
    from .config import get_config

    storage = Path(str(get_config().qdrant_storage_dir)).expanduser()
    return storage.parent / _MACHINE_LOCK_FILENAME


def machine_discovery_path() -> Path:
    """Path of the machine-global discovery pointer (beside the lock).

    STATUS_DIR-independent (anchored to the machine-global Qdrant storage, like the
    lock), so a consumer that does not share rag's ``VAULTSPEC_RAG_STATUS_DIR`` can
    discover the one running service. The daemon writes the versioned discovery
    payload here on each heartbeat and removes it on shutdown.
    """
    return machine_lock_path().parent / _MACHINE_DISCOVERY_FILENAME


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
    return lease.path.parent / _MACHINE_DISCOVERY_FILENAME


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
    encoded = json.dumps(payload, indent=2)
    pointer = _lease_discovery_path(lease)
    from ._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="publish the machine service discovery pointer",
        targets=(lease.path, pointer),
    )
    with _lease_guard:
        _require_active_lease(lease, operation="publish machine discovery")
        pointer.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=pointer.parent,
                prefix=f".{pointer.name}.{lease.pid}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, pointer)
            temporary = None
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    temporary.unlink()


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


def _machine_lock_holder(path: Path) -> int:
    """Return the pid recorded in the lock file, or 0 when absent/unreadable.

    Informational only (for the refusal message); the OS lock is the authority.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    pid = cast("dict[str, object]", data).get("pid") if isinstance(data, dict) else None
    return int(pid) if isinstance(pid, int) else 0


def _try_lock_exclusive(fd: int) -> bool:
    """Take a non-blocking exclusive OS lock on *fd*; return whether acquired."""
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    """Release the OS lock on *fd* (best effort)."""
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lease_guard:
        retained = _held_leases.get(str(path))
        if retained is not None:
            _require_active_lease(retained, operation="reuse the machine lock")
            return (retained, retained.pid)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    if not _try_lock_exclusive(fd):
        holder = _machine_lock_holder(path)
        os.close(fd)
        return (None, holder)
    # We hold the lock. Record our pid for the refusal message a future
    # contender will read; the lock itself is the authority.
    with contextlib.suppress(OSError):
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, json.dumps({"pid": os.getpid()}).encode("utf-8"))
        os.fsync(fd)
    lease = MachineLockLease(path=path, pid=os.getpid(), descriptor=fd)
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
    with _lease_guard:
        if _held_leases.get(str(lease.path)) is not lease:
            return
        _held_leases.pop(str(lease.path))
        _unlock(lease.descriptor)
        with contextlib.suppress(OSError):
            os.close(lease.descriptor)


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
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return 0
    try:
        if _try_lock_exclusive(fd):
            # Nobody holds it (free, or a dead holder the OS already released).
            _unlock(fd)
            return 0
        return _machine_lock_holder(path)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
