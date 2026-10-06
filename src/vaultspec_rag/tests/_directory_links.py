"""Planting a directory link, and reading a tree without walking through one.

Shared by the suites that prove a link beneath a root is refused rather than
followed. A junction needs no privilege on Windows and is not a symlink to any
``is_symlink`` check, so every such suite runs both shapes there.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The directory-link shapes this platform can create.
LINK_KINDS = ("symlink", "junction") if os.name == "nt" else ("symlink",)


def link_directory(path: Path, target: Path, kind: str) -> None:
    """Make *path* a *kind* link to the directory *target*."""
    if kind == "symlink":
        path.symlink_to(target, target_is_directory=True)
        return
    from .integration._install_helpers import create_windows_junction

    create_windows_junction(path, target)


def tree_bytes(top: Path) -> dict[str, bytes | None]:
    """Every node beneath *top*: a file's bytes, ``None`` for anything else.

    Links are recorded and never descended, so a tree that contains one is
    compared as itself and what the link reaches is compared separately.
    """
    found: dict[str, bytes | None] = {}
    for current, directories, files in os.walk(top, followlinks=False):
        base = Path(current)
        for name in directories:
            found[(base / name).relative_to(top).as_posix()] = None
        for name in files:
            node = base / name
            found[node.relative_to(top).as_posix()] = (
                None if node.is_symlink() else node.read_bytes()
            )
    return found
