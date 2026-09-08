"""Bounded publication-proof reads and receipt-backed proof commits."""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Never

from .._source_types import PublicSourceType
from ._file_state import validate_rel_path
from ._publication_proof import (
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
    ProofReadToken,
    ProofRebuildRequiredError,
    ProofReceiptState,
    ProofUnverifiableReason,
)
from ._run_ledger_models import (
    FETCH_BATCH,
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    GenerationRow,
    PublicationMutationUnit,
    PublicationProof,
    PublicationReceipt,
    RunGeneration,
    RunLedgerCorruptionError,
    RunLedgerStateError,
    column_int,
    column_text,
    fetch_all,
    fetch_one,
    in_ledger_transaction,
    ledger_connection,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


_OPEN_RECEIPT_SQL = "state IN ('reserved', 'sealed')"


def _stable_parameters(key: ProofCompatibilityKey) -> tuple[object, ...]:
    return (
        key.source_type.value,
        key.root_identity,
        key.backend_identity,
        key.collection_identity,
    )


def _row_number(row: sqlite3.Row, key: str) -> float:
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"column {key!r} must be numeric")
    return float(value)


def _row_optional_number(row: sqlite3.Row, key: str) -> float | None:
    value = row[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"column {key!r} must be numeric or null")
    return float(value)


def _row_optional_text(row: sqlite3.Row, key: str) -> str | None:
    value = row[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"column {key!r} must be text or null")
    return value


def _compatibility_from_row(row: sqlite3.Row) -> ProofCompatibilityKey:
    return ProofCompatibilityKey(
        source_type=PublicSourceType(column_text(row, "source_type")),
        root_identity=column_text(row, "root_identity"),
        backend_identity=column_text(row, "backend_identity"),
        collection_identity=column_text(row, "collection_identity"),
        storage_schema=column_int(row, "storage_schema"),
        payload_schema=column_int(row, "payload_schema"),
        embedding_schema_identity=column_text(row, "embedding_schema_identity"),
        chunking_schema_identity=column_text(row, "chunking_schema_identity"),
        membership_identity=column_text(row, "membership_identity"),
        content_identity=column_text(row, "content_identity"),
        policy_identity=column_text(row, "policy_identity"),
    )


