"""CPU-only behavior tests for serialized service-quiesce admission."""

from __future__ import annotations

import threading
from typing import get_args

import pytest

from ..service_quiesce import (
    QuiesceAdmissionClosedError,
    QuiesceState,
    QuiesceTransition,
    QuiesceTransitionCode,
    ServiceQuiesceController,
    TerminalFailureCode,
    _failure_targets,
    _pin_terminal_failure_codes,
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


def test_resume_recovery_failure_keeps_warming_closed_and_unsafe() -> None:
    """A durable recovery failure is truthful without inventing a fifth state."""
    controller = ServiceQuiesceController()

    # A terminal code never narrows the unavailable answer: this report
    # arrives while the controller is still running, so it is answered for the
    # transition that code requires and not as a recovery failure.
    late = controller.fail_transition(
        code=QuiesceTransitionCode.RESUME_RECOVERY_FAILED,
        reason="job_resume_persistence_failed",
    )

    assert late.code is QuiesceTransitionCode.WARMUP_UNAVAILABLE
    assert late.snapshot.failure_reason is None

    assert controller.begin_pause().achieved is False
    assert controller.wait_for_drain(timeout=0).achieved
    assert controller.acknowledge_vram_released().achieved
    assert controller.begin_warming().snapshot.state is QuiesceState.WARMING

    failed = controller.fail_transition(
        code=QuiesceTransitionCode.RESUME_RECOVERY_FAILED,
        reason="job_resume_persistence_failed",
    )

    assert failed.code is QuiesceTransitionCode.RESUME_RECOVERY_FAILED
    assert not failed.achieved
    assert failed.snapshot.state is QuiesceState.WARMING
    assert not failed.snapshot.admissions_open
    assert not failed.snapshot.safe_to_borrow_gpu
    assert failed.snapshot.failure_reason == "job_resume_persistence_failed"
    with pytest.raises(QuiesceAdmissionClosedError):
        controller.acquire_ticket()


def test_failure_transition_records_its_matching_terminal_code() -> None:
    """A matching failure report keeps its transition closed and unsafe."""
    controller = ServiceQuiesceController()

    assert controller.begin_pause().code is QuiesceTransitionCode.PAUSE_STARTED
    failed_pause = controller.fail_transition(
        code=QuiesceTransitionCode.QUIESCE_FAILED,
        reason="gpu_dependency_release_failed",
    )

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
        code=QuiesceTransitionCode.WARMUP_FAILED,
        reason="gpu_dependency_rebuild_failed",
    )

    assert failed_warming.code is QuiesceTransitionCode.WARMUP_FAILED
    assert failed_warming.snapshot.state is QuiesceState.WARMING
    assert not failed_warming.snapshot.admissions_open
    assert not failed_warming.snapshot.safe_to_borrow_gpu
    assert failed_warming.snapshot.failure_reason == "gpu_dependency_rebuild_failed"
    with pytest.raises(ValueError, match="failure reason must not be empty"):
        controller.fail_transition(
            code=QuiesceTransitionCode.RESUME_RECOVERY_FAILED,
            reason="   ",
        )


def test_failure_transition_refuses_every_code_from_the_wrong_state() -> None:
    """A stale failure report cannot overwrite the controller's live truth."""
    controller = ServiceQuiesceController()

    wrong_pause = controller.fail_transition(
        code=QuiesceTransitionCode.QUIESCE_FAILED,
        reason="gpu_dependency_release_failed",
    )
    wrong_warmup = controller.fail_transition(
        code=QuiesceTransitionCode.WARMUP_FAILED,
        reason="gpu_dependency_rebuild_failed",
    )
    wrong_recovery = controller.fail_transition(
        code=QuiesceTransitionCode.RESUME_RECOVERY_FAILED,
        reason="job_resume_persistence_failed",
    )

    assert wrong_pause.code is QuiesceTransitionCode.QUIESCE_UNAVAILABLE
    assert wrong_warmup.code is QuiesceTransitionCode.WARMUP_UNAVAILABLE
    assert wrong_recovery.code is QuiesceTransitionCode.WARMUP_UNAVAILABLE
    for transition in (wrong_pause, wrong_warmup, wrong_recovery):
        assert not transition.achieved
        assert transition.snapshot.state is QuiesceState.RUNNING
        assert transition.snapshot.admissions_open
        assert transition.snapshot.failure_reason is None


