"""Real SQLite behavior for resumable indexing generations."""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import threading
from dataclasses import MISSING, replace
from pathlib import Path

import pytest

from .._index_breadth import GENERATION_ID_KEY
from .._source_types import PublicSourceType
from ..indexer._code_meta import (
    CONTENT_EPOCH_KEY,
    MEMBERSHIP_EPOCH_KEY,
    load_meta,
    publish_meta_from_file_states,
    read_meta_raw,
)
from ..indexer._content_policy import AdmissionDisposition, AdmissionReason, ContentKind
from ..indexer._file_state import FileState, FileStateKind
from ..indexer._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofAggregate,
    ProofCompatibilityKey,
    ProofEvidence,
    ProofIncompatibleError,
    ProofMissingError,
    ProofMutationState,
    ProofOldEvidenceMismatchError,
    ProofParentMismatchError,
    ProofProvenance,
    ProofReadConflictError,
    ProofReceiptState,
)
from ..indexer._run_ledger_commits import (
    RunLedgerCommitMethods,
    retained_point_ids_sql,
)
from ..indexer._run_ledger_models import (
    FETCH_BATCH,
    INDEX_RUN_LEDGER_FILENAME,
    PUBLICATION_PROOF_SCHEMA,
    REQUIRED_INDEX_PREDICATES,
    REQUIRED_INDEXES,
    REQUIRED_SCHEMA,
    RESUMABLE_STATES,
    SCHEMA_VERSION,
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    PublicationMutationUnit,
    PublicationPointCandidate,
    PublicationProof,
    PublicationReceipt,
    RunLedgerCompatibilityError,
    RunLedgerCorruptionError,
    RunLedgerIndexedPathCollisionError,
    RunLedgerRebuildRequiredError,
    RunLedgerStateError,
    RunOperation,
    RunSignature,
    RunTerminalState,
    index_run_ledger_path,
)
from ..indexer._run_ledger_publication import RunLedgerPublicationMethods
from ..indexer._run_ledger_runtime import RunLedger, _signature_from_payload
from ._production_service import PROCESS_TIMEOUT_SECONDS

pytestmark = [pytest.mark.unit]


def _digest(value: str) -> str:
    return hashlib.blake2b(value.encode("utf-8")).hexdigest()


def _signature(
    root: Path,
    *,
    content_epoch: str = "content-v1",
    backend_identity: str = "backend-v1",
) -> RunSignature:
    return RunSignature(
        root_identity=str(root.resolve()),
        collection_identity="source-v1",
        source_type=ContentKind.CODE,
        operation=RunOperation.FULL,
        clean=False,
        model_identity="model-v1",
        dense_dimensions=8,
        embedding_schema=2,
        payload_schema=3,
        content_epoch=content_epoch,
        membership_epoch="membership-v1",
        preprocessing_identity="preprocessing-v1",
        configuration_fingerprint="configuration-v1",
        policy_fingerprint="policy-v1",
        backend_identity=backend_identity,
    )


def test_run_signature_and_decoder_require_backend_identity() -> None:
    """Mutation: a default or missing-field fallback reopens old signatures."""
    backend_field = RunSignature.__dataclass_fields__["backend_identity"]
    assert backend_field.default is MISSING

    payload = json.loads(_signature(Path(".")).canonical_json)
    del payload["backend_identity"]
    with pytest.raises(TypeError, match="backend_identity"):
        _signature_from_payload(payload)


def _unit(
    path: str,
    ordinal: int,
    count: int,
    *,
    digest: str | None = None,
) -> CommitUnit:
    return CommitUnit(
        rel_path=path,
        kind=CommitUnitKind.UPSERT,
        source_digest=digest or _digest(path),
        segment_ordinal=ordinal,
        is_file_end=ordinal == count - 1,
        point_ids=(f"{path}:{ordinal}:0", f"{path}:{ordinal}:1"),
    )


def _proof_compatibility() -> ProofCompatibilityKey:
    return ProofCompatibilityKey(
        source_type=PublicSourceType.CODE,
        root_identity="root-v1",
        backend_identity="backend-v1",
        collection_identity="collection-v1",
        storage_schema=1,
        payload_schema=2,
        embedding_schema_identity="embedding-v1",
        chunking_schema_identity="chunking-v1",
        membership_identity="membership-v1",
        content_identity="content-v1",
        policy_identity="policy-v1",
    )


def _proof_key_for_signature(signature: RunSignature) -> ProofCompatibilityKey:
    return ProofCompatibilityKey(
        source_type=PublicSourceType(signature.source_type.value),
        root_identity=signature.root_identity,
        backend_identity=signature.backend_identity,
        collection_identity=signature.collection_identity,
        storage_schema=1,
        payload_schema=signature.payload_schema,
        embedding_schema_identity=(
            f"{signature.model_identity}:{signature.dense_dimensions}:"
            f"{signature.embedding_schema}"
        ),
        chunking_schema_identity=signature.preprocessing_identity,
        membership_identity=signature.membership_epoch,
        content_identity=signature.content_epoch,
        policy_identity=signature.policy_fingerprint,
    )


def _assert_rebuild_required_without_mutation(
    path: Path,
    *,
    match: str,
) -> None:
    before = path.read_bytes()
    companions = tuple(
        Path(f"{path}{suffix}") for suffix in ("-journal", "-shm", "-wal")
    )
    companion_bytes = {
        companion: companion.read_bytes() if companion.exists() else None
        for companion in companions
    }

    with pytest.raises(RunLedgerRebuildRequiredError, match=match) as caught:
        RunLedger(path)

    assert type(caught.value) is RunLedgerRebuildRequiredError
    assert path.read_bytes() == before
    assert {
        companion: companion.read_bytes() if companion.exists() else None
        for companion in companions
    } == companion_bytes


