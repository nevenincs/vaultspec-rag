"""Transactional storage-confirmed progress for resumable index generations.

The ledger is deliberately local and CPU-only.  Vector-store mutation happens
first; callers record the matching unit only after that mutation is confirmed.
Consequently a crash may replay one idempotent unit, but the ledger can never
claim work that did not reach storage.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any, Final

from ._content_policy import AdmissionReason, ContentKind
from ._file_state import FileState, FileStateKind

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

__all__ = [
    "CommitUnit",
    "CommitUnitKind",
    "FinalizationPhase",
    "RunGeneration",
    "RunLedger",
    "RunLedgerCompatibilityError",
    "RunLedgerCorruptionError",
    "RunLedgerError",
    "RunLedgerStateError",
    "RunOperation",
    "RunSignature",
    "RunTerminalState",
]

_SCHEMA_VERSION: Final = 2
_FETCH_BATCH: Final = 256
_DIGEST_REPR_LENGTH: Final = 128


class RunLedgerError(RuntimeError):
    """Base class for durable run-ledger failures."""


class RunLedgerCompatibilityError(RunLedgerError):
    """The ledger schema or requested generation is incompatible."""


class RunLedgerCorruptionError(RunLedgerError):
    """SQLite reported corrupt durable state."""


class RunLedgerStateError(RunLedgerError):
    """A requested transition violates immutable generation state."""


class RunOperation(StrEnum):
    """Closed indexing operation vocabulary stored in generation identity."""

    FULL = "full"
    INCREMENTAL = "incremental"
    SCOPED_INCREMENTAL = "scoped_incremental"


class CommitUnitKind(StrEnum):
    """Idempotent external mutation represented by one ledger unit."""

    UPSERT = "upsert"
    DELETE = "delete"


class FinalizationPhase(StrEnum):
    """Ordered externally-confirmed generation publication phases."""

    INGESTING = "ingesting"
    STALE_RECONCILED = "stale_reconciled"
    METADATA_PUBLISHED = "metadata_published"
    GENERATION_PUBLISHED = "generation_published"
    COMPACTED = "compacted"


_FINALIZATION_ORDER: Final = tuple(FinalizationPhase)


class RunTerminalState(StrEnum):
    """Stable terminal classifications for one generation."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"
    REBUILD_INCOMPLETE = "rebuild_incomplete"


