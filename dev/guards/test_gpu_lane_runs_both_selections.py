"""A red resident tier must not hide the spawned-service tier.

``test gpu`` is two sequential pytest selections. Without ``keep_going`` the
runner stops at the first failing step, so a failure in the first selection
leaves the second never run and never reported - the lane then reads as one
red tier when two were owed a verdict.

The live target is driven for real: its gate is opened and its two pytest
steps are swapped for subprocesses with a known outcome, so the only thing
under test is how the registered target is configured.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from dev.__main__ import _execute
from dev.runner import Cmd
from dev.toolchain import VERBS, Target, Verb

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: Distinct from pytest's own statuses, so the assertion names this step.
FIRST_STAGE_FAILURE = 3


def _gpu_lane() -> tuple[Verb, Target]:
    verb = next(verb for verb in VERBS if verb.name == "test")
    target = verb.find("gpu")
    assert target is not None
    return verb, target


def _marker_step(marker: Path) -> Cmd:
    return Cmd(
        (
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
        )
    )


def test_a_red_first_selection_does_not_hide_the_second(tmp_path: Path) -> None:
    """The second selection runs and the lane still exits with the first failure.

    Mutation proof: removing ``keep_going`` from the ``gpu`` target stops the
    runner after the failing step, so the marker is never written and the first
    assertion fails; restoring it passes.
    """
    verb, target = _gpu_lane()
    marker = tmp_path / "second-selection-ran"
    failing = Cmd((sys.executable, "-c", f"raise SystemExit({FIRST_STAGE_FAILURE})"))
    driven = replace(target, gate=None, steps=(failing, _marker_step(marker)))

    code = _execute(verb, driven)

    assert marker.exists(), "the second selection never ran after the first failed"
    assert code == FIRST_STAGE_FAILURE


def test_a_red_second_selection_fails_the_lane(tmp_path: Path) -> None:
    """Running past a failure never turns the lane green."""
    verb, target = _gpu_lane()
    marker = tmp_path / "first-selection-ran"
    failing = Cmd((sys.executable, "-c", f"raise SystemExit({FIRST_STAGE_FAILURE})"))
    driven = replace(target, gate=None, steps=(_marker_step(marker), failing))

    code = _execute(verb, driven)

    assert marker.exists()
    assert code == FIRST_STAGE_FAILURE