def _proof_from_row(row: sqlite3.Row) -> PublicationProof:
    try:
        return PublicationProof(
            revision=column_int(row, "revision"),
            reservation_sequence=column_int(row, "reservation_sequence"),
            compatibility_key=_compatibility_from_row(row),
            generation_id=column_text(row, "generation_id"),
            aggregate=ProofAggregate(
                indexed_identities=column_int(row, "indexed_identities"),
                retained_points=column_int(row, "retained_points"),
            ),
            provenance=ProofProvenance(column_text(row, "provenance")),
            committed_at=_row_number(row, "committed_at"),
            verified_at=_row_optional_number(row, "verified_at"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RunLedgerCorruptionError("stored publication proof is malformed") from exc


def _require_exact_key(
    row: sqlite3.Row,
    expected: ProofCompatibilityKey,
    *,
    subject: str,
) -> ProofCompatibilityKey:
    try:
        actual = _compatibility_from_row(row)
    except (KeyError, TypeError, ValueError) as exc:
        raise RunLedgerCorruptionError(
            f"stored {subject} compatibility key is malformed"
        ) from exc
    if actual != expected:
        raise ProofIncompatibleError(
            f"{subject} exists for the stable identity but is incompatible"
        )
    return actual


def _proof_row(
    connection: sqlite3.Connection,
    key: ProofCompatibilityKey,
) -> sqlite3.Row | None:
    return fetch_one(
        connection,
        """
        SELECT * FROM publication_proofs
        WHERE source_type = ? AND root_identity = ?
          AND backend_identity = ? AND collection_identity = ?
        """,
        _stable_parameters(key),
    )


def _require_proof_row(
    connection: sqlite3.Connection,
    key: ProofCompatibilityKey,
) -> sqlite3.Row:
    row = _proof_row(connection, key)
    if row is None:
        raise ProofMissingError("publication proof does not exist")
    _require_exact_key(row, key, subject="publication proof")
    return row


def _begin_read(connection: sqlite3.Connection) -> None:
    # A connection-wide transaction is required whenever a value is hydrated
    # from more than one normalized table. Without it, a writer can commit
    # between child queries and manufacture a mixed receipt or evidence view.
    connection.execute("BEGIN")


def _evidence_rows_for_paths(
    connection: sqlite3.Connection,
    key: ProofCompatibilityKey,
    rel_paths: tuple[str, ...],
) -> dict[str, ProofEvidence]:
    if not rel_paths:
        return {}
    placeholders = ", ".join("?" for _path in rel_paths)
    rows: list[sqlite3.Row] = fetch_all(
        connection,
        f"""
        SELECT evidence.rel_path, evidence.content_identity,
               points.point_ordinal, points.point_id
        FROM publication_evidence AS evidence
        LEFT JOIN publication_points AS points
          ON points.source_type = evidence.source_type
         AND points.root_identity = evidence.root_identity
         AND points.backend_identity = evidence.backend_identity
         AND points.collection_identity = evidence.collection_identity
         AND points.rel_path = evidence.rel_path
        WHERE evidence.source_type = ? AND evidence.root_identity = ?
          AND evidence.backend_identity = ?
          AND evidence.collection_identity = ?
          AND evidence.rel_path IN ({placeholders})
        ORDER BY evidence.rel_path, points.point_ordinal
        """,
        (*_stable_parameters(key), *rel_paths),
    )
    grouped: dict[str, list[tuple[int, str]]] = defaultdict(list)
    content: dict[str, str] = {}
    try:
        for row in rows:
            rel_path = column_text(row, "rel_path")
            stored_content = column_text(row, "content_identity")
            previous = content.setdefault(rel_path, stored_content)
            if previous != stored_content:
                raise ValueError("one evidence path has multiple content identities")
            raw_ordinal = row["point_ordinal"]
            raw_point_id = row["point_id"]
            if raw_ordinal is None or raw_point_id is None:
                raise ValueError("indexed evidence has no retained points")
            if isinstance(raw_ordinal, bool) or not isinstance(raw_ordinal, int):
                raise TypeError("point ordinal must be an integer")
            if not isinstance(raw_point_id, str):
                raise TypeError("point identity must be text")
            grouped[rel_path].append((raw_ordinal, raw_point_id))
        result: dict[str, ProofEvidence] = {}
        for rel_path, points in grouped.items():
            if tuple(ordinal for ordinal, _point in points) != tuple(
                range(len(points))
            ):
                raise ValueError("publication points must use contiguous ordinals")
            result[rel_path] = ProofEvidence(
                rel_path=rel_path,
                content_identity=content[rel_path],
                point_ids=tuple(point for _ordinal, point in points),
            )
        return result
    except (KeyError, TypeError, ValueError) as exc:
        raise RunLedgerCorruptionError(
            "stored publication evidence is malformed"
        ) from exc


def _all_evidence_for_paths(
    connection: sqlite3.Connection,
    key: ProofCompatibilityKey,
    rel_paths: Iterable[str],
) -> dict[str, ProofEvidence]:
    unique_paths = tuple(dict.fromkeys(rel_paths))
    result: dict[str, ProofEvidence] = {}
    for start in range(0, len(unique_paths), FETCH_BATCH):
        page = unique_paths[start : start + FETCH_BATCH]
        result.update(_evidence_rows_for_paths(connection, key, page))
    return result


def _receipt_corrupt(message: str, exc: BaseException | None = None) -> Never:
    error = ProofRebuildRequiredError(
        message,
        reason=ProofUnverifiableReason.CORRUPT_RECEIPT,
    )
    if exc is None:
        raise error
    raise error from exc


def _mutation_rows(
    connection: sqlite3.Connection,
    receipt_id: str,
) -> tuple[PublicationMutationUnit, ...]:
    rows: list[sqlite3.Row] = fetch_all(
        connection,
        """
        SELECT units.*, points.point_ordinal, points.point_id
        FROM publication_mutation_units AS units
        LEFT JOIN publication_mutation_points AS points
          ON points.receipt_id = units.receipt_id
         AND points.mutation_ordinal = units.mutation_ordinal
        WHERE units.receipt_id = ?
        ORDER BY units.mutation_ordinal, points.point_ordinal
        """,
        (receipt_id,),
    )
    if not rows:
        return ()
    by_ordinal: dict[int, list[sqlite3.Row]] = defaultdict(list)
    try:
        for row in rows:
            by_ordinal[column_int(row, "mutation_ordinal")].append(row)
        if tuple(by_ordinal) != tuple(range(len(by_ordinal))):
            raise ValueError("mutation ordinals are not contiguous")
        mutations: list[PublicationMutationUnit] = []
        for ordinal, unit_rows in by_ordinal.items():
            first = unit_rows[0]
            points: list[str] = []
            point_ordinals: list[int] = []
            for row in unit_rows:
                raw_ordinal = row["point_ordinal"]
                raw_point = row["point_id"]
                if raw_ordinal is None or raw_point is None:
                    raise ValueError("mutation unit has no point identities")
                if isinstance(raw_ordinal, bool) or not isinstance(raw_ordinal, int):
                    raise TypeError("mutation point ordinal must be an integer")
                if not isinstance(raw_point, str):
                    raise TypeError("mutation point identity must be text")
                point_ordinals.append(raw_ordinal)
                points.append(raw_point)
            if tuple(point_ordinals) != tuple(range(len(point_ordinals))):
                raise ValueError("mutation point ordinals are not contiguous")
            unit = CommitUnit(
                rel_path=column_text(first, "rel_path"),
                kind=CommitUnitKind(column_text(first, "unit_kind")),
                source_digest=_row_optional_text(first, "source_digest"),
                segment_ordinal=column_int(first, "segment_ordinal"),
                is_file_end=column_int(first, "is_file_end") != 0,
                point_ids=tuple(points),
            )
            if column_text(first, "unit_id") != unit.identity:
                raise ValueError("stored mutation identity is not deterministic")
            sealed_value = first["sealed_ordinal"]
            if sealed_value is not None and (
                isinstance(sealed_value, bool) or not isinstance(sealed_value, int)
            ):
                raise TypeError("sealed ordinal must be an integer or null")
            mutations.append(
                PublicationMutationUnit(
                    ordinal=ordinal,
                    unit=unit,
                    state=ProofMutationState(column_text(first, "state")),
                    prepared_at=_row_number(first, "prepared_at"),
                    applied_at=_row_optional_number(first, "applied_at"),
                    confirmed_at=_row_optional_number(first, "confirmed_at"),
                    sealed_ordinal=sealed_value,
                )
            )
        return tuple(mutations)
    except (KeyError, TypeError, ValueError) as exc:
        _receipt_corrupt("stored publication mutation units are malformed", exc)


def _delta_rows(
    connection: sqlite3.Connection,
    receipt_id: str,
    *,
    parent_revision: int,
) -> tuple[PathDelta, ...]:
    headers: list[sqlite3.Row] = fetch_all(
        connection,
        """
        SELECT * FROM publication_receipt_deltas
        WHERE receipt_id = ? ORDER BY delta_ordinal
        """,
        (receipt_id,),
    )
    point_rows: list[sqlite3.Row] = fetch_all(
        connection,
        """
        SELECT delta_ordinal, evidence_side, point_ordinal, point_id
        FROM publication_receipt_points
        WHERE receipt_id = ?
        ORDER BY delta_ordinal, evidence_side, point_ordinal
        """,
        (receipt_id,),
    )
    try:
        header_ordinals = tuple(column_int(row, "delta_ordinal") for row in headers)
        if header_ordinals != tuple(range(len(headers))):
            raise ValueError("receipt delta ordinals are not contiguous")
        points: dict[tuple[int, str], list[tuple[int, str]]] = defaultdict(list)
        for row in point_rows:
            ordinal = column_int(row, "delta_ordinal")
            side = column_text(row, "evidence_side")
            points[(ordinal, side)].append(
                (column_int(row, "point_ordinal"), column_text(row, "point_id"))
            )
        for values in points.values():
            if tuple(ordinal for ordinal, _point in values) != tuple(
                range(len(values))
            ):
                raise ValueError("receipt point ordinals are not contiguous")
        deltas: list[PathDelta] = []
        for header in headers:
            ordinal = column_int(header, "delta_ordinal")
            rel_path = column_text(header, "rel_path")
            target_rel_path = _row_optional_text(header, "target_rel_path")
            old_content = _row_optional_text(header, "old_content_identity")
            new_content = _row_optional_text(header, "new_content_identity")
            old_points = points.pop((ordinal, "old"), [])
            new_points = points.pop((ordinal, "new"), [])
            if (old_content is None) != (not old_points):
                raise ValueError("old receipt evidence is incomplete")
            if (new_content is None) != (not new_points):
                raise ValueError("new receipt evidence is incomplete")
            old = (
                ProofEvidence(
                    rel_path=rel_path,
                    content_identity=old_content,
                    point_ids=tuple(point for _index, point in old_points),
                )
                if old_content is not None
                else None
            )
            new_path = target_rel_path if target_rel_path is not None else rel_path
            new = (
                ProofEvidence(
                    rel_path=new_path,
                    content_identity=new_content,
                    point_ids=tuple(point for _index, point in new_points),
                )
                if new_content is not None
                else None
            )
            deltas.append(
                PathDelta(
                    outcome=PathOutcome(column_text(header, "outcome")),
                    expected_parent_revision=parent_revision,
                    rel_path=rel_path,
                    target_rel_path=target_rel_path,
                    old=old,
                    new=new,
                )
            )
        if points:
            raise ValueError("receipt points name a missing delta or evidence side")
        return tuple(deltas)
    except (KeyError, TypeError, ValueError) as exc:
        _receipt_corrupt("stored publication deltas are malformed", exc)


def _hydrate_receipt(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> PublicationReceipt:
    try:
        receipt_id = column_text(row, "receipt_id")
        parent_revision = column_int(row, "parent_revision")
        receipt = PublicationReceipt(
            receipt_id=receipt_id,
            reservation_sequence=column_int(row, "reservation_sequence"),
            compatibility_key=_compatibility_from_row(row),
            generation_id=column_text(row, "generation_id"),
            parent_revision=parent_revision,
            target_revision=column_int(row, "target_revision"),
            state=ProofReceiptState(column_text(row, "state")),
            reserved_at=_row_number(row, "reserved_at"),
            mutations=_mutation_rows(connection, receipt_id),
            deltas=_delta_rows(
                connection,
                receipt_id,
                parent_revision=parent_revision,
            ),
            sealed_at=_row_optional_number(row, "sealed_at"),
            committed_at=_row_optional_number(row, "committed_at"),
            rolled_back_at=_row_optional_number(row, "rolled_back_at"),
        )
        return receipt
    except ProofRebuildRequiredError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        _receipt_corrupt("stored publication receipt is malformed", exc)


def _receipt_row_by_id(
    connection: sqlite3.Connection,
    receipt_id: str,
) -> sqlite3.Row | None:
    return fetch_one(
        connection,
        "SELECT * FROM publication_receipts WHERE receipt_id = ?",
        (receipt_id,),
    )


def _proof_snapshot_row(
    connection: sqlite3.Connection,
    key: ProofCompatibilityKey,
) -> sqlite3.Row | None:
    return fetch_one(
        connection,
        f"""
        SELECT proof.*,
               EXISTS(
                   SELECT 1 FROM publication_receipts AS receipt
                   WHERE receipt.source_type = proof.source_type
                     AND receipt.root_identity = proof.root_identity
                     AND receipt.backend_identity = proof.backend_identity
                     AND receipt.collection_identity = proof.collection_identity
                     AND {_OPEN_RECEIPT_SQL.replace("state", "receipt.state")}
               ) AS has_open_receipt
        FROM publication_proofs AS proof
        WHERE proof.source_type = ? AND proof.root_identity = ?
          AND proof.backend_identity = ? AND proof.collection_identity = ?
        """,
        _stable_parameters(key),
    )


def _has_open_receipt(row: sqlite3.Row) -> bool:
    value = column_int(row, "has_open_receipt")
    if value not in {0, 1}:
        raise RunLedgerCorruptionError("open-receipt snapshot is malformed")
    return value != 0


class RunLedgerPublicationMethods:
    """Source-neutral publication proof and receipt operations."""

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
            row = _require_proof_row(connection, key)
        return _proof_from_row(row)

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
            _begin_read(connection)
            try:
                _require_proof_row(connection, key)
                return _evidence_rows_for_paths(connection, key, unique_paths)
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
            _begin_read(connection)
            try:
                _require_proof_row(connection, key)
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
                    (*_stable_parameters(key), *unique_ids),
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
            _begin_read(connection)
            try:
                row: sqlite3.Row | None = fetch_one(
                    connection,
                    f"""
                    SELECT * FROM publication_receipts
                    WHERE source_type = ? AND root_identity = ?
                      AND backend_identity = ? AND collection_identity = ?
                      AND {_OPEN_RECEIPT_SQL}
                    """,
                    _stable_parameters(key),
                )
                if row is None:
                    return None
                _require_exact_key(row, key, subject="active publication receipt")
                receipt = _hydrate_receipt(connection, row)
                proof_row = _proof_row(connection, key)
                if proof_row is None:
                    _receipt_corrupt("active publication receipt has no current proof")
                _require_exact_key(proof_row, key, subject="publication proof")
                proof = _proof_from_row(proof_row)
                if (
                    receipt.parent_revision != proof.revision
                    or receipt.reservation_sequence != proof.reservation_sequence
                ):
                    _receipt_corrupt(
                        "active publication receipt does not match the current proof"
                    )
                return receipt
            finally:
                connection.rollback()

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
            existing = _receipt_row_by_id(connection, receipt_id)
            if existing is not None:
                receipt = _hydrate_receipt(connection, existing)
                if (
                    receipt.compatibility_key == key
                    and receipt.generation_id == generation_id
                    and receipt.parent_revision == expected_parent_revision
                ):
                    return receipt
                raise RunLedgerStateError("publication receipt identity was reused")
            proof_row = _require_proof_row(connection, key)
            proof = _proof_from_row(proof_row)
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
                  AND {_OPEN_RECEIPT_SQL}
                """,
                _stable_parameters(key),
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
                    *_stable_parameters(key),
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
                    parent_revision, target_revision, state, reserved_at,
                    sealed_at, committed_at, rolled_back_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    NULL, NULL, NULL
                )
                """,
                (
                    receipt_id,
                    sequence,
                    *_stable_parameters(key),
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
            row = _receipt_row_by_id(connection, receipt_id)
            assert row is not None
            return _hydrate_receipt(connection, row)

        return in_ledger_transaction(self.path, body)

    def _require_compatible_receipt_generation(
        self,
        connection: sqlite3.Connection,
        generation_id: str,
        key: ProofCompatibilityKey,
        proof: PublicationProof,
    ) -> RunGeneration:
        row = self._require_mutable_generation(connection, generation_id)
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
    ) -> PublicationProof:
        """Commit one sealed, confirmed receipt with an exact revision CAS."""
        if not isinstance(receipt_id, str) or not receipt_id.strip():  # pyright: ignore[reportUnnecessaryIsInstance] - runtime boundary
            raise ValueError("receipt_id must be non-empty")
        committed_at = time.time()

        def body(connection: sqlite3.Connection) -> PublicationProof:
            row = _receipt_row_by_id(connection, receipt_id)
            if row is None:
                raise KeyError(receipt_id)
            receipt = _hydrate_receipt(connection, row)
            if receipt.state is ProofReceiptState.COMMITTED:
                return self._committed_receipt_replay(connection, receipt)
            if receipt.state is ProofReceiptState.ROLLED_BACK:
                raise RunLedgerStateError(
                    "rolled-back publication receipt cannot commit"
                )
            if receipt.state is not ProofReceiptState.SEALED:
                raise RunLedgerStateError(
                    "publication receipt must be sealed before commit"
                )
            receipt_committed_at = max(
                committed_at,
                receipt.sealed_at
                if receipt.sealed_at is not None
                else receipt.reserved_at,
            )
            if not any(delta.changes_proof for delta in receipt.deltas):
                raise RunLedgerStateError("a no-op receipt must not advance the proof")
            if any(
                mutation.state is not ProofMutationState.CONFIRMED
                for mutation in receipt.mutations
            ):
                raise RunLedgerStateError(
                    "publication receipt has unconfirmed mutation units"
                )
            proof_row = _require_proof_row(connection, receipt.compatibility_key)
            proof = _proof_from_row(proof_row)
            if proof.revision != receipt.parent_revision:
                raise ProofParentMismatchError(
                    "publication proof no longer matches the receipt parent"
                )
            if proof.reservation_sequence != receipt.reservation_sequence:
                raise ProofReadConflictError(
                    "publication reservation sequence no longer matches the receipt"
                )
            generation = self._require_compatible_receipt_generation(
                connection,
                receipt.generation_id,
                receipt.compatibility_key,
                proof,
            )
            if generation.finalization_phase is not FinalizationPhase.STALE_RECONCILED:
                raise RunLedgerStateError(
                    "publication proof commits only after stale reconciliation"
                )
            affected_paths = tuple(
                path
                for delta in receipt.deltas
                for path in (
                    delta.rel_path,
                    *((delta.target_rel_path,) if delta.target_rel_path else ()),
                )
            )
            current = _all_evidence_for_paths(
                connection,
                receipt.compatibility_key,
                affected_paths,
            )
            self._validate_receipt_evidence(receipt, current)
            self._validate_new_point_ownership(connection, receipt)
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
                    receipt_committed_at,
                    *_stable_parameters(receipt.compatibility_key),
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
                    receipt_committed_at,
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
                committed_at=receipt_committed_at,
            )

        return in_ledger_transaction(self.path, body)

    @staticmethod
    def _committed_receipt_replay(
        connection: sqlite3.Connection,
        receipt: PublicationReceipt,
    ) -> PublicationProof:
        row = _require_proof_row(connection, receipt.compatibility_key)
        proof = _proof_from_row(row)
        if (
            proof.revision != receipt.target_revision
            or proof.reservation_sequence != receipt.reservation_sequence
            or proof.generation_id != receipt.generation_id
        ):
            _receipt_corrupt(
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

    @staticmethod
    def _validate_new_point_ownership(
        connection: sqlite3.Connection,
        receipt: PublicationReceipt,
    ) -> None:
        new_points = tuple(
            point_id
            for delta in receipt.deltas
            if delta.changes_proof and delta.new is not None
            for point_id in delta.new.point_ids
        )
        if not new_points:
            return
        owners: dict[str, str] = {}
        unique_points = tuple(dict.fromkeys(new_points))
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
                (*_stable_parameters(receipt.compatibility_key), *page),
            )
            owners.update(
                {
                    column_text(row, "point_id"): column_text(row, "rel_path")
                    for row in rows
                }
            )
        for delta in receipt.deltas:
            if not delta.changes_proof or delta.new is None:
                continue
            for point_id in delta.new.point_ids:
                owner = owners.get(point_id)
                if owner is not None and owner != delta.rel_path:
                    raise ProofOldEvidenceMismatchError(
                        f"point {point_id!r} belongs to untouched path {owner!r}"
                    )

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
                    (*_stable_parameters(key), delta.old.rel_path),
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
                        *_stable_parameters(key),
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
                            *_stable_parameters(key),
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

    def acquire_publication_read_token(
        self,
        key: ProofCompatibilityKey,
    ) -> ProofReadToken:
        """Acquire one proof revision only when no receipt is open."""
        with ledger_connection(self.path) as connection:
            row = _proof_snapshot_row(connection, key)
        if row is None:
            raise ProofMissingError("publication proof does not exist")
        actual = _require_exact_key(row, key, subject="publication proof")
        return ProofReadToken.from_snapshot(
            compatibility_key=actual,
            revision=column_int(row, "revision"),
            reservation_sequence=column_int(row, "reservation_sequence"),
            has_open_receipt=_has_open_receipt(row),
        )

    def validate_publication_read_token(self, token: ProofReadToken) -> None:
        """Reject a backend read if proof or open-receipt state changed."""
        if not isinstance(token, ProofReadToken):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime boundary
            raise TypeError("token must be a ProofReadToken")
        with ledger_connection(self.path) as connection:
            row = _proof_snapshot_row(connection, token.compatibility_key)
        if row is None:
            raise ProofReadConflictError(
                "publication proof disappeared during the backend read"
            )
        try:
            actual = _compatibility_from_row(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise RunLedgerCorruptionError(
                "stored publication proof compatibility key is malformed"
            ) from exc
        token.validate(
            compatibility_key=actual,
            revision=column_int(row, "revision"),
            reservation_sequence=column_int(row, "reservation_sequence"),
            has_open_receipt=_has_open_receipt(row),
        )
