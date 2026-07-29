"""Real SQLite behavior for resumable indexing generations."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from .._index_breadth import GENERATION_ID_KEY
from ..indexer._code_meta import (
    CONTENT_EPOCH_KEY,
    MEMBERSHIP_EPOCH_KEY,
    load_meta,
    publish_meta_from_file_states,
    read_meta_raw,
)
from ..indexer._content_policy import AdmissionDisposition, AdmissionReason, ContentKind
from ..indexer._file_state import FileState, FileStateKind
from ..indexer._run_ledger_commits import retained_point_ids_sql
from ..indexer._run_ledger_models import (
    FETCH_BATCH,
    INDEX_RUN_LEDGER_FILENAME,
    RESUMABLE_STATES,
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    RunLedgerCompatibilityError,
    RunLedgerCorruptionError,
    RunLedgerIndexedPathCollisionError,
    RunLedgerStateError,
    RunOperation,
    RunSignature,
    RunTerminalState,
    index_run_ledger_path,
)
from ..indexer._run_ledger_runtime import RunLedger

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _digest(value: str) -> str:
    return hashlib.blake2b(value.encode("utf-8")).hexdigest()


def _signature(root: Path, *, content_epoch: str = "content-v1") -> RunSignature:
    return RunSignature(
        root_identity=str(root.resolve()),
        collection_identity="source-v1",
        source_type=ContentKind.CODE,
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
    )


def _unit(
    path: str,
    ordinal: int,
    count: int,
    *,
    digest: str | None = None,
) -> CommitUnit:
    return CommitUnit(
        rel_path=path,
        kind=CommitUnitKind.UPSERT,
        source_digest=digest or _digest(path),
        segment_ordinal=ordinal,
        is_file_end=ordinal == count - 1,
        point_ids=(f"{path}:{ordinal}:0", f"{path}:{ordinal}:1"),
    )


def test_generation_transactions_resume_and_invalidate_drift(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "index" / "runs.sqlite3")
    signature = _signature(tmp_path)

    first = ledger.start_generation(signature)
    resumed = ledger.start_generation(signature)
    assert resumed.generation_id == first.generation_id
    assert resumed.signature == signature

    replacement = ledger.start_generation(
        replace(signature, content_epoch="content-v2")
    )
    assert replacement.generation_id != first.generation_id
    invalidated = ledger.generation(first.generation_id)
    assert invalidated.terminal_state is RunTerminalState.INVALIDATED
    assert invalidated.terminal_detail == "generation signature changed"

    unit = _unit("src/resume.py", 0, 1)
    ledger.record_storage_confirmed_unit(replacement.generation_id, unit)
    ledger.finish_generation(
        replacement.generation_id,
        RunTerminalState.CANCELLED,
        detail="operator requested cancellation",
    )
    retry = ledger.start_generation(replacement.signature)
    assert retry.generation_id == replacement.generation_id
    assert retry.terminal_state is RunTerminalState.RUNNING
    assert retry.terminal_detail is None
    assert ledger.unit_committed(retry.generation_id, unit)

    clean_signature = replace(
        replacement.signature,
        clean=True,
        content_epoch="clean-replacement",
    )
    clean = ledger.start_generation(clean_signature)
    ledger.finish_generation(
        clean.generation_id,
        RunTerminalState.REBUILD_INCOMPLETE,
        detail="replacement interrupted",
    )
    resumed_clean = ledger.start_generation(clean_signature)
    assert resumed_clean.generation_id == clean.generation_id
    assert resumed_clean.destructive_intent


def test_shared_path_and_latest_generation_are_independent_per_kind(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    assert index_run_ledger_path(data_root) == data_root / INDEX_RUN_LEDGER_FILENAME
    ledger = RunLedger(index_run_ledger_path(data_root))
    code = ledger.start_generation(_signature(tmp_path))
    document = ledger.start_generation(
        replace(
            _signature(tmp_path),
            source_type=ContentKind.DOCUMENT,
            collection_identity="document-v1",
        )
    )

    assert ledger.latest_generation(ContentKind.CODE) == code
    assert (
        ledger.latest_generation(
            ContentKind.DOCUMENT,
            collection_identity="document-v1",
        )
        == document
    )

    legacy_root = tmp_path / "legacy"
    legacy_path = legacy_root / "code_index_runs.sqlite3"
    RunLedger(legacy_path)
    assert index_run_ledger_path(legacy_root) == legacy_path


def test_commit_units_are_atomic_idempotent_and_row_streamed(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    digest = _digest("large-source")
    units = [_unit("src/large.py", ordinal, 3, digest=digest) for ordinal in range(3)]

    assert ledger.record_storage_confirmed_unit(generation.generation_id, units[0])
    assert not ledger.record_storage_confirmed_unit(generation.generation_id, units[0])
    assert not ledger.file_complete(generation.generation_id, "src/large.py")
    for unit in units[1:]:
        assert ledger.record_storage_confirmed_unit(generation.generation_id, unit)
    assert ledger.file_complete(generation.generation_id, "src/large.py")
    assert list(ledger.iter_units(generation.generation_id, batch_size=1)) == units

    conflicting = _unit("src/large.py", 0, 3, digest=_digest("different"))
    with pytest.raises(RunLedgerStateError, match="source digest"):
        ledger.record_storage_confirmed_unit(generation.generation_id, conflicting)
    assert list(ledger.iter_units(generation.generation_id)) == units
    duplicate_point = CommitUnit(
        rel_path="src/duplicate.py",
        kind=CommitUnitKind.UPSERT,
        source_digest=_digest("duplicate"),
        segment_ordinal=0,
        is_file_end=True,
        point_ids=(units[0].point_ids[0],),
    )
    with pytest.raises(RunLedgerStateError, match="point identity"):
        ledger.record_storage_confirmed_unit(
            generation.generation_id,
            duplicate_point,
        )
    assert list(ledger.iter_point_ids(generation.generation_id, batch_size=2)) == [
        point_id for unit in units for point_id in unit.point_ids
    ]

    deletion = CommitUnit(
        rel_path="src/removed.py",
        kind=CommitUnitKind.DELETE_PATH,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("removed-point",),
    )
    assert ledger.record_storage_confirmed_unit(generation.generation_id, deletion)
    assert ledger.file_complete(generation.generation_id, deletion.rel_path)


def test_file_outcomes_and_finalization_are_immutable(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    indexed = FileState.indexed("src/good.py", ContentKind.CODE, _digest("good"))
    rejected = FileState.policy_rejected(
        "notes/readme.md",
        AdmissionDisposition(
            kind=None,
            admitted=False,
            reason=AdmissionReason.SOURCE_PROFILE_EXCLUDED,
        ),
    )
    failed = FileState.failed(
        "src/bad.py",
        FileStateKind.DECODE_FAILED,
        ContentKind.CODE,
        "invalid source encoding",
        content_hash=_digest("bad"),
    )
    with pytest.raises(RunLedgerStateError, match="storage-confirmed"):
        ledger.record_file_state(generation.generation_id, indexed)
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        _unit("src/good.py", 0, 1, digest=indexed.content_hash),
    )
    wrong_hash = replace(indexed, content_hash=_digest("different-good"))
    with pytest.raises(RunLedgerStateError, match="hash differs"):
        ledger.record_file_state(generation.generation_id, wrong_hash)
    for state in (indexed, rejected, failed):
        ledger.record_file_state(generation.generation_id, state)
    good_point_ids = _unit(
        "src/good.py",
        0,
        1,
        digest=indexed.content_hash,
    ).point_ids
    assert ledger.retained_point_ids_for_candidates(
        generation.generation_id,
        (*good_point_ids, "not-in-the-generation"),
    ) == frozenset(good_point_ids)
    with pytest.raises(RunLedgerStateError, match="path is indexed"):
        ledger.record_storage_confirmed_unit(
            generation.generation_id,
            _unit("src/good.py", 1, 2, digest=indexed.content_hash),
        )

    assert list(ledger.iter_file_states(generation.generation_id, batch_size=1)) == [
        rejected,
        failed,
        indexed,
    ]
    assert list(
        ledger.iter_file_states(generation.generation_id, converged_only=True)
    ) == [rejected, indexed]

    with pytest.raises(RunLedgerStateError, match="unresolved"):
        ledger.advance_finalization(
            generation.generation_id,
            FinalizationPhase.STALE_RECONCILED,
        )
    assert failed.content_hash is not None
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        _unit("src/bad.py", 0, 1, digest=failed.content_hash),
    )
    ledger.record_file_state(
        generation.generation_id,
        FileState.indexed("src/bad.py", ContentKind.CODE, failed.content_hash),
    )

    with pytest.raises(RunLedgerStateError, match="cannot advance"):
        ledger.advance_finalization(
            generation.generation_id,
            FinalizationPhase.METADATA_PUBLISHED,
        )
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        advanced = ledger.advance_finalization(generation.generation_id, phase)
        assert advanced.finalization_phase is phase
        if phase is FinalizationPhase.STALE_RECONCILED:
            with pytest.raises(RunLedgerStateError, match="finalization begins"):
                ledger.record_file_state(generation.generation_id, failed)
    with pytest.raises(RunLedgerStateError, match=r"only compact\(\)"):
        ledger.advance_finalization(
            generation.generation_id,
            FinalizationPhase.COMPACTED,
        )

    completed = ledger.finish_generation(
        generation.generation_id,
        RunTerminalState.SUCCEEDED,
    )
    assert completed.complete
    with pytest.raises(RunLedgerStateError, match="immutable"):
        ledger.record_file_state(generation.generation_id, failed)
    assert (
        ledger.finish_generation(
            generation.generation_id,
            RunTerminalState.SUCCEEDED,
        )
        == completed
    )


def _indexed_path_ledger(tmp_path: Path, digest: str) -> tuple[RunLedger, str]:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        _unit("src/drift.py", 0, 1, digest=digest),
    )
    ledger.record_file_state(
        generation.generation_id,
        FileState.indexed("src/drift.py", ContentKind.CODE, digest),
    )
    return ledger, generation.generation_id


# Both guard tests below were proven able to fail, by deleting the indexed-path
# branch of ``_record_storage_confirmed_unit`` outright, running them alone,
# observing the failures recorded here, restoring, and observing them pass.
#
# What the removal does NOT produce is a permitted write, and a reader who
# expects "DID NOT RAISE" will wrongly conclude these tests are vacuous. An
# indexed file state is only accepted when storage-confirmed upsert units for
# the same digest already exist (``record_file_state``), so a drifted upsert
# onto an indexed path always also violates "segments for one path must share
# one source digest". The two branches overlap on this input by construction,
# and the indexed-path branch exists to win that race and answer with a *typed*
# error the drift repair can act on.
#
# So the assertion that carries the guard is the type, and both directions land
# there:
#   - guard removed: the sibling-digest branch refuses instead, and
#     ``RunLedgerStateError('segments for one path must share one source
#     digest')`` escapes ``pytest.raises(RunLedgerIndexedPathCollisionError)``
#     in the first test and fails ``isinstance`` - the second test's own named
#     assertion - in the second.
#   - guard restored: both pass.
#
# Never relax these to catch the base class or to match on the message. A
# message-based matcher passes whichever branch fires, which is exactly the
# distinction the dedicated type was introduced to make.
def test_upsert_onto_an_indexed_path_raises_the_dedicated_collision(
    tmp_path: Path,
) -> None:
    indexed_digest = _digest("original")
    ledger, generation_id = _indexed_path_ledger(tmp_path, indexed_digest)

    edited_digest = _digest("edited")
    # The exact type is the assertion. A caller must be able to separate this
    # repairable condition - a file edited while the run that indexed it was
    # still going - from a genuinely broken generation invariant, and the base
    # state error carries no way to tell them apart.
    with pytest.raises(RunLedgerIndexedPathCollisionError) as drifted:
        ledger.record_storage_confirmed_unit(
            generation_id,
            _unit("src/drift.py", 1, 2, digest=edited_digest),
        )
    error = drifted.value
    assert type(error) is RunLedgerIndexedPathCollisionError
    assert error.generation_id == generation_id
    assert error.rel_path == "src/drift.py"
    assert error.indexed_digest == indexed_digest
    assert error.unit_digest == edited_digest
    assert error.is_drift

    with pytest.raises(RunLedgerIndexedPathCollisionError) as resubmitted:
        ledger.record_storage_confirmed_unit(
            generation_id,
            _unit("src/drift.py", 1, 2, digest=indexed_digest),
        )
    assert not resubmitted.value.is_drift


def test_indexed_path_collision_stays_catchable_as_a_state_error(
    tmp_path: Path,
) -> None:
    indexed_digest = _digest("original")
    ledger, generation_id = _indexed_path_ledger(tmp_path, indexed_digest)

    # Handlers written against the base class predate the dedicated type and
    # must keep intercepting the collision unchanged.
    try:
        ledger.record_storage_confirmed_unit(
            generation_id,
            _unit("src/drift.py", 1, 2, digest=_digest("edited")),
        )
    except RunLedgerStateError as caught:
        assert isinstance(caught, RunLedgerIndexedPathCollisionError)
        assert "path is indexed" in str(caught)
    else:  # pragma: no cover - the guard above always raises
        pytest.fail("recording an upsert onto an indexed path must be refused")


def test_compaction_preserves_published_and_running_generations(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    first = ledger.start_generation(_signature(tmp_path, content_epoch="first"))
    second = ledger.start_generation(_signature(tmp_path, content_epoch="second"))
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(second.generation_id, phase)
    ledger.finish_generation(second.generation_id, RunTerminalState.SUCCEEDED)

    document = replace(
        _signature(tmp_path),
        source_type=ContentKind.DOCUMENT,
        collection_identity="document-v1",
    )
    running = ledger.start_generation(document)
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(running.generation_id, phase)
    document_published = ledger.finish_generation(
        running.generation_id,
        RunTerminalState.SUCCEEDED,
    )
    assert ledger.compact(second.generation_id) == 1
    with pytest.raises(KeyError):
        ledger.generation(first.generation_id)
    assert ledger.generation(second.generation_id).finalization_phase is (
        FinalizationPhase.COMPACTED
    )
    assert ledger.generation(running.generation_id) == document_published


def test_schema_compatibility_and_corruption_fail_closed(tmp_path: Path) -> None:
    incompatible = tmp_path / "incompatible.sqlite3"
    connection = sqlite3.connect(incompatible)
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    with pytest.raises(RunLedgerCompatibilityError, match="not supported"):
        RunLedger(incompatible)

    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")
    with pytest.raises(RunLedgerCorruptionError, match="cannot open"):
        RunLedger(corrupt)

    logical = RunLedger(tmp_path / "logical.sqlite3")
    generation = logical.start_generation(_signature(tmp_path))
    connection = sqlite3.connect(logical.path)
    connection.execute(
        "UPDATE generations SET signature_json = ? WHERE generation_id = ?",
        (
            generation.signature.canonical_json.replace("content-v1", "tampered"),
            generation.generation_id,
        ),
    )
    connection.commit()
    connection.close()
    with pytest.raises(RunLedgerCorruptionError, match="signature"):
        logical.start_generation(generation.signature)

    incomplete_path = tmp_path / "incomplete.sqlite3"
    RunLedger(incomplete_path)
    connection = sqlite3.connect(incomplete_path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("DROP TABLE file_states")
    connection.close()
    with pytest.raises(RunLedgerCompatibilityError, match="missing tables"):
        RunLedger(incomplete_path)

    malformed = RunLedger(tmp_path / "malformed.sqlite3")
    malformed_generation = malformed.start_generation(_signature(tmp_path))
    connection = sqlite3.connect(malformed.path)
    connection.execute(
        "UPDATE generations SET terminal_state = 'unknown' WHERE generation_id = ?",
        (malformed_generation.generation_id,),
    )
    connection.commit()
    connection.close()
    with pytest.raises(RunLedgerCorruptionError, match="generation"):
        malformed.generation(malformed_generation.generation_id)


def test_bounded_iterator_does_not_hold_a_writer_transaction(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    first = _unit("src/a.py", 0, 1)
    second = _unit("src/b.py", 0, 1)
    ledger.record_storage_confirmed_unit(generation.generation_id, first)
    ledger.record_storage_confirmed_unit(generation.generation_id, second)

    rows = ledger.iter_units(generation.generation_id, batch_size=1)
    assert next(rows) == first
    third = _unit("src/c.py", 0, 1)
    assert ledger.record_storage_confirmed_unit(generation.generation_id, third)
    assert list(rows) == [second, third]


def test_incremental_manifest_carries_forward_and_deletes_exact_paths(
    tmp_path: Path,
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    full = ledger.start_generation(_signature(tmp_path))
    hashes = {path: _digest(path) for path in ("src/a.py", "src/b.py")}
    for path, content_hash in hashes.items():
        ledger.record_storage_confirmed_unit(
            full.generation_id,
            _unit(path, 0, 1, digest=content_hash),
        )
        ledger.record_file_state(
            full.generation_id,
            FileState.indexed(path, ContentKind.CODE, content_hash),
        )
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(full.generation_id, phase)
    ledger.finish_generation(full.generation_id, RunTerminalState.SUCCEEDED)

    incremental_signature = replace(
        full.signature,
        operation=RunOperation.INCREMENTAL,
        configuration_fingerprint="configuration-v2",
    )
    incremental = ledger.start_generation(incremental_signature)
    assert incremental.parent_generation_id == full.generation_id
    assert [
        state.rel_path for state in ledger.iter_file_states(incremental.generation_id)
    ] == ["src/a.py", "src/b.py"]

    deletion = CommitUnit(
        rel_path="src/a.py",
        kind=CommitUnitKind.DELETE_PATH,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("old-a",),
    )
    ledger.record_storage_confirmed_unit(incremental.generation_id, deletion)
    with pytest.raises(RunLedgerStateError, match="retained in the manifest"):
        ledger.advance_finalization(
            incremental.generation_id,
            FinalizationPhase.STALE_RECONCILED,
        )
    ledger.record_path_deleted(incremental.generation_id, "src/a.py")
    assert [
        state.rel_path for state in ledger.iter_file_states(incremental.generation_id)
    ] == ["src/b.py"]

    replacement_hash = _digest("new-b")
    first_segment = _unit("src/b.py", 0, 2, digest=replacement_hash)
    ledger.record_storage_confirmed_unit(incremental.generation_id, first_segment)
    with pytest.raises(RunLedgerStateError, match="incomplete"):
        ledger.advance_finalization(
            incremental.generation_id,
            FinalizationPhase.STALE_RECONCILED,
        )
    ledger.record_storage_confirmed_unit(
        incremental.generation_id,
        _unit("src/b.py", 1, 2, digest=replacement_hash),
    )
    ledger.record_file_state(
        incremental.generation_id,
        FileState.indexed("src/b.py", ContentKind.CODE, replacement_hash),
    )
    stale_deletion = CommitUnit(
        rel_path="src/b.py",
        kind=CommitUnitKind.DELETE_STALE,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("superseded-b",),
    )
    assert ledger.record_storage_confirmed_unit(
        incremental.generation_id,
        stale_deletion,
    )
    assert [
        state.content_hash
        for state in ledger.iter_file_states(incremental.generation_id)
    ] == [replacement_hash]
    assert list(
        ledger.iter_retained_point_ids(incremental.generation_id, batch_size=1)
    ) == [
        point_id
        for ordinal in range(2)
        for point_id in _unit(
            "src/b.py",
            ordinal,
            2,
            digest=replacement_hash,
        ).point_ids
    ]


def test_retained_point_iteration_stays_on_index_seeks(tmp_path: Path) -> None:
    """Guard: the retained-point walk must never scan a generation's points.

    The ledger never runs ANALYZE, so no ``sqlite_stat1`` table exists and
    the planner works from default estimates. Under those estimates the
    plain-JOIN form of the retained-point query visits ``commit_point_ids``
    before ``commit_units``, reachable only by ``generation_id`` - a scan of
    every committed point in the generation for every file row, re-sorted
    through a temp B-tree, repeated per keyset batch. On a corpus of tens of
    thousands of points that turns a sub-second walk into minutes of CPU
    while the writer lock is held. The pinned join order keeps every batch
    on index seeks; this test asserts the plan properties that pinning
    guarantees, on a ledger built through the production API so the
    statistics conditions match production exactly.

    Failure direction proven: replacing both CROSS JOINs with plain JOINs
    in the SQL this test imports makes the keyset-batch plan reach
    ``commit_point_ids`` without the ``unit_id`` seek and adds a temp
    B-tree, failing the seek assertion below; restoring CROSS JOIN makes
    it pass again.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    full = ledger.start_generation(_signature(tmp_path))
    for path in ("src/a.py", "src/b.py"):
        content_hash = _digest(path)
        ledger.record_storage_confirmed_unit(
            full.generation_id,
            _unit(path, 0, 1, digest=content_hash),
        )
        ledger.record_file_state(
            full.generation_id,
            FileState.indexed(path, ContentKind.CODE, content_hash),
        )
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(full.generation_id, phase)
    ledger.finish_generation(full.generation_id, RunTerminalState.SUCCEEDED)
    incremental = ledger.start_generation(
        replace(full.signature, operation=RunOperation.INCREMENTAL)
    )

    # The carried manifest must actually flow through the pinned query.
    assert list(ledger.iter_retained_point_ids(incremental.generation_id)) == [
        point_id
        for path in ("src/a.py", "src/b.py")
        for point_id in _unit(path, 0, 1, digest=_digest(path)).point_ids
    ]

    connection = sqlite3.connect(ledger.path)
    try:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'sqlite_stat1'"
            ).fetchone()
            is None
        ), "ANALYZE ran; the planner conditions this guard exists for are gone"
        plan = [
            str(row[3])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN "
                + retained_point_ids_sql(scoped_to_path=False, keyset=True),
                (
                    CommitUnitKind.UPSERT.value,
                    incremental.generation_id,
                    FileStateKind.INDEXED.value,
                    "src/a.py",
                    0,
                    1,
                    "src/a.py:0:1",
                    FETCH_BATCH,
                ),
            )
        ]
    finally:
        connection.close()

    points_steps = [step for step in plan if "commit_point_ids" in step]
    assert points_steps, f"plan named no commit_point_ids access: {plan}"
    # The degenerate plan reads 'USING INDEX ..._2 (generation_id=?)':
    # a per-file scan of the whole generation's points. The pinned plan
    # must seek the point primary key on both join columns.
    assert all("unit_id=?" in step for step in points_steps), plan
    assert not any("TEMP B-TREE" in step.upper() for step in plan), plan


