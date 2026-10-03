"""Real thread, queue, timing, and control tests for index run policy."""

from __future__ import annotations

import threading
import time

import pytest

from .._job_errors import JobError, JobErrorKind
from ..indexer._run_policy import (
    DurableProgressKind,
    RunPolicy,
    ThreadWaitOutcome,
)
from ..job_control import CancelRequested, RunControlToken

pytestmark = [pytest.mark.unit]

_THREAD_TIMEOUT_SECONDS = 2.0


def _join_thread(thread: threading.Thread) -> None:
    thread.join(timeout=_THREAD_TIMEOUT_SECONDS)
    assert not thread.is_alive(), f"worker {thread.name!r} did not stop"


def test_no_progress_expiry_is_typed_latched_and_visible() -> None:
    policy = RunPolicy(no_progress_timeout_seconds=0.08)
    started = time.monotonic()

    with pytest.raises(JobError) as first:
        policy.wait(1.0)
    elapsed = time.monotonic() - started

    assert first.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
    assert 0.05 <= elapsed < 1.0
    with pytest.raises(JobError) as second:
        policy.remaining_seconds()
    assert second.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
    assert second.value.detail == first.value.detail

    snapshot = policy.snapshot()
    assert snapshot.expired is True
    assert snapshot.remaining_seconds == 0.0
    assert snapshot.durable_progress_count == 0


def test_durable_commits_extend_a_long_healthy_run_but_other_checks_do_not() -> None:
    # Each step spends 40% of the window, so the run outlasts the window only
    # because commits extend it, while a host stall of up to 0.3s inside one
    # step still cannot expire a healthy run on its own.
    window = 0.5
    policy = RunPolicy(no_progress_timeout_seconds=window)
    started = time.monotonic()

    for ordinal in range(4):
        policy.wait(window * 0.4)
        snapshot = policy.record_durable_progress(
            kind=DurableProgressKind.LEDGER_UNIT_COMMITTED,
            label=f"segment-{ordinal}",
        )
        assert snapshot.durable_progress_count == ordinal + 1

    assert time.monotonic() - started > window
    policy.checkpoint("ordinary pipeline motion")

    with pytest.raises(JobError) as expired:
        policy.wait(window * 2)
    assert expired.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
    final = policy.snapshot()
    assert final.durable_progress_count == 4
    assert final.last_progress_kind is DurableProgressKind.LEDGER_UNIT_COMMITTED
    assert final.last_progress_label == "segment-3"


def test_interruptible_wait_delivers_real_cross_thread_control() -> None:
    control = RunControlToken()
    policy = RunPolicy(
        no_progress_timeout_seconds=5.0,
        run_control=control,
    )
    entered = threading.Event()
    outcomes: list[BaseException] = []

    def run_wait() -> None:
        entered.set()
        try:
            policy.wait(5.0)
        except BaseException as exc:
            outcomes.append(exc)

    worker = threading.Thread(target=run_wait, name="run-policy-control-wait")
    worker.start()
    assert entered.wait(timeout=_THREAD_TIMEOUT_SECONDS)
    assert control.request_cancel() is True
    _join_thread(worker)

    assert len(outcomes) == 1
    assert isinstance(outcomes[0], CancelRequested)


def test_protected_span_defers_control_until_its_durable_exit() -> None:
    control = RunControlToken()
    policy = RunPolicy(
        no_progress_timeout_seconds=5.0,
        run_control=control,
    )

    with (
        pytest.raises(CancelRequested),
        policy.protected("storage-confirmed replacement"),
    ):
        assert control.request_cancel()
        snapshot = control.snapshot()
        assert snapshot.delivered is None
        assert snapshot.protected_depth == 1

    final = control.snapshot()
    assert final.delivered is not None
    assert final.protected_depth == 0


def test_thread_join_reports_exit_and_hard_cleanup_timeout() -> None:
    release = threading.Event()
    worker = threading.Thread(
        target=release.wait,
        name="run-policy-cleanup-worker",
    )
    worker.start()
    policy = RunPolicy(no_progress_timeout_seconds=0.02)

    try:
        assert (
            policy.join_thread(
                worker,
                timeout_seconds=0.06,
                label="consumer cleanup",
            )
            is ThreadWaitOutcome.TIMED_OUT
        )
        assert worker.is_alive()
        release.set()
        assert (
            policy.join_thread(
                worker,
                timeout_seconds=1.0,
                label="consumer cleanup",
            )
            is ThreadWaitOutcome.EXITED
        )
    finally:
        release.set()
        _join_thread(worker)


def test_store_write_capability_uses_the_same_policy_clock() -> None:
    # The window only has to outlast one short wait; a wide one keeps a host
    # stall from expiring the policy before progress is recorded.
    window = 1.0
    policy = RunPolicy(no_progress_timeout_seconds=window)
    capability = policy.store_write_policy

    assert capability is policy.store_write_policy
    assert 0.0 < capability.remaining_seconds() <= window
    capability.wait(0.03)
    before = capability.remaining_seconds()
    policy.record_durable_progress(
        kind=DurableProgressKind.FINALIZATION_PHASE_COMMITTED,
        label="metadata-published",
    )
    after = capability.remaining_seconds()

    assert after > before


@pytest.mark.parametrize(
    "value",
    [0.0, -1.0, float("nan"), float("inf"), True],
)
def test_run_policy_rejects_invalid_deadlines(value: float) -> None:
    with pytest.raises(ValueError):
        RunPolicy(no_progress_timeout_seconds=value)
