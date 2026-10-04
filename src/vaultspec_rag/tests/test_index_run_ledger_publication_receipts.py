"""Run-ledger publication receipts behavior."""

from __future__ import annotations

import inspect
import sqlite3
from contextlib import closing
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from ..indexer._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofAggregate,
    ProofEvidence,
    ProofMutationState,
    ProofOldEvidenceMismatchError,
    ProofProvenance,
    ProofReadConflictError,
    ProofReceiptState,
)
from ..indexer._run_ledger_commits import RunLedgerCommitMethods
from ..indexer._run_ledger_models import (
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    PublicationMutationUnit,
    PublicationReceipt,
    RunLedgerStateError,
    RunTerminalState,
)
from ..indexer._run_ledger_runtime import RunLedger
from ._ledger_fixtures import acquire_publication_read_token
from ._run_ledger_test_support import (
    ledger_test_digest,
    ledger_test_proof_compatibility,
    ledger_test_sealed_modify_receipt,
    ledger_test_seeded_publication_lineage,
    ledger_test_unit,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_receipt_reserves_streaming_work_then_seals_complete_deltas() -> None:
    """Mutation proving this can fail: omit sealed coverage or close at seal."""
    prepared = PublicationMutationUnit(
        ordinal=0,
        unit=ledger_test_unit("src/item.py", 0, 1),
        state=ProofMutationState.PREPARED,
        prepared_at=2.0,
    )
    reserved = PublicationReceipt(
        receipt_id="receipt-v1",
        reservation_sequence=8,
        compatibility_key=ledger_test_proof_compatibility(),
        generation_id="generation-v2",
        parent_revision=3,
        target_revision=4,
        state=ProofReceiptState.RESERVED,
        reserved_at=1.0,
    )

    assert reserved.mutations == ()
    assert reserved.deltas == ()
    assert reserved.is_open
    with_prepared = replace(reserved, mutations=(prepared,))

    assert prepared.unit.source_digest is not None
    evidence = ProofEvidence(
        rel_path="src/item.py",
        content_identity=prepared.unit.source_digest,
        point_ids=prepared.unit.point_ids,
    )
    delta = PathDelta(
        outcome=PathOutcome.ADD,
        expected_parent_revision=3,
        rel_path=evidence.rel_path,
        new=evidence,
    )
    with pytest.raises(ValueError, match="exactly cover"):
        replace(
            reserved,
            state=ProofReceiptState.SEALED,
            deltas=(delta,),
            sealed_at=4.0,
        )

    sealed_prepared = replace(prepared, sealed_ordinal=0)
    sealed = replace(
        with_prepared,
        state=ProofReceiptState.SEALED,
        mutations=(sealed_prepared,),
        deltas=(delta,),
        sealed_at=4.0,
    )

    assert sealed.is_open
    wrong_content = replace(
        sealed_prepared,
        unit=replace(
            sealed_prepared.unit, source_digest=ledger_test_digest("other-content")
        ),
    )
    with pytest.raises(ValueError, match="content must match"):
        replace(sealed, mutations=(wrong_content,))
    wrong_points = replace(
        sealed_prepared,
        unit=replace(
            sealed_prepared.unit,
            point_ids=sealed_prepared.unit.point_ids[:1],
        ),
    )
    with pytest.raises(ValueError, match="exact proof point"):
        replace(sealed, mutations=(wrong_points,))
    with pytest.raises(ValueError, match="every mutation"):
        replace(sealed, state=ProofReceiptState.COMMITTED, committed_at=5.0)

    confirmed = replace(
        sealed_prepared,
        state=ProofMutationState.CONFIRMED,
        applied_at=2.5,
        confirmed_at=3.0,
    )
    late_confirmation = replace(confirmed, applied_at=4.5, confirmed_at=6.0)
    with pytest.raises(ValueError, match="follow receipt closure"):
        replace(
            sealed,
            state=ProofReceiptState.COMMITTED,
            mutations=(late_confirmation,),
            committed_at=5.0,
        )
    committed = replace(
        sealed,
        state=ProofReceiptState.COMMITTED,
        mutations=(confirmed,),
        committed_at=5.0,
    )
    noop_evidence = ProofEvidence(
        rel_path="src/noop.py",
        content_identity="content-v1",
        point_ids=("point-v1",),
    )
    noop = PathDelta(
        outcome=PathOutcome.NOOP,
        expected_parent_revision=3,
        rel_path=noop_evidence.rel_path,
        old=noop_evidence,
        new=noop_evidence,
    )
    with pytest.raises(ValueError, match="no-op receipt"):
        replace(
            reserved,
            state=ProofReceiptState.COMMITTED,
            deltas=(noop,),
            sealed_at=4.0,
            committed_at=5.0,
        )
    confirmed_unsealed = replace(confirmed, sealed_ordinal=None)
    with_confirmed = replace(with_prepared, mutations=(confirmed_unsealed,))
    with pytest.raises(ValueError, match="confirmed mutations"):
        replace(
            with_prepared,
            state=ProofReceiptState.ROLLING_BACK,
            rollback_started_at=4.0,
        )
    rolling_back = replace(
        with_confirmed,
        state=ProofReceiptState.ROLLING_BACK,
        rollback_started_at=4.0,
    )
    with pytest.raises(ValueError, match="follow receipt closure"):
        replace(
            with_confirmed,
            state=ProofReceiptState.ROLLING_BACK,
            rollback_started_at=2.75,
        )
    rolled_back = replace(
        rolling_back,
        state=ProofReceiptState.ROLLED_BACK,
        rolled_back_at=5.0,
    )

    assert not committed.is_open
    assert rolling_back.is_open
    assert not rolled_back.is_open
    assert set(ProofReceiptState) == {
        ProofReceiptState.RESERVED,
        ProofReceiptState.SEALED,
        ProofReceiptState.ROLLING_BACK,
        ProofReceiptState.COMMITTED,
        ProofReceiptState.ROLLED_BACK,
    }


def test_publication_reservation_sequence_fences_open_and_rolled_back_receipts(
    tmp_path: Path,
) -> None:
    """Mutation proving this can fail: ignore the stored sequence at validation."""
    evidence = ProofEvidence(
        rel_path="src/a.py",
        content_identity=ledger_test_digest("a-v1"),
        point_ids=("point-a",),
    )
    ledger, key, _parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path,
        (evidence,),
    )
    token = acquire_publication_read_token(ledger, key)

    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=token.revision,
    )
    assert receipt.reservation_sequence == token.reservation_sequence + 1
    assert ledger.active_publication_receipt(key) == receipt
    with pytest.raises(ProofReadConflictError):
        acquire_publication_read_token(ledger, key)
    with pytest.raises(ProofReadConflictError):
        ledger.validate_publication_read_token(token)

    rolling_back = ledger.begin_publication_rollback(receipt.receipt_id)
    assert rolling_back.state is ProofReceiptState.ROLLING_BACK
    rolled_back = ledger.roll_back_publication_receipt(
        receipt.receipt_id,
        compensated_units=(),
    )
    assert rolled_back.state is ProofReceiptState.ROLLED_BACK

    assert ledger.active_publication_receipt(key) is None
    with pytest.raises(ProofReadConflictError):
        ledger.validate_publication_read_token(token)
    current = acquire_publication_read_token(ledger, key)
    ledger.validate_publication_read_token(current)
    next_receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=current.revision,
    )
    assert next_receipt.reservation_sequence == receipt.reservation_sequence + 1


