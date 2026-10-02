"""Run-ledger schema behavior."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from ..indexer._run_ledger_models import (
    PUBLICATION_PROOF_SCHEMA,
    REQUIRED_INDEXES,
    REQUIRED_SCHEMA,
    SCHEMA_VERSION,
)
from ..indexer._run_ledger_runtime import RunLedger
from ._child_signal import PROCESS_TIMEOUT_SECONDS
from ._run_ledger_test_support import (
    ledger_test_assert_publication_foreign_keys,
    ledger_test_assert_publication_indexes,
    ledger_test_assert_publication_tables,
    ledger_test_assert_rebuild_required_without_mutation,
    ledger_test_digest,
    ledger_test_insert_reserved_receipt,
    ledger_test_interleave_peer_after_version_read,
    ledger_test_open_concurrent_fresh_ledgers,
    ledger_test_signature,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_publication_schema_separates_receipts_from_streaming_mutations() -> None:
    """Mutation proving this can fail: remove either normalized mutation table."""
    assert {
        "publication_mutation_units",
        "publication_mutation_points",
    } <= PUBLICATION_PROOF_SCHEMA.keys()
    assert {
        "reservation_sequence",
        "next_mutation_ordinal",
        "reserved_at",
        "sealed_at",
        "rollback_started_at",
        "committed_at",
        "rolled_back_at",
    } <= PUBLICATION_PROOF_SCHEMA["publication_receipts"]
    assert {
        "prepared_at",
        "applied_at",
        "confirmed_at",
        "sealed_ordinal",
        "state",
    } <= (PUBLICATION_PROOF_SCHEMA["publication_mutation_units"])
    assert "reservation_sequence" in PUBLICATION_PROOF_SCHEMA["publication_proofs"]
    assert "prepared_at" not in PUBLICATION_PROOF_SCHEMA["publication_receipts"]


def test_publication_ledger_schema_has_a_distinct_current_version() -> None:
    """Mutation: restoring the prior version would admit the old receipt format."""
    assert SCHEMA_VERSION == 9
    assert REQUIRED_INDEXES["publication_receipt_deltas_target"] == (
        "publication_receipt_deltas",
        ("receipt_id", "target_rel_path"),
        False,
        False,
    )


def test_run_ledger_installs_and_verifies_normalized_publication_schema(
    tmp_path: Path,
) -> None:
    """Mutation proving this can fail: omit a table or weaken an index."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    expected_tables = {
        "publication_proofs",
        "publication_evidence",
        "publication_points",
        "publication_receipts",
        "publication_mutation_units",
        "publication_mutation_points",
        "publication_receipt_deltas",
        "publication_receipt_points",
        "file_state_tombstones",
    }

    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == (
            SCHEMA_VERSION
        )
        ledger_test_assert_publication_tables(connection, expected_tables)
        ledger_test_assert_publication_indexes(connection)
        ledger_test_assert_publication_foreign_keys(connection)


