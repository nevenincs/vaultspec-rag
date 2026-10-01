"""Canonical publication evidence reads and proof revision fencing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .._job_errors import FULL_REINDEX_REQUIRED_PHRASE
from .._source_types import PublicSourceType
from ._file_state import validate_rel_path
from ._publication_proof import (
    ProofCompatibilityKey,
    ProofEvidence,
    ProofIncompatibleError,
    ProofMissingError,
    ProofParentMismatchError,
    ProofReadConflictError,
    ProofReadToken,
    ProofReceiptState,
)
from ._run_ledger_models import (
    FETCH_BATCH,
    GenerationRow,
    PublicationProof,
    PublicationReceipt,
    RunLedgerCorruptionError,
    RunLedgerStateError,
    column_int,
    column_text,
    fetch_all,
    fetch_one,
    ledger_connection,
)
from ._run_ledger_publication_identity import (
    compatibility_for_generation,
    publication_compatibility_from_row,
    stable_parameters,
)
from ._run_ledger_publication_storage import (
    OPEN_RECEIPT_SQL,
    begin_read,
    current_proof_snapshot_row,
    evidence_rows_for_paths,
    has_open_receipt,
    hydrate_receipt,
    proof_from_row,
    proof_row,
    proof_snapshot_row,
    receipt_corrupt,
    receipt_row_by_id,
    require_exact_key,
    require_proof_row,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from ._run_ledger_models import RunGeneration, RunSignature


class RunLedgerPublicationReadMethods:
    """Own canonical evidence reads and proof revision fences."""

    if TYPE_CHECKING:
        path: Path

        @staticmethod
        def _generation_from_row(row: GenerationRow) -> RunGeneration: ...

        def _require_compatible_receipt_generation(
            self,
            connection: sqlite3.Connection,
            generation_id: str,
            key: ProofCompatibilityKey,
            proof: PublicationProof,
            *,
            rebuild_signature: RunSignature | None = None,
        ) -> RunGeneration: ...

    def _require_effective_read_authority(
        self,
        connection: sqlite3.Connection,
        receipt_id: str,
        generation_id: str,
    ) -> tuple[ProofCompatibilityKey, int, int]:
        """Validate the sealed forward receipt that authorizes one local read."""
        if not isinstance(receipt_id, str) or not receipt_id.strip():  # pyright: ignore[reportUnnecessaryIsInstance] - runtime boundary
            raise ValueError("receipt_id must be non-empty")
        if not isinstance(generation_id, str) or not generation_id.strip():  # pyright: ignore[reportUnnecessaryIsInstance] - runtime boundary
            raise ValueError("generation_id must be non-empty")
        row = receipt_row_by_id(connection, receipt_id)
        if row is None:
            raise KeyError(receipt_id)
        if column_text(row, "generation_id") != generation_id:
            raise RunLedgerStateError(
                "publication receipt belongs to a different generation"
            )
        try:
            state = ProofReceiptState(column_text(row, "state"))
            key = publication_compatibility_from_row(row)
        except (KeyError, TypeError, ValueError) as exc:
            receipt_corrupt("stored publication receipt header is malformed", exc)
        if state is not ProofReceiptState.SEALED:
            raise RunLedgerStateError(
                "effective publication reads require a sealed forward receipt"
            )
        proof_row = require_proof_row(connection, key)
        proof = proof_from_row(proof_row)
        parent_revision = column_int(row, "parent_revision")
        reservation_sequence = column_int(row, "reservation_sequence")
        if proof.revision != parent_revision:
            raise ProofParentMismatchError(
                "publication proof no longer matches the receipt parent"
            )
        if proof.reservation_sequence != reservation_sequence:
            raise ProofReadConflictError(
                "publication reservation sequence no longer matches the receipt"
            )
        self._require_compatible_receipt_generation(
            connection,
            generation_id,
            key,
            proof,
        )
        return key, parent_revision, reservation_sequence

    @staticmethod
    def _publication_evidence_in_snapshot(
        connection: sqlite3.Connection,
        key: ProofCompatibilityKey,
        rel_paths: tuple[str, ...],
    ) -> dict[str, ProofEvidence]:
        """Read canonical heads without opening a second ledger snapshot."""
        return evidence_rows_for_paths(connection, key, rel_paths)

    def publication_evidence_for_paths(
        self,
        key: ProofCompatibilityKey,
        rel_paths: tuple[str, ...],
    ) -> dict[str, ProofEvidence]:
        """Return one bounded path-evidence page from a single snapshot."""
        if len(rel_paths) > FETCH_BATCH:
            raise ValueError(
                f"publication-evidence lookup accepts at most {FETCH_BATCH} paths"
            )
        for rel_path in rel_paths:
            validate_rel_path(rel_path)
        unique_paths = tuple(dict.fromkeys(rel_paths))
        with ledger_connection(self.path) as connection:
            begin_read(connection)
            try:
                require_proof_row(connection, key)
                return evidence_rows_for_paths(connection, key, unique_paths)
            finally:
                connection.rollback()

    def publication_evidence_page(
        self,
        key: ProofCompatibilityKey,
        *,
        after_path: str | None = None,
        limit: int = FETCH_BATCH,
    ) -> dict[str, ProofEvidence]:
        """Return one keyset-paginated page of canonical path evidence."""
        if limit <= 0 or limit > FETCH_BATCH:
            raise ValueError(f"limit must be between 1 and {FETCH_BATCH}")
        if after_path is not None:
            validate_rel_path(after_path)
        with ledger_connection(self.path) as connection:
            begin_read(connection)
            try:
                require_proof_row(connection, key)
                parameters: tuple[object, ...] = (*stable_parameters(key), limit)
                after_clause = ""
                if after_path is not None:
                    after_clause = " AND rel_path > ?"
                    parameters = (*stable_parameters(key), after_path, limit)
                rows: list[sqlite3.Row] = fetch_all(
                    connection,
                    f"""
                    SELECT rel_path
                    FROM publication_evidence
                    WHERE source_type = ? AND root_identity = ?
                      AND backend_identity = ? AND collection_identity = ?
                      {after_clause}
                    ORDER BY rel_path
                    LIMIT ?
                    """,
                    parameters,
                )
                paths = tuple(column_text(row, "rel_path") for row in rows)
                return evidence_rows_for_paths(connection, key, paths)
            finally:
                connection.rollback()

    def publication_point_ids_for_candidates(
        self,
        key: ProofCompatibilityKey,
        point_ids: tuple[str, ...],
    ) -> frozenset[str]:
        """Return retained IDs from one bounded backend candidate page."""
        if len(point_ids) > FETCH_BATCH:
            raise ValueError(
                f"publication-point lookup accepts at most {FETCH_BATCH} IDs"
            )
        if any(
            not isinstance(point_id, str) or not point_id.strip()  # pyright: ignore[reportUnnecessaryIsInstance] - runtime boundary
            for point_id in point_ids
        ):
            raise ValueError("point_ids must contain only non-empty strings")
        unique_ids = tuple(dict.fromkeys(point_ids))
        with ledger_connection(self.path) as connection:
            begin_read(connection)
            try:
                require_proof_row(connection, key)
                if not unique_ids:
                    return frozenset()
                placeholders = ", ".join("?" for _point in unique_ids)
                rows: list[sqlite3.Row] = fetch_all(
                    connection,
                    f"""
                    SELECT point_id FROM publication_points
                    WHERE source_type = ? AND root_identity = ?
                      AND backend_identity = ? AND collection_identity = ?
                      AND point_id IN ({placeholders})
                    """,
                    (*stable_parameters(key), *unique_ids),
                )
                return frozenset(column_text(row, "point_id") for row in rows)
            finally:
                connection.rollback()

    def active_publication_receipt(
        self,
        key: ProofCompatibilityKey,
    ) -> PublicationReceipt | None:
        """Return the one open receipt for a stable projection, if present."""
        with ledger_connection(self.path) as connection:
            begin_read(connection)
            try:
                row: sqlite3.Row | None = fetch_one(
                    connection,
                    f"""
                    SELECT * FROM publication_receipts
                    WHERE source_type = ? AND root_identity = ?
                      AND backend_identity = ? AND collection_identity = ?
                      AND {OPEN_RECEIPT_SQL}
                    """,
                    stable_parameters(key),
                )
                if row is None:
                    return None
                require_exact_key(row, key, subject="active publication receipt")
                receipt = hydrate_receipt(connection, row)
                proof_record = proof_row(connection, key)
                if proof_record is None:
                    receipt_corrupt("active publication receipt has no current proof")
                require_exact_key(proof_record, key, subject="publication proof")
                proof = proof_from_row(proof_record)
                if (
                    receipt.parent_revision != proof.revision
                    or receipt.reservation_sequence != proof.reservation_sequence
                ):
                    receipt_corrupt(
                        "active publication receipt does not match the current proof"
                    )
                return receipt
            finally:
                connection.rollback()

    def acquire_publication_read_token(
        self,
        key: ProofCompatibilityKey,
    ) -> ProofReadToken:
        """Acquire one proof revision only when no receipt is open."""
        with ledger_connection(self.path) as connection:
            row = proof_snapshot_row(connection, key)
        if row is None:
            raise ProofMissingError("publication proof does not exist")
        actual = require_exact_key(row, key, subject="publication proof")
        return ProofReadToken.from_snapshot(
            compatibility_key=actual,
            revision=column_int(row, "revision"),
            reservation_sequence=column_int(row, "reservation_sequence"),
            has_open_receipt=has_open_receipt(row),
        )

    def acquire_current_publication_snapshot(
        self,
        *,
        source_type: PublicSourceType,
        root_identity: str,
        backend_identity: str,
    ) -> tuple[PublicationProof, ProofReadToken]:
        """Atomically select the current proof and its receipt-free read token.

        Audit callers know the stable storage projection but deliberately do
        not infer membership, content, policy, or pipeline identities from the
        current source tree. Those values are part of the proof being audited,
        so this lookup reads them from the one canonical proof row in the same
        SQLite snapshot that checks for an open publication receipt.
        """
        if not isinstance(source_type, PublicSourceType):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime boundary
            raise TypeError("source_type must be a PublicSourceType")
        if source_type is PublicSourceType.COMBINED:
            raise ValueError("publication proof selection requires one concrete source")
        for name, value in (
            ("root_identity", root_identity),
            ("backend_identity", backend_identity),
        ):
            if not isinstance(value, str) or not value.strip():  # pyright: ignore[reportUnnecessaryIsInstance] - runtime boundary
                raise ValueError(f"{name} must be non-empty")
        current_identity: tuple[object, object, object] = (
            source_type.value,
            root_identity,
            backend_identity,
        )
        with ledger_connection(self.path) as connection:
            begin_read(connection)
            try:
                row = current_proof_snapshot_row(connection, current_identity)
                if row is None:
                    incompatible: sqlite3.Row | None = fetch_one(
                        connection,
                        """
                        SELECT 1 FROM publication_proofs
                        WHERE source_type = ? AND root_identity = ?
                        LIMIT 1
                        """,
                        (source_type.value, root_identity),
                    )
                    if incompatible is not None:
                        raise ProofIncompatibleError(
                            "publication proof exists for a different backend identity"
                        )
                    raise ProofMissingError(
                        "publication proof does not exist; "
                        f"{FULL_REINDEX_REQUIRED_PHRASE}"
                    )
                proof = proof_from_row(row)
                generation_row: GenerationRow | None = fetch_one(
                    connection,
                    "SELECT * FROM generations WHERE generation_id = ?",
                    (proof.generation_id,),
                )
                if generation_row is None:
                    raise RunLedgerCorruptionError(
                        "publication proof cites a missing generation"
                    )
                generation = self._generation_from_row(generation_row)
                if compatibility_for_generation(generation) != proof.compatibility_key:
                    raise ProofIncompatibleError(
                        "publication proof generation ancestry is incompatible"
                    )
                open_receipt_exists = has_open_receipt(row)
                if open_receipt_exists:
                    receipt_row: sqlite3.Row | None = fetch_one(
                        connection,
                        f"""
                        SELECT * FROM publication_receipts
                        WHERE source_type = ? AND root_identity = ?
                          AND backend_identity = ? AND collection_identity = ?
                          AND {OPEN_RECEIPT_SQL}
                        """,
                        stable_parameters(proof.compatibility_key),
                    )
                    if receipt_row is None:
                        receipt_corrupt(
                            "open publication receipt snapshot is inconsistent"
                        )
                    receipt = hydrate_receipt(connection, receipt_row)
                    if (
                        receipt.compatibility_key != proof.compatibility_key
                        or receipt.parent_revision != proof.revision
                        or receipt.reservation_sequence != proof.reservation_sequence
                    ):
                        receipt_corrupt(
                            "open publication receipt does not match the current proof"
                        )
                token = ProofReadToken.from_snapshot(
                    compatibility_key=proof.compatibility_key,
                    revision=proof.revision,
                    reservation_sequence=proof.reservation_sequence,
                    has_open_receipt=open_receipt_exists,
                )
                return proof, token
            finally:
                connection.rollback()

    def validate_publication_read_token(self, token: ProofReadToken) -> None:
        """Reject a backend read if proof or open-receipt state changed."""
        if not isinstance(token, ProofReadToken):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime boundary
            raise TypeError("token must be a ProofReadToken")
        with ledger_connection(self.path) as connection:
            row = proof_snapshot_row(connection, token.compatibility_key)
        if row is None:
            raise ProofReadConflictError(
                "publication proof disappeared during the backend read"
            )
        try:
            actual = publication_compatibility_from_row(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise RunLedgerCorruptionError(
                "stored publication proof compatibility key is malformed"
            ) from exc
        token.validate(
            compatibility_key=actual,
            revision=column_int(row, "revision"),
            reservation_sequence=column_int(row, "reservation_sequence"),
            has_open_receipt=has_open_receipt(row),
        )
