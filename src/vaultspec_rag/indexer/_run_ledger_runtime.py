"""Run-ledger lifecycle, SQLite connection, and schema-runtime authority."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._content_policy import ContentKind
from ._file_state import FileState, FileStateKind, validate_rel_path
from ._run_ledger_commits import RunLedgerCommitMethods
from ._run_ledger_files import RunLedgerFileMethods, file_state_from_row
from ._run_ledger_finalization import RunLedgerFinalizationMethods
from ._run_ledger_models import (
    MAX_RESUME_FAILURES,
    REQUIRED_SCHEMA,
    RESUMABLE_STATES,
    SCHEMA_VERSION,
    FinalizationPhase,
    RunGeneration,
    RunLedgerCompatibilityError,
    RunLedgerCorruptionError,
    RunLedgerStateError,
    RunOperation,
    RunSignature,
    RunTerminalState,
)

if TYPE_CHECKING:
    from collections.abc import Generator

__all__ = ["RunLedger"]


class RunLedger(
    RunLedgerCommitMethods,
    RunLedgerFileMethods,
    RunLedgerFinalizationMethods,
):
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
                    *(state.value for state in RESUMABLE_STATES),
                ),
            ).fetchone()
            if (
                active is not None
                and active["signature_fingerprint"] == signature.fingerprint
                and int(active["consecutive_failures"]) >= MAX_RESUME_FAILURES
            ):
                # Retirement, not repair. A generation that has failed this
                # many times in a row is failing for a reason resuming will
                # not change, and every further attempt inherits its state and
                # fails the same way. Invalidating rather than deleting keeps
                # its evidence readable until the next success compacts it,
                # and moves it out of the resumable set so the next attempt
                # starts clean instead of inheriting the fault.
                connection.execute(
                    """
                    UPDATE generations
                    SET terminal_state = ?, terminal_detail = ?, updated_at = ?
                    WHERE generation_id = ?
                    """,
                    (
                        RunTerminalState.INVALIDATED.value,
                        "generation retired after "
                        f"{int(active['consecutive_failures'])} consecutive "
                        "failed attempts",
                        now,
                        active["generation_id"],
                    ),
                )
                active = None
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
                != signature.content_compatibility_fingerprint
            ):
                continue
            # A manifest whose cited evidence generation no longer exists
            # cannot seed an incremental diff: every carried point would read
            # as unretained and the publication purge would delete the whole
            # collection. Refusing it leaves the caller no parent, which
            # forces the full failure-safe reconciliation path instead.
            dangling = connection.execute(
                """
                SELECT 1
                FROM file_states AS states
                LEFT JOIN generations AS evidence
                  ON evidence.generation_id = states.evidence_generation_id
                WHERE states.generation_id = ?
                  AND evidence.generation_id IS NULL
                LIMIT 1
                """,
                (published.generation_id,),
            ).fetchone()
            if dangling is not None:
                continue
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
        validate_rel_path(rel_path)
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
        return file_state_from_row(row) if row is not None else None

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection]:
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
        if version not in (0, SCHEMA_VERSION):
            raise RunLedgerCompatibilityError(
                "run ledger schema "
                f"{version} is not supported; expected {SCHEMA_VERSION}"
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
                    parent_generation_id TEXT,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0
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
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
            return
        # Additive migrations for ledgers created before these existed. Both
        # must reach existing files - including the ones these changes repair -
        # and neither alters stored data or query results, so they need no
        # schema-version bump. A bump would reach those ledgers only by
        # rejecting them, since the compatibility check admits one exact
        # version, forcing every current ledger to rebuild from zero.
        #
        # Without the index the bounded retained-point lookup degrades to a
        # full scan of every point in the ledger.
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS commit_point_ids_point
                ON commit_point_ids(point_id)
            """
        )
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(generations)")
        }
        if "consecutive_failures" not in columns:
            connection.execute(
                """
                ALTER TABLE generations
                ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0
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
        missing_tables = set(REQUIRED_SCHEMA) - tables
        if missing_tables:
            raise RunLedgerCompatibilityError(
                "run ledger schema is incomplete; missing tables: "
                + ", ".join(sorted(missing_tables))
            )
        for table, required_columns in REQUIRED_SCHEMA.items():
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
