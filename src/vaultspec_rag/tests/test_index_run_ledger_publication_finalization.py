"""Run-ledger publication finalization behavior."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from ..indexer._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofEvidence,
    ProofOldEvidenceMismatchError,
    ProofParentMismatchError,
    ProofReceiptState,
)
from ..indexer._run_ledger_models import (
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    RunAuthority,
    RunLedgerStateError,
)
from ..indexer._run_ledger_runtime import RunLedger
from ._run_ledger_test_support import (
    ledger_test_assert_generation_proof_gate,
    ledger_test_digest,
    ledger_test_seal_publication_receipt,
    ledger_test_sealed_modify_receipt,
    ledger_test_seeded_publication_lineage,
    ledger_test_signature,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_generation_finalization_waits_for_the_current_proof_commit(
    tmp_path: Path,
) -> None:
    """Mutation: bypassing the proof fence advances an uncertified generation."""
    (
        ledger,
        key,
        parent_id,
        successor_id,
        receipt,
        _old,
        _new,
        _delta,
        _mutation,
    ) = ledger_test_sealed_modify_receipt(
        tmp_path,
        point_ids=("point-a",),
    )
    ledger.advance_finalization(successor_id, FinalizationPhase.STALE_RECONCILED)

    with pytest.raises(RunLedgerStateError, match=r"proof.*before generation"):
        ledger_test_assert_generation_proof_gate(ledger, successor_id)
    assert ledger.generation(successor_id).finalization_phase is (
        FinalizationPhase.STALE_RECONCILED
    )
    assert ledger.publication_proof(key).generation_id == parent_id
    assert ledger.active_publication_receipt(key) is not None

    committed = ledger.commit_publication_receipt(receipt.receipt_id)
    assert committed.generation_id == successor_id
    assert ledger.active_publication_receipt(key) is None
    ledger_test_assert_generation_proof_gate(ledger, successor_id)


def test_generation_finalization_refuses_a_missing_proof(tmp_path: Path) -> None:
    """Mutation: treating absent canonical proof as a no-op makes this red."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    ledger.advance_finalization(
        generation.generation_id,
        FinalizationPhase.STALE_RECONCILED,
    )

    with pytest.raises(RunLedgerStateError, match="proof must commit"):
        ledger_test_assert_generation_proof_gate(ledger, generation.generation_id)
    assert ledger.generation(generation.generation_id).finalization_phase is (
        FinalizationPhase.STALE_RECONCILED
    )


def test_generation_finalization_refuses_a_parent_owned_proof_without_a_receipt(
    tmp_path: Path,
) -> None:
    """Mutation: accepting parent proof as a silent no-op makes this guard red."""
    ledger, _key, _parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path, ()
    )
    ledger.advance_finalization(successor_id, FinalizationPhase.STALE_RECONCILED)

    with pytest.raises(RunLedgerStateError, match="proof must commit"):
        ledger_test_assert_generation_proof_gate(ledger, successor_id)


