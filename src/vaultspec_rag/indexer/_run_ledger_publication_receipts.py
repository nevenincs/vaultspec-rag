"""Receipt reservation, mutation ownership, and proof commit operations."""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import TYPE_CHECKING, Final

from ._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofCompatibilityKey,
    ProofEvidence,
    ProofIncompatibleError,
    ProofOldEvidenceMismatchError,
    ProofParentMismatchError,
    ProofProvenance,
    ProofReadConflictError,
    ProofReceiptState,
)
from ._run_ledger_models import (
    FETCH_BATCH,
    FinalizationPhase,
    GenerationRow,
    PublicationProof,
    PublicationReceipt,
    RunAuthority,
    RunLedgerCorruptionError,
    RunLedgerStateError,
    RunOperation,
    RunSignature,
    RunTerminalState,
    column_text,
    fetch_all,
    fetch_one,
    in_ledger_transaction,
    ledger_connection,
)
from ._run_ledger_publication_identity import (
    stable_parameters,
)
from ._run_ledger_publication_storage import (
    OPEN_RECEIPT_SQL,
    all_evidence_for_paths,
    hydrate_receipt,
    latest_receipt_row,
    proof_from_row,
    receipt_committed_at,
    receipt_corrupt,
    receipt_row_by_id,
    require_exact_key,
    require_proof_row,
    require_receipt_ready_to_commit,
)

_CLOSED_PUBLICATION_RECEIPT_HISTORY_LIMIT: Final = FETCH_BATCH

if TYPE_CHECKING:
    from pathlib import Path

    from ._run_ledger_models import RunGeneration


def _require_rebuild_projection(
    signature: RunSignature,
    key: ProofCompatibilityKey,
) -> None:
    if signature.operation is not RunOperation.FULL:
        raise PermissionError(
            "receipt recovery requires an explicit full rebuild signature"
        )
    if (
        signature.source_type.value,
        signature.root_identity,
        signature.backend_identity,
        signature.collection_identity,
    ) != stable_parameters(key):
        raise PermissionError(
            "receipt recovery requires the exact full rebuild projection"
        )


