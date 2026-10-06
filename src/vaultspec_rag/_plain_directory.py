"""Reaching a directory beneath a root without following a link out of it.

A path built by joining names onto a root is inside that root only if none of
the directories on the way is a link. Checking the last component proves
nothing about the ones before it: an ordinary file reached through a linked
parent lives wherever the link points. Every component is therefore opened
itself - never what a link at its name designates - and proven a real
directory before the next is looked up beneath it.

The directory stays held for as long as the caller works in it, so a check
cannot go stale between being made and being relied on. Where the platform
resolves names against an open directory, entries are reached through that
descriptor and a later swap of any ancestor cannot redirect them. Windows has
no such lookup, so there every component is held open without delete sharing,
which refuses any rename or replacement of it until it is released.
"""

from __future__ import annotations

import os
import stat
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ._rmtree import remove_tree

if TYPE_CHECKING:
    from collections.abc import Generator

__all__ = [
    "LinkedDirectoryError",
    "PlainDirectory",
    "ensure_plain_directory",
    "link_kind",
    "open_plain_directory",
    "require_plain_parents",
]

#: Whether an entry can be named relative to an open directory descriptor.
_DESCRIPTOR_RELATIVE = os.open in os.supports_dir_fd


class LinkedDirectoryError(OSError):
    """A directory beneath the root is a link, or is not a directory at all."""


def link_kind(metadata: os.stat_result) -> str | None:
    """Name the link a no-follow stat describes, or ``None`` for any other node."""
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    # A junction reports as a directory; only its reparse tag gives it away.
    if (
        sys.platform == "win32"
        and metadata.st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
    ):
        return "junction"
    return None


def _is_plain(metadata: os.stat_result) -> bool:
    return stat.S_ISDIR(metadata.st_mode) and link_kind(metadata) is None


def _refusal(shown: Path, observed: os.stat_result) -> str:
    kind = link_kind(observed)
    if kind is not None:
        found = f"is a {kind}, not a real directory"
    elif stat.S_ISDIR(observed.st_mode):
        found = "changed while it was being opened"
    else:
        found = "is not a directory"
    return f"unsafe directory topology: {shown} {found}"


@dataclass(frozen=True)
class PlainDirectory:
    """A proven real directory, held so its entries are reached through it."""

    path: Path
    descriptor: int | None

    def _entry(self, name: str) -> str | Path:
        return name if self.descriptor is not None else self.path / name

    def lstat(self, name: str) -> os.stat_result | None:
        """Describe the entry *name* itself, or ``None`` when there is none."""
        try:
            return os.stat(
                self._entry(name), dir_fd=self.descriptor, follow_symlinks=False
            )
        except FileNotFoundError:
            return None

    def unlink(self, name: str) -> None:
        """Remove the file entry *name*; a link is removed, never followed."""
        os.unlink(self._entry(name), dir_fd=self.descriptor)

    def remove_tree(self, name: str) -> None:
        """Remove the directory entry *name* and everything beneath it."""
        remove_tree(self._entry(name), dir_fd=self.descriptor)


def _open_itself(
    location: str | Path, parent: int | None, *, follow: bool = False
) -> int:
    """Open and hold one directory node, a link as the link unless *follow*."""
    if sys.platform == "win32":
        from ._win32 import open_without_following

        return open_without_following(os.fspath(location), directory=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if not follow:
        flags |= os.O_NOFOLLOW
    return os.open(location, flags, dir_fd=parent)


def _hold_plain(location: str | Path, parent: int | None, shown: Path) -> int:
    """Open one component itself and prove it is a real directory."""
    try:
        descriptor = _open_itself(location, parent)
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        # A no-follow open refuses a link outright where the platform has
        # one, so say which kind of node was refused. A real directory that
        # still could not be opened is a different failure, reported as itself.
        observed = os.stat(location, dir_fd=parent, follow_symlinks=False)
        if _is_plain(observed):
            raise
        raise LinkedDirectoryError(_refusal(shown, observed)) from None
    try:
        observed = os.stat(location, dir_fd=parent, follow_symlinks=False)
        if not _is_plain(observed) or not os.path.samestat(
            observed, os.fstat(descriptor)
        ):
            raise LinkedDirectoryError(_refusal(shown, observed))
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _descend(
    root: Path, parts: tuple[str, ...], held: list[int], *, create: bool
) -> PlainDirectory | None:
    try:
        # The root is the caller's chosen anchor; only what lies beneath it is
        # required to be link-free.
        held.append(_open_itself(root, None, follow=True))
    except FileNotFoundError:
        if create:
            raise
        return None
    current = root
    for part in parts:
        parent = held[-1] if _DESCRIPTOR_RELATIVE else None
        current /= part
        location = part if parent is not None else current
        try:
            held.append(_hold_plain(location, parent, current))
        except FileNotFoundError:
            if not create:
                return None
            os.mkdir(location, dir_fd=parent)
            held.append(_hold_plain(location, parent, current))
    return PlainDirectory(current, held[-1] if _DESCRIPTOR_RELATIVE else None)


@contextmanager
def open_plain_directory(
    root: Path, relative: Path, *, create: bool = False
) -> Generator[PlainDirectory | None]:
    """Hold ``root / relative`` with every component beneath *root* proven real.

    Yields ``None`` when a component does not exist and *create* is false:
    nothing beneath an absent directory can be reached, so there is nothing
    to refuse. With *create*, missing components are made, and each is opened
    the same way before the next is made beneath it.

    Raises:
        LinkedDirectoryError: A component is a symlink, a junction, or not a
            directory.
        ValueError: *relative* is not a path beneath *root*.
    """
    if relative.anchor or ".." in relative.parts:
        raise ValueError(f"not a path beneath {root}: {relative}")
    held: list[int] = []
    try:
        yield _descend(root, relative.parts, held, create=create)
    finally:
        for descriptor in reversed(held):
            os.close(descriptor)


def require_plain_parents(root: Path, path: Path) -> None:
    """Refuse *path* unless every existing directory above it is a real one.

    Only the directories between *root* and *path* are examined; what may sit
    at *path* itself is the caller's question.

    Raises:
        LinkedDirectoryError: A directory on the way is a link or not a
            directory.
    """
    with open_plain_directory(root, Path(os.path.relpath(path, root)).parent):
        pass


def ensure_plain_directory(root: Path, relative: Path) -> None:
    """Create ``root / relative`` as real directories, refusing any link.

    Raises:
        LinkedDirectoryError: An existing component is a link or not a
            directory.
    """
    with open_plain_directory(root, relative, create=True):
        pass
