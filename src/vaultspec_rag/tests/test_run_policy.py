"""Real thread, queue, timing, and control tests for index run policy."""

from __future__ import annotations

import queue
import threading
import time

import pytest

from .._job_errors import JobError, JobErrorKind
from ..indexer._run_policy import (
    CleanupQueuePutOutcome,
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
    policy = RunPolicy(no_progress_timeout_seconds=0.09)
    started = time.monotonic()

    for ordinal in range(4):
        policy.wait(0.04)
        snapshot = policy.record_durable_progress(
            kind=DurableProgressKind.LEDGER_UNIT_COMMITTED,
            label=f"segment-{ordinal}",
        )
        assert snapshot.durable_progress_count == ordinal + 1

    assert time.monotonic() - started > 0.09
    policy.checkpoint("ordinary pipeline motion")

    with pytest.raises(JobError) as expired:
        policy.wait(0.2)
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


def test_full_queue_put_expires_without_hanging() -> None:
    target: queue.Queue[str] = queue.Queue(maxsize=1)
    target.put_nowait("occupied")
    policy = RunPolicy(no_progress_timeout_seconds=0.08)

    with pytest.raises(JobError) as expired:
        policy.queue_put(target, "blocked", label="producer queue put")

    assert expired.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
    assert target.get_nowait() == "occupied"
    assert target.empty()


def test_empty_queue_get_is_interrupted_by_real_control() -> None:
    target: queue.Queue[str] = queue.Queue(maxsize=1)
    control = RunControlToken()
    policy = RunPolicy(
        no_progress_timeout_seconds=5.0,
        run_control=control,
    )
    entered = threading.Event()
    outcomes: list[BaseException] = []

    def run_get() -> None:
        entered.set()
        try:
            policy.queue_get(target, label="consumer queue get")
        except BaseException as exc:
            outcomes.append(exc)

    worker = threading.Thread(target=run_get, name="run-policy-queue-get")
    worker.start()
    assert entered.wait(timeout=_THREAD_TIMEOUT_SECONDS)
    assert control.request_cancel() is True
    _join_thread(worker)

    assert len(outcomes) == 1
    assert isinstance(outcomes[0], CancelRequested)


def test_successful_queue_motion_transfers_each_item_exactly_once() -> None:
    get_control = RunControlToken()
    get_policy = RunPolicy(
        no_progress_timeout_seconds=1.0,
        run_control=get_control,
    )
    source: queue.Queue[str] = queue.Queue(maxsize=1)
    source.put_nowait("owned-by-queue")

    item = get_policy.queue_get(source, label="consumer queue get")
    assert item == "owned-by-queue"
    assert source.empty()
    assert get_control.request_cancel() is True
    with pytest.raises(CancelRequested):
        get_policy.checkpoint("consumer owns item")
    assert source.empty()

    put_control = RunControlToken()
    put_policy = RunPolicy(
        no_progress_timeout_seconds=1.0,
        run_control=put_control,
    )
    target: queue.Queue[str] = queue.Queue(maxsize=1)

    put_policy.queue_put(target, "owned-by-queue", label="producer queue put")
    assert put_control.request_cancel() is True
    with pytest.raises(CancelRequested):
        put_policy.checkpoint("producer transferred item")
    assert target.get_nowait() == "owned-by-queue"
    assert target.empty()


def test_cleanup_queue_put_ignores_expired_policy_and_pending_control() -> None:
    control = RunControlToken()
    policy = RunPolicy(
        no_progress_timeout_seconds=0.05,
        run_control=control,
    )
    with pytest.raises(JobError):
        policy.wait(0.2)
    assert control.request_cancel() is True
    target: queue.Queue[str] = queue.Queue(maxsize=1)

    outcome = policy.queue_put_for_cleanup(
        target,
        "shutdown",
        timeout_seconds=0.5,
        label="consumer sentinel",
    )

    assert outcome is CleanupQueuePutOutcome.DELIVERED
    assert target.get_nowait() == "shutdown"
    assert target.empty()
    with pytest.raises(JobError) as still_expired:
        policy.remaining_seconds()
    assert still_expired.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT


def test_cleanup_queue_put_delivers_once_after_real_capacity_frees() -> None:
    target: queue.Queue[str] = queue.Queue(maxsize=1)
    target.put_nowait("work")
    policy = RunPolicy(no_progress_timeout_seconds=1.0)
    consumed: list[str] = []

    def release_capacity() -> None:
        time.sleep(0.06)
        consumed.append(target.get(timeout=_THREAD_TIMEOUT_SECONDS))

    worker = threading.Thread(
        target=release_capacity,
        name="run-policy-cleanup-queue-consumer",
    )
    worker.start()
    try:
        outcome = policy.queue_put_for_cleanup(
            target,
            "shutdown",
            timeout_seconds=1.0,
            label="consumer sentinel",
        )
    finally:
        _join_thread(worker)

    assert outcome is CleanupQueuePutOutcome.DELIVERED
    assert consumed == ["work"]
    assert target.qsize() == 1
    assert target.get_nowait() == "shutdown"
    assert target.empty()


def test_cleanup_queue_put_reports_hard_cap_with_full_queue_unchanged() -> None:
    target: queue.Queue[str] = queue.Queue(maxsize=1)
    target.put_nowait("work")
    policy = RunPolicy(no_progress_timeout_seconds=1.0)
    started = time.monotonic()

    outcome = policy.queue_put_for_cleanup(
        target,
        "shutdown",
        timeout_seconds=0.06,
        label="consumer sentinel",
    )
    elapsed = time.monotonic() - started

    assert outcome is CleanupQueuePutOutcome.TIMED_OUT
    assert 0.04 <= elapsed < 1.0
    assert target.get_nowait() == "work"
    assert target.empty()


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
    policy = RunPolicy(no_progress_timeout_seconds=0.08)
    capability = policy.store_write_policy

    assert capability is policy.store_write_policy
    assert 0.0 < capability.remaining_seconds() <= 0.08
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