def test_metadata_publication_streams_only_converged_ledger_rows(
    tmp_path: Path,
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    content_hash = _digest("published")
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        _unit("src/published.py", 0, 1, digest=content_hash),
    )
    ledger.record_file_state(
        generation.generation_id,
        FileState.indexed("src/published.py", ContentKind.CODE, content_hash),
    )
    ledger.record_file_state(
        generation.generation_id,
        FileState.policy_rejected(
            "notes/ignored.md",
            AdmissionDisposition(
                kind=None,
                admitted=False,
                reason=AdmissionReason.IGNORED,
            ),
        ),
    )
    meta_path = tmp_path / "code_meta.json"
    assert (
        publish_meta_from_file_states(
            meta_path,
            ledger.iter_file_states(
                generation.generation_id,
                converged_only=True,
                batch_size=1,
            ),
            generation_id=generation.generation_id,
            membership_epoch="membership-v1",
            content_epoch="content-v1",
            published_points_count=1,
        )
        == 1
    )
    assert load_meta(meta_path) == {"src/published.py": content_hash}
    raw = read_meta_raw(meta_path)
    assert raw[GENERATION_ID_KEY] == generation.generation_id
    assert raw[MEMBERSHIP_EPOCH_KEY] == "membership-v1"
    assert raw[CONTENT_EPOCH_KEY] == "content-v1"

    ledger.record_file_state(
        generation.generation_id,
        FileState.failed(
            "src/unresolved.py",
            FileStateKind.CHUNK_FAILED,
            ContentKind.CODE,
            "chunking failed",
            content_hash=_digest("unresolved"),
        ),
    )
    before = meta_path.read_bytes()
    with pytest.raises(ValueError, match="unresolved"):
        publish_meta_from_file_states(
            meta_path,
            ledger.iter_file_states(generation.generation_id),
            generation_id=generation.generation_id,
            membership_epoch="membership-v1",
            content_epoch="content-v1",
            published_points_count=1,
        )
    assert meta_path.read_bytes() == before


