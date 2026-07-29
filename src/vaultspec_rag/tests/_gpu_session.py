"""Machine-global admission for one GPU-bound test session at a time.

One card, one GPU session. Two test processes that each load the embedding and
reranker stacks onto a single device exhaust its memory and take the host down
with them, and neither can see the other through anything else the harness owns:
a scheduling group reaches only inside one process, and every configured
singleton path is deliberately redirected into a per-session temporary tree
precisely so that sessions cannot observe each other's state.

The lock taken here is therefore NOT derived from configuration and sits outside
that per-session tree. The device is one piece of machine hardware rather than
per-session state, so a lock relocated with a configured directory would be
private to each session and would serialise nothing. That makes this the one
effect in the harness anchored machine-globally, and the exemption is kept
narrow on purpose: a single fixed file, never read or written for anything but
the holder pid a refusal message quotes, and never a substitute for the OS lock
that is the actual authority.

Ownership lasts for the life of the process. The descriptor stays reachable, so
the operating system releases the lock however the session ends - a clean exit,
a failed run, or a hard kill - and no stale-file reclaim heuristic is needed.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "GpuSessionLease",
    "acquire_gpu_session_lock",
    "gpu_session_lock_path",
    "gpu_session_refusal",
    "release_gpu_session_lock",
]

_LOCK_FILENAME = "vaultspec-rag-gpu-test-session.lock"

# The lock byte sits far past the recorded pid because a Windows lock is
# mandatory rather than advisory: a locked byte cannot be READ by another
# process, and a contender must still read the holder pid for its refusal.
_LOCK_OFFSET = 1 << 20


@dataclass(frozen=True, slots=True, eq=False)
class GpuSessionLease:
    """Process-local proof that this process owns the machine's GPU session."""

    path: Path
    pid: int
    descriptor: int


_held: GpuSessionLease | None = None


def gpu_session_lock_path() -> Path:
    """Path of the machine-global GPU test-session lock."""
    return Path(tempfile.gettempdir()) / _LOCK_FILENAME


def _recorded_holder(path: Path) -> int:
    """Return the pid recorded in the lock file, or 0 when it cannot be read.

    Informational, for the refusal message only; the OS lock is the authority,
    so an absent or truncated record costs the operator a pid and nothing more.
    """
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    pid = recorded.get("pid") if isinstance(recorded, dict) else None
    return pid if isinstance(pid, int) else 0


def acquire_gpu_session_lock(anchor: Path) -> tuple[GpuSessionLease | None, int]:
    """Claim the GPU at *anchor* and hold the claim for this process.

    The anchor is passed in rather than resolved here so that the machine-global
    choice is made in one place and stated at the call site, and so the claiming
    mechanism can be exercised without reserving the real device.

    A process holds at most one claim: acquiring again returns the claim already
    held rather than reserving a second anchor.

    Args:
        anchor: The lock file to claim. Created if absent, never removed.

    Returns:
        ``(lease, own_pid)`` once this process owns the device for the rest of
        the session, or ``(None, holder_pid)`` when another process owns it,
        where ``holder_pid`` is 0 if the recorded pid could not be read.
    """
    global _held
    if _held is not None:
        return (_held, _held.pid)

    from .._fd_lock import lock_fd_exclusive

    path = anchor
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        lock_fd_exclusive(fd, offset=_LOCK_OFFSET)
    except OSError:
        holder = _recorded_holder(path)
        os.close(fd)
        return (None, holder)
    # Record our pid for the refusal a later contender will print. Best effort:
    # the lock is already ours, and a failed write costs that contender a pid.
    with contextlib.suppress(OSError):
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, json.dumps({"pid": os.getpid()}).encode("utf-8"))
        os.fsync(fd)
    _held = GpuSessionLease(path=path, pid=os.getpid(), descriptor=fd)
    return (_held, _held.pid)


def release_gpu_session_lock() -> None:
    """Release the GPU session lock if this process holds it.

    Called when the session tears down, so a long-lived process that ran one
    GPU session does not keep the machine reserved afterwards. Deliberately not
    the guarantee - process death releases the lock whether or not this runs,
    which is what makes a killed session safe - and deliberately not unlinking
    the file, because a contender that acquired between the release and the
    unlink would have its own freshly locked file deleted underneath it.
    """
    global _held
    lease = _held
    if lease is None:
        return
    _held = None

    from .._fd_lock import unlock_fd

    unlock_fd(lease.descriptor, offset=_LOCK_OFFSET)
    with contextlib.suppress(OSError):
        os.close(lease.descriptor)


def gpu_session_refusal(anchor: Path) -> str | None:
    """Claim the GPU at *anchor* for this session, or say why it cannot be had.

    Returns:
        ``None`` once this process owns the device for the rest of the session,
        or the operator-facing reason another session already owns it.
    """
    lease, holder = acquire_gpu_session_lock(anchor)
    if lease is not None:
        return None
    owner = f"process {holder}" if holder else "another process"
    return (
        "refusing to start a second GPU test session on this machine: "
        f"{owner} already holds the device for a session of its own.\n\n"
        "There is one GPU here and each session loads its own model stack onto "
        "it, so two of them exhaust device memory and take the host down "
        "together. Wait for that session to finish, or stop it, before running "
        "the GPU tiers. The claim is released however that session ends, "
        "including a kill, so there is nothing to clean up by hand."
    )
