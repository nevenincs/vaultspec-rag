"""Watcher observations for tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from ..watcher_runtime import WatcherConvergenceSlot


def dirty_paths(slot: WatcherConvergenceSlot) -> frozenset[Path]:
    """Snapshot the exact paths eligible for the next watcher attempt."""
    with slot.lock:
        return frozenset(slot.held_paths | slot.pending_paths)
