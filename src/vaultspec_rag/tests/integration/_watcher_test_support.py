"""Small shared publication helpers for watcher integration tests."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ...progress import NullProgressReporter
from ...watcher_retry import WatcherPathEvent, WatcherPathObservation, WatcherSource

if TYPE_CHECKING:
    from pathlib import Path

    from ...service import ServiceRegistry


def pending_code_observation(relative_path: str) -> WatcherPathObservation:
    """Build one exact modified-path observation on the wall clock."""
    observed_at = time.time()
    return WatcherPathObservation(
        relative_path=relative_path,
        source=WatcherSource.CODE,
        first_observed_at=observed_at,
        latest_observed_at=observed_at,
        event_kinds=frozenset({WatcherPathEvent.MODIFIED}),
        generation=1,
    )


def seed_vault_publication(registry: ServiceRegistry, root: Path) -> None:
    """Publish an explicit empty Vault baseline before scoped watcher work."""
    with registry.compute_lease(root) as lease:
        lease.runtime.vault_indexer.full_index(reporter=NullProgressReporter())
