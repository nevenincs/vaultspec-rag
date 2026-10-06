"""Hold an executable file from before it is hashed until a process runs it.

A digest check says something about a file at the moment it was read. A
process created afterwards by path runs whatever the path names by then, so
the check and the execution have to be tied to one file. How tightly depends
on what the platform offers, and each case is stated here because the
difference is a security property, not a detail.

Windows
    The file is opened without write or delete sharing. For as long as the
    hold lasts nothing can rewrite it, rename it, remove it, replace it, or
    rename a directory above it, so the path names the hashed bytes when the
    process is created. Nothing is left open.

Linux, with ``/proc`` mounted
    The file is opened without following a link and the process is created
    from that descriptor, so it runs the file that was hashed whatever the
    path names by then. A replacement cannot reach it. Rewriting the same
    file in place is not preventable before it executes: the kernel refuses
    writers to a running image, and refuses to execute a file a writer still
    has open, but a writer that finishes between the hash and the execution is
    not refused. That case is caught afterwards - see
    :meth:`HeldExecutable.unchanged` - so a rewritten image can run for the
    time it takes to hash it again, and no longer.

Elsewhere (macOS, the BSDs, Linux without ``/proc``)
    Nothing ties a path to an open file across process creation. The file is
    hashed through the descriptor and the process is created by path. The
    path is confirmed to name the held file before and after, and the content
    is hashed again after. A replacement that is put back before the second
    look is not seen. That window cannot be closed on these platforms.

This module knows nothing about where a binary came from or what digest it is
held to; it only keeps one file in hand.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator
    from io import BufferedReader
    from pathlib import Path

__all__ = ["HeldExecutable", "held_executable"]

_PROC_DESCRIPTORS = "/proc/self/fd"


@dataclass(frozen=True)
class HeldExecutable:
    """One regular file, open, and how a new process is bound to it.

    Attributes:
        path: The path the file was opened by.
        handle: The open file. Every digest is read through it, never
            through the path.
        launch_path: What to create the process from: the path where the hold
            itself pins it or nothing better exists, the held descriptor's
            own name where the platform can execute one.
        inherited: Descriptors the new process must inherit for
            ``launch_path`` to resolve in it.
        exclusive: Whether the hold alone guarantees the file cannot change
            or be replaced while it lasts.
    """

    path: Path
    handle: BufferedReader
    launch_path: str
    inherited: tuple[int, ...]
    exclusive: bool

    def sha256(self) -> str:
        """Return the hex SHA256 of the held file's whole content."""
        self.handle.seek(0)
        return hashlib.file_digest(self.handle, "sha256").hexdigest()

    def names_held_file(self) -> bool:
        """Whether :attr:`path` still names the file that is held."""
        held = os.fstat(self.handle.fileno())
        try:
            named = os.lstat(self.path)
        except OSError:
            return False
        return (held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)

    def unchanged(self, expected_sha256: str) -> bool:
        """Whether a process just created from this hold ran the verified file.

        Called once the process exists. An exclusive hold answers by
        construction. Otherwise the content is hashed again - a running image
        can no longer be written to, so what is read now is what runs - and a
        process created by path is also required to have been given a path
        that still names the held file.

        Args:
            expected_sha256: The digest the file was verified against.
        """
        if self.exclusive:
            return True
        if not self.inherited and not self.names_held_file():
            return False
        return self.sha256() == expected_sha256


def _open_held(path: Path) -> int:
    """Open *path* itself for reading, denying whatever the platform can."""
    if sys.platform == "win32":
        from .._win32 import open_without_following

        return open_without_following(str(path), share_write=False)
    # Non-blocking so a FIFO at the path cannot hang the open; a regular file
    # is the only thing accepted, and blocking is restored for it below.
    return os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)


@contextmanager
def held_executable(path: Path) -> Generator[HeldExecutable]:
    """Hold the regular file at *path* open for the duration of the block.

    Raises:
        OSError: When the path cannot be opened as itself - it is absent, a
            link, or held by a writer on a platform that can refuse one - or
            names something other than a regular file.
    """
    descriptor = _open_held(path)
    with os.fdopen(descriptor, "rb") as handle:
        status = os.fstat(descriptor)
        # A link opened as itself still reports a regular file on Windows;
        # only its reparse attribute tells it apart.
        is_link = bool(
            getattr(status, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )
        if is_link or not stat.S_ISREG(status.st_mode):
            raise OSError(f"{path} is not a regular file")
        if sys.platform == "win32":
            yield HeldExecutable(path, handle, str(path), (), exclusive=True)
            return
        os.set_blocking(descriptor, True)
        if sys.platform.startswith("linux") and os.path.isdir(_PROC_DESCRIPTORS):
            yield HeldExecutable(
                path,
                handle,
                f"{_PROC_DESCRIPTORS}/{descriptor}",
                (descriptor,),
                exclusive=False,
            )
            return
        yield HeldExecutable(path, handle, str(path), (), exclusive=False)
