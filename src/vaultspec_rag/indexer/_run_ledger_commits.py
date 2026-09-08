"""Run-ledger storage-confirmed commit evidence operations."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypedDict, cast

from ._file_state import FileStateKind, validate_rel_path
from ._publication_proof import (
    PathDelta,
    ProofCompatibilityKey,
    ProofMutationState,
    ProofReceiptState,
)
from ._run_ledger_models import (
    FETCH_BATCH,
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    PublicationMutationUnit,
    PublicationPointCandidate,
    PublicationReceipt,
    RunLedgerCorruptionError,
    RunLedgerIndexedPathCollisionError,
    RunLedgerStateError,
    column_int,
    column_text,
    fetch_all,
    fetch_one,
    in_ledger_transaction,
    ledger_connection,
    ledger_transaction,
    with_contention_retry,
)
from ._run_ledger_publication import (
    _hydrate_receipt,  # pyright: ignore[reportPrivateUsage]  # sibling receipt codec
    _receipt_corrupt,  # pyright: ignore[reportPrivateUsage]  # sibling receipt codec
    _receipt_row_by_id,  # pyright: ignore[reportPrivateUsage]  # sibling receipt codec
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path

    from ._run_ledger_models import GenerationRow, PublicationProof, RunGeneration


class _CommitUnitRow(TypedDict):
    """The ``commit_units`` row columns :func:`_commit_unit_from_row` reads.

    Also the shape of a full ``SELECT *`` against ``commit_units`` generally,
    so it is reused wherever this module reads an existing unit's row rather
    than through the ``point_ids``-decoding conversion function.
    """

    unit_id: str
    rel_path: str
    unit_kind: str
    source_digest: str | None
    segment_ordinal: int
    is_file_end: int
    point_ids_json: str


class _ContentHashRow(TypedDict):
    """One ``file_states.content_hash`` projection row."""

    content_hash: str | None


class _SiblingAggregateRow(TypedDict):
    """The sibling aggregate :func:`_assert_segment_follows_siblings` reads."""

    source_digest: str | None
    last_ordinal: int | None
    has_file_end: int | None
    unit_count: int


class _CompletionAggregateRow(TypedDict):
    """The per-``(unit_kind, source_digest)`` completion aggregate row."""

    unit_kind: str
    source_digest: str | None
    unit_count: int
    first_ordinal: int
    last_ordinal: int
    ordinal_sum: int
    end_count: int
    end_ordinal: int | None


class _PointIdJoinRow(TypedDict):
    """One ``commit_point_ids`` x ``commit_units`` join row, ordered for paging."""

    point_id: str
    point_ordinal: int
    rel_path: str
    unit_kind: str
    segment_ordinal: int


class _RetainedPointRow(TypedDict):
    """One retained-point row from :func:`retained_point_ids_sql`."""

    point_id: str
    point_ordinal: int
    rel_path: str
    segment_ordinal: int


class _UnitCountRow(TypedDict):
    """A bare ``COUNT(*)`` projection over ``commit_units``."""

    unit_count: int


@dataclass(frozen=True, slots=True)
class _EffectiveCandidateQuery:
    """Receipt-bound inputs for one bounded retained-candidate query."""

    receipt_id: str
    generation_id: str
    compatibility_key: ProofCompatibilityKey
    candidates: tuple[PublicationPointCandidate, ...]
    local_paths: frozenset[str]
    tombstoned_paths: frozenset[str]


def effective_retained_candidates(
    connection: sqlite3.Connection,
    query: _EffectiveCandidateQuery,
) -> frozenset[PublicationPointCandidate]:
    """Resolve path-qualified candidates from canonical or confirmed local owners."""
    if not query.candidates:
        return frozenset()
    canonical = tuple(
        candidate
        for candidate in query.candidates
        if candidate.rel_path not in query.local_paths
        and candidate.rel_path not in query.tombstoned_paths
    )
    local = tuple(
        candidate
        for candidate in query.candidates
        if candidate.rel_path in query.local_paths
    )
    retained: set[PublicationPointCandidate] = set()
    stable = (
        query.compatibility_key.source_type.value,
        query.compatibility_key.root_identity,
        query.compatibility_key.backend_identity,
        query.compatibility_key.collection_identity,
    )
    if canonical:
        values = ", ".join("(?, ?)" for _candidate in canonical)
        rows: list[sqlite3.Row] = fetch_all(
            connection,
            f"""
            WITH candidates(rel_path, point_id) AS (VALUES {values})
            SELECT candidates.rel_path, candidates.point_id
            FROM candidates
            JOIN publication_points AS points
              ON points.rel_path = candidates.rel_path
             AND points.point_id = candidates.point_id
            WHERE points.source_type = ? AND points.root_identity = ?
              AND points.backend_identity = ?
              AND points.collection_identity = ?
            """,
            (
                *(
                    value
                    for item in canonical
                    for value in (item.rel_path, item.point_id)
                ),
                *stable,
            ),
        )
        retained.update(
            PublicationPointCandidate(
                column_text(row, "rel_path"),
                column_text(row, "point_id"),
            )
            for row in rows
        )
    if local:
        values = ", ".join("(?, ?)" for _candidate in local)
        rows = fetch_all(
            connection,
            f"""
            WITH candidates(rel_path, point_id) AS (VALUES {values})
            SELECT candidates.rel_path, candidates.point_id
            FROM candidates
            JOIN publication_mutation_points AS points
              ON points.receipt_id = ?
             AND points.point_id = candidates.point_id
            JOIN publication_mutation_units AS units
              ON units.receipt_id = points.receipt_id
             AND units.mutation_ordinal = points.mutation_ordinal
             AND units.rel_path = candidates.rel_path
            JOIN file_states AS states
              ON states.generation_id = ?
             AND states.evidence_generation_id = ?
             AND states.rel_path = units.rel_path
             AND states.state = ?
             AND states.content_hash = units.source_digest
            WHERE units.unit_kind = ? AND units.state = ?
            """,
            (
                *(value for item in local for value in (item.rel_path, item.point_id)),
                query.receipt_id,
                query.generation_id,
                query.generation_id,
                FileStateKind.INDEXED.value,
                CommitUnitKind.UPSERT.value,
                ProofMutationState.CONFIRMED.value,
            ),
        )
        retained.update(
            PublicationPointCandidate(
                column_text(row, "rel_path"),
                column_text(row, "point_id"),
            )
            for row in rows
        )
    return frozenset(retained)


def _validate_receipt_id(receipt_id: str) -> None:
    if not isinstance(receipt_id, str) or not receipt_id.strip():  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
        raise ValueError("receipt_id must be non-empty")


def _row_optional_text(row: sqlite3.Row, key: str) -> str | None:
    value = row[key]
    if value is None:
        return None
    if not isinstance(value, str):
        _receipt_corrupt(f"stored publication mutation {key} is not text")
    return value


def _row_number(row: sqlite3.Row, key: str) -> float:
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _receipt_corrupt(f"stored publication mutation {key} is not numeric")
    return float(value)


def _row_optional_number(row: sqlite3.Row, key: str) -> float | None:
    if row[key] is None:
        return None
    return _row_number(row, key)


def _receipt_state(
    connection: sqlite3.Connection,
    receipt_id: str,
) -> ProofReceiptState:
    row = _receipt_row_by_id(connection, receipt_id)
    if row is None:
        raise KeyError(receipt_id)
    try:
        return ProofReceiptState(column_text(row, "state"))
    except ValueError as exc:
        _receipt_corrupt("stored publication receipt state is malformed", exc)


def _publication_mutation(
    connection: sqlite3.Connection,
    receipt_id: str,
    unit_id: str,
) -> PublicationMutationUnit | None:
    rows: list[sqlite3.Row] = fetch_all(
        connection,
        """
        SELECT units.*, points.point_ordinal, points.point_id
        FROM publication_mutation_units AS units
        LEFT JOIN publication_mutation_points AS points
          ON points.receipt_id = units.receipt_id
         AND points.mutation_ordinal = units.mutation_ordinal
        WHERE units.receipt_id = ? AND units.unit_id = ?
        ORDER BY points.point_ordinal
        """,
        (receipt_id, unit_id),
    )
    if not rows:
        return None
    try:
        first = rows[0]
        point_ordinals: list[int] = []
        point_ids: list[str] = []
        for row in rows:
            if row["point_ordinal"] is None or row["point_id"] is None:
                raise ValueError("mutation unit has no point identities")
            point_ordinals.append(column_int(row, "point_ordinal"))
            point_ids.append(column_text(row, "point_id"))
        if tuple(point_ordinals) != tuple(range(len(point_ordinals))):
            raise ValueError("mutation point ordinals are not contiguous")
        unit = CommitUnit(
            rel_path=column_text(first, "rel_path"),
            kind=CommitUnitKind(column_text(first, "unit_kind")),
            source_digest=_row_optional_text(first, "source_digest"),
            segment_ordinal=column_int(first, "segment_ordinal"),
            is_file_end=column_int(first, "is_file_end") != 0,
            point_ids=tuple(point_ids),
        )
        if unit.identity != column_text(first, "unit_id"):
            raise ValueError("stored mutation identity is not deterministic")
        sealed_ordinal = first["sealed_ordinal"]
        if sealed_ordinal is not None:
            sealed_ordinal = column_int(first, "sealed_ordinal")
        return PublicationMutationUnit(
            ordinal=column_int(first, "mutation_ordinal"),
            unit=unit,
            state=ProofMutationState(column_text(first, "state")),
            prepared_at=_row_number(first, "prepared_at"),
            applied_at=_row_optional_number(first, "applied_at"),
            confirmed_at=_row_optional_number(first, "confirmed_at"),
            sealed_ordinal=sealed_ordinal,
        )
    except (KeyError, TypeError, ValueError) as exc:
        _receipt_corrupt("stored publication mutation unit is malformed", exc)


def _assert_exact_mutation(
    mutation: PublicationMutationUnit,
    expected: CommitUnit,
) -> None:
    if mutation.unit != expected:
        raise RunLedgerStateError("publication mutation identity collision")


def _validate_mutation_point_authority(
    connection: sqlite3.Connection,
    receipt_row: sqlite3.Row,
    unit: CommitUnit,
) -> None:
    """Reject a bounded unit that could mutate another canonical path."""
    owners: dict[str, str] = {}
    for start in range(0, len(unit.point_ids), FETCH_BATCH):
        point_page = unit.point_ids[start : start + FETCH_BATCH]
        placeholders = ", ".join("?" for _point_id in point_page)
        rows: list[sqlite3.Row] = fetch_all(
            connection,
            f"""
            SELECT point_id, rel_path FROM publication_points
            WHERE source_type = ? AND root_identity = ?
              AND backend_identity = ? AND collection_identity = ?
              AND point_id IN ({placeholders})
            """,
            (
                column_text(receipt_row, "source_type"),
                column_text(receipt_row, "root_identity"),
                column_text(receipt_row, "backend_identity"),
                column_text(receipt_row, "collection_identity"),
                *point_page,
            ),
        )
        owners.update(
            {column_text(row, "point_id"): column_text(row, "rel_path") for row in rows}
        )
    foreign = {
        point_id: owner for point_id, owner in owners.items() if owner != unit.rel_path
    }
    if foreign:
        raise RunLedgerStateError(
            "publication mutation points belong to another canonical path"
        )
    if unit.kind is not CommitUnitKind.UPSERT and owners.keys() != set(unit.point_ids):
        raise RunLedgerStateError(
            "publication deletion points do not exactly match canonical ownership"
        )


def _sealed_publication_candidate(
    receipt: PublicationReceipt,
    deltas: tuple[PathDelta, ...],
    sealed_at: float,
) -> PublicationReceipt:
    sealed_by_identity = {
        mutation.identity: ordinal
        for ordinal, mutation in enumerate(
            sorted(receipt.mutations, key=lambda item: item.identity)
        )
    }
    sealed_mutations = tuple(
        replace(
            mutation,
            sealed_ordinal=sealed_by_identity[mutation.identity],
        )
        for mutation in receipt.mutations
    )
    return replace(
        receipt,
        state=ProofReceiptState.SEALED,
        mutations=sealed_mutations,
        deltas=deltas,
        sealed_at=max(sealed_at, receipt.reserved_at),
    )


def _persist_sealed_receipt_body(
    connection: sqlite3.Connection,
    candidate: PublicationReceipt,
) -> None:
    """Persist already-validated sealed mutation and delta material."""
    for mutation in candidate.mutations:
        cursor = connection.execute(
            """
            UPDATE publication_mutation_units SET sealed_ordinal = ?
            WHERE receipt_id = ? AND unit_id = ?
              AND sealed_ordinal IS NULL
            """,
            (
                mutation.sealed_ordinal,
                candidate.receipt_id,
                mutation.identity,
            ),
        )
        if cursor.rowcount != 1:
            _receipt_corrupt("publication mutation changed while sealing receipt")
    for ordinal, delta in enumerate(candidate.deltas):
        connection.execute(
            """
            INSERT INTO publication_receipt_deltas (
                receipt_id, delta_ordinal, outcome, rel_path,
                target_rel_path, old_content_identity,
                new_content_identity
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.receipt_id,
                ordinal,
                delta.outcome.value,
                delta.rel_path,
                delta.target_rel_path,
                (delta.old.content_identity if delta.old is not None else None),
                (delta.new.content_identity if delta.new is not None else None),
            ),
        )
        for side, evidence in (("old", delta.old), ("new", delta.new)):
            if evidence is None:
                continue
            connection.executemany(
                """
                INSERT INTO publication_receipt_points (
                    receipt_id, delta_ordinal, evidence_side,
                    point_ordinal, point_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        candidate.receipt_id,
                        ordinal,
                        side,
                        point_ordinal,
                        point_id,
                    )
                    for point_ordinal, point_id in enumerate(evidence.point_ids)
                ),
            )


class RunLedgerCommitMethods:
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
        ) -> RunGeneration: ...

    def prepare_publication_mutation(
        self,
        receipt_id: str,
        unit: CommitUnit,
    ) -> PublicationMutationUnit:
        """Persist one exact mutation unit before any external store call."""
        _validate_receipt_id(receipt_id)
        if not isinstance(unit, CommitUnit):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("unit must be a CommitUnit")

        def body(connection: sqlite3.Connection) -> PublicationMutationUnit:
            state = _receipt_state(connection, receipt_id)
            if state not in {
                ProofReceiptState.RESERVED,
                ProofReceiptState.SEALED,
            }:
                raise RunLedgerStateError(
                    f"cannot prepare a mutation for a {state.value} receipt"
                )
            existing = _publication_mutation(connection, receipt_id, unit.identity)
            if existing is not None:
                _assert_exact_mutation(existing, unit)
                return existing
            if state is not ProofReceiptState.RESERVED:
                raise RunLedgerStateError(
                    f"cannot prepare a mutation for a {state.value} receipt"
                )
            receipt_row = _receipt_row_by_id(connection, receipt_id)
            assert receipt_row is not None
            _validate_mutation_point_authority(connection, receipt_row, unit)
            generation = self._require_mutable_generation(
                connection,
                column_text(receipt_row, "generation_id"),
            )
            if generation["finalization_phase"] != FinalizationPhase.INGESTING.value:
                raise RunLedgerStateError(
                    "cannot prepare a publication mutation after finalization begins"
                )
            slot: sqlite3.Row | None = fetch_one(
                connection,
                """
                SELECT unit_id FROM publication_mutation_units
                WHERE receipt_id = ? AND rel_path = ? AND unit_kind = ?
                  AND segment_ordinal = ?
                """,
                (
                    receipt_id,
                    unit.rel_path,
                    unit.kind.value,
                    unit.segment_ordinal,
                ),
            )
            if slot is not None:
                raise RunLedgerStateError(
                    "publication mutation slot belongs to different evidence"
                )
            for start in range(0, len(unit.point_ids), FETCH_BATCH):
                point_page = unit.point_ids[start : start + FETCH_BATCH]
                placeholders = ", ".join("?" for _point_id in point_page)
                owner: sqlite3.Row | None = fetch_one(
                    connection,
                    f"""
                    SELECT point_id FROM publication_mutation_points
                    WHERE receipt_id = ? AND point_id IN ({placeholders})
                    LIMIT 1
                    """,
                    (receipt_id, *point_page),
                )
                if owner is not None:
                    raise RunLedgerStateError(
                        "publication mutation point belongs to another unit"
                    )
            next_ordinal = column_int(receipt_row, "next_mutation_ordinal")
            if next_ordinal:
                predecessor = fetch_one(
                    connection,
                    """
                    SELECT 1 FROM publication_mutation_units
                    WHERE receipt_id = ? AND mutation_ordinal = ?
                    """,
                    (receipt_id, next_ordinal - 1),
                )
                if predecessor is None:
                    _receipt_corrupt("publication mutation cursor has no predecessor")
            cursor = connection.execute(
                """
                UPDATE publication_receipts
                SET next_mutation_ordinal = next_mutation_ordinal + 1
                WHERE receipt_id = ? AND state = ?
                  AND next_mutation_ordinal = ?
                """,
                (
                    receipt_id,
                    ProofReceiptState.RESERVED.value,
                    next_ordinal,
                ),
            )
            if cursor.rowcount != 1:
                raise RunLedgerStateError(
                    "publication mutation cursor changed during preparation"
                )
            prepared_at = max(time.time(), _row_number(receipt_row, "reserved_at"))
            connection.execute(
                """
                INSERT INTO publication_mutation_units (
                    receipt_id, mutation_ordinal, sealed_ordinal, unit_id,
                    rel_path, unit_kind, source_digest, segment_ordinal,
                    is_file_end, state, prepared_at, applied_at, confirmed_at
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    receipt_id,
                    next_ordinal,
                    unit.identity,
                    unit.rel_path,
                    unit.kind.value,
                    unit.source_digest,
                    unit.segment_ordinal,
                    int(unit.is_file_end),
                    ProofMutationState.PREPARED.value,
                    prepared_at,
                ),
            )
            connection.executemany(
                """
                INSERT INTO publication_mutation_points (
                    receipt_id, mutation_ordinal, point_ordinal, point_id
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    (receipt_id, next_ordinal, ordinal, point_id)
                    for ordinal, point_id in enumerate(unit.point_ids)
                ),
            )
            prepared = _publication_mutation(connection, receipt_id, unit.identity)
            assert prepared is not None
            return prepared

        return in_ledger_transaction(self.path, body)

    def mark_publication_mutation_applied(
        self,
        receipt_id: str,
        unit: CommitUnit,
    ) -> PublicationMutationUnit:
        """Record that the external store acknowledged a prepared unit."""
        return self._advance_publication_mutation(
            receipt_id,
            unit,
            target=ProofMutationState.APPLIED,
        )

    def confirm_publication_mutation(
        self,
        receipt_id: str,
        unit: CommitUnit,
    ) -> PublicationMutationUnit:
        """Record that an applied unit crossed its required ingest barrier."""
        return self._advance_publication_mutation(
            receipt_id,
            unit,
            target=ProofMutationState.CONFIRMED,
        )

    def _advance_publication_mutation(
        self,
        receipt_id: str,
        unit: CommitUnit,
        *,
        target: ProofMutationState,
    ) -> PublicationMutationUnit:
        _validate_receipt_id(receipt_id)
        if not isinstance(unit, CommitUnit):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("unit must be a CommitUnit")

        def body(connection: sqlite3.Connection) -> PublicationMutationUnit:
            state = _receipt_state(connection, receipt_id)
            if state not in {ProofReceiptState.RESERVED, ProofReceiptState.SEALED}:
                raise RunLedgerStateError(
                    f"cannot advance a mutation for a {state.value} receipt"
                )
            mutation = _publication_mutation(connection, receipt_id, unit.identity)
            if mutation is None:
                raise KeyError(unit.identity)
            _assert_exact_mutation(mutation, unit)
            if mutation.state is target or (
                mutation.state is ProofMutationState.CONFIRMED
                and target is ProofMutationState.APPLIED
            ):
                return mutation
            expected = {
                ProofMutationState.APPLIED: ProofMutationState.PREPARED,
                ProofMutationState.CONFIRMED: ProofMutationState.APPLIED,
            }[target]
            if mutation.state is not expected:
                raise RunLedgerStateError(
                    f"publication mutation must be {expected.value} before "
                    f"it becomes {target.value}"
                )
            now = max(
                time.time(),
                mutation.applied_at
                if mutation.applied_at is not None
                else mutation.prepared_at,
            )
            if target is ProofMutationState.APPLIED:
                assignment = "state = ?, applied_at = ?"
            else:
                assignment = "state = ?, confirmed_at = ?"
            cursor = connection.execute(
                f"""
                UPDATE publication_mutation_units SET {assignment}
                WHERE receipt_id = ? AND unit_id = ? AND state = ?
                """,
                (target.value, now, receipt_id, unit.identity, expected.value),
            )
            if cursor.rowcount != 1:
                raise RunLedgerStateError(
                    "publication mutation changed during state transition"
                )
            advanced = _publication_mutation(connection, receipt_id, unit.identity)
            assert advanced is not None
            return advanced

        return in_ledger_transaction(self.path, body)

    def seal_publication_receipt(
        self,
        receipt_id: str,
        deltas: tuple[PathDelta, ...],
    ) -> PublicationReceipt:
        """Freeze complete delta and mutation coverage before reconciliation."""
        _validate_receipt_id(receipt_id)
        if not isinstance(deltas, tuple):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("deltas must be a tuple")
        if any(not isinstance(delta, PathDelta) for delta in deltas):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("deltas must contain only PathDelta values")
        if not deltas or not any(delta.changes_proof for delta in deltas):
            raise RunLedgerStateError(
                "a receipt with no proof change must roll back instead of sealing"
            )
        sealed_at = time.time()

        def body(connection: sqlite3.Connection) -> PublicationReceipt:
            row = _receipt_row_by_id(connection, receipt_id)
            if row is None:
                raise KeyError(receipt_id)
            receipt = _hydrate_receipt(connection, row)
            if receipt.state in {
                ProofReceiptState.SEALED,
                ProofReceiptState.COMMITTED,
            }:
                if receipt.deltas != deltas:
                    raise RunLedgerStateError(
                        "sealed publication receipt has different deltas"
                    )
                return receipt
            if receipt.state in {
                ProofReceiptState.ROLLING_BACK,
                ProofReceiptState.ROLLED_BACK,
            }:
                raise RunLedgerStateError(
                    f"{receipt.state.value} publication receipt cannot be sealed"
                )
            candidate = _sealed_publication_candidate(receipt, deltas, sealed_at)
            proof = self._validate_receipt_authority(connection, candidate)
            generation = self._require_compatible_receipt_generation(
                connection,
                receipt.generation_id,
                receipt.compatibility_key,
                proof,
            )
            if generation.finalization_phase is not FinalizationPhase.INGESTING:
                raise RunLedgerStateError(
                    "publication receipt seals only while its generation is ingesting"
                )
            _persist_sealed_receipt_body(connection, candidate)
            cursor = connection.execute(
                """
                UPDATE publication_receipts SET state = ?, sealed_at = ?
                WHERE receipt_id = ? AND state = ?
                """,
                (
                    ProofReceiptState.SEALED.value,
                    candidate.sealed_at,
                    receipt_id,
                    ProofReceiptState.RESERVED.value,
                ),
            )
            if cursor.rowcount != 1:
                raise RunLedgerStateError(
                    "publication receipt changed while it was being sealed"
                )
            result_row = _receipt_row_by_id(connection, receipt_id)
            assert result_row is not None
            return _hydrate_receipt(connection, result_row)

        return in_ledger_transaction(self.path, body)

    def begin_publication_rollback(
        self,
        receipt_id: str,
    ) -> PublicationReceipt:
        """Persist rollback direction before any inverse storage mutation."""
        _validate_receipt_id(receipt_id)
        rollback_started_at = time.time()

        def body(connection: sqlite3.Connection) -> PublicationReceipt:
            row = _receipt_row_by_id(connection, receipt_id)
            if row is None:
                raise KeyError(receipt_id)
            receipt = _hydrate_receipt(connection, row)
            if receipt.state in {
                ProofReceiptState.ROLLING_BACK,
                ProofReceiptState.ROLLED_BACK,
            }:
                return receipt
            if receipt.state is ProofReceiptState.COMMITTED:
                raise RunLedgerStateError(
                    "committed publication receipt cannot roll back"
                )
            if any(
                mutation.state is not ProofMutationState.CONFIRMED
                for mutation in receipt.mutations
            ):
                raise RunLedgerStateError(
                    "publication mutations must be confirmed before rollback"
                )
            decision_at = max(
                rollback_started_at,
                receipt.sealed_at
                if receipt.sealed_at is not None
                else receipt.reserved_at,
                *(
                    mutation.confirmed_at
                    for mutation in receipt.mutations
                    if mutation.confirmed_at is not None
                ),
            )
            cursor = connection.execute(
                """
                UPDATE publication_receipts
                SET state = ?, rollback_started_at = ?
                WHERE receipt_id = ? AND state = ?
                """,
                (
                    ProofReceiptState.ROLLING_BACK.value,
                    decision_at,
                    receipt_id,
                    receipt.state.value,
                ),
            )
            if cursor.rowcount != 1:
                raise RunLedgerStateError(
                    "publication receipt changed while rollback began"
                )
            result_row = _receipt_row_by_id(connection, receipt_id)
            assert result_row is not None
            return _hydrate_receipt(connection, result_row)

        return in_ledger_transaction(self.path, body)

    def roll_back_publication_receipt(
        self,
        receipt_id: str,
        *,
        compensated_units: tuple[CommitUnit, ...],
    ) -> PublicationReceipt:
        """Close a rollback only after exact confirmed storage compensation."""
        _validate_receipt_id(receipt_id)
        if not isinstance(compensated_units, tuple):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("compensated_units must be a tuple")
        if any(not isinstance(unit, CommitUnit) for unit in compensated_units):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("compensated_units must contain only CommitUnit values")
        compensated_by_id = {unit.identity: unit for unit in compensated_units}
        if len(compensated_by_id) != len(compensated_units):
            raise ValueError("compensated_units must not contain duplicates")
        rolled_back_at = time.time()

        def body(connection: sqlite3.Connection) -> PublicationReceipt:
            row = _receipt_row_by_id(connection, receipt_id)
            if row is None:
                raise KeyError(receipt_id)
            receipt = _hydrate_receipt(connection, row)
            expected_by_id = {
                mutation.identity: mutation.unit for mutation in receipt.mutations
            }
            if compensated_by_id != expected_by_id:
                raise RunLedgerStateError(
                    "compensated units must exactly match confirmed receipt mutations"
                )
            if receipt.state is ProofReceiptState.ROLLED_BACK:
                return receipt
            if receipt.state is not ProofReceiptState.ROLLING_BACK:
                raise RunLedgerStateError(
                    "publication rollback must begin before compensation"
                )
            terminal_at = max(
                rolled_back_at,
                receipt.rollback_started_at
                if receipt.rollback_started_at is not None
                else receipt.reserved_at,
            )
            cursor = connection.execute(
                """
                UPDATE publication_receipts
                SET state = ?, rolled_back_at = ?
                WHERE receipt_id = ? AND state = ?
                """,
                (
                    ProofReceiptState.ROLLED_BACK.value,
                    terminal_at,
                    receipt_id,
                    ProofReceiptState.ROLLING_BACK.value,
                ),
            )
            if cursor.rowcount != 1:
                raise RunLedgerStateError("publication receipt changed during rollback")
            result_row = _receipt_row_by_id(connection, receipt_id)
            assert result_row is not None
            return _hydrate_receipt(connection, result_row)

        return in_ledger_transaction(self.path, body)

    def record_storage_confirmed_unit(
        self,
        generation_id: str,
        unit: CommitUnit,
    ) -> bool:
        """Durably record one already-confirmed external storage mutation.

        Returns ``True`` for the first record and ``False`` for exact replay.
        A reused identity with different evidence is rejected.
        """
        return self.record_storage_confirmed_units(generation_id, (unit,)) == 1

    def record_storage_confirmed_units(
        self,
        generation_id: str,
        units: tuple[CommitUnit, ...],
    ) -> int:
        """Atomically record one confirmed bounded store mutation's units.

        Every unit is validated and inserted in the same SQLite transaction.
        The transaction therefore exposes either the complete synchronous
        store mutation or none of it to compatible recovery.

        Raises:
            RunLedgerIndexedPathCollisionError: When an upsert unit names a
                path this generation already indexed, which a caller can
                repair rather than having to fail the run.
            RunLedgerStateError: When any other durable invariant of the
                generation would be violated.
        """
        if not units:
            raise ValueError("a confirmed storage mutation must contain units")
        return with_contention_retry(
            lambda: self._record_storage_confirmed_units_once(generation_id, units),
            path=self.path,
        )

    def _record_storage_confirmed_units_once(
        self,
        generation_id: str,
        units: tuple[CommitUnit, ...],
    ) -> int:
        """Record the units in one transaction, without the contention replay.

        Separated so the replay above has a body to re-run. A contended
        transaction rolls back whole, and an already-recorded unit reports zero
        insertions, so re-running is safe on either outcome.
        """
        now = time.time()
        with ledger_transaction(self.path) as connection:
            generation = self._require_mutable_generation(connection, generation_id)
            if generation["finalization_phase"] != FinalizationPhase.INGESTING.value:
                raise RunLedgerStateError("cannot add units after finalization begins")
            inserted = sum(
                self._record_storage_confirmed_unit(
                    connection,
                    generation_id,
                    unit,
                    now=now,
                )
                for unit in units
            )
            if inserted:
                connection.execute(
                    "UPDATE generations SET updated_at = ? WHERE generation_id = ?",
                    (now, generation_id),
                )
            return inserted

    def _record_storage_confirmed_unit(
        self,
        connection: sqlite3.Connection,
        generation_id: str,
        unit: CommitUnit,
        *,
        now: float,
    ) -> int:
        point_ids_json = json.dumps(unit.point_ids, separators=(",", ":"))
        existing: _CommitUnitRow | None = fetch_one(
            connection,
            """
            SELECT * FROM commit_units
            WHERE generation_id = ? AND unit_id = ?
            """,
            (generation_id, unit.identity),
        )
        if existing is not None:
            self._assert_existing_unit_matches(existing, unit, point_ids_json)
            return 0
        indexed: _ContentHashRow | None = fetch_one(
            connection,
            """
            SELECT content_hash FROM file_states
            WHERE generation_id = ? AND rel_path = ? AND state = ?
              AND evidence_generation_id = generation_id
            """,
            (generation_id, unit.rel_path, FileStateKind.INDEXED.value),
        )
        self._assert_unit_path_not_indexed(indexed, generation_id, unit)
        sibling: _SiblingAggregateRow | None = fetch_one(
            connection,
            """
            SELECT source_digest, MAX(segment_ordinal) AS last_ordinal,
                   MAX(is_file_end) AS has_file_end, COUNT(*) AS unit_count
            FROM commit_units
            WHERE generation_id = ? AND rel_path = ? AND unit_kind = ?
            """,
            (generation_id, unit.rel_path, unit.kind.value),
        )
        assert sibling is not None
        self._assert_segment_follows_siblings(sibling, unit)
        self._assert_point_ids_are_unowned(connection, generation_id, unit)
        connection.execute(
            """
            INSERT INTO commit_units (
                generation_id, unit_id, rel_path, unit_kind,
                source_digest, segment_ordinal, is_file_end,
                point_ids_json, committed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                unit.identity,
                unit.rel_path,
                unit.kind.value,
                unit.source_digest,
                unit.segment_ordinal,
                int(unit.is_file_end),
                point_ids_json,
                now,
            ),
        )
        connection.executemany(
            """
            INSERT INTO commit_point_ids (
                generation_id, unit_id, point_ordinal, point_id
            ) VALUES (?, ?, ?, ?)
            """,
            (
                (generation_id, unit.identity, ordinal, point_id)
                for ordinal, point_id in enumerate(unit.point_ids)
            ),
        )
        return 1

    @staticmethod
    def _assert_existing_unit_matches(
        existing: _CommitUnitRow,
        unit: CommitUnit,
        point_ids_json: str,
    ) -> None:
        values_match = (
            existing["rel_path"] == unit.rel_path
            and existing["unit_kind"] == unit.kind.value
            and existing["segment_ordinal"] == unit.segment_ordinal
            and bool(existing["is_file_end"]) is unit.is_file_end
            and existing["source_digest"] == unit.source_digest
            and existing["point_ids_json"] == point_ids_json
        )
        if not values_match:
            raise RunLedgerStateError("commit-unit identity collision")

    @staticmethod
    def _assert_unit_path_not_indexed(
        indexed: _ContentHashRow | None,
        generation_id: str,
        unit: CommitUnit,
    ) -> None:
        if indexed is None or unit.kind is not CommitUnitKind.UPSERT:
            return
        unit_digest = unit.source_digest
        assert unit_digest is not None
        raise RunLedgerIndexedPathCollisionError(
            "cannot add upsert commit units after a path is indexed: "
            f"{unit.rel_path!r}",
            generation_id=generation_id,
            rel_path=unit.rel_path,
            indexed_digest=indexed["content_hash"],
            unit_digest=unit_digest,
        )

    @staticmethod
    def _assert_segment_follows_siblings(
        sibling: _SiblingAggregateRow,
        unit: CommitUnit,
    ) -> None:
        sibling_count = sibling["unit_count"]
        if sibling_count and sibling["source_digest"] != unit.source_digest:
            raise RunLedgerStateError(
                "segments for one path must share one source digest"
            )
        if sibling_count and bool(sibling["has_file_end"]):
            raise RunLedgerStateError(
                "cannot add a segment after the file-end commit unit"
            )
        if unit.segment_ordinal != sibling_count:
            raise RunLedgerStateError("commit-unit segment ordinals must be contiguous")

    @staticmethod
    def _assert_point_ids_are_unowned(
        connection: sqlite3.Connection,
        generation_id: str,
        unit: CommitUnit,
    ) -> None:
        for point_id in unit.point_ids:
            owner: object | None = fetch_one(
                connection,
                """
                SELECT unit_id FROM commit_point_ids
                WHERE generation_id = ? AND point_id = ?
                """,
                (generation_id, point_id),
            )
            if owner is not None:
                raise RunLedgerStateError(
                    f"point identity {point_id!r} belongs to another commit unit"
                )

    def unit_committed(self, generation_id: str, unit: CommitUnit) -> bool:
        """Return whether an exact storage-confirmed unit is durable."""
        with ledger_connection(self.path) as connection:
            row: object | None = fetch_one(
                connection,
                """
                SELECT 1 FROM commit_units
                WHERE generation_id = ? AND unit_id = ?
                """,
                (generation_id, unit.identity),
            )
        return row is not None

    def committed_unit_count(self, generation_id: str) -> int:
        """Return the committed-unit count without materializing ledger rows."""
        with ledger_connection(self.path) as connection:
            row: _UnitCountRow | None = fetch_one(
                connection,
                """
                SELECT COUNT(*) AS unit_count FROM commit_units
                WHERE generation_id = ?
                """,
                (generation_id,),
            )
        assert row is not None
        return row["unit_count"]

    def file_complete(self, generation_id: str, rel_path: str) -> bool:
        """Return whether every segment (or the deletion unit) is committed."""
        validate_rel_path(rel_path)
        with ledger_connection(self.path) as connection:
            complete, _digest = self._file_completion_evidence(
                connection,
                generation_id,
                rel_path,
            )
            return complete

    @staticmethod
    def _file_completion_evidence(
        connection: sqlite3.Connection,
        generation_id: str,
        rel_path: str,
    ) -> tuple[bool, str | None]:
        rows: list[_CompletionAggregateRow] = fetch_all(
            connection,
            """
            SELECT unit_kind, source_digest,
                   COUNT(*) AS unit_count,
                   MIN(segment_ordinal) AS first_ordinal,
                   MAX(segment_ordinal) AS last_ordinal,
                   SUM(segment_ordinal) AS ordinal_sum,
                   SUM(is_file_end) AS end_count,
                   MAX(CASE WHEN is_file_end = 1 THEN segment_ordinal END)
                       AS end_ordinal
            FROM commit_units
            WHERE generation_id = ? AND rel_path = ?
            GROUP BY unit_kind, source_digest
            """,
            (generation_id, rel_path),
        )
        if not rows:
            return False, None
        by_kind: dict[str, _CompletionAggregateRow] = {}
        for row in rows:
            kind = row["unit_kind"]
            if kind in by_kind:
                return False, None
            by_kind[kind] = row
            count = row["unit_count"]
            expected_sum = count * (count - 1) // 2
            if (
                count <= 0
                or row["first_ordinal"] != 0
                or row["last_ordinal"] != count - 1
                or row["ordinal_sum"] != expected_sum
                or row["end_count"] != 1
                or row["end_ordinal"] != count - 1
            ):
                return False, None
        upserts = by_kind.get(CommitUnitKind.UPSERT.value)
        digest = upserts["source_digest"] if upserts else None
        return True, digest

    def iter_units(
        self,
        generation_id: str,
        *,
        batch_size: int = FETCH_BATCH,
    ) -> Iterator[CommitUnit]:
        """Yield committed units using bounded row-wise iteration."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        last_key: tuple[str, str, int, str] | None = None
        while True:
            with ledger_connection(self.path) as connection:
                rows: list[_CommitUnitRow]
                if last_key is None:
                    rows = fetch_all(
                        connection,
                        """
                        SELECT * FROM commit_units
                        WHERE generation_id = ?
                        ORDER BY rel_path, unit_kind, segment_ordinal, unit_id
                        LIMIT ?
                        """,
                        (generation_id, batch_size),
                    )
                else:
                    rows = fetch_all(
                        connection,
                        """
                        SELECT * FROM commit_units
                        WHERE generation_id = ?
                          AND (rel_path, unit_kind, segment_ordinal, unit_id)
                              > (?, ?, ?, ?)
                        ORDER BY rel_path, unit_kind, segment_ordinal, unit_id
                        LIMIT ?
                        """,
                        (generation_id, *last_key, batch_size),
                    )
            if not rows:
                return
            for row in rows:
                yield _commit_unit_from_row(row)
            last = rows[-1]
            last_key = (
                last["rel_path"],
                last["unit_kind"],
                last["segment_ordinal"],
                last["unit_id"],
            )

    def iter_point_ids(
        self,
        generation_id: str,
        *,
        batch_size: int = FETCH_BATCH,
    ) -> Iterator[str]:
        """Yield deterministic committed point identities row by row."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        last_key: tuple[str, str, int, int, str] | None = None
        while True:
            condition = ""
            parameters: tuple[object, ...] = (generation_id,)
            if last_key is not None:
                condition = """
                  AND (units.rel_path, units.unit_kind,
                       units.segment_ordinal, points.point_ordinal,
                       points.point_id) > (?, ?, ?, ?, ?)
                """
                parameters = (generation_id, *last_key)
            with ledger_connection(self.path) as connection:
                rows: list[_PointIdJoinRow] = fetch_all(
                    connection,
                    f"""
                    SELECT points.point_id, points.point_ordinal,
                           units.rel_path, units.unit_kind,
                           units.segment_ordinal
                    FROM commit_point_ids AS points
                    JOIN commit_units AS units
                      ON units.generation_id = points.generation_id
                     AND units.unit_id = points.unit_id
                    WHERE points.generation_id = ?
                    {condition}
                    ORDER BY units.rel_path, units.unit_kind,
                             units.segment_ordinal, points.point_ordinal,
                             points.point_id
                    LIMIT ?
                    """,
                    (*parameters, batch_size),
                )
            if not rows:
                return
            for row in rows:
                yield row["point_id"]
            last = rows[-1]
            last_key = (
                last["rel_path"],
                last["unit_kind"],
                last["segment_ordinal"],
                last["point_ordinal"],
                last["point_id"],
            )

    def iter_retained_point_ids(
        self,
        generation_id: str,
        *,
        rel_path: str | None = None,
        batch_size: int = FETCH_BATCH,
    ) -> Iterator[str]:
        """Yield exact point identities retained by the generation manifest.

        Carried paths read their original evidence generation while replaced paths
        read the current generation. Deletion units are deliberately excluded.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if rel_path is not None:
            validate_rel_path(rel_path)
        last_key: tuple[str, int, int, str] | None = None
        while True:
            parameters: tuple[object, ...] = (
                CommitUnitKind.UPSERT.value,
                generation_id,
                FileStateKind.INDEXED.value,
            )
            if rel_path is not None:
                parameters = (*parameters, rel_path)
            if last_key is not None:
                parameters = (*parameters, *last_key)
            with ledger_connection(self.path) as connection:
                rows: list[_RetainedPointRow] = fetch_all(
                    connection,
                    retained_point_ids_sql(
                        scoped_to_path=rel_path is not None,
                        keyset=last_key is not None,
                    ),
                    (*parameters, batch_size),
                )
            if not rows:
                return
            for row in rows:
                yield row["point_id"]
            last = rows[-1]
            last_key = (
                last["rel_path"],
                last["segment_ordinal"],
                last["point_ordinal"],
                last["point_id"],
            )


def retained_point_ids_sql(*, scoped_to_path: bool, keyset: bool) -> str:
    """Build one retained-point batch query with a pinned join order.

    ``CROSS JOIN`` is load-bearing: without ``ANALYZE`` statistics - and the
    ledger never runs ``ANALYZE`` - SQLite's planner reorders the plain-JOIN
    form of this three-way join to visit ``commit_point_ids`` before
    ``commit_units``, reaching it on ``generation_id`` alone. That scans every
    committed point in the generation for every file row and re-sorts through
    a temp B-tree, which turns each keyset batch into a full-corpus pass and
    the whole iteration into minutes of CPU on a corpus of tens of thousands
    of points. Pinning states -> units -> points keeps every batch on pure
    index seeks (the file-state primary key, the commit-unit uniqueness
    index, and the point primary key) and the iteration linear in the number
    of retained points.

    Args:
        scoped_to_path: Restrict the manifest walk to one relative path.
        keyset: Resume after a ``(rel_path, segment_ordinal, point_ordinal,
            point_id)`` cursor row.
    """
    path_condition = " AND states.rel_path = ?" if scoped_to_path else ""
    keyset_condition = (
        """
          AND (states.rel_path, units.segment_ordinal,
               points.point_ordinal, points.point_id) > (?, ?, ?, ?)
        """
        if keyset
        else ""
    )
    return f"""
        SELECT points.point_id, points.point_ordinal,
               states.rel_path, units.segment_ordinal
        FROM file_states AS states
        CROSS JOIN commit_units AS units
          ON units.generation_id = states.evidence_generation_id
         AND units.rel_path = states.rel_path
         AND units.unit_kind = ?
         AND units.source_digest = states.content_hash
        CROSS JOIN commit_point_ids AS points
          ON points.generation_id = units.generation_id
         AND points.unit_id = units.unit_id
        WHERE states.generation_id = ?
          AND states.state = ?
        {path_condition}
        {keyset_condition}
        ORDER BY states.rel_path, units.segment_ordinal,
                 points.point_ordinal, points.point_id
        LIMIT ?
        """


def _commit_unit_from_row(row: _CommitUnitRow) -> CommitUnit:
    try:
        decoded: object = json.loads(row["point_ids_json"])
        if not isinstance(decoded, list):
            raise TypeError("point_ids_json must contain a list")
        # Entry types are checked, not asserted: a stored list of integers
        # satisfies every downstream invariant CommitUnit enforces (truthy,
        # unique, ordered) and would otherwise reach the store as point
        # identities of the wrong type. `object`, not `Any`: the isinstance
        # check just below is what actually narrows each element, so the
        # cast only needs to name the list's element type as unknown-but-safe
        # rather than assert it away.
        stored_ids = cast("list[object]", decoded)
        point_ids = tuple(
            point_id for point_id in stored_ids if isinstance(point_id, str)
        )
        if len(point_ids) != len(stored_ids):
            raise TypeError("point_ids_json must contain only strings")
        return CommitUnit(
            rel_path=row["rel_path"],
            kind=CommitUnitKind(row["unit_kind"]),
            source_digest=row["source_digest"],
            segment_ordinal=row["segment_ordinal"],
            is_file_end=bool(row["is_file_end"]),
            point_ids=point_ids,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RunLedgerCorruptionError("stored commit unit is malformed") from exc
