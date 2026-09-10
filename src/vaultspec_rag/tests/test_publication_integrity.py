"""Canonical publication proof consumers share one fenced authority."""

from pathlib import Path

import pytest

from .._index_integrity import (
    VERDICT_CONSISTENT,
    VERDICT_SHRUNKEN,
    acquire_index_integrity_snapshot,
)
from .._source_types import PublicSourceType
from ..indexer._publication_proof import ProofReadConflictError
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

    assert snapshot.finish(0).verdict == VERDICT_CONSISTENT
    assert snapshot.finish(-1).verdict == VERDICT_SHRUNKEN


def test_integrity_token_rejects_publication_started_during_backend_work(
    tmp_path: Path,
) -> None:
    _published_empty_vault(tmp_path)
    snapshot = acquire_index_integrity_snapshot(tmp_path, PublicSourceType.VAULT)
    VaultRunCheckpoint.open(
        tmp_path,
        backend_identity=configured_backend_identity(tmp_path),
        authority=RunAuthority.PUBLICATION,
        operation=RunOperation.SCOPED_INCREMENTAL,
        run_control=NO_RUN_CONTROL,
    )

    with pytest.raises(ProofReadConflictError):
        snapshot.finish(0)
