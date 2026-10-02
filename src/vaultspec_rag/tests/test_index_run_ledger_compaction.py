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
from ..indexer._publication_proof import ProofReceiptState
from ..indexer._run_ledger_models import (
    FETCH_BATCH,
    FinalizationPhase,
    RunTerminalState,
)
from ..indexer._run_ledger_runtime import RunLedger
from ._run_ledger_test_support import (
    ledger_test_digest,
    ledger_test_insert_reserved_receipt,
    ledger_test_proof_compatibility,
    ledger_test_proof_key_for_signature,
    ledger_test_publish_and_compact,
    ledger_test_publish_generation_with_proof,
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
    """Mutation: omitting any proof owner makes compaction delete or fail."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    base = replace(ledger_test_signature(tmp_path), collection_identity="collection-v1")
    generations = tuple(
        ledger.start_generation(replace(base, content_epoch=f"epoch-{ordinal}"))
        for ordinal in range(5)
    )
    proof_owner, evidence_owner, open_owner, obsolete, keep = generations
    key = ledger_test_proof_key_for_signature(keep.signature)
    ledger_test_publish_generation_with_proof(
        ledger,
        keep.generation_id,
        key=key,
    )

    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            UPDATE publication_proofs
            SET generation_id = ?, indexed_identities = 1
            WHERE source_type = ? AND root_identity = ?
              AND backend_identity = ? AND collection_identity = ?
            """,
            (
                proof_owner.generation_id,
                key.source_type.value,
                key.root_identity,
                key.backend_identity,
                key.collection_identity,
            ),
        )
        connection.execute(
            """
            INSERT INTO publication_evidence (
                source_type, root_identity, backend_identity,
                collection_identity, rel_path, content_identity,
                evidence_generation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key.source_type.value,
                key.root_identity,
                key.backend_identity,
                key.collection_identity,
                "src/retained.py",
                ledger_test_digest("retained"),
                evidence_owner.generation_id,
            ),
        )
        ledger_test_insert_reserved_receipt(
            connection,
            receipt_id="open-owner",
            reservation_sequence=6,
            generation_id=open_owner.generation_id,
            projection=(key, 1),
        )
        connection.commit()

    assert ledger.compact(keep.generation_id) == 1
    for retained in (proof_owner, evidence_owner, open_owner, keep):
        assert ledger.generation(retained.generation_id).generation_id == (
            retained.generation_id
        )
    with pytest.raises(KeyError):
        ledger.generation(obsolete.generation_id)
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        assert connection.execute(
            "SELECT state FROM publication_receipts WHERE receipt_id = 'open-owner'"
        ).fetchone() == (ProofReceiptState.RESERVED.value,)


def test_compaction_bounds_closed_receipts_per_projection_without_pruning_open(
    tmp_path: Path,
) -> None:
    """Mutation: skipping, reversing, or widening pruning makes this guard red."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = replace(
        ledger_test_signature(tmp_path),
        collection_identity="collection-v1",
        content_epoch="current",
    )
    obsolete = ledger.start_generation(replace(signature, content_epoch="obsolete"))
    keep = ledger.start_generation(signature)
    key = ledger_test_proof_key_for_signature(signature)
    ledger_test_publish_generation_with_proof(
        ledger,
        keep.generation_id,
        key=key,
    )

    history_limit = FETCH_BATCH
    history_size = history_limit + 3
    projection_keys = (
        ledger_test_proof_compatibility(),
        replace(ledger_test_proof_compatibility(), backend_identity="backend-v2"),
    )
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for projection_index, projection_key in enumerate(projection_keys):
            for sequence in range(1, history_size + 1):
                receipt_id = f"history-{projection_index}-{sequence}"
                ledger_test_insert_reserved_receipt(
                    connection,
                    receipt_id=receipt_id,
                    reservation_sequence=sequence,
                    generation_id=(
                        obsolete.generation_id if sequence == 1 else keep.generation_id
                    ),
                    projection=(projection_key, 1),
                )
                if sequence % 2 == 0:
                    connection.execute(
                        """
                        INSERT INTO publication_receipt_deltas (
                            receipt_id, delta_ordinal, outcome, rel_path,
                            target_rel_path, old_content_identity,
                            new_content_identity
                        ) VALUES (?, 0, 'add', ?, NULL, NULL, ?)
                        """,
                        (
                            receipt_id,
                            f"src/{receipt_id}.py",
                            ledger_test_digest(receipt_id),
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE publication_receipts
                        SET state = 'committed', sealed_at = 2.0,
                            committed_at = 3.0
                        WHERE receipt_id = ?
                        """,
                        (receipt_id,),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE publication_receipts
                        SET state = 'rolled_back', rollback_started_at = 2.0,
                            rolled_back_at = 3.0
                        WHERE receipt_id = ?
                        """,
                        (receipt_id,),
                    )
        ledger_test_insert_reserved_receipt(
            connection,
            receipt_id="still-open",
            reservation_sequence=history_size + 1,
            generation_id=keep.generation_id,
            projection=(projection_keys[0], 1),
        )
        ledger_test_insert_reserved_receipt(
            connection,
            receipt_id="still-sealed",
            reservation_sequence=history_size + 1,
            generation_id=keep.generation_id,
            projection=(projection_keys[1], 1),
        )
        connection.execute(
            """
            UPDATE publication_receipts
            SET state = 'sealed', sealed_at = 2.0
            WHERE receipt_id = 'still-sealed'
            """
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
                range(history_size - history_limit + 1, history_size + 1)
            )
        assert {
            str(row[0])
            for row in connection.execute(
                """
                SELECT state FROM publication_receipts
                WHERE receipt_id IN ('still-open', 'still-sealed')
                """
            )
        } == {ProofReceiptState.RESERVED.value, ProofReceiptState.SEALED.value}
