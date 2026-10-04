"""Checkpoint-scoped idle handles preserve WAL lifetime and release on every exit."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .._job_errors import JobError, JobErrorKind
from .._source_types import PublicSourceType
from ..indexer._run_checkpoint import CodeRunCheckpoint
from ..indexer._run_ledger_models import (
    RunAuthority,
    RunTerminalState,
    index_run_ledger_path,
    ledger_connection,
)
from ..indexer._run_ledger_runtime import RunLedger
from ..indexer._run_policy import RunPolicy
from ..job_control import (
    ControlRequest,
    RunControlSignal,
    RunControlToken,
)
from ._run_ledger_test_support import (
    ledger_test_publish_generation_with_proof,
    ledger_test_signature,
    ledger_test_unit,
)

if TYPE_CHECKING:
    from ..indexer._run_ledger_models import CommitUnit

pytestmark = [pytest.mark.unit]


def _checkpoint(root: Path, *, clean: bool = False) -> CodeRunCheckpoint:
    ledger = RunLedger(index_run_ledger_path(root))
    generation = ledger.start_generation(
        replace(ledger_test_signature(root), clean=clean)
    )
    return CodeRunCheckpoint(
        ledger,
        generation,
        None,
        RunPolicy(no_progress_timeout_seconds=60.0),
        RunAuthority.REBUILD,
        None,
    )


def _wal(checkpoint: CodeRunCheckpoint) -> Path:
    return Path(f"{checkpoint.ledger.path}-wal")


def _assert_released(checkpoint: CodeRunCheckpoint) -> None:
    assert not _wal(checkpoint).exists(), "checkpoint exit must release its idle handle"
    assert not Path(f"{checkpoint.ledger.path}-shm").exists()


def test_confirmed_writers_keep_wal_until_checkpoint_exit(tmp_path: Path) -> None:
    """Omitting the preservation context's idle handle removes WAL on writer close."""
    checkpoint = _checkpoint(tmp_path)
    units = tuple(ledger_test_unit("src/a.py", ordinal, 2) for ordinal in range(2))

    with checkpoint.preserve_incomplete_generation():
        for unit in units:
            assert checkpoint.ledger.record_storage_confirmed_unit(
                checkpoint.generation_id, unit
            )
            assert _wal(checkpoint).exists(), (
                "checkpoint lifetime must keep WAL after confirmed writer closes"
            )
        assert checkpoint.ledger.committed_unit_count(checkpoint.generation_id) == 2
        with ledger_connection(checkpoint.ledger.path) as connection:
            assert not connection.in_transaction
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
            assert connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 1000
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    _assert_released(checkpoint)
    assert all(
        checkpoint.ledger.unit_committed(checkpoint.generation_id, unit)
        for unit in units
    )


@pytest.mark.parametrize("clean", [False, True], ids=["incremental", "rebuild"])
def test_confirmed_failure_preserves_error_units_and_releases_handle(
    tmp_path: Path, clean: bool
) -> None:
    checkpoint = _checkpoint(tmp_path, clean=clean)
    unit = ledger_test_unit("src/failure.py", 0, 1)
    error = JobError(JobErrorKind.CHUNK_FAILED, "failure after confirmed unit")

    with pytest.raises(JobError) as caught, checkpoint.preserve_incomplete_generation():
        assert checkpoint.ledger.record_storage_confirmed_unit(
            checkpoint.generation_id, unit
        )
        assert _wal(checkpoint).exists()
        raise error

    assert caught.value is error
    _assert_released(checkpoint)
    expected = RunTerminalState.REBUILD_INCOMPLETE if clean else RunTerminalState.FAILED
    assert checkpoint.generation.terminal_state is expected
    assert (
        checkpoint.ledger.generation(checkpoint.generation_id).terminal_state
        is expected
    )
    assert checkpoint.ledger.unit_committed(checkpoint.generation_id, unit)


