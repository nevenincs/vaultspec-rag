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


def canonical_root_key_or_none(value: object) -> str | None:
    """Return the canonical key of a recorded root, or ``None`` when it has none.

    Recorded roots come from job specs and request payloads, so a value may be
    absent, blank, not a path, or unresolvable. A reader comparing roots must
    still answer for such a record, so it gets no key rather than an error.
    """
    if not isinstance(value, (str, Path)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return canonical_root_key(Path(value).expanduser())
    except (OSError, RuntimeError, ValueError):
        return None
