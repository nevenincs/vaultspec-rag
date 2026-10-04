"""Bind source reads to regular files at their admitted root-relative names."""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator
    from io import BufferedReader


class SourceIdentityError(OSError):
    """A source name redirects to an object that was not admitted."""


def source_file_stat(path: Path, root_dir: Path) -> os.stat_result:
    """Reject links below the selected root, including directory junctions."""
    expected = root_dir.resolve() / path.relative_to(root_dir)
    observed = path.lstat()
    if stat.S_ISLNK(observed.st_mode) or path.resolve(strict=True) != expected:
        raise SourceIdentityError(f"non-canonical source: {path}")
    if not stat.S_ISREG(observed.st_mode):
        raise OSError(f"source is not a regular file: {path}")
    return observed


def _open_posix_source(path: Path, root_dir: Path) -> int:
    """Open descendants without following links in any path component."""
    parts = path.relative_to(root_dir).parts
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root_dir.resolve(), directory_flags)
    try:
        for part in parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    finally:
        os.close(directory)


def _windows_opened_path(descriptor: int) -> Path:
    """Identify the opened object rather than resolving its mutable name again."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    final_path = kernel32.GetFinalPathNameByHandleW
    final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    final_path.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = final_path(msvcrt.get_osfhandle(descriptor), buffer, len(buffer), 0)
    if not length:
        raise ctypes.WinError(ctypes.get_last_error())
    if length >= len(buffer):
        raise SourceIdentityError("opened source path exceeds filesystem limit")
    name = buffer.value
    if name.startswith("\\\\?\\UNC\\"):
        name = "\\\\" + name[8:]
    elif name.startswith("\\\\?\\"):
        name = name[4:]
    return Path(name)


@contextmanager
def open_source_file(path: Path, root_dir: Path) -> Generator[BufferedReader]:
    """Validate the opened file before any probe, digest, or chunk read."""
    observed = source_file_stat(path, root_dir)
    expected = root_dir.resolve() / path.relative_to(root_dir)
    descriptor = -1
    try:
        if os.name == "nt":
            descriptor = os.open(path, os.O_RDONLY | os.O_BINARY)
            if _windows_opened_path(descriptor) != expected:
                raise SourceIdentityError(f"non-canonical source: {path}")
        else:
            descriptor = _open_posix_source(path, root_dir)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(observed, opened):
            raise SourceIdentityError(f"source identity changed before read: {path}")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            yield stream
    finally:
        if descriptor >= 0:
            os.close(descriptor)
