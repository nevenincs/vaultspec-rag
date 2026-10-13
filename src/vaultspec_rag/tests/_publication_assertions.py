"""Assertions over canonical publication evidence used by integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .._publication_state import (
    acquire_publication_snapshot,
    read_all_publication_evidence,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .._source_types import PublicSourceType


def published_content_identities(
    root: Path,
    source: PublicSourceType,
) -> dict[str, str]:
    """Return exact path-to-content identities from committed authority."""
    snapshot = acquire_publication_snapshot(root, source)
    return {
        path: evidence.content_identity
        for path, evidence in read_all_publication_evidence(snapshot).items()
    }


def published_retained_points(root: Path, source: PublicSourceType) -> int:
    """Return the point total committed authority says storage retains."""
    return acquire_publication_snapshot(root, source).proof.aggregate.retained_points
