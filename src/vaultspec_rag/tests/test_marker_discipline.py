"""Guard: every test declares exactly one lane, and the gate enforces it.

The fast lane is selected by EXCLUDING the slow tiers rather than by naming the
fast one, so an unclassified test is not skipped - it is silently pulled into
the fast lane and run on a machine that may have neither a GPU nor a token. The
inverse costs just as much: a module-level ``pytestmark`` is ADDED to a test's
own decorator rather than overridden by it, so a blanket module default drags
GPU tests into ``-m unit``.

Both directions are enforced at collection time from the root conftest, so the
enforcement runs on every pytest invocation rather than only where someone
remembered to add a gate. The same gate module refuses to spread a GPU-bound
selection across worker processes, which one card cannot survive. These tests
exercise that enforcement directly; the mutation each one catches is named in
its own docstring.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import pytest

from ._tier_gate import (
    SLOW_TIERS,
    distributed_worker_count,
    enforce_serial_gpu_lane,
    enforce_tiers,
    selectable_slow_tiers,
    selected_tiers,
    tier_violations,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]


class _FakeMark:
    """Stands in for a pytest ``Mark``, which carries only a name here."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeItem:
    """Stands in for a collected item: a node id and the marks it carries."""

    def __init__(self, nodeid: str, *marker_names: str) -> None:
        self.nodeid = nodeid
        self._marks = [_FakeMark(name) for name in marker_names]

    def iter_markers(self) -> Iterator[_FakeMark]:
        return iter(self._marks)


class TestTierClassification:
    """The classification behind the gate."""

    def test_a_test_with_no_tier_is_reported(self) -> None:
        """The whole point: an unclassified test must not pass unnoticed.

        Mutation it catches: dropping the ``not names & TIER_MARKERS`` branch
        from ``tier_violations``. Every unmarked test would then be accepted and
        would run in the fast lane on hardware that cannot satisfy it.
        """
        untiered, contradictory = tier_violations([_FakeItem("t.py::test_nothing")])

        assert untiered == ["t.py::test_nothing"]
        assert contradictory == []

    def test_a_timeout_marker_alone_is_not_a_tier(self) -> None:
        """Modifiers are not tiers, or the gate passes on decoration alone.

        Mutation it catches: widening ``TIER_MARKERS`` to every registered
        marker. ``timeout`` and ``xdist_group`` say nothing about which lane a
        test belongs to, and accepting them would let an unclassified test pass
        merely because it declared a timeout.
        """
        untiered, _ = tier_violations(
            [_FakeItem("t.py::test_slow", "timeout", "xdist_group")]
        )

        assert untiered == ["t.py::test_slow"]

    @pytest.mark.parametrize(
        "tier",
        [
            "unit",
            "integration",
            "cuda",
            "subprocess_gpu",
            "performance",
            "quality",
            "robustness",
        ],
    )
    def test_each_declared_tier_satisfies_the_gate(self, tier: str) -> None:
        """Every registered tier must be accepted, or the gate blocks real work."""
        untiered, contradictory = tier_violations([_FakeItem("t.py::test_x", tier)])

        assert untiered == []
        assert contradictory == []

    def test_fast_tier_beside_a_slow_tier_is_reported(self) -> None:
        """The blanket-pytestmark trap, which has bitten this repo four times.

        Mutation it catches: dropping the ``FAST_TIER in names and names &
        SLOW_TIERS`` branch. A module-level ``pytestmark = [pytest.mark.unit]``
        would then silently add ``unit`` to GPU tests in that module, and
        ``-m unit`` would schedule them on a machine with no device.
        """
        _, contradictory = tier_violations(
            [_FakeItem("t.py::test_gpu", "unit", "integration")]
        )

        assert contradictory == ["t.py::test_gpu"]

    def test_two_slow_tiers_together_are_allowed(self) -> None:
        """integration+subprocess_gpu is a real, intended combination.

        Mutation it catches: rejecting any test carrying more than one tier.
        That would fail the existing GPU suite, which deliberately pairs
        ``integration`` with ``subprocess_gpu`` and with ``quality``.
        """
        untiered, contradictory = tier_violations(
            [_FakeItem("t.py::test_gpu", "integration", "subprocess_gpu")]
        )

        assert untiered == []
        assert contradictory == []