def test_publication_mutation_journal_is_monotonic_exact_and_replayable(
    tmp_path: Path,
) -> None:
    """Mutation: allowing CONFIRMED directly from PREPARED makes this guard red."""
    ledger, key, _parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path, ()
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )
    unit = ledger_test_unit("src/a.py", 0, 1)

    preparation_source = inspect.getsource(
        RunLedgerCommitMethods.prepare_publication_mutation
    ).lower()
    assert "count(*)" not in preparation_source
    assert "max(mutation_ordinal)" not in preparation_source

    prepared = ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    assert prepared.state is ProofMutationState.PREPARED
    reopened = RunLedger(ledger.path)
    assert reopened.prepare_publication_mutation(receipt.receipt_id, unit) == prepared
    second = ledger_test_unit("src/second.py", 0, 1)
    second_prepared = reopened.prepare_publication_mutation(
        receipt.receipt_id,
        second,
    )
    assert (prepared.ordinal, second_prepared.ordinal) == (0, 1)
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        cursor = connection.execute(
            """
            SELECT next_mutation_ordinal FROM publication_receipts
            WHERE receipt_id = ?
            """,
            (receipt.receipt_id,),
        ).fetchone()
    assert cursor is not None and int(cursor[0]) == 2
    assert ledger.prepare_publication_mutation(receipt.receipt_id, unit) == prepared
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        replay_cursor = connection.execute(
            """
            SELECT next_mutation_ordinal FROM publication_receipts
            WHERE receipt_id = ?
            """,
            (receipt.receipt_id,),
        ).fetchone()
    assert replay_cursor is not None and int(replay_cursor[0]) == 2
    with pytest.raises(RunLedgerStateError, match="applied"):
        ledger.confirm_publication_mutation(receipt.receipt_id, unit)

    applied = ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
    assert applied.state is ProofMutationState.APPLIED
    assert applied.applied_at is not None
    assert ledger.mark_publication_mutation_applied(receipt.receipt_id, unit) == applied

    confirmed = ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    assert confirmed.state is ProofMutationState.CONFIRMED
    assert confirmed.confirmed_at is not None
    assert ledger.confirm_publication_mutation(receipt.receipt_id, unit) == confirmed
    assert ledger.prepare_publication_mutation(receipt.receipt_id, unit) == confirmed

    collision = replace(unit, point_ids=("different-point",))
    with pytest.raises(RunLedgerStateError, match="slot"):
        ledger.prepare_publication_mutation(receipt.receipt_id, collision)
    ledger.advance_finalization(successor_id, FinalizationPhase.STALE_RECONCILED)
    with pytest.raises(RunLedgerStateError, match="after finalization begins"):
        ledger.prepare_publication_mutation(
            receipt.receipt_id,
            ledger_test_unit("src/b.py", 0, 1),
        )


