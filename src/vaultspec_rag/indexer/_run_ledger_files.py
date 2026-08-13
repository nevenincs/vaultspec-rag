"""Run-ledger per-file manifest and retained-point operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from ._content_policy import AdmissionReason, ContentKind
from ._file_state import FileState, FileStateKind, validate_rel_path
from ._run_ledger_models import (
    FETCH_BATCH,
    CommitUnitKind,
    FinalizationPhase,
    RunLedgerCorruptionError,
    RunLedgerStateError,
    fetch_all,
    fetch_one,
    ledger_connection,
    ledger_transaction,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path

    from ._run_ledger_models import GenerationRow, RunGeneration


class FileStateRow(TypedDict):
    """The ``file_states`` row columns :func:`file_state_from_row` reads."""

    rel_path: str
    state: str
    content_kind: str | None
    content_hash: str | None
    admission_reason: str | None
    error_kind: str | None
    detail: str | None


class _DeletionEvidenceRow(TypedDict):
    """The aggregate columns read to confirm a path deletion is committed."""

    unit_count: int
    end_count: int


class _PointIdRow(TypedDict):
    """A single ``commit_point_ids.point_id`` column, read across queries."""

    point_id: str


class RunLedgerFileMethods:
    if TYPE_CHECKING:
        path: Path

        @staticmethod
        def _require_mutable_generation(
            connection: sqlite3.Connection, generation_id: str
        ) -> GenerationRow: ...

        @staticmethod
        def _file_completion_evidence(
            connection: sqlite3.Connection, generation_id: str, rel_path: str
        ) -> tuple[bool, str | None]: ...

        @staticmethod
        def _generation_from_row(row: GenerationRow) -> RunGeneration: ...

    def record_file_state(self, generation_id: str, state: FileState) -> None:
        """Upsert the latest explicit per-file convergence outcome."""
        with ledger_transaction(self.path) as connection:
            generation = self._require_mutable_generation(connection, generation_id)
            if generation["finalization_phase"] != FinalizationPhase.INGESTING.value:
                raise RunLedgerStateError(
                    "cannot change file state after finalization begins"
                )
            if state.state is FileStateKind.INDEXED:
                complete, committed_digest = self._file_completion_evidence(
                    connection,
                    generation_id,
                    state.rel_path,
                )
                if not complete:
                    raise RunLedgerStateError(
                        "indexed file state requires every storage-confirmed segment"
                    )
                if committed_digest is None:
                    raise RunLedgerStateError(
                        "indexed file state requires storage-confirmed upsert units"
                    )
                if committed_digest != state.content_hash:
                    raise RunLedgerStateError(
                        "indexed file hash differs from storage-confirmed units"
                    )
            connection.execute(
                """
                INSERT INTO file_states (
                    generation_id, rel_path, state, content_kind, content_hash,
                    admission_reason, error_kind, detail, evidence_generation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(generation_id, rel_path) DO UPDATE SET
                    state = excluded.state,
                    content_kind = excluded.content_kind,
                    content_hash = excluded.content_hash,
                    admission_reason = excluded.admission_reason,
                    error_kind = excluded.error_kind,
                    detail = excluded.detail,
                    evidence_generation_id = excluded.evidence_generation_id
                """,
                (
                    generation_id,
                    state.rel_path,
                    state.state.value,
                    state.kind.value if state.kind is not None else None,
                    state.content_hash,
                    state.admission_reason.value
                    if state.admission_reason is not None
                    else None,
                    state.error_kind.value if state.error_kind is not None else None,
                    state.detail,
                    generation_id,
                ),
            )

    def record_path_deleted(self, generation_id: str, rel_path: str) -> None:
        """Remove carried/current manifest state after confirmed path deletion."""
        validate_rel_path(rel_path)
        with ledger_transaction(self.path) as connection:
            generation = self._require_mutable_generation(connection, generation_id)
            if generation["finalization_phase"] != FinalizationPhase.INGESTING.value:
                raise RunLedgerStateError(
                    "cannot change file state after finalization begins"
                )
            evidence: _DeletionEvidenceRow | None = fetch_one(
                connection,
                """
                SELECT COUNT(*) AS unit_count, SUM(is_file_end) AS end_count
                FROM commit_units
                WHERE generation_id = ? AND rel_path = ? AND unit_kind = ?
                """,
                (generation_id, rel_path, CommitUnitKind.DELETE_PATH.value),
            )
            assert evidence is not None
            if int(evidence["unit_count"]) != 1 or int(evidence["end_count"]) != 1:
                raise RunLedgerStateError(
                    "path deletion requires one storage-confirmed deletion unit"
                )
            connection.execute(
                """
                DELETE FROM file_states
                WHERE generation_id = ? AND rel_path = ?
                """,
                (generation_id, rel_path),
            )

    def superseded_point_ids(
        self,
        generation_id: str,
        rel_path: str,
        *,
        source_digest: str,
    ) -> tuple[str, ...]:
        """Return the points claimed by one path's units at a given digest.

        This is the exact set :meth:`reopen_drifted_path` is about to stop
        claiming, so it is what the caller must drop from storage first. Taken
        from the ledger rather than by asking storage which points a path
        holds, because the two answers differ once the fresh content has
        already been written: a storage query returns the superseded points and
        the replacement points together, and dropping that union would delete
        the very content the re-record is about to claim.
        """
        validate_rel_path(rel_path)
        with ledger_connection(self.path) as connection:
            rows: list[_PointIdRow] = fetch_all(
                connection,
                """
                SELECT points.point_id
                FROM commit_point_ids AS points
                JOIN commit_units AS units
                  ON units.generation_id = points.generation_id
                 AND units.unit_id = points.unit_id
                WHERE units.generation_id = ? AND units.rel_path = ?
                  AND units.unit_kind = ? AND units.source_digest = ?
                ORDER BY units.segment_ordinal, points.point_ordinal,
                         points.point_id
                """,
                (
                    generation_id,
                    rel_path,
                    CommitUnitKind.UPSERT.value,
                    source_digest,
                ),
            )
        return tuple(str(row["point_id"]) for row in rows)

    def reopen_drifted_path(
        self,
        generation_id: str,
        rel_path: str,
        *,
        superseded_digest: str,
    ) -> int:
        """Re-open one indexed path whose source changed after it was indexed.

        A resumed generation carries the file states of the attempt that
        failed. When a path was marked indexed there and its source has since
        changed, the fresh segments describe different content under a new
        digest, so they can neither be recognised as already committed nor
        recorded on top of an indexed path. Superseding clears the stale
        upsert evidence and the indexed state so the path is ingested again
        from nothing.

        Only the superseded digest's upsert units are removed. Deletion units
        survive, because they are the durable record that the previously
        published points were removed from storage - the caller performs that
        deletion before calling this, so a crash between the two replays as a
        no-op rather than stranding points.

        Args:
            generation_id: The resumed generation being repaired.
            rel_path: The project-relative path to re-open.
            superseded_digest: The digest recorded when the path was indexed.

        Returns:
            The number of stale upsert units removed.

        Raises:
            RunLedgerStateError: When the generation has left ingestion, so
                its file states can no longer change.
        """
        validate_rel_path(rel_path)
        with ledger_transaction(self.path) as connection:
            generation = self._require_mutable_generation(connection, generation_id)
            if generation["finalization_phase"] != FinalizationPhase.INGESTING.value:
                raise RunLedgerStateError(
                    "cannot re-open a path after finalization begins"
                )
            removed = connection.execute(
                """
                DELETE FROM commit_units
                WHERE generation_id = ? AND rel_path = ?
                  AND unit_kind = ? AND source_digest = ?
                """,
                (
                    generation_id,
                    rel_path,
                    CommitUnitKind.UPSERT.value,
                    superseded_digest,
                ),
            ).rowcount
            connection.execute(
                """
                DELETE FROM file_states
                WHERE generation_id = ? AND rel_path = ?
                """,
                (generation_id, rel_path),
            )
            return removed

    def iter_file_states(
        self,
        generation_id: str,
        *,
        converged_only: bool = False,
        batch_size: int = FETCH_BATCH,
    ) -> Iterator[FileState]:
        """Yield explicit outcomes without materializing generation metadata."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        last_path: str | None = None
        while True:
            with ledger_connection(self.path) as connection:
                rows: list[FileStateRow]
                if last_path is None:
                    rows = fetch_all(
                        connection,
                        """
                        SELECT * FROM file_states
                        WHERE generation_id = ?
                        ORDER BY rel_path LIMIT ?
                        """,
                        (generation_id, batch_size),
                    )
                else:
                    rows = fetch_all(
                        connection,
                        """
                        SELECT * FROM file_states
                        WHERE generation_id = ? AND rel_path > ?
                        ORDER BY rel_path LIMIT ?
                        """,
                        (generation_id, last_path, batch_size),
                    )
            if not rows:
                return
            for row in rows:
                state = file_state_from_row(row)
                if not converged_only or state.converged:
                    yield state
            last_path = str(rows[-1]["rel_path"])

    def file_states_for_paths(
        self,
        generation_id: str,
        rel_paths: tuple[str, ...],
    ) -> dict[str, FileState]:
        """Return one bounded indexed file-state page keyed by relative path."""
        if len(rel_paths) > FETCH_BATCH:
            raise ValueError(f"file-state lookup accepts at most {FETCH_BATCH} paths")
        if not rel_paths:
            return {}
        unique_paths = tuple(dict.fromkeys(rel_paths))
        placeholders = ", ".join("?" for _path in unique_paths)
        with ledger_connection(self.path) as connection:
            rows: list[FileStateRow] = fetch_all(
                connection,
                f"""
                SELECT * FROM file_states
                WHERE generation_id = ? AND rel_path IN ({placeholders})
                """,
                (generation_id, *unique_paths),
            )
        return {
            state.rel_path: state
            for state in (file_state_from_row(row) for row in rows)
        }

    def indexed_digests_for_paths(
        self,
        generation_id: str,
        rel_paths: tuple[str, ...],
    ) -> dict[str, str]:
        """Return the recorded digest of every named path already indexed.

        Paths absent from the generation, recorded in any state other than
        indexed, or carrying no digest are omitted, so the result contains
        exactly the paths whose recorded content can be compared against a
        freshly observed digest. The lookup is chunked internally, so callers
        may pass an unbounded path set.
        """
        unique_paths = tuple(dict.fromkeys(rel_paths))
        digests: dict[str, str] = {}
        for start in range(0, len(unique_paths), FETCH_BATCH):
            page = unique_paths[start : start + FETCH_BATCH]
            for rel_path, state in self.file_states_for_paths(
                generation_id, page
            ).items():
                if state.state is FileStateKind.INDEXED and state.content_hash:
                    digests[rel_path] = state.content_hash
        return digests

    def retained_point_ids_for_candidates(
        self,
        generation_id: str,
        point_ids: tuple[str, ...],
    ) -> frozenset[str]:
        """Return retained identities from one bounded store-page candidate set."""
        if len(point_ids) > FETCH_BATCH:
            raise ValueError(f"retained-point lookup accepts at most {FETCH_BATCH} IDs")
        if not point_ids:
            return frozenset()
        unique_ids = tuple(dict.fromkeys(point_ids))
        placeholders = ", ".join("?" for _point_id in unique_ids)
        with ledger_connection(self.path) as connection:
            # Candidate IDs are the bounded input, so keep them as the outer
            # loop.  A regular JOIN lets SQLite start from every indexed file
            # state and probe the candidate set, making each store page scale
            # with the entire generation during finalization.
            #
            # The points table is deliberately NOT constrained to the queried
            # generation. Carried-forward file states preserve the generation
            # that produced their evidence while living under the current one,
            # so their units - and therefore their points - belong to the
            # parent. The join chain already pins points to whichever
            # generation owns the matching unit; constraining them to the
            # queried generation instead drops every inherited point, which
            # then reads as obsolete and is deleted.
            rows: list[_PointIdRow] = fetch_all(
                connection,
                f"""
                SELECT points.point_id
                FROM commit_point_ids AS points
                CROSS JOIN commit_units AS units
                  ON units.generation_id = points.generation_id
                 AND units.unit_id = points.unit_id
                CROSS JOIN file_states AS states
                  ON states.evidence_generation_id = units.generation_id
                 AND states.rel_path = units.rel_path
                WHERE points.point_id IN ({placeholders})
                  AND units.unit_kind = ?
                  AND units.source_digest = states.content_hash
                  AND states.generation_id = ?
                  AND states.state = ?
                """,
                (
                    *unique_ids,
                    CommitUnitKind.UPSERT.value,
                    generation_id,
                    FileStateKind.INDEXED.value,
                ),
            )
        return frozenset(str(row["point_id"]) for row in rows)


def file_state_from_row(row: FileStateRow) -> FileState:
    from .._job_errors import JobErrorKind

    try:
        return FileState(
            rel_path=row["rel_path"],
            state=FileStateKind(row["state"]),
            kind=ContentKind(row["content_kind"])
            if row["content_kind"] is not None
            else None,
            content_hash=row["content_hash"],
            admission_reason=AdmissionReason(row["admission_reason"])
            if row["admission_reason"] is not None
            else None,
            error_kind=JobErrorKind(row["error_kind"])
            if row["error_kind"] is not None
            else None,
            detail=row["detail"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RunLedgerCorruptionError("stored file state is malformed") from exc
