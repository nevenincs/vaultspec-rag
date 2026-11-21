"""Canonical publication proof consumers share one fenced authority."""

from pathlib import Path

import pytest

from .._index_breadth import CodeBreadthSnapshot
from .._index_integrity import (
    IntegrityReason,
    IntegrityVerdict,
    acquire_index_integrity_snapshot,
)
from .._publication_state import acquire_publication_snapshot
from .._source_types import PublicSourceType
from ..indexer._run_ledger_models import RunAuthority, RunOperation
from ..indexer._vault_checkpoint import VaultRunCheckpoint
from ..job_control import NO_RUN_CONTROL
from ..store_runtime import configured_backend_identity

pytestmark = pytest.mark.unit


def _published_empty_vault(root: Path) -> VaultRunCheckpoint:
    checkpoint = VaultRunCheckpoint.open(
        root,
        backend_identity=configured_backend_identity(root),
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )
    assert checkpoint.publish_proof_transition() == 0
    checkpoint.publish_generation()
    return checkpoint


def test_integrity_classifies_a_stable_canonical_proof(tmp_path: Path) -> None:
    _published_empty_vault(tmp_path)
    snapshot = acquire_index_integrity_snapshot(tmp_path, PublicSourceType.VAULT)

    assert snapshot.finish(0).verdict == IntegrityVerdict.CONSISTENT
    assert snapshot.finish(-1).verdict == IntegrityVerdict.SHRUNKEN


def _start_publication(root: Path) -> None:
    """Open a publishing run, as an automatic update does mid-search."""
    VaultRunCheckpoint.open(
        root,
        backend_identity=configured_backend_identity(root),
        authority=RunAuthority.PUBLICATION,
        operation=RunOperation.SCOPED_INCREMENTAL,
        run_control=NO_RUN_CONTROL,
    )


def test_integrity_is_unverifiable_when_publication_starts_during_backend_work(
    tmp_path: Path,
) -> None:
    _published_empty_vault(tmp_path)
    snapshot = acquire_index_integrity_snapshot(tmp_path, PublicSourceType.VAULT)
    _start_publication(tmp_path)

    # Mutation: validating the token without tolerating a moved proof raises
    # the read conflict here, which a served search answered as a 500.
    integrity = snapshot.finish(0)
    assert integrity.verdict == IntegrityVerdict.UNVERIFIABLE
    assert integrity.reason == IntegrityReason.PROOF_UNREADABLE


def test_breadth_demonstrates_no_shortfall_when_publication_starts_during_a_count(
    tmp_path: Path,
) -> None:
    _published_empty_vault(tmp_path)
    breadth = CodeBreadthSnapshot(
        published=1,
        publication=acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT),
    )
    _start_publication(tmp_path)

    # Mutation: validating the token without tolerating a moved proof raises
    # the read conflict here; a stable proof would report a shortfall of one.
    assert breadth.finish(0) is None
