"""Serialized, torch-free admission and resource-quiesce control.

The controller owns only lifecycle truth: it closes compute admission, tracks
the tickets already admitted to an epoch, and records the evidence required
before a registry may describe GPU borrowing as safe.  It deliberately does
not import or operate GPU dependencies.  The registry owns their release and
rebuild, then acknowledges the achieved result here.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import TYPE_CHECKING, Final, Literal, Self

if TYPE_CHECKING:
    from types import TracebackType

__all__ = [
    "ComputeTicket",
    "QuiesceAdmissionClosedError",
    "QuiesceSnapshot",
    "QuiesceState",
    "QuiesceTransition",
    "QuiesceTransitionCode",
    "ServiceQuiesceController",
    "ServiceQuiesceTransitionConflictError",
    "ServiceQuiesceTransitionWaitTimeoutError",
]


class QuiesceState(StrEnum):
    """The only controller lifecycle states exposed to service surfaces."""

    RUNNING = "running"
    PAUSING = "pausing"
    QUIESCED = "quiesced"
    WARMING = "warming"


class QuiesceTransitionCode(StrEnum):
    """Machine-readable result for one controller transition or observation."""

    PAUSE_STARTED = "pause_started"
    ALREADY_PAUSING = "already_pausing"
    ALREADY_QUIESCED = "already_quiesced"
    PAUSE_UNAVAILABLE = "pause_unavailable"
    DRAINED = "drained"
    DRAIN_TIMED_OUT = "drain_timed_out"
    DRAIN_UNAVAILABLE = "drain_unavailable"
    QUIESCED = "quiesced"
    QUIESCE_UNAVAILABLE = "quiesce_unavailable"
    WARMING_STARTED = "warming_started"
    ALREADY_WARMING = "already_warming"
    WARMING_UNAVAILABLE = "warming_unavailable"
    PAUSE_ABORTED = "pause_aborted"
    PAUSE_ABORT_UNAVAILABLE = "pause_abort_unavailable"
    RUNNING = "running"
    WARMUP_UNAVAILABLE = "warmup_unavailable"
    QUIESCE_FAILED = "quiesce_failed"
    WARMUP_FAILED = "warmup_failed"
    RESUME_RECOVERY_FAILED = "resume_recovery_failed"


# The only two closed transitions a caller can own, each mapped to the code
# for a request that arrived after the controller moved on and the code that
# records the owned transition failing.
_FAILURE_CODES: Final[
    dict[QuiesceState, tuple[QuiesceTransitionCode, QuiesceTransitionCode]]
] = {
    QuiesceState.PAUSING: (
        QuiesceTransitionCode.QUIESCE_UNAVAILABLE,
        QuiesceTransitionCode.QUIESCE_FAILED,
    ),
    QuiesceState.WARMING: (
        QuiesceTransitionCode.WARMUP_UNAVAILABLE,
        QuiesceTransitionCode.WARMUP_FAILED,
    ),
}


@dataclass(frozen=True, slots=True)
class QuiesceSnapshot:
    """Immutable controller evidence rendered identically by all adapters."""

    state: QuiesceState
    admission_epoch: int
    admissions_open: bool
    active_compute_tickets: int
    drain_complete: bool
    vram_released: bool
    safe_to_borrow_gpu: bool
    pause_requested_at: float | None
    drain_acknowledged_at: float | None
    quiesced_at: float | None
    warming_started_at: float | None
    failure_reason: str | None

    def as_envelope(self) -> dict[str, object]:
        """Render the whole observation as one adapter-agnostic payload."""
        return {
            "state": self.state.value,
            "admission_epoch": self.admission_epoch,
            "admissions_open": self.admissions_open,
            "active_compute_tickets": self.active_compute_tickets,
            "drain_complete": self.drain_complete,
            "vram_released": self.vram_released,
            "safe_to_borrow_gpu": self.safe_to_borrow_gpu,
            "pause_requested_at": self.pause_requested_at,
            "drain_acknowledged_at": self.drain_acknowledged_at,
            "quiesced_at": self.quiesced_at,
            "warming_started_at": self.warming_started_at,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True, slots=True)
class QuiesceTransition:
    """One immutable outcome envelope for a serialized controller operation."""

    code: QuiesceTransitionCode
    achieved: bool
    snapshot: QuiesceSnapshot


class QuiesceAdmissionClosedError(RuntimeError):
    """Raised when a caller tries to admit compute outside a running epoch."""

    def __init__(self, snapshot: QuiesceSnapshot) -> None:
        super().__init__(
            "compute admission is closed while service quiesce state is "
            f"{snapshot.state.value!r}"
        )
        self.snapshot = snapshot


class ServiceQuiesceTransitionConflictError(RuntimeError):
    """Raised when a request opposes the registry's owned transition."""

    code = "quiesce_transition_conflict"

    def __init__(
        self,
        *,
        requested_direction: str,
        active_direction: str,
        snapshot: QuiesceSnapshot,
    ) -> None:
        super().__init__(
            "service resource transition conflict: "
            f"requested {requested_direction!r} while {active_direction!r} owns "
            "the transition"
        )
        self.requested_direction = requested_direction
        self.active_direction = active_direction
        self.snapshot = snapshot