def test_generation_finalization_refuses_proof_pair_incompatible_with_generation(
    tmp_path: Path,
) -> None:
    """Mutation: dropping the key comparison makes this guard red.

    The proof is the one a rebuild really committed for this generation. Its
    stored ``policy_identity`` is then damaged on disk - the one state a
    writer cannot produce, because every write derives that column from the
    generation it publishes - so the row is found by stable identity and
    rejected on the full key.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    ledger.advance_finalization(
        generation.generation_id,
        FinalizationPhase.STALE_RECONCILED,
    )
    ledger.establish_verified_publication(
        generation.generation_id, RunAuthority.REBUILD, ()
    )
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute(
            "UPDATE publication_proofs SET policy_identity = 'policy-other'"
        )
        connection.commit()

    with pytest.raises(RunLedgerStateError, match="incompatible with generation"):
        ledger_test_assert_generation_proof_gate(ledger, generation.generation_id)


def test_generation_finalization_refuses_an_open_receipt_even_if_proof_points_at_it(
    tmp_path: Path,
) -> None:
    """Mutation: ignoring open receipt ownership makes this guard red."""
    ledger, key, _parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path, ()
    )
    ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute(
            """
            UPDATE publication_proofs SET generation_id = ?
            WHERE source_type = ? AND root_identity = ?
              AND backend_identity = ? AND collection_identity = ?
            """,
            (
                successor_id,
                key.source_type.value,
                key.root_identity,
                key.backend_identity,
                key.collection_identity,
            ),
        )
        connection.commit()
    ledger.advance_finalization(successor_id, FinalizationPhase.STALE_RECONCILED)

    with pytest.raises(RunLedgerStateError, match="close its receipt"):
        ledger_test_assert_generation_proof_gate(ledger, successor_id)


def _committed_publication(tmp_path: Path) -> tuple[RunLedger, str]:
    """Publish a real delta through the API, leaving its committed receipt.

    Everything the damage tests below start from: a parent generation whose
    rebuild established a verified proof, a successor that reserved, sealed
    and committed one receipt against it, and the delta-derived proof that
    commit installed. Returns the ledger and the successor generation.
    """
    (
        ledger,
        _key,
        _parent_id,
        successor_id,
        receipt,
        *_rest,
    ) = ledger_test_sealed_modify_receipt(tmp_path, point_ids=("point-a",))
    ledger.advance_finalization(successor_id, FinalizationPhase.STALE_RECONCILED)
    ledger.commit_publication_receipt(receipt.receipt_id)
    ledger_test_assert_generation_proof_gate(ledger, successor_id)
    return ledger, successor_id


def test_generation_finalization_refuses_a_noncommitted_latest_receipt(
    tmp_path: Path,
) -> None:
    """Mutation: accepting rolled-back history as proof closure makes this red.

    The committed receipt's state column is damaged on disk; no transition
    moves a committed receipt back to rolled back.
    """
    ledger, successor_id = _committed_publication(tmp_path)
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute(
            """
            UPDATE publication_receipts
            SET state = 'rolled_back', rollback_started_at = sealed_at,
                rolled_back_at = sealed_at, committed_at = NULL
            """
        )
        connection.commit()

    with pytest.raises(RunLedgerStateError, match="receipt must commit"):
        ledger_test_assert_generation_proof_gate(ledger, successor_id)


def test_generation_finalization_requires_receipt_for_delta_derived_proof(
    tmp_path: Path,
) -> None:
    """Mutation: accepting receiptless delta provenance makes this guard red.

    The proof is the delta-derived one its receipt really committed, and the
    receipt row is then lost from the file.
    """
    ledger, successor_id = _committed_publication(tmp_path)
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute("DELETE FROM publication_receipts")
        connection.commit()

    with pytest.raises(RunLedgerStateError, match="requires its committed receipt"):
        ledger_test_assert_generation_proof_gate(ledger, successor_id)


#: One damaged column per equality the finalization gate asserts between a
#: committed receipt and the proof it installed. Each statement runs over the
#: committed publication a real receipt produced.
_MISMATCH_DAMAGE = {
    "state": """
        UPDATE publication_receipts
        SET state = 'rolled_back', rollback_started_at = sealed_at,
            rolled_back_at = sealed_at, committed_at = NULL
    """,
    "compatibility": """
        UPDATE publication_receipts
        SET root_identity = root_identity || '-other'
    """,
    "revision": """
        UPDATE publication_receipts
        SET parent_revision = parent_revision + 1,
            target_revision = target_revision + 1
    """,
    "sequence": """
        UPDATE publication_receipts
        SET reservation_sequence = reservation_sequence + 1
    """,
    "provenance": """
        UPDATE publication_proofs
        SET provenance = 'verified', verified_at = committed_at
    """,
}


@pytest.mark.parametrize("mismatch", tuple(_MISMATCH_DAMAGE))
def test_generation_finalization_refuses_mismatched_committed_receipt(
    tmp_path: Path,
    mismatch: str,
) -> None:
    """Mutation: removing any receipt/proof equality guard makes a case red."""
    ledger, successor_id = _committed_publication(tmp_path)
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute(_MISMATCH_DAMAGE[mismatch])
        connection.commit()

    with pytest.raises(RunLedgerStateError, match="receipt must commit"):
        ledger_test_assert_generation_proof_gate(ledger, successor_id)


def test_late_receipt_transition_failure_rolls_back_the_entire_proof_commit(
    tmp_path: Path,
) -> None:
    """Mutation: committing evidence before the receipt transition makes this red."""
    (
        ledger,
        key,
        _parent_id,
        successor_id,
        receipt,
        old,
        new,
        _delta,
        _mutation,
    ) = ledger_test_sealed_modify_receipt(
        tmp_path,
        point_ids=("point-a-old",),
    )
    ledger.advance_finalization(successor_id, FinalizationPhase.STALE_RECONCILED)

    def durable_projection() -> tuple[tuple[object, ...], ...]:
        with closing(sqlite3.connect(ledger.path)) as connection, connection:
            return tuple(
                tuple(row)
                for table in (
                    "publication_proofs",
                    "publication_evidence",
                    "publication_points",
                    "publication_receipts",
                )
                for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
            )

    before = durable_projection()
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute(
            """
            CREATE TRIGGER reject_receipt_commit
            BEFORE UPDATE OF state ON publication_receipts
            WHEN NEW.state = 'committed'
            BEGIN
                SELECT RAISE(ABORT, 'injected late receipt commit failure');
            END
            """
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="injected late"):
        ledger.commit_publication_receipt(receipt.receipt_id)

    assert durable_projection() == before
    active = ledger.active_publication_receipt(key)
    assert active is not None
    assert active.state is ProofReceiptState.SEALED
    assert ledger.publication_evidence_for_paths(key, (old.rel_path,)) == {
        old.rel_path: old
    }

    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute("DROP TRIGGER reject_receipt_commit")
        connection.commit()
    committed = ledger.commit_publication_receipt(receipt.receipt_id)
    assert committed.revision == receipt.target_revision
    assert ledger.publication_evidence_for_paths(key, (new.rel_path,)) == {
        new.rel_path: new
    }


def test_changed_parent_revision_refuses_proof_commit_without_mutation(
    tmp_path: Path,
) -> None:
    """Mutation: skipping the commit-time parent revision check makes this red."""
    (
        ledger,
        key,
        _parent_id,
        successor_id,
        receipt,
        old,
        _new,
        _delta,
        _mutation,
    ) = ledger_test_sealed_modify_receipt(
        tmp_path,
        point_ids=("point-a-old",),
    )
    ledger.advance_finalization(successor_id, FinalizationPhase.STALE_RECONCILED)
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute("UPDATE publication_proofs SET revision = revision + 1")
        connection.commit()

    def durable_projection() -> tuple[tuple[object, ...], ...]:
        with closing(sqlite3.connect(ledger.path)) as connection, connection:
            return tuple(
                tuple(row)
                for table in (
                    "publication_proofs",
                    "publication_evidence",
                    "publication_points",
                    "publication_receipts",
                )
                for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
            )

    before = durable_projection()
    with pytest.raises(
        ProofParentMismatchError,
        match="publication proof no longer matches the receipt parent",
    ):
        ledger.commit_publication_receipt(receipt.receipt_id)

    assert durable_projection() == before
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        state = connection.execute(
            "SELECT state FROM publication_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()
    assert state == (ProofReceiptState.SEALED.value,)
    assert ledger.publication_evidence_for_paths(key, (old.rel_path,)) == {
        old.rel_path: old
    }


def test_receipt_seal_refuses_stale_parent_or_old_evidence_atomically(
    tmp_path: Path,
) -> None:
    actual = ProofEvidence(
        rel_path="src/a.py",
        content_identity=ledger_test_digest("a-v1"),
        point_ids=("point-a",),
    )
    ledger, key, _parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path,
        (actual,),
    )
    before = ledger.publication_proof(key)
    with pytest.raises(ProofParentMismatchError):
        ledger.reserve_publication_receipt(
            key,
            successor_id,
            expected_parent_revision=before.revision + 1,
        )
    assert ledger.publication_proof(key) == before

    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=before.revision,
    )
    wrong_old = replace(
        actual, content_identity=ledger_test_digest("not-authoritative")
    )
    new = replace(actual, content_identity=ledger_test_digest("a-v2"))
    delta = PathDelta(
        outcome=PathOutcome.MODIFY,
        expected_parent_revision=receipt.parent_revision,
        rel_path=actual.rel_path,
        old=wrong_old,
        new=new,
    )
    mutation = CommitUnit(
        rel_path=new.rel_path,
        kind=CommitUnitKind.UPSERT,
        source_digest=new.content_identity,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=new.point_ids,
    )
    with pytest.raises(ProofOldEvidenceMismatchError):
        ledger_test_seal_publication_receipt(
            ledger,
            receipt,
            mutation=mutation,
            delta=delta,
        )
    after = ledger.publication_proof(key)
    assert after.revision == before.revision
    assert after.reservation_sequence == receipt.reservation_sequence
    assert ledger.publication_evidence_for_paths(key, (actual.rel_path,)) == {
        actual.rel_path: actual
    }
    active = ledger.active_publication_receipt(key)
    assert active is not None
    assert active.state is ProofReceiptState.RESERVED
    assert active.deltas == ()
    assert active.mutations[0].sealed_ordinal is None
