"""The one OS advisory-lock primitive: take and release a byte on an fd.

Every module needing a cross-process lock reaches the ``msvcrt``/``fcntl``
branch through here, so the platform split has one implementation. This module
owns the platform call and nothing else, because what a caller does AROUND it
differs for real reasons:

- **Which file.** A caller may lock its own payload file, or a dedicated
  ``.lock`` sibling nobody reads.
- **Which byte.** That distinction is why ``offset`` exists. On Windows
  ``msvcrt.locking`` is MANDATORY - a locked byte cannot be READ by another
  process - so a caller locking a file whose contents others must read has to
  put the lock byte past the payload, and a caller locking a dedicated file
  does not need to.
- **What contention means.** One caller retries until a deadline, one refuses
  immediately, one records the error for a diagnostic, one degrades to running
  unserialised. So this raises ``OSError`` - what the platform calls already
  do - and lets each decide, rather than flattening the outcome to a bool and
  discarding the cause.

Deliberately NOT handled here: a platform with neither primitive. Proceeding
unlocked is safe for a status-file merge and catastrophic for a singleton lock
that two daemons would then both believe they hold, so the import error
surfaces and each caller decides whether it can tolerate running unlocked.

One sequence built on this call IS shared rather than per-caller, and has its
own owner in ``_anchor_claim``: open an anchor, claim it without blocking,
record the owning pid, read that pid back when refused, release on close or on
process death. A caller wanting only the platform call uses this module
directly.
"""

from __future__ import annotations

import contextlib
import os
import sys

__all__ = ["lock_fd_exclusive", "unlock_fd"]


def lock_fd_exclusive(fd: int, *, offset: int = 0) -> None:
    """Take a non-blocking exclusive advisory lock on one byte of *fd*.

    Args:
        fd: Open file descriptor to lock.
        offset: Byte offset to lock, honoured on Windows only. POSIX
            ``flock`` is whole-file and ignores it. Pass a value past the
            payload when other processes must still read the file, because a
            Windows lock makes the byte unreadable rather than merely
            advisory.

    Raises:
        OSError: Another holder has the lock, or the platform call failed.
        ImportError: The platform ships neither ``msvcrt`` nor ``fcntl``.

    """
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, offset, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_fd(fd: int, *, offset: int = 0) -> None:
    """Release the lock taken by :func:`lock_fd_exclusive`, best effort.

    Swallows ``OSError``: the fd is being closed or the process is exiting on
    every path that reaches here, and a failed release has no remedy the
    caller could apply. *offset* must match the one used to take the lock.
    """
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, offset, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
