"""Shared liveness and interruption policy for one indexing attempt.

The policy owns one monotonic clock measuring time since durable progress.
Store retry, producer/consumer queues, and cooperative waits consume that
clock; none of them may reset it.  A future run ledger advances the clock only
after a storage-confirmed unit or finalization phase is durably committed.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from .._job_errors import JobError, JobErrorKind
from .._store_writes import StoreWritePolicy
from ..job_control import NO_RUN_CONTROL, RunControl

if TYPE_CHECKING:
    from collections.abc import Generator

__all__ = [
    "CleanupQueuePutOutcome",
    "DurableProgressKind",
    "RunPolicy",
    "RunPolicySnapshot",
    "ThreadWaitOutcome",
]

_POLL_INTERVAL_SECONDS = 0.05


class CleanupQueuePutOutcome(StrEnum):
    """Bounded cleanup result for transferring one queue item."""

    DELIVERED = "delivered"
    TIMED_OUT = "timed_out"


class DurableProgressKind(StrEnum):
    """The two events allowed to advance the no-progress clock."""

    LEDGER_UNIT_COMMITTED = "ledger_unit_committed"
    FINALIZATION_PHASE_COMMITTED = "finalization_phase_committed"


class ThreadWaitOutcome(StrEnum):
    """Bounded cleanup result for a worker thread."""

    EXITED = "exited"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class RunPolicySnapshot:
    """Immutable liveness state suitable for service-domain projection."""

    timeout_seconds: float
    last_durable_progress_at: float
    seconds_since_durable_progress: float
    remaining_seconds: float
    durable_progress_count: int
    last_progress_kind: DurableProgressKind | None
    last_progress_label: str | None
    expired: bool


class RunPolicy:
    """Thread-safe run liveness and cooperative interruption authority.

    One instance belongs to one indexing attempt and is shared by its producer
    and consumer threads. Deadline expiry is latched so every participant
    observes the same typed terminal outcome. Normal checkpoints also deliver
    operator control through the attempt's :class:`RunControl` token.

    Thread cleanup is intentionally different from production polling. Once a
    deadline or control signal starts unwind, the same signal must not prevent
    the coordinator from joining a worker. :meth:`join_thread` therefore uses
    only its explicit hard cleanup cap and returns a typed outcome.
    """

    __slots__ = (
        "_durable_progress_count",
        "_failure_detail",
        "_last_progress_kind",
        "_last_progress_label",
        "_last_progress_monotonic",
        "_last_progress_wall",
        "_lock",
        "_run_control",
        "_store_write_policy",
        "_timeout_seconds",
    )

    def __init__(
        self,
        *,
        no_progress_timeout_seconds: float,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Create an attempt policy with a frozen finite positive timeout."""
        timeout = _finite_positive_seconds(
            "no_progress_timeout_seconds",
            no_progress_timeout_seconds,
        )

        now_monotonic = time.monotonic()
        self._timeout_seconds = timeout
        self._run_control = run_control
        self._lock = threading.Lock()
        self._last_progress_monotonic = now_monotonic
        self._last_progress_wall = time.time()
        self._durable_progress_count = 0
        self._last_progress_kind: DurableProgressKind | None = None
        self._last_progress_label: str | None = None
        self._failure_detail: str | None = None
        self._store_write_policy = StoreWritePolicy(
            remaining_seconds=self.remaining_seconds,
            wait=self.wait,
        )

    @classmethod
    def from_config(
        cls,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> RunPolicy:
        """Construct a policy from the process configuration snapshot."""
        from ..config._settings import get_config

        return cls(
            no_progress_timeout_seconds=(
                get_config().index_no_progress_timeout_seconds
            ),
            run_control=run_control,
        )

    @property
    def store_write_policy(self) -> StoreWritePolicy:
        """Expose the store's limited view of this same clock and waiter."""
        return self._store_write_policy

    def checkpoint(self, label: str) -> None:
        """Raise a latched deadline or pending control signal at a safe edge."""
        _require_label(label)
        self._remaining_or_raise(label=label)
        self._run_control.checkpoint()

    @contextmanager
    def protected(self, label: str) -> Generator[None]:
        """Defer cooperative control across one labeled indivisible span."""
        _require_label(label)
        self.checkpoint(f"{label} entry")
        with self._run_control.protected():
            yield
        self.checkpoint(f"{label} exit")

    def remaining_seconds(self) -> float:
        """Return the live positive budget or raise the typed latched expiry."""
        return self._remaining_or_raise(label="remaining-budget check")

    def record_durable_progress(
        self,
        *,
        kind: DurableProgressKind,
        label: str,
    ) -> RunPolicySnapshot:
        """Advance the clock after a confirmed ledger commit.

        Callers must invoke this only after the matching store mutation and
        local ledger transaction have both completed. The policy accepts only
        the two architecture-defined durable progress kinds so UI progress,
        queue motion, encoding, and retry activity cannot be mistaken for a
        liveness reset.
        """
        _require_label(label)

        with self._lock:
            now_monotonic = time.monotonic()
            self._raise_or_latch_expiry_locked(
                now_monotonic=now_monotonic,
                label=label,
            )
            self._last_progress_monotonic = now_monotonic
            self._last_progress_wall = time.time()
            self._durable_progress_count += 1
            self._last_progress_kind = kind
            self._last_progress_label = label
            return self._snapshot_locked(now_monotonic=now_monotonic)

    def wait(self, seconds: float) -> None:
        """Wait for at most ``seconds`` while polling control and liveness."""
        duration = _finite_nonnegative_seconds("seconds", seconds)
        self.checkpoint("interruptible wait")
        wait_deadline = time.monotonic() + duration
        while True:
            wait_remaining = wait_deadline - time.monotonic()
            if wait_remaining <= 0.0:
                break
            budget_remaining = self.remaining_seconds()
            time.sleep(
                min(
                    _POLL_INTERVAL_SECONDS,
                    wait_remaining,
                    budget_remaining,
                )
            )
            self.checkpoint("interruptible wait")
        self.checkpoint("interruptible wait")

    def queue_put[T](
        self,
        target: queue.Queue[T],
        item: T,
        *,
        label: str,
    ) -> None:
        """Put one item into a bounded real queue without an unbounded wait."""
        _require_label(label)
        while True:
            self.checkpoint(label)
            timeout = min(_POLL_INTERVAL_SECONDS, self.remaining_seconds())
            try:
                target.put(item, timeout=timeout)
            except queue.Full:
                continue
            # Successful put transfers ownership to the queue. Delivering a
            # signal here would report failure after mutation and invite a
            # duplicate enqueue during reconciliation; the caller checks at
            # its next safe production boundary instead.
            return

    def queue_get[T](self, target: queue.Queue[T], *, label: str) -> T:
        """Get one item from a real queue while polling control and liveness."""
        _require_label(label)
        while True:
            self.checkpoint(label)
            timeout = min(_POLL_INTERVAL_SECONDS, self.remaining_seconds())
            try:
                item = target.get(timeout=timeout)
            except queue.Empty:
                continue
            # Successful get transfers ownership to the caller. Do not raise
            # after removing the item or the current attempt would silently
            # lose it; the caller checkpoints before acting on the item.
            return item

    def queue_put_for_cleanup[T](
        self,
        target: queue.Queue[T],
        item: T,
        *,
        timeout_seconds: float,
        label: str,
    ) -> CleanupQueuePutOutcome:
        """Transfer one cleanup item under an independent hard cap.

        Once ordinary production has been interrupted, a latched deadline or
        pending operator signal must not prevent the coordinator from sending
        a shutdown sentinel. This method therefore ignores both and polls only
        until ``timeout_seconds`` expires. It returns immediately after a
        successful put, so the item is delivered exactly once.
        """
        hard_cap = _finite_nonnegative_seconds("timeout_seconds", timeout_seconds)
        _require_label(label)
        cleanup_deadline = time.monotonic() + hard_cap
        while True:
            remaining = max(0.0, cleanup_deadline - time.monotonic())
            try:
                target.put(
                    item,
                    timeout=min(_POLL_INTERVAL_SECONDS, remaining),
                )
            except queue.Full:
                if remaining <= 0.0:
                    return CleanupQueuePutOutcome.TIMED_OUT
                continue
            return CleanupQueuePutOutcome.DELIVERED

    def join_thread(
        self,
        thread: threading.Thread,
        *,
        timeout_seconds: float,
        label: str,
    ) -> ThreadWaitOutcome:
        """Join a worker under an independent hard cleanup cap.

        Cleanup deliberately does not redeliver the run's latched failure or
        control signal. The worker itself shares this policy and sees those at
        production checkpoints; the coordinator must retain a bounded chance
        to release it before a store can be closed.
        """
        hard_cap = _finite_nonnegative_seconds("timeout_seconds", timeout_seconds)
        _require_label(label)
        cleanup_deadline = time.monotonic() + hard_cap
        while thread.is_alive():
            remaining = cleanup_deadline - time.monotonic()
            if remaining <= 0.0:
                return ThreadWaitOutcome.TIMED_OUT
            thread.join(timeout=min(_POLL_INTERVAL_SECONDS, remaining))
        return ThreadWaitOutcome.EXITED

    def snapshot(self) -> RunPolicySnapshot:
        """Return current state without raising or advancing the clock."""
        with self._lock:
            return self._snapshot_locked(now_monotonic=time.monotonic())

    def _remaining_or_raise(self, *, label: str) -> float:
        with self._lock:
            now_monotonic = time.monotonic()
            self._raise_or_latch_expiry_locked(
                now_monotonic=now_monotonic,
                label=label,
            )
            return self._remaining_locked(now_monotonic=now_monotonic)

    def _raise_or_latch_expiry_locked(
        self,
        *,
        now_monotonic: float,
        label: str,
    ) -> None:
        detail = self._failure_detail
        if detail is None and self._remaining_locked(now_monotonic=now_monotonic) <= 0:
            elapsed = max(0.0, now_monotonic - self._last_progress_monotonic)
            prior = self._last_progress_label or "run admission"
            detail = (
                f"no storage-confirmed durable progress for {elapsed:.3f}s "
                f"before {label}; last durable boundary: {prior}"
            )
            self._failure_detail = detail
        if detail is not None:
            raise JobError(JobErrorKind.NO_PROGRESS_TIMEOUT, detail)

    def _remaining_locked(self, *, now_monotonic: float) -> float:
        return max(
            0.0,
            self._timeout_seconds
            - max(0.0, now_monotonic - self._last_progress_monotonic),
        )

    def _snapshot_locked(self, *, now_monotonic: float) -> RunPolicySnapshot:
        elapsed = max(0.0, now_monotonic - self._last_progress_monotonic)
        remaining = self._remaining_locked(now_monotonic=now_monotonic)
        return RunPolicySnapshot(
            timeout_seconds=self._timeout_seconds,
            last_durable_progress_at=self._last_progress_wall,
            seconds_since_durable_progress=elapsed,
            remaining_seconds=remaining,
            durable_progress_count=self._durable_progress_count,
            last_progress_kind=self._last_progress_kind,
            last_progress_label=self._last_progress_label,
            expired=self._failure_detail is not None or remaining <= 0.0,
        )


def _finite_positive_seconds(name: str, value: object) -> float:
    result = _finite_nonnegative_seconds(name, value)
    if result <= 0.0:
        raise ValueError(f"{name} must be a finite positive number, got {value!r}")
    return result


def _finite_nonnegative_seconds(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite non-negative number, got {value!r}")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number, got {value!r}")
    return result


def _require_label(label: str) -> None:
    if not label.strip():
        raise ValueError("run-policy labels must not be empty")
