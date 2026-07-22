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
    "INDEX_RUN_LEDGER_FILENAME",
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
    "index_run_ledger_path",
]

_SCHEMA_VERSION: Final = 6
_FETCH_BATCH: Final = 256
_DIGEST_REPR_LENGTH: Final = 128
INDEX_RUN_LEDGER_FILENAME: Final = "index_runs.sqlite3"
_LEGACY_CODE_RUN_LEDGER_FILENAME: Final = "code_index_runs.sqlite3"
_REQUIRED_SCHEMA: Final = {
    "generations": frozenset(
        {
            "generation_id",
            "source_type",
            "collection_identity",
            "signature_fingerprint",
            "signature_json",
            "finalization_phase",
            "terminal_state",
            "destructive_intent",
            "created_at",
            "updated_at",
            "terminal_detail",
            "parent_generation_id",
        }
    ),
    "commit_units": frozenset(
        {
            "generation_id",
            "unit_id",
            "rel_path",
            "unit_kind",
            "source_digest",
            "segment_ordinal",
            "is_file_end",
            "point_ids_json",
            "committed_at",
        }
    ),
    "commit_point_ids": frozenset(
        {"generation_id", "unit_id", "point_ordinal", "point_id"}
    ),
    "file_states": frozenset(
        {
            "generation_id",
            "rel_path",
            "state",
            "content_kind",
            "content_hash",
            "admission_reason",
            "error_kind",
            "detail",
            "evidence_generation_id",
        }
    ),
}


def index_run_ledger_path(data_root: Path) -> Path:
    """Return one shared per-root ledger path with legacy continuity."""
    root = Path(data_root)
    current = root / INDEX_RUN_LEDGER_FILENAME
    legacy = root / _LEGACY_CODE_RUN_LEDGER_FILENAME
    if current.exists() or not legacy.is_file():
        return current
    return legacy


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
    DELETE_PATH = "delete_path"
    DELETE_STALE = "delete_stale"


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