def test_overlapping_metadata_publications_are_each_atomic(tmp_path: Path) -> None:
    meta_path = tmp_path / "code_meta.json"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def states(prefix: str):
        barrier.wait(timeout=5.0)
        for ordinal in range(200):
            yield FileState.indexed(
                f"src/{prefix}-{ordinal:04d}.py",
                ContentKind.CODE,
                _digest(f"{prefix}-{ordinal}"),
            )

    def publish(prefix: str) -> None:
        try:
            publish_meta_from_file_states(
                meta_path,
                states(prefix),
                generation_id=f"generation-{prefix}",
                membership_epoch="membership-v1",
                content_epoch="content-v1",
                published_points_count=1,
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=publish, args=(prefix,)) for prefix in ("left", "right")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    raw = read_meta_raw(meta_path)
    winner = raw[GENERATION_ID_KEY].removeprefix("generation-")
    assert winner in {"left", "right"}
    published = load_meta(meta_path)
    assert len(published) == 200
    assert all(path.startswith(f"src/{winner}-") for path in published)
    assert not list(tmp_path.glob(f".{meta_path.name}.*.tmp"))


def test_reopening_a_drifted_path_supersedes_only_its_stale_upserts(
    tmp_path: Path,
) -> None:
    """A resumed indexed path whose source changed can be ingested again.

    This is the ledger half of the resume-after-failure cascade: an attempt
    marks a path indexed, fails, and the next attempt finds that path's source
    changed. Its fresh segments carry a new digest, so they are neither
    recognised as already committed nor writable over an indexed path.
    """
    ledger = RunLedger(index_run_ledger_path(tmp_path))
    generation = ledger.start_generation(_signature(tmp_path))
    generation_id = generation.generation_id
    old_digest = _digest("before the edit")
    new_digest = _digest("after the edit")

    for ordinal in range(2):
        ledger.record_storage_confirmed_unit(
            generation_id,
            _unit("src/drifted.py", ordinal, 2, digest=old_digest),
        )
    ledger.record_storage_confirmed_unit(
        generation_id,
        CommitUnit(
            rel_path="src/drifted.py",
            kind=CommitUnitKind.DELETE_STALE,
            source_digest=None,
            segment_ordinal=0,
            is_file_end=True,
            point_ids=("src/drifted.py:stale:0",),
        ),
    )
    ledger.record_file_state(
        generation_id,
        FileState.indexed("src/drifted.py", ContentKind.CODE, old_digest),
    )
    for ordinal in range(2):
        ledger.record_storage_confirmed_unit(
            generation_id,
            _unit("src/untouched.py", ordinal, 2),
        )
    ledger.record_file_state(
        generation_id,
        FileState.indexed(
            "src/untouched.py", ContentKind.CODE, _digest("src/untouched.py")
        ),
    )

    lookup = ("src/drifted.py", "src/untouched.py")
    assert ledger.indexed_digests_for_paths(generation_id, lookup) == {
        "src/drifted.py": old_digest,
        "src/untouched.py": _digest("src/untouched.py"),
    }

    # The cascade itself: the fresh content cannot be written over the path.
    fresh = _unit("src/drifted.py", 0, 1, digest=new_digest)
    with pytest.raises(RunLedgerStateError, match="after a path is indexed"):
        ledger.record_storage_confirmed_unit(generation_id, fresh)

    assert (
        ledger.reopen_drifted_path(
            generation_id, "src/drifted.py", superseded_digest=old_digest
        )
        == 2
    )

    remaining = [
        unit
        for unit in ledger.iter_units(generation_id)
        if unit.rel_path == "src/drifted.py"
    ]
    # The deletion unit is the durable record that the published points were
    # removed from storage, so it must outlive the upserts it supersedes.
    assert [unit.kind for unit in remaining] == [CommitUnitKind.DELETE_STALE]
    assert not any(unit.source_digest == old_digest for unit in remaining)
    # A sibling path's evidence and indexed state are untouched.
    untouched = [
        unit
        for unit in ledger.iter_units(generation_id)
        if unit.rel_path == "src/untouched.py"
    ]
    assert len(untouched) == 2
    assert ledger.indexed_digests_for_paths(generation_id, lookup) == {
        "src/untouched.py": _digest("src/untouched.py")
    }

    # The previously refused write now succeeds and the path re-converges.
    ledger.record_storage_confirmed_unit(generation_id, fresh)
    ledger.record_file_state(
        generation_id,
        FileState.indexed("src/drifted.py", ContentKind.CODE, new_digest),
    )
    assert ledger.indexed_digests_for_paths(generation_id, ("src/drifted.py",)) == {
        "src/drifted.py": new_digest
    }
    # Replaying the re-open after an interruption removes nothing.
    assert (
        ledger.reopen_drifted_path(
            generation_id, "src/drifted.py", superseded_digest=old_digest
        )
        == 0
    )


