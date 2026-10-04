"""Canonical filesystem identity for root-keyed service facts."""

from __future__ import annotations

import os
from pathlib import Path


def canonical_root_path(root: str | Path) -> Path:
    """Validate and resolve a root while retaining its display spelling."""
    if "\0" in os.fspath(root):
        raise ValueError("root must not contain NUL characters")
    return Path(root).resolve()


def canonical_root_key(root: str | Path) -> str:
    """Resolve a root and normalize the platform's equivalent path spellings."""
    return os.path.normcase(str(canonical_root_path(root)))