def test_abort_pause_reopens_the_epoch_a_failed_pause_closed() -> None:
    """A drain that timed out is not a terminal state for the whole daemon."""
    controller = ServiceQuiesceController()
    stuck_ticket = controller.acquire_ticket()
    controller.begin_pause()
    timed_out = controller.wait_for_drain(timeout=0)
    aborted = controller.abort_pause()
    readmitted = controller.acquire_ticket()
    try:
        assert timed_out.code is QuiesceTransitionCode.DRAIN_TIMED_OUT
        assert timed_out.snapshot.state is QuiesceState.PAUSING
        assert aborted.code is QuiesceTransitionCode.PAUSE_ABORTED
        assert aborted.achieved
        assert aborted.snapshot.state is QuiesceState.RUNNING
        assert aborted.snapshot.admissions_open
        assert aborted.snapshot.failure_reason is None
        assert not aborted.snapshot.safe_to_borrow_gpu
        # The abort reopens the generation it never finished closing, so the
        # ticket it failed to drain is still the current epoch's to release.
        assert readmitted.admission_epoch == stuck_ticket.admission_epoch
        assert stuck_ticket.release()
    finally:
        readmitted.release()


def test_abort_pause_is_idempotent_and_refuses_a_completed_pause() -> None:
    """Only ``pausing`` is abortable; a real quiesce is released by warming."""
    controller = ServiceQuiesceController()
    already_running = controller.abort_pause()
    controller.begin_pause()
    controller.wait_for_drain(timeout=0)
    controller.acknowledge_vram_released()
    refused = controller.abort_pause()

    assert already_running.code is QuiesceTransitionCode.RUNNING
    assert already_running.achieved
    assert already_running.snapshot.state is QuiesceState.RUNNING
    assert refused.code is QuiesceTransitionCode.PAUSE_ABORT_UNAVAILABLE
    assert not refused.achieved
    assert refused.snapshot.state is QuiesceState.QUIESCED
    assert refused.snapshot.safe_to_borrow_gpu


def test_terminal_failure_codes_match_the_enum_naming_rule() -> None:
    """Every ``_FAILED`` member is accepted by ``fail_transition``, nothing else."""
    named = {code for code in QuiesceTransitionCode if code.name.endswith("_FAILED")}

    accepted = set(get_args(TerminalFailureCode))

    assert accepted == named
    assert named == {
        QuiesceTransitionCode.QUIESCE_FAILED,
        QuiesceTransitionCode.WARMUP_FAILED,
        QuiesceTransitionCode.RESUME_RECOVERY_FAILED,
    }


def test_every_accepted_terminal_failure_code_has_a_failure_target() -> None:
    """No accepted code reaches ``fail_transition`` without a failure target."""
    targets = {code: _failure_targets(code) for code in get_args(TerminalFailureCode)}

    assert targets == {
        QuiesceTransitionCode.QUIESCE_FAILED: (
            QuiesceState.PAUSING,
            QuiesceTransitionCode.QUIESCE_UNAVAILABLE,
        ),
        QuiesceTransitionCode.WARMUP_FAILED: (
            QuiesceState.WARMING,
            QuiesceTransitionCode.WARMUP_UNAVAILABLE,
        ),
        QuiesceTransitionCode.RESUME_RECOVERY_FAILED: (
            QuiesceState.WARMING,
            QuiesceTransitionCode.WARMUP_UNAVAILABLE,
        ),
    }


def test_import_time_pin_accepts_the_shipped_vocabulary() -> None:
    """The import-time drift guard passes against the shipped enum."""
    _pin_terminal_failure_codes()