def test_publication_receipt_seal_is_exact_atomic_and_identity_ordered(
    tmp_path: Path,
) -> None:
    """Mutation: sealing partial point coverage makes this guard red."""
    ledger, key, _parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path, ()
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )
    digest = ledger_test_digest("a-v1")
    first = ledger_test_unit("src/a.py", 0, 2, digest=digest)
    second = ledger_test_unit("src/a.py", 1, 2, digest=digest)
    for unit in (second, first):
        ledger.prepare_publication_mutation(receipt.receipt_id, unit)
        ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
        ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    evidence = ProofEvidence(
        rel_path="src/a.py",
        content_identity=digest,
        point_ids=tuple(sorted((*first.point_ids, *second.point_ids))),
    )
    partial = replace(evidence, point_ids=tuple(sorted(first.point_ids)))
    invalid_delta = PathDelta(
        outcome=PathOutcome.ADD,
        expected_parent_revision=receipt.parent_revision,
        rel_path=evidence.rel_path,
        new=partial,
    )
    with pytest.raises(ValueError, match="exact proof point membership"):
        ledger.seal_publication_receipt(receipt.receipt_id, (invalid_delta,))
    still_reserved = ledger.active_publication_receipt(key)
    assert still_reserved is not None
    assert still_reserved.state is ProofReceiptState.RESERVED
    assert still_reserved.deltas == ()
    assert all(unit.sealed_ordinal is None for unit in still_reserved.mutations)

    delta = replace(invalid_delta, new=evidence)
    sealed = ledger.seal_publication_receipt(receipt.receipt_id, (delta,))
    assert sealed.state is ProofReceiptState.SEALED
    assert sealed.deltas == (delta,)
    assert {
        mutation.identity: mutation.sealed_ordinal for mutation in sealed.mutations
    } == {
        identity: ordinal
        for ordinal, identity in enumerate(sorted((first.identity, second.identity)))
    }
    assert ledger.seal_publication_receipt(receipt.receipt_id, (delta,)) == sealed
    with pytest.raises(RunLedgerStateError, match="sealed"):
        ledger.prepare_publication_mutation(
            receipt.receipt_id,
            ledger_test_unit("src/b.py", 0, 1),
        )


