"""Run-ledger commit units behavior."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from ..indexer._run_ledger_models import (
    CommitUnit,
    CommitUnitKind,
    RunLedgerCorruptionError,
    RunLedgerStateError,
)
from ..indexer._run_ledger_runtime import RunLedger
from ._run_ledger_test_support import (
    ledger_test_digest,
    ledger_test_signature,
    ledger_test_unit,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_commit_units_are_atomic_idempotent_and_row_streamed(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    digest = ledger_test_digest("large-source")
    units = [
        ledger_test_unit("src/large.py", ordinal, 3, digest=digest)
        for ordinal in range(3)
    ]

    assert ledger.record_storage_confirmed_unit(generation.generation_id, units[0])
    assert not ledger.record_storage_confirmed_unit(generation.generation_id, units[0])
    assert not ledger.file_complete(generation.generation_id, "src/large.py")
    for unit in units[1:]:
        assert ledger.record_storage_confirmed_unit(generation.generation_id, unit)
    assert ledger.file_complete(generation.generation_id, "src/large.py")
    assert list(ledger.iter_units(generation.generation_id, batch_size=1)) == units

    conflicting = ledger_test_unit(
        "src/large.py", 0, 3, digest=ledger_test_digest("different")
    )
    with pytest.raises(RunLedgerStateError, match="source digest"):
        ledger.record_storage_confirmed_unit(generation.generation_id, conflicting)
    assert list(ledger.iter_units(generation.generation_id)) == units
    duplicate_point = CommitUnit(
        rel_path="src/duplicate.py",
        kind=CommitUnitKind.UPSERT,
        source_digest=ledger_test_digest("duplicate"),
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


def test_commit_units_accept_storage_order_but_finalize_in_file_order(
    tmp_path: Path,
) -> None:
    """Keep length-sorted store batches independent of file-local ordinals.

    Mutation proof: restoring the insertion-time ordinal/count comparison in
    ``_assert_segment_matches_siblings`` makes the first assertion below fail
    with ``commit-unit segment ordinals must be contiguous``.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    digest = ledger_test_digest("length-sorted-source")
    units = [
        ledger_test_unit("src/large.py", ordinal, 3, digest=digest)
        for ordinal in range(3)
    ]

    assert ledger.record_storage_confirmed_unit(generation.generation_id, units[2])
    assert not ledger.file_complete(generation.generation_id, "src/large.py")
    assert (
        ledger.record_storage_confirmed_units(
            generation.generation_id,
            (units[0], units[1]),
        )
        == 2
    )

    assert ledger.file_complete(generation.generation_id, "src/large.py")
    assert list(ledger.iter_units(generation.generation_id)) == units


def test_commit_unit_point_ids_of_the_wrong_type_read_as_corruption(
    tmp_path: Path,
) -> None:
    """A stored point identity that is not a string is a detected corruption.

    Integers are the escaping class specifically: `CommitUnit.__post_init__`
    already rejects a falsy entry, so a stored `null` or `""` is caught
    incidentally by that emptiness rule and proves nothing about the entry
    types. A list of non-empty integers satisfies every invariant the unit
    checks - truthy, unique, orderable - and, without an entry check, reaches
    the store as point identities of the wrong type.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    unit = ledger_test_unit("src/a.py", 0, 1)
    ledger.record_storage_confirmed_unit(generation.generation_id, unit)

    connection = sqlite3.connect(ledger.path)
    connection.execute(
        "UPDATE commit_units SET point_ids_json = ? WHERE generation_id = ?",
        ('["src/a.py:0:0",7]', generation.generation_id),
    )
    connection.commit()
    connection.close()

    with pytest.raises(RunLedgerCorruptionError, match="malformed"):
        list(ledger.iter_units(generation.generation_id))


def test_well_formed_commit_unit_point_ids_still_read_back_exactly(
    tmp_path: Path,
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    unit = ledger_test_unit("src/a.py", 0, 1)
    ledger.record_storage_confirmed_unit(generation.generation_id, unit)

    assert list(ledger.iter_units(generation.generation_id)) == [unit]


def test_bounded_iterator_does_not_hold_a_writer_transaction(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    first = ledger_test_unit("src/a.py", 0, 1)
    second = ledger_test_unit("src/b.py", 0, 1)
    ledger.record_storage_confirmed_unit(generation.generation_id, first)
    ledger.record_storage_confirmed_unit(generation.generation_id, second)

    rows = ledger.iter_units(generation.generation_id, batch_size=1)
    assert next(rows) == first
    third = ledger_test_unit("src/c.py", 0, 1)
    assert ledger.record_storage_confirmed_unit(generation.generation_id, third)
    assert list(rows) == [second, third]
