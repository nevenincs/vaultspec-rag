"""The operator surfaces for a deliberately held service.

A pause that renders as a fault sends every reader to a repair command for a
service with nothing wrong with it, and a pause whose remediation is guessed
sends them to a verb that can only refuse. These cover the rows an operator
actually reads and the fields a structured caller actually parses.
"""

from __future__ import annotations

import json

import pytest
import typer

from ..cli._render import _display_service_error
from ..cli._status_labels import _status_busy_label, _status_health_label
from ..cli._status_render import _status_next_action

pytestmark = [pytest.mark.unit]


def _held_health(*, borrower_bound: bool) -> dict[str, object]:
    """A health payload for a held service, as the daemon publishes one."""
    return {
        "status": "paused",
        "quiesce": {"state": "quiesced", "borrower_bound": borrower_bound},
    }


class TestHeldConditionRows:
    """The condition rows name the hold rather than describing its effects."""

    def test_an_operator_hold_says_it_is_paused(self) -> None:
        label = _status_health_label(
            _held_health(borrower_bound=False),
            port_listening=True,
        )

        assert "paused" in label

    def test_a_borrower_hold_says_it_is_not_the_operators_to_release(self) -> None:
        label = _status_health_label(
            _held_health(borrower_bound=True),
            port_listening=True,
        )

        assert "borrower" in label

    def test_held_work_is_reported_held_rather_than_idle(self) -> None:
        """Held jobs report neither running nor queued, which read as idle."""
        jobs: dict[str, object] = {
            "available": True,
            "running": 0,
            "queued": 0,
            "phases": {"paused": 4, "done": 257},
        }

        label = _status_busy_label(jobs)

        assert label != "idle"
        assert "4" in label

    def test_a_service_with_no_held_work_is_still_idle(self) -> None:
        """The held row must not claim work that does not exist."""
        jobs: dict[str, object] = {
            "available": True,
            "running": 0,
            "queued": 0,
            "phases": {"done": 257},
        }

        assert _status_busy_label(jobs) == "idle"


class TestHeldRemediation:
    """Only a command that can end the hold is offered."""

    def test_an_operator_hold_offers_resume(self) -> None:
        action = _status_next_action(
            "running",
            _held_health(borrower_bound=False),
            {},
            port=8766,
        )

        assert "resume" in action

    def test_a_borrower_hold_offers_nothing(self) -> None:
        """Resume here would only ever return a refusal, so it is not offered."""
        action = _status_next_action(
            "running",
            _held_health(borrower_bound=True),
            {},
            port=8766,
        )

        assert action == ""


class TestStructuredFailureForwarding:
    """What the service published about a failure reaches the caller."""

    def test_retryability_and_the_controller_block_survive_the_cli(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Both used to be dropped by a fixed allowlist of forwarded keys."""
        payload: dict[str, object] = {
            "ok": False,
            "error": "quiesce_admission_closed",
            "message": "Search is temporarily unavailable.",
            "retryable": True,
            "quiesce": {"state": "quiesced", "borrower_bound": False},
        }

        with pytest.raises(typer.Exit):
            _display_service_error(payload, json_mode=True, command="search")

        emitted = json.loads(capsys.readouterr().out.strip())
        assert emitted["retryable"] is True
        assert emitted["quiesce"]["state"] == "quiesced"

    def test_a_field_the_cli_has_never_heard_of_is_forwarded(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exclusion is the point: an allowlist drops every future field."""
        payload: dict[str, object] = {
            "ok": False,
            "error": "some_error",
            "message": "something went wrong",
            "a_field_invented_after_this_test_was_written": 42,
        }

        with pytest.raises(typer.Exit):
            _display_service_error(payload, json_mode=True, command="search")

        emitted = json.loads(capsys.readouterr().out.strip())
        assert emitted["a_field_invented_after_this_test_was_written"] == 42