def test_publication_mutation_prepare_refuses_foreign_point_ownership(
    tmp_path: Path,
) -> None:
    """Mutation: deferring point-owner validation until seal makes this red."""
    owner = ProofEvidence(
        rel_path="src/owner.py",
        content_identity=ledger_test_digest("owner"),
        point_ids=("owned-point",),
    )
    ledger, key, _parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path,
        (owner,),
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )
    evidence = ProofEvidence(
        rel_path="src/new.py",
        content_identity=ledger_test_digest("new"),
        point_ids=("owned-point",),
    )
    unit = CommitUnit(
        rel_path=evidence.rel_path,
        kind=CommitUnitKind.UPSERT,
        source_digest=evidence.content_identity,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=evidence.point_ids,
    )
    with pytest.raises(RunLedgerStateError, match="another canonical path"):
        ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    active = ledger.active_publication_receipt(key)
    assert active is not None
    assert active.state is ProofReceiptState.RESERVED
    assert active.mutations == ()
    assert active.deltas == ()


def test_publication_receipt_seal_rechecks_late_point_ownership(
    tmp_path: Path,
) -> None:
    """Mutation: removing seal's defense-in-depth owner check makes this red."""
    owner = ProofEvidence(
        rel_path="src/owner.py",
        content_identity=ledger_test_digest("owner"),
        point_ids=("owner-original",),
    )
    ledger, key, _parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path,
        (owner,),
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )
    evidence = ProofEvidence(
        rel_path="src/new.py",
        content_identity=ledger_test_digest("new"),
        point_ids=("late-collision",),
    )
    unit = CommitUnit(
        rel_path=evidence.rel_path,
        kind=CommitUnitKind.UPSERT,
        source_digest=evidence.content_identity,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=evidence.point_ids,
    )
    ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
    ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute(
            """
            UPDATE publication_points SET point_id = ?
            WHERE source_type = ? AND root_identity = ?
              AND backend_identity = ? AND collection_identity = ?
              AND rel_path = ?
            """,
            (
                evidence.point_ids[0],
                key.source_type.value,
                key.root_identity,
                key.backend_identity,
                key.collection_identity,
                owner.rel_path,
            ),
        )
        connection.commit()
    delta = PathDelta(
        outcome=PathOutcome.ADD,
        expected_parent_revision=receipt.parent_revision,
        rel_path=evidence.rel_path,
        new=evidence,
    )

    with pytest.raises(ProofOldEvidenceMismatchError, match="untouched path"):
        ledger.seal_publication_receipt(receipt.receipt_id, (delta,))
    active = ledger.active_publication_receipt(key)
    assert active is not None
    assert active.state is ProofReceiptState.RESERVED
    assert active.deltas == ()


