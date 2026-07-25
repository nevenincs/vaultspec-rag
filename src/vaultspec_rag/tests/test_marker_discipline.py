"""Guard: every test declares exactly one lane, and the gate enforces it.

The fast lane is selected by EXCLUDING the slow tiers rather than by naming the
fast one, so an unclassified test is not skipped - it is silently pulled into
the fast lane and run on a machine that may have neither a GPU nor a token. The
inverse costs just as much: a module-level ``pytestmark`` is ADDED to a test's
own decorator rather than overridden by it, so a blanket module default drags
GPU tests into ``-m unit``.

Both directions are enforced at collection time from the root conftest, so the
enforcement runs on every pytest invocation rather than only where someone
remembered to add a gate. These tests exercise that enforcement directly; the
mutation each one catches is named in its own docstring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ._tier_gate import enforce_tiers, group_gpu_items, tier_violations

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
        self.added: list[object] = []

    def iter_markers(self) -> Iterator[_FakeMark]:
        return iter(self._marks)

    def add_marker(self, marker: object) -> None:
        self.added.append(marker)


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


class TestGpuGroupingSurvives:
    """The pre-existing xdist grouping must not be lost to the new gate."""

    def test_gpu_tests_receive_the_group(self) -> None:
        """Mutation it catches: dropping the grouping when the hook was split.

        GPU tests would then be free to co-schedule across xdist workers and
        contend for one device.
        """
        item = _FakeItem("t.py::test_gpu", "integration")

        group_gpu_items([item])

        assert len(item.added) == 1

    def test_fast_tests_are_left_alone(self) -> None:
        """Mutation it catches: grouping every item regardless of tier.

        That would serialise the whole fast lane onto a single xdist worker.
        """
        item = _FakeItem("t.py::test_fast", "unit")

        group_gpu_items([item])

        assert item.added == []