_RESUMABLE_STATES: Final = (
    RunTerminalState.RUNNING,
    RunTerminalState.FAILED,
    RunTerminalState.CANCELLED,
    RunTerminalState.REBUILD_INCOMPLETE,
)


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

    @property
    def content_compatibility_fingerprint(self) -> str:
        """Return identity for safely carrying a published file manifest."""
        payload = asdict(self)
        payload.pop("operation")
        payload.pop("clean")
        # Pipeline sizing shapes resumable commit-unit boundaries, so it must
        # remain part of the exact generation fingerprint.  It does not shape
        # deterministic chunk identities or published file content, however,
        # and must not prevent a new attempt from carrying a completed manifest.
        payload.pop("configuration_fingerprint")
        payload["source_type"] = self.source_type.value
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.blake2b(encoded.encode("utf-8")).hexdigest()


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
        if self.kind is not CommitUnitKind.UPSERT and self.point_ids != tuple(
            sorted(self.point_ids)
        ):
            raise ValueError("deletion point_ids must be in canonical order")
        if self.kind is CommitUnitKind.UPSERT:
            if not _is_digest(self.source_digest):
                raise ValueError("upsert units require a lowercase BLAKE2b-512 digest")
        elif self.source_digest is not None:
            raise ValueError("deletion units must not carry a source digest")
        if self.kind is not CommitUnitKind.UPSERT and (
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
    parent_generation_id: str | None = None

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
                self._verify_schema(connection)
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
                WHERE source_type = ?
                  AND terminal_state IN (?, ?, ?, ?)
                ORDER BY created_at DESC LIMIT 1
                """,
                (
                    signature.source_type.value,
                    *(state.value for state in _RESUMABLE_STATES),
                ),
            ).fetchone()
            if (
                active is not None
                and active["signature_fingerprint"] == signature.fingerprint
            ):
                if active["terminal_state"] != RunTerminalState.RUNNING.value:
                    connection.execute(
                        """
                        UPDATE generations
                        SET terminal_state = ?, terminal_detail = NULL, updated_at = ?
                        WHERE generation_id = ?
                        """,
                        (
                            RunTerminalState.RUNNING.value,
                            now,
                            active["generation_id"],
                        ),
                    )
                    active = connection.execute(
                        "SELECT * FROM generations WHERE generation_id = ?",
                        (active["generation_id"],),
                    ).fetchone()
                    assert active is not None
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
                    generation_id, source_type, collection_identity,
                    signature_fingerprint,
                    signature_json, finalization_phase, terminal_state,
                    destructive_intent, created_at, updated_at, terminal_detail,
                    parent_generation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    generation_id,
                    signature.source_type.value,
                    signature.collection_identity,
                    signature.fingerprint,
                    signature.canonical_json,
                    FinalizationPhase.INGESTING.value,
                    RunTerminalState.RUNNING.value,
                    int(signature.clean),
                    now,
                    now,
                ),
            )
            if not signature.clean:
                parent_generation_id = self._carry_published_manifest(
                    connection,
                    generation_id,
                    signature,
                )
                if parent_generation_id is not None:
                    connection.execute(
                        """
                        UPDATE generations SET parent_generation_id = ?
                        WHERE generation_id = ?
                        """,
                        (parent_generation_id, generation_id),
                    )
            row = connection.execute(
                "SELECT * FROM generations WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
            assert row is not None
            return self._generation_from_row(row)

    def _carry_published_manifest(
        self,
        connection: sqlite3.Connection,
        generation_id: str,
        signature: RunSignature,
    ) -> str | None:
        candidates = connection.execute(
            """
            SELECT * FROM generations
            WHERE generation_id != ?
              AND source_type = ?
              AND collection_identity = ?
              AND terminal_state = ?
            ORDER BY updated_at DESC
            """,
            (
                generation_id,
                signature.source_type.value,
                signature.collection_identity,
                RunTerminalState.SUCCEEDED.value,
            ),
        ).fetchall()
        source_id: str | None = None
        for candidate in candidates:
            published = self._generation_from_row(candidate)
            if (
                published.signature.content_compatibility_fingerprint
                == signature.content_compatibility_fingerprint
            ):
                source_id = published.generation_id
                break
        if source_id is None:
            return None
        connection.execute(
            """
            INSERT INTO file_states (
                generation_id, rel_path, state, content_kind, content_hash,
                admission_reason, error_kind, detail, evidence_generation_id
            )
            SELECT ?, rel_path, state, content_kind, content_hash,
                   admission_reason, error_kind, detail,
                   evidence_generation_id
            FROM file_states WHERE generation_id = ?
            """,
            (generation_id, source_id),
        )
        return source_id

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

    def latest_generation(
        self,
        source_type: ContentKind,
        *,
        collection_identity: str | None = None,
    ) -> RunGeneration | None:
        """Return the latest typed generation without loading its file rows."""
        parameters: tuple[object, ...] = (source_type.value,)
        collection_clause = ""
        if collection_identity is not None:
            collection_clause = " AND collection_identity = ?"
            parameters = (*parameters, collection_identity)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM generations
                WHERE source_type = ?{collection_clause}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                parameters,
            ).fetchone()
        return self._generation_from_row(row) if row is not None else None

    def latest_file_state(
        self,
        source_type: ContentKind,
        *,
        collection_identity: str,
        rel_path: str,
    ) -> FileState | None:
        """Return the newest indexed ownership state across generations.

        A newer incomplete clean generation carries no prior manifest. Looking
        only at that generation would therefore hide points still certified by
        an older generation and still present in storage. Rejections and
        failures do not certify stored ownership and cannot mask that evidence.
        """
        _validate_rel_path(rel_path)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT states.* FROM file_states AS states
                JOIN generations AS generations
                  ON generations.generation_id = states.generation_id
                WHERE generations.source_type = ?
                  AND generations.collection_identity = ?
                  AND states.rel_path = ?
                  AND states.state = ?
                  AND states.content_kind = ?
                ORDER BY generations.updated_at DESC,
                         generations.created_at DESC
                LIMIT 1
                """,
                (
                    source_type.value,
                    collection_identity,
                    rel_path,
                    FileStateKind.INDEXED.value,
                    source_type.value,
                ),
            ).fetchone()
        return _file_state_from_row(row) if row is not None else None

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
            return 0
        indexed = connection.execute(
            """
            SELECT 1 FROM file_states
            WHERE generation_id = ? AND rel_path = ? AND state = ?
              AND evidence_generation_id = generation_id
            """,
            (generation_id, unit.rel_path, FileStateKind.INDEXED.value),
        ).fetchone()
        if indexed is not None and unit.kind is CommitUnitKind.UPSERT:
            raise RunLedgerStateError(
                "cannot add upsert commit units after a path is indexed"
            )
        sibling = connection.execute(
            """
            SELECT source_digest, MAX(segment_ordinal) AS last_ordinal,
                   MAX(is_file_end) AS has_file_end, COUNT(*) AS unit_count
            FROM commit_units
            WHERE generation_id = ? AND rel_path = ? AND unit_kind = ?
            """,
            (generation_id, unit.rel_path, unit.kind.value),
        ).fetchone()
        assert sibling is not None
        sibling_count = int(sibling["unit_count"])
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
        for point_id in unit.point_ids:
            owner = connection.execute(
                """
                SELECT unit_id FROM commit_point_ids
                WHERE generation_id = ? AND point_id = ?
                """,
                (generation_id, point_id),
            ).fetchone()
            if owner is not None:
                raise RunLedgerStateError(
                    f"point identity {point_id!r} belongs to another commit unit"
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

    def committed_unit_count(self, generation_id: str) -> int:
        """Return the committed-unit count without materializing ledger rows."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS unit_count FROM commit_units
                WHERE generation_id = ?
                """,
                (generation_id,),
            ).fetchone()
        assert row is not None
        return int(row["unit_count"])

    def file_complete(self, generation_id: str, rel_path: str) -> bool:
        """Return whether every segment (or the deletion unit) is committed."""
        _validate_rel_path(rel_path)
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
        rows = connection.execute(
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
        ).fetchall()
        if not rows:
            return False, None
        by_kind: dict[str, sqlite3.Row] = {}
        for row in rows:
            kind = str(row["unit_kind"])
            if kind in by_kind:
                return False, None
            by_kind[kind] = row
            count = int(row["unit_count"])
            expected_sum = count * (count - 1) // 2
            if (
                count <= 0
                or int(row["first_ordinal"]) != 0
                or int(row["last_ordinal"]) != count - 1
                or int(row["ordinal_sum"]) != expected_sum
                or int(row["end_count"]) != 1
                or int(row["end_ordinal"]) != count - 1
            ):
                return False, None
        upserts = by_kind.get(CommitUnitKind.UPSERT.value)
        digest = str(upserts["source_digest"]) if upserts else None
        return True, digest

    def iter_units(
        self,
        generation_id: str,
        *,
        batch_size: int = _FETCH_BATCH,
    ) -> Iterator[CommitUnit]:
        """Yield committed units using bounded row-wise iteration."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        last_key: tuple[str, str, int, str] | None = None
        while True:
            with self._connect() as connection:
                if last_key is None:
                    rows = connection.execute(
                        """
                        SELECT * FROM commit_units
                        WHERE generation_id = ?
                        ORDER BY rel_path, unit_kind, segment_ordinal, unit_id
                        LIMIT ?
                        """,
                        (generation_id, batch_size),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT * FROM commit_units
                        WHERE generation_id = ?
                          AND (rel_path, unit_kind, segment_ordinal, unit_id)
                              > (?, ?, ?, ?)
                        ORDER BY rel_path, unit_kind, segment_ordinal, unit_id
                        LIMIT ?
                        """,
                        (generation_id, *last_key, batch_size),
                    ).fetchall()
            if not rows:
                return
            for row in rows:
                yield _commit_unit_from_row(row)
            last = rows[-1]
            last_key = (
                str(last["rel_path"]),
                str(last["unit_kind"]),
                int(last["segment_ordinal"]),
                str(last["unit_id"]),
            )

    def iter_point_ids(
        self,
        generation_id: str,
        *,
        batch_size: int = _FETCH_BATCH,
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
                rows = connection.execute(
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
                ).fetchall()
            if not rows:
                return
            for row in rows:
                yield str(row["point_id"])
            last = rows[-1]
            last_key = (
                str(last["rel_path"]),
                str(last["unit_kind"]),
                int(last["segment_ordinal"]),
                int(last["point_ordinal"]),
                str(last["point_id"]),
            )

    def iter_retained_point_ids(
        self,
        generation_id: str,
        *,
        rel_path: str | None = None,
        batch_size: int = _FETCH_BATCH,
    ) -> Iterator[str]:
        """Yield exact point identities retained by the generation manifest.

        Carried paths read their original evidence generation while replaced paths
        read the current generation. Deletion units are deliberately excluded.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if rel_path is not None:
            _validate_rel_path(rel_path)
        last_key: tuple[str, int, int, str] | None = None
        while True:
            condition = ""
            parameters: tuple[object, ...] = (
                CommitUnitKind.UPSERT.value,
                generation_id,
                FileStateKind.INDEXED.value,
            )
            path_condition = ""
            if rel_path is not None:
                path_condition = " AND states.rel_path = ?"
                parameters = (*parameters, rel_path)
            if last_key is not None:
                condition = """
                  AND (states.rel_path, units.segment_ordinal,
                       points.point_ordinal, points.point_id) > (?, ?, ?, ?)
                """
                parameters = (*parameters, *last_key)
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT points.point_id, points.point_ordinal,
                           states.rel_path, units.segment_ordinal
                    FROM file_states AS states
                    JOIN commit_units AS units
                      ON units.generation_id = states.evidence_generation_id
                     AND units.rel_path = states.rel_path
                     AND units.unit_kind = ?
                     AND units.source_digest = states.content_hash
                    JOIN commit_point_ids AS points
                      ON points.generation_id = units.generation_id
                     AND points.unit_id = units.unit_id
                    WHERE states.generation_id = ?
                      AND states.state = ?
                    {path_condition}
                    {condition}
                    ORDER BY states.rel_path, units.segment_ordinal,
                             points.point_ordinal, points.point_id
                    LIMIT ?
                    """,
                    (*parameters, batch_size),
                ).fetchall()
            if not rows:
                return
            for row in rows:
                yield str(row["point_id"])
            last = rows[-1]
            last_key = (
                str(last["rel_path"]),
                int(last["segment_ordinal"]),
                int(last["point_ordinal"]),
                str(last["point_id"]),
            )

    def record_file_state(self, generation_id: str, state: FileState) -> None:
        """Upsert the latest explicit per-file convergence outcome."""
        with self._transaction() as connection:
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
        _validate_rel_path(rel_path)
        with self._transaction() as connection:
            generation = self._require_mutable_generation(connection, generation_id)
            if generation["finalization_phase"] != FinalizationPhase.INGESTING.value:
                raise RunLedgerStateError(
                    "cannot change file state after finalization begins"
                )
            evidence = connection.execute(
                """
                SELECT COUNT(*) AS unit_count, SUM(is_file_end) AS end_count
                FROM commit_units
                WHERE generation_id = ? AND rel_path = ? AND unit_kind = ?
                """,
                (generation_id, rel_path, CommitUnitKind.DELETE_PATH.value),
            ).fetchone()
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
        _validate_rel_path(rel_path)
        with self._transaction() as connection:
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
        batch_size: int = _FETCH_BATCH,
    ) -> Iterator[FileState]:
        """Yield explicit outcomes without materializing generation metadata."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        last_path: str | None = None
        while True:
            with self._connect() as connection:
                if last_path is None:
                    rows = connection.execute(
                        """
                        SELECT * FROM file_states
                        WHERE generation_id = ?
                        ORDER BY rel_path LIMIT ?
                        """,
                        (generation_id, batch_size),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT * FROM file_states
                        WHERE generation_id = ? AND rel_path > ?
                        ORDER BY rel_path LIMIT ?
                        """,
                        (generation_id, last_path, batch_size),
                    ).fetchall()
            if not rows:
                return
            for row in rows:
                state = _file_state_from_row(row)
                if not converged_only or state.converged:
                    yield state
            last_path = str(rows[-1]["rel_path"])

    def file_states_for_paths(
        self,
        generation_id: str,
        rel_paths: tuple[str, ...],
    ) -> dict[str, FileState]:
        """Return one bounded indexed file-state page keyed by relative path."""
        if len(rel_paths) > _FETCH_BATCH:
            raise ValueError(f"file-state lookup accepts at most {_FETCH_BATCH} paths")
        if not rel_paths:
            return {}
        unique_paths = tuple(dict.fromkeys(rel_paths))
        placeholders = ", ".join("?" for _path in unique_paths)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM file_states
                WHERE generation_id = ? AND rel_path IN ({placeholders})
                """,
                (generation_id, *unique_paths),
            ).fetchall()
        return {
            state.rel_path: state
            for state in (_file_state_from_row(row) for row in rows)
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
        for start in range(0, len(unique_paths), _FETCH_BATCH):
            page = unique_paths[start : start + _FETCH_BATCH]
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
        if len(point_ids) > _FETCH_BATCH:
            raise ValueError(
                f"retained-point lookup accepts at most {_FETCH_BATCH} IDs"
            )
        if not point_ids:
            return frozenset()
        unique_ids = tuple(dict.fromkeys(point_ids))
        placeholders = ", ".join("?" for _point_id in unique_ids)
        with self._connect() as connection:
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
            rows = connection.execute(
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
            ).fetchall()
        return frozenset(str(row["point_id"]) for row in rows)

    def advance_finalization(
        self,
        generation_id: str,
        phase: FinalizationPhase,
    ) -> RunGeneration:
        """Advance exactly one confirmed external finalization boundary."""
        if not isinstance(phase, FinalizationPhase):
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
            current_index = _FINALIZATION_ORDER.index(current)
            if current_index + 1 >= len(_FINALIZATION_ORDER):
                raise RunLedgerStateError("generation finalization is already complete")
            if phase is not _FINALIZATION_ORDER[current_index + 1]:
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
                WHERE generation_id != ?
                  AND source_type = ?
                  AND collection_identity = ?
                  AND terminal_state IN (?, ?)
                """,
                (
                    keep_generation_id,
                    keep["source_type"],
                    keep["collection_identity"],
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
                    collection_identity TEXT NOT NULL,
                    signature_fingerprint TEXT NOT NULL,
                    signature_json TEXT NOT NULL,
                    finalization_phase TEXT NOT NULL,
                    terminal_state TEXT NOT NULL,
                    destructive_intent INTEGER NOT NULL
                        CHECK(destructive_intent IN (0, 1)),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    terminal_detail TEXT,
                    parent_generation_id TEXT
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

                CREATE TABLE IF NOT EXISTS commit_point_ids (
                    generation_id TEXT NOT NULL,
                    unit_id TEXT NOT NULL,
                    point_ordinal INTEGER NOT NULL,
                    point_id TEXT NOT NULL,
                    PRIMARY KEY(generation_id, unit_id, point_ordinal),
                    UNIQUE(generation_id, point_id),
                    FOREIGN KEY(generation_id, unit_id)
                        REFERENCES commit_units(generation_id, unit_id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS commit_point_ids_point
                    ON commit_point_ids(point_id);

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
                    evidence_generation_id TEXT NOT NULL,
                    PRIMARY KEY(generation_id, rel_path)
                );
                CREATE INDEX IF NOT EXISTS file_states_state
                    ON file_states(generation_id, state, rel_path);
                """
            )
            connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            connection.commit()
            return
        # Additive index for ledgers created before it existed. Without it the
        # bounded retained-point lookup degrades to a full scan of every point
        # in the ledger, so it must reach existing files too - and an index is
        # a pure read-path addition, so it needs no schema-version bump and
        # cannot invalidate a ledger that is otherwise current.
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS commit_point_ids_point
                ON commit_point_ids(point_id)
            """
        )
        connection.commit()

    def _verify_integrity(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("PRAGMA quick_check").fetchall()
        if [row[0] for row in rows] != ["ok"]:
            raise RunLedgerCorruptionError("run ledger failed SQLite quick_check")

    def _verify_schema(self, connection: sqlite3.Connection) -> None:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing_tables = set(_REQUIRED_SCHEMA) - tables
        if missing_tables:
            raise RunLedgerCompatibilityError(
                "run ledger schema is incomplete; missing tables: "
                + ", ".join(sorted(missing_tables))
            )
        for table, required_columns in _REQUIRED_SCHEMA.items():
            columns = {
                str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
            }
            missing_columns = required_columns - columns
            if missing_columns:
                raise RunLedgerCompatibilityError(
                    f"run ledger table {table!r} is missing columns: "
                    + ", ".join(sorted(missing_columns))
                )

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
        try:
            signature_payload: dict[str, Any] = json.loads(row["signature_json"])
            signature_payload["source_type"] = ContentKind(
                signature_payload["source_type"]
            )
            signature_payload["operation"] = RunOperation(
                signature_payload["operation"]
            )
            signature = RunSignature(**signature_payload)
            finalization_phase = FinalizationPhase(row["finalization_phase"])
            terminal_state = RunTerminalState(row["terminal_state"])
            destructive_intent = bool(row["destructive_intent"])
            created_at = float(row["created_at"])
            updated_at = float(row["updated_at"])
            terminal_detail = row["terminal_detail"]
            parent_generation_id = row["parent_generation_id"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RunLedgerCorruptionError(
                "stored generation row is malformed"
            ) from exc
        if signature.fingerprint != row["signature_fingerprint"]:
            raise RunLedgerCorruptionError(
                "stored generation signature does not match its fingerprint"
            )
        return RunGeneration(
            generation_id=row["generation_id"],
            signature=signature,
            finalization_phase=finalization_phase,
            terminal_state=terminal_state,
            destructive_intent=destructive_intent,
            created_at=created_at,
            updated_at=updated_at,
            terminal_detail=terminal_detail,
            parent_generation_id=parent_generation_id,
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


def _commit_unit_from_row(row: Mapping[str, Any]) -> CommitUnit:
    try:
        point_ids = json.loads(row["point_ids_json"])
        if not isinstance(point_ids, list):
            raise TypeError("point_ids_json must contain a list")
        return CommitUnit(
            rel_path=row["rel_path"],
            kind=CommitUnitKind(row["unit_kind"]),
            source_digest=row["source_digest"],
            segment_ordinal=row["segment_ordinal"],
            is_file_end=bool(row["is_file_end"]),
            point_ids=tuple(point_ids),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RunLedgerCorruptionError("stored commit unit is malformed") from exc
