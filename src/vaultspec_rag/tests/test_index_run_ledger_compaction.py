"""Run-ledger compaction behavior."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from .._source_types import PublicSourceType
from ..indexer._content_policy import ContentKind
from ..indexer._file_state import FileState, FileStateKind
from ..indexer._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofEvidence,
    ProofReceiptState,
)
from ..indexer._run_ledger_models import (
    FETCH_BATCH,
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    RunTerminalState,
)
from ..indexer._run_ledger_publication_identity import compatibility_for_signature
from ..indexer._run_ledger_runtime import RunLedger
from ._run_ledger_test_support import (
    ledger_test_certify_generation,
    ledger_test_digest,
    ledger_test_duplicate_receipt_row,
    ledger_test_publish_and_compact,
    ledger_test_publish_and_finish,
    ledger_test_publish_generation_with_proof,
    ledger_test_seal_publication_receipt,
    ledger_test_signature,
    ledger_test_unit,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_compaction_preserves_published_and_running_generations(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    first = ledger.start_generation(
        ledger_test_signature(tmp_path, content_epoch="first")
    )
    second = ledger.start_generation(
        ledger_test_signature(tmp_path, content_epoch="second")
    )
    ledger_test_certify_generation(ledger, second.generation_id)
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(second.generation_id, phase)
    ledger.finish_generation(second.generation_id, RunTerminalState.SUCCEEDED)

    document = replace(
        ledger_test_signature(tmp_path),
        source_type=PublicSourceType.DOCUMENT,
        collection_identity="document-v1",
    )
    running = ledger.start_generation(document)
    ledger_test_certify_generation(ledger, running.generation_id)
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(running.generation_id, phase)
    document_published = ledger.finish_generation(
        running.generation_id,
        RunTerminalState.SUCCEEDED,
    )
    assert ledger.compact(second.generation_id) == 1
    with pytest.raises(KeyError):
        ledger.generation(first.generation_id)
    assert ledger.generation(second.generation_id).finalization_phase is (
        FinalizationPhase.COMPACTED
    )
    assert ledger.generation(running.generation_id) == document_published


def test_compact_tolerates_an_updated_at_tie_with_another_publication(
    tmp_path: Path,
) -> None:
    """A timestamp tie must not refuse the in-order publisher.

    Two stamps taken from one coarse clock reading cannot be ordered, so the
    guard refuses only a strictly newer publication. The tie is reachable
    only through clock coarseness, which is why the stamp is written
    directly rather than raced.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = ledger_test_signature(tmp_path)

    older = ledger.start_generation(signature)
    digest = ledger_test_digest("src/kept.py:v1")
    ledger.record_storage_confirmed_unit(
        older.generation_id,
        ledger_test_unit("src/kept.py", 0, 1, digest=digest),
    )
    ledger.record_file_state(
        older.generation_id,
        FileState("src/kept.py", FileStateKind.INDEXED, ContentKind.CODE, digest),
    )
    ledger_test_publish_and_compact(ledger, older.generation_id)

    newest = ledger.start_generation(signature)
    ledger_test_certify_generation(ledger, newest.generation_id)
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(newest.generation_id, phase)
    ledger.finish_generation(newest.generation_id, RunTerminalState.SUCCEEDED)

    connection = sqlite3.connect(ledger.path)
    connection.execute(
        "UPDATE generations SET updated_at = "
        "(SELECT updated_at FROM generations WHERE generation_id = ?) "
        "WHERE generation_id = ?",
        (older.generation_id, newest.generation_id),
    )
    connection.commit()
    connection.close()

    ledger.compact(newest.generation_id)
    assert ledger.generation(newest.generation_id).finalization_phase is (
        FinalizationPhase.COMPACTED
    )


