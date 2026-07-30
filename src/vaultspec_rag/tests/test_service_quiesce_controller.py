"""CPU-only behavior tests for serialized service-quiesce admission."""

from __future__ import annotations

import threading

import pytest

from ..service_quiesce import (
    QuiesceAdmissionClosedError,
    QuiesceState,
    QuiesceTransition,
    QuiesceTransitionCode,
    ServiceQuiesceController,
)

pytestmark = [pytest.mark.unit]

_HANDOFF_TIMEOUT = 5.0


def test_pause_drain_quiesce_warm_and_resume_transitions() -> None:
    """A completed lifecycle reopens admission only in its next epoch."""
    controller = ServiceQuiesceController()
    first_ticket = controller.acquire_ticket()

    started_pause = controller.begin_pause()

    assert not started_pause.snapshot.admissions_open

    assert first_ticket.release()
    drained = controller.wait_for_drain(timeout=0)
    quiesced = controller.acknowledge_vram_released()
    warming = controller.begin_warming()
    resumed = controller.complete_warming()
    second_ticket = controller.acquire_ticket()
    try:
        assert started_pause.code is QuiesceTransitionCode.PAUSE_STARTED
        assert started_pause.snapshot.state is QuiesceState.PAUSING
        assert drained.code is QuiesceTransitionCode.DRAINED
        assert quiesced.code is QuiesceTransitionCode.QUIESCED
        assert quiesced.snapshot.safe_to_borrow_gpu
        assert warming.code is QuiesceTransitionCode.WARMING_STARTED
        assert resumed.code is QuiesceTransitionCode.RUNNING
        assert second_ticket.admission_epoch == first_ticket.admission_epoch + 1
    finally:
        second_ticket.release()


def test_drain_waits_for_every_pre_pause_ticket_in_release_order() -> None:
    """A real condition waiter returns only after the final ticket releases."""
    controller = ServiceQuiesceController()
    first_ticket = controller.acquire_ticket()
    second_ticket = controller.acquire_ticket()
    waiter_started = threading.Event()
    waiter_finished = threading.Event()
    result: list[QuiesceTransition] = []

    assert controller.begin_pause().code is QuiesceTransitionCode.PAUSE_STARTED

    def wait_for_drain() -> None:
        waiter_started.set()
        result.append(controller.wait_for_drain(timeout=_HANDOFF_TIMEOUT))
        waiter_finished.set()

    waiter = threading.Thread(target=wait_for_drain, name="quiesce-drain-waiter")
    waiter.start()
    try:
        assert waiter_started.wait(timeout=_HANDOFF_TIMEOUT)
        assert not waiter_finished.wait(timeout=0.05)
        assert first_ticket.release()
        assert not waiter_finished.wait(timeout=0.05)
        assert second_ticket.release()
        assert waiter_finished.wait(timeout=_HANDOFF_TIMEOUT)
    finally:
        first_ticket.release()
        second_ticket.release()
        waiter.join(timeout=_HANDOFF_TIMEOUT)

    assert not waiter.is_alive()
    assert len(result) == 1
    transition = result[0]
    assert transition.code is QuiesceTransitionCode.DRAINED
    assert transition.achieved
    assert transition.snapshot.active_compute_tickets == 0
    assert transition.snapshot.drain_complete


def test_repeated_release_and_lifecycle_requests_are_idempotent() -> None:
    """Duplicate control calls preserve the achieved lifecycle state."""
    controller = ServiceQuiesceController()
    ticket = controller.acquire_ticket()

    assert controller.begin_pause().code is QuiesceTransitionCode.PAUSE_STARTED
    assert controller.begin_pause().code is QuiesceTransitionCode.ALREADY_PAUSING
    assert ticket.release()
    assert not ticket.release()
    assert controller.wait_for_drain(timeout=0).code is QuiesceTransitionCode.DRAINED
    assert controller.acknowledge_vram_released().code is QuiesceTransitionCode.QUIESCED
    assert (
        controller.acknowledge_vram_released().code
        is QuiesceTransitionCode.ALREADY_QUIESCED
    )
    assert controller.begin_pause().code is QuiesceTransitionCode.ALREADY_QUIESCED
    assert controller.begin_warming().code is QuiesceTransitionCode.WARMING_STARTED
    assert controller.begin_warming().code is QuiesceTransitionCode.ALREADY_WARMING


