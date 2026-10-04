"""Replay preserves exact file outcomes without rewriting identical rows."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import pytest

from ..indexer import _run_ledger_models
from ..indexer._content_policy import AdmissionDisposition, AdmissionReason, ContentKind
from ..indexer._file_state import FileState, FileStateKind
from ..indexer._run_ledger_models import (
    FinalizationPhase,
    RunLedgerStateError,
    RunTerminalState,
    ledger_connection,
)
from ..indexer._run_ledger_runtime import RunLedger
from ._run_ledger_test_support import (
    ledger_test_digest,
    ledger_test_signature,
    ledger_test_unit,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Generator
    from pathlib import Path

pytestmark = pytest.mark.unit


@dataclass(slots=True)
class _WriteCost:
    changed_rows: int = 0
    connections: int = 0
    statements: list[str] = field(default_factory=list)


@contextmanager
def _measured_writes(monkeypatch: pytest.MonkeyPatch) -> Generator[_WriteCost]:
    """Count actual transaction changes through the canonical connection owner."""
    cost = _WriteCost()
    original = _run_ledger_models.ledger_connection

    @contextmanager
    def measured(path: Path) -> Generator[sqlite3.Connection]:
        with original(path) as connection:
            cost.connections += 1
            before = connection.total_changes
            connection.set_trace_callback(cost.statements.append)
            try:
                yield connection
            finally:
                cost.changed_rows += connection.total_changes - before

    with monkeypatch.context() as probe:
        probe.setattr(_run_ledger_models, "ledger_connection", measured)
        yield cost


def _seed_indexed_path(ledger: RunLedger, generation_id: str) -> FileState:
    path = "src/confirmed.py"
    unit = ledger_test_unit(path, 0, 1)
    ledger.record_storage_confirmed_unit(generation_id, unit)
    state = FileState.indexed(path, ContentKind.CODE, ledger_test_digest(path))
    ledger.record_file_state(generation_id, state)
    return state


def test_unchanged_indexed_replay_changes_no_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitting the production upsert WHERE fails the zero-change assertion.

    A fresh process with the predicate restored passes; mutation changes only
    the method in memory and restores it before that process exits.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    states: list[FileState] = []
    for index in range(20):
        path = f"src/file-{index:03d}.py"
        ledger.record_storage_confirmed_units(
            generation.generation_id,
            tuple(ledger_test_unit(path, ordinal, 6) for ordinal in range(6)),
        )
        state = FileState.indexed(path, ContentKind.CODE, ledger_test_digest(path))
        ledger.record_file_state(generation.generation_id, state)
        states.append(state)

    with _measured_writes(monkeypatch) as cost:
        for state in states:
            ledger.record_file_state(generation.generation_id, state)

    assert cost.connections == len(states), "replay transactions were not measured"
    assert cost.statements.count("BEGIN IMMEDIATE") == len(states)
    assert cost.changed_rows == 0, "unchanged indexed replay rewrote persisted rows"
    assert ledger.file_states_for_paths(
        generation.generation_id, tuple(state.rel_path for state in states)
    ) == {state.rel_path: state for state in states}


def test_processing_outcomes_insert_and_update_nullable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    failed = FileState.failed(
        "src/unreadable.py",
        FileStateKind.DECODE_FAILED,
        ContentKind.CODE,
        "decode failed",
    )
    hashed = replace(failed, content_hash=ledger_test_digest("readable bytes"))
    changed_detail = replace(hashed, detail="different decode failure")
    chunk_failed = FileState.failed(
        failed.rel_path, FileStateKind.CHUNK_FAILED, ContentKind.CODE, "chunk failed"
    )
    for state in (failed, hashed, changed_detail, failed, chunk_failed):
        with _measured_writes(monkeypatch) as cost:
            ledger.record_file_state(generation.generation_id, state)
        assert cost.changed_rows == 1
        assert ledger.file_states_for_paths(
            generation.generation_id, (state.rel_path,)
        ) == {state.rel_path: state}

    with _measured_writes(monkeypatch) as cost:
        ledger.record_file_state(generation.generation_id, chunk_failed)
    assert cost.changed_rows == 0


def test_reclassification_updates_rejection_reason_and_nullable_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    ignored = FileState.policy_rejected(
        "src/ignored.py",
        AdmissionDisposition(kind=None, admitted=False, reason=AdmissionReason.IGNORED),
    )
    unrouted = replace(ignored, admission_reason=AdmissionReason.NOT_ROUTED)
    routed = replace(unrouted, kind=ContentKind.CODE)
    for state in (ignored, unrouted, routed, unrouted):
        with _measured_writes(monkeypatch) as cost:
            ledger.record_file_state(generation.generation_id, state)
        assert cost.changed_rows == 1
        assert ledger.file_states_for_paths(
            generation.generation_id, (state.rel_path,)
        ) == {state.rel_path: state}


def test_confirmed_indexing_replaces_a_failure_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    indexed = _seed_indexed_path(ledger, generation.generation_id)
    failed = FileState.failed(
        indexed.rel_path,
        FileStateKind.EXTRACT_RETRYABLE,
        ContentKind.CODE,
        "extractor unavailable",
        content_hash=indexed.content_hash,
    )
    ledger.record_file_state(generation.generation_id, failed)
    with _measured_writes(monkeypatch) as cost:
        ledger.record_file_state(generation.generation_id, indexed)
    assert cost.changed_rows == 1
    assert ledger.file_states_for_paths(
        generation.generation_id, (indexed.rel_path,)
    ) == {indexed.rel_path: indexed}


def test_identical_outcome_promotes_inherited_evidence_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = ledger_test_signature(tmp_path)
    parent = ledger.start_generation(signature)
    state = _seed_indexed_path(ledger, parent.generation_id)
    current = ledger.start_generation(
        replace(signature, content_epoch="current-content")
    )
    _seed_indexed_path(ledger, current.generation_id)
    # Carried state may still name the earlier generation that owned its evidence.
    with ledger_connection(ledger.path) as connection:
        connection.execute(
            "UPDATE file_states SET evidence_generation_id = ? WHERE generation_id = ?",
            (parent.generation_id, current.generation_id),
        )
        connection.commit()

    with _measured_writes(monkeypatch) as cost:
        ledger.record_file_state(current.generation_id, state)
    assert cost.changed_rows == 1
    with ledger_connection(ledger.path) as connection:
        assert (
            connection.execute(
                "SELECT evidence_generation_id FROM file_states "
                "WHERE generation_id = ?",
                (current.generation_id,),
            ).fetchone()[0]
            == current.generation_id
        )


def test_identical_state_still_clears_its_tombstone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    state = _seed_indexed_path(ledger, generation.generation_id)
    with ledger_connection(ledger.path) as connection:
        connection.execute(
            "INSERT INTO file_state_tombstones (generation_id, rel_path) VALUES (?, ?)",
            (generation.generation_id, state.rel_path),
        )
        connection.commit()

    with _measured_writes(monkeypatch) as cost:
        ledger.record_file_state(generation.generation_id, state)
    assert cost.changed_rows == 1  # Only the tombstone is deleted.
    with ledger_connection(ledger.path) as connection:
        assert not connection.execute(
            "SELECT 1 FROM file_state_tombstones "
            "WHERE generation_id = ? AND rel_path = ?",
            (generation.generation_id, state.rel_path),
        ).fetchone()
    assert ledger.file_states_for_paths(
        generation.generation_id, (state.rel_path,)
    ) == {state.rel_path: state}


@pytest.mark.parametrize("invalid", ["completion", "hash", "finalizing", "terminal"])
def test_identical_state_does_not_bypass_authority_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    state = _seed_indexed_path(ledger, generation.generation_id)
    if invalid == "completion":
        with ledger_connection(ledger.path) as connection:
            connection.execute(
                "DELETE FROM commit_units WHERE generation_id = ?",
                (generation.generation_id,),
            )
            connection.commit()
        message = "indexed file state requires every storage-confirmed segment"
    elif invalid == "hash":
        state = replace(state, content_hash=ledger_test_digest("wrong-content"))
        with ledger_connection(ledger.path) as connection:
            connection.execute(
                "UPDATE file_states SET content_hash = ? WHERE generation_id = ?",
                (state.content_hash, generation.generation_id),
            )
            connection.commit()
        message = "indexed file hash differs from storage-confirmed units"
    elif invalid == "finalizing":
        ledger.advance_finalization(
            generation.generation_id, FinalizationPhase.STALE_RECONCILED
        )
        message = "cannot change file state after finalization begins"
    else:
        ledger.finish_generation(generation.generation_id, RunTerminalState.CANCELLED)
        message = "terminal generations are immutable"

    with (
        _measured_writes(monkeypatch) as cost,
        pytest.raises(RunLedgerStateError, match=f"^{message}$"),
    ):
        ledger.record_file_state(generation.generation_id, state)
    assert cost.changed_rows == 0