def _seed_publication_proof(
    ledger: RunLedger,
    *,
    generation_id: str,
    key: ProofCompatibilityKey,
    evidence: tuple[ProofEvidence, ...],
) -> None:
    connection = sqlite3.connect(ledger.path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO publication_proofs (
                source_type, root_identity, backend_identity,
                collection_identity, storage_schema, payload_schema,
                embedding_schema_identity, chunking_schema_identity,
                membership_identity, content_identity, policy_identity,
                generation_id, revision, reservation_sequence,
                indexed_identities, retained_points, provenance,
                committed_at, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key.source_type.value,
                key.root_identity,
                key.backend_identity,
                key.collection_identity,
                key.storage_schema,
                key.payload_schema,
                key.embedding_schema_identity,
                key.chunking_schema_identity,
                key.membership_identity,
                key.content_identity,
                key.policy_identity,
                generation_id,
                3,
                5,
                len(evidence),
                sum(len(item.point_ids) for item in evidence),
                ProofProvenance.VERIFIED.value,
                1.0,
                1.0,
            ),
        )
        for item in evidence:
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
                    item.rel_path,
                    item.content_identity,
                    generation_id,
                ),
            )
            connection.executemany(
                """
                INSERT INTO publication_points (
                    source_type, root_identity, backend_identity,
                    collection_identity, rel_path, point_ordinal, point_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        key.source_type.value,
                        key.root_identity,
                        key.backend_identity,
                        key.collection_identity,
                        item.rel_path,
                        ordinal,
                        point_id,
                    )
                    for ordinal, point_id in enumerate(item.point_ids)
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _seal_publication_receipt(
    ledger: RunLedger,
    receipt: PublicationReceipt,
    *,
    mutation: CommitUnit,
    delta: PathDelta,
) -> None:
    ledger.prepare_publication_mutation(receipt.receipt_id, mutation)
    ledger.mark_publication_mutation_applied(receipt.receipt_id, mutation)
    ledger.confirm_publication_mutation(receipt.receipt_id, mutation)
    ledger.seal_publication_receipt(receipt.receipt_id, (delta,))


def _insert_reserved_receipt(
    connection: sqlite3.Connection,
    *,
    receipt_id: str,
    reservation_sequence: int,
    generation_id: str,
    projection: tuple[str, int] = ("collection-v1", 1),
) -> None:
    key = _proof_compatibility()
    collection_identity, target_revision = projection
    connection.execute(
        """
        INSERT INTO publication_receipts (
            receipt_id, reservation_sequence, source_type, root_identity,
            backend_identity, collection_identity, storage_schema,
            payload_schema, embedding_schema_identity,
            chunking_schema_identity, membership_identity, content_identity,
            policy_identity, generation_id, parent_revision, target_revision,
            next_mutation_ordinal, state, reserved_at, sealed_at,
            rollback_started_at, committed_at, rolled_back_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?,
            0, 'reserved', 1.0, NULL, NULL, NULL, NULL
        )
        """,
        (
            receipt_id,
            reservation_sequence,
            key.source_type.value,
            key.root_identity,
            key.backend_identity,
            collection_identity,
            key.storage_schema,
            key.payload_schema,
            key.embedding_schema_identity,
            key.chunking_schema_identity,
            key.membership_identity,
            key.content_identity,
            key.policy_identity,
            generation_id,
            target_revision,
        ),
    )


def test_publication_generation_is_provenance_not_compatibility() -> None:
    key = _proof_compatibility()
    first = PublicationProof(
        revision=3,
        reservation_sequence=7,
        compatibility_key=key,
        generation_id="generation-a",
        aggregate=ProofAggregate(indexed_identities=1, retained_points=2),
        provenance=ProofProvenance.DELTA_DERIVED,
        committed_at=2.0,
    )
    second = replace(first, generation_id="generation-b", committed_at=3.0)

    assert first.compatibility_key == second.compatibility_key
    assert first.generation_id != second.generation_id
    assert not hasattr(key, "generation_id")


def test_streaming_mutations_advance_independently_before_receipt_sealing() -> None:
    prepared = PublicationMutationUnit(
        ordinal=0,
        unit=_unit("src/item.py", 0, 1),
        state=ProofMutationState.PREPARED,
        prepared_at=1.0,
    )
    applied = replace(
        prepared,
        state=ProofMutationState.APPLIED,
        applied_at=2.0,
    )
    confirmed = replace(
        applied,
        state=ProofMutationState.CONFIRMED,
        confirmed_at=3.0,
    )

    assert prepared.identity == applied.identity == confirmed.identity
    with pytest.raises(ValueError, match="timestamps must match"):
        replace(prepared, state=ProofMutationState.CONFIRMED, confirmed_at=3.0)
    with pytest.raises(ValueError, match="monotonic"):
        replace(applied, applied_at=0.5)


def test_receipt_reserves_streaming_work_then_seals_complete_deltas() -> None:
    """Mutation proving this can fail: omit sealed coverage or close at seal."""
    prepared = PublicationMutationUnit(
        ordinal=0,
        unit=_unit("src/item.py", 0, 1),
        state=ProofMutationState.PREPARED,
        prepared_at=2.0,
    )
    reserved = PublicationReceipt(
        receipt_id="receipt-v1",
        reservation_sequence=8,
        compatibility_key=_proof_compatibility(),
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
        unit=replace(sealed_prepared.unit, source_digest=_digest("other-content")),
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


def test_receipt_rejects_ambiguous_point_ownership_across_paths() -> None:
    """Mutation proving this can fail: omit receipt-wide point ownership checks."""
    shared_a = ProofEvidence(
        rel_path="src/a.py",
        content_identity=_digest("content-a"),
        point_ids=("shared-point",),
    )
    shared_b = ProofEvidence(
        rel_path="src/b.py",
        content_identity=_digest("content-b"),
        point_ids=("shared-point",),
    )

    def unit(kind: CommitUnitKind, evidence: ProofEvidence) -> CommitUnit:
        return CommitUnit(
            rel_path=evidence.rel_path,
            kind=kind,
            source_digest=(
                evidence.content_identity if kind is CommitUnitKind.UPSERT else None
            ),
            segment_ordinal=0,
            is_file_end=True,
            point_ids=evidence.point_ids,
        )

    def seal(
        deltas: tuple[PathDelta, ...], units: tuple[CommitUnit, ...]
    ) -> PublicationReceipt:
        prepared = tuple(
            PublicationMutationUnit(
                ordinal=ordinal,
                unit=value,
                state=ProofMutationState.PREPARED,
                prepared_at=1.5,
            )
            for ordinal, value in enumerate(units)
        )
        sealed_order = {
            mutation.identity: ordinal
            for ordinal, mutation in enumerate(
                sorted(prepared, key=lambda mutation: mutation.identity)
            )
        }
        mutations = tuple(
            replace(
                mutation,
                sealed_ordinal=sealed_order[mutation.identity],
            )
            for mutation in prepared
        )
        return PublicationReceipt(
            receipt_id="receipt-overlap",
            reservation_sequence=9,
            compatibility_key=_proof_compatibility(),
            generation_id="generation-v2",
            parent_revision=3,
            target_revision=4,
            state=ProofReceiptState.SEALED,
            reserved_at=1.0,
            mutations=mutations,
            deltas=deltas,
            sealed_at=2.0,
        )

    add_a = PathDelta(
        outcome=PathOutcome.ADD,
        expected_parent_revision=3,
        rel_path=shared_a.rel_path,
        new=shared_a,
    )
    add_b = PathDelta(
        outcome=PathOutcome.ADD,
        expected_parent_revision=3,
        rel_path=shared_b.rel_path,
        new=shared_b,
    )
    delete_a = PathDelta(
        outcome=PathOutcome.DELETE,
        expected_parent_revision=3,
        rel_path=shared_a.rel_path,
        old=shared_a,
    )
    delete_b = PathDelta(
        outcome=PathOutcome.DELETE,
        expected_parent_revision=3,
        rel_path=shared_b.rel_path,
        old=shared_b,
    )
    with pytest.raises(ValueError, match="multiple proof paths"):
        seal(
            (add_a, add_b),
            (
                unit(CommitUnitKind.UPSERT, shared_a),
                unit(CommitUnitKind.UPSERT, shared_b),
            ),
        )
    with pytest.raises(ValueError, match="multiple proof paths"):
        seal(
            (delete_a, delete_b),
            (
                unit(CommitUnitKind.DELETE_PATH, shared_a),
                unit(CommitUnitKind.DELETE_PATH, shared_b),
            ),
        )
    with pytest.raises(ValueError, match="transfer point identity"):
        seal(
            (delete_a, add_b),
            (
                unit(CommitUnitKind.DELETE_PATH, shared_a),
                unit(CommitUnitKind.UPSERT, shared_b),
            ),
        )


def test_publication_schema_separates_receipts_from_streaming_mutations() -> None:
    """Mutation proving this can fail: remove either normalized mutation table."""
    assert {
        "publication_mutation_units",
        "publication_mutation_points",
    } <= PUBLICATION_PROOF_SCHEMA.keys()
    assert {
        "reservation_sequence",
        "next_mutation_ordinal",
        "reserved_at",
        "sealed_at",
        "rollback_started_at",
        "committed_at",
        "rolled_back_at",
    } <= PUBLICATION_PROOF_SCHEMA["publication_receipts"]
    assert {
        "prepared_at",
        "applied_at",
        "confirmed_at",
        "sealed_ordinal",
        "state",
    } <= (PUBLICATION_PROOF_SCHEMA["publication_mutation_units"])
    assert "reservation_sequence" in PUBLICATION_PROOF_SCHEMA["publication_proofs"]
    assert "prepared_at" not in PUBLICATION_PROOF_SCHEMA["publication_receipts"]


def test_publication_ledger_schema_has_a_distinct_current_version() -> None:
    """Mutation: restoring the prior version would admit the old receipt format."""
    assert SCHEMA_VERSION == 9
    assert REQUIRED_INDEXES["publication_receipt_deltas_target"] == (
        "publication_receipt_deltas",
        ("receipt_id", "target_rel_path"),
        False,
        False,
    )


def test_run_ledger_installs_and_verifies_normalized_publication_schema(
    tmp_path: Path,
) -> None:
    """Mutation proving this can fail: omit a table or weaken an index."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    expected_tables = {
        "publication_proofs",
        "publication_evidence",
        "publication_points",
        "publication_receipts",
        "publication_mutation_units",
        "publication_mutation_points",
        "publication_receipt_deltas",
        "publication_receipt_points",
        "file_state_tombstones",
    }

    with sqlite3.connect(ledger.path) as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == (
            SCHEMA_VERSION
        )
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert expected_tables <= tables
        assert expected_tables == set(PUBLICATION_PROOF_SCHEMA)
        for table, expected_columns in PUBLICATION_PROOF_SCHEMA.items():
            actual_columns = {
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            assert expected_columns <= actual_columns
        receipt_columns = {
            str(row[1]): row
            for row in connection.execute('PRAGMA table_info("publication_receipts")')
        }
        assert bool(receipt_columns["receipt_id"][3])
        assert int(receipt_columns["receipt_id"][5]) == 1

        for name, (table, columns, unique, partial) in REQUIRED_INDEXES.items():
            index_row = next(
                row
                for row in connection.execute(f'PRAGMA index_list("{table}")')
                if str(row[1]) == name
            )
            actual_columns = tuple(
                str(row[2])
                for row in sorted(
                    connection.execute(f'PRAGMA index_info("{name}")'),
                    key=lambda row: int(row[0]),
                )
            )
            assert actual_columns == columns
            assert bool(index_row[2]) is unique
            assert bool(index_row[4]) is partial
            expected_predicate = REQUIRED_INDEX_PREDICATES.get(name)
            if expected_predicate is not None:
                definition = " ".join(
                    str(
                        connection.execute(
                            "SELECT sql FROM sqlite_master WHERE name = ?", (name,)
                        ).fetchone()[0]
                    )
                    .lower()
                    .split()
                )
                _prefix, separator, predicate = definition.partition(" where ")
                actual_predicate = f"where {predicate}" if separator else ""
                assert actual_predicate == expected_predicate

        assert {
            str(row[2])
            for row in connection.execute(
                'PRAGMA foreign_key_list("publication_evidence")'
            )
        } == {"generations", "publication_proofs"}
        assert {
            str(row[2])
            for row in connection.execute(
                'PRAGMA foreign_key_list("file_state_tombstones")'
            )
        } == {"generations"}


def _seeded_publication_lineage(
    tmp_path: Path,
    evidence: tuple[ProofEvidence, ...],
) -> tuple[RunLedger, ProofCompatibilityKey, str, str]:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = _signature(tmp_path)
    parent = ledger.start_generation(signature)
    _publish_and_compact(ledger, parent.generation_id)
    key = _proof_key_for_signature(signature)
    _seed_publication_proof(
        ledger,
        generation_id=parent.generation_id,
        key=key,
        evidence=evidence,
    )
    successor = ledger.start_generation(signature)
    assert successor.parent_generation_id == parent.generation_id
    return ledger, key, parent.generation_id, successor.generation_id


def test_generation_start_leaves_canonical_publication_projection_unchanged(
    tmp_path: Path,
) -> None:
    """Mutation: any canonical-table DML during generation start makes this red."""
    evidence = (
        ProofEvidence(
            rel_path="src/a.py",
            content_identity=_digest("a-v1"),
            point_ids=("point-a-0", "point-a-1"),
        ),
        ProofEvidence(
            rel_path="src/b.py",
            content_identity=_digest("b-v1"),
            point_ids=("point-b-0",),
        ),
    )
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = _signature(tmp_path)
    parent = ledger.start_generation(signature)
    _publish_and_compact(ledger, parent.generation_id)
    _seed_publication_proof(
        ledger,
        generation_id=parent.generation_id,
        key=_proof_key_for_signature(signature),
        evidence=evidence,
    )

    def canonical_projection() -> tuple[tuple[object, ...], ...]:
        with sqlite3.connect(ledger.path) as connection:
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
    with sqlite3.connect(ledger.path) as connection:
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
        with sqlite3.connect(ledger.path) as connection:
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
        content_identity=_digest("a-v1"),
        point_ids=("point-a-0", "point-a-1"),
    )
    second = ProofEvidence(
        rel_path="src/b.py",
        content_identity=_digest("b-v1"),
        point_ids=("point-b-0",),
    )
    ledger, key, parent_id, _successor_id = _seeded_publication_lineage(
        tmp_path,
        (first, second),
    )

    assert RunLedgerPublicationMethods in RunLedger.__mro__
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
        content_identity=_digest("a-v1"),
        point_ids=("point-a-old",),
    )
    old_b = ProofEvidence(
        rel_path="src/b.py",
        content_identity=_digest("b-v1"),
        point_ids=("point-b-old",),
    )
    untouched = ProofEvidence(
        rel_path="src/untouched.py",
        content_identity=_digest("untouched-v1"),
        point_ids=("point-untouched",),
    )
    ledger, key, _parent_id, successor_id = _seeded_publication_lineage(
        tmp_path,
        (old_a, old_b, untouched),
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=3,
    )

    replacement_digest = _digest("b-v2")
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
    with sqlite3.connect(ledger.path) as connection:
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
        content_identity=_digest("a-v1"),
        point_ids=("point-a",),
    )
    ledger, key, _parent_id, successor_id = _seeded_publication_lineage(
        tmp_path,
        (evidence,),
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=3,
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

    with sqlite3.connect(ledger.path) as connection:
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
    generation = ledger.start_generation(_signature(tmp_path))
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
    with sqlite3.connect(ledger.path) as connection:
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

    digest = _digest("replacement")
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        _unit(rel_path, 0, 1, digest=digest),
    )
    ledger.record_file_state(
        generation.generation_id,
        FileState.indexed(rel_path, ContentKind.CODE, digest),
    )
    with sqlite3.connect(ledger.path) as connection:
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