def test_drain_timeout_keeps_admission_closed_and_gpu_borrowing_unsafe() -> None:
    """A timed-out drain fails closed until a later acknowledged drain."""
    controller = ServiceQuiesceController()
    ticket = controller.acquire_ticket()

    assert controller.begin_pause().code is QuiesceTransitionCode.PAUSE_STARTED
    timed_out = controller.wait_for_drain(timeout=0)

    assert timed_out.code is QuiesceTransitionCode.DRAIN_TIMED_OUT
    assert not timed_out.achieved
    assert timed_out.snapshot.state is QuiesceState.PAUSING
    assert not timed_out.snapshot.admissions_open
    assert not timed_out.snapshot.drain_complete
    assert not timed_out.snapshot.safe_to_borrow_gpu
    assert timed_out.snapshot.failure_reason == "compute_ticket_drain_timed_out"
    with pytest.raises(QuiesceAdmissionClosedError):
        controller.acquire_ticket()
    assert (
        controller.acknowledge_vram_released().code
        is QuiesceTransitionCode.QUIESCE_UNAVAILABLE
    )

    assert ticket.release()
    assert controller.wait_for_drain(timeout=0).code is QuiesceTransitionCode.DRAINED
    assert controller.acknowledge_vram_released().code is QuiesceTransitionCode.QUIESCED


def test_a_failed_transition_records_only_the_direction_its_caller_owns() -> None:
    """A failure report names its own transition and never the live one."""
    controller = ServiceQuiesceController()

    assert controller.begin_pause().code is QuiesceTransitionCode.PAUSE_STARTED
    mismatched = controller.fail_transition(
        owned_state=QuiesceState.WARMING,
        reason="gpu_dependency_rebuild_failed",
    )
    failed_pause = controller.fail_transition(
        owned_state=QuiesceState.PAUSING,
        reason="gpu_dependency_release_failed",
    )

    assert mismatched.code is QuiesceTransitionCode.WARMUP_UNAVAILABLE
    assert mismatched.snapshot.failure_reason is None
    assert failed_pause.code is QuiesceTransitionCode.QUIESCE_FAILED
    assert not failed_pause.achieved
    assert failed_pause.snapshot.state is QuiesceState.PAUSING
    assert not failed_pause.snapshot.admissions_open
    assert not failed_pause.snapshot.safe_to_borrow_gpu
    assert failed_pause.snapshot.failure_reason == "gpu_dependency_release_failed"

    assert controller.wait_for_drain(timeout=0).code is QuiesceTransitionCode.DRAINED
    assert controller.acknowledge_vram_released().code is QuiesceTransitionCode.QUIESCED
    assert controller.begin_warming().code is QuiesceTransitionCode.WARMING_STARTED
    failed_warming = controller.fail_transition(
        owned_state=QuiesceState.WARMING,
        reason="gpu_dependency_rebuild_failed",
    )

    assert failed_warming.code is QuiesceTransitionCode.WARMUP_FAILED
    assert failed_warming.snapshot.state is QuiesceState.WARMING
    assert not failed_warming.snapshot.admissions_open
    assert not failed_warming.snapshot.safe_to_borrow_gpu
    assert failed_warming.snapshot.failure_reason == "gpu_dependency_rebuild_failed"
    with pytest.raises(ValueError, match="failure reason must not be empty"):
        controller.fail_transition(owned_state=QuiesceState.WARMING, reason="   ")
