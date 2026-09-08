"""Run-ledger lifecycle, SQLite connection, and schema-runtime authority."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from functools import cache
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
    REQUIRED_INDEX_PREDICATES,
    REQUIRED_INDEXES,
    REQUIRED_SCHEMA,
    RESUMABLE_STATES,
    SCHEMA_VERSION,
    FinalizationPhase,
    GenerationRow,
    RunGeneration,
    RunLedgerCorruptionError,
    RunLedgerRebuildRequiredError,
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
    open_ledger_connection,
    raise_if_lock_contention,
)
from ._run_ledger_publication import RunLedgerPublicationMethods

__all__ = ["RunLedger"]


def _normalize_schema_definition(definition: str) -> str:
    """Collapse non-semantic whitespace in one SQLite schema definition."""
    return " ".join(definition.split()).removesuffix(";")


def _execute_schema_statements(
    connection: sqlite3.Connection,
    script: str,
) -> None:
    """Execute a trusted DDL script without escaping its caller's transaction."""
    statement = ""
    for line in script.splitlines():
        statement += f"{line}\n"
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise AssertionError("schema DDL contains an incomplete statement")


class RunLedger(
    RunLedgerPublicationMethods,
    RunLedgerCommitMethods,
    RunLedgerFileMethods,
    RunLedgerFinalizationMethods,
):
    """Transactional per-root indexing generation ledger."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with ledger_connection(
                self.path,
                read_only_preflight=self._require_current_or_empty_schema,
                before_journal_mode=self._initialize,
            ) as connection:
                self._verify_schema(connection)
        except sqlite3.OperationalError as exc:
            # A held lock is not damage. It reaches here because opening
            # converts the journal mode and creates a fresh schema, both of which a
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

    def _require_current_or_empty_schema(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        """Refuse non-current durable state before journal-mode mutation."""
        version_row: sqlite3.Row | None = fetch_one(connection, "PRAGMA user_version")
        assert version_row is not None
        version = column_int(version_row, 0)
        if version == 0:
            object_row: sqlite3.Row | None = fetch_one(
                connection,
                "SELECT 1 FROM sqlite_master LIMIT 1",
            )
            if object_row is None:
                active_wal = any(
                    Path(f"{self.path}{suffix}").exists() for suffix in ("-wal", "-shm")
                )
                if active_wal:
                    raise RunLedgerRebuildRequiredError(
                        "run ledger has active journal state but no current base "
                        "schema; an explicit rebuild is required"
                    )
                return
            raise RunLedgerRebuildRequiredError(
                "run ledger schema 0 belongs to a nonempty pre-proof database; "
                "an explicit rebuild is required"
            )
        if version != SCHEMA_VERSION:
            raise RunLedgerRebuildRequiredError(
                "run ledger schema "
                f"{version} is not supported; expected {SCHEMA_VERSION}; "
                "an explicit rebuild is required"
            )
        self._verify_schema(connection)

    def _initialize(self, connection: sqlite3.Connection) -> None:
        version_row: sqlite3.Row | None = fetch_one(connection, "PRAGMA user_version")
        assert version_row is not None
        version = column_int(version_row, 0)
        if version == SCHEMA_VERSION:
            self._verify_schema(connection)
            return
        object_row: sqlite3.Row | None = fetch_one(
            connection,
            "SELECT 1 FROM sqlite_master LIMIT 1",
        )
        if version != 0 or object_row is not None:
            raise RunLedgerRebuildRequiredError(
                "run ledger changed before current-schema creation; "
                "an explicit rebuild is required"
            )
        connection.execute("BEGIN IMMEDIATE")
        try:
            version_row = fetch_one(connection, "PRAGMA user_version")
            assert version_row is not None
            version = column_int(version_row, 0)
            object_row = fetch_one(
                connection,
                "SELECT 1 FROM sqlite_master LIMIT 1",
            )
            if version == SCHEMA_VERSION:
                self._verify_schema(connection)
            elif version == 0 and object_row is None:
                self._create_base_tables(connection)
                self._create_publication_tables(connection)
                self._create_required_indexes(connection)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self._verify_schema(connection)
            else:
                raise RunLedgerRebuildRequiredError(
                    "run ledger changed before current-schema creation; "
                    "an explicit rebuild is required"
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    @staticmethod
    def _create_base_tables(connection: sqlite3.Connection) -> None:
        _execute_schema_statements(
            connection,
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
            """,
        )

    @staticmethod
    def _create_publication_tables(connection: sqlite3.Connection) -> None:
        _execute_schema_statements(
            connection,
            """
            CREATE TABLE IF NOT EXISTS publication_proofs (
                source_type TEXT NOT NULL
                    CHECK(source_type IN ('vault', 'code', 'document')),
                root_identity TEXT NOT NULL
                    CHECK(length(trim(root_identity)) > 0),
                backend_identity TEXT NOT NULL
                    CHECK(length(trim(backend_identity)) > 0),
                collection_identity TEXT NOT NULL
                    CHECK(length(trim(collection_identity)) > 0),
                storage_schema INTEGER NOT NULL CHECK(storage_schema > 0),
                payload_schema INTEGER NOT NULL CHECK(payload_schema > 0),
                embedding_schema_identity TEXT NOT NULL
                    CHECK(length(trim(embedding_schema_identity)) > 0),
                chunking_schema_identity TEXT NOT NULL
                    CHECK(length(trim(chunking_schema_identity)) > 0),
                membership_identity TEXT NOT NULL
                    CHECK(length(trim(membership_identity)) > 0),
                content_identity TEXT NOT NULL
                    CHECK(length(trim(content_identity)) > 0),
                policy_identity TEXT NOT NULL
                    CHECK(length(trim(policy_identity)) > 0),
                generation_id TEXT NOT NULL
                    REFERENCES generations(generation_id) ON DELETE RESTRICT,
                revision INTEGER NOT NULL CHECK(revision >= 0),
                reservation_sequence INTEGER NOT NULL
                    CHECK(reservation_sequence >= 0),
                indexed_identities INTEGER NOT NULL
                    CHECK(indexed_identities >= 0),
                retained_points INTEGER NOT NULL CHECK(retained_points >= 0),
                provenance TEXT NOT NULL
                    CHECK(provenance IN ('verified', 'delta_derived')),
                committed_at REAL NOT NULL CHECK(committed_at >= 0),
                verified_at REAL CHECK(verified_at IS NULL OR verified_at >= 0),
                PRIMARY KEY(
                    source_type, root_identity, backend_identity,
                    collection_identity
                ),
                CHECK(
                    (
                        provenance = 'verified'
                        AND verified_at IS NOT NULL
                        AND verified_at <= committed_at
                    ) OR (
                        provenance = 'delta_derived'
                        AND verified_at IS NULL
                    )
                )
            );

            CREATE TABLE IF NOT EXISTS publication_evidence (
                source_type TEXT NOT NULL,
                root_identity TEXT NOT NULL,
                backend_identity TEXT NOT NULL,
                collection_identity TEXT NOT NULL,
                rel_path TEXT NOT NULL CHECK(length(trim(rel_path)) > 0),
                content_identity TEXT NOT NULL
                    CHECK(length(trim(content_identity)) > 0),
                evidence_generation_id TEXT NOT NULL
                    REFERENCES generations(generation_id) ON DELETE RESTRICT,
                PRIMARY KEY(
                    source_type, root_identity, backend_identity,
                    collection_identity, rel_path
                ),
                FOREIGN KEY(
                    source_type, root_identity, backend_identity,
                    collection_identity
                ) REFERENCES publication_proofs(
                    source_type, root_identity, backend_identity,
                    collection_identity
                ) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS publication_points (
                source_type TEXT NOT NULL,
                root_identity TEXT NOT NULL,
                backend_identity TEXT NOT NULL,
                collection_identity TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                point_ordinal INTEGER NOT NULL CHECK(point_ordinal >= 0),
                point_id TEXT NOT NULL CHECK(length(trim(point_id)) > 0),
                PRIMARY KEY(
                    source_type, root_identity, backend_identity,
                    collection_identity, rel_path, point_ordinal
                ),
                UNIQUE(
                    source_type, root_identity, backend_identity,
                    collection_identity, point_id
                ),
                FOREIGN KEY(
                    source_type, root_identity, backend_identity,
                    collection_identity, rel_path
                ) REFERENCES publication_evidence(
                    source_type, root_identity, backend_identity,
                    collection_identity, rel_path
                ) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS publication_receipts (
                receipt_id TEXT NOT NULL PRIMARY KEY
                    CHECK(length(trim(receipt_id)) > 0),
                reservation_sequence INTEGER NOT NULL
                    CHECK(reservation_sequence > 0),
                source_type TEXT NOT NULL
                    CHECK(source_type IN ('vault', 'code', 'document')),
                root_identity TEXT NOT NULL
                    CHECK(length(trim(root_identity)) > 0),
                backend_identity TEXT NOT NULL
                    CHECK(length(trim(backend_identity)) > 0),
                collection_identity TEXT NOT NULL
                    CHECK(length(trim(collection_identity)) > 0),
                storage_schema INTEGER NOT NULL CHECK(storage_schema > 0),
                payload_schema INTEGER NOT NULL CHECK(payload_schema > 0),
                embedding_schema_identity TEXT NOT NULL
                    CHECK(length(trim(embedding_schema_identity)) > 0),
                chunking_schema_identity TEXT NOT NULL
                    CHECK(length(trim(chunking_schema_identity)) > 0),
                membership_identity TEXT NOT NULL
                    CHECK(length(trim(membership_identity)) > 0),
                content_identity TEXT NOT NULL
                    CHECK(length(trim(content_identity)) > 0),
                policy_identity TEXT NOT NULL
                    CHECK(length(trim(policy_identity)) > 0),
                generation_id TEXT NOT NULL
                    REFERENCES generations(generation_id) ON DELETE RESTRICT,
                parent_revision INTEGER NOT NULL CHECK(parent_revision >= 0),
                target_revision INTEGER NOT NULL
                    CHECK(target_revision = parent_revision + 1),
                state TEXT NOT NULL
                    CHECK(state IN (
                        'reserved', 'sealed', 'committed', 'rolled_back'
                    )),
                reserved_at REAL NOT NULL CHECK(reserved_at >= 0),
                sealed_at REAL CHECK(sealed_at IS NULL OR sealed_at >= reserved_at),
                committed_at REAL CHECK(
                    committed_at IS NULL OR (
                        sealed_at IS NOT NULL AND committed_at >= sealed_at
                    )
                ),
                rolled_back_at REAL CHECK(
                    rolled_back_at IS NULL OR
                    rolled_back_at >= COALESCE(sealed_at, reserved_at)
                ),
                UNIQUE(
                    source_type, root_identity, backend_identity,
                    collection_identity, reservation_sequence
                ),
                CHECK(
                    (
                        state = 'reserved'
                        AND sealed_at IS NULL
                        AND committed_at IS NULL
                        AND rolled_back_at IS NULL
                    ) OR (
                        state = 'sealed'
                        AND sealed_at IS NOT NULL
                        AND committed_at IS NULL
                        AND rolled_back_at IS NULL
                    ) OR (
                        state = 'committed'
                        AND sealed_at IS NOT NULL
                        AND committed_at IS NOT NULL
                        AND rolled_back_at IS NULL
                    ) OR (
                        state = 'rolled_back'
                        AND committed_at IS NULL
                        AND rolled_back_at IS NOT NULL
                    )
                )
            );

            CREATE TABLE IF NOT EXISTS publication_mutation_units (
                receipt_id TEXT NOT NULL
                    REFERENCES publication_receipts(receipt_id) ON DELETE CASCADE,
                mutation_ordinal INTEGER NOT NULL CHECK(mutation_ordinal >= 0),
                sealed_ordinal INTEGER
                    CHECK(sealed_ordinal IS NULL OR sealed_ordinal >= 0),
                unit_id TEXT NOT NULL CHECK(length(trim(unit_id)) > 0),
                rel_path TEXT NOT NULL CHECK(length(trim(rel_path)) > 0),
                unit_kind TEXT NOT NULL
                    CHECK(unit_kind IN ('upsert', 'delete_path', 'delete_stale')),
                source_digest TEXT,
                segment_ordinal INTEGER NOT NULL CHECK(segment_ordinal >= 0),
                is_file_end INTEGER NOT NULL CHECK(is_file_end IN (0, 1)),
                state TEXT NOT NULL
                    CHECK(state IN ('prepared', 'applied', 'confirmed')),
                prepared_at REAL NOT NULL CHECK(prepared_at >= 0),
                applied_at REAL CHECK(
                    applied_at IS NULL OR applied_at >= prepared_at
                ),
                confirmed_at REAL CHECK(
                    confirmed_at IS NULL AND state != 'confirmed' OR
                    applied_at IS NOT NULL AND confirmed_at >= applied_at
                ),
                PRIMARY KEY(receipt_id, mutation_ordinal),
                UNIQUE(receipt_id, unit_id),
                UNIQUE(receipt_id, rel_path, unit_kind, segment_ordinal),
                CHECK(
                    (
                        unit_kind = 'upsert'
                        AND source_digest IS NOT NULL
                        AND length(source_digest) = 128
                        AND source_digest NOT GLOB '*[^0-9a-f]*'
                    ) OR
                    (unit_kind != 'upsert' AND source_digest IS NULL)
                ),
                CHECK(
                    unit_kind = 'upsert' OR
                    (segment_ordinal = 0 AND is_file_end = 1)
                ),
                CHECK(
                    (state = 'prepared' AND applied_at IS NULL) OR
                    (
                        state = 'applied'
                        AND applied_at IS NOT NULL
                        AND confirmed_at IS NULL
                    ) OR (
                        state = 'confirmed'
                        AND applied_at IS NOT NULL
                        AND confirmed_at IS NOT NULL
                    )
                )
            );

            CREATE TABLE IF NOT EXISTS publication_mutation_points (
                receipt_id TEXT NOT NULL,
                mutation_ordinal INTEGER NOT NULL,
                point_ordinal INTEGER NOT NULL CHECK(point_ordinal >= 0),
                point_id TEXT NOT NULL CHECK(length(trim(point_id)) > 0),
                PRIMARY KEY(receipt_id, mutation_ordinal, point_ordinal),
                UNIQUE(receipt_id, mutation_ordinal, point_id),
                FOREIGN KEY(receipt_id, mutation_ordinal)
                    REFERENCES publication_mutation_units(
                        receipt_id, mutation_ordinal
                    ) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS publication_receipt_deltas (
                receipt_id TEXT NOT NULL
                    REFERENCES publication_receipts(receipt_id) ON DELETE CASCADE,
                delta_ordinal INTEGER NOT NULL CHECK(delta_ordinal >= 0),
                outcome TEXT NOT NULL CHECK(outcome IN (
                    'add', 'modify', 'delete', 'rename', 'empty', 'ignored',
                    'rejected', 'noop'
                )),
                rel_path TEXT NOT NULL CHECK(length(trim(rel_path)) > 0),
                target_rel_path TEXT CHECK(
                    target_rel_path IS NULL OR length(trim(target_rel_path)) > 0
                ),
                old_content_identity TEXT CHECK(
                    old_content_identity IS NULL OR
                    length(trim(old_content_identity)) > 0
                ),
                new_content_identity TEXT CHECK(
                    new_content_identity IS NULL OR
                    length(trim(new_content_identity)) > 0
                ),
                PRIMARY KEY(receipt_id, delta_ordinal),
                CHECK(
                    (
                        outcome = 'rename'
                        AND target_rel_path IS NOT NULL
                        AND target_rel_path != rel_path
                    ) OR (
                        outcome != 'rename' AND target_rel_path IS NULL
                    )
                ),
                CHECK(
                    (
                        outcome = 'add'
                        AND old_content_identity IS NULL
                        AND new_content_identity IS NOT NULL
                    ) OR (
                        outcome = 'modify'
                        AND old_content_identity IS NOT NULL
                        AND new_content_identity IS NOT NULL
                        AND old_content_identity != new_content_identity
                    ) OR (
                        outcome = 'rename'
                        AND old_content_identity IS NOT NULL
                        AND new_content_identity IS NOT NULL
                    ) OR (
                        outcome = 'delete'
                        AND old_content_identity IS NOT NULL
                        AND new_content_identity IS NULL
                    ) OR (
                        outcome IN ('empty', 'ignored', 'rejected')
                        AND new_content_identity IS NULL
                    ) OR (
                        outcome = 'noop'
                        AND old_content_identity IS NOT NULL
                        AND old_content_identity = new_content_identity
                    )
                )
            );

            CREATE TABLE IF NOT EXISTS publication_receipt_points (
                receipt_id TEXT NOT NULL,
                delta_ordinal INTEGER NOT NULL,
                evidence_side TEXT NOT NULL
                    CHECK(evidence_side IN ('old', 'new')),
                point_ordinal INTEGER NOT NULL CHECK(point_ordinal >= 0),
                point_id TEXT NOT NULL CHECK(length(trim(point_id)) > 0),
                PRIMARY KEY(
                    receipt_id, delta_ordinal, evidence_side, point_ordinal
                ),
                UNIQUE(receipt_id, delta_ordinal, evidence_side, point_id),
                FOREIGN KEY(receipt_id, delta_ordinal)
                    REFERENCES publication_receipt_deltas(
                        receipt_id, delta_ordinal
                    ) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS file_state_tombstones (
                generation_id TEXT NOT NULL
                    REFERENCES generations(generation_id) ON DELETE CASCADE,
                rel_path TEXT NOT NULL CHECK(length(trim(rel_path)) > 0),
                PRIMARY KEY(generation_id, rel_path)
            );

            """,
        )

    @staticmethod
    @cache
    def _expected_table_definitions() -> tuple[tuple[str, str], ...]:
        """Build the exact table contract from the current DDL authority.

        SQLite retains each table's complete definition in ``sqlite_master``.
        That definition includes nullability, primary and unique keys, CHECK
        expressions, foreign keys, and their actions. Building it once in an
        isolated in-memory database makes differently shaped ledgers fail closed
        while keeping the definition single-sourced.
        """
        connection = open_ledger_connection(Path(":memory:"))
        try:
            connection.row_factory = sqlite3.Row
            RunLedger._create_base_tables(connection)
            RunLedger._create_publication_tables(connection)
            definitions: list[tuple[str, str]] = []
            for table in REQUIRED_SCHEMA:
                row: sqlite3.Row | None = fetch_one(
                    connection,
                    "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                )
                assert row is not None
                definitions.append(
                    (table, _normalize_schema_definition(column_text(row, "sql")))
                )
            return tuple(definitions)
        finally:
            connection.close()

    @staticmethod
    @cache
    def _expected_index_definitions() -> tuple[tuple[str, str], ...]:
        """Build the exact named-index contract from the current DDL authority."""
        connection = open_ledger_connection(Path(":memory:"))
        try:
            connection.row_factory = sqlite3.Row
            RunLedger._create_base_tables(connection)
            RunLedger._create_publication_tables(connection)
            RunLedger._create_required_indexes(connection)
            definitions: list[tuple[str, str]] = []
            for index_name in REQUIRED_INDEXES:
                row: sqlite3.Row | None = fetch_one(
                    connection,
                    "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
                    (index_name,),
                )
                assert row is not None
                definitions.append(
                    (index_name, _normalize_schema_definition(column_text(row, "sql")))
                )
            return tuple(definitions)
        finally:
            connection.close()

    @staticmethod
    def _create_required_indexes(connection: sqlite3.Connection) -> None:
        _execute_schema_statements(
            connection,
            """
            CREATE INDEX IF NOT EXISTS generations_active
                ON generations(source_type, terminal_state, created_at DESC);
            CREATE INDEX IF NOT EXISTS commit_units_path
                ON commit_units(generation_id, rel_path, segment_ordinal);
            CREATE INDEX IF NOT EXISTS commit_point_ids_point
                ON commit_point_ids(point_id);
            CREATE INDEX IF NOT EXISTS file_states_state
                ON file_states(generation_id, state, rel_path);

            CREATE INDEX IF NOT EXISTS publication_proofs_generation
                ON publication_proofs(generation_id);
            CREATE INDEX IF NOT EXISTS publication_evidence_generation
                ON publication_evidence(evidence_generation_id);
            CREATE INDEX IF NOT EXISTS publication_points_point
                ON publication_points(point_id);
            CREATE INDEX IF NOT EXISTS publication_receipts_generation
                ON publication_receipts(generation_id, state);
            CREATE UNIQUE INDEX IF NOT EXISTS publication_receipts_open
                ON publication_receipts(
                    source_type, root_identity, backend_identity,
                    collection_identity
                ) WHERE state IN ('reserved', 'sealed');
            CREATE INDEX IF NOT EXISTS publication_mutation_units_state
                ON publication_mutation_units(
                    receipt_id, state, mutation_ordinal
                );
            CREATE UNIQUE INDEX IF NOT EXISTS publication_mutation_units_sealed
                ON publication_mutation_units(receipt_id, sealed_ordinal)
                WHERE sealed_ordinal IS NOT NULL;
            CREATE INDEX IF NOT EXISTS publication_mutation_points_point
                ON publication_mutation_points(point_id);
            CREATE UNIQUE INDEX IF NOT EXISTS publication_receipt_deltas_path
                ON publication_receipt_deltas(receipt_id, rel_path);
            CREATE INDEX IF NOT EXISTS publication_receipt_points_point
                ON publication_receipt_points(point_id);
            CREATE INDEX IF NOT EXISTS file_state_tombstones_path
                ON file_state_tombstones(rel_path, generation_id);
            """,
        )

    def _verify_schema(self, connection: sqlite3.Connection) -> None:
        self._verify_schema_objects(connection)
        self._verify_schema_tables(connection)
        for index_name, (
            table,
            expected_columns,
            expected_unique,
            expected_partial,
        ) in REQUIRED_INDEXES.items():
            index_rows: list[sqlite3.Row] = fetch_all(
                connection, f'PRAGMA index_list("{table}")'
            )
            index_row = next(
                (row for row in index_rows if column_text(row, "name") == index_name),
                None,
            )
            if index_row is None:
                raise RunLedgerRebuildRequiredError(
                    "run ledger schema is incomplete; missing index: "
                    f"{index_name}; an explicit rebuild is required"
                )
            info_rows: list[sqlite3.Row] = fetch_all(
                connection, f'PRAGMA index_info("{index_name}")'
            )
            columns = tuple(
                column_text(row, "name")
                for row in sorted(info_rows, key=lambda row: column_int(row, "seqno"))
            )
            unique = column_int(index_row, "unique") != 0
            partial = column_int(index_row, "partial") != 0
            if (
                columns != expected_columns
                or unique is not expected_unique
                or partial is not expected_partial
            ):
                raise RunLedgerRebuildRequiredError(
                    f"run ledger index {index_name!r} does not match its contract; "
                    "an explicit rebuild is required"
                )
            expected_predicate = REQUIRED_INDEX_PREDICATES.get(index_name)
            if expected_predicate is not None:
                predicate_definition_row: sqlite3.Row | None = fetch_one(
                    connection,
                    """
                    SELECT sql FROM sqlite_master
                    WHERE type = 'index' AND name = ?
                    """,
                    (index_name,),
                )
                if predicate_definition_row is None:
                    raise RunLedgerRebuildRequiredError(
                        "run ledger schema is incomplete; missing index: "
                        f"{index_name}; an explicit rebuild is required"
                    )
                definition = " ".join(
                    column_text(predicate_definition_row, "sql").lower().split()
                )
                _prefix, separator, predicate = definition.partition(" where ")
                actual_predicate = f"where {predicate}" if separator else ""
                if actual_predicate != expected_predicate:
                    raise RunLedgerRebuildRequiredError(
                        f"run ledger index {index_name!r} does not match its contract; "
                        "an explicit rebuild is required"
                    )
        index_rows = fetch_all(
            connection,
            """
            SELECT name FROM sqlite_master
            WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
            """,
        )
        indexes = {column_text(row, "name") for row in index_rows}
        unexpected_indexes = indexes - set(REQUIRED_INDEXES)
        if unexpected_indexes:
            raise RunLedgerRebuildRequiredError(
                "run ledger schema contains unexpected indexes: "
                + ", ".join(sorted(unexpected_indexes))
                + "; an explicit rebuild is required"
            )
        for index_name, expected_definition in self._expected_index_definitions():
            definition_row: sqlite3.Row | None = fetch_one(
                connection,
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
                (index_name,),
            )
            assert definition_row is not None
            actual_definition = _normalize_schema_definition(
                column_text(definition_row, "sql")
            )
            if actual_definition != expected_definition:
                raise RunLedgerRebuildRequiredError(
                    f"run ledger index {index_name!r} does not match its contract; "
                    "an explicit rebuild is required"
                )

    @staticmethod
    def _verify_schema_objects(connection: sqlite3.Connection) -> None:
        object_rows: list[sqlite3.Row] = fetch_all(
            connection,
            """
            SELECT type, name FROM sqlite_master
            WHERE type NOT IN ('table', 'index') AND name NOT LIKE 'sqlite_%'
            """,
        )
        unexpected_objects = sorted(
            f"{column_text(row, 'type')} {column_text(row, 'name')!r}"
            for row in object_rows
        )
        if unexpected_objects:
            raise RunLedgerRebuildRequiredError(
                "run ledger schema contains unexpected objects: "
                + ", ".join(unexpected_objects)
                + "; an explicit rebuild is required"
            )

    @staticmethod
    def _verify_schema_tables(connection: sqlite3.Connection) -> None:
        table_rows: list[sqlite3.Row] = fetch_all(
            connection,
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            """,
        )
        tables = {column_text(row, "name") for row in table_rows}
        missing_tables = set(REQUIRED_SCHEMA) - tables
        if missing_tables:
            raise RunLedgerRebuildRequiredError(
                "run ledger schema is incomplete; missing tables: "
                + ", ".join(sorted(missing_tables))
                + "; an explicit rebuild is required"
            )
        unexpected_tables = tables - set(REQUIRED_SCHEMA)
        if unexpected_tables:
            raise RunLedgerRebuildRequiredError(
                "run ledger schema contains unexpected tables: "
                + ", ".join(sorted(unexpected_tables))
                + "; an explicit rebuild is required"
            )
        for table, required_columns in REQUIRED_SCHEMA.items():
            info_rows: list[sqlite3.Row] = fetch_all(
                connection, f"PRAGMA table_info({table})"
            )
            columns = {column_text(row, "name") for row in info_rows}
            if frozenset(columns) != required_columns:
                raise RunLedgerRebuildRequiredError(
                    f"run ledger table {table!r} does not match its column contract; "
                    "an explicit rebuild is required"
                )
        for (
            table,
            expected_definition,
        ) in RunLedger._expected_table_definitions():
            definition_row: sqlite3.Row | None = fetch_one(
                connection,
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            )
            if definition_row is None:
                raise RunLedgerRebuildRequiredError(
                    f"run ledger schema is incomplete; missing table: {table}; "
                    "an explicit rebuild is required"
                )
            actual_definition = _normalize_schema_definition(
                column_text(definition_row, "sql")
            )
            if actual_definition != expected_definition:
                raise RunLedgerRebuildRequiredError(
                    f"run ledger table {table!r} does not match its contract; "
                    "an explicit rebuild is required"
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
        backend_identity=_typed_field(payload, "backend_identity", str),
    )