@pytest.mark.parametrize(
    "control_request",
    list(ControlRequest),
    ids=[value.value for value in ControlRequest],
)
def test_cooperative_unwind_releases_handle_and_retains_confirmed_work(
    tmp_path: Path, control_request: ControlRequest
) -> None:
    checkpoint = _checkpoint(tmp_path)
    token = RunControlToken()
    unit = ledger_test_unit("src/control.py", 0, 1)
    actions = {
        ControlRequest.PAUSE: token.request_pause,
        ControlRequest.CANCEL: token.request_cancel,
        ControlRequest.SHUTDOWN: token.request_shutdown,
        ControlRequest.QUIESCE: token.request_quiesce,
    }

    with (
        pytest.raises(RunControlSignal) as caught,
        checkpoint.preserve_incomplete_generation(),
    ):
        assert checkpoint.ledger.record_storage_confirmed_unit(
            checkpoint.generation_id, unit
        )
        assert _wal(checkpoint).exists()
        assert actions[control_request]()
        token.checkpoint()

    assert caught.value.request is control_request
    _assert_released(checkpoint)
    assert checkpoint.generation.terminal_state is RunTerminalState.FAILED
    assert checkpoint.ledger.unit_committed(checkpoint.generation_id, unit)


def test_late_failure_keeps_published_success_and_releases_handle(
    tmp_path: Path,
) -> None:
    checkpoint = _checkpoint(tmp_path)
    error = RuntimeError("failure after durable publication")

    with (
        pytest.raises(RuntimeError) as caught,
        checkpoint.preserve_incomplete_generation(),
    ):
        ledger_test_publish_generation_with_proof(
            checkpoint.ledger,
            checkpoint.generation_id,
        )
        checkpoint.generation = checkpoint.ledger.generation(checkpoint.generation_id)
        assert checkpoint.generation.terminal_state is RunTerminalState.SUCCEEDED
        assert _wal(checkpoint).exists()
        raise error

    assert caught.value is error
    _assert_released(checkpoint)
    assert checkpoint.generation.terminal_state is RunTerminalState.SUCCEEDED
    assert (
        checkpoint.ledger.generation(checkpoint.generation_id) == checkpoint.generation
    )


def test_idle_handle_allows_other_source_writer_transactions(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)
    document = checkpoint.ledger.start_generation(
        replace(
            ledger_test_signature(tmp_path),
            source_type=PublicSourceType.DOCUMENT,
            collection_identity="document-v1",
        )
    )
    barrier = threading.Barrier(3)
    code_units = tuple(ledger_test_unit("src/code.py", i, 3) for i in range(3))
    doc_units = tuple(ledger_test_unit("doc/a.md", i, 3) for i in range(3))

    def write(generation_id: str, units: tuple[CommitUnit, ...]) -> int:
        barrier.wait(timeout=30.0)
        ledger = RunLedger(checkpoint.ledger.path)
        return ledger.record_storage_confirmed_units(generation_id, units)

    with checkpoint.preserve_incomplete_generation():
        with ThreadPoolExecutor(max_workers=2) as workers:
            code = workers.submit(write, checkpoint.generation_id, code_units)
            doc = workers.submit(write, document.generation_id, doc_units)
            barrier.wait(timeout=30.0)
            assert code.result(timeout=60.0) == 3
            assert doc.result(timeout=60.0) == 3
        assert _wal(checkpoint).exists()
        assert checkpoint.ledger.committed_unit_count(checkpoint.generation_id) == 3
        assert checkpoint.ledger.committed_unit_count(document.generation_id) == 3

    _assert_released(checkpoint)
    assert all(
        checkpoint.ledger.unit_committed(document.generation_id, unit)
        for unit in doc_units
    )


def test_idle_handle_allows_default_wal_recycling(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)
    checkpoint_sequences: set[int] = set()
    max_wal_bytes = 0

    with checkpoint.preserve_incomplete_generation():
        for ordinal in range(240):
            unit = ledger_test_unit(f"src/file-{ordinal // 6}.py", ordinal % 6, 6)
            assert checkpoint.ledger.record_storage_confirmed_unit(
                checkpoint.generation_id, unit
            )
            with _wal(checkpoint).open("rb") as handle:
                header = handle.read(16)
            checkpoint_sequences.add(int.from_bytes(header[12:16], "big"))
            max_wal_bytes = max(max_wal_bytes, _wal(checkpoint).stat().st_size)
        assert len(checkpoint_sequences) > 1, (
            "idle handle must allow automatic WAL reset"
        )
        assert max_wal_bytes < 32 + 2000 * (4096 + 24)
        assert checkpoint.ledger.committed_unit_count(checkpoint.generation_id) == 240

    _assert_released(checkpoint)
