"""Whether a project root still exists, and the watched roots found missing.

Roots are frequently short-lived worktrees. When one is deleted, every fact
the service keeps about it - its watcher, its controllers, its searches - must
stop treating it as a project that only needs indexing. This module owns the
one presence check and the service-wide record of watched roots that were
found missing, so the watcher, search, health and operator surfaces all agree.

Only proven absence counts. A root whose stat fails for any reason other than
"not found" (an offline share, a permission change, an unplugged drive) is
unverifiable, not missing, and is never declared stale.
"""

from __future__ import annotations

import os
import stat
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ._root_identity import canonical_root_key

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = [
    "RootMissingError",
    "StaleWatcherRoot",
    "clear_stale_watcher_root",
    "record_stale_watcher_root",
    "root_is_missing",
    "root_missing_message",
    "stale_watcher_roots",
]

#: Upper bound on remembered stale roots. Records are dropped oldest-first
#: beyond it, so a machine churning through worktrees cannot grow the set.
_MAX_STALE_WATCHER_ROOTS: Final = 256


def root_is_missing(root: str | Path) -> bool:
    """Return whether *root* is proven not to exist as a directory.

    The criterion is the root directory itself, never its ``.vault/``: a root
    that never had one is still a valid code root, while a deleted worktree
    loses both at once.
    """
    try:
        info = os.stat(root)
    except (FileNotFoundError, NotADirectoryError):
        return True
    except (OSError, ValueError):
        return False
    return not stat.S_ISDIR(info.st_mode)


def root_missing_message(root: str | Path) -> str:
    """Explain a missing root in the words every surface uses."""
    return (
        f"project root does not exist: {root}. It was deleted or moved, so it "
        "can no longer be indexed or searched; a rebuild cannot restore it."
    )


class RootMissingError(ValueError):
    """A request named a project root that no longer exists."""

    def __init__(self, root: str | Path) -> None:
        self.root = str(root)
        super().__init__(root_missing_message(root))


@dataclass(frozen=True, slots=True)
class StaleWatcherRoot:
    """One watched root whose directory was found missing."""

    root: str
    detected_at: float
    sources: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "detected_at": self.detected_at,
            "sources": list(self.sources),
        }


_lock = threading.Lock()
_stale_roots: dict[str, StaleWatcherRoot] = {}


def record_stale_watcher_root(
    root: str | Path,
    sources: Iterable[str],
    *,
    detected_at: float | None = None,
) -> bool:
    """Record *root* as a missing watched root.

    Returns ``True`` only for the transition into the stale state, so a caller
    reports each root once rather than once per observation. Later
    observations merge their sources into the existing record.
    """
    key = canonical_root_key(root)
    observed = tuple(sorted(set(sources)))
    with _lock:
        existing = _stale_roots.get(key)
        if existing is not None:
            merged = tuple(sorted(set(existing.sources) | set(observed)))
            if merged != existing.sources:
                _stale_roots[key] = StaleWatcherRoot(
                    existing.root, existing.detected_at, merged
                )
            return False
        while len(_stale_roots) >= _MAX_STALE_WATCHER_ROOTS:
            _stale_roots.pop(next(iter(_stale_roots)))
        _stale_roots[key] = StaleWatcherRoot(
            str(root),
            time.time() if detected_at is None else detected_at,
            observed,
        )
        return True


def clear_stale_watcher_root(root: str | Path) -> bool:
    """Forget *root*'s stale record; return whether one existed."""
    key = canonical_root_key(root)
    with _lock:
        return _stale_roots.pop(key, None) is not None


def stale_watcher_roots() -> tuple[StaleWatcherRoot, ...]:
    """Return the watched roots still missing, oldest detection first.

    A root that exists again has recovered, so its record is dropped here
    rather than reported: every reader sees recovery without a separate sweep.
    """
    with _lock:
        records = tuple(_stale_roots.values())
    recovered = [record for record in records if not root_is_missing(record.root)]
    if recovered:
        with _lock:
            for record in recovered:
                key = canonical_root_key(record.root)
                if _stale_roots.get(key) is record:
                    _stale_roots.pop(key)
    return tuple(
        sorted(
            (record for record in records if record not in recovered),
            key=lambda record: (record.detected_at, record.root),
        )
    )