def test_publication_reservation_sequence_fences_open_and_rolled_back_receipts(
    tmp_path: Path,
) -> None:
    """Mutation proving this can fail: ignore the stored sequence at validation."""
    evidence = ProofEvidence(
        rel_path="src/a.py",
        content_identity=_digest("a-v1"),
        point_ids=("point-a",),
    )
    ledger, key, _parent_id, successor_id = _seeded_publication_lineage(
        tmp_path,
        (evidence,),
    )
    token = ledger.acquire_publication_read_token(key)

    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=token.revision,
    )
    assert receipt.reservation_sequence == token.reservation_sequence + 1
    assert ledger.active_publication_receipt(key) == receipt
    with pytest.raises(ProofReadConflictError):
        ledger.acquire_publication_read_token(key)
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
    current = ledger.acquire_publication_read_token(key)
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
    ledger, key, _parent_id, successor_id = _seeded_publication_lineage(tmp_path, ())
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=3,
    )
    unit = _unit("src/a.py", 0, 1)

    preparation_source = inspect.getsource(
        RunLedgerCommitMethods.prepare_publication_mutation
    ).lower()
    assert "count(*)" not in preparation_source
    assert "max(mutation_ordinal)" not in preparation_source

    prepared = ledger.prepare_publication_mutation(receipt.receipt_id, unit)
    assert prepared.state is ProofMutationState.PREPARED
    reopened = RunLedger(ledger.path)
    assert reopened.prepare_publication_mutation(receipt.receipt_id, unit) == prepared
    second = _unit("src/second.py", 0, 1)
    second_prepared = reopened.prepare_publication_mutation(
        receipt.receipt_id,
        second,
    )
    assert (prepared.ordinal, second_prepared.ordinal) == (0, 1)
    with sqlite3.connect(ledger.path) as connection:
        cursor = connection.execute(
            """
            SELECT next_mutation_ordinal FROM publication_receipts
            WHERE receipt_id = ?
            """,
            (receipt.receipt_id,),
        ).fetchone()
    assert cursor is not None and int(cursor[0]) == 2
    assert ledger.prepare_publication_mutation(receipt.receipt_id, unit) == prepared
    with sqlite3.connect(ledger.path) as connection:
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
            _unit("src/b.py", 0, 1),
        )


def test_publication_receipt_seal_is_exact_atomic_and_identity_ordered(
    tmp_path: Path,
) -> None:
    """Mutation: sealing partial point coverage makes this guard red."""
    ledger, key, _parent_id, successor_id = _seeded_publication_lineage(tmp_path, ())
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=3,
    )
    digest = _digest("a-v1")
    first = _unit("src/a.py", 0, 2, digest=digest)
    second = _unit("src/a.py", 1, 2, digest=digest)
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
            _unit("src/b.py", 0, 1),
        )


