"""Acknowledged chunk work is independent of CODE's completed-file display."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, cast

import pytest

from .. import _job_progress
from .._job_errors import STALL_THRESHOLD_SECONDS
from ..job_models import JobSource
from ..jobs import JobProgressReporter, record_finish, record_start, reset, snapshot
from ..server._routes_jobs import _job_summary, _job_with_liveness

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from types import FrameType

pytestmark = [pytest.mark.unit]


@dataclass
class _Clock:
    at: float = 1000.0

    def time(self) -> float:
        return self.at


@pytest.fixture
def clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Clock]:
    from ._config_fixtures import reset_config

    monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
    reset_config()
    reset()
    timer = _Clock()
    monkeypatch.setattr(_job_progress, "time", timer)
    yield timer
    reset()
    reset_config()


def _reporter(source: JobSource = JobSource.CODE) -> JobProgressReporter:
    job_id = record_start(source, "tool", command="reindex_codebase")
    reporter = JobProgressReporter(job_id)
    reporter.phase_start("chunk + embed", 2000)
    return reporter


def _record(reporter: JobProgressReporter) -> dict[str, object]:
    return next(record for record in snapshot() if record["id"] == reporter.record_id)


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _cadence(
    reporter: JobProgressReporter,
    clock: _Clock,
    *,
    unequal_files: bool,
    chunk_rate: int | None = 32,
) -> dict[str, object]:
    """Replay actual reporter events with a known chunk and file denominator."""
    for second in range(1, 421):
        clock.at = 1000.0 + second
        if chunk_rate is not None:
            reporter.confirmed_chunks(32 if second <= 300 else chunk_rate)
        if second <= 300 or not unequal_files:
            reporter.advance(3)
        elif second % 10 == 0:
            reporter.advance(1)
    return _job_with_liveness(_record(reporter), now=clock.at + 1.0)


@pytest.mark.parametrize("unequal_files", [False, True], ids=["uniform", "unequal"])
def test_equal_chunk_work_has_equal_health_despite_file_sizes(
    clock: _Clock, unequal_files: bool
) -> None:
    reporter = _reporter()
    shaped = _cadence(reporter, clock, unequal_files=unequal_files)
    assert shaped["degradation"] == "healthy", (
        "equal confirmed chunk throughput was classified by file cadence"
    )
    work = _mapping(shaped["confirmed_chunk_progress"])
    baseline = _mapping(shaped["confirmed_chunk_rate_baseline"])
    assert work["completed"] == 420 * 32
    assert work["unit"] == baseline["unit"] == "confirmed_chunks"
    assert baseline["recent_per_second"] == pytest.approx(32.0)
    assert baseline["median_per_second"] == pytest.approx(32.0)
    assert baseline["ratio"] == pytest.approx(1.0)
    assert shaped["degradation_rate_unit"] == "confirmed_chunks"
    # File display, its original window and ETA keep their own denominator.
    file_rate = _mapping(shaped["progress_rate_baseline"])
    progress = _mapping(shaped["progress"])
    assert progress["completed"] == (912 if unequal_files else 1260)
    assert shaped["progress_rate_per_second"] == file_rate["recent_per_second"]
    if unequal_files:
        assert cast("float", file_rate["ratio"]) < 0.25
    assert _job_summary([_record(reporter)], now=clock.at + 1.0)["degraded"] == 0


def test_unknown_chunk_rate_does_not_fall_back_to_code_file_rate(clock: _Clock) -> None:
    reporter = _reporter()
    shaped = _cadence(reporter, clock, unequal_files=True, chunk_rate=None)
    assert cast("float", _mapping(shaped["progress_rate_baseline"])["ratio"]) < 0.25
    assert shaped["degradation"] == "healthy", "unknown CODE work used file collapse"
    baseline = _mapping(shaped["confirmed_chunk_rate_baseline"])
    assert baseline == {
        "unit": "confirmed_chunks",
        "recent_per_second": None,
        "median_per_second": None,
        "ratio": None,
    }


def test_real_chunk_collapse_drives_detail_evidence_and_summary(clock: _Clock) -> None:
    reporter = _reporter()
    shaped = _cadence(reporter, clock, unequal_files=False, chunk_rate=3)
    assert shaped["degradation"] == "degraded", "confirmed chunk collapse was ignored"
    baseline = _mapping(shaped["confirmed_chunk_rate_baseline"])
    assert baseline["recent_per_second"] == pytest.approx(3.0)
    assert baseline["median_per_second"] == pytest.approx(32.0)
    assert cast("float", baseline["ratio"]) < 0.25
    evidence = _mapping(_mapping(shaped["degradation_evidence"])["rate"])
    assert evidence == {key: value for key, value in baseline.items() if key != "unit"}
    summary = _job_summary([_record(reporter)], now=clock.at + 1.0)
    assert summary["degraded"] == 1, "summary ignored confirmed chunk collapse"
    assert summary["stalled"] == 0


def test_detail_uses_one_immutable_acknowledged_work_snapshot(clock: _Clock) -> None:
    reporter = _reporter()
    _cadence(reporter, clock, unequal_files=False)
    captured: list[int] = []

    def observe(frame: FrameType, event: str, _argument: object) -> None:
        if (
            frame.f_code is _job_progress.confirmed_chunk_progress.__code__
            and event == "return"
        ):
            captured.append(1)
            # The writer advances as soon as the real read releases its lock.
            # Classification must use that captured snapshot throughout.
            clock.at += 1.0
            reporter.confirmed_chunks(100)

    previous = sys.getprofile()
    sys.setprofile(observe)
    try:
        shaped = _job_with_liveness(_record(reporter), now=1421.0)
    finally:
        sys.setprofile(previous)
    assert len(captured) == 1, (
        "projection read more than one acknowledged work snapshot"
    )
    work = _mapping(shaped["confirmed_chunk_progress"])
    baseline = _mapping(shaped["confirmed_chunk_rate_baseline"])
    assert work["completed"] == 13440
    assert baseline["recent_per_second"] == pytest.approx(32.0)
    assert (
        _mapping(_job_progress.confirmed_chunk_progress(reporter.record_id))[
            "completed"
        ]
        == 13540
    )


def test_other_source_keeps_existing_phase_rate_semantics(clock: _Clock) -> None:
    reporter = _reporter(JobSource.DOCUMENT)
    shaped = _cadence(reporter, clock, unequal_files=True, chunk_rate=None)
    assert shaped["degradation"] == "degraded"
    assert shaped["confirmed_chunk_progress"] is None
    assert shaped["confirmed_chunk_rate_baseline"] is None
    assert shaped["degradation_rate_unit"] == "phase_items"


def test_fresh_acknowledgements_keep_oversized_file_live_without_file_ticks(
    clock: _Clock,
) -> None:
    reporter = _reporter()
    reporter.forward_started(ordinal=0, items=10)
    reporter.forward_finished(ordinal=0, items=10)
    clock.at += STALL_THRESHOLD_SECONDS + 100.0
    reporter.confirmed_chunks(10)
    clock.at += 10.0
    reporter.confirmed_chunks(10)
    shaped = _job_with_liveness(_record(reporter), now=clock.at + 1.0)
    assert shaped["stalled"] is False, "fresh chunk acknowledgement falsely stalled"
    assert shaped["degradation"] == "healthy", "fresh acknowledgement recency ignored"
    assert shaped["last_progress_age_seconds"] == STALL_THRESHOLD_SECONDS + 111.0
    assert _mapping(shaped["progress"])["completed"] == 0
    assert _mapping(shaped["progress"])["last_updated"] == 1000.0
    assert _mapping(shaped["confirmed_chunk_progress"])["last_updated"] == clock.at
    summary = _job_summary([_record(reporter)], now=clock.at + 1.0)
    assert summary["stalled"] == summary["degraded"] == 0


@pytest.mark.parametrize("acknowledged", [False, True], ids=["no-ack", "old-ack"])
def test_old_or_absent_acknowledgements_preserve_stall_threshold(
    clock: _Clock, acknowledged: bool
) -> None:
    reporter = _reporter()
    if acknowledged:
        reporter.confirmed_chunks(10)
    before = _job_with_liveness(
        _record(reporter), now=clock.at + STALL_THRESHOLD_SECONDS - 0.01
    )
    at = _job_with_liveness(_record(reporter), now=clock.at + STALL_THRESHOLD_SECONDS)
    assert before["stalled"] is False
    assert before["degradation"] == "degraded"
    assert at["stalled"] is True, "public stall boundary changed"
    assert at["degradation"] == "stalled"


def test_phase_reset_and_late_reporter_cannot_reuse_work_history(clock: _Clock) -> None:
    old = _reporter()
    _cadence(old, clock, unequal_files=False)
    current = JobProgressReporter(old.record_id)
    current.phase_start("chunk + embed", 2000)
    old.confirmed_chunks(999)
    work = _job_progress.confirmed_chunk_progress(old.record_id)
    assert work is not None
    assert work["completed"] == 0, "old phase owner changed resumed work"
    assert work["recent_per_second"] is work["median_per_second"] is None
    assert work["last_updated"] is None
    current.confirmed_chunks(5)
    current.phase_end()
    current.confirmed_chunks(999)
    assert (
        _mapping(_job_progress.confirmed_chunk_progress(old.record_id))["completed"]
        == 5
    )
    current.phase_start("write metadata", None)
    assert (
        _mapping(_job_progress.confirmed_chunk_progress(old.record_id))["completed"]
        == 0
    )


def test_terminal_and_zero_work_cannot_advance_chunk_count(clock: _Clock) -> None:
    clock.at += 1.0
    reporter = _reporter()
    reporter.confirmed_chunks(0)
    assert (
        _mapping(_job_progress.confirmed_chunk_progress(reporter.record_id))[
            "last_updated"
        ]
        is None
    )
    record_finish(reporter.record_id, result="0")
    reporter.confirmed_chunks(99)
    assert (
        _mapping(_job_progress.confirmed_chunk_progress(reporter.record_id))[
            "completed"
        ]
        == 0
    )


def test_private_chunk_sampling_never_leaks_into_json_snapshot(clock: _Clock) -> None:
    clock.at += 1.0
    reporter = _reporter()
    reporter.confirmed_chunks(10)
    entries = snapshot()
    assert _job_progress.CONFIRMED_CHUNK_SAMPLING_KEY not in _record(reporter), (
        "private chunk sampler leaked into persisted projection"
    )
    json.dumps(entries, allow_nan=False)


async def test_managed_resume_refuses_old_attempt_before_new_phase_starts(
    clock: _Clock, tmp_path: Path
) -> None:
    from ..indexer._run_ledger_models import RunAuthority
    from ..job_control import RunControlToken
    from ..job_manager._control import AttemptTerminal
    from ..job_manager.models import JobAttemptContext
    from ..job_models import DesiredJobState, JobState
    from ._job_manager_transition_helpers import pending_attempt
    from .test_job_progress_durability import _started_manager

    tasks = [asyncio.create_task(pending_attempt()) for _ in range(2)]
    try:
        manager, job_id = _started_manager(
            tmp_path / "managed.json", str(tmp_path), tasks[0]
        )
        record_start(JobSource.CODE, "tool", _record_id=job_id)
        old = JobProgressReporter(
            job_id,
            context=JobAttemptContext(
                manager,
                job_id,
                1,
                tasks[0],
                RunControlToken(),
                RunAuthority.PUBLICATION,
            ),
        )
        old.phase_start("chunk + embed", 10)
        clock.at += 1.0
        old.confirmed_chunks(10)
        manager.set_desired_state(job_id, DesiredJobState.PAUSED)
        # No worker or store resources are held by this isolated task, so
        # canonical acknowledgement completes its requested pause directly.
        assert (
            manager.acknowledge_control(job_id, attempt=1, task=tasks[0]).job
            is not None
        )
        old.confirmed_chunks(99)
        assert (
            _mapping(_job_progress.confirmed_chunk_progress(job_id))["completed"] == 10
        ), "paused managed attempt changed chunk work"
        assert (
            manager.set_desired_state(job_id, DesiredJobState.RUNNING).job is not None
        )
        assert (
            manager.start_attempt(job_id, task=tasks[1], control=RunControlToken()).job
            is not None
        )
        # The activity record still carries the old phase owner. Only the
        # canonical attempt fence can refuse this late acknowledgement.
        old.confirmed_chunks(99)
        assert (
            _mapping(_job_progress.confirmed_chunk_progress(job_id))["completed"] == 10
        ), "old managed attempt changed resumed chunk work"
        current = JobProgressReporter(
            job_id,
            context=JobAttemptContext(
                manager,
                job_id,
                2,
                tasks[1],
                RunControlToken(),
                RunAuthority.PUBLICATION,
            ),
        )
        current.phase_start("chunk + embed", 10)
        old.phase_start("chunk + embed", 10)
        clock.at += 1.0
        current.confirmed_chunks(3)
        assert (
            _mapping(_job_progress.confirmed_chunk_progress(job_id))["completed"] == 3
        ), "stale phase start reset the current chunk sampler"
        assert (
            manager.finish_attempt(
                job_id,
                AttemptTerminal(attempt=2, task=tasks[1], state=JobState.SUCCEEDED),
            ).job
            is not None
        )
        current.confirmed_chunks(99)
        assert (
            _mapping(_job_progress.confirmed_chunk_progress(job_id))["completed"] == 3
        ), "terminal managed attempt changed chunk work"
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with pytest.raises(asyncio.CancelledError):
                await task


def test_publication_rollback_preserves_elapsed_acknowledged_work(
    clock: _Clock, tmp_path: Path
) -> None:
    from ..indexer._publication_proof import ProofReceiptState
    from ..indexer._streaming import execute_store_mutation
    from ..indexer._streaming_types import StoreMutationLifecycle
    from ._run_ledger_test_support import (
        ledger_test_seeded_publication_lineage,
        ledger_test_unit,
    )

    reporter = _reporter()
    ledger, key, _parent_id, successor_id = ledger_test_seeded_publication_lineage(
        tmp_path / "publication", ()
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor_id,
        expected_parent_revision=ledger.publication_proof(key).revision,
    )
    unit = ledger_test_unit("pkg/a.py", 0, 3)
    stored: set[str] = set()

    def prepare() -> bool:
        ledger.prepare_publication_mutation(receipt.receipt_id, unit)
        return True

    def mark_applied() -> None:
        ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)

    def confirm() -> None:
        ledger.confirm_publication_mutation(receipt.receipt_id, unit)

    clock.at += 1.0
    execute_store_mutation(
        partial(stored.update, unit.point_ids),
        StoreMutationLifecycle(
            prepare, mark_applied, confirm, confirm_when_stored=True
        ),
        after_acknowledgement=partial(reporter.confirmed_chunks, len(unit.point_ids)),
    )
    before = _job_progress.confirmed_chunk_progress(reporter.record_id)
    assert before is not None and before["completed"] == len(unit.point_ids)
    ledger.begin_publication_rollback(receipt.receipt_id)
    # Compensation is storage work, not a new consumer chunk acknowledgement.
    stored.clear()
    rolled_back = ledger.roll_back_publication_receipt(
        receipt.receipt_id, compensated_units=(unit,)
    )
    assert rolled_back.state is ProofReceiptState.ROLLED_BACK
    assert _job_progress.confirmed_chunk_progress(reporter.record_id) == before, (
        "publication rollback erased or counted elapsed acknowledged work"
    )
    reporter.phase_start("chunk + embed", 1)
    assert (
        _mapping(_job_progress.confirmed_chunk_progress(reporter.record_id))[
            "completed"
        ]
        == 0
    )


async def test_managed_root_status_uses_the_same_acknowledgement_recency(
    clock: _Clock, tmp_path: Path
) -> None:
    from ..indexer._run_ledger_models import RunAuthority
    from ..job_control import RunControlToken
    from ..job_manager._control import AttemptTerminal
    from ..job_manager.models import JobAttemptContext
    from ..job_models import JobState
    from ..jobs import index_job_status
    from ._job_manager_transition_helpers import pending_attempt
    from .test_job_progress_durability import _started_manager

    task = asyncio.create_task(pending_attempt())
    manager, job_id = _started_manager(tmp_path / "root-jobs.json", str(tmp_path), task)
    try:
        record_start(JobSource.CODE, "tool", _record_id=job_id)
        reporter = JobProgressReporter(
            job_id,
            context=JobAttemptContext(
                manager, job_id, 1, task, RunControlToken(), RunAuthority.PUBLICATION
            ),
        )
        reporter.phase_start("chunk + embed", 1)
        started = manager.get(job_id)
        assert started is not None and started.progress is not None
        clock.at = started.progress.last_updated + STALL_THRESHOLD_SECONDS + 100.0
        without_ack = index_job_status(tmp_path, manager=manager, now=clock.at)
        assert _mapping(_mapping(without_ack["sources"])["code"])["stalled"] is True
        reporter.confirmed_chunks(10)
        fresh = index_job_status(tmp_path, manager=manager, now=clock.at + 1.0)
        code = _mapping(_mapping(fresh["sources"])["code"])
        assert code["stalled"] is False, (
            "root status ignored fresh chunk acknowledgement"
        )
        assert fresh["degraded_reasons"] == []
        assert _mapping(code["confirmed_chunk_progress"])["completed"] == 10
        observed = manager.get(job_id)
        assert observed is not None and observed.progress == started.progress
        old = index_job_status(
            tmp_path, manager=manager, now=clock.at + STALL_THRESHOLD_SECONDS
        )
        assert _mapping(_mapping(old["sources"])["code"])["stalled"] is True
        assert old["degraded_reasons"] == [
            {
                "source": "code",
                "job_id": job_id,
                "reason": "stalled",
                "error_kind": None,
            }
        ]
    finally:
        manager.finish_attempt(
            job_id, AttemptTerminal(attempt=1, task=task, state=JobState.SUCCEEDED)
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