class TestGateRefusesTheRun:
    """Enforcement must abort collection, not merely notice."""

    def test_untiered_test_aborts_collection(self) -> None:
        """A reported violation that does not fail is not a gate.

        Mutation it catches: computing the violations and not raising. The
        message would still be correct and the classification tests above would
        still pass, while an unclassified test sailed into the fast lane.
        """
        with pytest.raises(pytest.UsageError) as excinfo:
            enforce_tiers([_FakeItem("t.py::test_bare")])

        assert "no tier marker" in str(excinfo.value)
        assert "t.py::test_bare" in str(excinfo.value)

    def test_contradictory_test_aborts_collection(self) -> None:
        """The contradiction must fail the run, not just the classification."""
        with pytest.raises(pytest.UsageError) as excinfo:
            enforce_tiers([_FakeItem("t.py::test_both", "unit", "cuda")])

        assert "alongside a slow tier" in str(excinfo.value)

    def test_a_correctly_tiered_run_is_not_disturbed(self) -> None:
        """The gate must stay silent on a clean collection.

        Mutation it catches: raising unconditionally. That is loud enough to
        find on its own, but this pins the passing direction so the two failure
        tests above cannot be satisfied by a gate that simply always raises.
        """
        enforce_tiers(
            [_FakeItem("t.py::test_fast", "unit"), _FakeItem("t.py::test_gpu", "cuda")]
        )

    def test_the_message_names_offenders_up_to_a_bound(self) -> None:
        """A gate that names nothing leaves the reader grepping.

        Mutation it catches: reporting only the count. The bound is asserted
        too, so the message cannot grow unbounded on a suite-wide violation.
        """
        items = [_FakeItem(f"t.py::test_{i}") for i in range(25)]

        with pytest.raises(pytest.UsageError) as excinfo:
            enforce_tiers(items)

        message = str(excinfo.value)
        assert "t.py::test_0" in message
        assert "and 5 more" in message


class TestSelectedTiers:
    """The tier reading every device precondition is decided from."""

    def test_only_tier_markers_are_reported(self) -> None:
        """Mutation it catches: returning every marker name instead of tiers.

        The run-loop gates test this reading against the slow tiers, so
        admitting ``timeout`` would make any decorated test look like a tier and
        an unrelated modifier would decide whether the GPU lock is taken.
        """
        items = [
            _FakeItem("t.py::test_fast", "unit", "timeout"),
            _FakeItem("t.py::test_gpu", "cuda"),
        ]

        assert selected_tiers(items) == {"unit", "cuda"}

    def test_an_empty_selection_declares_no_tier(self) -> None:
        """A fully deselected run must not look like it needs a device."""
        assert selected_tiers([]) == set()


#: The exclusion the project's own distributed lane passes. Held here as the
#: input it is, so the admission direction is pinned against the real string
#: rather than one invented to pass.
_DISTRIBUTED_LANE_EXCLUSION = (
    "not (integration or quality or performance or robustness "
    "or subprocess_gpu or cuda)"
)


def _options(
    *, workers: int = 0, markexpr: str = "", dist: str = "no"
) -> argparse.Namespace:
    """Build the resolved option set pytest hands the gate.

    Mirrors what the plugin has already done by the time the gate runs: a
    worker count is an integer, and each worker has an execution environment.
    """
    return argparse.Namespace(
        numprocesses=workers or None,
        dist=dist if workers == 0 else "load",
        tx=["popen"] * workers,
        markexpr=markexpr,
    )