def test_reopening_a_path_is_refused_once_finalization_begins(tmp_path: Path) -> None:
    """Re-opening is an ingestion-phase repair, not a post-publication edit."""
    ledger = RunLedger(index_run_ledger_path(tmp_path))
    generation_id = ledger.start_generation(_signature(tmp_path)).generation_id
    digest = _digest("only content")
    ledger.record_storage_confirmed_unit(
        generation_id, _unit("src/one.py", 0, 1, digest=digest)
    )
    ledger.record_file_state(
        generation_id, FileState.indexed("src/one.py", ContentKind.CODE, digest)
    )
    ledger.advance_finalization(generation_id, FinalizationPhase.STALE_RECONCILED)

    with pytest.raises(RunLedgerStateError, match="finalization"):
        ledger.reopen_drifted_path(
            generation_id, "src/one.py", superseded_digest=digest
        )


def test_carried_forward_points_are_retained_by_the_inheriting_generation(
    tmp_path: Path,
) -> None:
    """Inherited points must survive a generation that carries them forward.

    A carried-forward file state keeps the generation that produced its
    evidence while living under the new one, so its units - and therefore its
    points - belong to the parent. A retained-point lookup that constrains
    points to the querying generation finds none of them, the caller reads
    that as obsolete, and an ordinary incremental run silently deletes the
    inherited half of the index.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    full = ledger.start_generation(_signature(tmp_path))
    paths = ("src/carried_one.py", "src/carried_two.py")
    inherited_points: set[str] = set()
    for path in paths:
        unit = _unit(path, 0, 1, digest=_digest(path))
        inherited_points.update(unit.point_ids)
        ledger.record_storage_confirmed_unit(full.generation_id, unit)
        ledger.record_file_state(
            full.generation_id,
            FileState.indexed(path, ContentKind.CODE, _digest(path)),
        )
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(full.generation_id, phase)
    ledger.finish_generation(full.generation_id, RunTerminalState.SUCCEEDED)

    incremental = ledger.start_generation(
        replace(
            full.signature,
            operation=RunOperation.INCREMENTAL,
            configuration_fingerprint="configuration-v2",
        )
    )
    assert incremental.parent_generation_id == full.generation_id
    # The states now live under the new generation while their evidence still
    # points at the parent, which is the condition that made this reachable.
    carried = ledger.file_states_for_paths(incremental.generation_id, paths)
    assert set(carried) == set(paths)

    retained = ledger.retained_point_ids_for_candidates(
        incremental.generation_id,
        tuple(sorted(inherited_points)),
    )
    assert retained == frozenset(inherited_points), (
        "carried-forward points were not recognised as retained; an "
        "incremental run would delete the inherited index"
    )


def test_a_repeatedly_failing_generation_retires_instead_of_resuming(
    tmp_path: Path,
) -> None:
    """Resumption is bounded, so a deterministic fault cannot wedge forever.

    A generation that keeps failing for a stable reason is inherited by every
    later attempt, which fails the same way. Without a bound the only escape
    is an unrelated signature change, so one transient cause can hold an
    index down indefinitely.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = replace(_signature(tmp_path), operation=RunOperation.INCREMENTAL)
    original = ledger.start_generation(signature).generation_id

    # Below the bound the generation is still the right thing to resume.
    for _attempt in range(2):
        resumed = ledger.start_generation(signature)
        assert resumed.generation_id == original
        ledger.finish_generation(
            resumed.generation_id,
            RunTerminalState.FAILED,
            detail="a stable fault",
        )
    still_resumable = ledger.start_generation(signature)
    assert still_resumable.generation_id == original
    ledger.finish_generation(
        still_resumable.generation_id,
        RunTerminalState.FAILED,
        detail="a stable fault",
    )

    # At the bound it retires and the next attempt starts clean.
    replacement = ledger.start_generation(signature)
    assert replacement.generation_id != original

    retired = ledger.generation(original)
    # Invalidated rather than deleted: the evidence stays readable until a
    # later success compacts it, and invalidated is not resumable.
    assert retired.terminal_state is RunTerminalState.INVALIDATED
    assert retired.terminal_detail is not None
    assert "consecutive failed attempts" in retired.terminal_detail
    assert RunTerminalState.INVALIDATED not in RESUMABLE_STATES


