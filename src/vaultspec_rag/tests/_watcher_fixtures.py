"""Watcher observations and state seeds for tests."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ..watcher_retry import locked_state, wall_time

if TYPE_CHECKING:
    from pathlib import Path

    from ..watcher_retry import WatcherRetryState
    from ..watcher_retry_policy import WatcherRetryPolicy
    from ..watcher_runtime import WatcherConvergenceSlot


def dirty_paths(slot: WatcherConvergenceSlot) -> frozenset[Path]:
    """Snapshot the exact paths eligible for the next watcher attempt."""
    with slot.lock:
        return frozenset(slot.held_paths | slot.pending_paths)


def mark_convergence_pending(
    policy: WatcherRetryPolicy, *, now: float | None = None
) -> WatcherRetryState:
    """Persist a new unscoped convergence generation.

    Production always marks a scope. A test staging a pending generation with
    no paths behind it writes the same state through the policy's own commit.
    """
    timestamp = wall_time(now)
    with locked_state(policy._path):
        state = policy._refresh_scope_unlocked()
        committed = policy._commit_unlocked(
            replace(
                state,
                convergence_pending=True,
                convergence_generation=state.convergence_generation + 1,
                updated_at=timestamp,
            )
        )
        policy._scoped_generation = committed.convergence_generation
        return committed
