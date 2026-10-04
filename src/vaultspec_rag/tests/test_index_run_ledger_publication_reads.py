"""Run-ledger publication reads behavior."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from ..indexer._content_policy import ContentKind
from ..indexer._file_state import FileState, FileStateKind
from ..indexer._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofAggregate,
    ProofEvidence,
    ProofIncompatibleError,
    ProofMissingError,
)
from ..indexer._run_ledger_models import (
    FETCH_BATCH,
    CommitUnit,
    CommitUnitKind,
    PublicationPointCandidate,
    RunAuthority,
    RunLedgerCorruptionError,
    RunLedgerStateError,
)
from ..indexer._run_ledger_publication_proofs import RunLedgerPublicationProofMethods
from ..indexer._run_ledger_publication_reads import RunLedgerPublicationReadMethods
from ..indexer._run_ledger_publication_receipts import (
    RunLedgerPublicationReceiptMethods,
)
from ..indexer._run_ledger_runtime import RunLedger
from ._run_ledger_test_support import (
    ledger_test_digest,
    ledger_test_publish_and_compact,
    ledger_test_seeded_publication_lineage,
    ledger_test_signature,
    ledger_test_unit,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_generation_start_leaves_canonical_publication_projection_unchanged(
    tmp_path: Path,
) -> None:
    """Mutation: any canonical-table DML during generation start makes this red."""
    evidence = (
        ProofEvidence(
            rel_path="src/a.py",
            content_identity=ledger_test_digest("a-v1"),
            point_ids=("point-a-0", "point-a-1"),
        ),
        ProofEvidence(
            rel_path="src/b.py",
            content_identity=ledger_test_digest("b-v1"),
            point_ids=("point-b-0",),
        ),
    )
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = ledger_test_signature(tmp_path)
    parent = ledger.start_generation(signature)
    ledger.establish_verified_publication(
        parent.generation_id, RunAuthority.REBUILD, evidence
    )
    ledger_test_publish_and_compact(ledger, parent.generation_id)

    def canonical_projection() -> tuple[tuple[object, ...], ...]:
        with closing(sqlite3.connect(ledger.path)) as connection, connection:
            return tuple(
                tuple(row)
                for table in (
                    "publication_proofs",
                    "publication_evidence",
                    "publication_points",
                )
                for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
            )

    before = canonical_projection()
    canonical_tables = (
        "publication_proofs",
        "publication_evidence",
        "publication_points",
    )
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        for table in canonical_tables:
            for operation in ("INSERT", "UPDATE", "DELETE"):
                trigger = f"reject_start_{operation.lower()}_{table}"
                connection.execute(
                    f"""
                    CREATE TRIGGER "{trigger}"
                    BEFORE {operation} ON "{table}"
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'canonical publication write during generation start'
                        );
                    END
                    """
                )
        connection.commit()

    try:
        successor = ledger.start_generation(signature)
    except sqlite3.IntegrityError as exc:  # pragma: no cover - mutation guard
        pytest.fail(f"generation start wrote canonical publication state: {exc}")
    finally:
        with closing(sqlite3.connect(ledger.path)) as connection, connection:
            for table in canonical_tables:
                for operation in ("INSERT", "UPDATE", "DELETE"):
                    connection.execute(
                        f'DROP TRIGGER "reject_start_{operation.lower()}_{table}"'
                    )
            connection.commit()

    assert successor.parent_generation_id == parent.generation_id
    assert successor.generation_id != parent.generation_id
    assert canonical_projection() == before


def test_publication_reads_are_bounded_and_distinguish_incompatible_proof(
    tmp_path: Path,
) -> None:
    first = ProofEvidence(
        rel_path="src/a.py",
        content_identity=ledger_test_digest("a-v1"),
        point_ids=("point-a-0", "point-a-1"),
    )
    second = ProofEvidence(
        rel_path="src/b.py",
        content_identity=ledger_test_digest("b-v1"),
        point_ids=("point-b-0",),
    )
    ledger, key, parent_id, _successor_id = ledger_test_seeded_publication_lineage(
        tmp_path,
        (first, second),
    )

    assert all(
        owner in RunLedger.__mro__
        for owner in (
            RunLedgerPublicationProofMethods,
            RunLedgerPublicationReadMethods,
            RunLedgerPublicationReceiptMethods,
        )
    )
    proof = ledger.publication_proof(key)
    assert proof.generation_id == parent_id
    assert proof.aggregate == ProofAggregate(
        indexed_identities=2,
        retained_points=3,
    )
    assert ledger.publication_evidence_for_paths(
        key,
        (second.rel_path, first.rel_path, first.rel_path),
    ) == {first.rel_path: first, second.rel_path: second}
    assert ledger.publication_point_ids_for_candidates(
        key,
        ("absent", "point-a-1", "point-b-0"),
    ) == frozenset({"point-a-1", "point-b-0"})

    incompatible = replace(key, payload_schema=key.payload_schema + 1)
    with pytest.raises(ProofIncompatibleError):
        ledger.publication_proof(incompatible)
    with pytest.raises(ProofIncompatibleError):
        ledger.publication_evidence_for_paths(incompatible, (first.rel_path,))
    with pytest.raises(ProofMissingError):
        ledger.publication_proof(replace(key, root_identity="other-root"))
    with pytest.raises(ValueError, match="at most"):
        ledger.publication_evidence_for_paths(
            key,
            tuple(f"src/{ordinal}.py" for ordinal in range(FETCH_BATCH + 1)),
        )
    with pytest.raises(ValueError, match="at most"):
        ledger.publication_point_ids_for_candidates(
            key,
            tuple(f"point-{ordinal}" for ordinal in range(FETCH_BATCH + 1)),
        )


def test_effective_receipt_read_folds_canonical_sparse_and_deleted_state(
    tmp_path: Path,
) -> None:
    """Guard: one receipt snapshot owns both path state and retained IDs."""
    old_a = ProofEvidence(
        rel_path="src/a.py",
        content_identity=ledger_test_digest("a-v1"),
        point_ids=("point-a-old",),
    )
    old_b = ProofEvidence(
        rel_path="src/b.py",
        content_identity=ledger_test_digest("b-v1"),
        point_ids=("point-b-old",),
    )
    untouched = ProofEvidence(
        rel_path="src/untouched.py",
        content_identity=ledger_test_digest("untouched-v1"),
        point_ids=("point-untouched",),
    )
    ledger, key, _parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path,
        (old_a, old_b, untouched),
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )

    replacement_digest = ledger_test_digest("b-v2")
    replacement = CommitUnit(
        rel_path=old_b.rel_path,
        kind=CommitUnitKind.UPSERT,
        source_digest=replacement_digest,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("point-b-new",),
    )
    deletion = CommitUnit(
        rel_path=old_a.rel_path,
        kind=CommitUnitKind.DELETE_PATH,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=old_a.point_ids,
    )
    stale_deletion = CommitUnit(
        rel_path=old_b.rel_path,
        kind=CommitUnitKind.DELETE_STALE,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=old_b.point_ids,
    )
    for unit in (replacement, deletion, stale_deletion):
        ledger.prepare_publication_mutation(receipt.receipt_id, unit)
        ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
        ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    replacement_evidence = ProofEvidence(
        rel_path=old_b.rel_path,
        content_identity=replacement_digest,
        point_ids=replacement.point_ids,
    )
    receipt = ledger.seal_publication_receipt(
        receipt.receipt_id,
        (
            PathDelta(
                outcome=PathOutcome.DELETE,
                expected_parent_revision=receipt.parent_revision,
                rel_path=old_a.rel_path,
                old=old_a,
            ),
            PathDelta(
                outcome=PathOutcome.MODIFY,
                expected_parent_revision=receipt.parent_revision,
                rel_path=old_b.rel_path,
                old=old_b,
                new=replacement_evidence,
            ),
        ),
    )

    # Sparse state is deliberately inserted without commit_units. The receipt's
    # confirmed mutation journal, not generation ancestry or the old checkpoint
    # table, is the retained-membership owner of this read.
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO file_states (
                generation_id, rel_path, state, content_kind, content_hash,
                admission_reason, error_kind, detail, evidence_generation_id
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
            """,
            (
                successor_id,
                old_b.rel_path,
                FileStateKind.INDEXED.value,
                ContentKind.CODE.value,
                replacement_digest,
                successor_id,
            ),
        )
        connection.execute(
            "INSERT INTO file_state_tombstones (generation_id, rel_path) VALUES (?, ?)",
            (successor_id, old_a.rel_path),
        )

    page = ledger.effective_file_state_page(
        receipt.receipt_id,
        successor_id,
        rel_paths=(old_a.rel_path, old_b.rel_path, untouched.rel_path),
        candidates=(
            PublicationPointCandidate(old_a.rel_path, old_a.point_ids[0]),
            PublicationPointCandidate(old_b.rel_path, old_b.point_ids[0]),
            PublicationPointCandidate(
                untouched.rel_path,
                untouched.point_ids[0],
            ),
            PublicationPointCandidate("src/wrong.py", untouched.point_ids[0]),
            PublicationPointCandidate(old_b.rel_path, untouched.point_ids[0]),
            PublicationPointCandidate(old_b.rel_path, replacement.point_ids[0]),
        ),
    )

    assert {state.rel_path: state for state in page.file_states} == {
        old_b.rel_path: FileState.indexed(
            old_b.rel_path,
            ContentKind.CODE,
            replacement_digest,
        ),
        untouched.rel_path: FileState.indexed(
            untouched.rel_path,
            ContentKind.CODE,
            untouched.content_identity,
        ),
    }
    assert page.retained_candidates == frozenset(
        {
            PublicationPointCandidate(old_b.rel_path, "point-b-new"),
            PublicationPointCandidate(untouched.rel_path, "point-untouched"),
        }
    )
    assert page.receipt_id == receipt.receipt_id
    assert page.generation_id == successor_id
    assert page.parent_revision == receipt.parent_revision
    assert page.reservation_sequence == receipt.reservation_sequence