def test_a_succeeding_generation_never_accrues_resume_failures(
    tmp_path: Path,
) -> None:
    """Only unsuccessful outcomes advance the bound."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(_signature(tmp_path))
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(generation.generation_id, phase)
    ledger.finish_generation(generation.generation_id, RunTerminalState.SUCCEEDED)

    with sqlite3.connect(tmp_path / "runs.sqlite3") as connection:
        failures = connection.execute(
            "SELECT consecutive_failures FROM generations WHERE generation_id = ?",
            (generation.generation_id,),
        ).fetchone()[0]
    assert int(failures) == 0


def _publish_and_compact(ledger: RunLedger, generation_id: str) -> int:
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(generation_id, phase)
    ledger.finish_generation(generation_id, RunTerminalState.SUCCEEDED)
    return ledger.compact(generation_id)


def test_compaction_keeps_generations_backing_carried_evidence(
    tmp_path: Path,
) -> None:
    """Compacting a published carrier must not sever its inherited evidence.

    A carried-forward file state pins the generation that produced its
    evidence; the commit units that vouch for its stored points live there.
    Deleting that generation cascades the units away, and the next run's
    retention lookup then reads every inherited point as obsolete and purges
    the entire collection.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = _signature(tmp_path)
    unit = _unit("src/kept.py", 0, 1)

    origin = ledger.start_generation(signature)
    ledger.record_storage_confirmed_unit(origin.generation_id, unit)
    ledger.record_file_state(
        origin.generation_id,
        FileState(
            "src/kept.py",
            FileStateKind.INDEXED,
            ContentKind.CODE,
            _digest("src/kept.py"),
        ),
    )
    _publish_and_compact(ledger, origin.generation_id)

    carrier = ledger.start_generation(signature)
    assert carrier.parent_generation_id == origin.generation_id
    _publish_and_compact(ledger, carrier.generation_id)

    # The generation the carried state cites must survive its child's
    # compaction, or the retained-point lookup below returns nothing and the
    # purge deletes the whole collection.
    assert ledger.generation(origin.generation_id).terminal_state is (
        RunTerminalState.SUCCEEDED
    )
    successor = ledger.start_generation(signature)
    assert ledger.retained_point_ids_for_candidates(
        successor.generation_id,
        unit.point_ids,
    ) == frozenset(unit.point_ids)