class ServiceQuiesceTransitionWaitTimeoutError(TimeoutError):
    """Raised when a same-direction caller outwaits its owned transition."""

    code = "quiesce_transition_wait_timed_out"

    def __init__(self, *, direction: str, snapshot: QuiesceSnapshot) -> None:
        super().__init__(
            f"timed out waiting for the service {direction!r} resource transition"
        )
        self.direction = direction
        self.snapshot = snapshot


@dataclass(frozen=True, slots=True)
class ComputeTicket:
    """One epoch-scoped compute admission that must be released exactly once.

    Tickets are immutable handles.  The controller owns the mutable active
    set, so duplicate releases are harmless and an old-epoch ticket cannot
    affect a later epoch.
    """

    admission_epoch: int
    ticket_id: int
    _controller: ServiceQuiesceController

    def release(self) -> bool:
        """Release this ticket, returning ``True`` only for the first release."""
        return self._controller.release_ticket(self)

    def belongs_to(self, controller: ServiceQuiesceController) -> bool:
        """Return whether this immutable ticket was issued by ``controller``."""
        return self._controller is controller

    def __enter__(self) -> Self:
        """Return this ticket for a bounded admitted compute section."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        """Release the ticket without swallowing an exception from its user."""
        del exc_type, exc_val, exc_tb
        self.release()
        return False


class ServiceQuiesceController:
    """Serialize compute admission, drain acknowledgement, and lifecycle truth.

    A pause first closes admission for the current epoch.  Callers then ask
    managed work to unwind and wait through :meth:`wait_for_drain`.  Only the
    GPU-owning registry can subsequently acknowledge released residency with
    :meth:`acknowledge_vram_released`.  Resume is similarly closed until the
    registry reports a successful rebuild through :meth:`complete_warming`.

    A pause that fails - a drain that outran its budget, a residency release
    that raised - stops in ``pausing`` with admission closed.  That state has
    no route through ``warming``, because ``warming`` presupposes the
    quiesced evidence the pause never produced, so :meth:`abort_pause` is the
    one way back to ``running`` and keeps a failed pause from holding the
    whole daemon shut until it is restarted.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._state = QuiesceState.RUNNING
        self._admission_epoch = 1
        self._next_ticket_id = 1
        self._active_ticket_epochs: dict[int, int] = {}
        self._pause_requested_at: float | None = None
        self._drain_acknowledged_at: float | None = None
        self._quiesced_at: float | None = None
        self._warming_started_at: float | None = None
        self._vram_released = False
        self._failure_reason: str | None = None

    def snapshot(self) -> QuiesceSnapshot:
        """Return one immutable, internally consistent lifecycle observation."""
        with self._condition:
            return self._snapshot_locked()

    def acquire_ticket(self) -> ComputeTicket:
        """Admit one compute section in the current running epoch.

        The returned ticket must be acquired before a project lease, model
        reference, or GPU lock.  Closing admission and registering a ticket
        share one condition lock, so a pause never overlooks a concurrent
        admission.
        """
        with self._condition:
            if self._state is not QuiesceState.RUNNING:
                raise QuiesceAdmissionClosedError(self._snapshot_locked())
            ticket_id = self._next_ticket_id
            self._next_ticket_id += 1
            self._active_ticket_epochs[ticket_id] = self._admission_epoch
            return ComputeTicket(self._admission_epoch, ticket_id, self)

    def release_ticket(self, ticket: ComputeTicket) -> bool:
        """Release a tracked ticket and wake a drain waiter when it was active."""
        with self._condition:
            if not ticket.belongs_to(self):
                return False
            ticket_epoch = self._active_ticket_epochs.get(ticket.ticket_id)
            if ticket_epoch != ticket.admission_epoch:
                return False
            del self._active_ticket_epochs[ticket.ticket_id]
            self._condition.notify_all()
            return True

    def begin_pause(self) -> QuiesceTransition:
        """Close the current admission epoch and enter ``pausing`` idempotently."""
        with self._condition:
            if self._state is QuiesceState.RUNNING:
                self._state = QuiesceState.PAUSING
                self._pause_requested_at = time.monotonic()
                self._drain_acknowledged_at = None
                self._quiesced_at = None
                self._warming_started_at = None
                self._vram_released = False
                self._failure_reason = None
                return self._transition_locked(
                    QuiesceTransitionCode.PAUSE_STARTED,
                    achieved=False,
                )
            if self._state is QuiesceState.PAUSING:
                return self._transition_locked(
                    QuiesceTransitionCode.ALREADY_PAUSING,
                    achieved=False,
                )
            if self._state is QuiesceState.QUIESCED:
                return self._transition_locked(
                    QuiesceTransitionCode.ALREADY_QUIESCED,
                    achieved=True,
                )
            return self._transition_locked(
                QuiesceTransitionCode.PAUSE_UNAVAILABLE,
                achieved=False,
            )

    def wait_for_drain(self, timeout: float) -> QuiesceTransition:
        """Wait boundedly for every ticket admitted before pause to release."""
        if not isfinite(timeout) or timeout < 0:
            raise ValueError(
                "timeout must be a finite value greater than or equal to zero"
            )
        with self._condition:
            if self._state is QuiesceState.QUIESCED:
                return self._transition_locked(
                    QuiesceTransitionCode.ALREADY_QUIESCED,
                    achieved=True,
                )
            if self._state is not QuiesceState.PAUSING:
                return self._transition_locked(
                    QuiesceTransitionCode.DRAIN_UNAVAILABLE,
                    achieved=False,
                )
            if self._active_ticket_epochs:
                self._condition.wait_for(
                    lambda: not self._active_ticket_epochs,
                    timeout=timeout,
                )
            if self._active_ticket_epochs:
                self._failure_reason = "compute_ticket_drain_timed_out"
                return self._transition_locked(
                    QuiesceTransitionCode.DRAIN_TIMED_OUT,
                    achieved=False,
                )
            self._drain_acknowledged_at = time.monotonic()
            if self._failure_reason == "compute_ticket_drain_timed_out":
                self._failure_reason = None
            return self._transition_locked(QuiesceTransitionCode.DRAINED, achieved=True)

    def acknowledge_vram_released(self) -> QuiesceTransition:
        """Record GPU-residency release after the registry's completed teardown."""
        with self._condition:
            if self._state is QuiesceState.QUIESCED:
                return self._transition_locked(
                    QuiesceTransitionCode.ALREADY_QUIESCED,
                    achieved=True,
                )
            if self._state is not QuiesceState.PAUSING:
                return self._transition_locked(
                    QuiesceTransitionCode.QUIESCE_UNAVAILABLE,
                    achieved=False,
                )
            if self._active_ticket_epochs:
                self._failure_reason = "compute_tickets_still_active"
                return self._transition_locked(
                    QuiesceTransitionCode.QUIESCE_UNAVAILABLE,
                    achieved=False,
                )
            if self._drain_acknowledged_at is None:
                self._failure_reason = "compute_ticket_drain_not_acknowledged"
                return self._transition_locked(
                    QuiesceTransitionCode.QUIESCE_UNAVAILABLE,
                    achieved=False,
                )
            self._state = QuiesceState.QUIESCED
            self._vram_released = True
            self._quiesced_at = time.monotonic()
            self._failure_reason = None
            self._condition.notify_all()
            return self._transition_locked(
                QuiesceTransitionCode.QUIESCED,
                achieved=True,
            )

    def fail_transition(
        self,
        *,
        owned_state: Literal[QuiesceState.PAUSING, QuiesceState.WARMING],
        reason: str,
    ) -> QuiesceTransition:
        """Keep admission closed and unsafe when an owned transition fails.

        ``owned_state`` names the closed transition the caller was driving, so
        a report arriving after the controller has already moved on is
        answered as unavailable for that transition rather than recorded
        against whichever one is now live.
        """
        failure_reason = _require_reason(reason)
        unavailable, failed = _FAILURE_CODES[owned_state]
        with self._condition:
            if self._state is not owned_state:
                return self._transition_locked(unavailable, achieved=False)
            self._vram_released = False
            self._failure_reason = failure_reason
            return self._transition_locked(failed, achieved=False)

    def abort_pause(self) -> QuiesceTransition:
        """Reopen the admission epoch a pause closed but never quiesced.

        ``pausing`` is the one state a pause can fail into, and it closes
        admission without ever reaching the evidence that lets ``warming``
        start.  Aborting is therefore the only way back for a drain that
        timed out or a residency release that failed, and the registry must
        have restored whatever residency it already detached before calling
        it.  The admission epoch is deliberately not advanced: an aborted
        pause never finished closing its generation of admitted work, so the
        tickets it failed to drain stay releasable against the epoch that
        issued them.
        """
        with self._condition:
            if self._state is QuiesceState.RUNNING:
                return self._transition_locked(
                    QuiesceTransitionCode.RUNNING,
                    achieved=True,
                )
            if self._state is not QuiesceState.PAUSING:
                return self._transition_locked(
                    QuiesceTransitionCode.PAUSE_ABORT_UNAVAILABLE,
                    achieved=False,
                )
            self._state = QuiesceState.RUNNING
            self._pause_requested_at = None
            self._drain_acknowledged_at = None
            self._quiesced_at = None
            self._warming_started_at = None
            self._vram_released = False
            self._failure_reason = None
            self._condition.notify_all()
            return self._transition_locked(
                QuiesceTransitionCode.PAUSE_ABORTED,
                achieved=True,
            )

    def begin_warming(self) -> QuiesceTransition:
        """Enter closed ``warming`` before the registry rebuilds GPU residency."""
        with self._condition:
            if self._state is QuiesceState.QUIESCED:
                self._state = QuiesceState.WARMING
                self._warming_started_at = time.monotonic()
                self._vram_released = False
                self._failure_reason = None
                return self._transition_locked(
                    QuiesceTransitionCode.WARMING_STARTED,
                    achieved=False,
                )
            if self._state is QuiesceState.WARMING:
                return self._transition_locked(
                    QuiesceTransitionCode.ALREADY_WARMING,
                    achieved=False,
                )
            return self._transition_locked(
                QuiesceTransitionCode.WARMING_UNAVAILABLE,
                achieved=False,
            )

    def complete_warming(self) -> QuiesceTransition:
        """Open a new admission epoch after the registry rebuilt its GPU stack."""
        with self._condition:
            if self._state is not QuiesceState.WARMING:
                return self._transition_locked(
                    QuiesceTransitionCode.WARMUP_UNAVAILABLE,
                    achieved=False,
                )
            self._state = QuiesceState.RUNNING
            self._admission_epoch += 1
            self._pause_requested_at = None
            self._drain_acknowledged_at = None
            self._quiesced_at = None
            self._warming_started_at = None
            self._vram_released = False
            self._failure_reason = None
            self._condition.notify_all()
            return self._transition_locked(QuiesceTransitionCode.RUNNING, achieved=True)

    def fail_warming(self, reason: str) -> QuiesceTransition:
        """Record a rebuild failure while keeping admission closed and unsafe."""
        failure_reason = _require_reason(reason)
        with self._condition:
            if self._state is not QuiesceState.WARMING:
                return self._transition_locked(
                    QuiesceTransitionCode.WARMUP_UNAVAILABLE,
                    achieved=False,
                )
            self._vram_released = False
            self._failure_reason = failure_reason
            return self._transition_locked(
                QuiesceTransitionCode.WARMUP_FAILED,
                achieved=False,
            )

    def fail_resume_recovery(self, reason: str) -> QuiesceTransition:
        """Keep admission closed when durable same-ID recovery preparation fails."""
        failure_reason = _require_reason(reason)
        with self._condition:
            if self._state is not QuiesceState.WARMING:
                return self._transition_locked(
                    QuiesceTransitionCode.WARMUP_UNAVAILABLE,
                    achieved=False,
                )
            self._vram_released = False
            self._failure_reason = failure_reason
            return self._transition_locked(
                QuiesceTransitionCode.RESUME_RECOVERY_FAILED,
                achieved=False,
            )
    def _snapshot_locked(self) -> QuiesceSnapshot:
        active_tickets = len(self._active_ticket_epochs)
        admissions_open = self._state is QuiesceState.RUNNING
        drain_complete = self._state is not QuiesceState.RUNNING and active_tickets == 0
        safe_to_borrow_gpu = (
            self._state is QuiesceState.QUIESCED
            and self._vram_released
            and active_tickets == 0
        )
        return QuiesceSnapshot(
            state=self._state,
            admission_epoch=self._admission_epoch,
            admissions_open=admissions_open,
            active_compute_tickets=active_tickets,
            drain_complete=drain_complete,
            vram_released=self._vram_released,
            safe_to_borrow_gpu=safe_to_borrow_gpu,
            pause_requested_at=self._pause_requested_at,
            drain_acknowledged_at=self._drain_acknowledged_at,
            quiesced_at=self._quiesced_at,
            warming_started_at=self._warming_started_at,
            failure_reason=self._failure_reason,
        )

    def _transition_locked(
        self,
        code: QuiesceTransitionCode,
        *,
        achieved: bool,
    ) -> QuiesceTransition:
        return QuiesceTransition(
            code=code,
            achieved=achieved,
            snapshot=self._snapshot_locked(),
        )


def _require_reason(reason: str) -> str:
    """Reject empty failure evidence instead of publishing an opaque failure."""
    normalized = reason.strip()
    if not normalized:
        raise ValueError("failure reason must not be empty")
    return normalized