def test_publication_schema_enforces_open_receipt_and_state_constraints(
    tmp_path: Path,
) -> None:
    """The durable schema rejects ambiguous or malformed receipt state."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))

    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        ledger_test_insert_reserved_receipt(
            connection,
            receipt_id="receipt-one",
            reservation_sequence=1,
            generation_id=generation.generation_id,
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            ledger_test_insert_reserved_receipt(
                connection,
                receipt_id="receipt-two",
                reservation_sequence=2,
                generation_id=generation.generation_id,
            )

        connection.execute(
            """
            UPDATE publication_receipts
            SET state = 'rolling_back', rollback_started_at = 2.0
            WHERE receipt_id = 'receipt-one'
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            ledger_test_insert_reserved_receipt(
                connection,
                receipt_id="receipt-two",
                reservation_sequence=2,
                generation_id=generation.generation_id,
            )
        connection.execute(
            """
            UPDATE publication_receipts
            SET state = 'rolled_back', rolled_back_at = 3.0
            WHERE receipt_id = 'receipt-one'
            """
        )
        ledger_test_insert_reserved_receipt(
            connection,
            receipt_id="receipt-two",
            reservation_sequence=2,
            generation_id=generation.generation_id,
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            ledger_test_insert_reserved_receipt(
                connection,
                receipt_id="wrong-revision",
                reservation_sequence=1,
                generation_id=generation.generation_id,
                projection=("other-collection", 2),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO publication_mutation_units (
                    receipt_id, mutation_ordinal, sealed_ordinal, unit_id,
                    rel_path, unit_kind, source_digest, segment_ordinal,
                    is_file_end, state, prepared_at, applied_at, confirmed_at
                ) VALUES (
                    'receipt-two', 0, NULL, 'unit-one', 'src/item.py',
                    'upsert', ?, 0, 1, 'confirmed', 2.0, NULL, 3.0
                )
                """,
                (ledger_test_digest("item"),),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO file_state_tombstones (generation_id, rel_path)
                VALUES ('missing-generation', 'src/deleted.py')
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO publication_receipt_deltas (
                    receipt_id, delta_ordinal, outcome, rel_path,
                    target_rel_path, old_content_identity, new_content_identity
                ) VALUES (
                    'receipt-two', 0, 'modify', 'src/item.py',
                    NULL, 'same-content', 'same-content'
                )
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO publication_receipt_deltas (
                    receipt_id, delta_ordinal, outcome, rel_path,
                    target_rel_path, old_content_identity, new_content_identity
                ) VALUES (
                    'receipt-two', 1, 'noop', 'src/item.py',
                    NULL, 'old-content', 'new-content'
                )
                """
            )


@pytest.mark.parametrize("schema_version", [6, 7, 8])
def test_old_ledger_format_requires_rebuild_without_mutation(
    tmp_path: Path,
    schema_version: int,
) -> None:
    """Mutation: requesting WAL before the version gate mutates this database."""
    path = tmp_path / "runs.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE old_runs (value TEXT NOT NULL)")
        connection.execute("INSERT INTO old_runs VALUES ('preserve-me')")
        connection.execute(f"PRAGMA user_version = {schema_version}")
        connection.commit()

    ledger_test_assert_rebuild_required_without_mutation(path, match="not supported")


def test_live_wal_old_ledger_requires_rebuild_without_durable_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A coherent WAL reader refuses obsolete schema without changing contents."""
    path = tmp_path / "runs.sqlite3"
    require_schema = RunLedger._require_current_or_empty_schema
    observed_versions: list[int] = []

    def track_preflight_schema(
        self: RunLedger,
        connection: sqlite3.Connection,
    ) -> None:
        observed_versions.append(
            int(connection.execute("PRAGMA user_version").fetchone()[0])
        )
        require_schema(self, connection)

    peer = sqlite3.connect(path)
    try:
        assert peer.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        peer.execute("CREATE TABLE old_runs (value TEXT NOT NULL)")
        peer.execute("INSERT INTO old_runs VALUES ('preserve-me')")
        peer.execute("PRAGMA user_version = 6")
        peer.commit()

        with monkeypatch.context() as patch:
            patch.setattr(
                RunLedger,
                "_require_current_or_empty_schema",
                track_preflight_schema,
            )
            ledger_test_assert_rebuild_required_without_mutation(path, match="rebuild")
        assert observed_versions == [6]
        assert peer.execute("PRAGMA user_version").fetchone() == (6,)
        assert peer.execute("SELECT value FROM old_runs").fetchall() == [
            ("preserve-me",)
        ]
    finally:
        peer.close()


def test_nonempty_schema_zero_requires_rebuild_without_mutation(tmp_path: Path) -> None:
    """Mutation: treating every schema-zero database as fresh overwrites its shape."""
    path = tmp_path / "runs.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE foreign_state (value TEXT NOT NULL)")
        connection.execute("INSERT INTO foreign_state VALUES ('preserve-me')")
        connection.commit()

    ledger_test_assert_rebuild_required_without_mutation(
        path, match="nonempty pre-proof"
    )


def test_fresh_schema_creation_is_atomic_and_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation: autocommitted schema scripts leave a partial version-zero file."""
    path = tmp_path / "runs.sqlite3"
    create_publication_tables = RunLedger._create_publication_tables

    def fail_after_publication_tables(connection: sqlite3.Connection) -> None:
        create_publication_tables(connection)
        raise RuntimeError("injected schema-creation interruption")

    with monkeypatch.context() as patch:
        patch.setattr(
            RunLedger,
            "_create_publication_tables",
            staticmethod(fail_after_publication_tables),
        )
        with pytest.raises(RuntimeError, match="injected schema-creation interruption"):
            RunLedger(path)

    with closing(sqlite3.connect(path)) as connection, connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 0
        assert connection.execute("SELECT name FROM sqlite_master").fetchall() == []

    ledger = RunLedger(path)
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == (
            SCHEMA_VERSION
        )