class TestParallelGpuBan:
    """A GPU-bound selection must never be spread across worker processes."""

    def test_a_distributed_gpu_selection_is_refused(self) -> None:
        """The whole point: one card cannot host one model stack per worker.

        Mutation it catches: returning instead of raising once the offending
        tiers are known. Every worker would then load its own models onto the
        single device, which is the failure this gate exists to prevent.
        """
        with pytest.raises(pytest.UsageError) as excinfo:
            enforce_serial_gpu_lane(_options(workers=4, markexpr="cuda"))

        message = str(excinfo.value)
        assert "refusing to distribute this session across 4 worker" in message
        assert "cuda" in message

    def test_an_unfiltered_distributed_session_is_refused(self) -> None:
        """No marker expression selects the whole suite, GPU tiers included.

        Mutation it catches: treating an empty expression as excluding
        everything. ``-n auto`` with no selection would then be admitted and
        would distribute the entire GPU suite.
        """
        with pytest.raises(pytest.UsageError) as excinfo:
            enforce_serial_gpu_lane(_options(workers=2))

        message = str(excinfo.value)
        assert "no marker expression, so the whole suite is selected" in message

    def test_a_distributed_unit_selection_is_admitted(self) -> None:
        """The project's own parallel lane must keep running.

        Mutation it catches: refusing on distribution alone without reading the
        selection. That would break the one lane that legitimately distributes,
        and the pressure to delete the gate would follow.
        """
        enforce_serial_gpu_lane(
            _options(workers=12, markexpr=_DISTRIBUTED_LANE_EXCLUSION, dist="loadfile")
        )

    def test_a_serial_gpu_selection_is_admitted(self) -> None:
        """The GPU lane itself is serial and must pass untouched.

        Mutation it catches: reading the marker expression without first
        checking the worker count. The serial GPU lane would then be refused
        and the GPU tiers could not be run at all.
        """
        enforce_serial_gpu_lane(_options(markexpr="cuda"))

    def test_a_partial_exclusion_is_still_refused(self) -> None:
        """Excluding some slow tiers is not excluding the GPU.

        Mutation it catches: refusing only when every slow tier is selectable.
        A lane that excluded ``integration`` but not ``cuda`` would distribute
        real device work.
        """
        with pytest.raises(pytest.UsageError) as excinfo:
            enforce_serial_gpu_lane(_options(workers=2, markexpr="not integration"))

        # The listing is asserted whole rather than by substring: naming one
        # surviving tier passes even when the reading has lost the others, and
        # naming the excluded one would read as a refusal for the wrong reason.
        listing = str(excinfo.value).split("tier(s) ")[1].split(".")[0]

        assert listing == "cuda, performance, quality, robustness, subprocess_gpu"


class TestDistributionReading:
    """Whether this process will hand tests to other processes."""

    def test_a_worker_count_is_reported(self) -> None:
        """Mutation it catches: reading the mode and ignoring the count."""
        assert distributed_worker_count(_options(workers=8)) == 8

    def test_a_distribution_mode_alone_spawns_nothing(self) -> None:
        """``--dist`` without a worker count runs in this very process.

        Mutation it catches: treating any mode other than ``no`` as
        distribution. A serial run passing only ``--dist`` would be refused,
        and so would every process that reports a mode without spawning.
        """
        assert distributed_worker_count(_options(dist="loadfile")) == 0

    def test_a_process_told_nothing_reports_no_distribution(self) -> None:
        """A distributed session's workers are told neither count nor mode.

        Mutation it catches: defaulting an absent option to distribution. Every
        worker of a legitimate parallel run would refuse its own collection,
        turning the gate into an internal scheduling fault.
        """
        assert distributed_worker_count(argparse.Namespace()) == 0


class TestSelectableSlowTiers:
    """Which GPU tiers a marker expression can still reach."""

    def test_the_lane_exclusion_reaches_no_slow_tier(self) -> None:
        """Mutation it catches: inverting the evaluated verdict."""
        assert selectable_slow_tiers(_DISTRIBUTED_LANE_EXCLUSION) == []

    def test_the_fast_lane_expression_reaches_no_slow_tier(self) -> None:
        """``-m unit`` names one tier, so no slow tier survives it."""
        assert selectable_slow_tiers("unit") == []

    def test_a_union_with_a_slow_tier_reaches_it(self) -> None:
        """Mutation it catches: reading only the leading term of a union."""
        assert selectable_slow_tiers("unit or cuda") == ["cuda"]

    def test_an_empty_expression_reaches_every_slow_tier(self) -> None:
        """Nothing selected means everything selected."""
        assert selectable_slow_tiers("   ") == sorted(SLOW_TIERS)

    def test_a_malformed_expression_proves_no_exclusion(self) -> None:
        """An expression that cannot be compiled excludes nothing provable.

        Mutation it catches: letting the compile error escape. It would surface
        as an unhandled fault from session startup instead of the clear
        expression error pytest raises on its own moments later.
        """
        assert selectable_slow_tiers("cuda and or") == sorted(SLOW_TIERS)
