"""What the borrower coordinator tells an operator about a pause or a resume.

Each case hands the coordinator's message helpers the envelope a service sends,
or none, and reads back the sentence the operator gets. The helpers are pure,
so the envelopes here are the values a service publishes rather than a service.
"""

from __future__ import annotations

import pytest


def _envelope(**overrides: object) -> dict[str, object]:
    """Build the canonical quiesce envelope this build publishes."""
    from ..cli._gpu_lease import QUIESCE_ENVELOPE_FIELDS

    defaults: dict[str, object] = {
        "state": "running",
        "admission_epoch": 1,
        "admissions_open": True,
        "active_compute_tickets": 0,
        "drain_complete": False,
        "vram_released": False,
        "safe_to_borrow_gpu": False,
        "borrower_bound": False,
        "pause_requested_at": None,
        "drain_acknowledged_at": None,
        "quiesced_at": None,
        "warming_started_at": None,
        "failure_reason": None,
    }
    assert frozenset(defaults) == QUIESCE_ENVELOPE_FIELDS, (
        "the fixture envelope must track the contract it stands in for"
    )
    return defaults | overrides


@pytest.mark.unit
def test_a_skewed_quiesce_envelope_is_named_as_a_build_mismatch() -> None:
    """A different build's envelope must not read as a refused transition.

    The transition checks compare the field set exactly, which is correct: a
    partial snapshot must never pass for a safe handoff. But that comparison
    cannot, on its own, tell a service that refused to quiesce from one that
    quiesced and said so in a vocabulary this build does not know. Both used to
    surface as "the service did not acknowledge borrower pause", sending the
    reader to debug quiescence when the actual condition was two builds of the
    same service disagreeing - and the transition may already have succeeded.
    """
    from ..cli._gpu_lease import BorrowGPUError, _reject_unrecognised_quiesce

    older = _envelope()
    del older["borrower_bound"]
    with pytest.raises(BorrowGPUError) as failure:
        _reject_unrecognised_quiesce({"ok": True, "quiesce": older}, verb="resume")
    assert failure.value.error == "borrow_gpu_quiesce_contract_mismatch"
    assert "borrower_bound" in str(failure.value)
    assert "same install" in str(failure.value)

    newer = _envelope(some_future_field=True)
    with pytest.raises(BorrowGPUError) as newer_failure:
        _reject_unrecognised_quiesce({"ok": True, "quiesce": newer}, verb="pause")
    assert "some_future_field" in str(newer_failure.value)


@pytest.mark.unit
def test_a_matching_envelope_is_left_to_the_transition_check() -> None:
    """The mismatch guard must not usurp the judgement it precedes.

    A refused transition on a recognised envelope is still a refused
    transition, and has to keep reaching the acknowledgement check rather than
    being relabelled a build mismatch.
    """
    from ..cli._gpu_lease import (
        _acknowledged_transition,
        _reject_unrecognised_quiesce,
    )
    from ..service_quiesce import QuiesceState

    refused: dict[str, object] = {
        "ok": False,
        "quiesce": _envelope(state="running"),
    }
    _reject_unrecognised_quiesce(refused, verb="pause")
    assert not _acknowledged_transition(refused, QuiesceState.QUIESCED)

    _reject_unrecognised_quiesce(None, verb="resume")
    _reject_unrecognised_quiesce({"ok": True}, verb="resume")


@pytest.mark.unit
def test_a_busy_service_is_told_to_wait_not_that_pause_failed() -> None:
    """A draining service and a broken one must not read the same.

    "The service did not acknowledge borrower pause" is true of every refusal,
    so it says nothing about the one that actually happens: the service was
    mid-index and could not hand over the device yet. That clears on its own,
    but the flat message gives the reader no way to tell it apart from a fault,
    and the envelope already carries the answer.
    """
    from ..cli._gpu_lease import _pause_refusal_message

    busy = _pause_refusal_message(
        {"ok": True, "quiesce": _envelope(state="running", active_compute_tickets=3)}
    )
    assert "3 compute tickets" in busy
    assert "retry" in busy

    one = _pause_refusal_message(
        {"ok": True, "quiesce": _envelope(active_compute_tickets=1)}
    )
    assert "1 compute ticket" in one

    stuck = _pause_refusal_message(
        {"ok": True, "quiesce": _envelope(state="pausing", active_compute_tickets=0)}
    )
    assert "'pausing'" in stuck

    assert (
        _pause_refusal_message(None)
        == "The service did not acknowledge borrower pause."
    )


