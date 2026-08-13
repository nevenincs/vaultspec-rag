"""Run-ledger lifecycle, SQLite connection, and schema-runtime authority."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from ._content_policy import ContentKind
from ._file_state import FileState, FileStateKind, validate_rel_path
from ._run_ledger_commits import RunLedgerCommitMethods
from ._run_ledger_files import (
    FileStateRow,
    RunLedgerFileMethods,
    file_state_from_row,
)
from ._run_ledger_finalization import RunLedgerFinalizationMethods
from ._run_ledger_models import (
    MAX_RESUME_FAILURES,
    REQUIRED_SCHEMA,
    RESUMABLE_STATES,
    SCHEMA_VERSION,
    FinalizationPhase,
    GenerationRow,
    RunGeneration,
    RunLedgerCompatibilityError,
    RunLedgerCorruptionError,
    RunLedgerStateError,
    RunOperation,
    RunSignature,
    RunTerminalState,
    column_int,
    column_text,
    fetch_all,
    fetch_one,
    ledger_connection,
    ledger_transaction,
    raise_if_lock_contention,
)

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
            with ledger_connection(self.path) as connection:
                self._initialize(connection)
                self._verify_schema(connection)
        except sqlite3.OperationalError as exc:
            # A held lock is not damage. It reaches here because opening
            # converts the journal mode and schema-migrates, both of which a
            # peer's transaction can block. Reporting that as corrupt durable
            # state would be a lie the caller cannot recover from, where the
            # truth is a condition that clears on its own.
            raise_if_lock_contention(exc, path=self.path)
            raise RunLedgerCorruptionError(
                f"cannot open run ledger {self.path}: {exc}"
            ) from exc
        except sqlite3.DatabaseError as exc:
            raise RunLedgerCorruptionError(
                f"cannot open run ledger {self.path}: {exc}"
            ) from exc

    def verify_integrity(self) -> None:
        """Scan the whole ledger and raise when SQLite reports damage.

        Deliberately not on the open path. This reads every page in the file,
        so its cost tracks total ledger size across every content kind sharing
        the root - and it holds a read lock for that whole time. Run per open,
        it turned each new run into a scan of every other source's history, and
        grew worst exactly where resilience matters most.

        Schema and page-level damage still surfaces without it: opening the
        ledger reads ``sqlite_master`` and the schema contract, and SQLite
        raises on a malformed image as soon as a query touches it. This is the
        deeper check, for recovery and maintenance to call deliberately.
        """
        try:
            with ledger_connection(self.path) as connection:
                rows: list[sqlite3.Row] = fetch_all(connection, "PRAGMA quick_check")
        except sqlite3.OperationalError as exc:
            # This runs on the resume path, on a generation that already holds
            # storage-confirmed work. Calling a held lock corruption here would
            # discard exactly the work this verification exists to protect.
            raise_if_lock_contention(exc, path=self.path)
            raise RunLedgerCorruptionError(
                f"cannot verify run ledger {self.path}: {exc}"
            ) from exc
        except sqlite3.DatabaseError as exc:
            raise RunLedgerCorruptionError(
                f"cannot verify run ledger {self.path}: {exc}"
            ) from exc
        if [column_text(row, 0) for row in rows] != ["ok"]:
            raise RunLedgerCorruptionError("run ledger failed SQLite quick_check")

    def start_generation(self, signature: RunSignature) -> RunGeneration:
        """Resume one compatible active generation or invalidate and replace it."""
        now = time.time()
        with ledger_transaction(self.path) as connection:
            active: GenerationRow | None = fetch_one(
                connection,
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
            )
            if (
                active is not None
                and active["signature_fingerprint"] == signature.fingerprint
                and active["consecutive_failures"] >= MAX_RESUME_FAILURES
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
                        f"{active['consecutive_failures']} consecutive "
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
                    active = fetch_one(
                        connection,
                        "SELECT * FROM generations WHERE generation_id = ?",
                        (active["generation_id"],),
                    )
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
            row: GenerationRow | None = fetch_one(
                connection,
                "SELECT * FROM generations WHERE generation_id = ?",
                (generation_id,),
            )
            assert row is not None
            return self._generation_from_row(row)

    def _carry_published_manifest(
        self,
        connection: sqlite3.Connection,
        generation_id: str,
        signature: RunSignature,
    ) -> str | None:
        candidates: list[GenerationRow] = fetch_all(
            connection,
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
        )
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
            #
            # Stop rather than fall through to an older candidate. The newest
            # compatible manifest is the one storage reflects; anything older
            # describes points a later publication already replaced or purged,
            # so carrying it would claim dead point ids and skip re-encoding
            # the files it names - a worse diff than the one just refused.
            dangling: object | None = fetch_one(
                connection,
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
            )
            if dangling is not None:
                return None
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
        with ledger_connection(self.path) as connection:
            row: GenerationRow | None = fetch_one(
                connection,
                "SELECT * FROM generations WHERE generation_id = ?",
                (generation_id,),
            )
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
        with ledger_connection(self.path) as connection:
            row: GenerationRow | None = fetch_one(
                connection,
                f"""
                SELECT * FROM generations
                WHERE source_type = ?{collection_clause}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                parameters,
            )
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
        with ledger_connection(self.path) as connection:
            row: FileStateRow | None = fetch_one(
                connection,
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
            )
        return file_state_from_row(row) if row is not None else None

    def _initialize(self, connection: sqlite3.Connection) -> None:
        version_row: sqlite3.Row | None = fetch_one(connection, "PRAGMA user_version")
        assert version_row is not None
        version = column_int(version_row, 0)
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
        info_rows: list[sqlite3.Row] = fetch_all(
            connection, "PRAGMA table_info(generations)"
        )
        columns = {column_text(row, "name") for row in info_rows}
        if "consecutive_failures" not in columns:
            connection.execute(
                """
                ALTER TABLE generations
                ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0
                """
            )
        connection.commit()

    def _verify_schema(self, connection: sqlite3.Connection) -> None:
        table_rows: list[sqlite3.Row] = fetch_all(
            connection, "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
        tables = {column_text(row, "name") for row in table_rows}
        missing_tables = set(REQUIRED_SCHEMA) - tables
        if missing_tables:
            raise RunLedgerCompatibilityError(
                "run ledger schema is incomplete; missing tables: "
                + ", ".join(sorted(missing_tables))
            )
        for table, required_columns in REQUIRED_SCHEMA.items():
            info_rows: list[sqlite3.Row] = fetch_all(
                connection, f"PRAGMA table_info({table})"
            )
            columns = {column_text(row, "name") for row in info_rows}
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
    ) -> GenerationRow:
        row: GenerationRow | None = fetch_one(
            connection,
            "SELECT * FROM generations WHERE generation_id = ?",
            (generation_id,),
        )
        if row is None:
            raise KeyError(generation_id)
        if RunTerminalState(row["terminal_state"]) is not RunTerminalState.RUNNING:
            raise RunLedgerStateError("terminal generations are immutable")
        return row

    @staticmethod
    def _generation_from_row(row: GenerationRow) -> RunGeneration:
        try:
            signature_payload: dict[str, object] = json.loads(row["signature_json"])
            signature = _signature_from_payload(signature_payload)
            finalization_phase = FinalizationPhase(row["finalization_phase"])
            terminal_state = RunTerminalState(row["terminal_state"])
            destructive_intent = row["destructive_intent"] != 0
            created_at = row["created_at"]
            updated_at = row["updated_at"]
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