def test_compaction_preserves_every_canonical_publication_owner(
    tmp_path: Path,
) -> None:
    """Mutation: omitting any proof owner makes compaction delete or fail.

    Three generations are cited by canonical publication state, each the way a
    real run leaves it: the rebuild that wrote the still-current evidence for
    an untouched path, the successor whose committed receipt moved the proof
    and rewrote one path's evidence, and the successor still holding an open
    reservation.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    base = replace(ledger_test_signature(tmp_path), collection_identity="collection-v1")
    key = compatibility_for_signature(base)
    untouched = ProofEvidence(
        rel_path="src/retained.py",
        content_identity=ledger_test_digest("retained"),
        point_ids=("point-retained",),
    )
    rewritten = ProofEvidence(
        rel_path="src/moved.py",
        content_identity=ledger_test_digest("moved-v1"),
        point_ids=("point-moved",),
    )

    evidence_owner = ledger.start_generation(base)
    ledger_test_publish_generation_with_proof(
        ledger,
        evidence_owner.generation_id,
        evidence=(untouched, rewritten),
    )

    proof_owner = ledger.start_generation(base)
    receipt = ledger.reserve_publication_receipt(
        key,
        proof_owner.generation_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )
    replacement = replace(rewritten, content_identity=ledger_test_digest("moved-v2"))
    ledger_test_seal_publication_receipt(
        ledger,
        receipt,
        mutation=CommitUnit(
            rel_path=replacement.rel_path,
            kind=CommitUnitKind.UPSERT,
            source_digest=replacement.content_identity,
            segment_ordinal=0,
            is_file_end=True,
            point_ids=replacement.point_ids,
        ),
        delta=PathDelta(
            outcome=PathOutcome.MODIFY,
            expected_parent_revision=receipt.parent_revision,
            rel_path=rewritten.rel_path,
            old=rewritten,
            new=replacement,
        ),
    )
    ledger.advance_finalization(
        proof_owner.generation_id, FinalizationPhase.STALE_RECONCILED
    )
    ledger.commit_publication_receipt(receipt.receipt_id)
    for phase in (
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(proof_owner.generation_id, phase)
    ledger.finish_generation(proof_owner.generation_id, RunTerminalState.SUCCEEDED)

    open_owner = ledger.start_generation(base)
    open_receipt = ledger.reserve_publication_receipt(
        key,
        open_owner.generation_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )
    obsolete = ledger.start_generation(replace(base, content_epoch="obsolete"))
    keep = ledger.start_generation(replace(base, backend_identity="keep-backend"))
    ledger_test_publish_and_finish(ledger, keep.generation_id)

    assert ledger.compact(keep.generation_id) == 1
    for retained in (proof_owner, evidence_owner, open_owner, keep):
        assert ledger.generation(retained.generation_id).generation_id == (
            retained.generation_id
        )
    with pytest.raises(KeyError):
        ledger.generation(obsolete.generation_id)
    active = ledger.active_publication_receipt(key)
    assert active is not None
    assert active.receipt_id == open_receipt.receipt_id
    assert active.state is ProofReceiptState.RESERVED


def test_compaction_bounds_closed_receipts_per_projection_without_pruning_open(
    tmp_path: Path,
) -> None:
    """Mutation: skipping, reversing, or widening pruning makes this guard red.

    The open reservation is the one the ledger issued; the closed history is
    that row copied forward, because a hundred-deep history is reachable only
    by replaying a hundred publications and the bound, not the replay, is
    what is under test.

    Mutation evidence: reducing the retained-history bound by one failed the
    exact retained-sequence assertion; restoring it passed the same test.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = replace(
        ledger_test_signature(tmp_path),
        collection_identity="collection-v1",
        content_epoch="current",
    )
    obsolete = ledger.start_generation(replace(signature, content_epoch="obsolete"))
    published = ledger.start_generation(signature)
    ledger_test_publish_generation_with_proof(ledger, published.generation_id)
    key = compatibility_for_signature(signature)
    open_owner = ledger.start_generation(signature)
    still_open = ledger.reserve_publication_receipt(
        key,
        open_owner.generation_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )
    keep = ledger.start_generation(replace(signature, backend_identity="keep-backend"))
    ledger_test_publish_and_finish(ledger, keep.generation_id)
    stamp = still_open.reserved_at
    # The live reservation already holds one sequence on its projection, and
    # the sequence is unique per projection, so the copied history follows it.
    first_history = still_open.reservation_sequence + 1

    history_limit = FETCH_BATCH
    history_size = history_limit + 3
    projection_keys = (key, replace(key, backend_identity="backend-v2"))
    closed_states = (
        {"state": "rolled_back", "rollback_started_at": stamp, "rolled_back_at": stamp},
        {"state": "committed", "sealed_at": stamp, "committed_at": stamp},
    )
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for projection_index, projection_key in enumerate(projection_keys):
            for sequence in range(first_history, first_history + history_size):
                ledger_test_duplicate_receipt_row(
                    connection,
                    still_open.receipt_id,
                    receipt_id=f"history-{projection_index}-{sequence}",
                    reservation_sequence=sequence,
                    overrides={
                        "backend_identity": projection_key.backend_identity,
                        "generation_id": (
                            obsolete.generation_id
                            if sequence == first_history
                            else keep.generation_id
                        ),
                        **closed_states[sequence % 2],
                    },
                )
        ledger_test_duplicate_receipt_row(
            connection,
            still_open.receipt_id,
            receipt_id="still-sealed",
            reservation_sequence=first_history + history_size,
            overrides={
                "backend_identity": projection_keys[1].backend_identity,
                "state": "sealed",
                "sealed_at": stamp,
            },
        )
        connection.commit()

    assert ledger.compact(keep.generation_id) == 1
    assert ledger.compact(keep.generation_id) == 0
    with pytest.raises(KeyError):
        ledger.generation(obsolete.generation_id)
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        for projection_key in projection_keys:
            rows = connection.execute(
                """
                SELECT reservation_sequence FROM publication_receipts
                WHERE source_type = ? AND root_identity = ?
                  AND backend_identity = ? AND collection_identity = ?
                  AND state IN ('committed', 'rolled_back')
                ORDER BY reservation_sequence
                """,
                (
                    projection_key.source_type.value,
                    projection_key.root_identity,
                    projection_key.backend_identity,
                    projection_key.collection_identity,
                ),
            ).fetchall()
            assert tuple(int(row[0]) for row in rows) == tuple(
                range(
                    first_history + history_size - history_limit,
                    first_history + history_size,
                )
            )
        assert {
            str(row[0])
            for row in connection.execute(
                """
                SELECT state FROM publication_receipts
                WHERE receipt_id IN (?, 'still-sealed')
                """,
                (still_open.receipt_id,),
            )
        } == {ProofReceiptState.RESERVED.value, ProofReceiptState.SEALED.value}
