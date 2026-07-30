"""Threaded CPU proofs for registry-owned resource-transition single flight."""

from __future__ import annotations

import threading
import time

import pytest

from ..service import ServiceRegistry
from ..service_quiesce import (
    QuiesceState,
    QuiesceTransition,
    QuiesceTransitionCode,
    ServiceQuiesceTransitionConflictError,
    ServiceQuiesceTransitionWaitTimeoutError,
)

pytestmark = [pytest.mark.unit]

_THREAD_TIMEOUT = 5.0


def _wait_for_state(registry: ServiceRegistry, state: QuiesceState) -> None:
    deadline = time.monotonic() + _THREAD_TIMEOUT
    while registry.quiesce_snapshot().state is not state:
        if time.monotonic() >= deadline:
            raise AssertionError(f"registry did not reach {state.value!r}")
        time.sleep(0.001)


def test_concurrent_pause_calls_share_one_terminal_transition() -> None:
    """Two callers drain one epoch and receive the same immutable outcome."""
    registry = ServiceRegistry()
    held_ticket = registry.acquire_compute_ticket()
    launch = threading.Barrier(3)
    outcomes: list[QuiesceTransition] = []

    def pause() -> None:
        launch.wait()
        outcomes.append(registry.quiesce_resources(timeout_seconds=_THREAD_TIMEOUT))

    workers = [
        threading.Thread(target=pause, name=f"pause-{index}") for index in range(2)
    ]
    for worker in workers:
        worker.start()
    launch.wait()
    try:
        _wait_for_state(registry, QuiesceState.PAUSING)
        held_ticket.release()
        for worker in workers:
            worker.join(timeout=_THREAD_TIMEOUT)
    finally:
        held_ticket.release()
        for worker in workers:
            worker.join(timeout=_THREAD_TIMEOUT)

    assert all(not worker.is_alive() for worker in workers)
    assert len(outcomes) == 2
    assert outcomes[0] is outcomes[1]
    assert outcomes[0].code is QuiesceTransitionCode.QUIESCED
    assert outcomes[0].snapshot.state is QuiesceState.QUIESCED
    assert outcomes[0].snapshot.safe_to_borrow_gpu


def test_terminal_transition_requests_are_successful_without_new_side_effects() -> None:
    """Already-quiesced and already-running calls publish their current evidence."""
    registry = ServiceRegistry()

    first_pause = registry.quiesce_resources(timeout_seconds=0)
    repeated_pause = registry.quiesce_resources(timeout_seconds=0)
    first_resume = registry.resume_resources(timeout_seconds=0)
    repeated_resume = registry.resume_resources(timeout_seconds=0)

    assert first_pause.code is QuiesceTransitionCode.QUIESCED
    assert repeated_pause.code is QuiesceTransitionCode.ALREADY_QUIESCED
    assert repeated_pause.snapshot == first_pause.snapshot
    assert first_resume.code is QuiesceTransitionCode.RUNNING
    assert repeated_resume.code is QuiesceTransitionCode.RUNNING
    assert repeated_resume.snapshot == first_resume.snapshot


def test_resume_conflicts_immediately_while_pause_is_owned() -> None:
    """An opposite request never queues behind an in-flight resource handoff."""
    registry = ServiceRegistry()
    held_ticket = registry.acquire_compute_ticket()
    completed: list[QuiesceTransition] = []

    def pause() -> None:
        completed.append(registry.quiesce_resources(timeout_seconds=_THREAD_TIMEOUT))

    worker = threading.Thread(target=pause, name="pause-owner")
    worker.start()
    try:
        _wait_for_state(registry, QuiesceState.PAUSING)
        with pytest.raises(ServiceQuiesceTransitionConflictError) as raised:
            registry.resume_resources(timeout_seconds=_THREAD_TIMEOUT)
        conflict = raised.value
        assert conflict.requested_direction == "resume"
        assert conflict.active_direction == "pause"
        assert conflict.snapshot.state is QuiesceState.PAUSING
        held_ticket.release()
        worker.join(timeout=_THREAD_TIMEOUT)
    finally:
        held_ticket.release()
        worker.join(timeout=_THREAD_TIMEOUT)

    assert not worker.is_alive()
    assert completed[0].code is QuiesceTransitionCode.QUIESCED


