"""Run-ledger storage-confirmed commit evidence operations."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, TypedDict, cast

from ._file_state import FileStateKind, validate_rel_path
from ._run_ledger_models import (
    FETCH_BATCH,
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    RunLedgerCorruptionError,
    RunLedgerIndexedPathCollisionError,
    RunLedgerStateError,
    fetch_all,
    fetch_one,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from contextlib import AbstractContextManager

    from ._run_ledger_models import GenerationRow, RunGeneration


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


class RunLedgerCommitMethods:
    if TYPE_CHECKING:

        def _transaction(self) -> AbstractContextManager[sqlite3.Connection]: ...

        def _connect(self) -> sqlite3.Connection: ...

        @staticmethod
        def _require_mutable_generation(
            connection: sqlite3.Connection, generation_id: str
        ) -> GenerationRow: ...

        @staticmethod
        def _generation_from_row(row: GenerationRow) -> RunGeneration: ...

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
        now = time.time()
        with self._transaction() as connection:
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
        with self._connect() as connection:
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
        with self._connect() as connection:
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
        with self._connect() as connection:
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
            with self._connect() as connection:
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
            with self._connect() as connection:
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
            with self._connect() as connection:
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
