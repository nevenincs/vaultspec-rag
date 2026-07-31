"""Thread-safe cooperative control for indexing attempts.

Run control is deliberately separate from progress reporting: checkpoints are
correctness boundaries, not a side effect of whether an attempt emits progress.
The mutable :class:`RunControlToken` is owned by orchestration code while
indexers consume the smaller :class:`RunControl` protocol.
"""

from __future__ import annotations

import threading
import time
from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Generator

__all__ = [
    "NO_RUN_CONTROL",
    "CancelRequested",
    "ControlRequest",
    "GpuLockWaitAccumulator",
    "NullRunControl",
    "PauseRequested",
    "QuiesceRequested",
    "RunControl",
    "RunControlSignal",
    "RunControlSnapshot",
    "RunControlToken",
    "ShutdownRequested",
    "gpu_lock_wait_scope",
    "timed_gpu_lock",
]


class GpuLockWaitAccumulator:
    """Thread-safe sum of seconds one attempt spent waiting for the GPU lock.

    Torch-free by design so it stays importable from every indexing path.
    The accumulator is shared across the attempt's threads (the encoding
    caller and the single GPU consumer) through :data:`_GPU_LOCK_WAIT`;
    contextvars do not flow into manually spawned threads, so a consumer
    thread must be started under a copied context to contribute.
    """

    __slots__ = ("_lock", "_seconds")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seconds = 0.0

    def add(self, seconds: float) -> None:
        """Fold one lock-acquisition wait into the attempt total."""
        with self._lock:
            self._seconds += seconds

    @property
    def seconds(self) -> float:
        """Return the accumulated GPU-lock wait for the attempt so far."""
        with self._lock:
            return self._seconds


_GPU_LOCK_WAIT: ContextVar[GpuLockWaitAccumulator | None] = ContextVar(
    "gpu_lock_wait",
    default=None,
)


@contextmanager
def gpu_lock_wait_scope() -> Generator[GpuLockWaitAccumulator]:
    """Attribute every timed GPU-lock acquisition in this context to one attempt."""
    accumulator = GpuLockWaitAccumulator()
    token = _GPU_LOCK_WAIT.set(accumulator)
    try:
        yield accumulator
    finally:
        _GPU_LOCK_WAIT.reset(token)


@contextmanager
def timed_gpu_lock(lock: threading.Lock | None) -> Generator[None]:
    """Acquire the GPU lock, crediting the wait to the active attempt scope.

    A ``None`` lock (local single-tenant paths) is a no-op passthrough.
    Only the acquisition wait is measured - the forward pass inside the
    lock is work, not contention - and the wait is recorded even when no
    scope is active (it is simply dropped), so call sites need no branching.
    """
    if lock is None:
        yield
        return
    started = time.perf_counter()
    lock.acquire()
    try:
        waited = time.perf_counter() - started
        accumulator = _GPU_LOCK_WAIT.get()
        if accumulator is not None:
            accumulator.add(waited)
        yield
    finally:
        lock.release()


class ControlRequest(StrEnum):
    """A cooperative request that can unwind an indexing attempt."""

    PAUSE = "pause"
    CANCEL = "cancel"
    SHUTDOWN = "shutdown"
    QUIESCE = "quiesce"


class RunControlSignal(BaseException):
    """Base class for deliberate cooperative attempt unwind.

    These signals inherit from :class:`BaseException` so broad application
    ``except Exception`` handlers cannot accidentally turn operator control
    into an indexing failure. Attempt dispatchers must catch the concrete
    signal explicitly and reconcile it with the job's current desired state.
    """

    request: ClassVar[ControlRequest]

    def __init__(self) -> None:
        super().__init__(f"run {self.request.value} requested")


class PauseRequested(RunControlSignal):
    """Raised at a safe checkpoint when pause is desired."""

    request = ControlRequest.PAUSE


class CancelRequested(RunControlSignal):
    """Raised at a safe checkpoint when cancellation is desired."""

    request = ControlRequest.CANCEL


class ShutdownRequested(RunControlSignal):
    """Raised when daemon shutdown cooperatively interrupts an attempt."""

    request = ControlRequest.SHUTDOWN


class QuiesceRequested(RunControlSignal):
    """Raised at a safe checkpoint when service quiesce needs an unwind."""

    request = ControlRequest.QUIESCE


@runtime_checkable
class RunControl(Protocol):
    """Control surface consumed by synchronous indexing code."""

    def checkpoint(self) -> None:
        """Raise the requested control signal when interruption is safe."""

    def protected(self) -> AbstractContextManager[None]:
        """Defer control signals across an indivisible mutation span."""
        ...


