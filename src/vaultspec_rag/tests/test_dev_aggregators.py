"""Guards that an aggregate target actually aggregates.

``test all`` once had a one-line body: run the ``python`` lane. It claimed
complete coverage, ran a quarter of it, and said nothing about the three lanes
it dropped. Nobody reading a green ``test all`` could tell. These guards make
that class of defect a test failure rather than a discovery.

The exemption list below is the whole point of the design: a lane may be left
out of its aggregate ONLY by being named here with a reason. Adding a target
without either joining the aggregate or claiming an exemption fails
:func:`test_every_target_is_reachable_from_its_aggregate`.
"""

from __future__ import annotations

import pytest

from dev import exit_codes, gates
from dev.__main__ import _execute
from dev.runner import Cmd, Ref
from dev.toolchain import VERBS, Target, Verb

#: Targets deliberately outside their verb's ``all``, and why. Each is a
#: SELECTION within a target that ``all`` already runs, so including it would
#: run the same tests twice rather than cover anything new. Both claims are
#: checked against real pytest collection by the marker guards in this tree.
EXEMPT: dict[tuple[str, str], str] = {
    ("test", "fast"): "the unit tier, a subset of the python lane",
    ("test", "provisioning"): "five files the python lane already collects",
}


def _aggregate_verbs() -> list[Verb]:
    """Return every verb that publishes an ``all`` target."""
    return [verb for verb in VERBS if verb.find("all") is not None]


@pytest.mark.unit
@pytest.mark.parametrize("verb", _aggregate_verbs(), ids=lambda v: v.name)
def test_every_target_is_reachable_from_its_aggregate(verb: Verb) -> None:
    """Every target either joins its verb's ``all`` or is exempted by name."""
    aggregate = verb.find("all")
    assert aggregate is not None
    referenced = {step.target for step in aggregate.steps if isinstance(step, Ref)}
    for target in verb.targets:
        if target.name == "all" or target.name.startswith("_"):
            continue
        if (verb.name, target.name) in EXEMPT:
            continue
        assert target.name in referenced, (
            f"'{verb.name} all' does not run '{target.name}'. Add it to the "
            f"aggregate, or record why it is a subset in EXEMPT."
        )


@pytest.mark.unit
def test_every_test_lane_is_named_in_the_aggregate() -> None:
    """The four real lanes are all wired into ``test all``, by name."""
    aggregate = next(v for v in VERBS if v.name == "test").find("all")
    assert aggregate is not None
    referenced = [step.target for step in aggregate.steps if isinstance(step, Ref)]
    assert referenced == ["python", "gpu", "mps", "perf"]


@pytest.mark.unit
def test_hardware_lanes_are_gated_rather_than_dropped() -> None:
    """Each lane needing hardware carries a gate, so it can report a skip.

    A lane with no gate cannot be skipped, only run - and this repository's
    conftest aborts a GPU tier on a GPU-less host rather than skipping it, so
    an ungated GPU lane inside the aggregate turns a laptop run red.
    """
    verb = next(v for v in VERBS if v.name == "test")
    for name in ("gpu", "mps", "perf"):
        target = verb.find(name)
        assert target is not None
        assert target.gate is not None, f"lane '{name}' has no gate"
        assert target.gate.reason.strip(), f"lane '{name}' skips without a reason"


@pytest.mark.unit
def test_all_skipped_aggregate_does_not_report_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An aggregate whose every lane skipped exits non-zero and says so.

    This is the assertion the whole gate exists for: a run that proved nothing
    must not be indistinguishable from a run that proved everything.
    """
    closed = gates.Gate("no hardware in this test", lambda: False)
    verb = Verb(
        name="test",
        summary="fixture",
        targets=(
            Target("one", "gated", (), gate=closed),
            Target("two", "gated", (), gate=closed),
            Target("all", "aggregate", (Ref("one"), Ref("two")), aggregate=True),
        ),
    )
    aggregate = verb.find("all")
    assert aggregate is not None

    code = _execute(verb, aggregate)

    assert code != 0
    assert code == exit_codes.NOTHING_SELECTED
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "SKIPPED" in combined
    assert "NOTHING RAN" in combined


@pytest.mark.unit
def test_aggregate_passes_when_one_lane_ran(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One lane running and the rest skipping is a pass, with the skips named."""
    verb = Verb(
        name="test",
        summary="fixture",
        targets=(
            Target("ran", "runs", ()),
            Target("gated", "gated", (), gate=gates.Gate("no hardware", lambda: False)),
            Target("all", "aggregate", (Ref("ran"), Ref("gated")), aggregate=True),
        ),
    )
    aggregate = verb.find("all")
    assert aggregate is not None

    assert _execute(verb, aggregate) == 0
    combined = capsys.readouterr().out
    assert "gated" in combined
    assert "SKIPPED" in combined


@pytest.mark.unit
def test_aggregate_stops_at_the_first_failing_lane(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A red lane fails the aggregate and the lanes after it do not run."""
    verb = Verb(
        name="test",
        summary="fixture",
        targets=(
            Target("red", "fails", (Cmd(("python", "-c", "raise SystemExit(7)")),)),
            Target("after", "never reached", ()),
            Target("all", "aggregate", (Ref("red"), Ref("after")), aggregate=True),
        ),
    )
    aggregate = verb.find("all")
    assert aggregate is not None

    assert _execute(verb, aggregate) == 7
    assert "not reached" in capsys.readouterr().out


@pytest.mark.unit
def test_a_directly_selected_gated_lane_reports_a_skip_not_a_pass() -> None:
    """A lane this host cannot run yields the skip marker, never 0.

    ``main`` maps that marker onto a non-zero status, so selecting ``just test
    gpu`` on a laptop cannot be mistaken for having run the GPU tier.
    """
    closed = gates.Gate("no hardware in this test", lambda: False)
    solo = Target("solo", "gated", (), gate=closed)
    verb = Verb("test", "fixture", (solo,))

    code = _execute(verb, solo)

    assert code == gates.SKIPPED
    assert code != 0
