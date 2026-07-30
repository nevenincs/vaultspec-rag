"""Shared waits for tests that drive real registry quiesce transitions."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..service import ServiceRegistry
    from ..service_quiesce import QuiesceState

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