@dataclass(frozen=True, slots=True)
class RunControlSnapshot:
    """Immutable diagnostic view of a mutable run-control token."""

    desired: ControlRequest | None
    delivered: ControlRequest | None
    protected_depth: int


class RunControlToken:
    """Thread-safe cooperative control token for one indexing attempt.

    Pause is reversible until orchestration decides how to reconcile the
    attempt. Cancellation is absorbing for operator control, while daemon
    shutdown is the highest-priority absorbing request. A request remains
    pending after signal delivery so every cooperating thread that reaches a
    checkpoint also unwinds.

    Service quiesce is a separate cooperative request. It always unwinds an
    attempt; the manager releases that attempt's concrete resources and lets
    the service controller decide when a later reconciliation attempt may run.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._desired: ControlRequest | None = None
        self._delivered: ControlRequest | None = None
        self._protected_depth = 0
        self._quiesce_requested = False

    def request_pause(self) -> bool:
        """Request pause, returning whether the desired request changed."""
        with self._lock:
            if self._desired in {ControlRequest.CANCEL, ControlRequest.SHUTDOWN}:
                return False
            changed = self._desired is not ControlRequest.PAUSE
            self._desired = ControlRequest.PAUSE
            return changed

    def request_resume(self) -> bool:
        """Withdraw an undelivered pause request.

        Once a checkpoint has delivered pause, the attempt must finish its
        cooperative unwind. Returning ``False`` tells orchestration to queue a
        reconciliation attempt after acknowledgement instead of pretending the
        current stack can continue.
        """
        with self._lock:
            if (
                self._desired is not ControlRequest.PAUSE
                or self._delivered is ControlRequest.PAUSE
            ):
                return False
            self._desired = None
            return True

    def request_cancel(self) -> bool:
        """Request absorbing cancellation, returning whether state changed."""
        with self._lock:
            if self._desired is ControlRequest.SHUTDOWN:
                return False
            changed = self._desired is not ControlRequest.CANCEL
            self._desired = ControlRequest.CANCEL
            return changed

    def request_shutdown(self) -> bool:
        """Request a distinct absorbing daemon-shutdown interruption."""
        with self._lock:
            changed = self._desired is not ControlRequest.SHUTDOWN
            self._desired = ControlRequest.SHUTDOWN
            return changed

    def request_quiesce(self) -> bool:
        """Request cooperative service quiesce without changing job intent."""
        with self._lock:
            changed = not self._quiesce_requested
            self._quiesce_requested = True
            return changed

    def snapshot(self) -> RunControlSnapshot:
        """Return one consistent view for orchestration and diagnostics."""
        with self._lock:
            return RunControlSnapshot(
                desired=self._desired,
                delivered=self._delivered,
                protected_depth=self._protected_depth,
            )

    def checkpoint(self) -> None:
        """Deliver the highest-priority pending request at a safe boundary."""
        signal = self._take_signal_if_safe()
        if signal is not None:
            raise signal

    @contextmanager
    def protected(self) -> Generator[None]:
        """Protect a mutation and deliver pending control at its safe edges.

        Entry is atomic with respect to new requests: a request already
        present is delivered instead of starting the outermost span. Requests
        arriving during the span remain pending. On a normal outermost exit,
        the pending signal is delivered immediately. An application exception
        is never masked by a control signal.
        """
        entry_signal: RunControlSignal | None = None
        with self._lock:
            if self._protected_depth == 0:
                entry_signal = self._take_signal_locked()
            if entry_signal is None:
                self._protected_depth += 1
        if entry_signal is not None:
            raise entry_signal

        completed = False
        exit_signal: RunControlSignal | None = None
        try:
            yield
            completed = True
        finally:
            with self._lock:
                self._protected_depth -= 1
                if completed and self._protected_depth == 0:
                    exit_signal = self._take_signal_locked()
            if exit_signal is not None:
                raise exit_signal

    def _take_signal_if_safe(self) -> RunControlSignal | None:
        with self._lock:
            if self._protected_depth > 0:
                return None
            return self._take_signal_locked()

    def _take_signal_locked(self) -> RunControlSignal | None:
        request = self._desired
        if request is ControlRequest.SHUTDOWN:
            self._delivered = request
            return ShutdownRequested()
        if request is ControlRequest.CANCEL:
            self._delivered = request
            return CancelRequested()
        if request is ControlRequest.PAUSE:
            self._delivered = request
            return PauseRequested()
        if self._quiesce_requested:
            self._delivered = ControlRequest.QUIESCE
            return QuiesceRequested()
        return None


class NullRunControl:
    """No-op run control for callers that do not own a managed job."""

    def checkpoint(self) -> None:
        return None

    def protected(self) -> AbstractContextManager[None]:
        return nullcontext()


NO_RUN_CONTROL: RunControl = NullRunControl()