def test_concurrent_fresh_schema_openers_observe_only_empty_or_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation: removing the creation transaction exposes a partial schema."""
    path = tmp_path / "runs.sqlite3"
    ledgers, errors, (first, second) = ledger_test_open_concurrent_fresh_ledgers(
        path,
        monkeypatch,
    )

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert len(ledgers) == 2
    with closing(sqlite3.connect(path)) as connection, connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == (
            SCHEMA_VERSION
        )


def test_a_schema_committed_mid_preflight_is_not_read_as_pre_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The preflight reads the version and the tables from one snapshot.

    Mutation: dropping the preflight's ``BEGIN``. The peer's commit then lands
    between the two reads, the fresh file reads as tables without a version,
    and opening raises the pre-proof refusal instead of succeeding.
    """
    path = tmp_path / "runs.sqlite3"
    path.touch()
    landed = ledger_test_interleave_peer_after_version_read(
        monkeypatch, nth_read=1, busy_seconds=0.2
    )

    RunLedger(path)

    # The snapshot held the peer off, so the opener created the schema itself.
    assert landed == [False]
    with closing(sqlite3.connect(path)) as connection, connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == (
            SCHEMA_VERSION
        )


def test_a_schema_committed_before_the_initializer_locks_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A peer that finished creating the schema first leaves nothing to refuse.

    Mutation: restoring the initializer's unlocked version-then-tables check.
    Its version read predates the peer's commit and its table read follows
    it, so opening raises "changed before current-schema creation".
    """
    path = tmp_path / "runs.sqlite3"
    path.touch()
    landed = ledger_test_interleave_peer_after_version_read(
        monkeypatch, nth_read=2, busy_seconds=PROCESS_TIMEOUT_SECONDS
    )

    RunLedger(path)

    assert landed == [True]


def test_existing_empty_file_receives_the_exact_current_schema(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite3"
    path.touch()

    ledger = RunLedger(path)

    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == (
            SCHEMA_VERSION
        )
        tables = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            )
        }
    assert tables == set(REQUIRED_SCHEMA)


def test_open_refuses_a_preexisting_incompatible_publication_index(
    tmp_path: Path,
) -> None:
    """Mutation proving this can fail: skip exact current-index verification."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("DROP INDEX publication_receipts_open")
        connection.execute(
            """
            CREATE UNIQUE INDEX publication_receipts_open
            ON publication_receipts(
                source_type, root_identity, backend_identity,
                collection_identity
            ) WHERE state = 'committed'
            """
        )
        connection.commit()

    ledger_test_assert_rebuild_required_without_mutation(
        ledger.path, match="does not match"
    )


def test_open_refuses_a_preexisting_publication_table_without_constraints(
    tmp_path: Path,
) -> None:
    """Mutation proving this can fail: skip exact table-definition verification."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TABLE file_state_tombstones")
        connection.execute(
            """
            CREATE TABLE file_state_tombstones (
                generation_id TEXT,
                rel_path TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX file_state_tombstones_path
            ON file_state_tombstones(rel_path, generation_id)
            """
        )
        connection.commit()

    ledger_test_assert_rebuild_required_without_mutation(
        ledger.path, match="does not match"
    )


def test_open_refuses_unexpected_current_schema_objects_without_mutation(
    tmp_path: Path,
) -> None:
    """Mutation: checking only required names admits a second durable authority."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("CREATE TABLE shadow_proof (value TEXT NOT NULL)")
        connection.commit()

    ledger_test_assert_rebuild_required_without_mutation(
        ledger.path, match="unexpected tables"
    )


@pytest.mark.parametrize(
    "ddl",
    [
        """
        CREATE VIEW shadow_proof_view AS
        SELECT generation_id FROM publication_proofs
        """,
        """
        CREATE TRIGGER shadow_proof_trigger
        AFTER INSERT ON publication_proofs
        BEGIN
            SELECT 1;
        END
        """,
    ],
    ids=["view", "trigger"],
)
def test_open_refuses_unexpected_schema_authorities_without_mutation(
    tmp_path: Path,
    ddl: str,
) -> None:
    """Mutation: ignoring views or triggers admits another durable authority."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute(ddl)
        connection.commit()

    ledger_test_assert_rebuild_required_without_mutation(
        ledger.path, match="unexpected objects"
    )
