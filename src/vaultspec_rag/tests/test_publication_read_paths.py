"""Read-only paths treat every unreadable publication proof as absence."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from .._context_scope import bind_context
from .._index_breadth import acquire_code_breadth_snapshot_if_proven
from .._index_integrity import (
    IndexIntegrity,
    acquire_index_integrity_snapshot_if_proven,
)
from .._source_types import PublicSourceType
from .._store_writes import workspace_volume_path
from ..indexer._publication_proof import ProofEvidence
from ..indexer._run_ledger_models import (
    SCHEMA_VERSION,
    RunAuthority,
    index_run_ledger_path,
)
from ..indexer._run_ledger_publication_identity import compatibility_for_signature
from ..indexer._run_ledger_runtime import RunLedger
from ..store_runtime import configured_backend_identity
from ._run_ledger_test_support import (
    ledger_test_digest,
    ledger_test_publish_and_compact,
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
    ledger.establish_verified_publication(
        parent.generation_id,
        RunAuthority.REBUILD,
        (
            ProofEvidence(
                "src/a.py",
                ledger_test_digest("a-v1"),
                ledger_test_unit("src/a.py", 0, 1).point_ids,
            ),
        ),
    )
    ledger_test_publish_and_compact(ledger, parent.generation_id)
    key = compatibility_for_signature(signature)
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


def test_recovery_writer_reads_parent_without_unfencing_other_readers(
    tmp_path: Path,
) -> None:
    """The recovery exception is limited to the exact owning execution context.

    Mutation: bypassing the ordinary open-receipt fence failed the concurrent
    reader assertion with DID NOT RAISE; restoring the fence passed.
    """
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace

    from .._publication_state import (
        acquire_publication_snapshot,
        publication_recovery_receipt,
    )
    from ..indexer._publication_proof import ProofReadConflictError
    from ..indexer._run_ledger_models import RunOperation
    from ._publication_assertions import publish_empty_vault_proof

    publish_empty_vault_proof(tmp_path)
    parent = acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT)
    ledger = parent.ledger
    generation = ledger.start_generation(
        replace(
            ledger.generation(parent.proof.generation_id).signature,
            clean=False,
            operation=RunOperation.SCOPED_INCREMENTAL,
        )
    )
    receipt = ledger.reserve_publication_receipt(
        parent.proof.compatibility_key,
        generation.generation_id,
        expected_parent_revision=parent.proof.revision,
    )
    with bind_context(publication_recovery_receipt, receipt):
        snapshot = acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT)
        snapshot.validate()
        assert snapshot.proof.generation_id == parent.proof.generation_id
        # A failing nested binding must restore the owning recovery receipt.
        # Omitting bind_context's reset failed the receipt equality below;
        # restoring it passed and read the canonical parent again.
        foreign = replace(receipt, receipt_id="nested-foreign-owner")
        with (
            pytest.raises(ProofReadConflictError, match="does not own"),
            bind_context(publication_recovery_receipt, foreign),
        ):
            acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT)
        assert publication_recovery_receipt.get() == receipt
        acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT).validate()
        with ThreadPoolExecutor(max_workers=1) as pool:
            reader = pool.submit(
                acquire_publication_snapshot, tmp_path, PublicSourceType.VAULT
            )
            with pytest.raises(ProofReadConflictError, match="open receipt"):
                reader.result()
        ledger.begin_publication_rollback(receipt.receipt_id)
        with pytest.raises(ProofReadConflictError, match="does not own"):
            snapshot.validate()
    with pytest.raises(ProofReadConflictError, match="open receipt"):
        acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT)


@pytest.mark.parametrize("field", ["receipt_id", "generation_id"])
def test_recovery_read_rejects_another_receipt_owner(
    tmp_path: Path, field: str
) -> None:
    """A caller cannot borrow another generation's read exemption.

    Mutation: removing each receipt/generation identity comparison failed its
    corresponding DID NOT RAISE assertion; each restored guard passed.
    """
    from dataclasses import replace

    from .._publication_state import (
        acquire_publication_snapshot,
        publication_recovery_receipt,
    )
    from ..indexer._publication_proof import ProofReadConflictError
    from ..indexer._run_ledger_models import RunOperation
    from ._publication_assertions import publish_empty_vault_proof

    publish_empty_vault_proof(tmp_path)
    parent = acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT)
    ledger = parent.ledger
    generation = ledger.start_generation(
        replace(
            ledger.generation(parent.proof.generation_id).signature,
            clean=False,
            operation=RunOperation.SCOPED_INCREMENTAL,
        )
    )
    receipt = ledger.reserve_publication_receipt(
        parent.proof.compatibility_key,
        generation.generation_id,
        expected_parent_revision=parent.proof.revision,
    )
    foreign = replace(receipt, **{field: "another-owner"})
    with (
        bind_context(publication_recovery_receipt, foreign),
        pytest.raises(ProofReadConflictError, match="does not own"),
    ):
        acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT)
