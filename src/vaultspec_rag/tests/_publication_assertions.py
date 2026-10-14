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


def publish_empty_vault_proof(root: Path) -> None:
    """Complete one real empty vault publication for *root*.

    The cheapest way to give a root a completed publication: a real
    generation, opened and published through production checkpoint code,
    whose corpus happens to be empty. Tests needing a root that is not
    awaiting its first build take it from here.
    """
    from ..indexer._run_ledger_models import RunAuthority, RunOperation
    from ..indexer._vault_checkpoint import VaultRunCheckpoint
    from ..job_control import NO_RUN_CONTROL
    from ..store_runtime import configured_backend_identity

    root.mkdir(parents=True, exist_ok=True)
    checkpoint = VaultRunCheckpoint.open(
        root,
        backend_identity=configured_backend_identity(root),
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )
    checkpoint.publish_proof_transition()
    checkpoint.publish_generation()


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
