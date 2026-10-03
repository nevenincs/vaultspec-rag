"""Shared liveness and interruption policy for one indexing attempt.

The policy owns one monotonic clock measuring time since durable progress.
Store retry, producer/consumer queues, and cooperative waits consume that
clock; none of them may reset it.  A future run ledger advances the clock only
after a storage-confirmed unit or finalization phase is durably committed.
"""

from __future__ import annotations

import logging
import math
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
    from collections.abc import Callable, Generator

__all__ = [
    "DurableProgressKind",
    "RunPolicy",
    "RunPolicySnapshot",
    "ThreadWaitOutcome",
]

_POLL_INTERVAL_SECONDS = 0.05
logger = logging.getLogger(__name__)


class DurableProgressKind(StrEnum):
    """Committed storage or ledger events allowed to advance liveness."""

    LEDGER_UNIT_COMMITTED = "ledger_unit_committed"
    FINALIZATION_PHASE_COMMITTED = "finalization_phase_committed"
    RECONCILIATION_BATCH_COMMITTED = "reconciliation_batch_committed"


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
        "_completed",
        "_durable_progress_count",
        "_durable_progress_observer",
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
        self._completed = False
        self._last_progress_kind: DurableProgressKind | None = None
        self._last_progress_label: str | None = None
        self._failure_detail: str | None = None
        self._durable_progress_observer: Callable[[RunPolicySnapshot], None] | None = (
            None
        )
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

    def checkpoint(self, label: str = "indexing safe boundary") -> None:
        """Raise a latched deadline or pending control signal at a safe edge."""
        _require_label(label)
        self._remaining_or_raise(label=label, allow_completed=True)
        self._run_control.checkpoint()

    @contextmanager
    def protected(self, label: str = "indexing protected interval") -> Generator[None]:
        """Defer cooperative control across one labeled indivisible span."""
        _require_label(label)
        self.checkpoint(f"{label} entry")
        with self._run_control.protected():
            yield
        self.checkpoint(f"{label} exit")

    def remaining_seconds(self) -> float:
        """Return live budget, zero after completion, or the latched expiry."""
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
        architecture-defined durable progress kinds so UI progress,
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
            snapshot = self._record_progress_locked(
                now_monotonic=now_monotonic, kind=kind, label=label
            )
            observer = self._durable_progress_observer
        self._notify_durable_progress(snapshot, observer)
        return snapshot

    def complete(self, *, label: str) -> None:
        """Retire deadline checks after the actual successful terminal commit.

        Completion permits control-aware epilogues, not further store writes.
        A prior latched failure is retained. Callers must check the budget
        before committing terminal success and invoke this only after it returns.
        """
        _require_label(label)
        with self._lock:
            if self._completed:
                return
            self._completed = True
            snapshot = self._record_progress_locked(
                now_monotonic=time.monotonic(),
                kind=DurableProgressKind.FINALIZATION_PHASE_COMMITTED,
                label=label,
            )
            observer = self._durable_progress_observer
        self._notify_durable_progress(snapshot, observer)

    def _record_progress_locked(
        self, *, now_monotonic: float, kind: DurableProgressKind, label: str
    ) -> RunPolicySnapshot:
        self._last_progress_monotonic = now_monotonic
        self._last_progress_wall = time.time()
        self._durable_progress_count += 1
        self._last_progress_kind = kind
        self._last_progress_label = label
        return self._snapshot_locked(now_monotonic=now_monotonic)

    @staticmethod
    def _notify_durable_progress(
        snapshot: RunPolicySnapshot,
        observer: Callable[[RunPolicySnapshot], None] | None,
    ) -> None:
        if observer is not None:
            try:
                observer(snapshot)
            except Exception:
                logger.warning("durable progress observation failed", exc_info=True)

    def set_durable_progress_observer(
        self, observer: Callable[[RunPolicySnapshot], None] | None
    ) -> None:
        """Attach one run's observer without exposing the policy lock to it."""
        with self._lock:
            self._durable_progress_observer = observer

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

    def _remaining_or_raise(
        self, *, label: str, allow_completed: bool = False
    ) -> float:
        with self._lock:
            now_monotonic = time.monotonic()
            if self._completed and not allow_completed:
                if self._failure_detail is not None:
                    raise JobError(
                        JobErrorKind.NO_PROGRESS_TIMEOUT, self._failure_detail
                    )
                return 0.0
            if not (
                allow_completed and self._completed and self._failure_detail is None
            ):
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
            remaining_seconds=0.0 if self._completed else remaining,
            durable_progress_count=self._durable_progress_count,
            last_progress_kind=self._last_progress_kind,
            last_progress_label=self._last_progress_label,
            expired=self._failure_detail is not None
            or (not self._completed and remaining <= 0.0),
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
