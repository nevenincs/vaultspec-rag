"""Run-ledger recovery, source-reset intent and confirmed compensation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._file_state import validate_rel_path
from ._publication_proof import ProofMutationState, ProofReceiptState
from ._run_ledger_models import (
    RESUMABLE_STATES,
    FinalizationPhase,
    RunLedgerStateError,
    column_text,
    fetch_all,
    fetch_one,
    in_ledger_transaction,
    ledger_connection,
    ledger_transaction,
)
from ._run_ledger_publication_storage import (
    hydrate_receipt,
    proof_from_row,
    receipt_row_by_id,
    require_proof_row,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from ._publication_proof import ProofCompatibilityKey
    from ._run_ledger_models import (
        GenerationRow,
        PublicationMutationUnit,
        PublicationProof,
        PublicationReceipt,
        RunGeneration,
        RunSignature,
    )


def _retained_after_restoration(
    receipt: PublicationReceipt, restored_paths: frozenset[str]
) -> list[PublicationMutationUnit]:
    """Remove only confirmed compensation, retaining every other mutation in order."""
    retained: list[PublicationMutationUnit] = []
    for item in receipt.mutations:
        if item.unit.rel_path not in restored_paths:
            retained.append(item)
        elif item.state is not ProofMutationState.CONFIRMED:
            raise RunLedgerStateError("restored paths must be storage confirmed")
    return retained


def _mark_storage_reset_paths(
    connection: sqlite3.Connection, generation_id: str, paths: tuple[str, ...]
) -> None:
    for path in paths:
        validate_rel_path(path)
    connection.executemany(
        "INSERT OR IGNORE INTO file_state_tombstones (generation_id, "
        "rel_path) VALUES (?, ?)",
        [(generation_id, path) for path in paths],
    )


class RunLedgerRecoveryMethods:
    if TYPE_CHECKING:
        path: Path

        @staticmethod
        def _require_mutable_generation(
            connection: sqlite3.Connection, generation_id: str
        ) -> GenerationRow: ...

        @staticmethod
        def _generation_from_row(row: GenerationRow) -> RunGeneration: ...

        def _validate_receipt_authority(
            self,
            connection: sqlite3.Connection,
            receipt: PublicationReceipt,
        ) -> PublicationProof: ...

        def _require_compatible_receipt_generation(
            self,
            connection: sqlite3.Connection,
            generation_id: str,
            key: ProofCompatibilityKey,
            proof: PublicationProof,
            *,
            rebuild_signature: RunSignature | None = None,
        ) -> RunGeneration: ...

    def generation_storage_reset_paths(self, generation_id: str) -> tuple[str, ...]:
        """Read source-reset intent from the existing generation tombstones."""
        with ledger_connection(self.path) as connection:
            rows: list[sqlite3.Row] = fetch_all(
                connection,
                "SELECT rel_path FROM file_state_tombstones "
                "WHERE generation_id = ? ORDER BY rel_path",
                (generation_id,),
            )
            return tuple(column_text(row, "rel_path") for row in rows)

    def begin_generation_storage_reset(
        self, generation_id: str, paths: tuple[str, ...]
    ) -> None:
        """Fence resumed full-generation evidence before removing its storage."""
        with ledger_transaction(self.path) as connection:
            generation = self._require_mutable_generation(connection, generation_id)
            if not self._generation_from_row(generation).signature.clean:
                raise RunLedgerStateError("generation storage reset requires a rebuild")
            if generation["finalization_phase"] != FinalizationPhase.INGESTING.value:
                raise RunLedgerStateError(
                    "storage reset requires an ingesting generation"
                )
            _mark_storage_reset_paths(connection, generation_id, paths)

    def finish_generation_storage_reset(
        self, generation_id: str, paths: tuple[str, ...]
    ) -> None:
        """Release reset intent only after the superseded upsert units are gone."""
        with ledger_transaction(self.path) as connection:
            self._require_mutable_generation(connection, generation_id)
            for path in paths:
                row = fetch_one(
                    connection,
                    "SELECT 1 FROM commit_units WHERE generation_id = ? "
                    "AND rel_path = ? AND unit_kind = 'upsert' LIMIT 1",
                    (generation_id, path),
                )
                if row is not None:
                    raise RunLedgerStateError(
                        "storage reset still has retained upserts"
                    )
                connection.execute(
                    "DELETE FROM file_state_tombstones "
                    "WHERE generation_id = ? AND rel_path = ?",
                    (generation_id, path),
                )

    def publication_replay_paths(self, receipt_id: str) -> tuple[str, ...]:
        """Return durable reset paths owned by this unfinished receipt."""
        with ledger_connection(self.path) as connection:
            row = receipt_row_by_id(connection, receipt_id)
            if row is None:
                raise KeyError(receipt_id)
            rows: list[sqlite3.Row] = fetch_all(
                connection,
                "SELECT rel_path FROM file_state_tombstones "
                "WHERE generation_id = ? AND rel_path NOT IN "
                "(SELECT rel_path FROM commit_units WHERE generation_id = ? "
                "AND unit_kind = 'delete_path') ORDER BY rel_path",
                (column_text(row, "generation_id"), column_text(row, "generation_id")),
            )
            return tuple(column_text(item, "rel_path") for item in rows)

    def resume_publication_generation(self, receipt_id: str) -> RunGeneration:
        """Resume exact journal repair without retiring its still-open receipt."""

        def body(connection: sqlite3.Connection) -> RunGeneration:
            row = receipt_row_by_id(connection, receipt_id)
            if row is None:
                raise KeyError(receipt_id)
            receipt = hydrate_receipt(connection, row)
            existing = fetch_one(
                connection,
                "SELECT * FROM generations WHERE generation_id = ?",
                (receipt.generation_id,),
            )
            if (
                existing is None
                or column_text(existing, "terminal_state") not in RESUMABLE_STATES
            ):
                raise RunLedgerStateError("publication generation is not resumable")
            connection.execute(
                "UPDATE generations SET terminal_state = 'running', "
                "terminal_detail = NULL, consecutive_failures = 0 WHERE "
                "generation_id = ?",
                (receipt.generation_id,),
            )
            if receipt.state is ProofReceiptState.COMMITTED:
                proof = proof_from_row(
                    require_proof_row(connection, receipt.compatibility_key)
                )
                if (
                    proof.generation_id != receipt.generation_id
                    or proof.revision != receipt.target_revision
                ):
                    raise RunLedgerStateError(
                        "committed receipt no longer owns its proof"
                    )
                generation = self._generation_from_row(
                    self._require_mutable_generation(connection, receipt.generation_id)
                )
            else:
                proof = self._validate_receipt_authority(connection, receipt)
                generation = self._require_compatible_receipt_generation(
                    connection, receipt.generation_id, receipt.compatibility_key, proof
                )
            return self._generation_from_row(
                self._require_mutable_generation(connection, generation.generation_id)
            )

        return in_ledger_transaction(self.path, body)

    def clear_publication_replay_markers(self, receipt_id: str) -> None:
        """Finish replay discovery while retaining confirmed deletion tombstones."""
        with ledger_transaction(self.path) as connection:
            row = receipt_row_by_id(connection, receipt_id)
            if row is None:
                raise KeyError(receipt_id)
            receipt = hydrate_receipt(connection, row)
            self._validate_receipt_authority(connection, receipt)
            connection.execute(
                "DELETE FROM file_state_tombstones WHERE generation_id = ? "
                "AND rel_path NOT IN (SELECT rel_path FROM commit_units "
                "WHERE generation_id = ? AND unit_kind = 'delete_path')",
                (receipt.generation_id, receipt.generation_id),
            )

    def begin_publication_storage_reset(
        self, receipt_id: str, paths: tuple[str, ...]
    ) -> None:
        """Fence forward completion before compensating any uncertain storage."""
        with ledger_transaction(self.path) as connection:
            row = receipt_row_by_id(connection, receipt_id)
            if row is None:
                raise KeyError(receipt_id)
            receipt = hydrate_receipt(connection, row)
            self._validate_receipt_authority(connection, receipt)
            _mark_storage_reset_paths(connection, receipt.generation_id, paths)

    def reopen_publication_after_storage_reset(
        self, receipt_id: str, paths: tuple[str, ...]
    ) -> PublicationReceipt:
        """Retain replay intent after the caller removed every affected point.

        The receipt still fences its unchanged parent. A crash before this
        transaction leaves original point membership for idempotent deletion;
        a crash after it leaves tombstones forcing ordinary source ingestion.
        """

        def body(connection: sqlite3.Connection) -> PublicationReceipt:
            row = receipt_row_by_id(connection, receipt_id)
            if row is None:
                raise KeyError(receipt_id)
            receipt = hydrate_receipt(connection, row)
            if receipt.state not in {
                ProofReceiptState.RESERVED,
                ProofReceiptState.SEALED,
            }:
                raise RunLedgerStateError(
                    "only a forward receipt can restart ingestion"
                )
            self._validate_receipt_authority(connection, receipt)
            if not {item.unit.rel_path for item in receipt.mutations}.issubset(paths):
                raise RunLedgerStateError(
                    "reset must retain every affected receipt path"
                )
            connection.execute(
                "DELETE FROM publication_receipt_deltas WHERE receipt_id = ?",
                (receipt_id,),
            )
            connection.execute(
                "UPDATE publication_receipts SET state = 'reserved', sealed_at = "
                "NULL WHERE receipt_id = ?",
                (receipt_id,),
            )
            connection.execute(
                "DELETE FROM publication_mutation_units WHERE receipt_id = ?",
                (receipt_id,),
            )
            connection.execute(
                "UPDATE publication_receipts SET next_mutation_ordinal = 0 WHERE "
                "receipt_id = ?",
                (receipt_id,),
            )
            for rel_path in paths:
                for table in ("commit_units", "file_states"):
                    connection.execute(
                        f"DELETE FROM {table} WHERE generation_id = ? AND rel_path = ?",
                        (receipt.generation_id, rel_path),
                    )
                connection.execute(
                    "INSERT OR IGNORE INTO file_state_tombstones (generation_id, "
                    "rel_path) VALUES (?, ?)",
                    (receipt.generation_id, rel_path),
                )
            refreshed = receipt_row_by_id(connection, receipt_id)
            assert refreshed is not None
            return hydrate_receipt(connection, refreshed)

        return in_ledger_transaction(self.path, body)

    def discard_restored_publication_paths(
        self, receipt_id: str, paths: tuple[str, ...]
    ) -> PublicationReceipt:
        """Forget confirmed compensation after exact parent evidence was restored."""

        def body(connection: sqlite3.Connection) -> PublicationReceipt:
            row = receipt_row_by_id(connection, receipt_id)
            if row is None:
                raise KeyError(receipt_id)
            receipt = hydrate_receipt(connection, row)
            if receipt.state is not ProofReceiptState.RESERVED:
                raise RunLedgerStateError("restored paths require an unsealed receipt")
            self._validate_receipt_authority(connection, receipt)
            retained = _retained_after_restoration(receipt, frozenset(paths))
            connection.execute(
                "DELETE FROM publication_mutation_units WHERE receipt_id = ?",
                (receipt_id,),
            )
            for ordinal, item in enumerate(retained):
                unit = item.unit
                connection.execute(
                    "INSERT INTO publication_mutation_units (receipt_id, "
                    "mutation_ordinal, sealed_ordinal, unit_id, rel_path, unit_kind, "
                    "source_digest, segment_ordinal, is_file_end, state, "
                    "prepared_at, applied_at, confirmed_at) VALUES (?, ?, NULL, ?, "
                    "?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        receipt_id,
                        ordinal,
                        unit.identity,
                        unit.rel_path,
                        unit.kind.value,
                        unit.source_digest,
                        unit.segment_ordinal,
                        int(unit.is_file_end),
                        item.state.value,
                        item.prepared_at,
                        item.applied_at,
                        item.confirmed_at,
                    ),
                )
                connection.executemany(
                    "INSERT INTO publication_mutation_points (receipt_id, "
                    "mutation_ordinal, point_ordinal, point_id) VALUES (?, ?, ?, ?)",
                    [
                        (receipt_id, ordinal, point_ordinal, point)
                        for point_ordinal, point in enumerate(unit.point_ids)
                    ],
                )
            connection.execute(
                "UPDATE publication_receipts SET next_mutation_ordinal = ? WHERE "
                "receipt_id = ?",
                (len(retained), receipt_id),
            )
            for rel_path in paths:
                for table in ("commit_units", "file_states", "file_state_tombstones"):
                    connection.execute(
                        f"DELETE FROM {table} WHERE generation_id = ? AND rel_path = ?",
                        (receipt.generation_id, rel_path),
                    )
            refreshed = receipt_row_by_id(connection, receipt_id)
            assert refreshed is not None
            return hydrate_receipt(connection, refreshed)

        return in_ledger_transaction(self.path, body)