def test_effective_receipt_read_refuses_unbounded_or_ambiguous_state(
    tmp_path: Path,
) -> None:
    """Guard: invalid authority never degrades into deletion-authorizing absence."""
    evidence = ProofEvidence(
        rel_path="src/a.py",
        content_identity=ledger_test_digest("a-v1"),
        point_ids=("point-a",),
    )
    ledger, key, _parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path,
        (evidence,),
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )

    with pytest.raises(ValueError, match="at most"):
        ledger.effective_file_state_page(
            receipt.receipt_id,
            successor_id,
            rel_paths=tuple(f"src/{ordinal}.py" for ordinal in range(FETCH_BATCH + 1)),
            candidates=(),
        )
    with pytest.raises(ValueError, match="at most"):
        ledger.effective_file_state_page(
            receipt.receipt_id,
            successor_id,
            rel_paths=(),
            candidates=tuple(
                PublicationPointCandidate(evidence.rel_path, f"point-{ordinal}")
                for ordinal in range(FETCH_BATCH + 1)
            ),
        )
    with pytest.raises(RunLedgerStateError, match="generation"):
        ledger.effective_file_state_page(
            receipt.receipt_id,
            "wrong-generation",
            rel_paths=(evidence.rel_path,),
            candidates=(
                PublicationPointCandidate(evidence.rel_path, evidence.point_ids[0]),
            ),
        )

    unit = CommitUnit(
        rel_path=evidence.rel_path,
        kind=CommitUnitKind.DELETE_PATH,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=evidence.point_ids,
    )
    ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
    ledger.confirm_publication_mutation(receipt.receipt_id, unit)
    receipt = ledger.seal_publication_receipt(
        receipt.receipt_id,
        (
            PathDelta(
                outcome=PathOutcome.DELETE,
                expected_parent_revision=receipt.parent_revision,
                rel_path=evidence.rel_path,
                old=evidence,
            ),
        ),
    )

    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO file_states (
                generation_id, rel_path, state, content_kind, content_hash,
                admission_reason, error_kind, detail, evidence_generation_id
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
            """,
            (
                successor_id,
                evidence.rel_path,
                FileStateKind.INDEXED.value,
                ContentKind.CODE.value,
                evidence.content_identity,
                successor_id,
            ),
        )
        connection.execute(
            "INSERT INTO file_state_tombstones (generation_id, rel_path) VALUES (?, ?)",
            (successor_id, evidence.rel_path),
        )

    with pytest.raises(RunLedgerCorruptionError, match=r"override.*tombstone"):
        ledger.effective_file_state_page(
            receipt.receipt_id,
            successor_id,
            rel_paths=(evidence.rel_path,),
            candidates=(
                PublicationPointCandidate(evidence.rel_path, evidence.point_ids[0]),
            ),
        )


def test_file_state_and_deletion_tombstone_replace_each_other_atomically(
    tmp_path: Path,
) -> None:
    """Guard: a path has exactly one sparse run-local outcome at a time."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    rel_path = "src/replaced.py"
    deletion = CommitUnit(
        rel_path=rel_path,
        kind=CommitUnitKind.DELETE_PATH,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("point-old",),
    )
    ledger.record_storage_confirmed_unit(generation.generation_id, deletion)
    ledger.record_path_deleted(generation.generation_id, rel_path)
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        assert connection.execute(
            """
            SELECT 1 FROM file_state_tombstones
            WHERE generation_id = ? AND rel_path = ?
            """,
            (generation.generation_id, rel_path),
        ).fetchone() == (1,)
        assert (
            connection.execute(
                """
            SELECT 1 FROM file_states
            WHERE generation_id = ? AND rel_path = ?
            """,
                (generation.generation_id, rel_path),
            ).fetchone()
            is None
        )

    digest = ledger_test_digest("replacement")
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        ledger_test_unit(rel_path, 0, 1, digest=digest),
    )
    ledger.record_file_state(
        generation.generation_id,
        FileState.indexed(rel_path, ContentKind.CODE, digest),
    )
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        assert (
            connection.execute(
                """
            SELECT 1 FROM file_state_tombstones
            WHERE generation_id = ? AND rel_path = ?
            """,
                (generation.generation_id, rel_path),
            ).fetchone()
            is None
        )
        assert connection.execute(
            """
            SELECT 1 FROM file_states
            WHERE generation_id = ? AND rel_path = ?
            """,
            (generation.generation_id, rel_path),
        ).fetchone() == (1,)
