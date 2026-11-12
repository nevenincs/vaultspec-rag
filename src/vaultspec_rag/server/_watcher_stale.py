"""Reporting and pruning of watched roots whose directory was deleted.

A missing root is warned about once per transition into it and recorded until
it is pruned or returns. Pruning releases watcher ownership only: storage,
retry history and indexes are never touched, so a root that comes back resumes
from them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import vaultspec_rag.server as _m

from .._operator_commands import server_updates_prune_command
from .._root_identity import canonical_root_key
from .._root_presence import (
    clear_stale_watcher_root,
    record_stale_watcher_root,
    root_is_missing,
    root_missing_message,
    stale_watcher_roots,
)
from ..logging_config import log_event

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = [
    "StaleWatcherCandidate",
    "missing_root_remediation",
    "missing_roots",
    "prune_stale_watchers",
    "report_missing_watcher_root",
    "stale_watcher_candidates",
]

logger = logging.getLogger("vaultspec_rag.server")


def missing_root_remediation() -> str:
    return (
        "The watched root was deleted or moved. Run "
        f"`{server_updates_prune_command()}` to drop it, or recreate the root "
        "and request it again."
    )


def report_missing_watcher_root(root: str | Path, sources: tuple[str, ...]) -> None:
    """Record a missing watched root, warning once per transition into it."""
    if record_stale_watcher_root(root, sources):
        log_event(
            logger,
            "service.watcher",
            "root_missing",
            severity=logging.WARNING,
            root=root,
            sources=",".join(sorted(set(sources))) or None,
            reason=root_missing_message(root),
            remediation=missing_root_remediation(),
        )


def missing_roots(roots: set[str]) -> tuple[str, ...]:
    """Return the canonical roots proven absent, in stable order."""
    return tuple(sorted(root for root in roots if root_is_missing(root)))


@dataclass(frozen=True, slots=True)
class StaleWatcherCandidate:
    """One missing watched root and the watcher generations still owning it."""

    root: str
    detected_at: float | None
    sources: tuple[str, ...]
    owners: tuple[Path, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "detected_at": self.detected_at,
            "sources": list(self.sources),
            "watcher_running": bool(self.owners),
        }


def stale_watcher_candidates(
    owned_roots: Iterable[Path],
) -> tuple[StaleWatcherCandidate, ...]:
    """Return every watched root proven missing, recorded or still owned.

    Reads the filesystem, so call it off the event loop.
    """
    records = {
        canonical_root_key(record.root): record for record in stale_watcher_roots()
    }
    owners: dict[str, list[Path]] = {}
    for owned in owned_roots:
        if root_is_missing(owned):
            owners.setdefault(canonical_root_key(owned), []).append(owned)
    candidates: list[StaleWatcherCandidate] = []
    for key in sorted(records.keys() | owners.keys()):
        record = records.get(key)
        owned_paths = tuple(sorted(owners.get(key, ())))
        candidates.append(
            StaleWatcherCandidate(
                root=record.root if record is not None else str(owned_paths[0]),
                detected_at=record.detected_at if record is not None else None,
                sources=record.sources if record is not None else (),
                owners=owned_paths,
            )
        )
    return tuple(candidates)


def prune_stale_watchers(candidates: tuple[StaleWatcherCandidate, ...]) -> None:
    """Stop every watcher of a missing root and forget its stale record."""
    for candidate in candidates:
        for owner in candidate.owners:
            _m._stop_watcher(owner)
        clear_stale_watcher_root(candidate.root)