def test_joined_pause_shares_the_owner_drain_timeout() -> None:
    """A timed-out drain is one fail-closed outcome, not a second teardown."""
    registry = ServiceRegistry()
    held_ticket = registry.acquire_compute_ticket()
    outcomes: list[QuiesceTransition] = []

    def owner_pause() -> None:
        outcomes.append(registry.quiesce_resources(timeout_seconds=0.2))

    def follower_pause() -> None:
        outcomes.append(registry.quiesce_resources(timeout_seconds=_THREAD_TIMEOUT))

    owner = threading.Thread(target=owner_pause, name="pause-timeout-owner")
    follower = threading.Thread(target=follower_pause, name="pause-timeout-follower")
    owner.start()
    try:
        _wait_for_state(registry, QuiesceState.PAUSING)
        follower.start()
        owner.join(timeout=_THREAD_TIMEOUT)
        follower.join(timeout=_THREAD_TIMEOUT)
    finally:
        held_ticket.release()
        owner.join(timeout=_THREAD_TIMEOUT)
        follower.join(timeout=_THREAD_TIMEOUT)

    assert not owner.is_alive()
    assert not follower.is_alive()
    assert len(outcomes) == 2
    assert outcomes[0] is outcomes[1]
    assert outcomes[0].code is QuiesceTransitionCode.DRAIN_TIMED_OUT
    assert outcomes[0].snapshot.state is QuiesceState.PAUSING
    assert outcomes[0].snapshot.failure_reason == "compute_ticket_drain_timed_out"


def test_joined_resume_wait_is_bounded_without_changing_owner_truth() -> None:
    """A short join deadline cannot cancel or duplicate a real GPU rebuild."""
    registry = ServiceRegistry()
    assert registry.quiesce_resources(timeout_seconds=0).achieved
    assert registry.gpu_lock.acquire(timeout=_THREAD_TIMEOUT)
    owner_outcomes: list[QuiesceTransition] = []

    def resume() -> None:
        owner_outcomes.append(registry.resume_resources(timeout_seconds=_THREAD_TIMEOUT))

    owner = threading.Thread(target=resume, name="resume-bounded-owner")
    owner.start()
    try:
        _wait_for_state(registry, QuiesceState.WARMING)
        with pytest.raises(ServiceQuiesceTransitionWaitTimeoutError) as raised:
            registry.resume_resources(timeout_seconds=0)
        assert raised.value.direction == "resume"
        assert raised.value.snapshot.state is QuiesceState.WARMING
        registry.gpu_lock.release()
        owner.join(timeout=_THREAD_TIMEOUT)
    finally:
        if registry.gpu_lock.locked():
            registry.gpu_lock.release()
        owner.join(timeout=_THREAD_TIMEOUT)

    assert not owner.is_alive()
    assert owner_outcomes[0].code is QuiesceTransitionCode.RUNNING


def test_concurrent_resume_calls_share_one_terminal_transition() -> None:
    """A held real GPU lock proves follower resume waits without duplicate rebuild."""
    registry = ServiceRegistry()
    assert registry.quiesce_resources(timeout_seconds=0).achieved
    assert registry.gpu_lock.acquire(timeout=_THREAD_TIMEOUT)
    launch = threading.Barrier(3)
    outcomes: list[QuiesceTransition] = []

    def resume() -> None:
        launch.wait()
        outcomes.append(registry.resume_resources(timeout_seconds=_THREAD_TIMEOUT))

    workers = [
        threading.Thread(target=resume, name=f"resume-{index}") for index in range(2)
    ]
    for worker in workers:
        worker.start()
    launch.wait()
    try:
        _wait_for_state(registry, QuiesceState.WARMING)
        registry.gpu_lock.release()
        for worker in workers:
            worker.join(timeout=_THREAD_TIMEOUT)
    finally:
        if registry.gpu_lock.locked():
            registry.gpu_lock.release()
        for worker in workers:
            worker.join(timeout=_THREAD_TIMEOUT)

    assert all(not worker.is_alive() for worker in workers)
    assert len(outcomes) == 2
    assert outcomes[0] is outcomes[1]
    assert outcomes[0].code is QuiesceTransitionCode.RUNNING
    assert outcomes[0].snapshot.state is QuiesceState.RUNNING
