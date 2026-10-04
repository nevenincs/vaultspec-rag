"""Exact stale-point lookup stays proportional to the requested path."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from ..indexer import _run_ledger_files, _run_ledger_models
from ..indexer._run_ledger_models import FETCH_BATCH, CommitUnit, CommitUnitKind
from ..indexer._run_ledger_runtime import RunLedger
from ._run_ledger_test_support import (
    ledger_test_digest,
    ledger_test_signature,
    ledger_test_unit,
)
from .test_publication_scaling import _measured

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _seed_unrelated_paths(
    ledger: RunLedger, generation_id: str, *, start: int, count: int
) -> None:
    """Add confirmed units through production's bounded transaction API."""
    for page_start in range(start, start + count, FETCH_BATCH):
        units = tuple(
            ledger_test_unit(f"src/unrelated-{index:06d}.py", 0, 1)
            for index in range(page_start, min(page_start + FETCH_BATCH, start + count))
        )
        ledger.record_storage_confirmed_units(generation_id, units)


def test_superseded_points_preserve_generation_digest_kind_and_order(
    tmp_path: Path,
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = ledger_test_signature(tmp_path)
    generation = ledger.start_generation(signature)
    path = "src/changed.py"
    digest = ledger_test_digest(path)
    units = tuple(ledger_test_unit(path, ordinal, 3) for ordinal in range(3))
    ledger.record_storage_confirmed_units(
        generation.generation_id, tuple(reversed(units))
    )
    deletion = CommitUnit(
        rel_path=path,
        kind=CommitUnitKind.DELETE_STALE,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("stale-deletion-point",),
    )
    ledger.record_storage_confirmed_unit(generation.generation_id, deletion)
    _seed_unrelated_paths(ledger, generation.generation_id, start=0, count=8)
    other_generation = ledger.start_generation(
        replace(signature, content_epoch="other-content")
    )
    ledger.record_storage_confirmed_unit(
        other_generation.generation_id,
        replace(units[0], is_file_end=True, point_ids=("other-generation-point",)),
    )

    assert ledger.superseded_point_ids(
        generation.generation_id, path, source_digest=digest
    ) == tuple(point_id for unit in units for point_id in unit.point_ids)
    assert not ledger.superseded_point_ids(
        generation.generation_id,
        path,
        source_digest=ledger_test_digest("different-content"),
    )
    assert not ledger.superseded_point_ids(
        generation.generation_id, "src/missing.py", source_digest=digest
    )


def test_superseded_point_lookup_work_is_independent_of_other_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production lookup must seek the path regardless of unrelated rows.

    Process-only mutation proof: replacing CROSS JOIN with JOIN retires 369
    instructions before growth and 45,425 after growth, failing the named bound.
    A fresh process with the production implementation restored passes.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    path = "src/changed.py"
    digest = ledger_test_digest(path)
    units = tuple(ledger_test_unit(path, ordinal, 3) for ordinal in range(3))
    ledger.record_storage_confirmed_units(generation.generation_id, units)
    _seed_unrelated_paths(ledger, generation.generation_id, start=0, count=8)

    with monkeypatch.context() as probe, _measured(probe) as small_cost:
        probe.setattr(
            _run_ledger_files, "ledger_connection", _run_ledger_models.ledger_connection
        )
        small = ledger.superseded_point_ids(
            generation.generation_id, path, source_digest=digest
        )
    _seed_unrelated_paths(ledger, generation.generation_id, start=8, count=2048)
    with monkeypatch.context() as probe, _measured(probe) as large_cost:
        probe.setattr(
            _run_ledger_files, "ledger_connection", _run_ledger_models.ledger_connection
        )
        large = ledger.superseded_point_ids(
            generation.generation_id, path, source_digest=digest
        )

    expected = tuple(point_id for unit in units for point_id in unit.point_ids)
    assert small == large == expected
    assert small_cost.vm_steps > 0, "small-path production read was not measured"
    assert large_cost.vm_steps > 0, "large-path production read was not measured"
    assert large_cost.vm_steps <= small_cost.vm_steps * 2, (
        "superseded lookup scanned unrelated generation points: "
        f"{small_cost.vm_steps} instructions before growth, "
        f"{large_cost.vm_steps} after growth"
    )
