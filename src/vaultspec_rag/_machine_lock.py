"""Machine-scoped service singleton lock (ADR D1 / P3).

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
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "acquire_machine_lock",
    "machine_lock_live_holder",
    "machine_lock_path",
    "release_machine_lock",
]

_MACHINE_LOCK_FILENAME = "service.lock"

# The byte offset the OS lock is taken at. On Windows ``msvcrt.locking`` is
# MANDATORY - a locked byte cannot be read by another process - so the lock byte
# must sit well beyond the recorded-pid JSON (which lives at offset 0) so a
# contender can still read the holder pid for its refusal message. Windows
# permits locking a byte past EOF; POSIX ``flock`` is whole-file and ignores the
# offset entirely.
_LOCK_OFFSET = 1 << 20

# Open fds for locks this process currently holds, keyed by lock path. Keeping
# the fd open is what keeps the OS lock held for the process lifetime; closing
# it (or the process dying) releases the lock.
_held_fds: dict[str, int] = {}


def machine_lock_path() -> Path:
    """Path of the machine-scoped service lock (alongside the shared storage)."""
    from .config import get_config

    storage = Path(str(get_config().qdrant_storage_dir)).expanduser()
    return storage.parent / _MACHINE_LOCK_FILENAME


def _machine_lock_holder(path: Path) -> int:
    """Return the pid recorded in the lock file, or 0 when absent/unreadable.

    Informational only (for the refusal message); the OS lock is the authority.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    pid = data.get("pid") if isinstance(data, dict) else None
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


def acquire_machine_lock() -> tuple[bool, int]:
    """Acquire the machine-scoped service lock; report success and the holder.

    Takes a non-blocking exclusive OS lock. Returns ``(True, our_pid)`` on
    success (the fd is held open for the process lifetime), or
    ``(False, holder_pid)`` when another live process holds the lock - where
    ``holder_pid`` is the recorded pid for the refusal message (0 if
    unreadable). Crash-safe: a dead holder's lock is released by the OS, so a
    later acquire simply succeeds with no stale-file reclaim.
    """
    path = machine_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    if not _try_lock_exclusive(fd):
        holder = _machine_lock_holder(path)
        os.close(fd)
        return (False, holder)
    # We hold the lock. Record our pid for the refusal message a future
    # contender will read; the lock itself is the authority.
    with contextlib.suppress(OSError):
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, json.dumps({"pid": os.getpid()}).encode("utf-8"))
        os.fsync(fd)
    _held_fds[str(path)] = fd
    return (True, os.getpid())


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
    fd = _held_fds.pop(str(path), None)
    if fd is None:
        return
    _unlock(fd)
    with contextlib.suppress(OSError):
        os.close(fd)


def machine_lock_live_holder() -> int:
    """Return the pid of a *live* lock holder, or 0 when free/stale.

    A fast, side-effect-free pre-flight for ``server start``: probes the OS lock
    (acquire-then-immediately-release) without disturbing a real holder. A
    non-zero result means a resident service is already running on this machine
    and a second must not be spawned.
    """
    path = machine_lock_path()
    if str(path) in _held_fds:
        # We already hold it in this process.
        return os.getpid()
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
