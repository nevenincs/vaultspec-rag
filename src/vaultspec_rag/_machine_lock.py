"""Machine-scoped service singleton lock (ADR D1 / P3).

The resident RAG service owns the machine's single GPU and the single managed
Qdrant (one port, one single-writer storage), so exactly one resident service
may run per machine. This module provides the crash-safe lock that enforces it.

It is a neutral leaf - it depends only on the config and the low-level
``qdrant_runtime`` pid-liveness helper - so both the CLI (pre-flight refusal in
``server start``) and the daemon lifespan (the authoritative hold) can import it
without a ``server`` <-> ``cli`` import cycle.

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
from pathlib import Path

from .qdrant_runtime._resolve import pid_alive

logger = logging.getLogger(__name__)

__all__ = [
    "acquire_machine_lock",
    "machine_lock_live_holder",
    "machine_lock_path",
    "release_machine_lock",
]

_MACHINE_LOCK_FILENAME = "service.lock"


def machine_lock_path() -> Path:
    """Path of the machine-scoped service lock (alongside the shared storage)."""
    from .config import get_config

    storage = Path(str(get_config().qdrant_storage_dir)).expanduser()
    return storage.parent / _MACHINE_LOCK_FILENAME


def _machine_lock_holder(path: Path) -> int:
    """Return the pid recorded in the lock file, or 0 when absent/unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    pid = data.get("pid") if isinstance(data, dict) else None
    return int(pid) if isinstance(pid, int) else 0


def machine_lock_live_holder() -> int:
    """Return the pid of a *live* lock holder, or 0 when free/stale.

    A fast, side-effect-free pre-flight for ``server start``: a non-zero result
    is the signal that a resident service is already running on this machine and
    a second must not be spawned.
    """
    holder = _machine_lock_holder(machine_lock_path())
    return holder if holder and pid_alive(holder) else 0


def acquire_machine_lock() -> tuple[bool, int]:
    """Acquire the machine-scoped service lock; report success and the holder.

    Crash-safe: a lock left by a dead holder (the orphan class this very guard
    addresses) is reclaimed. Returns ``(True, our_pid)`` on success, or
    ``(False, holder_pid)`` when a *live* process already holds it.
    """
    path = machine_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Claim by hard-linking a temp file that ALREADY contains our pid into
    # place. os.link is atomically exclusive (one winner; losers get
    # FileExistsError), and because the link target already holds the pid, the
    # lock file is never observable empty - so a crash can never strand an
    # empty, unreclaimable lock, and a concurrent loser always reads the
    # winner's pid (never a transient holder-0). A holder-0 file can now only be
    # genuine corruption or a legacy file, which is safely reclaimable.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    try:
        for _ in range(2):
            try:
                os.link(tmp, path)
            except FileExistsError:
                holder = _machine_lock_holder(path)
                if holder and holder != os.getpid() and pid_alive(holder):
                    return (False, holder)
                # Our own prior lock, a dead-holder orphan, or a corrupt/empty
                # legacy file: reclaim and retry.
                with contextlib.suppress(OSError):
                    path.unlink()
                continue
            return (True, os.getpid())
        return (False, _machine_lock_holder(path))
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def release_machine_lock() -> None:
    """Release the machine-scoped service lock if this process holds it."""
    path = machine_lock_path()
    if _machine_lock_holder(path) == os.getpid():
        with contextlib.suppress(OSError):
            path.unlink()