def test_publication_receipt_rollback_requires_exact_confirmed_compensation(
    tmp_path: Path,
) -> None:
    """Mutation: accepting an uncertain PREPARED rollback makes this guard red."""
    ledger, key, _parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path, ()
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )
    unit = ledger_test_unit("src/a.py", 0, 1)
    ledger.prepare_publication_mutation(receipt.receipt_id, unit)

    with pytest.raises(RunLedgerStateError, match="confirmed"):
        ledger.begin_publication_rollback(receipt.receipt_id)
    ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
    with pytest.raises(RunLedgerStateError, match="confirmed"):
        ledger.begin_publication_rollback(receipt.receipt_id)
    ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    with pytest.raises(RunLedgerStateError, match="must begin"):
        ledger.roll_back_publication_receipt(
            receipt.receipt_id,
            compensated_units=(unit,),
        )
    rolling_back = ledger.begin_publication_rollback(receipt.receipt_id)
    assert rolling_back.state is ProofReceiptState.ROLLING_BACK
    reopened = RunLedger(ledger.path)
    assert reopened.active_publication_receipt(key) == rolling_back
    for transition in (
        reopened.prepare_publication_mutation,
        reopened.mark_publication_mutation_applied,
        reopened.confirm_publication_mutation,
    ):
        with pytest.raises(RunLedgerStateError, match="rolling_back"):
            transition(receipt.receipt_id, unit)
    with pytest.raises(RunLedgerStateError, match="exactly"):
        reopened.roll_back_publication_receipt(
            receipt.receipt_id,
            compensated_units=(),
        )

    rolled_back = reopened.roll_back_publication_receipt(
        receipt.receipt_id,
        compensated_units=(unit,),
    )
    assert rolled_back.state is ProofReceiptState.ROLLED_BACK
    assert ledger.active_publication_receipt(key) is None
    for transition in (
        ledger.prepare_publication_mutation,
        ledger.mark_publication_mutation_applied,
        ledger.confirm_publication_mutation,
    ):
        with pytest.raises(RunLedgerStateError, match="rolled_back"):
            transition(receipt.receipt_id, unit)
    assert (
        ledger.roll_back_publication_receipt(
            receipt.receipt_id,
            compensated_units=(unit,),
        )
        == rolled_back
    )


def test_sealed_receipt_commit_is_exact_atomic_and_replayable(
    tmp_path: Path,
) -> None:
    """Mutation proving this can fail: allow proof commit while still ingesting."""
    untouched = ProofEvidence(
        rel_path="src/b.py",
        content_identity=ledger_test_digest("b-v1"),
        point_ids=("point-b-0",),
    )
    (
        ledger,
        key,
        _parent_id,
        successor_id,
        receipt,
        old,
        new,
        delta,
        mutation,
    ) = ledger_test_sealed_modify_receipt(
        tmp_path,
        point_ids=("point-a-0", "point-a-1"),
        additional_evidence=(untouched,),
    )
    with pytest.raises(RunLedgerStateError, match="only after stale reconciliation"):
        ledger.commit_publication_receipt(receipt.receipt_id)
    ledger.advance_finalization(successor_id, FinalizationPhase.STALE_RECONCILED)

    active = ledger.active_publication_receipt(key)
    assert active is not None
    assert active.state is ProofReceiptState.SEALED
    assert active.deltas == (delta,)
    assert active.mutations[0].unit == mutation
    committed = ledger.commit_publication_receipt(receipt.receipt_id)

    assert committed.revision == receipt.target_revision
    assert committed.reservation_sequence == receipt.reservation_sequence
    assert committed.generation_id == successor_id
    assert committed.provenance is ProofProvenance.DELTA_DERIVED
    assert committed.aggregate == ProofAggregate(
        indexed_identities=2,
        retained_points=3,
    )
    assert ledger.publication_evidence_for_paths(
        key,
        (old.rel_path, untouched.rel_path),
    ) == {new.rel_path: new, untouched.rel_path: untouched}
    assert ledger.active_publication_receipt(key) is None

    connection = sqlite3.connect(ledger.path)
    try:
        connection.execute(
            "UPDATE generations SET terminal_state = ? WHERE generation_id = ?",
            (RunTerminalState.SUCCEEDED.value, successor_id),
        )
        connection.commit()
    finally:
        connection.close()
    assert ledger.commit_publication_receipt(receipt.receipt_id) == committed