@pytest.mark.unit
def test_a_refusal_the_service_named_reaches_the_operator_unchanged() -> None:
    """A quiesced service that still refuses has a reason only it knows.

    A loan it could not record - an anchor another account created and left
    unwritable - looks, from the snapshot alone, exactly like a pause that was
    never acknowledged, and the operator is told to debug quiescence while the
    actual condition is a permission on a file. The service names it; this
    side must not paper over the name with a sentence true of every refusal.

    Mutation check: dropped the named-refusal branch, the shape this had.
    Observed this assertion fail on the generic "reached a quiesced state but
    did not acknowledge" sentence arriving instead.
    """
    from ..cli._gpu_lease import _pause_refusal_message

    refused = _pause_refusal_message(
        {
            "ok": False,
            "status": "borrower_gpu_not_lendable",
            "error": "borrower_gpu_not_lendable",
            "message": (
                "The service paused for this borrower but could not lend it "
                "the GPU, because another process owns the GPU or the loan "
                "could not be recorded, so the GPU must not be used."
            ),
            "quiesce": _envelope(state="quiesced", active_compute_tickets=0),
        }
    )

    assert "could not lend it the GPU" in refused
    assert "did not acknowledge" not in refused


@pytest.mark.unit
def test_a_resume_that_found_no_service_is_not_called_a_refusal() -> None:
    """A service that is gone has no pause to clear, and must not read as one.

    "The service did not acknowledge borrower resume" was the whole message for
    every outcome, so a session that ended after its service had been stopped
    read exactly like a service that refused the resume - and sent the reader to
    the refusal log lines of an unrelated request. Nothing answered, and the
    message has to say that.

    Mutation check: answered ``None`` with the generic sentence, the shape this
    had. Observed the first assertion fail on "could not be reached" being
    absent from it; the stopped-service coordinator test fails on the same
    assertion.
    """
    from ..cli._gpu_lease import _resume_refusal_message

    gone = _resume_refusal_message(None)

    assert "could not be reached" in gone
    assert "comes up running" in gone
    assert "did not acknowledge" not in gone


@pytest.mark.unit
def test_a_resume_refusal_the_service_named_reaches_the_operator_unchanged() -> None:
    """A service that refuses the resume says why, and only it can.

    A different borrower holding the pause and a lease the service could not
    verify both come back as the same non-running answer, with opposite
    remedies. The service names which one; this side must not replace the name
    with a sentence true of both.

    Mutation check: dropped the named-refusal branch. Observed this assertion
    fail on the still-held sentence arriving instead of the service's own; the
    refused-resume coordinator test fails on "does not match the live lease".
    """
    from ..cli._gpu_lease import _resume_refusal_message

    refused = _resume_refusal_message(
        {
            "ok": False,
            "status": "borrower_lease_mismatch",
            "error": "borrower_lease_mismatch",
            "message": (
                "A different borrower already holds this pause, so this "
                "capability cannot act on it."
            ),
            "quiesce": _envelope(state="quiesced", borrower_bound=True),
        }
    )

    assert refused == (
        "A different borrower already holds this pause, so this capability "
        "cannot act on it."
    )


@pytest.mark.unit
def test_a_resume_that_left_the_service_held_names_the_state_it_is_in() -> None:
    """An answer without a named refusal still says what the service is doing.

    Mutation check: dropped the state branch. Observed this assertion fail on
    the generic sentence arriving with no state in it.
    """
    from ..cli._gpu_lease import _resume_refusal_message

    held = _resume_refusal_message(
        {"ok": False, "quiesce": _envelope(state="warming", admissions_open=False)}
    )
    assert "'warming'" in held

    assert (
        _resume_refusal_message({"ok": False})
        == "The service did not acknowledge borrower resume."
    )