@dataclass(frozen=True, slots=True)
class RunSignature:
    """Canonical compatibility identity for one resumable generation."""

    root_identity: str
    collection_identity: str
    source_type: ContentKind
    operation: RunOperation
    clean: bool
    model_identity: str
    dense_dimensions: int
    embedding_schema: int
    payload_schema: int
    content_epoch: str
    membership_epoch: str
    preprocessing_identity: str
    configuration_fingerprint: str
    policy_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "root_identity",
            "collection_identity",
            "model_identity",
            "content_epoch",
            "membership_epoch",
            "preprocessing_identity",
            "configuration_fingerprint",
            "policy_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(self.source_type, ContentKind):
            raise TypeError("source_type must be a ContentKind")
        if not isinstance(self.operation, RunOperation):
            raise TypeError("operation must be a RunOperation")
        for name in ("dense_dimensions", "embedding_schema", "payload_schema"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    @property
    def canonical_json(self) -> str:
        """Return deterministic serialized compatibility evidence."""
        payload = asdict(self)
        payload["source_type"] = self.source_type.value
        payload["operation"] = self.operation.value
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @property
    def fingerprint(self) -> str:
        """Return a stable digest suitable for indexed lookup."""
        return hashlib.blake2b(self.canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CommitUnit:
    """One bounded storage mutation confirmed before ledger insertion."""

    rel_path: str
    kind: CommitUnitKind
    segment_ordinal: int
    is_file_end: bool
    point_ids: tuple[str, ...]
    source_digest: str | None = None

    def __post_init__(self) -> None:
        _validate_rel_path(self.rel_path)
        if not isinstance(self.kind, CommitUnitKind):
            raise TypeError("kind must be a CommitUnitKind")
        if isinstance(self.segment_ordinal, bool) or self.segment_ordinal < 0:
            raise ValueError("segment_ordinal must be a non-negative integer")
        if not isinstance(self.is_file_end, bool):
            raise TypeError("is_file_end must be a bool")
        if not self.point_ids or any(not point_id for point_id in self.point_ids):
            raise ValueError("point_ids must contain non-empty identifiers")
        if len(set(self.point_ids)) != len(self.point_ids):
            raise ValueError("point_ids must be unique within a commit unit")
        if self.kind is CommitUnitKind.UPSERT:
            if not _is_digest(self.source_digest):
                raise ValueError("upsert units require a lowercase BLAKE2b-512 digest")
        elif self.source_digest is not None:
            raise ValueError("deletion units must not carry a source digest")
        if self.kind is CommitUnitKind.DELETE and (
            self.segment_ordinal != 0 or not self.is_file_end
        ):
            raise ValueError("a deletion is exactly one commit unit")

    @property
    def identity(self) -> str:
        """Return deterministic idempotency identity for this unit."""
        payload = {
            "kind": self.kind.value,
            "path": self.rel_path,
            "source_digest": self.source_digest,
            "segment_ordinal": self.segment_ordinal,
            "is_file_end": self.is_file_end,
            "point_ids": self.point_ids,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.blake2b(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RunGeneration:
    """Immutable projection of one durable generation row."""

    generation_id: str
    signature: RunSignature
    finalization_phase: FinalizationPhase
    terminal_state: RunTerminalState
    destructive_intent: bool
    created_at: float
    updated_at: float
    terminal_detail: str | None = None

    @property
    def complete(self) -> bool:
        """Return whether the generation is immutably successful."""
        return self.terminal_state is RunTerminalState.SUCCEEDED


class RunLedger:
    """Transactional per-root indexing generation ledger."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as connection:
                self._initialize(connection)
                self._verify_integrity(connection)
        except sqlite3.DatabaseError as exc:
            raise RunLedgerCorruptionError(
                f"cannot open run ledger {self.path}: {exc}"
            ) from exc

    def start_generation(self, signature: RunSignature) -> RunGeneration:
        """Resume one compatible active generation or invalidate and replace it."""
        now = time.time()
        with self._transaction() as connection:
            active = connection.execute(
                """
                SELECT * FROM generations
                WHERE source_type = ? AND terminal_state = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (signature.source_type.value, RunTerminalState.RUNNING.value),
            ).fetchone()
            if (
                active is not None
                and active["signature_fingerprint"] == signature.fingerprint
            ):
                return self._generation_from_row(active)
            if active is not None:
                connection.execute(
                    """
                    UPDATE generations
                    SET terminal_state = ?, terminal_detail = ?, updated_at = ?
                    WHERE generation_id = ?
                    """,
                    (
                        RunTerminalState.INVALIDATED.value,
                        "generation signature changed",
                        now,
                        active["generation_id"],
                    ),
                )
            generation_id = uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO generations (
                    generation_id, source_type, signature_fingerprint,
                    signature_json, finalization_phase, terminal_state,
                    destructive_intent, created_at, updated_at, terminal_detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    generation_id,
                    signature.source_type.value,
                    signature.fingerprint,
                    signature.canonical_json,
                    FinalizationPhase.INGESTING.value,
                    RunTerminalState.RUNNING.value,
                    int(signature.clean),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
            assert row is not None
            return self._generation_from_row(row)

    def generation(self, generation_id: str) -> RunGeneration:
        """Return one generation or raise for an unknown identifier."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(generation_id)
        return self._generation_from_row(row)

    def record_storage_confirmed_unit(
        self,
        generation_id: str,
        unit: CommitUnit,
    ) -> bool:
        """Durably record one already-confirmed external storage mutation.

        Returns ``True`` for the first record and ``False`` for exact replay.
        A reused identity with different evidence is rejected.
        """
        now = time.time()
        point_ids_json = json.dumps(unit.point_ids, separators=(",", ":"))
        with self._transaction() as connection:
            generation = self._require_mutable_generation(connection, generation_id)
            if generation["finalization_phase"] != FinalizationPhase.INGESTING.value:
                raise RunLedgerStateError("cannot add units after finalization begins")
            existing = connection.execute(
                """
                SELECT * FROM commit_units
                WHERE generation_id = ? AND unit_id = ?
                """,
                (generation_id, unit.identity),
            ).fetchone()
            if existing is not None:
                if (
                    existing["rel_path"] != unit.rel_path
                    or existing["unit_kind"] != unit.kind.value
                    or existing["segment_ordinal"] != unit.segment_ordinal
                    or bool(existing["is_file_end"]) is not unit.is_file_end
                    or existing["source_digest"] != unit.source_digest
                    or existing["point_ids_json"] != point_ids_json
                ):
                    raise RunLedgerStateError("commit-unit identity collision")
                return False
            sibling = connection.execute(
                """
                SELECT source_digest FROM commit_units
                WHERE generation_id = ? AND rel_path = ? AND unit_kind = ?
                LIMIT 1
                """,
                (generation_id, unit.rel_path, unit.kind.value),
            ).fetchone()
            if sibling is not None and (
                sibling["source_digest"] != unit.source_digest
            ):
                raise RunLedgerStateError(
                    "segments for one path must share one source digest"
                )
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
            connection.execute(
                "UPDATE generations SET updated_at = ? WHERE generation_id = ?",
                (now, generation_id),
            )
            return True

    def unit_committed(self, generation_id: str, unit: CommitUnit) -> bool:
        """Return whether an exact storage-confirmed unit is durable."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM commit_units
                WHERE generation_id = ? AND unit_id = ?
                """,
                (generation_id, unit.identity),
            ).fetchone()
        return row is not None

    def file_complete(self, generation_id: str, rel_path: str) -> bool:
        """Return whether every segment (or the deletion unit) is committed."""
        _validate_rel_path(rel_path)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT unit_kind, segment_ordinal, is_file_end
                FROM commit_units
                WHERE generation_id = ? AND rel_path = ?
                ORDER BY segment_ordinal
                """,
                (generation_id, rel_path),
            ).fetchall()
        if not rows:
            return False
        kinds = {row["unit_kind"] for row in rows}
        if len(kinds) != 1:
            return False
        end_ordinals = [
            row["segment_ordinal"] for row in rows if bool(row["is_file_end"])
        ]
        if len(end_ordinals) != 1:
            return False
        expected = end_ordinals[0] + 1
        return (
            len(rows) == expected
            and [row["segment_ordinal"] for row in rows] == list(range(expected))
        )

    def iter_units(
        self,
        generation_id: str,
        *,
        batch_size: int = _FETCH_BATCH,
    ) -> Iterator[CommitUnit]:
        """Yield committed units using bounded row-wise iteration."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT * FROM commit_units
                WHERE generation_id = ?
                ORDER BY rel_path, unit_kind, segment_ordinal
                """,
                (generation_id,),
            )
            while rows := cursor.fetchmany(batch_size):
                for row in rows:
                    yield CommitUnit(
                        rel_path=row["rel_path"],
                        kind=CommitUnitKind(row["unit_kind"]),
                        source_digest=row["source_digest"],
                        segment_ordinal=row["segment_ordinal"],
                        is_file_end=bool(row["is_file_end"]),
                        point_ids=tuple(json.loads(row["point_ids_json"])),
                    )

    def record_file_state(self, generation_id: str, state: FileState) -> None:
        """Upsert the latest explicit per-file convergence outcome."""
        with self._transaction() as connection:
            generation = self._require_mutable_generation(connection, generation_id)
            if generation["finalization_phase"] != FinalizationPhase.INGESTING.value:
                raise RunLedgerStateError(
                    "cannot change file state after finalization begins"
                )
            connection.execute(
                """
                INSERT INTO file_states (
                    generation_id, rel_path, state, content_kind, content_hash,
                    admission_reason, error_kind, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(generation_id, rel_path) DO UPDATE SET
                    state = excluded.state,
                    content_kind = excluded.content_kind,
                    content_hash = excluded.content_hash,
                    admission_reason = excluded.admission_reason,
                    error_kind = excluded.error_kind,
                    detail = excluded.detail
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
                ),
            )

    def iter_file_states(
        self,
        generation_id: str,
        *,
        converged_only: bool = False,
        batch_size: int = _FETCH_BATCH,
    ) -> Iterator[FileState]:
        """Yield explicit outcomes without materializing generation metadata."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT * FROM file_states
                WHERE generation_id = ? ORDER BY rel_path
                """,
                (generation_id,),
            )
            while rows := cursor.fetchmany(batch_size):
                for row in rows:
                    state = _file_state_from_row(row)
                    if not converged_only or state.converged:
                        yield state

    def advance_finalization(
        self,
        generation_id: str,
        phase: FinalizationPhase,
    ) -> RunGeneration:
        """Advance exactly one confirmed external finalization boundary."""
        if not isinstance(phase, FinalizationPhase):
            raise TypeError("phase must be a FinalizationPhase")
        now = time.time()
        with self._transaction() as connection:
            row = self._require_mutable_generation(connection, generation_id)
            current = FinalizationPhase(row["finalization_phase"])
            if phase is current:
                return self._generation_from_row(row)
            current_index = _FINALIZATION_ORDER.index(current)
            if current_index + 1 >= len(_FINALIZATION_ORDER):
                raise RunLedgerStateError("generation finalization is already complete")
            if phase is not _FINALIZATION_ORDER[current_index + 1]:
                raise RunLedgerStateError(
                    f"cannot advance finalization from {current.value} to {phase.value}"
                )
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
            connection.execute(
                """
                UPDATE generations
                SET terminal_state = ?, terminal_detail = ?, updated_at = ?
                WHERE generation_id = ?
                """,
                (terminal_state.value, detail, now, generation_id),
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
            result = connection.execute(
                """
                DELETE FROM generations
                WHERE generation_id != ? AND terminal_state != ?
                """,
                (keep_generation_id, RunTerminalState.RUNNING.value),
            )
            connection.execute(
                """
                UPDATE generations SET finalization_phase = ?, updated_at = ?
                WHERE generation_id = ?
                """,
                (FinalizationPhase.COMPACTED.value, time.time(), keep_generation_id),
            )
            return result.rowcount

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self, connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version not in (0, _SCHEMA_VERSION):
            raise RunLedgerCompatibilityError(
                "run ledger schema "
                f"{version} is not supported; expected {_SCHEMA_VERSION}"
            )
        if version == 0:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS generations (
                    generation_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    signature_fingerprint TEXT NOT NULL,
                    signature_json TEXT NOT NULL,
                    finalization_phase TEXT NOT NULL,
                    terminal_state TEXT NOT NULL,
                    destructive_intent INTEGER NOT NULL
                        CHECK(destructive_intent IN (0, 1)),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    terminal_detail TEXT
                );
                CREATE INDEX IF NOT EXISTS generations_active
                    ON generations(source_type, terminal_state, created_at DESC);

                CREATE TABLE IF NOT EXISTS commit_units (
                    generation_id TEXT NOT NULL REFERENCES generations(generation_id)
                        ON DELETE CASCADE,
                    unit_id TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    unit_kind TEXT NOT NULL,
                    source_digest TEXT,
                    segment_ordinal INTEGER NOT NULL,
                    is_file_end INTEGER NOT NULL CHECK(is_file_end IN (0, 1)),
                    point_ids_json TEXT NOT NULL,
                    committed_at REAL NOT NULL,
                    PRIMARY KEY(generation_id, unit_id),
                    UNIQUE(generation_id, rel_path, unit_kind, segment_ordinal)
                );
                CREATE INDEX IF NOT EXISTS commit_units_path
                    ON commit_units(generation_id, rel_path, segment_ordinal);

                CREATE TABLE IF NOT EXISTS file_states (
                    generation_id TEXT NOT NULL REFERENCES generations(generation_id)
                        ON DELETE CASCADE,
                    rel_path TEXT NOT NULL,
                    state TEXT NOT NULL,
                    content_kind TEXT,
                    content_hash TEXT,
                    admission_reason TEXT,
                    error_kind TEXT,
                    detail TEXT,
                    PRIMARY KEY(generation_id, rel_path)
                );
                CREATE INDEX IF NOT EXISTS file_states_state
                    ON file_states(generation_id, state, rel_path);
                """
            )
            connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            connection.commit()

    def _verify_integrity(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("PRAGMA quick_check").fetchall()
        if [row[0] for row in rows] != ["ok"]:
            raise RunLedgerCorruptionError("run ledger failed SQLite quick_check")

    @staticmethod
    def _require_mutable_generation(
        connection: sqlite3.Connection,
        generation_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM generations WHERE generation_id = ?",
            (generation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(generation_id)
        if RunTerminalState(row["terminal_state"]) is not RunTerminalState.RUNNING:
            raise RunLedgerStateError("terminal generations are immutable")
        return row

    @staticmethod
    def _generation_from_row(row: sqlite3.Row) -> RunGeneration:
        signature_payload: dict[str, Any] = json.loads(row["signature_json"])
        signature_payload["source_type"] = ContentKind(
            signature_payload["source_type"]
        )
        signature_payload["operation"] = RunOperation(signature_payload["operation"])
        return RunGeneration(
            generation_id=row["generation_id"],
            signature=RunSignature(**signature_payload),
            finalization_phase=FinalizationPhase(row["finalization_phase"]),
            terminal_state=RunTerminalState(row["terminal_state"]),
            destructive_intent=bool(row["destructive_intent"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            terminal_detail=row["terminal_detail"],
        )


def _validate_rel_path(rel_path: str) -> None:
    path = PurePosixPath(rel_path)
    if (
        not rel_path
        or rel_path == "."
        or path.is_absolute()
        or PureWindowsPath(rel_path).drive
        or "\0" in rel_path
        or "\\" in rel_path
        or ".." in path.parts
        or path.as_posix() != rel_path
    ):
        raise ValueError("rel_path must be canonical project-relative POSIX syntax")


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_REPR_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _file_state_from_row(row: Mapping[str, Any]) -> FileState:
    from .._job_errors import JobErrorKind

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
