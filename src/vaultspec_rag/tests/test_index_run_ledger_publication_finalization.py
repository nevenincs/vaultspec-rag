"""Run-ledger publication finalization behavior."""

from __future__ import annotations

import sqlite3
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
    RunLedgerStateError,
)
from ..indexer._run_ledger_runtime import RunLedger
from ._run_ledger_test_support import (
    ledger_test_assert_generation_proof_gate,
    ledger_test_digest,
    ledger_test_insert_reserved_receipt,
    ledger_test_proof_key_for_signature,
    ledger_test_seal_publication_receipt,
    ledger_test_sealed_modify_receipt,
    ledger_test_seed_publication_proof,
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
    """Mutation: trusting proof/receipt agreement alone makes this guard red."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    ledger.advance_finalization(
        generation.generation_id,
        FinalizationPhase.STALE_RECONCILED,
    )
    key = replace(
        ledger_test_proof_key_for_signature(generation.signature),
        policy_identity="policy-other",
    )
    ledger_test_seed_publication_proof(
        ledger,
        generation_id=generation.generation_id,
        key=key,
        evidence=(),
    )
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            """
            UPDATE publication_proofs
            SET provenance = 'delta_derived', verified_at = NULL
            WHERE generation_id = ?
            """,
            (generation.generation_id,),
        )
        ledger_test_insert_reserved_receipt(
            connection,
            receipt_id="incompatible-generation",
            reservation_sequence=5,
            generation_id=generation.generation_id,
            projection=(key, 1),
        )
        connection.execute(
            """
            UPDATE publication_receipts
            SET parent_revision = 2, target_revision = 3,
                state = 'committed', sealed_at = 2.0, committed_at = 3.0
            WHERE receipt_id = 'incompatible-generation'
            """
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
        expected_parent_revision=3,
    )
    with sqlite3.connect(ledger.path) as connection:
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


def test_generation_finalization_refuses_a_noncommitted_latest_receipt(
    tmp_path: Path,
) -> None:
    """Mutation: accepting rolled-back history as proof closure makes this red."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    ledger.advance_finalization(
        generation.generation_id,
        FinalizationPhase.STALE_RECONCILED,
    )
    key = ledger_test_proof_key_for_signature(generation.signature)
    ledger_test_seed_publication_proof(
        ledger,
        generation_id=generation.generation_id,
        key=key,
        evidence=(),
    )
    with sqlite3.connect(ledger.path) as connection:
        ledger_test_insert_reserved_receipt(
            connection,
            receipt_id="rolled-back-latest",
            reservation_sequence=6,
            generation_id=generation.generation_id,
            projection=(key, 1),
        )
        connection.execute(
            """
            UPDATE publication_receipts
            SET state = 'rolled_back', rollback_started_at = 2.0,
                rolled_back_at = 3.0
            WHERE receipt_id = 'rolled-back-latest'
            """
        )
        connection.commit()

    with pytest.raises(RunLedgerStateError, match="receipt must commit"):
        ledger_test_assert_generation_proof_gate(ledger, generation.generation_id)


def test_generation_finalization_requires_receipt_for_delta_derived_proof(
    tmp_path: Path,
) -> None:
    """Mutation: accepting receiptless delta provenance makes this guard red."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    ledger.advance_finalization(
        generation.generation_id,
        FinalizationPhase.STALE_RECONCILED,
    )
    ledger_test_seed_publication_proof(
        ledger,
        generation_id=generation.generation_id,
        key=ledger_test_proof_key_for_signature(generation.signature),
        evidence=(),
    )
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            """
            UPDATE publication_proofs
            SET provenance = 'delta_derived', verified_at = NULL
            WHERE generation_id = ?
            """,
            (generation.generation_id,),
        )
        connection.commit()

    with pytest.raises(RunLedgerStateError, match="requires its committed receipt"):
        ledger_test_assert_generation_proof_gate(ledger, generation.generation_id)


@pytest.mark.parametrize(
    "mismatch",
    ("state", "compatibility", "revision", "sequence", "provenance"),
)
def test_generation_finalization_refuses_mismatched_committed_receipt(
    tmp_path: Path,
    mismatch: str,
) -> None:
    """Mutation: removing any receipt/proof equality guard makes a case red."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    ledger.advance_finalization(
        generation.generation_id,
        FinalizationPhase.STALE_RECONCILED,
    )
    key = ledger_test_proof_key_for_signature(generation.signature)
    ledger_test_seed_publication_proof(
        ledger,
        generation_id=generation.generation_id,
        key=key,
        evidence=(),
    )
    receipt_key = (
        replace(key, root_identity=f"{key.root_identity}-other")
        if mismatch == "compatibility"
        else key
    )
    target_revision = 4 if mismatch == "revision" else 3
    reservation_sequence = 6 if mismatch == "sequence" else 5
    with sqlite3.connect(ledger.path) as connection:
        if mismatch != "provenance":
            connection.execute(
                """
                UPDATE publication_proofs
                SET provenance = 'delta_derived', verified_at = NULL
                WHERE generation_id = ?
                """,
                (generation.generation_id,),
            )
        ledger_test_insert_reserved_receipt(
            connection,
            receipt_id=f"mismatch-{mismatch}",
            reservation_sequence=reservation_sequence,
            generation_id=generation.generation_id,
            projection=(receipt_key, 1),
        )
        connection.execute(
            """
            UPDATE publication_receipts
            SET parent_revision = ?, target_revision = ?
            WHERE receipt_id = ?
            """,
            (
                target_revision - 1,
                target_revision,
                f"mismatch-{mismatch}",
            ),
        )
        if mismatch == "state":
            connection.execute(
                """
                UPDATE publication_receipts
                SET state = 'rolled_back', rollback_started_at = 2.0,
                    rolled_back_at = 3.0
                WHERE receipt_id = ?
                """,
                (f"mismatch-{mismatch}",),
            )
        else:
            connection.execute(
                """
                UPDATE publication_receipts
                SET state = 'committed', sealed_at = 2.0, committed_at = 3.0
                WHERE receipt_id = ?
                """,
                (f"mismatch-{mismatch}",),
            )
        connection.commit()

    with pytest.raises(RunLedgerStateError, match="receipt must commit"):
        ledger_test_assert_generation_proof_gate(ledger, generation.generation_id)


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
        with sqlite3.connect(ledger.path) as connection:
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
    with sqlite3.connect(ledger.path) as connection:
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

    with sqlite3.connect(ledger.path) as connection:
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
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("UPDATE publication_proofs SET revision = revision + 1")
        connection.commit()

    def durable_projection() -> tuple[tuple[object, ...], ...]:
        with sqlite3.connect(ledger.path) as connection:
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
    with sqlite3.connect(ledger.path) as connection:
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
