"""Run-ledger publication state transitions and retention compaction."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ._content_policy import AdmissionReason
from ._file_state import FileStateKind
from ._run_ledger_models import (
    FINALIZATION_ORDER,
    CommitUnitKind,
    FinalizationPhase,
    RunGeneration,
    RunLedgerStateError,
    RunTerminalState,
)

if TYPE_CHECKING:
    import sqlite3
    from contextlib import AbstractContextManager

    from ._run_ledger_models import RunGeneration


class RunLedgerFinalizationMethods:
    if TYPE_CHECKING:

        def _transaction(self) -> AbstractContextManager[sqlite3.Connection]: ...

        @staticmethod
        def _require_mutable_generation(
            connection: sqlite3.Connection, generation_id: str
        ) -> sqlite3.Row: ...

        @staticmethod
        def _generation_from_row(row: sqlite3.Row) -> RunGeneration: ...

    def advance_finalization(
        self,
        generation_id: str,
        phase: FinalizationPhase,
    ) -> RunGeneration:
        """Advance exactly one confirmed external finalization boundary."""
        if not isinstance(phase, FinalizationPhase):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("phase must be a FinalizationPhase")
        if phase is FinalizationPhase.COMPACTED:
            raise RunLedgerStateError(
                "only compact() may commit the compacted finalization phase"
            )
        now = time.time()
        with self._transaction() as connection:
            row = self._require_mutable_generation(connection, generation_id)
            current = FinalizationPhase(row["finalization_phase"])
            if phase is current:
                return self._generation_from_row(row)
            current_index = FINALIZATION_ORDER.index(current)
            if current_index + 1 >= len(FINALIZATION_ORDER):
                raise RunLedgerStateError("generation finalization is already complete")
            if phase is not FINALIZATION_ORDER[current_index + 1]:
                raise RunLedgerStateError(
                    f"cannot advance finalization from {current.value} to {phase.value}"
                )
            if current is FinalizationPhase.INGESTING:
                self._assert_ready_for_finalization(connection, generation_id)
            connection.execute(
                """
                UPDATE generations SET finalization_phase = ?, updated_at = ?
                WHERE generation_id = ?
                """,
                (phase.value, now, generation_id),
            )
            updated = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
            assert updated is not None
            return self._generation_from_row(updated)

    @staticmethod
    def _assert_ready_for_finalization(
        connection: sqlite3.Connection,
        generation_id: str,
    ) -> None:
        incomplete = connection.execute(
            """
            SELECT rel_path, unit_kind
            FROM commit_units
            WHERE generation_id = ?
            GROUP BY rel_path, unit_kind
            HAVING MIN(segment_ordinal) != 0
                OR MAX(segment_ordinal) != COUNT(*) - 1
                OR SUM(segment_ordinal) != (COUNT(*) * (COUNT(*) - 1)) / 2
                OR SUM(is_file_end) != 1
                OR MAX(CASE WHEN is_file_end = 1 THEN segment_ordinal END)
                    != COUNT(*) - 1
            LIMIT 1
            """,
            (generation_id,),
        ).fetchone()
        if incomplete is not None:
            raise RunLedgerStateError(
                "cannot finalize an incomplete commit-unit sequence for "
                f"{incomplete['rel_path']}"
            )
        missing_state = connection.execute(
            """
            SELECT units.rel_path
            FROM commit_units AS units
            LEFT JOIN file_states AS states
              ON states.generation_id = units.generation_id
             AND states.rel_path = units.rel_path
            WHERE units.generation_id = ? AND units.unit_kind = ?
            GROUP BY units.rel_path, states.state, states.content_hash
            HAVING states.state IS NULL
                OR states.state != ?
                OR MIN(units.source_digest) != states.content_hash
                OR MAX(units.source_digest) != states.content_hash
            LIMIT 1
            """,
            (
                generation_id,
                CommitUnitKind.UPSERT.value,
                FileStateKind.INDEXED.value,
            ),
        ).fetchone()
        if missing_state is not None:
            raise RunLedgerStateError(
                "cannot finalize storage evidence without matching indexed state for "
                f"{missing_state['rel_path']}"
            )
        undeleted_manifest = connection.execute(
            """
            SELECT units.rel_path
            FROM commit_units AS units
            JOIN file_states AS states
              ON states.generation_id = units.generation_id
             AND states.rel_path = units.rel_path
            WHERE units.generation_id = ? AND units.unit_kind = ?
            LIMIT 1
            """,
            (generation_id, CommitUnitKind.DELETE_PATH.value),
        ).fetchone()
        if undeleted_manifest is not None:
            raise RunLedgerStateError(
                "cannot finalize a deleted path retained in the manifest: "
                f"{undeleted_manifest['rel_path']}"
            )
        unresolved = connection.execute(
            """
            SELECT rel_path FROM file_states
            WHERE generation_id = ? AND (
                state NOT IN (?, ?)
                OR (
                    state = ? AND (
                        admission_reason = ?
                        OR admission_reason IS NULL
                        OR (
                            admission_reason IN (?, ?)
                            AND content_hash IS NULL
                        )
                    )
                )
            )
            LIMIT 1
            """,
            (
                generation_id,
                FileStateKind.INDEXED.value,
                FileStateKind.POLICY_REJECTED.value,
                FileStateKind.POLICY_REJECTED.value,
                AdmissionReason.SOURCE_PROBE_FAILED.value,
                AdmissionReason.SOURCE_TOO_LARGE.value,
                AdmissionReason.SOURCE_BINARY.value,
            ),
        ).fetchone()
        if unresolved is not None:
            raise RunLedgerStateError(
                f"cannot finalize unresolved file state for {unresolved['rel_path']}"
            )

    def finish_generation(
        self,
        generation_id: str,
        terminal_state: RunTerminalState,
        *,
        detail: str | None = None,
    ) -> RunGeneration:
        """Make one generation terminal; successful publication is immutable."""
        if terminal_state is RunTerminalState.RUNNING:
            raise ValueError("terminal_state must be terminal")
        if detail is not None and not detail.strip():
            raise ValueError("detail must not be empty")
        now = time.time()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(generation_id)
            current = RunTerminalState(row["terminal_state"])
            if current is not RunTerminalState.RUNNING:
                if current is terminal_state and row["terminal_detail"] == detail:
                    return self._generation_from_row(row)
                raise RunLedgerStateError("terminal generations are immutable")
            phase = FinalizationPhase(row["finalization_phase"])
            if (
                terminal_state is RunTerminalState.SUCCEEDED
                and phase is not FinalizationPhase.GENERATION_PUBLISHED
                and phase is not FinalizationPhase.COMPACTED
            ):
                raise RunLedgerStateError(
                    "a generation succeeds only after durable publication"
                )
            # Only an unsuccessful outcome advances the counter that bounds
            # resumption. A success retires the generation anyway, so the
            # count never needs clearing.
            failure_increment = 0 if terminal_state is RunTerminalState.SUCCEEDED else 1
            connection.execute(
                """
                UPDATE generations
                SET terminal_state = ?, terminal_detail = ?, updated_at = ?,
                    consecutive_failures = consecutive_failures + ?
                WHERE generation_id = ?
                """,
                (
                    terminal_state.value,
                    detail,
                    now,
                    failure_increment,
                    generation_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
            assert updated is not None
            return self._generation_from_row(updated)

    def compact(self, keep_generation_id: str) -> int:
        """Remove obsolete terminal generations after publication.

        The retained generation and every still-running generation are never
        removed.  Cascading foreign keys compact units and file states in the
        same transaction.

        A generation cited as evidence by a surviving file state is also
        never removed. Carried-forward states pin the generation that
        produced their evidence, and the commit units that vouch for their
        stored points live under it; deleting it cascades those units away,
        after which every retained-point lookup reads the inherited points
        as obsolete and the next publication purges the entire collection.

        The keep must be the newest published generation of its collection;
        compacting an older one is refused.
        """
        with self._transaction() as connection:
            keep = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?",
                (keep_generation_id,),
            ).fetchone()
            if keep is None:
                raise KeyError(keep_generation_id)
            if (
                RunTerminalState(keep["terminal_state"])
                is not RunTerminalState.SUCCEEDED
            ):
                raise RunLedgerStateError(
                    "only a published successful generation compacts"
                )
            # An older keep would restamp itself newest and delete - or strand
            # the evidence of - the manifest storage actually reflects, and the
            # next carry-forward would then read stale history as current.
            # Strictly newer is the predicate on purpose: two stamps taken from
            # one coarse clock reading cannot be ordered, and the in-order
            # publisher must never be refused over a timestamp tie.
            newer = connection.execute(
                """
                SELECT 1 FROM generations
                WHERE generation_id != ?
                  AND source_type = ?
                  AND collection_identity = ?
                  AND terminal_state = ?
                  AND updated_at > ?
                LIMIT 1
                """,
                (
                    keep_generation_id,
                    keep["source_type"],
                    keep["collection_identity"],
                    RunTerminalState.SUCCEEDED.value,
                    keep["updated_at"],
                ),
            ).fetchone()
            if newer is not None:
                raise RunLedgerStateError(
                    "only the newest published generation compacts its collection"
                )
            result = connection.execute(
                """
                DELETE FROM generations
                WHERE generation_id != ?
                  AND source_type = ?
                  AND collection_identity = ?
                  AND terminal_state IN (?, ?)
                  AND generation_id NOT IN (
                      SELECT states.evidence_generation_id
                      FROM file_states AS states
                      JOIN generations AS owners
                        ON owners.generation_id = states.generation_id
                      WHERE owners.generation_id = ?
                         OR owners.terminal_state NOT IN (?, ?)
                  )
                """,
                (
                    keep_generation_id,
                    keep["source_type"],
                    keep["collection_identity"],
                    RunTerminalState.SUCCEEDED.value,
                    RunTerminalState.INVALIDATED.value,
                    keep_generation_id,
                    RunTerminalState.SUCCEEDED.value,
                    RunTerminalState.INVALIDATED.value,
                ),
            )
            connection.execute(
                """
                UPDATE generations SET finalization_phase = ?, updated_at = ?
                WHERE generation_id = ?
                """,
                (FinalizationPhase.COMPACTED.value, time.time(), keep_generation_id),
            )
            return result.rowcount
