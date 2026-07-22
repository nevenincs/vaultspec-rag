"""Thread-safe cooperative control for indexing attempts.

Run control is deliberately separate from progress reporting: checkpoints are
correctness boundaries, not a side effect of whether an attempt emits progress.
The mutable :class:`RunControlToken` is owned by orchestration code while
indexers consume the smaller :class:`RunControl` protocol.
"""

from __future__ import annotations

import threading
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Generator

__all__ = [
    "NO_RUN_CONTROL",
    "CancelRequested",
    "ControlRequest",
    "NullRunControl",
    "PauseRequested",
    "RunControl",
    "RunControlSignal",
    "RunControlSnapshot",
    "RunControlToken",
]


class ControlRequest(StrEnum):
    """A cooperative request that can unwind an indexing attempt."""

    PAUSE = "pause"
    CANCEL = "cancel"


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
    attempt. Cancellation is absorbing: once requested, neither pause nor
    resume can weaken it. A request remains pending after signal delivery so
    every cooperating thread that reaches a checkpoint also unwinds.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._desired: ControlRequest | None = None
        self._delivered: ControlRequest | None = None
        self._protected_depth = 0

    def request_pause(self) -> bool:
        """Request pause, returning whether the desired request changed."""
        with self._lock:
            if self._desired is ControlRequest.CANCEL:
                return False
            changed = self._desired is not ControlRequest.PAUSE
            self._desired = ControlRequest.PAUSE
            return changed

    def request_resume(self) -> bool:
        """Withdraw a pause request unless cancellation is already desired."""
        with self._lock:
            if self._desired is not ControlRequest.PAUSE:
                return False
            self._desired = None
            return True

    def request_cancel(self) -> bool:
        """Request absorbing cancellation, returning whether state changed."""
        with self._lock:
            changed = self._desired is not ControlRequest.CANCEL
            self._desired = ControlRequest.CANCEL
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
        """Deliver a pending request unless an indivisible span is active."""
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
        if request is None:
            return None
        self._delivered = request
        if request is ControlRequest.CANCEL:
            return CancelRequested()
        return PauseRequested()


class NullRunControl:
    """No-op run control for callers that do not own a managed job."""

    def checkpoint(self) -> None:
        return None

    def protected(self) -> AbstractContextManager[None]:
        return nullcontext()


NO_RUN_CONTROL: RunControl = NullRunControl()
