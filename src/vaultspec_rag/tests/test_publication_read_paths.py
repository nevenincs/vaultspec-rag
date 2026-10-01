"""Read-only paths treat every unreadable publication proof as absence."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from .._index_breadth import acquire_code_breadth_snapshot_if_proven
from .._index_integrity import (
    IndexIntegrity,
    acquire_index_integrity_snapshot_if_proven,
)
from .._source_types import PublicSourceType
from .._store_writes import workspace_volume_path
from ..indexer._publication_proof import ProofEvidence
from ..indexer._run_ledger_models import SCHEMA_VERSION, index_run_ledger_path
from ..indexer._run_ledger_runtime import RunLedger
from ..store_runtime import configured_backend_identity
from ._run_ledger_test_support import (
    ledger_test_digest,
    ledger_test_proof_key_for_signature,
    ledger_test_publish_and_compact,
    ledger_test_seed_publication_proof,
    ledger_test_signature,
    ledger_test_unit,
)
from ._sqlite_state import assert_sqlite_unchanged, sqlite_contents

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _old_schema_ledger(root: Path) -> Path:
    """Write the ledger an older build left behind: tables at a prior version."""
    path = index_run_ledger_path(workspace_volume_path(root.resolve()))
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE old_runs (value TEXT NOT NULL)")
        connection.execute("INSERT INTO old_runs VALUES ('preserve-me')")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 3}")
    return path


def test_an_old_ledger_leaves_a_search_unfenced_rather_than_failing(
    tmp_path: Path,
) -> None:
    # A root indexed by an older build keeps a ledger this build refuses to
    # open. The serving path read that refusal as an internal server error on
    # every search, so no project indexed before the schema moved could be
    # searched at all. Mutation: narrowing either helper back to the proof
    # errors alone raises the ledger's rebuild refusal here instead.
    ledger = _old_schema_ledger(tmp_path)
    before = sqlite_contents(ledger)

    observation = acquire_index_integrity_snapshot_if_proven(
        tmp_path, PublicSourceType.VAULT
    )
    assert isinstance(observation, IndexIntegrity)
    assert observation.reason == "proof_unreadable"
    assert acquire_code_breadth_snapshot_if_proven(tmp_path) is None
    assert_sqlite_unchanged(ledger, before)


def _root_mid_publication(root: Path) -> None:
    """Commit a code proof at *root*, then hold a receipt open as a run does."""
    path = index_run_ledger_path(workspace_volume_path(root))
    path.parent.mkdir(parents=True)
    ledger = RunLedger(path)
    signature = ledger_test_signature(
        root, backend_identity=configured_backend_identity(root)
    )
    parent = ledger.start_generation(signature)
    key = ledger_test_proof_key_for_signature(signature)
    ledger_test_seed_publication_proof(
        ledger,
        generation_id=parent.generation_id,
        key=key,
        evidence=(
            ProofEvidence(
                "src/a.py",
                ledger_test_digest("a-v1"),
                ledger_test_unit("src/a.py", 0, 1).point_ids,
            ),
        ),
    )
    ledger_test_publish_and_compact(ledger, parent.generation_id)
    successor = ledger.start_generation(signature)
    ledger.reserve_publication_receipt(
        key,
        successor.generation_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )


def test_an_update_publishing_leaves_a_search_unfenced_rather_than_failing(
    tmp_path: Path,
) -> None:
    # An index run holds its publication receipt open while it publishes, and
    # certifying proof under an open receipt raises a read conflict. Unhandled,
    # every search issued during an automatic update failed. Mutation: leaving
    # the read conflict out of the unreadable set raises it here.
    root = tmp_path.resolve()
    _root_mid_publication(root)

    observation = acquire_index_integrity_snapshot_if_proven(
        root, PublicSourceType.CODE
    )
    assert isinstance(observation, IndexIntegrity)
    assert observation.reason == "proof_unreadable"
    assert acquire_code_breadth_snapshot_if_proven(root) is None
