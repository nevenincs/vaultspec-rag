"""Real SQLite behavior for resumable indexing generations."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from ..indexer._content_policy import AdmissionDisposition, AdmissionReason, ContentKind
from ..indexer._file_state import FileState, FileStateKind
from ..indexer._run_ledger import (
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    RunLedger,
    RunLedgerCompatibilityError,
    RunLedgerCorruptionError,
    RunLedgerStateError,
    RunOperation,
    RunSignature,
    RunTerminalState,
)

if TYPE_CHECKING:
    from pathlib import Path


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

    deletion = CommitUnit(
        rel_path="src/removed.py",
        kind=CommitUnitKind.DELETE,
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
    for state in (indexed, rejected, failed):
        ledger.record_file_state(generation.generation_id, state)

    assert list(ledger.iter_file_states(generation.generation_id, batch_size=1)) == [
        rejected,
        failed,
        indexed,
    ]
    assert list(
        ledger.iter_file_states(generation.generation_id, converged_only=True)
    ) == [rejected, indexed]

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
