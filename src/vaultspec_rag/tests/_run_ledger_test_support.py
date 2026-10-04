"""Shared builders for the real run-ledger behavior tests."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

from .._source_types import PublicSourceType
from ..indexer._content_policy import ContentKind
from ..indexer._file_state import FileState, FileStateKind
from ..indexer._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofCompatibilityKey,
    ProofEvidence,
    ProofMissingError,
)
from ..indexer._run_ledger_models import (
    PUBLICATION_PROOF_SCHEMA,
    REQUIRED_INDEX_PREDICATES,
    REQUIRED_INDEXES,
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    PublicationReceipt,
    RunAuthority,
    RunLedgerRebuildRequiredError,
    RunOperation,
    RunSignature,
    RunTerminalState,
)
from ..indexer._run_ledger_publication_identity import compatibility_for_signature
from ..indexer._run_ledger_runtime import RunLedger
from ._child_signal import PROCESS_TIMEOUT_SECONDS
from ._sqlite_state import assert_sqlite_unchanged, sqlite_contents

if TYPE_CHECKING:
    from collections.abc import Mapping


def ledger_test_digest(value: str) -> str:
    return hashlib.blake2b(value.encode("utf-8")).hexdigest()


def ledger_test_signature(
    root: Path,
    *,
    content_epoch: str = "content-v1",
    backend_identity: str = "backend-v1",
) -> RunSignature:
    return RunSignature(
        root_identity=str(root.resolve()),
        collection_identity="source-v1",
        source_type=PublicSourceType.CODE,
        operation=RunOperation.FULL,
        clean=False,
        model_identity="model-v1",
        dense_dimensions=8,
        embedding_schema=2,
        payload_schema=3,
        content_epoch=content_epoch,
        membership_epoch="membership-v1",
        preprocessing_identity="preprocessing-v1",
        configuration_fingerprint="configuration-v1",
        policy_fingerprint="policy-v1",
        backend_identity=backend_identity,
    )


def ledger_test_unit(
    path: str,
    ordinal: int,
    count: int,
    *,
    digest: str | None = None,
) -> CommitUnit:
    return CommitUnit(
        rel_path=path,
        kind=CommitUnitKind.UPSERT,
        source_digest=digest or ledger_test_digest(path),
        segment_ordinal=ordinal,
        is_file_end=ordinal == count - 1,
        point_ids=(f"{path}:{ordinal}:0", f"{path}:{ordinal}:1"),
    )


def ledger_test_proof_compatibility() -> ProofCompatibilityKey:
    return ProofCompatibilityKey(
        source_type=PublicSourceType.CODE,
        root_identity="root-v1",
        backend_identity="backend-v1",
        collection_identity="collection-v1",
        storage_schema=1,
        payload_schema=2,
        embedding_schema_identity="embedding-v1",
        chunking_schema_identity="chunking-v1",
        membership_identity="membership-v1",
        content_identity="content-v1",
        policy_identity="policy-v1",
    )


def ledger_test_assert_rebuild_required_without_mutation(
    path: Path, *, match: str
) -> None:
    before = sqlite_contents(path)

    with pytest.raises(RunLedgerRebuildRequiredError, match=match) as caught:
        RunLedger(path)

    assert type(caught.value) is RunLedgerRebuildRequiredError
    assert_sqlite_unchanged(path, before)


def ledger_test_assert_generation_proof_gate(
    ledger: RunLedger,
    generation_id: str,
) -> None:
    """Invoke the strict gate inside one caller-owned ledger snapshot."""
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        ledger.assert_generation_proof_committed(
            connection,
            generation_id,
        )


def ledger_test_seal_publication_receipt(
    ledger: RunLedger,
    receipt: PublicationReceipt,
    *,
    mutation: CommitUnit,
    delta: PathDelta,
) -> None:
    ledger.prepare_publication_mutation(receipt.receipt_id, mutation)
    ledger.mark_publication_mutation_applied(receipt.receipt_id, mutation)
    ledger.confirm_publication_mutation(receipt.receipt_id, mutation)
    ledger.seal_publication_receipt(receipt.receipt_id, (delta,))


def ledger_test_assert_publication_tables(
    connection: sqlite3.Connection,
    expected_tables: set[str],
) -> None:
    """Assert the normalized publication tables and their columns."""
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert expected_tables <= tables
    assert expected_tables == set(PUBLICATION_PROOF_SCHEMA)
    for table, expected_columns in PUBLICATION_PROOF_SCHEMA.items():
        actual_columns = {
            str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
        assert expected_columns <= actual_columns

    receipt_columns = {
        str(row[1]): row
        for row in connection.execute('PRAGMA table_info("publication_receipts")')
    }
    assert bool(receipt_columns["receipt_id"][3])
    assert int(receipt_columns["receipt_id"][5]) == 1


def ledger_test_duplicate_receipt_row(
    connection: sqlite3.Connection,
    source_id: str,
    *,
    receipt_id: str,
    reservation_sequence: int,
    overrides: Mapping[str, object] = MappingProxyType({}),
) -> None:
    """Copy one receipt row the ledger wrote, under a new identity.

    The copy carries every column of a row ``reserve_publication_receipt``
    produced, so no table shape is restated here and the duplicate cannot
    drift from the schema the ledger creates. It exists because the two
    conditions that need it - a second reservation open on one projection,
    and a closed history longer than the retention bound - are exactly what
    the reservation API refuses to produce one call at a time.
    """
    connection.execute(
        "CREATE TEMP TABLE receipt_copy AS "
        "SELECT * FROM publication_receipts WHERE receipt_id = ?",
        (source_id,),
    )
    try:
        connection.execute(
            """
            UPDATE receipt_copy
            SET receipt_id = ?, reservation_sequence = ?, state = 'reserved',
                next_mutation_ordinal = 0, sealed_at = NULL,
                rollback_started_at = NULL, committed_at = NULL,
                rolled_back_at = NULL
            """,
            (receipt_id, reservation_sequence),
        )
        for column, value in overrides.items():
            connection.execute(
                f"UPDATE receipt_copy SET {column} = ?",
                (value,),
            )
        connection.execute(
            "INSERT INTO publication_receipts SELECT * FROM receipt_copy"
        )
    finally:
        connection.execute("DROP TABLE receipt_copy")


def ledger_test_assert_publication_indexes(connection: sqlite3.Connection) -> None:
    """Assert every required publication index and optional predicate."""
    for name, (table, columns, unique, partial) in REQUIRED_INDEXES.items():
        index_row = next(
            row
            for row in connection.execute(f'PRAGMA index_list("{table}")')
            if str(row[1]) == name
        )
        actual_columns = tuple(
            str(row[2])
            for row in sorted(
                connection.execute(f'PRAGMA index_info("{name}")'),
                key=lambda row: int(row[0]),
            )
        )
        assert actual_columns == columns
        assert bool(index_row[2]) is unique
        assert bool(index_row[4]) is partial
        expected_predicate = REQUIRED_INDEX_PREDICATES.get(name)
        if expected_predicate is None:
            continue
        definition = " ".join(
            str(
                connection.execute(
                    "SELECT sql FROM sqlite_master WHERE name = ?", (name,)
                ).fetchone()[0]
            )
            .lower()
            .split()
        )
        _prefix, separator, predicate = definition.partition(" where ")
        actual_predicate = f"where {predicate}" if separator else ""
        assert actual_predicate == expected_predicate


def ledger_test_assert_publication_foreign_keys(connection: sqlite3.Connection) -> None:
    """Assert the normalized publication foreign-key relationships."""
    assert {
        str(row[2])
        for row in connection.execute('PRAGMA foreign_key_list("publication_evidence")')
    } == {"generations", "publication_proofs"}
    assert {
        str(row[2])
        for row in connection.execute(
            'PRAGMA foreign_key_list("file_state_tombstones")'
        )
    } == {"generations"}


def ledger_test_seeded_publication_lineage(
    tmp_path: Path,
    evidence: tuple[ProofEvidence, ...],
) -> tuple[RunLedger, ProofCompatibilityKey, str, str]:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = ledger_test_signature(tmp_path)
    parent = ledger.start_generation(signature)
    ledger.establish_verified_publication(
        parent.generation_id, RunAuthority.REBUILD, evidence
    )
    ledger_test_publish_and_compact(ledger, parent.generation_id)
    key = compatibility_for_signature(signature)
    successor = ledger.start_generation(signature)
    assert successor.parent_generation_id == parent.generation_id
    return ledger, key, parent.generation_id, successor.generation_id


def ledger_test_sealed_modify_receipt(
    tmp_path: Path,
    *,
    point_ids: tuple[str, ...],
    additional_evidence: tuple[ProofEvidence, ...] = (),
) -> tuple[
    RunLedger,
    ProofCompatibilityKey,
    str,
    str,
    PublicationReceipt,
    ProofEvidence,
    ProofEvidence,
    PathDelta,
    CommitUnit,
]:
    old = ProofEvidence(
        rel_path="src/a.py",
        content_identity=ledger_test_digest("a-v1"),
        point_ids=point_ids,
    )
    ledger, key, parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path,
        (old, *additional_evidence),
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )
    new = replace(old, content_identity=ledger_test_digest("a-v2"))
    delta = PathDelta(
        outcome=PathOutcome.MODIFY,
        expected_parent_revision=receipt.parent_revision,
        rel_path=old.rel_path,
        old=old,
        new=new,
    )
    mutation = CommitUnit(
        rel_path=new.rel_path,
        kind=CommitUnitKind.UPSERT,
        source_digest=new.content_identity,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=new.point_ids,
    )
    ledger_test_seal_publication_receipt(
        ledger,
        receipt,
        mutation=mutation,
        delta=delta,
    )
    return ledger, key, parent_id, successor_id, receipt, old, new, delta, mutation


def ledger_test_publish_generation_with_proof(
    ledger: RunLedger,
    generation_id: str,
    *,
    evidence: tuple[ProofEvidence, ...] = (),
) -> None:
    ledger.advance_finalization(generation_id, FinalizationPhase.STALE_RECONCILED)
    ledger.establish_verified_publication(generation_id, RunAuthority.REBUILD, evidence)
    ledger.advance_finalization(generation_id, FinalizationPhase.METADATA_PUBLISHED)
    ledger.advance_finalization(generation_id, FinalizationPhase.GENERATION_PUBLISHED)
    ledger.finish_generation(generation_id, RunTerminalState.SUCCEEDED)


def ledger_test_open_concurrent_fresh_ledgers(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[RunLedger], list[BaseException], tuple[threading.Thread, ...]]:
    create_base_tables = RunLedger._create_base_tables
    require_schema = RunLedger._require_current_or_empty_schema
    first_base_created = threading.Event()
    release_first_creator = threading.Event()
    second_preflight_entered = threading.Event()
    first_call = True
    call_lock = threading.Lock()
    ledgers: list[RunLedger] = []
    errors: list[BaseException] = []

    def blocking_create_base_tables(connection: sqlite3.Connection) -> None:
        nonlocal first_call
        create_base_tables(connection)
        with call_lock:
            should_block = first_call
            first_call = False
        if should_block:
            first_base_created.set()
            assert release_first_creator.wait(PROCESS_TIMEOUT_SECONDS)

    def tracked_require_schema(
        self: RunLedger,
        connection: sqlite3.Connection,
    ) -> None:
        if threading.current_thread().name == "second-schema-opener":
            second_preflight_entered.set()
        require_schema(self, connection)

    def open_ledger() -> None:
        try:
            ledgers.append(RunLedger(path))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    with monkeypatch.context() as patch:
        patch.setattr(
            RunLedger,
            "_create_base_tables",
            staticmethod(blocking_create_base_tables),
        )
        patch.setattr(
            RunLedger, "_require_current_or_empty_schema", tracked_require_schema
        )
        first = threading.Thread(target=open_ledger, name="first-schema-opener")
        second = threading.Thread(target=open_ledger, name="second-schema-opener")
        first.start()
        try:
            assert first_base_created.wait(PROCESS_TIMEOUT_SECONDS)
            second.start()
            assert second_preflight_entered.wait(PROCESS_TIMEOUT_SECONDS)
        finally:
            release_first_creator.set()
        first.join(PROCESS_TIMEOUT_SECONDS)
        second.join(PROCESS_TIMEOUT_SECONDS)

    return ledgers, errors, (first, second)


def _peer_creates_current_schema(path: Path, *, busy_seconds: float) -> bool:
    """Commit the whole current schema from another connection, as a peer would.

    Returns whether the commit landed; ``False`` means a reader's lock held it
    off for *busy_seconds*.
    """
    connection = sqlite3.connect(path, timeout=busy_seconds)
    try:
        connection.row_factory = sqlite3.Row
        # The production initializer owns the whole create sequence, including
        # its own write lock and commit. Only the connection - and the short
        # busy budget that makes a held lock observable - is supplied here.
        RunLedger.__new__(RunLedger)._initialize(connection)
    except sqlite3.OperationalError as exc:
        assert "locked" in str(exc), exc
        return False
    finally:
        connection.close()
    return True


def ledger_test_interleave_peer_after_version_read(
    monkeypatch: pytest.MonkeyPatch,
    *,
    nth_read: int,
    busy_seconds: float,
) -> list[bool]:
    """Let a peer create the schema right after the opener's *nth* version read.

    The interleaving is forced, not raced: the opener's own read returns, the
    peer then tries to commit, and only after that does the opener continue.
    """
    from ..indexer import _run_ledger_runtime

    real_fetch_one = _run_ledger_runtime.fetch_one
    reads = 0
    landed: list[bool] = []

    def interleaving_fetch_one(
        connection: sqlite3.Connection,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> object:
        nonlocal reads
        row: object = real_fetch_one(connection, sql, parameters)
        if "user_version" in sql:
            reads += 1
            if reads == nth_read:
                path = Path(connection.execute("PRAGMA database_list").fetchone()[2])
                landed.append(
                    _peer_creates_current_schema(path, busy_seconds=busy_seconds)
                )
        return row

    monkeypatch.setattr(_run_ledger_runtime, "fetch_one", interleaving_fetch_one)
    return landed


def ledger_test_indexed_path_ledger(
    tmp_path: Path, digest: str
) -> tuple[RunLedger, str]:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        ledger_test_unit("src/drift.py", 0, 1, digest=digest),
    )
    ledger.record_file_state(
        generation.generation_id,
        FileState.indexed("src/drift.py", ContentKind.CODE, digest),
    )
    return ledger, generation.generation_id


def ledger_test_certify_generation(ledger: RunLedger, generation_id: str) -> None:
    """Establish full-generation proof before a fixture publishes its phases."""
    generation = ledger.generation(generation_id)
    receipt = ledger.publication_receipt_for_generation(generation_id)
    if receipt is not None and ledger.publication_noop_completed(
        generation_id, receipt.receipt_id
    ):
        return
    key = compatibility_for_signature(generation.signature)
    try:
        proof = ledger.publication_proof(key)
    except ProofMissingError:
        proof = None
    if generation.signature.operation is RunOperation.FULL and (
        proof is None or proof.generation_id != generation_id
    ):
        evidence = tuple(
            ProofEvidence(
                state.rel_path,
                state.content_hash,
                tuple(
                    sorted(
                        ledger.iter_retained_point_ids(
                            generation_id, rel_path=state.rel_path
                        )
                    )
                ),
            )
            for state in ledger.iter_file_states(generation_id)
            if state.state is FileStateKind.INDEXED and state.content_hash is not None
        )
        ledger.establish_verified_publication(
            generation_id, RunAuthority.REBUILD, evidence
        )


def ledger_test_publish_and_finish(ledger: RunLedger, generation_id: str) -> None:
    ledger_test_certify_generation(ledger, generation_id)
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(generation_id, phase)
    ledger.finish_generation(generation_id, RunTerminalState.SUCCEEDED)


def ledger_test_publish_and_compact(ledger: RunLedger, generation_id: str) -> int:
    ledger_test_publish_and_finish(ledger, generation_id)
    return ledger.compact(generation_id)
