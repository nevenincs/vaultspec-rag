"""Run-ledger recovery behavior."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from ..indexer._content_policy import ContentKind
from ..indexer._file_state import FileState
from ..indexer._run_ledger_models import (
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    RunLedgerCompatibilityError,
    RunLedgerCorruptionError,
    RunLedgerIndexedPathCollisionError,
    RunLedgerStateError,
    index_run_ledger_path,
)
from ..indexer._run_ledger_runtime import RunLedger
from ._run_ledger_test_support import (
    ledger_test_digest,
    ledger_test_indexed_path_ledger,
    ledger_test_signature,
    ledger_test_unit,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


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
    indexed_digest = ledger_test_digest("original")
    ledger, generation_id = ledger_test_indexed_path_ledger(tmp_path, indexed_digest)

    edited_digest = ledger_test_digest("edited")
    # The exact type is the assertion. A caller must be able to separate this
    # repairable condition - a file edited while the run that indexed it was
    # still going - from a genuinely broken generation invariant, and the base
    # state error carries no way to tell them apart.
    with pytest.raises(RunLedgerIndexedPathCollisionError) as drifted:
        ledger.record_storage_confirmed_unit(
            generation_id,
            ledger_test_unit("src/drift.py", 1, 2, digest=edited_digest),
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
            ledger_test_unit("src/drift.py", 1, 2, digest=indexed_digest),
        )
    assert not resubmitted.value.is_drift


def test_indexed_path_collision_stays_catchable_as_a_state_error(
    tmp_path: Path,
) -> None:
    indexed_digest = ledger_test_digest("original")
    ledger, generation_id = ledger_test_indexed_path_ledger(tmp_path, indexed_digest)

    # Handlers written against the base class predate the dedicated type and
    # must keep intercepting the collision unchanged.
    try:
        ledger.record_storage_confirmed_unit(
            generation_id,
            ledger_test_unit("src/drift.py", 1, 2, digest=ledger_test_digest("edited")),
        )
    except RunLedgerStateError as caught:
        assert isinstance(caught, RunLedgerIndexedPathCollisionError)
        assert "path is indexed" in str(caught)
    else:  # pragma: no cover - the guard above always raises
        pytest.fail("recording an upsert onto an indexed path must be refused")


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
    generation = logical.start_generation(ledger_test_signature(tmp_path))
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
    malformed_generation = malformed.start_generation(ledger_test_signature(tmp_path))
    connection = sqlite3.connect(malformed.path)
    connection.execute(
        "UPDATE generations SET terminal_state = 'unknown' WHERE generation_id = ?",
        (malformed_generation.generation_id,),
    )
    connection.commit()
    connection.close()
    with pytest.raises(RunLedgerCorruptionError, match="generation"):
        malformed.generation(malformed_generation.generation_id)


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
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    generation_id = generation.generation_id
    old_digest = ledger_test_digest("before the edit")
    new_digest = ledger_test_digest("after the edit")

    for ordinal in range(2):
        ledger.record_storage_confirmed_unit(
            generation_id,
            ledger_test_unit("src/drifted.py", ordinal, 2, digest=old_digest),
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
            ledger_test_unit("src/untouched.py", ordinal, 2),
        )
    ledger.record_file_state(
        generation_id,
        FileState.indexed(
            "src/untouched.py", ContentKind.CODE, ledger_test_digest("src/untouched.py")
        ),
    )

    lookup = ("src/drifted.py", "src/untouched.py")
    assert ledger.indexed_digests_for_paths(generation_id, lookup) == {
        "src/drifted.py": old_digest,
        "src/untouched.py": ledger_test_digest("src/untouched.py"),
    }

    # The cascade itself: the fresh content cannot be written over the path.
    fresh = ledger_test_unit("src/drifted.py", 0, 1, digest=new_digest)
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
        "src/untouched.py": ledger_test_digest("src/untouched.py")
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
    generation_id = ledger.start_generation(
        ledger_test_signature(tmp_path)
    ).generation_id
    digest = ledger_test_digest("only content")
    ledger.record_storage_confirmed_unit(
        generation_id, ledger_test_unit("src/one.py", 0, 1, digest=digest)
    )
    ledger.record_file_state(
        generation_id, FileState.indexed("src/one.py", ContentKind.CODE, digest)
    )
    ledger.advance_finalization(generation_id, FinalizationPhase.STALE_RECONCILED)

    with pytest.raises(RunLedgerStateError, match="finalization"):
        ledger.reopen_drifted_path(
            generation_id, "src/one.py", superseded_digest=digest
        )
