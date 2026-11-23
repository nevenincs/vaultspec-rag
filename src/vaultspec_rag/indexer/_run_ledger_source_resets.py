"""Run-ledger record of selected-source resets and the epoch that fences them."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .._source_types import PublicSourceType
from ._run_ledger_models import (
    SOURCE_RESET_ORDER,
    SourceResetEpochError,
    SourceResetPhase,
    SourceResetState,
    column_int,
    column_text,
    fetch_one,
    in_ledger_transaction,
    ledger_connection,
)
from ._run_ledger_publication_proofs import retire_source_publication

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

__all__ = ["RunLedgerSourceResetMethods", "read_source_reset"]

_SELECT_RESET = """
    SELECT * FROM source_resets
    WHERE source_type = ? AND root_identity = ? AND backend_identity = ?
"""


def _concrete(source_type: PublicSourceType) -> PublicSourceType:
    if source_type is PublicSourceType.COMBINED:
        raise ValueError("a reset names one concrete source")
    return source_type


def _identity(root_identity: str, backend_identity: str) -> None:
    if not root_identity.strip() or not backend_identity.strip():
        raise ValueError("reset identity fields must be non-empty")


def _state_from_row(row: sqlite3.Row) -> SourceResetState:
    return SourceResetState(
        source_type=PublicSourceType(column_text(row, "source_type")),
        root_identity=column_text(row, "root_identity"),
        backend_identity=column_text(row, "backend_identity"),
        epoch=column_int(row, "epoch"),
        generation_id=column_text(row, "generation_id"),
        phase=SourceResetPhase(column_text(row, "phase")),
    )


def _read_reset(
    connection: sqlite3.Connection,
    source_type: PublicSourceType,
    root_identity: str,
    backend_identity: str,
) -> SourceResetState | None:
    row: sqlite3.Row | None = fetch_one(
        connection,
        _SELECT_RESET,
        (source_type.value, root_identity, backend_identity),
    )
    return None if row is None else _state_from_row(row)


def read_source_reset(
    path: Path,
    source_type: PublicSourceType,
    root_identity: str,
    backend_identity: str,
) -> SourceResetState | None:
    """Read one source's latest reset from a ledger already open at this format.

    The per-call fence check: it skips the schema verification a
    :class:`RunLedger` open performs, because the caller opened one when it
    captured the epoch it is now checking.
    """
    with ledger_connection(path) as connection:
        return _read_reset(
            connection, _concrete(source_type), root_identity, backend_identity
        )


class RunLedgerSourceResetMethods:
    """Own the durable phases and epoch of every selected-source reset."""

    if TYPE_CHECKING:
        path: Path

    def source_reset_state(
        self,
        source_type: PublicSourceType,
        root_identity: str,
        backend_identity: str,
    ) -> SourceResetState | None:
        """Return the latest reset of one source, or ``None`` if never reset."""
        _identity(root_identity, backend_identity)
        return read_source_reset(
            self.path, source_type, root_identity, backend_identity
        )

    def begin_source_reset(
        self,
        source_type: PublicSourceType,
        root_identity: str,
        backend_identity: str,
        generation_id: str,
    ) -> SourceResetState:
        """Record reset intent and retire the source's publication authority.

        One transaction advances the epoch, records ``INTENT``, deletes the
        source's proof and receipts, and invalidates every other resumable
        generation of the source. A reader or writer holding the previous
        epoch is fenced from the moment it commits, before any storage is
        touched.

        A call naming the generation that already owns the latest reset
        changes nothing and returns that reset as recorded, whatever its
        phase: a replay resumes its own reset, and a completed one is never
        repeated over confirmed replacement work.
        """
        source = _concrete(source_type)
        _identity(root_identity, backend_identity)
        if not generation_id.strip():
            raise ValueError("a reset must name the generation that owns it")

        def body(connection: sqlite3.Connection) -> SourceResetState:
            current = _read_reset(connection, source, root_identity, backend_identity)
            if current is not None and current.generation_id == generation_id:
                return current
            epoch = 1 if current is None else current.epoch + 1
            retire_source_publication(
                connection,
                source,
                root_identity,
                backend_identity,
                keep_generation_id=generation_id,
            )
            connection.execute(
                """
                INSERT INTO source_resets (
                    source_type, root_identity, backend_identity, epoch,
                    generation_id, phase, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_type, root_identity, backend_identity)
                DO UPDATE SET epoch = excluded.epoch,
                    generation_id = excluded.generation_id,
                    phase = excluded.phase,
                    updated_at = excluded.updated_at
                """,
                (
                    source.value,
                    root_identity,
                    backend_identity,
                    epoch,
                    generation_id,
                    SourceResetPhase.INTENT.value,
                    time.time(),
                ),
            )
            return SourceResetState(
                source_type=source,
                root_identity=root_identity,
                backend_identity=backend_identity,
                epoch=epoch,
                generation_id=generation_id,
                phase=SourceResetPhase.INTENT,
            )

        return in_ledger_transaction(self.path, body)

    def advance_source_reset(
        self,
        state: SourceResetState,
        phase: SourceResetPhase,
    ) -> SourceResetState:
        """Record that *state*'s reset reached *phase*.

        Only the reset that still owns the epoch may advance, and only
        forward; re-recording the current phase is a no-op, so a recovery
        that repeats a confirmed step converges.

        Raises:
            SourceResetEpochError: A later reset superseded *state*.
        """

        def body(connection: sqlite3.Connection) -> SourceResetState:
            current = _read_reset(
                connection,
                state.source_type,
                state.root_identity,
                state.backend_identity,
            )
            if (
                current is None
                or current.epoch != state.epoch
                or current.generation_id != state.generation_id
            ):
                raise SourceResetEpochError(
                    f"{state.source_type.value} reset epoch {state.epoch} was "
                    "superseded before it could advance"
                )
            if SOURCE_RESET_ORDER.index(phase) < SOURCE_RESET_ORDER.index(
                current.phase
            ):
                raise SourceResetEpochError(
                    f"{state.source_type.value} reset cannot move back from "
                    f"{current.phase.value} to {phase.value}"
                )
            connection.execute(
                """
                UPDATE source_resets SET phase = ?, updated_at = ?
                WHERE source_type = ? AND root_identity = ?
                  AND backend_identity = ?
                """,
                (
                    phase.value,
                    time.time(),
                    state.source_type.value,
                    state.root_identity,
                    state.backend_identity,
                ),
            )
            return SourceResetState(
                source_type=current.source_type,
                root_identity=current.root_identity,
                backend_identity=current.backend_identity,
                epoch=current.epoch,
                generation_id=current.generation_id,
                phase=phase,
            )

        return in_ledger_transaction(self.path, body)
