"""Proof establishment, invalidation, and generation proof checks."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, cast

from .._source_types import PublicSourceType
from ._publication_proof import (
    ProofAggregate,
    ProofCompatibilityKey,
    ProofEvidence,
    ProofProvenance,
    ProofReceiptState,
)
from ._run_ledger_models import (
    FinalizationPhase,
    GenerationRow,
    PublicationProof,
    RunAuthority,
    RunLedgerCorruptionError,
    RunLedgerStateError,
    RunOperation,
    RunTerminalState,
    column_int,
    column_text,
    fetch_all,
    fetch_one,
    in_ledger_transaction,
    ledger_connection,
    ledger_transaction,
)
from ._run_ledger_publication_identity import (
    compatibility_for_generation,
    publication_compatibility_from_row,
    stable_parameters,
)
from ._run_ledger_publication_storage import (
    OPEN_RECEIPT_SQL,
    proof_from_row,
    proof_row,
    receipt_corrupt,
    require_proof_row,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from ._run_ledger_models import RunGeneration


class RunLedgerPublicationProofMethods:
    """Own canonical proof establishment and generation checks."""

    if TYPE_CHECKING:
        path: Path

        @staticmethod
        def _require_mutable_generation(
            connection: sqlite3.Connection,
            generation_id: str,
        ) -> GenerationRow: ...

        @staticmethod
        def _generation_from_row(row: GenerationRow) -> RunGeneration: ...

    def publication_proof(self, key: ProofCompatibilityKey) -> PublicationProof:
        """Return the current proof for one stable projection without scanning."""
        with ledger_connection(self.path) as connection:
            row = require_proof_row(connection, key)
        return proof_from_row(row)

    def clear_publication_source(
        self,
        source_type: PublicSourceType,
        root_identity: str,
        backend_identity: str,
    ) -> None:
        """Invalidate one source before its backing storage is destroyed."""
        if source_type is PublicSourceType.COMBINED:
            raise ValueError("combined is not a stored publication source")
        if not root_identity.strip() or not backend_identity.strip():
            raise ValueError("publication identity fields must be non-empty")
        now = time.time()
        with ledger_transaction(self.path) as connection:
            parameters = (source_type.value, root_identity, backend_identity)
            connection.execute(
                """
                DELETE FROM publication_receipts
                WHERE source_type = ? AND root_identity = ?
                  AND backend_identity = ?
                """,
                parameters,
            )
            connection.execute(
                """
                DELETE FROM publication_proofs
                WHERE source_type = ? AND root_identity = ?
                  AND backend_identity = ?
                """,
                parameters,
            )
            rows: list[sqlite3.Row] = fetch_all(
                connection,
                """
                SELECT generation_id, signature_json
                FROM generations
                WHERE source_type = ? AND terminal_state = ?
                """,
                (source_type.value, RunTerminalState.RUNNING.value),
            )
            for row in rows:
                raw_payload = json.loads(column_text(row, "signature_json"))
                if not isinstance(raw_payload, dict):
                    raise RunLedgerCorruptionError(
                        "generation signature is not an object"
                    )
                payload = cast("dict[str, object]", raw_payload)
                if (
                    payload.get("root_identity") != root_identity
                    or payload.get("backend_identity") != backend_identity
                ):
                    continue
                connection.execute(
                    """
                    UPDATE generations
                    SET terminal_state = ?, finalization_phase = ?,
                        terminal_detail = ?, updated_at = ?
                    WHERE generation_id = ?
                    """,
                    (
                        RunTerminalState.REBUILD_INCOMPLETE.value,
                        FinalizationPhase.INGESTING.value,
                        "backing storage explicitly cleared",
                        now,
                        column_text(row, "generation_id"),
                    ),
                )

    def establish_verified_publication(
        self,
        generation_id: str,
        authority: RunAuthority,
        evidence: tuple[ProofEvidence, ...],
    ) -> PublicationProof:
        """Replace one projection's proof after an explicit full rebuild.

        Rebuild is the sole proof-creation path. Its complete evidence is
        accepted here only after storage reconciliation and committed in one
        transaction before generation publication.
        """
        if authority is not RunAuthority.REBUILD:
            raise PermissionError("verified publication requires rebuild authority")
        if any(not isinstance(item, ProofEvidence) for item in evidence):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime boundary
            raise TypeError("evidence must contain only ProofEvidence values")
        paths = tuple(item.rel_path for item in evidence)
        if len(set(paths)) != len(paths):
            raise ValueError("verified publication evidence paths must be unique")
        point_ids = tuple(point for item in evidence for point in item.point_ids)
        if len(set(point_ids)) != len(point_ids):
            raise ValueError("verified publication point ids must be unique")
        committed_at = time.time()
        return in_ledger_transaction(
            self.path,
            lambda connection: self._establish_verified_publication_body(
                connection,
                generation_id,
                evidence,
                point_ids,
                committed_at,
            ),
        )

    def _establish_verified_publication_body(
        self,
        connection: sqlite3.Connection,
        generation_id: str,
        evidence: tuple[ProofEvidence, ...],
        point_ids: tuple[str, ...],
        committed_at: float,
    ) -> PublicationProof:
        generation = self._generation_from_row(
            self._require_mutable_generation(connection, generation_id)
        )
        if generation.signature.operation is not RunOperation.FULL:
            raise RunLedgerStateError(
                "verified publication requires a full rebuild generation"
            )
        if generation.finalization_phase not in {
            FinalizationPhase.INGESTING,
            FinalizationPhase.STALE_RECONCILED,
        }:
            raise RunLedgerStateError(
                "verified publication must precede metadata publication"
            )
        key = compatibility_for_generation(generation)
        stable = stable_parameters(key)
        if (
            fetch_one(
                connection,
                f"""
            SELECT 1 FROM publication_receipts
            WHERE source_type = ? AND root_identity = ?
              AND backend_identity = ? AND collection_identity = ?
              AND {OPEN_RECEIPT_SQL}
            LIMIT 1
            """,
                stable,
            )
            is not None
        ):
            raise RunLedgerStateError(
                "cannot replace publication proof while a receipt is open"
            )
        previous = proof_row(connection, key)
        if previous is not None:
            existing = proof_from_row(previous)
            if (
                existing.generation_id == generation_id
                and existing.compatibility_key == key
                and existing.provenance is ProofProvenance.VERIFIED
            ):
                return existing
        revision = 0 if previous is None else column_int(previous, "revision") + 1
        sequence = (
            0 if previous is None else column_int(previous, "reservation_sequence") + 1
        )
        connection.execute(
            """
                DELETE FROM publication_proofs
                WHERE source_type = ? AND root_identity = ?
                  AND backend_identity = ? AND collection_identity = ?
                """,
            stable,
        )
        aggregate = ProofAggregate(
            indexed_identities=len(evidence),
            retained_points=len(point_ids),
        )
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
                *stable,
                key.storage_schema,
                key.payload_schema,
                key.embedding_schema_identity,
                key.chunking_schema_identity,
                key.membership_identity,
                key.content_identity,
                key.policy_identity,
                generation_id,
                revision,
                sequence,
                aggregate.indexed_identities,
                aggregate.retained_points,
                ProofProvenance.VERIFIED.value,
                committed_at,
                committed_at,
            ),
        )
        connection.executemany(
            """
                INSERT INTO publication_evidence (
                    source_type, root_identity, backend_identity,
                    collection_identity, rel_path, content_identity,
                    evidence_generation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
            (
                (*stable, item.rel_path, item.content_identity, generation_id)
                for item in evidence
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
                (*stable, item.rel_path, ordinal, point_id)
                for item in evidence
                for ordinal, point_id in enumerate(item.point_ids)
            ),
        )
        return PublicationProof(
            revision=revision,
            reservation_sequence=sequence,
            compatibility_key=key,
            generation_id=generation_id,
            aggregate=aggregate,
            provenance=ProofProvenance.VERIFIED,
            committed_at=committed_at,
            verified_at=committed_at,
        )

    def assert_generation_proof_committed(
        self,
        connection: sqlite3.Connection,
        generation_id: str,
    ) -> None:
        """Refuse a caller-owned finalization snapshot without current proof."""
        generation = self._generation_from_row(
            self._require_mutable_generation(connection, generation_id)
        )
        signature = generation.signature
        stable = (
            signature.source_type.value,
            signature.root_identity,
            signature.backend_identity,
            signature.collection_identity,
        )
        proof_row: sqlite3.Row | None = fetch_one(
            connection,
            """
            SELECT * FROM publication_proofs
            WHERE source_type = ? AND root_identity = ?
              AND backend_identity = ? AND collection_identity = ?
            """,
            stable,
        )
        if proof_row is None:
            raise RunLedgerStateError(
                "publication proof must commit before generation finalization"
            )
        proof = proof_from_row(proof_row)
        if proof.compatibility_key != compatibility_for_generation(generation):
            raise RunLedgerStateError(
                "publication proof is incompatible with generation finalization"
            )
        if proof.generation_id != generation.generation_id:
            raise RunLedgerStateError(
                "publication proof must commit before generation finalization"
            )
        open_receipt: sqlite3.Row | None = fetch_one(
            connection,
            f"""
            SELECT receipt_id FROM publication_receipts
            WHERE source_type = ? AND root_identity = ?
              AND backend_identity = ? AND collection_identity = ?
              AND {OPEN_RECEIPT_SQL}
            LIMIT 1
            """,
            stable,
        )
        if open_receipt is not None:
            raise RunLedgerStateError(
                "publication proof must close its receipt before generation "
                "finalization"
            )
        latest_receipt: sqlite3.Row | None = fetch_one(
            connection,
            """
            SELECT * FROM publication_receipts
            WHERE generation_id = ?
            ORDER BY reservation_sequence DESC, receipt_id DESC
            LIMIT 1
            """,
            (generation.generation_id,),
        )
        if latest_receipt is None:
            if proof.provenance is not ProofProvenance.VERIFIED:
                raise RunLedgerStateError(
                    "delta-derived publication proof requires its committed receipt"
                )
            return
        try:
            receipt_state = ProofReceiptState(column_text(latest_receipt, "state"))
            receipt_key = publication_compatibility_from_row(latest_receipt)
        except (KeyError, TypeError, ValueError) as exc:
            receipt_corrupt("stored publication receipt header is malformed", exc)
        if (
            receipt_state is not ProofReceiptState.COMMITTED
            or receipt_key != proof.compatibility_key
            or column_int(latest_receipt, "target_revision") != proof.revision
            or column_int(latest_receipt, "reservation_sequence")
            != proof.reservation_sequence
            or proof.provenance is not ProofProvenance.DELTA_DERIVED
        ):
            raise RunLedgerStateError(
                "publication receipt must commit the current proof before generation "
                "finalization"
            )