def test_publication_mutation_prepare_refuses_foreign_point_ownership(
    tmp_path: Path,
) -> None:
    """Mutation: deferring point-owner validation until seal makes this red."""
    owner = ProofEvidence(
        rel_path="src/owner.py",
        content_identity=_digest("owner"),
        point_ids=("owned-point",),
    )
    ledger, key, _parent_id, successor_id = _seeded_publication_lineage(
        tmp_path,
        (owner,),
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=3,
    )
    evidence = ProofEvidence(
        rel_path="src/new.py",
        content_identity=_digest("new"),
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
        content_identity=_digest("owner"),
        point_ids=("owner-original",),
    )
    ledger, key, _parent_id, successor_id = _seeded_publication_lineage(
        tmp_path,
        (owner,),
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=3,
    )
    evidence = ProofEvidence(
        rel_path="src/new.py",
        content_identity=_digest("new"),
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
    with sqlite3.connect(ledger.path) as connection:
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
    ledger, key, _parent_id, successor_id = _seeded_publication_lineage(tmp_path, ())
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=3,
    )
    unit = _unit("src/a.py", 0, 1)
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
    old = ProofEvidence(
        rel_path="src/a.py",
        content_identity=_digest("a-v1"),
        point_ids=("point-a-0", "point-a-1"),
    )
    untouched = ProofEvidence(
        rel_path="src/b.py",
        content_identity=_digest("b-v1"),
        point_ids=("point-b-0",),
    )
    ledger, key, _parent_id, successor_id = _seeded_publication_lineage(
        tmp_path,
        (old, untouched),
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=3,
    )
    new = replace(old, content_identity=_digest("a-v2"))
    delta = PathDelta(
        outcome=PathOutcome.MODIFY,
        expected_parent_revision=receipt.parent_revision,
        rel_path=old.rel_path,
        old=old,
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
    _seal_publication_receipt(
        ledger,
        receipt,
        mutation=mutation,
        delta=delta,
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


def test_late_receipt_transition_failure_rolls_back_the_entire_proof_commit(
    tmp_path: Path,
) -> None:
    """Mutation: committing evidence before the receipt transition makes this red."""
    old = ProofEvidence(
        rel_path="src/a.py",
        content_identity=_digest("a-v1"),
        point_ids=("point-a-old",),
    )
    ledger, key, _parent_id, successor_id = _seeded_publication_lineage(
        tmp_path,
        (old,),
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=3,
    )
    new = ProofEvidence(
        rel_path=old.rel_path,
        content_identity=_digest("a-v2"),
        point_ids=old.point_ids,
    )
    delta = PathDelta(
        outcome=PathOutcome.MODIFY,
        expected_parent_revision=receipt.parent_revision,
        rel_path=old.rel_path,
        old=old,
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
    _seal_publication_receipt(
        ledger,
        receipt,
        mutation=mutation,
        delta=delta,
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
    old = ProofEvidence(
        rel_path="src/a.py",
        content_identity=_digest("a-v1"),
        point_ids=("point-a-old",),
    )
    ledger, key, _parent_id, successor_id = _seeded_publication_lineage(
        tmp_path,
        (old,),
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=3,
    )
    new = ProofEvidence(
        rel_path=old.rel_path,
        content_identity=_digest("a-v2"),
        point_ids=old.point_ids,
    )
    delta = PathDelta(
        outcome=PathOutcome.MODIFY,
        expected_parent_revision=receipt.parent_revision,
        rel_path=old.rel_path,
        old=old,
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
    _seal_publication_receipt(
        ledger,
        receipt,
        mutation=mutation,
        delta=delta,
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
        content_identity=_digest("a-v1"),
        point_ids=("point-a",),
    )
    ledger, key, _parent_id, successor_id = _seeded_publication_lineage(
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
    wrong_old = replace(actual, content_identity=_digest("not-authoritative"))
    new = replace(actual, content_identity=_digest("a-v2"))
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
        _seal_publication_receipt(
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


def test_publication_schema_enforces_open_receipt_and_state_constraints(
    tmp_path: Path,
) -> None:
    """The durable schema rejects ambiguous or malformed receipt state."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))

    with sqlite3.connect(ledger.path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _insert_reserved_receipt(
            connection,
            receipt_id="receipt-one",
            reservation_sequence=1,
            generation_id=generation.generation_id,
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            _insert_reserved_receipt(
                connection,
                receipt_id="receipt-two",
                reservation_sequence=2,
                generation_id=generation.generation_id,
            )

        connection.execute(
            """
            UPDATE publication_receipts
            SET state = 'rolling_back', rollback_started_at = 2.0
            WHERE receipt_id = 'receipt-one'
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_reserved_receipt(
                connection,
                receipt_id="receipt-two",
                reservation_sequence=2,
                generation_id=generation.generation_id,
            )
        connection.execute(
            """
            UPDATE publication_receipts
            SET state = 'rolled_back', rolled_back_at = 3.0
            WHERE receipt_id = 'receipt-one'
            """
        )
        _insert_reserved_receipt(
            connection,
            receipt_id="receipt-two",
            reservation_sequence=2,
            generation_id=generation.generation_id,
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            _insert_reserved_receipt(
                connection,
                receipt_id="wrong-revision",
                reservation_sequence=1,
                generation_id=generation.generation_id,
                projection=("other-collection", 2),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO publication_mutation_units (
                    receipt_id, mutation_ordinal, sealed_ordinal, unit_id,
                    rel_path, unit_kind, source_digest, segment_ordinal,
                    is_file_end, state, prepared_at, applied_at, confirmed_at
                ) VALUES (
                    'receipt-two', 0, NULL, 'unit-one', 'src/item.py',
                    'upsert', ?, 0, 1, 'confirmed', 2.0, NULL, 3.0
                )
                """,
                (_digest("item"),),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO file_state_tombstones (generation_id, rel_path)
                VALUES ('missing-generation', 'src/deleted.py')
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO publication_receipt_deltas (
                    receipt_id, delta_ordinal, outcome, rel_path,
                    target_rel_path, old_content_identity, new_content_identity
                ) VALUES (
                    'receipt-two', 0, 'modify', 'src/item.py',
                    NULL, 'same-content', 'same-content'
                )
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO publication_receipt_deltas (
                    receipt_id, delta_ordinal, outcome, rel_path,
                    target_rel_path, old_content_identity, new_content_identity
                ) VALUES (
                    'receipt-two', 1, 'noop', 'src/item.py',
                    NULL, 'old-content', 'new-content'
                )
                """
            )


@pytest.mark.parametrize("schema_version", [6, 7, 8])
def test_old_ledger_format_requires_rebuild_without_mutation(
    tmp_path: Path,
    schema_version: int,
) -> None:
    """Mutation: requesting WAL before the version gate mutates this database."""
    path = tmp_path / "runs.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE old_runs (value TEXT NOT NULL)")
        connection.execute("INSERT INTO old_runs VALUES ('preserve-me')")
        connection.execute(f"PRAGMA user_version = {schema_version}")
        connection.commit()

    _assert_rebuild_required_without_mutation(path, match="not supported")


def test_live_wal_old_ledger_requires_rebuild_without_sidecar_mutation(
    tmp_path: Path,
) -> None:
    """Mutation: writable preflight changes shared-memory state before refusal."""
    path = tmp_path / "runs.sqlite3"
    peer = sqlite3.connect(path)
    try:
        assert peer.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        peer.execute("CREATE TABLE old_runs (value TEXT NOT NULL)")
        peer.execute("INSERT INTO old_runs VALUES ('preserve-me')")
        peer.execute("PRAGMA user_version = 6")
        peer.commit()

        _assert_rebuild_required_without_mutation(path, match="rebuild")
    finally:
        peer.close()


def test_nonempty_schema_zero_requires_rebuild_without_mutation(tmp_path: Path) -> None:
    """Mutation: treating every schema-zero database as fresh overwrites its shape."""
    path = tmp_path / "runs.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE foreign_state (value TEXT NOT NULL)")
        connection.execute("INSERT INTO foreign_state VALUES ('preserve-me')")
        connection.commit()

    _assert_rebuild_required_without_mutation(path, match="nonempty pre-proof")


def test_fresh_schema_creation_is_atomic_and_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation: autocommitted schema scripts leave a partial version-zero file."""
    path = tmp_path / "runs.sqlite3"
    create_publication_tables = RunLedger._create_publication_tables

    def fail_after_publication_tables(connection: sqlite3.Connection) -> None:
        create_publication_tables(connection)
        raise RuntimeError("injected schema-creation interruption")

    with monkeypatch.context() as patch:
        patch.setattr(
            RunLedger,
            "_create_publication_tables",
            staticmethod(fail_after_publication_tables),
        )
        with pytest.raises(RuntimeError, match="injected schema-creation interruption"):
            RunLedger(path)

    with sqlite3.connect(path) as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 0
        assert connection.execute("SELECT name FROM sqlite_master").fetchall() == []

    ledger = RunLedger(path)
    with sqlite3.connect(ledger.path) as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == (
            SCHEMA_VERSION
        )


def _open_concurrent_fresh_ledgers(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[RunLedger], list[BaseException], tuple[threading.Thread, ...]]:
    create_base_tables = RunLedger._create_base_tables
    require_schema = RunLedger._require_current_or_empty_schema
    first_base_created = threading.Event()
    release_first_creator = threading.Event()
    second_preflight_finished = threading.Event()
    first_call = True
    call_lock = threading.Lock()
    ledgers: list[RunLedger] = []
    errors: list[BaseException] = []

    def blocking_create_base_tables(connection: sqlite3.Connection) -> None:
        nonlocal first_call
        create_base_tables(connection)
        with call_lock:
            should_block = first_call
            first_call = False
        if should_block:
            first_base_created.set()
            assert release_first_creator.wait(PROCESS_TIMEOUT_SECONDS)

    def tracked_require_schema(
        self: RunLedger,
        connection: sqlite3.Connection,
    ) -> None:
        try:
            require_schema(self, connection)
        finally:
            if threading.current_thread().name == "second-schema-opener":
                second_preflight_finished.set()

    def open_ledger() -> None:
        try:
            ledgers.append(RunLedger(path))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    with monkeypatch.context() as patch:
        patch.setattr(
            RunLedger,
            "_create_base_tables",
            staticmethod(blocking_create_base_tables),
        )
        patch.setattr(
            RunLedger, "_require_current_or_empty_schema", tracked_require_schema
        )
        first = threading.Thread(target=open_ledger, name="first-schema-opener")
        second = threading.Thread(target=open_ledger, name="second-schema-opener")
        first.start()
        try:
            assert first_base_created.wait(PROCESS_TIMEOUT_SECONDS)
            second.start()
            assert second_preflight_finished.wait(PROCESS_TIMEOUT_SECONDS)
        finally:
            release_first_creator.set()
        first.join(PROCESS_TIMEOUT_SECONDS)
        second.join(PROCESS_TIMEOUT_SECONDS)

    return ledgers, errors, (first, second)


def test_concurrent_fresh_schema_openers_observe_only_empty_or_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation: removing the creation transaction exposes a partial schema."""
    path = tmp_path / "runs.sqlite3"
    ledgers, errors, (first, second) = _open_concurrent_fresh_ledgers(
        path,
        monkeypatch,
    )

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert len(ledgers) == 2
    with sqlite3.connect(path) as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == (
            SCHEMA_VERSION
        )


def test_existing_empty_file_receives_the_exact_current_schema(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite3"
    path.touch()

    ledger = RunLedger(path)

    with sqlite3.connect(ledger.path) as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == (
            SCHEMA_VERSION
        )
        tables = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            )
        }
    assert tables == set(REQUIRED_SCHEMA)


def test_open_refuses_a_preexisting_incompatible_publication_index(
    tmp_path: Path,
) -> None:
    """Mutation proving this can fail: skip exact current-index verification."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("DROP INDEX publication_receipts_open")
        connection.execute(
            """
            CREATE UNIQUE INDEX publication_receipts_open
            ON publication_receipts(
                source_type, root_identity, backend_identity,
                collection_identity
            ) WHERE state = 'committed'
            """
        )
        connection.commit()

    _assert_rebuild_required_without_mutation(ledger.path, match="does not match")


def test_open_refuses_a_preexisting_publication_table_without_constraints(
    tmp_path: Path,
) -> None:
    """Mutation proving this can fail: skip exact table-definition verification."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TABLE file_state_tombstones")
        connection.execute(
            """
            CREATE TABLE file_state_tombstones (
                generation_id TEXT,
                rel_path TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX file_state_tombstones_path
            ON file_state_tombstones(rel_path, generation_id)
            """
        )
        connection.commit()

    _assert_rebuild_required_without_mutation(ledger.path, match="does not match")


def test_open_refuses_unexpected_current_schema_objects_without_mutation(
    tmp_path: Path,
) -> None:
    """Mutation: checking only required names admits a second durable authority."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("CREATE TABLE shadow_proof (value TEXT NOT NULL)")
        connection.commit()

    _assert_rebuild_required_without_mutation(ledger.path, match="unexpected tables")


@pytest.mark.parametrize(
    "ddl",
    [
        """
        CREATE VIEW shadow_proof_view AS
        SELECT generation_id FROM publication_proofs
        """,
        """
        CREATE TRIGGER shadow_proof_trigger
        AFTER INSERT ON publication_proofs
        BEGIN
            SELECT 1;
        END
        """,
    ],
    ids=["view", "trigger"],
)
def test_open_refuses_unexpected_schema_authorities_without_mutation(
    tmp_path: Path,
    ddl: str,
) -> None:
    """Mutation: ignoring views or triggers admits another durable authority."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute(ddl)
        connection.commit()

    _assert_rebuild_required_without_mutation(ledger.path, match="unexpected objects")


def test_backend_identity_is_part_of_manifest_compatibility(tmp_path: Path) -> None:
    server = _signature(tmp_path)
    local = _signature(
        tmp_path,
        backend_identity=f"qdrant-local:{tmp_path.resolve()}",
    )

    assert server.content_compatibility_fingerprint != (
        local.content_compatibility_fingerprint
    )


def test_generation_transactions_resume_and_invalidate_drift(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "index" / "runs.sqlite3")
    signature = _signature(tmp_path)

    first = ledger.start_generation(signature)
    resumed = ledger.start_generation(signature)
    assert resumed.generation_id == first.generation_id
    assert resumed.signature == signature

    replacement = ledger.start_generation(
        replace(signature, content_epoch="content-v2")
    )
    assert replacement.generation_id != first.generation_id
    invalidated = ledger.generation(first.generation_id)
    assert invalidated.terminal_state is RunTerminalState.INVALIDATED
    assert invalidated.terminal_detail == "generation signature changed"

    unit = _unit("src/resume.py", 0, 1)
    ledger.record_storage_confirmed_unit(replacement.generation_id, unit)
    ledger.finish_generation(
        replacement.generation_id,
        RunTerminalState.CANCELLED,
        detail="operator requested cancellation",
    )
    retry = ledger.start_generation(replacement.signature)
    assert retry.generation_id == replacement.generation_id
    assert retry.terminal_state is RunTerminalState.RUNNING
    assert retry.terminal_detail is None
    assert ledger.unit_committed(retry.generation_id, unit)

    clean_signature = replace(
        replacement.signature,
        clean=True,
        content_epoch="clean-replacement",
    )
    clean = ledger.start_generation(clean_signature)
    ledger.finish_generation(
        clean.generation_id,
        RunTerminalState.REBUILD_INCOMPLETE,
        detail="replacement interrupted",
    )
    resumed_clean = ledger.start_generation(clean_signature)
    assert resumed_clean.generation_id == clean.generation_id
    assert resumed_clean.destructive_intent


def test_shared_path_and_latest_generation_are_independent_per_kind(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    assert index_run_ledger_path(data_root) == data_root / INDEX_RUN_LEDGER_FILENAME
    ledger = RunLedger(index_run_ledger_path(data_root))
    code = ledger.start_generation(_signature(tmp_path))
    document = ledger.start_generation(
        replace(
            _signature(tmp_path),
            source_type=ContentKind.DOCUMENT,
            collection_identity="document-v1",
        )
    )

    assert ledger.latest_generation(ContentKind.CODE) == code
    assert (
        ledger.latest_generation(
            ContentKind.DOCUMENT,
            collection_identity="document-v1",
        )
        == document
    )


def test_commit_units_are_atomic_idempotent_and_row_streamed(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    digest = _digest("large-source")
    units = [_unit("src/large.py", ordinal, 3, digest=digest) for ordinal in range(3)]

    assert ledger.record_storage_confirmed_unit(generation.generation_id, units[0])
    assert not ledger.record_storage_confirmed_unit(generation.generation_id, units[0])
    assert not ledger.file_complete(generation.generation_id, "src/large.py")
    for unit in units[1:]:
        assert ledger.record_storage_confirmed_unit(generation.generation_id, unit)
    assert ledger.file_complete(generation.generation_id, "src/large.py")
    assert list(ledger.iter_units(generation.generation_id, batch_size=1)) == units

    conflicting = _unit("src/large.py", 0, 3, digest=_digest("different"))
    with pytest.raises(RunLedgerStateError, match="source digest"):
        ledger.record_storage_confirmed_unit(generation.generation_id, conflicting)
    assert list(ledger.iter_units(generation.generation_id)) == units
    duplicate_point = CommitUnit(
        rel_path="src/duplicate.py",
        kind=CommitUnitKind.UPSERT,
        source_digest=_digest("duplicate"),
        segment_ordinal=0,
        is_file_end=True,
        point_ids=(units[0].point_ids[0],),
    )
    with pytest.raises(RunLedgerStateError, match="point identity"):
        ledger.record_storage_confirmed_unit(
            generation.generation_id,
            duplicate_point,
        )
    assert list(ledger.iter_point_ids(generation.generation_id, batch_size=2)) == [
        point_id for unit in units for point_id in unit.point_ids
    ]

    deletion = CommitUnit(
        rel_path="src/removed.py",
        kind=CommitUnitKind.DELETE_PATH,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("removed-point",),
    )
    assert ledger.record_storage_confirmed_unit(generation.generation_id, deletion)
    assert ledger.file_complete(generation.generation_id, deletion.rel_path)


def test_file_outcomes_and_finalization_are_immutable(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    indexed = FileState.indexed("src/good.py", ContentKind.CODE, _digest("good"))
    rejected = FileState.policy_rejected(
        "notes/readme.md",
        AdmissionDisposition(
            kind=None,
            admitted=False,
            reason=AdmissionReason.SOURCE_PROFILE_EXCLUDED,
        ),
    )
    failed = FileState.failed(
        "src/bad.py",
        FileStateKind.DECODE_FAILED,
        ContentKind.CODE,
        "invalid source encoding",
        content_hash=_digest("bad"),
    )
    with pytest.raises(RunLedgerStateError, match="storage-confirmed"):
        ledger.record_file_state(generation.generation_id, indexed)
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        _unit("src/good.py", 0, 1, digest=indexed.content_hash),
    )
    wrong_hash = replace(indexed, content_hash=_digest("different-good"))
    with pytest.raises(RunLedgerStateError, match="hash differs"):
        ledger.record_file_state(generation.generation_id, wrong_hash)
    for state in (indexed, rejected, failed):
        ledger.record_file_state(generation.generation_id, state)
    good_point_ids = _unit(
        "src/good.py",
        0,
        1,
        digest=indexed.content_hash,
    ).point_ids
    assert ledger.retained_point_ids_for_candidates(
        generation.generation_id,
        (*good_point_ids, "not-in-the-generation"),
    ) == frozenset(good_point_ids)
    with pytest.raises(RunLedgerStateError, match="path is indexed"):
        ledger.record_storage_confirmed_unit(
            generation.generation_id,
            _unit("src/good.py", 1, 2, digest=indexed.content_hash),
        )

    assert list(ledger.iter_file_states(generation.generation_id, batch_size=1)) == [
        rejected,
        failed,
        indexed,
    ]
    assert list(
        ledger.iter_file_states(generation.generation_id, converged_only=True)
    ) == [rejected, indexed]

    with pytest.raises(RunLedgerStateError, match="unresolved"):
        ledger.advance_finalization(
            generation.generation_id,
            FinalizationPhase.STALE_RECONCILED,
        )
    assert failed.content_hash is not None
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        _unit("src/bad.py", 0, 1, digest=failed.content_hash),
    )
    ledger.record_file_state(
        generation.generation_id,
        FileState.indexed("src/bad.py", ContentKind.CODE, failed.content_hash),
    )

    with pytest.raises(RunLedgerStateError, match="cannot advance"):
        ledger.advance_finalization(
            generation.generation_id,
            FinalizationPhase.METADATA_PUBLISHED,
        )
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        advanced = ledger.advance_finalization(generation.generation_id, phase)
        assert advanced.finalization_phase is phase
        if phase is FinalizationPhase.STALE_RECONCILED:
            with pytest.raises(RunLedgerStateError, match="finalization begins"):
                ledger.record_file_state(generation.generation_id, failed)
    with pytest.raises(RunLedgerStateError, match=r"only compact\(\)"):
        ledger.advance_finalization(
            generation.generation_id,
            FinalizationPhase.COMPACTED,
        )

    completed = ledger.finish_generation(
        generation.generation_id,
        RunTerminalState.SUCCEEDED,
    )
    assert completed.complete
    with pytest.raises(RunLedgerStateError, match="immutable"):
        ledger.record_file_state(generation.generation_id, failed)
    assert (
        ledger.finish_generation(
            generation.generation_id,
            RunTerminalState.SUCCEEDED,
        )
        == completed
    )


def _indexed_path_ledger(tmp_path: Path, digest: str) -> tuple[RunLedger, str]:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        _unit("src/drift.py", 0, 1, digest=digest),
    )
    ledger.record_file_state(
        generation.generation_id,
        FileState.indexed("src/drift.py", ContentKind.CODE, digest),
    )
    return ledger, generation.generation_id


# Both guard tests below were proven able to fail, by deleting the indexed-path
# branch of ``_record_storage_confirmed_unit`` outright, running them alone,
# observing the failures recorded here, restoring, and observing them pass.
#
# What the removal does NOT produce is a permitted write, and a reader who
# expects "DID NOT RAISE" will wrongly conclude these tests are vacuous. An
# indexed file state is only accepted when storage-confirmed upsert units for
# the same digest already exist (``record_file_state``), so a drifted upsert
# onto an indexed path always also violates "segments for one path must share
# one source digest". The two branches overlap on this input by construction,
# and the indexed-path branch exists to win that race and answer with a *typed*
# error the drift repair can act on.
#
# So the assertion that carries the guard is the type, and both directions land
# there:
#   - guard removed: the sibling-digest branch refuses instead, and
#     ``RunLedgerStateError('segments for one path must share one source
#     digest')`` escapes ``pytest.raises(RunLedgerIndexedPathCollisionError)``
#     in the first test and fails ``isinstance`` - the second test's own named
#     assertion - in the second.
#   - guard restored: both pass.
#
# Never relax these to catch the base class or to match on the message. A
# message-based matcher passes whichever branch fires, which is exactly the
# distinction the dedicated type was introduced to make.
def test_upsert_onto_an_indexed_path_raises_the_dedicated_collision(
    tmp_path: Path,
) -> None:
    indexed_digest = _digest("original")
    ledger, generation_id = _indexed_path_ledger(tmp_path, indexed_digest)

    edited_digest = _digest("edited")
    # The exact type is the assertion. A caller must be able to separate this
    # repairable condition - a file edited while the run that indexed it was
    # still going - from a genuinely broken generation invariant, and the base
    # state error carries no way to tell them apart.
    with pytest.raises(RunLedgerIndexedPathCollisionError) as drifted:
        ledger.record_storage_confirmed_unit(
            generation_id,
            _unit("src/drift.py", 1, 2, digest=edited_digest),
        )
    error = drifted.value
    assert type(error) is RunLedgerIndexedPathCollisionError
    assert error.generation_id == generation_id
    assert error.rel_path == "src/drift.py"
    assert error.indexed_digest == indexed_digest
    assert error.unit_digest == edited_digest
    assert error.is_drift

    with pytest.raises(RunLedgerIndexedPathCollisionError) as resubmitted:
        ledger.record_storage_confirmed_unit(
            generation_id,
            _unit("src/drift.py", 1, 2, digest=indexed_digest),
        )
    assert not resubmitted.value.is_drift


def test_indexed_path_collision_stays_catchable_as_a_state_error(
    tmp_path: Path,
) -> None:
    indexed_digest = _digest("original")
    ledger, generation_id = _indexed_path_ledger(tmp_path, indexed_digest)

    # Handlers written against the base class predate the dedicated type and
    # must keep intercepting the collision unchanged.
    try:
        ledger.record_storage_confirmed_unit(
            generation_id,
            _unit("src/drift.py", 1, 2, digest=_digest("edited")),
        )
    except RunLedgerStateError as caught:
        assert isinstance(caught, RunLedgerIndexedPathCollisionError)
        assert "path is indexed" in str(caught)
    else:  # pragma: no cover - the guard above always raises
        pytest.fail("recording an upsert onto an indexed path must be refused")


def test_compaction_preserves_published_and_running_generations(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    first = ledger.start_generation(_signature(tmp_path, content_epoch="first"))
    second = ledger.start_generation(_signature(tmp_path, content_epoch="second"))
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(second.generation_id, phase)
    ledger.finish_generation(second.generation_id, RunTerminalState.SUCCEEDED)

    document = replace(
        _signature(tmp_path),
        source_type=ContentKind.DOCUMENT,
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


def test_schema_compatibility_and_corruption_fail_closed(tmp_path: Path) -> None:
    incompatible = tmp_path / "incompatible.sqlite3"
    connection = sqlite3.connect(incompatible)
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    with pytest.raises(RunLedgerCompatibilityError, match="not supported"):
        RunLedger(incompatible)

    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")
    with pytest.raises(RunLedgerCorruptionError, match="cannot open"):
        RunLedger(corrupt)

    logical = RunLedger(tmp_path / "logical.sqlite3")
    generation = logical.start_generation(_signature(tmp_path))
    connection = sqlite3.connect(logical.path)
    connection.execute(
        "UPDATE generations SET signature_json = ? WHERE generation_id = ?",
        (
            generation.signature.canonical_json.replace("content-v1", "tampered"),
            generation.generation_id,
        ),
    )
    connection.commit()
    connection.close()
    with pytest.raises(RunLedgerCorruptionError, match="signature"):
        logical.start_generation(generation.signature)

    incomplete_path = tmp_path / "incomplete.sqlite3"
    RunLedger(incomplete_path)
    connection = sqlite3.connect(incomplete_path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("DROP TABLE file_states")
    connection.close()
    with pytest.raises(RunLedgerCompatibilityError, match="missing tables"):
        RunLedger(incomplete_path)

    malformed = RunLedger(tmp_path / "malformed.sqlite3")
    malformed_generation = malformed.start_generation(_signature(tmp_path))
    connection = sqlite3.connect(malformed.path)
    connection.execute(
        "UPDATE generations SET terminal_state = 'unknown' WHERE generation_id = ?",
        (malformed_generation.generation_id,),
    )
    connection.commit()
    connection.close()
    with pytest.raises(RunLedgerCorruptionError, match="generation"):
        malformed.generation(malformed_generation.generation_id)


def test_commit_unit_point_ids_of_the_wrong_type_read_as_corruption(
    tmp_path: Path,
) -> None:
    """A stored point identity that is not a string is a detected corruption.

    Integers are the escaping class specifically: `CommitUnit.__post_init__`
    already rejects a falsy entry, so a stored `null` or `""` is caught
    incidentally by that emptiness rule and proves nothing about the entry
    types. A list of non-empty integers satisfies every invariant the unit
    checks - truthy, unique, orderable - and, without an entry check, reaches
    the store as point identities of the wrong type.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    unit = _unit("src/a.py", 0, 1)
    ledger.record_storage_confirmed_unit(generation.generation_id, unit)

    connection = sqlite3.connect(ledger.path)
    connection.execute(
        "UPDATE commit_units SET point_ids_json = ? WHERE generation_id = ?",
        ('["src/a.py:0:0",7]', generation.generation_id),
    )
    connection.commit()
    connection.close()

    with pytest.raises(RunLedgerCorruptionError, match="malformed"):
        list(ledger.iter_units(generation.generation_id))


def test_well_formed_commit_unit_point_ids_still_read_back_exactly(
    tmp_path: Path,
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    unit = _unit("src/a.py", 0, 1)
    ledger.record_storage_confirmed_unit(generation.generation_id, unit)

    assert list(ledger.iter_units(generation.generation_id)) == [unit]


def test_bounded_iterator_does_not_hold_a_writer_transaction(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    first = _unit("src/a.py", 0, 1)
    second = _unit("src/b.py", 0, 1)
    ledger.record_storage_confirmed_unit(generation.generation_id, first)
    ledger.record_storage_confirmed_unit(generation.generation_id, second)

    rows = ledger.iter_units(generation.generation_id, batch_size=1)
    assert next(rows) == first
    third = _unit("src/c.py", 0, 1)
    assert ledger.record_storage_confirmed_unit(generation.generation_id, third)
    assert list(rows) == [second, third]


def test_incremental_manifest_carries_forward_and_deletes_exact_paths(
    tmp_path: Path,
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    full = ledger.start_generation(_signature(tmp_path))
    hashes = {path: _digest(path) for path in ("src/a.py", "src/b.py")}
    for path, content_hash in hashes.items():
        ledger.record_storage_confirmed_unit(
            full.generation_id,
            _unit(path, 0, 1, digest=content_hash),
        )
        ledger.record_file_state(
            full.generation_id,
            FileState.indexed(path, ContentKind.CODE, content_hash),
        )
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(full.generation_id, phase)
    ledger.finish_generation(full.generation_id, RunTerminalState.SUCCEEDED)

    incremental_signature = replace(
        full.signature,
        operation=RunOperation.INCREMENTAL,
        configuration_fingerprint="configuration-v2",
    )
    incremental = ledger.start_generation(incremental_signature)
    assert incremental.parent_generation_id == full.generation_id
    assert [
        state.rel_path for state in ledger.iter_file_states(incremental.generation_id)
    ] == ["src/a.py", "src/b.py"]

    deletion = CommitUnit(
        rel_path="src/a.py",
        kind=CommitUnitKind.DELETE_PATH,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("old-a",),
    )
    ledger.record_storage_confirmed_unit(incremental.generation_id, deletion)
    with pytest.raises(RunLedgerStateError, match="retained in the manifest"):
        ledger.advance_finalization(
            incremental.generation_id,
            FinalizationPhase.STALE_RECONCILED,
        )
    ledger.record_path_deleted(incremental.generation_id, "src/a.py")
    assert [
        state.rel_path for state in ledger.iter_file_states(incremental.generation_id)
    ] == ["src/b.py"]

    replacement_hash = _digest("new-b")
    first_segment = _unit("src/b.py", 0, 2, digest=replacement_hash)
    ledger.record_storage_confirmed_unit(incremental.generation_id, first_segment)
    with pytest.raises(RunLedgerStateError, match="incomplete"):
        ledger.advance_finalization(
            incremental.generation_id,
            FinalizationPhase.STALE_RECONCILED,
        )
    ledger.record_storage_confirmed_unit(
        incremental.generation_id,
        _unit("src/b.py", 1, 2, digest=replacement_hash),
    )
    ledger.record_file_state(
        incremental.generation_id,
        FileState.indexed("src/b.py", ContentKind.CODE, replacement_hash),
    )
    stale_deletion = CommitUnit(
        rel_path="src/b.py",
        kind=CommitUnitKind.DELETE_STALE,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("superseded-b",),
    )
    assert ledger.record_storage_confirmed_unit(
        incremental.generation_id,
        stale_deletion,
    )
    assert [
        state.content_hash
        for state in ledger.iter_file_states(incremental.generation_id)
    ] == [replacement_hash]
    assert list(
        ledger.iter_retained_point_ids(incremental.generation_id, batch_size=1)
    ) == [
        point_id
        for ordinal in range(2)
        for point_id in _unit(
            "src/b.py",
            ordinal,
            2,
            digest=replacement_hash,
        ).point_ids
    ]


def test_retained_point_iteration_stays_on_index_seeks(tmp_path: Path) -> None:
    """Guard: the retained-point walk must never scan a generation's points.

    The ledger never runs ANALYZE, so no ``sqlite_stat1`` table exists and
    the planner works from default estimates. Under those estimates the
    plain-JOIN form of the retained-point query visits ``commit_point_ids``
    before ``commit_units``, reachable only by ``generation_id`` - a scan of
    every committed point in the generation for every file row, re-sorted
    through a temp B-tree, repeated per keyset batch. On a corpus of tens of
    thousands of points that turns a sub-second walk into minutes of CPU
    while the writer lock is held. The pinned join order keeps every batch
    on index seeks; this test asserts the plan properties that pinning
    guarantees, on a ledger built through the production API so the
    statistics conditions match production exactly.

    Failure direction proven: replacing both CROSS JOINs with plain JOINs
    in the SQL this test imports makes the keyset-batch plan reach
    ``commit_point_ids`` without the ``unit_id`` seek and adds a temp
    B-tree, failing the seek assertion below; restoring CROSS JOIN makes
    it pass again.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    full = ledger.start_generation(_signature(tmp_path))
    for path in ("src/a.py", "src/b.py"):
        content_hash = _digest(path)
        ledger.record_storage_confirmed_unit(
            full.generation_id,
            _unit(path, 0, 1, digest=content_hash),
        )
        ledger.record_file_state(
            full.generation_id,
            FileState.indexed(path, ContentKind.CODE, content_hash),
        )
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(full.generation_id, phase)
    ledger.finish_generation(full.generation_id, RunTerminalState.SUCCEEDED)
    incremental = ledger.start_generation(
        replace(full.signature, operation=RunOperation.INCREMENTAL)
    )

    # The carried manifest must actually flow through the pinned query.
    assert list(ledger.iter_retained_point_ids(incremental.generation_id)) == [
        point_id
        for path in ("src/a.py", "src/b.py")
        for point_id in _unit(path, 0, 1, digest=_digest(path)).point_ids
    ]

    connection = sqlite3.connect(ledger.path)
    try:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'sqlite_stat1'"
            ).fetchone()
            is None
        ), "ANALYZE ran; the planner conditions this guard exists for are gone"
        plan = [
            str(row[3])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN "
                + retained_point_ids_sql(scoped_to_path=False, keyset=True),
                (
                    CommitUnitKind.UPSERT.value,
                    incremental.generation_id,
                    FileStateKind.INDEXED.value,
                    "src/a.py",
                    0,
                    1,
                    "src/a.py:0:1",
                    FETCH_BATCH,
                ),
            )
        ]
    finally:
        connection.close()

    points_steps = [step for step in plan if "commit_point_ids" in step]
    assert points_steps, f"plan named no commit_point_ids access: {plan}"
    # The degenerate plan reads 'USING INDEX ..._2 (generation_id=?)':
    # a per-file scan of the whole generation's points. The pinned plan
    # must seek the point primary key on both join columns.
    assert all("unit_id=?" in step for step in points_steps), plan
    assert not any("TEMP B-TREE" in step.upper() for step in plan), plan


def test_metadata_publication_streams_only_converged_ledger_rows(
    tmp_path: Path,
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    content_hash = _digest("published")
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        _unit("src/published.py", 0, 1, digest=content_hash),
    )
    ledger.record_file_state(
        generation.generation_id,
        FileState.indexed("src/published.py", ContentKind.CODE, content_hash),
    )
    ledger.record_file_state(
        generation.generation_id,
        FileState.policy_rejected(
            "notes/ignored.md",
            AdmissionDisposition(
                kind=None,
                admitted=False,
                reason=AdmissionReason.IGNORED,
            ),
        ),
    )
    meta_path = tmp_path / "code_meta.json"
    assert (
        publish_meta_from_file_states(
            meta_path,
            ledger.iter_file_states(
                generation.generation_id,
                converged_only=True,
                batch_size=1,
            ),
            generation_id=generation.generation_id,
            membership_epoch="membership-v1",
            content_epoch="content-v1",
            published_points_count=1,
        )
        == 1
    )
    assert load_meta(meta_path) == {"src/published.py": content_hash}
    raw = read_meta_raw(meta_path)
    assert raw[GENERATION_ID_KEY] == generation.generation_id
    assert raw[MEMBERSHIP_EPOCH_KEY] == "membership-v1"
    assert raw[CONTENT_EPOCH_KEY] == "content-v1"

    ledger.record_file_state(
        generation.generation_id,
        FileState.failed(
            "src/unresolved.py",
            FileStateKind.CHUNK_FAILED,
            ContentKind.CODE,
            "chunking failed",
            content_hash=_digest("unresolved"),
        ),
    )
    before = meta_path.read_bytes()
    with pytest.raises(ValueError, match="unresolved"):
        publish_meta_from_file_states(
            meta_path,
            ledger.iter_file_states(generation.generation_id),
            generation_id=generation.generation_id,
            membership_epoch="membership-v1",
            content_epoch="content-v1",
            published_points_count=1,
        )
    assert meta_path.read_bytes() == before


def test_overlapping_metadata_publications_are_each_atomic(tmp_path: Path) -> None:
    meta_path = tmp_path / "code_meta.json"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def states(prefix: str):
        # Both publishers must reach the rendezvous or the barrier breaks and
        # the failure surfaces as a BrokenBarrierError rather than as anything
        # about atomicity. Five seconds was a hand-picked figure for two
        # threads merely starting up; under a parallel run that is thread
        # scheduling, which is what the canonical ceiling exists to bound.
        barrier.wait(timeout=PROCESS_TIMEOUT_SECONDS)
        for ordinal in range(200):
            yield FileState.indexed(
                f"src/{prefix}-{ordinal:04d}.py",
                ContentKind.CODE,
                _digest(f"{prefix}-{ordinal}"),
            )

    def publish(prefix: str) -> None:
        try:
            publish_meta_from_file_states(
                meta_path,
                states(prefix),
                generation_id=f"generation-{prefix}",
                membership_epoch="membership-v1",
                content_epoch="content-v1",
                published_points_count=1,
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=publish, args=(prefix,)) for prefix in ("left", "right")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=PROCESS_TIMEOUT_SECONDS)

    assert not errors
    # Named rather than bare: this fired on CI as an unadorned "assert False",
    # which says nothing about whether a publisher was starved or the write
    # itself is wrong - and those two want opposite investigations. The
    # atomicity assertions below are only meaningful once both publishers have
    # finished, so this is the precondition for them, not a result.
    # Mutation: stalled one publisher past the join. Observed
    # "publisher thread(s) still running after 10s: ['Thread-2 (publish)']".
    # Restored, and it passes. Note the ceiling is unchanged at 10s, so this
    # names the next occurrence rather than preventing it.
    still_running = [thread.name for thread in threads if thread.is_alive()]
    assert not still_running, (
        f"publisher thread(s) still running after "
        f"{PROCESS_TIMEOUT_SECONDS:.0f}s: {still_running}"
    )
    raw = read_meta_raw(meta_path)
    winner = raw[GENERATION_ID_KEY].removeprefix("generation-")
    assert winner in {"left", "right"}
    published = load_meta(meta_path)
    assert len(published) == 200
    assert all(path.startswith(f"src/{winner}-") for path in published)
    assert not list(tmp_path.glob(f".{meta_path.name}.*.tmp"))


def test_reopening_a_drifted_path_supersedes_only_its_stale_upserts(
    tmp_path: Path,
) -> None:
    """A resumed indexed path whose source changed can be ingested again.

    This is the ledger half of the resume-after-failure cascade: an attempt
    marks a path indexed, fails, and the next attempt finds that path's source
    changed. Its fresh segments carry a new digest, so they are neither
    recognised as already committed nor writable over an indexed path.
    """
    ledger = RunLedger(index_run_ledger_path(tmp_path))
    generation = ledger.start_generation(_signature(tmp_path))
    generation_id = generation.generation_id
    old_digest = _digest("before the edit")
    new_digest = _digest("after the edit")

    for ordinal in range(2):
        ledger.record_storage_confirmed_unit(
            generation_id,
            _unit("src/drifted.py", ordinal, 2, digest=old_digest),
        )
    ledger.record_storage_confirmed_unit(
        generation_id,
        CommitUnit(
            rel_path="src/drifted.py",
            kind=CommitUnitKind.DELETE_STALE,
            source_digest=None,
            segment_ordinal=0,
            is_file_end=True,
            point_ids=("src/drifted.py:stale:0",),
        ),
    )
    ledger.record_file_state(
        generation_id,
        FileState.indexed("src/drifted.py", ContentKind.CODE, old_digest),
    )
    for ordinal in range(2):
        ledger.record_storage_confirmed_unit(
            generation_id,
            _unit("src/untouched.py", ordinal, 2),
        )
    ledger.record_file_state(
        generation_id,
        FileState.indexed(
            "src/untouched.py", ContentKind.CODE, _digest("src/untouched.py")
        ),
    )

    lookup = ("src/drifted.py", "src/untouched.py")
    assert ledger.indexed_digests_for_paths(generation_id, lookup) == {
        "src/drifted.py": old_digest,
        "src/untouched.py": _digest("src/untouched.py"),
    }

    # The cascade itself: the fresh content cannot be written over the path.
    fresh = _unit("src/drifted.py", 0, 1, digest=new_digest)
    with pytest.raises(RunLedgerStateError, match="after a path is indexed"):
        ledger.record_storage_confirmed_unit(generation_id, fresh)

    assert (
        ledger.reopen_drifted_path(
            generation_id, "src/drifted.py", superseded_digest=old_digest
        )
        == 2
    )

    remaining = [
        unit
        for unit in ledger.iter_units(generation_id)
        if unit.rel_path == "src/drifted.py"
    ]
    # The deletion unit is the durable record that the published points were
    # removed from storage, so it must outlive the upserts it supersedes.
    assert [unit.kind for unit in remaining] == [CommitUnitKind.DELETE_STALE]
    assert not any(unit.source_digest == old_digest for unit in remaining)
    # A sibling path's evidence and indexed state are untouched.
    untouched = [
        unit
        for unit in ledger.iter_units(generation_id)
        if unit.rel_path == "src/untouched.py"
    ]
    assert len(untouched) == 2
    assert ledger.indexed_digests_for_paths(generation_id, lookup) == {
        "src/untouched.py": _digest("src/untouched.py")
    }

    # The previously refused write now succeeds and the path re-converges.
    ledger.record_storage_confirmed_unit(generation_id, fresh)
    ledger.record_file_state(
        generation_id,
        FileState.indexed("src/drifted.py", ContentKind.CODE, new_digest),
    )
    assert ledger.indexed_digests_for_paths(generation_id, ("src/drifted.py",)) == {
        "src/drifted.py": new_digest
    }
    # Replaying the re-open after an interruption removes nothing.
    assert (
        ledger.reopen_drifted_path(
            generation_id, "src/drifted.py", superseded_digest=old_digest
        )
        == 0
    )


def test_reopening_a_path_is_refused_once_finalization_begins(tmp_path: Path) -> None:
    """Re-opening is an ingestion-phase repair, not a post-publication edit."""
    ledger = RunLedger(index_run_ledger_path(tmp_path))
    generation_id = ledger.start_generation(_signature(tmp_path)).generation_id
    digest = _digest("only content")
    ledger.record_storage_confirmed_unit(
        generation_id, _unit("src/one.py", 0, 1, digest=digest)
    )
    ledger.record_file_state(
        generation_id, FileState.indexed("src/one.py", ContentKind.CODE, digest)
    )
    ledger.advance_finalization(generation_id, FinalizationPhase.STALE_RECONCILED)

    with pytest.raises(RunLedgerStateError, match="finalization"):
        ledger.reopen_drifted_path(
            generation_id, "src/one.py", superseded_digest=digest
        )


def test_carried_forward_points_are_retained_by_the_inheriting_generation(
    tmp_path: Path,
) -> None:
    """Inherited points must survive a generation that carries them forward.

    A carried-forward file state keeps the generation that produced its
    evidence while living under the new one, so its units - and therefore its
    points - belong to the parent. A retained-point lookup that constrains
    points to the querying generation finds none of them, the caller reads
    that as obsolete, and an ordinary incremental run silently deletes the
    inherited half of the index.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    full = ledger.start_generation(_signature(tmp_path))
    paths = ("src/carried_one.py", "src/carried_two.py")
    inherited_points: set[str] = set()
    for path in paths:
        unit = _unit(path, 0, 1, digest=_digest(path))
        inherited_points.update(unit.point_ids)
        ledger.record_storage_confirmed_unit(full.generation_id, unit)
        ledger.record_file_state(
            full.generation_id,
            FileState.indexed(path, ContentKind.CODE, _digest(path)),
        )
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(full.generation_id, phase)
    ledger.finish_generation(full.generation_id, RunTerminalState.SUCCEEDED)

    incremental = ledger.start_generation(
        replace(
            full.signature,
            operation=RunOperation.INCREMENTAL,
            configuration_fingerprint="configuration-v2",
        )
    )
    assert incremental.parent_generation_id == full.generation_id
    # The states now live under the new generation while their evidence still
    # points at the parent, which is the condition that made this reachable.
    carried = ledger.file_states_for_paths(incremental.generation_id, paths)
    assert set(carried) == set(paths)

    retained = ledger.retained_point_ids_for_candidates(
        incremental.generation_id,
        tuple(sorted(inherited_points)),
    )
    assert retained == frozenset(inherited_points), (
        "carried-forward points were not recognised as retained; an "
        "incremental run would delete the inherited index"
    )


def test_a_repeatedly_failing_generation_retires_instead_of_resuming(
    tmp_path: Path,
) -> None:
    """Resumption is bounded, so a deterministic fault cannot wedge forever.

    A generation that keeps failing for a stable reason is inherited by every
    later attempt, which fails the same way. Without a bound the only escape
    is an unrelated signature change, so one transient cause can hold an
    index down indefinitely.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = replace(_signature(tmp_path), operation=RunOperation.INCREMENTAL)
    original = ledger.start_generation(signature).generation_id

    # Below the bound the generation is still the right thing to resume.
    for _attempt in range(2):
        resumed = ledger.start_generation(signature)
        assert resumed.generation_id == original
        ledger.finish_generation(
            resumed.generation_id,
            RunTerminalState.FAILED,
            detail="a stable fault",
        )
    still_resumable = ledger.start_generation(signature)
    assert still_resumable.generation_id == original
    ledger.finish_generation(
        still_resumable.generation_id,
        RunTerminalState.FAILED,
        detail="a stable fault",
    )

    # At the bound it retires and the next attempt starts clean.
    replacement = ledger.start_generation(signature)
    assert replacement.generation_id != original

    retired = ledger.generation(original)
    # Invalidated rather than deleted: the evidence stays readable until a
    # later success compacts it, and invalidated is not resumable.
    assert retired.terminal_state is RunTerminalState.INVALIDATED
    assert retired.terminal_detail is not None
    assert "consecutive failed attempts" in retired.terminal_detail
    assert RunTerminalState.INVALIDATED not in RESUMABLE_STATES


def test_a_succeeding_generation_never_accrues_resume_failures(
    tmp_path: Path,
) -> None:
    """Only unsuccessful outcomes advance the bound."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(generation.generation_id, phase)
    ledger.finish_generation(generation.generation_id, RunTerminalState.SUCCEEDED)

    with sqlite3.connect(tmp_path / "runs.sqlite3") as connection:
        failures = connection.execute(
            "SELECT consecutive_failures FROM generations WHERE generation_id = ?",
            (generation.generation_id,),
        ).fetchone()[0]
    assert int(failures) == 0


def _publish_and_compact(ledger: RunLedger, generation_id: str) -> int:
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(generation_id, phase)
    ledger.finish_generation(generation_id, RunTerminalState.SUCCEEDED)
    return ledger.compact(generation_id)


def test_compaction_keeps_generations_backing_carried_evidence(
    tmp_path: Path,
) -> None:
    """Compacting a published carrier must not sever its inherited evidence.

    A carried-forward file state pins the generation that produced its
    evidence; the commit units that vouch for its stored points live there.
    Deleting that generation cascades the units away, and the next run's
    retention lookup then reads every inherited point as obsolete and purges
    the entire collection.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = _signature(tmp_path)
    unit = _unit("src/kept.py", 0, 1)

    origin = ledger.start_generation(signature)
    ledger.record_storage_confirmed_unit(origin.generation_id, unit)
    ledger.record_file_state(
        origin.generation_id,
        FileState(
            "src/kept.py",
            FileStateKind.INDEXED,
            ContentKind.CODE,
            _digest("src/kept.py"),
        ),
    )
    _publish_and_compact(ledger, origin.generation_id)

    carrier = ledger.start_generation(signature)
    assert carrier.parent_generation_id == origin.generation_id
    _publish_and_compact(ledger, carrier.generation_id)

    # The generation the carried state cites must survive its child's
    # compaction, or the retained-point lookup below returns nothing and the
    # purge deletes the whole collection.
    assert ledger.generation(origin.generation_id).terminal_state is (
        RunTerminalState.SUCCEEDED
    )
    successor = ledger.start_generation(signature)
    assert ledger.retained_point_ids_for_candidates(
        successor.generation_id,
        unit.point_ids,
    ) == frozenset(unit.point_ids)


def test_compaction_removes_generations_no_surviving_state_cites(
    tmp_path: Path,
) -> None:
    """Evidence retention is exact: superseded generations still compact."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = _signature(tmp_path)

    origin = ledger.start_generation(signature)
    ledger.record_storage_confirmed_unit(
        origin.generation_id, _unit("src/kept.py", 0, 1)
    )
    ledger.record_file_state(
        origin.generation_id,
        FileState(
            "src/kept.py",
            FileStateKind.INDEXED,
            ContentKind.CODE,
            _digest("src/kept.py"),
        ),
    )
    _publish_and_compact(ledger, origin.generation_id)

    carrier = ledger.start_generation(signature)
    _publish_and_compact(ledger, carrier.generation_id)

    # A clean rebuild re-homes every file's evidence to itself, so nothing
    # cites the earlier generations and both must compact away.
    rebuild = ledger.start_generation(replace(signature, clean=True))
    ledger.record_storage_confirmed_unit(
        rebuild.generation_id, _unit("src/kept.py", 0, 1)
    )
    ledger.record_file_state(
        rebuild.generation_id,
        FileState(
            "src/kept.py",
            FileStateKind.INDEXED,
            ContentKind.CODE,
            _digest("src/kept.py"),
        ),
    )
    assert _publish_and_compact(ledger, rebuild.generation_id) == 2
    with pytest.raises(KeyError):
        ledger.generation(origin.generation_id)
    with pytest.raises(KeyError):
        ledger.generation(carrier.generation_id)


def test_carry_forward_refuses_a_manifest_with_dangling_evidence(
    tmp_path: Path,
) -> None:
    """A published manifest whose evidence dangles must not seed a diff.

    Carrying it forward hands the new generation file states whose cited
    units no longer exist, so every inherited point reads as unretained and
    the publication purge deletes the entire collection. Refusing the parent
    forces the caller onto the full failure-safe reconciliation path instead.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = _signature(tmp_path)
    unit = _unit("src/kept.py", 0, 1)

    origin = ledger.start_generation(signature)
    ledger.record_storage_confirmed_unit(origin.generation_id, unit)
    ledger.record_file_state(
        origin.generation_id,
        FileState(
            "src/kept.py",
            FileStateKind.INDEXED,
            ContentKind.CODE,
            _digest("src/kept.py"),
        ),
    )
    _publish_and_compact(ledger, origin.generation_id)
    carrier = ledger.start_generation(signature)
    _publish_and_compact(ledger, carrier.generation_id)

    # Sever the evidence out from under the published manifest, the state a
    # ledger compacted by a build without evidence retention is left in.
    connection = sqlite3.connect(ledger.path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "DELETE FROM generations WHERE generation_id = ?",
        (origin.generation_id,),
    )
    connection.commit()
    connection.close()

    successor = ledger.start_generation(signature)
    # No parent: the incremental open refuses and the caller escalates to a
    # full reconciliation rather than diffing against poisoned evidence.
    assert successor.parent_generation_id is None
    assert ledger.file_states_for_paths(successor.generation_id, ("src/kept.py",)) == {}


def test_carry_forward_stops_rather_than_falling_back_to_an_older_manifest(
    tmp_path: Path,
) -> None:
    """A dangling candidate ends the scan; it does not demote to an older one.

    The newest compatible manifest is the one storage reflects. An older
    same-fingerprint manifest describes points a later publication already
    replaced, so carrying it would claim dead point ids and skip re-encoding
    every file it names. Refusing outright forces the full failure-safe
    reconciliation instead.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = _signature(tmp_path)
    paths = ("src/one.py", "src/two.py", "src/three.py")

    def index(generation_id: str, rel_path: str, version: str) -> None:
        digest = _digest(f"{rel_path}:{version}")
        ledger.record_storage_confirmed_unit(
            generation_id,
            _unit(rel_path, 0, 1, digest=digest),
        )
        ledger.record_file_state(
            generation_id,
            FileState(rel_path, FileStateKind.INDEXED, ContentKind.CODE, digest),
        )

    # The origin indexes everything, so all three states cite it.
    origin = ledger.start_generation(signature)
    for rel_path in paths:
        index(origin.generation_id, rel_path, "v1")
    _publish_and_compact(ledger, origin.generation_id)

    # The middle generation re-indexes one file, moving that state's evidence
    # onto itself while the other two keep citing the origin.
    middle = ledger.start_generation(signature)
    index(middle.generation_id, paths[0], "v2")
    _publish_and_compact(ledger, middle.generation_id)

    # The newest generation re-indexes a second file. Its manifest now cites
    # the middle generation, itself, and the origin.
    newest = ledger.start_generation(signature)
    index(newest.generation_id, paths[1], "v2")
    _publish_and_compact(ledger, newest.generation_id)

    # Sever the middle generation, the state a ledger compacted by a build
    # without evidence retention is left in. The newest manifest now dangles
    # while the origin - older, compatible, and still cited only by itself -
    # remains a viable fall-back target.
    connection = sqlite3.connect(ledger.path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "DELETE FROM generations WHERE generation_id = ?",
        (middle.generation_id,),
    )
    connection.commit()
    connection.close()

    # Without an intact older candidate the assertion below would hold for the
    # wrong reason, so pin that the fall-back target really did survive.
    assert ledger.generation(origin.generation_id).terminal_state is (
        RunTerminalState.SUCCEEDED
    )

    successor = ledger.start_generation(signature)
    assert successor.parent_generation_id is None
    assert ledger.file_states_for_paths(successor.generation_id, paths) == {}


def test_compact_refuses_a_keep_older_than_the_newest_published_generation(
    tmp_path: Path,
) -> None:
    """Compacting an older published generation must be refused.

    An older keep restamps itself newest and deletes - or strands the
    evidence of - the manifest storage actually reflects, after which the
    next carry-forward reads stale history as current. The refusal must land
    before any deletion, leaving the newest manifest and the scan order
    untouched.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = _signature(tmp_path)

    older = ledger.start_generation(signature)
    digest = _digest("src/kept.py:v1")
    ledger.record_storage_confirmed_unit(
        older.generation_id,
        _unit("src/kept.py", 0, 1, digest=digest),
    )
    ledger.record_file_state(
        older.generation_id,
        FileState("src/kept.py", FileStateKind.INDEXED, ContentKind.CODE, digest),
    )
    _publish_and_compact(ledger, older.generation_id)

    # The newest generation carries the older manifest, so the older
    # generation survives the in-order compaction as cited evidence and
    # remains available as a stale keep.
    newest = ledger.start_generation(signature)
    _publish_and_compact(ledger, newest.generation_id)

    with pytest.raises(RunLedgerStateError, match="newest published generation"):
        ledger.compact(older.generation_id)

    # Without the refusal this compaction deletes the uncited newest
    # manifest and restamps the older one to the head of the carry scan, so
    # pin that neither happened.
    assert ledger.generation(newest.generation_id).terminal_state is (
        RunTerminalState.SUCCEEDED
    )
    latest = ledger.latest_generation(
        ContentKind.CODE, collection_identity=signature.collection_identity
    )
    assert latest is not None
    assert latest.generation_id == newest.generation_id


def test_compact_accepts_the_newest_keep_after_deferred_compaction(
    tmp_path: Path,
) -> None:
    """A publication interrupted before compacting stays recoverable.

    finish_generation stamps the keep, so a keep whose compaction never ran
    is still the newest published generation: the retry is accepted, a
    second compaction of the same keep stays legal, and a successor started
    after the interruption carries the uncompacted manifest and compacts
    around its own keep.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = _signature(tmp_path)

    published = ledger.start_generation(signature)
    digest = _digest("src/kept.py:v1")
    ledger.record_storage_confirmed_unit(
        published.generation_id,
        _unit("src/kept.py", 0, 1, digest=digest),
    )
    ledger.record_file_state(
        published.generation_id,
        FileState("src/kept.py", FileStateKind.INDEXED, ContentKind.CODE, digest),
    )
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(published.generation_id, phase)
    ledger.finish_generation(published.generation_id, RunTerminalState.SUCCEEDED)

    reopened = RunLedger(ledger.path)
    assert reopened.compact(published.generation_id) == 0
    assert reopened.compact(published.generation_id) == 0
    assert reopened.generation(published.generation_id).finalization_phase is (
        FinalizationPhase.COMPACTED
    )

    successor = reopened.start_generation(signature)
    assert successor.parent_generation_id == published.generation_id
    _publish_and_compact(reopened, successor.generation_id)
    assert reopened.generation(successor.generation_id).finalization_phase is (
        FinalizationPhase.COMPACTED
    )


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
    signature = _signature(tmp_path)

    older = ledger.start_generation(signature)
    digest = _digest("src/kept.py:v1")
    ledger.record_storage_confirmed_unit(
        older.generation_id,
        _unit("src/kept.py", 0, 1, digest=digest),
    )
    ledger.record_file_state(
        older.generation_id,
        FileState("src/kept.py", FileStateKind.INDEXED, ContentKind.CODE, digest),
    )
    _publish_and_compact(ledger, older.generation_id)

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


# --- Concurrency -----------------------------------------------------------
#
# A root keeps ONE ledger file, shared by code, document, and vault runs, so a
# commit lands while other work reads the same database. Nothing above can
# observe that: every test up to here opens the ledger once, from one thread,
# and passes just as happily against a build that starves its own commits.
#
# These are guard tests, and what they guard is a journal mode. A contention
# assertion proves nothing unless the harness genuinely creates contention, so
# the failing direction is kept as an executable test rather than as a mutation
# a reader has to apply by hand and remember to revert. If
# `test_the_contention_harness_starves_a_rollback_journal_commit` ever stops
# failing its commit, the harness has gone slack and the tests beside it can
# pass vacuously.
#
# Both directions were verified against the production path, not just against
# that harness. Swapping the journal mode requested in `open_ledger_connection`
# from WAL to DELETE fails both
# `test_a_long_reader_cannot_fail_a_concurrent_ledger_commit` and
# `test_a_held_read_blocks_neither_kind_on_the_shared_ledger`, each on its
# `record_storage_confirmed_units(...) == 1` assertion, raising
# `RunLedgerContentionError: ... database is locked`. Restoring WAL passes
# both. Repeat that swap if you ever need to re-confirm these can fail; do not
# relax an assertion to make one pass.