class RunLedgerPublicationReceiptMethods:
    """Own receipt reservations, exact delta checks, and proof commits."""

    if TYPE_CHECKING:
        path: Path

        @staticmethod
        def _require_mutable_generation(
            connection: sqlite3.Connection,
            generation_id: str,
        ) -> GenerationRow: ...

        @staticmethod
        def _generation_from_row(row: GenerationRow) -> RunGeneration: ...

        @staticmethod
        def _assert_ready_for_finalization(
            connection: sqlite3.Connection,
            generation_id: str,
        ) -> None: ...

    def publication_receipt_for_generation(
        self,
        generation_id: str,
    ) -> PublicationReceipt | None:
        """Read the latest durable receipt, including a completed reservation."""
        with ledger_connection(self.path) as connection:
            connection.execute("BEGIN")
            try:
                row = latest_receipt_row(connection, generation_id)
                return None if row is None else hydrate_receipt(connection, row)
            finally:
                connection.rollback()

    def rebuild_recovery_receipt(
        self,
        signature: RunSignature,
        authority: RunAuthority,
    ) -> PublicationReceipt | None:
        """Read unfinished work for exactly the explicitly rebuilt projection.

        The requested pipeline can differ from the old publication. Recovery
        validates that receipt against its own proof, never interprets its
        evidence as input to the replacement build.
        """
        if (
            authority is not RunAuthority.REBUILD
            or signature.operation is not RunOperation.FULL
        ):
            raise PermissionError(
                "receipt recovery requires explicit rebuild authority"
            )
        stable = (
            signature.source_type.value,
            signature.root_identity,
            signature.backend_identity,
            signature.collection_identity,
        )
        with ledger_connection(self.path) as connection:
            connection.execute("BEGIN")
            try:
                row = fetch_one(
                    connection,
                    f"""
                    SELECT * FROM publication_receipts
                    WHERE source_type = ? AND root_identity = ?
                      AND backend_identity = ? AND collection_identity = ?
                      AND {OPEN_RECEIPT_SQL}
                    """,
                    stable,
                )
                if row is None:
                    return None
                receipt = hydrate_receipt(connection, row)
                proof_row = require_proof_row(connection, receipt.compatibility_key)
                require_exact_key(
                    proof_row, receipt.compatibility_key, subject="recovery proof"
                )
                proof = proof_from_row(proof_row)
                if (
                    receipt.parent_revision != proof.revision
                    or receipt.reservation_sequence != proof.reservation_sequence
                ):
                    receipt_corrupt("recovery receipt does not match its current proof")
                return receipt
            finally:
                connection.rollback()

    @staticmethod
    def _new_point_ids(receipt: PublicationReceipt) -> tuple[str, ...]:
        return tuple(
            point_id
            for delta in receipt.deltas
            if delta.changes_proof and delta.new is not None
            for point_id in delta.new.point_ids
        )

    @staticmethod
    def _owners_for_points(
        connection: sqlite3.Connection,
        key: ProofCompatibilityKey,
        point_ids: tuple[str, ...],
    ) -> dict[str, str]:
        owners: dict[str, str] = {}
        unique_points = tuple(dict.fromkeys(point_ids))
        for start in range(0, len(unique_points), FETCH_BATCH):
            page = unique_points[start : start + FETCH_BATCH]
            placeholders = ", ".join("?" for _point in page)
            rows: list[sqlite3.Row] = fetch_all(
                connection,
                f"""
                SELECT point_id, rel_path FROM publication_points
                WHERE source_type = ? AND root_identity = ?
                  AND backend_identity = ? AND collection_identity = ?
                  AND point_id IN ({placeholders})
                """,
                (*stable_parameters(key), *page),
            )
            owners.update(
                {
                    column_text(row, "point_id"): column_text(row, "rel_path")
                    for row in rows
                }
            )
        return owners

    @staticmethod
    def _validate_delta_point_ownership(
        delta: PathDelta,
        owners: dict[str, str],
    ) -> None:
        if not delta.changes_proof or delta.new is None:
            return
        for point_id in delta.new.point_ids:
            owner = owners.get(point_id)
            if owner is not None and owner != delta.rel_path:
                raise ProofOldEvidenceMismatchError(
                    f"point {point_id!r} belongs to untouched path {owner!r}"
                )

    @staticmethod
    def _prune_closed_publication_receipts(
        connection: sqlite3.Connection,
        *,
        source_type: str,
        collection_identity: str,
    ) -> None:
        """Bound unexposed closed history before generation reclamation."""
        connection.execute(
            """
            WITH ranked_history AS (
                SELECT receipt.receipt_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY
                               receipt.source_type,
                               receipt.root_identity,
                               receipt.backend_identity,
                               receipt.collection_identity
                           ORDER BY receipt.reservation_sequence DESC,
                                    receipt.receipt_id DESC
                       ) AS history_rank
                FROM publication_receipts AS receipt
                WHERE receipt.source_type = ?
                  AND receipt.collection_identity = ?
                  AND receipt.state IN (?, ?)
                  AND NOT EXISTS (
                      SELECT 1 FROM publication_proofs AS proof
                      WHERE proof.source_type = receipt.source_type
                        AND proof.root_identity = receipt.root_identity
                        AND proof.backend_identity = receipt.backend_identity
                        AND proof.collection_identity = receipt.collection_identity
                        AND proof.storage_schema = receipt.storage_schema
                        AND proof.payload_schema = receipt.payload_schema
                        AND proof.embedding_schema_identity =
                            receipt.embedding_schema_identity
                        AND proof.chunking_schema_identity =
                            receipt.chunking_schema_identity
                        AND proof.membership_identity = receipt.membership_identity
                        AND proof.content_identity = receipt.content_identity
                        AND proof.policy_identity = receipt.policy_identity
                        AND proof.generation_id = receipt.generation_id
                        AND proof.revision = receipt.target_revision
                        AND proof.reservation_sequence =
                            receipt.reservation_sequence
                        AND proof.provenance = ?
                  )
            )
            DELETE FROM publication_receipts
            WHERE receipt_id IN (
                SELECT receipt_id FROM ranked_history
                WHERE history_rank > ?
            )
            """,
            (
                source_type,
                collection_identity,
                ProofReceiptState.COMMITTED.value,
                ProofReceiptState.ROLLED_BACK.value,
                ProofProvenance.DELTA_DERIVED.value,
                _CLOSED_PUBLICATION_RECEIPT_HISTORY_LIMIT,
            ),
        )

    def reserve_publication_receipt(
        self,
        key: ProofCompatibilityKey,
        generation_id: str,
        *,
        expected_parent_revision: int,
    ) -> PublicationReceipt:
        """Atomically reserve the next monotonic sequence and target revision."""
        if isinstance(expected_parent_revision, bool) or not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance] - runtime boundary
            expected_parent_revision, int
        ):
            raise TypeError("expected_parent_revision must be an integer")
        if expected_parent_revision < 0:
            raise ValueError("expected_parent_revision must be non-negative")
        receipt_id = uuid.uuid4().hex
        reserved_at = time.time()

        def body(connection: sqlite3.Connection) -> PublicationReceipt:
            existing = receipt_row_by_id(connection, receipt_id)
            if existing is not None:
                receipt = hydrate_receipt(connection, existing)
                if (
                    receipt.compatibility_key == key
                    and receipt.generation_id == generation_id
                    and receipt.parent_revision == expected_parent_revision
                ):
                    return receipt
                raise RunLedgerStateError("publication receipt identity was reused")
            proof_row = require_proof_row(connection, key)
            proof = proof_from_row(proof_row)
            if proof.revision != expected_parent_revision:
                raise ProofParentMismatchError(
                    "publication receipt names a stale parent revision"
                )
            generation = self._require_compatible_receipt_generation(
                connection,
                generation_id,
                key,
                proof,
            )
            if generation.finalization_phase is not FinalizationPhase.INGESTING:
                raise RunLedgerStateError(
                    "cannot reserve publication after stale reconciliation begins"
                )
            active: sqlite3.Row | None = fetch_one(
                connection,
                f"""
                SELECT receipt_id FROM publication_receipts
                WHERE source_type = ? AND root_identity = ?
                  AND backend_identity = ? AND collection_identity = ?
                  AND {OPEN_RECEIPT_SQL}
                """,
                stable_parameters(key),
            )
            if active is not None:
                raise RunLedgerStateError(
                    "another publication receipt is already active"
                )
            sequence = proof.reservation_sequence + 1
            cursor = connection.execute(
                """
                UPDATE publication_proofs SET reservation_sequence = ?
                WHERE source_type = ? AND root_identity = ?
                  AND backend_identity = ? AND collection_identity = ?
                  AND revision = ? AND reservation_sequence = ?
                """,
                (
                    sequence,
                    *stable_parameters(key),
                    proof.revision,
                    proof.reservation_sequence,
                ),
            )
            if cursor.rowcount != 1:
                raise ProofReadConflictError(
                    "publication proof changed during receipt reservation"
                )
            connection.execute(
                """
                INSERT INTO publication_receipts (
                    receipt_id, reservation_sequence, source_type,
                    root_identity, backend_identity, collection_identity,
                    storage_schema, payload_schema, embedding_schema_identity,
                    chunking_schema_identity, membership_identity,
                    content_identity, policy_identity, generation_id,
                    parent_revision, target_revision, next_mutation_ordinal,
                    state, reserved_at, sealed_at, rollback_started_at,
                    committed_at, rolled_back_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?,
                    NULL, NULL, NULL, NULL
                )
                """,
                (
                    receipt_id,
                    sequence,
                    *stable_parameters(key),
                    key.storage_schema,
                    key.payload_schema,
                    key.embedding_schema_identity,
                    key.chunking_schema_identity,
                    key.membership_identity,
                    key.content_identity,
                    key.policy_identity,
                    generation_id,
                    proof.revision,
                    proof.revision + 1,
                    ProofReceiptState.RESERVED.value,
                    reserved_at,
                ),
            )
            row = receipt_row_by_id(connection, receipt_id)
            assert row is not None
            return hydrate_receipt(connection, row)

        return in_ledger_transaction(self.path, body)

    def _require_compatible_receipt_generation(
        self,
        connection: sqlite3.Connection,
        generation_id: str,
        key: ProofCompatibilityKey,
        proof: PublicationProof,
        *,
        rebuild_signature: RunSignature | None = None,
    ) -> RunGeneration:
        if rebuild_signature is None:
            row = self._require_mutable_generation(connection, generation_id)
        else:
            _require_rebuild_projection(rebuild_signature, key)
            stored: GenerationRow | None = fetch_one(
                connection,
                "SELECT * FROM generations WHERE generation_id = ?",
                (generation_id,),
            )
            if stored is None:
                raise RunLedgerCorruptionError(
                    "recovery receipt cites a missing generation"
                )
            if RunTerminalState(stored["terminal_state"]) is RunTerminalState.SUCCEEDED:
                raise RunLedgerStateError(
                    "successful generations cannot own unfinished recovery"
                )
            row = stored
        generation = self._generation_from_row(row)
        signature = generation.signature
        if (
            signature.source_type.value != key.source_type.value
            or signature.root_identity != key.root_identity
            or signature.backend_identity != key.backend_identity
            or signature.collection_identity != key.collection_identity
        ):
            raise ProofIncompatibleError(
                "publication receipt generation has a different stable identity"
            )
        if generation.parent_generation_id != proof.generation_id:
            raise ProofParentMismatchError(
                "publication receipt generation does not descend from the proof"
            )
        parent_row: GenerationRow | None = fetch_one(
            connection,
            "SELECT * FROM generations WHERE generation_id = ?",
            (proof.generation_id,),
        )
        if parent_row is None:
            raise RunLedgerCorruptionError(
                "publication proof cites a missing generation"
            )
        parent = self._generation_from_row(parent_row)
        if (
            signature.content_compatibility_fingerprint
            != parent.signature.content_compatibility_fingerprint
        ):
            raise ProofIncompatibleError(
                "publication receipt generation is incompatible with its parent"
            )
        return generation

    def commit_publication_receipt(
        self,
        receipt_id: str,
        *,
        authority: RunAuthority = RunAuthority.PUBLICATION,
        rebuild_signature: RunSignature | None = None,
    ) -> PublicationProof:
        """Commit one sealed, confirmed receipt with an exact revision CAS.

        Explicit rebuild recovery can close exact recorded work left on a
        terminal owner without reactivating or editing its generation history.
        Ordinary publication still requires a running, reconciled generation.
        """
        if not isinstance(receipt_id, str) or not receipt_id.strip():  # pyright: ignore[reportUnnecessaryIsInstance] - runtime boundary
            raise ValueError("receipt_id must be non-empty")
        recovery = authority is RunAuthority.REBUILD
        if recovery:
            if (
                rebuild_signature is None
                or rebuild_signature.operation is not RunOperation.FULL
            ):
                raise PermissionError(
                    "receipt recovery requires an explicit full rebuild signature"
                )
        elif authority is not RunAuthority.PUBLICATION or rebuild_signature is not None:
            raise PermissionError("receipt recovery requires rebuild authority")
        committed_at = time.time()

        def body(connection: sqlite3.Connection) -> PublicationProof:
            row = receipt_row_by_id(connection, receipt_id)
            if row is None:
                raise KeyError(receipt_id)
            receipt = hydrate_receipt(connection, row)
            if rebuild_signature is not None:
                _require_rebuild_projection(
                    rebuild_signature, receipt.compatibility_key
                )
            if receipt.state is ProofReceiptState.COMMITTED:
                return self._committed_receipt_replay(connection, receipt)
            require_receipt_ready_to_commit(receipt)
            committed_receipt_at = receipt_committed_at(receipt, committed_at)
            proof = self._validate_receipt_authority(connection, receipt)
            self._require_receipt_commit_generation(
                connection, receipt, proof, rebuild_signature
            )
            aggregate = proof.aggregate
            for delta in receipt.deltas:
                aggregate = aggregate.apply(delta)
            self._replace_changed_evidence(connection, receipt)
            cursor = connection.execute(
                """
                UPDATE publication_proofs SET
                    generation_id = ?, revision = ?, indexed_identities = ?,
                    retained_points = ?, provenance = ?, committed_at = ?,
                    verified_at = NULL
                WHERE source_type = ? AND root_identity = ?
                  AND backend_identity = ? AND collection_identity = ?
                  AND revision = ? AND reservation_sequence = ?
                """,
                (
                    receipt.generation_id,
                    receipt.target_revision,
                    aggregate.indexed_identities,
                    aggregate.retained_points,
                    ProofProvenance.DELTA_DERIVED.value,
                    committed_receipt_at,
                    *stable_parameters(receipt.compatibility_key),
                    receipt.parent_revision,
                    receipt.reservation_sequence,
                ),
            )
            if cursor.rowcount != 1:
                raise ProofReadConflictError(
                    "publication proof changed during receipt commit"
                )
            cursor = connection.execute(
                """
                UPDATE publication_receipts
                SET state = ?, committed_at = ?
                WHERE receipt_id = ? AND state = ?
                  AND parent_revision = ? AND target_revision = ?
                  AND reservation_sequence = ?
                """,
                (
                    ProofReceiptState.COMMITTED.value,
                    committed_receipt_at,
                    receipt.receipt_id,
                    ProofReceiptState.SEALED.value,
                    receipt.parent_revision,
                    receipt.target_revision,
                    receipt.reservation_sequence,
                ),
            )
            if cursor.rowcount != 1:
                raise ProofReadConflictError(
                    "publication receipt changed during proof commit"
                )
            return PublicationProof(
                revision=receipt.target_revision,
                reservation_sequence=receipt.reservation_sequence,
                compatibility_key=receipt.compatibility_key,
                generation_id=receipt.generation_id,
                aggregate=aggregate,
                provenance=ProofProvenance.DELTA_DERIVED,
                committed_at=committed_receipt_at,
            )

        return in_ledger_transaction(self.path, body)

    def _require_receipt_commit_generation(
        self,
        connection: sqlite3.Connection,
        receipt: PublicationReceipt,
        proof: PublicationProof,
        rebuild_signature: RunSignature | None,
    ) -> None:
        """Validate readiness without changing a recovery owner's durable history."""
        generation = self._require_compatible_receipt_generation(
            connection,
            receipt.generation_id,
            receipt.compatibility_key,
            proof,
            rebuild_signature=rebuild_signature,
        )
        if rebuild_signature is not None:
            if generation.finalization_phase not in {
                FinalizationPhase.INGESTING,
                FinalizationPhase.STALE_RECONCILED,
            }:
                raise RunLedgerStateError(
                    "unfinished recovery has an incompatible finalization phase"
                )
            self._assert_ready_for_finalization(connection, generation.generation_id)
        elif generation.finalization_phase is not FinalizationPhase.STALE_RECONCILED:
            raise RunLedgerStateError(
                "publication proof commits only after stale reconciliation"
            )

    def _validate_receipt_authority(
        self,
        connection: sqlite3.Connection,
        receipt: PublicationReceipt,
    ) -> PublicationProof:
        """Validate a receipt against current proof before destructive work."""
        proof_row = require_proof_row(connection, receipt.compatibility_key)
        proof = proof_from_row(proof_row)
        if proof.revision != receipt.parent_revision:
            raise ProofParentMismatchError(
                "publication proof no longer matches the receipt parent"
            )
        if proof.reservation_sequence != receipt.reservation_sequence:
            raise ProofReadConflictError(
                "publication reservation sequence no longer matches the receipt"
            )
        affected_paths = tuple(
            path
            for delta in receipt.deltas
            for path in (
                delta.rel_path,
                *((delta.target_rel_path,) if delta.target_rel_path else ()),
            )
        )
        current = all_evidence_for_paths(
            connection,
            receipt.compatibility_key,
            affected_paths,
        )
        self._validate_receipt_evidence(receipt, current)
        self._validate_new_point_ownership(connection, receipt)
        return proof

    @staticmethod
    def _committed_receipt_replay(
        connection: sqlite3.Connection,
        receipt: PublicationReceipt,
    ) -> PublicationProof:
        row = require_proof_row(connection, receipt.compatibility_key)
        proof = proof_from_row(row)
        if (
            proof.revision != receipt.target_revision
            or proof.reservation_sequence != receipt.reservation_sequence
            or proof.generation_id != receipt.generation_id
        ):
            receipt_corrupt(
                "committed publication receipt does not match the current proof"
            )
        return proof

    @staticmethod
    def _validate_receipt_evidence(
        receipt: PublicationReceipt,
        current: dict[str, ProofEvidence],
    ) -> None:
        for delta in receipt.deltas:
            actual = current.get(delta.rel_path)
            if delta.old is None:
                if actual is not None:
                    raise ProofOldEvidenceMismatchError(
                        f"publication path {delta.rel_path!r} already exists"
                    )
            elif actual != delta.old:
                raise ProofOldEvidenceMismatchError(
                    f"old publication evidence differs for {delta.rel_path!r}"
                )
            if delta.outcome is PathOutcome.RENAME and delta.target_rel_path in current:
                raise ProofOldEvidenceMismatchError(
                    f"rename target {delta.target_rel_path!r} already exists"
                )

    @classmethod
    def _validate_new_point_ownership(
        cls,
        connection: sqlite3.Connection,
        receipt: PublicationReceipt,
    ) -> None:
        new_points = cls._new_point_ids(receipt)
        if not new_points:
            return
        owners = cls._owners_for_points(
            connection, receipt.compatibility_key, new_points
        )
        for delta in receipt.deltas:
            cls._validate_delta_point_ownership(delta, owners)

    @staticmethod
    def _replace_changed_evidence(
        connection: sqlite3.Connection,
        receipt: PublicationReceipt,
    ) -> None:
        key = receipt.compatibility_key
        changing = tuple(delta for delta in receipt.deltas if delta.changes_proof)
        for delta in changing:
            if delta.old is not None:
                connection.execute(
                    """
                    DELETE FROM publication_evidence
                    WHERE source_type = ? AND root_identity = ?
                      AND backend_identity = ? AND collection_identity = ?
                      AND rel_path = ?
                    """,
                    (*stable_parameters(key), delta.old.rel_path),
                )
        for delta in changing:
            if delta.new is None:
                continue
            evidence = delta.new
            try:
                connection.execute(
                    """
                    INSERT INTO publication_evidence (
                        source_type, root_identity, backend_identity,
                        collection_identity, rel_path, content_identity,
                        evidence_generation_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        *stable_parameters(key),
                        evidence.rel_path,
                        evidence.content_identity,
                        receipt.generation_id,
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
                            *stable_parameters(key),
                            evidence.rel_path,
                            ordinal,
                            point_id,
                        )
                        for ordinal, point_id in enumerate(evidence.point_ids)
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ProofOldEvidenceMismatchError(
                    "receipt evidence conflicts with retained point ownership"
                ) from exc
