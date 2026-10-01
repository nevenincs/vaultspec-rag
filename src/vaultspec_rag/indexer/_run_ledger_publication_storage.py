"""SQLite row decoding and bounded query helpers for publication state."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Final, Never

from ._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofAggregate,
    ProofCompatibilityKey,
    ProofEvidence,
    ProofIncompatibleError,
    ProofMissingError,
    ProofMutationState,
    ProofProvenance,
    ProofRebuildRequiredError,
    ProofReceiptState,
    ProofUnverifiableReason,
)
from ._run_ledger_models import (
    FETCH_BATCH,
    CommitUnit,
    CommitUnitKind,
    PublicationMutationUnit,
    PublicationProof,
    PublicationReceipt,
    RunLedgerCorruptionError,
    RunLedgerStateError,
    RunOperation,
    column_int,
    column_text,
    fetch_all,
    fetch_one,
)
from ._run_ledger_publication_identity import (
    publication_compatibility_from_row,
    stable_parameters,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable

    from ._run_ledger_models import RunGeneration


OPEN_RECEIPT_SQL: Final = "state IN ('reserved', 'sealed', 'rolling_back')"


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


def proof_from_row(row: sqlite3.Row) -> PublicationProof:
    try:
        return PublicationProof(
            revision=column_int(row, "revision"),
            reservation_sequence=column_int(row, "reservation_sequence"),
            compatibility_key=publication_compatibility_from_row(row),
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


def require_exact_key(
    row: sqlite3.Row,
    expected: ProofCompatibilityKey,
    *,
    subject: str,
) -> ProofCompatibilityKey:
    try:
        actual = publication_compatibility_from_row(row)
    except (KeyError, TypeError, ValueError) as exc:
        raise RunLedgerCorruptionError(
            f"stored {subject} compatibility key is malformed"
        ) from exc
    if actual != expected:
        raise ProofIncompatibleError(
            f"{subject} exists for the stable identity but is incompatible"
        )
    return actual


def proof_row(
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
        stable_parameters(key),
    )


def require_proof_row(
    connection: sqlite3.Connection,
    key: ProofCompatibilityKey,
) -> sqlite3.Row:
    row = proof_row(connection, key)
    if row is None:
        raise ProofMissingError("publication proof does not exist")
    require_exact_key(row, key, subject="publication proof")
    return row


def begin_read(connection: sqlite3.Connection) -> None:
    # A connection-wide transaction is required whenever a value is hydrated
    # from more than one normalized table. Without it, a writer can commit
    # between child queries and manufacture a mixed receipt or evidence view.
    connection.execute("BEGIN")


def evidence_rows_for_paths(
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
        (*stable_parameters(key), *rel_paths),
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


def all_evidence_for_paths(
    connection: sqlite3.Connection,
    key: ProofCompatibilityKey,
    rel_paths: Iterable[str],
) -> dict[str, ProofEvidence]:
    unique_paths = tuple(dict.fromkeys(rel_paths))
    result: dict[str, ProofEvidence] = {}
    for start in range(0, len(unique_paths), FETCH_BATCH):
        page = unique_paths[start : start + FETCH_BATCH]
        result.update(evidence_rows_for_paths(connection, key, page))
    return result


def receipt_corrupt(message: str, exc: BaseException | None = None) -> Never:
    error = ProofRebuildRequiredError(
        message,
        reason=ProofUnverifiableReason.CORRUPT_RECEIPT,
    )
    if exc is None:
        raise error
    raise error from exc


def _mutation_from_rows(
    ordinal: int,
    rows: list[sqlite3.Row],
) -> PublicationMutationUnit:
    first = rows[0]
    indexed_points: list[tuple[int, str]] = []
    for row in rows:
        raw_ordinal = row["point_ordinal"]
        raw_point = row["point_id"]
        if raw_ordinal is None or raw_point is None:
            raise ValueError("mutation unit has no point identities")
        if isinstance(raw_ordinal, bool) or not isinstance(raw_ordinal, int):
            raise TypeError("mutation point ordinal must be an integer")
        if not isinstance(raw_point, str):
            raise TypeError("mutation point identity must be text")
        indexed_points.append((raw_ordinal, raw_point))
    if tuple(index for index, _point in indexed_points) != tuple(
        range(len(indexed_points))
    ):
        raise ValueError("mutation point ordinals are not contiguous")
    unit = CommitUnit(
        rel_path=column_text(first, "rel_path"),
        kind=CommitUnitKind(column_text(first, "unit_kind")),
        source_digest=_row_optional_text(first, "source_digest"),
        segment_ordinal=column_int(first, "segment_ordinal"),
        is_file_end=column_int(first, "is_file_end") != 0,
        point_ids=tuple(point for _index, point in indexed_points),
    )
    if column_text(first, "unit_id") != unit.identity:
        raise ValueError("stored mutation identity is not deterministic")
    sealed_value = first["sealed_ordinal"]
    if sealed_value is not None and (
        isinstance(sealed_value, bool) or not isinstance(sealed_value, int)
    ):
        raise TypeError("sealed ordinal must be an integer or null")
    return PublicationMutationUnit(
        ordinal=ordinal,
        unit=unit,
        state=ProofMutationState(column_text(first, "state")),
        prepared_at=_row_number(first, "prepared_at"),
        applied_at=_row_optional_number(first, "applied_at"),
        confirmed_at=_row_optional_number(first, "confirmed_at"),
        sealed_ordinal=sealed_value,
    )


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
        return tuple(
            _mutation_from_rows(ordinal, unit_rows)
            for ordinal, unit_rows in by_ordinal.items()
        )
    except (KeyError, RunLedgerCorruptionError, TypeError, ValueError) as exc:
        receipt_corrupt("stored publication mutation units are malformed", exc)


def _delta_evidence(
    rel_path: str,
    content_identity: str | None,
    points: list[tuple[int, str]],
) -> ProofEvidence | None:
    if (content_identity is None) != (not points):
        raise ValueError("receipt evidence is incomplete")
    if content_identity is None:
        return None
    return ProofEvidence(
        rel_path=rel_path,
        content_identity=content_identity,
        point_ids=tuple(point for _index, point in points),
    )


def _delta_from_header(
    header: sqlite3.Row,
    points: dict[tuple[int, str], list[tuple[int, str]]],
    parent_revision: int,
) -> PathDelta:
    ordinal = column_int(header, "delta_ordinal")
    rel_path = column_text(header, "rel_path")
    target_rel_path = _row_optional_text(header, "target_rel_path")
    new_path = target_rel_path if target_rel_path is not None else rel_path
    return PathDelta(
        outcome=PathOutcome(column_text(header, "outcome")),
        expected_parent_revision=parent_revision,
        rel_path=rel_path,
        target_rel_path=target_rel_path,
        old=_delta_evidence(
            rel_path,
            _row_optional_text(header, "old_content_identity"),
            points.pop((ordinal, "old"), []),
        ),
        new=_delta_evidence(
            new_path,
            _row_optional_text(header, "new_content_identity"),
            points.pop((ordinal, "new"), []),
        ),
    )


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
        deltas = [
            _delta_from_header(header, points, parent_revision) for header in headers
        ]
        if points:
            raise ValueError("receipt points name a missing delta or evidence side")
        return tuple(deltas)
    except (KeyError, RunLedgerCorruptionError, TypeError, ValueError) as exc:
        receipt_corrupt("stored publication deltas are malformed", exc)


def hydrate_receipt(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> PublicationReceipt:
    try:
        receipt_id = column_text(row, "receipt_id")
        parent_revision = column_int(row, "parent_revision")
        next_mutation_ordinal = column_int(row, "next_mutation_ordinal")
        mutations = _mutation_rows(connection, receipt_id)
        if next_mutation_ordinal != len(mutations):
            raise ValueError(
                "receipt mutation cursor does not match persisted mutation units"
            )
        receipt = PublicationReceipt(
            receipt_id=receipt_id,
            reservation_sequence=column_int(row, "reservation_sequence"),
            compatibility_key=publication_compatibility_from_row(row),
            generation_id=column_text(row, "generation_id"),
            parent_revision=parent_revision,
            target_revision=column_int(row, "target_revision"),
            state=ProofReceiptState(column_text(row, "state")),
            reserved_at=_row_number(row, "reserved_at"),
            mutations=mutations,
            deltas=_delta_rows(
                connection,
                receipt_id,
                parent_revision=parent_revision,
            ),
            sealed_at=_row_optional_number(row, "sealed_at"),
            rollback_started_at=_row_optional_number(row, "rollback_started_at"),
            committed_at=_row_optional_number(row, "committed_at"),
            rolled_back_at=_row_optional_number(row, "rolled_back_at"),
        )
        return receipt
    except ProofRebuildRequiredError:
        raise
    except (KeyError, RunLedgerCorruptionError, TypeError, ValueError) as exc:
        receipt_corrupt("stored publication receipt is malformed", exc)


def receipt_row_by_id(
    connection: sqlite3.Connection,
    receipt_id: str,
) -> sqlite3.Row | None:
    return fetch_one(
        connection,
        "SELECT * FROM publication_receipts WHERE receipt_id = ?",
        (receipt_id,),
    )


def latest_receipt_row(
    connection: sqlite3.Connection,
    generation_id: str,
) -> sqlite3.Row | None:
    """Read a generation's last reservation, including completed no-op work."""
    return fetch_one(
        connection,
        """
        SELECT * FROM publication_receipts
        WHERE generation_id = ?
        ORDER BY reservation_sequence DESC, receipt_id DESC
        LIMIT 1
        """,
        (generation_id,),
    )