def _typed_field[T](payload: dict[str, object], key: str, expected_type: type[T]) -> T:
    """Return one JSON-decoded signature field, narrowed from the parser's Any.

    ``signature_json`` is genuinely dynamic - decoded JSON, not a value this
    module controls the shape of - so each field is isinstance-checked here
    rather than trusted through ``RunSignature(**payload)``, which would pass
    every field through as ``Any`` and could construct a signature from a
    field of the wrong type as long as it happened to satisfy the
    constructor's runtime checks by luck rather than by type.
    """
    value = payload.get(key)
    if not isinstance(value, expected_type):
        raise TypeError(f"signature field {key!r} must be a {expected_type.__name__}")
    return value


def _signature_from_payload(payload: dict[str, object]) -> RunSignature:
    """Construct one :class:`RunSignature` from its decoded JSON, field by field."""
    return RunSignature(
        root_identity=_typed_field(payload, "root_identity", str),
        collection_identity=_typed_field(payload, "collection_identity", str),
        source_type=ContentKind(_typed_field(payload, "source_type", str)),
        operation=RunOperation(_typed_field(payload, "operation", str)),
        clean=_typed_field(payload, "clean", bool),
        model_identity=_typed_field(payload, "model_identity", str),
        dense_dimensions=_typed_field(payload, "dense_dimensions", int),
        embedding_schema=_typed_field(payload, "embedding_schema", int),
        payload_schema=_typed_field(payload, "payload_schema", int),
        content_epoch=_typed_field(payload, "content_epoch", str),
        membership_epoch=_typed_field(payload, "membership_epoch", str),
        preprocessing_identity=_typed_field(payload, "preprocessing_identity", str),
        configuration_fingerprint=_typed_field(
            payload, "configuration_fingerprint", str
        ),
        policy_fingerprint=_typed_field(payload, "policy_fingerprint", str),
    )
