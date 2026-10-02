"""Run-ledger generations behavior."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from .._source_types import PublicSourceType
from ..indexer._content_policy import AdmissionDisposition, AdmissionReason, ContentKind
from ..indexer._file_state import FileState, FileStateKind
from ..indexer._run_ledger_models import (
    INDEX_RUN_LEDGER_FILENAME,
    RESUMABLE_STATES,
    FinalizationPhase,
    RunLedgerStateError,
    RunOperation,
    RunTerminalState,
    index_run_ledger_path,
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


def test_backend_identity_is_part_of_manifest_compatibility(tmp_path: Path) -> None:
    server = ledger_test_signature(tmp_path)
    local = ledger_test_signature(
        tmp_path,
        backend_identity=f"qdrant-local:{tmp_path.resolve()}",
    )

    assert server.content_compatibility_fingerprint != (
        local.content_compatibility_fingerprint
    )


def test_generation_transactions_resume_and_invalidate_drift(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "index" / "runs.sqlite3")
    signature = ledger_test_signature(tmp_path)

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

    unit = ledger_test_unit("src/resume.py", 0, 1)
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
    code = ledger.start_generation(ledger_test_signature(tmp_path))
    document = ledger.start_generation(
        replace(
            ledger_test_signature(tmp_path),
            source_type=PublicSourceType.DOCUMENT,
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


def test_file_outcomes_and_finalization_are_immutable(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    indexed = FileState.indexed(
        "src/good.py", ContentKind.CODE, ledger_test_digest("good")
    )
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
        content_hash=ledger_test_digest("bad"),
    )
    with pytest.raises(RunLedgerStateError, match="storage-confirmed"):
        ledger.record_file_state(generation.generation_id, indexed)
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        ledger_test_unit("src/good.py", 0, 1, digest=indexed.content_hash),
    )
    wrong_hash = replace(indexed, content_hash=ledger_test_digest("different-good"))
    with pytest.raises(RunLedgerStateError, match="hash differs"):
        ledger.record_file_state(generation.generation_id, wrong_hash)
    for state in (indexed, rejected, failed):
        ledger.record_file_state(generation.generation_id, state)
    good_point_ids = ledger_test_unit(
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
            ledger_test_unit("src/good.py", 1, 2, digest=indexed.content_hash),
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
        ledger_test_unit("src/bad.py", 0, 1, digest=failed.content_hash),
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
    signature = replace(
        ledger_test_signature(tmp_path), operation=RunOperation.INCREMENTAL
    )
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
    generation = ledger.start_generation(ledger_test_signature(tmp_path))
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(generation.generation_id, phase)
    ledger.finish_generation(generation.generation_id, RunTerminalState.SUCCEEDED)

    with closing(sqlite3.connect(tmp_path / "runs.sqlite3")) as connection, connection:
        failures = connection.execute(
            "SELECT consecutive_failures FROM generations WHERE generation_id = ?",
            (generation.generation_id,),
        ).fetchone()[0]
    assert int(failures) == 0