def is_noop_publication(
    receipt: PublicationReceipt,
    generation: RunGeneration,
    proof: PublicationProof,
) -> bool:
    """Recognize only a mutation-free rollback against its unchanged parent."""
    from ._run_ledger_publication_identity import compatibility_for_generation

    return (
        receipt.state is ProofReceiptState.ROLLED_BACK
        and not receipt.mutations
        and not receipt.deltas
        and receipt.generation_id == generation.generation_id
        and generation.signature.operation
        in {RunOperation.INCREMENTAL, RunOperation.SCOPED_INCREMENTAL}
        and generation.parent_generation_id == proof.generation_id
        and receipt.compatibility_key == proof.compatibility_key
        and receipt.compatibility_key == compatibility_for_generation(generation)
        and receipt.parent_revision == proof.revision
        and receipt.reservation_sequence == proof.reservation_sequence
    )


def proof_snapshot_row(
    connection: sqlite3.Connection,
    key: ProofCompatibilityKey,
) -> sqlite3.Row | None:
    return proof_snapshot_row_for_stable(connection, stable_parameters(key))


def proof_snapshot_row_for_stable(
    connection: sqlite3.Connection,
    stable_identity: tuple[object, object, object, object],
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
                     AND {OPEN_RECEIPT_SQL.replace("state", "receipt.state")}
               ) AS has_open_receipt
        FROM publication_proofs AS proof
        WHERE proof.source_type = ? AND proof.root_identity = ?
          AND proof.backend_identity = ? AND proof.collection_identity = ?
        """,
        stable_identity,
    )


def current_proof_snapshot_row(
    connection: sqlite3.Connection,
    identity: tuple[object, object, object],
) -> sqlite3.Row | None:
    rows: list[sqlite3.Row] = fetch_all(
        connection,
        f"""
        SELECT proof.*,
               EXISTS(
                   SELECT 1 FROM publication_receipts AS receipt
                   WHERE receipt.source_type = proof.source_type
                     AND receipt.root_identity = proof.root_identity
                     AND receipt.backend_identity = proof.backend_identity
                     AND receipt.collection_identity = proof.collection_identity
                     AND {OPEN_RECEIPT_SQL.replace("state", "receipt.state")}
               ) AS has_open_receipt
        FROM publication_proofs AS proof
        WHERE proof.source_type = ? AND proof.root_identity = ?
          AND proof.backend_identity = ?
        LIMIT 2
        """,
        identity,
    )
    if len(rows) > 1:
        raise RunLedgerCorruptionError(
            "multiple current publication proofs exist for one source projection"
        )
    return rows[0] if rows else None


def has_open_receipt(row: sqlite3.Row) -> bool:
    value = column_int(row, "has_open_receipt")
    if value not in {0, 1}:
        raise RunLedgerCorruptionError("open-receipt snapshot is malformed")
    return value != 0


def require_receipt_ready_to_commit(receipt: PublicationReceipt) -> None:
    if receipt.state is ProofReceiptState.ROLLED_BACK:
        raise RunLedgerStateError("rolled-back publication receipt cannot commit")
    if receipt.state is not ProofReceiptState.SEALED:
        raise RunLedgerStateError("publication receipt must be sealed before commit")
    if not any(delta.changes_proof for delta in receipt.deltas):
        raise RunLedgerStateError("a no-op receipt must not advance the proof")
    if any(
        mutation.state is not ProofMutationState.CONFIRMED
        for mutation in receipt.mutations
    ):
        raise RunLedgerStateError("publication receipt has unconfirmed mutation units")


def receipt_committed_at(receipt: PublicationReceipt, now: float) -> float:
    return max(
        now,
        receipt.sealed_at if receipt.sealed_at is not None else receipt.reserved_at,
    )
