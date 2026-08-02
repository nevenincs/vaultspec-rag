"""Shared waits for tests that drive real registry quiesce transitions."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ..service_quiesce import QuiesceSnapshot, QuiesceState

if TYPE_CHECKING:
    from ..service import ServiceRegistry

QUIESCE_THREAD_TIMEOUT = 5.0


def wait_for_quiesce_state(
    registry: ServiceRegistry,
    state: QuiesceState,
    *,
    timeout: float = QUIESCE_THREAD_TIMEOUT,
) -> None:
    """Block until *registry* observes *state*, or fail the calling test.

    Every controller state change happens after its transition owner has
    already claimed the registry's single-flight slot, so reaching a state is
    also the signal that a competing caller will now join or conflict rather
    than become the owner itself.
    """
    deadline = time.monotonic() + timeout
    while registry.quiesce_snapshot().state is not state:
        if time.monotonic() >= deadline:
            raise AssertionError(f"registry did not reach {state.value!r}")
        time.sleep(0.001)


def running_quiesce_snapshot() -> QuiesceSnapshot:
    """Return the controller snapshot of a service that is not held.

    Health-verdict tests are about infrastructure degradation, not about the
    pause, so they all want the same "nothing is holding this service" input.
    Building it here keeps a controller field addition from rippling through
    every one of them.
    """
    return QuiesceSnapshot(
        state=QuiesceState.RUNNING,
        admission_epoch=1,
        admissions_open=True,
        active_compute_tickets=0,
        drain_complete=False,
        vram_released=False,
        safe_to_borrow_gpu=False,
        pause_requested_at=None,
        drain_acknowledged_at=None,
        quiesced_at=None,
        warming_started_at=None,
        failure_reason=None,
    )


def held_quiesce_snapshot(*, borrower_bound: bool = False) -> QuiesceSnapshot:
    """Return the controller snapshot of a service deliberately held.

    Mirrors what pause actually publishes: admissions closed, drain finished,
    and GPU residency released. That last part is the point - the released
    residency is why a held service used to be reported as degraded.
    """
    return QuiesceSnapshot(
        state=QuiesceState.QUIESCED,
        admission_epoch=2,
        admissions_open=False,
        active_compute_tickets=0,
        drain_complete=True,
        vram_released=True,
        safe_to_borrow_gpu=True,
        pause_requested_at=1.0,
        drain_acknowledged_at=2.0,
        quiesced_at=3.0,
        warming_started_at=None,
        failure_reason=None,
        borrower_bound=borrower_bound,
    )