def test_compaction_removes_generations_no_surviving_state_cites(
    tmp_path: Path,
) -> None:
    """Evidence retention is exact: superseded generations still compact."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = _signature(tmp_path)

    origin = ledger.start_generation(signature)
    ledger.record_storage_confirmed_unit(
        origin.generation_id, _unit("src/kept.py", 0, 1)
    )
    ledger.record_file_state(
        origin.generation_id,
        FileState(
            "src/kept.py",
            FileStateKind.INDEXED,
            ContentKind.CODE,
            _digest("src/kept.py"),
        ),
    )
    _publish_and_compact(ledger, origin.generation_id)

    carrier = ledger.start_generation(signature)
    _publish_and_compact(ledger, carrier.generation_id)

    # A clean rebuild re-homes every file's evidence to itself, so nothing
    # cites the earlier generations and both must compact away.
    rebuild = ledger.start_generation(replace(signature, clean=True))
    ledger.record_storage_confirmed_unit(
        rebuild.generation_id, _unit("src/kept.py", 0, 1)
    )
    ledger.record_file_state(
        rebuild.generation_id,
        FileState(
            "src/kept.py",
            FileStateKind.INDEXED,
            ContentKind.CODE,
            _digest("src/kept.py"),
        ),
    )
    assert _publish_and_compact(ledger, rebuild.generation_id) == 2
    with pytest.raises(KeyError):
        ledger.generation(origin.generation_id)
    with pytest.raises(KeyError):
        ledger.generation(carrier.generation_id)


def test_carry_forward_refuses_a_manifest_with_dangling_evidence(
    tmp_path: Path,
) -> None:
    """A published manifest whose evidence dangles must not seed a diff.

    Carrying it forward hands the new generation file states whose cited
    units no longer exist, so every inherited point reads as unretained and
    the publication purge deletes the entire collection. Refusing the parent
    forces the caller onto the full failure-safe reconciliation path instead.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = _signature(tmp_path)
    unit = _unit("src/kept.py", 0, 1)

    origin = ledger.start_generation(signature)
    ledger.record_storage_confirmed_unit(origin.generation_id, unit)
    ledger.record_file_state(
        origin.generation_id,
        FileState(
            "src/kept.py",
            FileStateKind.INDEXED,
            ContentKind.CODE,
            _digest("src/kept.py"),
        ),
    )
    _publish_and_compact(ledger, origin.generation_id)
    carrier = ledger.start_generation(signature)
    _publish_and_compact(ledger, carrier.generation_id)

    # Sever the evidence out from under the published manifest, the state a
    # ledger compacted by a build without evidence retention is left in.
    connection = sqlite3.connect(ledger.path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "DELETE FROM generations WHERE generation_id = ?",
        (origin.generation_id,),
    )
    connection.commit()
    connection.close()

    successor = ledger.start_generation(signature)
    # No parent: the incremental open refuses and the caller escalates to a
    # full reconciliation rather than diffing against poisoned evidence.
    assert successor.parent_generation_id is None
    assert ledger.file_states_for_paths(successor.generation_id, ("src/kept.py",)) == {}
