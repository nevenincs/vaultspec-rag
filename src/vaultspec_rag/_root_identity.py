"""Canonical filesystem identity for root-keyed service facts."""

from __future__ import annotations

import os
from pathlib import Path


def canonical_root_key(root: str | Path) -> str:
    """Resolve a root and normalize the platform's equivalent path spellings."""
    if "\0" in os.fspath(root):
        raise ValueError("root must not contain NUL characters")
    return os.path.normcase(str(Path(root).resolve()))
