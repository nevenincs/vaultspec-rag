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
import ast
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ._tier_gate import (
    SLOW_TIERS,
    coscheduled_device_tiers,
    coscheduled_mps_tiers,
    distributed_worker_count,
    enforce_device_tier_isolation,
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
        untiered, contradictory, _ = tier_violations([_FakeItem("t.py::test_nothing")])

        assert untiered == ["t.py::test_nothing"]
        assert contradictory == []

    def test_a_timeout_marker_alone_is_not_a_tier(self) -> None:
        """Modifiers are not tiers, or the gate passes on decoration alone.

        Mutation it catches: widening ``TIER_MARKERS`` to every registered
        marker. ``timeout`` and ``xdist_group`` say nothing about which lane a
        test belongs to, and accepting them would let an unclassified test pass
        merely because it declared a timeout.
        """
        untiered, _, _ = tier_violations(
            [_FakeItem("t.py::test_slow", "timeout", "xdist_group")]
        )

        assert untiered == ["t.py::test_slow"]

    @pytest.mark.parametrize(
        "tier",
        [
            "unit",
            "integration",
            "cuda",
            "mps",
            "subprocess_gpu",
            "performance",
            "quality",
            "robustness",
        ],
    )
    def test_each_declared_tier_satisfies_the_gate(self, tier: str) -> None:
        """Every registered tier must be accepted, or the gate blocks real work."""
        untiered, contradictory, _ = tier_violations([_FakeItem("t.py::test_x", tier)])

        assert untiered == []
        assert contradictory == []

    def test_fast_tier_beside_a_slow_tier_is_reported(self) -> None:
        """The blanket-pytestmark trap, which has bitten this repo four times.

        Mutation it catches: dropping the ``FAST_TIER in names and names &
        SLOW_TIERS`` branch. A module-level ``pytestmark = [pytest.mark.unit]``
        would then silently add ``unit`` to GPU tests in that module, and
        ``-m unit`` would schedule them on a machine with no device.
        """
        _, contradictory, _ = tier_violations(
            [_FakeItem("t.py::test_gpu", "unit", "integration")]
        )

        assert contradictory == ["t.py::test_gpu"]

    def test_two_device_tiers_together_are_reported(self) -> None:
        """The pairing this suite carried for a long time, now refused.

        It was read as intended and was not: a test that spawns a service
        loading its own models belongs to the subprocess tier alone, and the
        resident tier came from a module default it never asked for. The
        result was that ``-m integration`` selected 67 subprocess tests, which
        one card cannot run.

        Mutation it catches: dropping the ``SUBPROCESS_GPU in names and names &
        GPU_MARKERS`` branch. The declarations would drift back one module at a
        time, and nothing would say so until a lane wedged.
        """
        _, _, both_devices = tier_violations(
            [_FakeItem("t.py::test_gpu", "integration", "subprocess_gpu")]
        )

        assert both_devices == ["t.py::test_gpu"]

    def test_two_resident_tiers_together_are_allowed(self) -> None:
        """Resident tiers still combine; they share one process and one model.

        Mutation it catches: widening the device-tier branch to any two slow
        tiers. ``integration`` with ``quality`` is a real pairing in this
        suite, and refusing it would fail collection outright.
        """
        untiered, contradictory, both_devices = tier_violations(
            [_FakeItem("t.py::test_gpu", "integration", "quality")]
        )

        assert untiered == []
        assert contradictory == []
        assert both_devices == []


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
    "or subprocess_gpu or cuda or mps)"
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

        assert listing == "cuda, mps, performance, quality, robustness, subprocess_gpu"


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

    def test_an_mps_selection_is_a_slow_hardware_tier(self) -> None:
        """Mutation it catches: omitting MPS from the slow-tier vocabulary."""
        assert selectable_slow_tiers("mps") == ["mps"]

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


class TestDeviceTierIsolation:
    """One selection must not hold both device tiers at once.

    The constraint was written beside the marker and enforced nowhere, so the
    project's own GPU recipe selected both in one expression. What that
    produces is not an out-of-memory error but a spawned service that never
    becomes healthy - surfacing as a health-poll timeout in an unrelated test,
    late in a long lane, naming nothing about memory.

    Judged on collected items rather than on the marker expression, because the
    expression cannot answer it: a subprocess test usually inherits a module
    default naming a resident tier, so ``-m integration`` selects it while a
    per-tier probe of that expression reports the subprocess tier unreachable.
    """

    def test_a_selection_holding_both_tiers_is_refused(self) -> None:
        """The whole point: the combination that wedges the lane must not run.

        Mutation it catches: requiring only one side in
        ``enforce_device_tier_isolation`` - say ``if subprocess_ids:`` - which
        would refuse the correctly split subprocess lane and let the mixed
        selection through, exactly inverting the gate.
        """
        items = [
            _FakeItem("t.py::test_spawns", "integration", "subprocess_gpu"),
            _FakeItem("t.py::test_resident", "integration"),
        ]

        with pytest.raises(pytest.UsageError) as refusal:
            enforce_device_tier_isolation(items)

        assert "1 subprocess_gpu test(s)" in str(refusal.value)
        assert "t.py::test_spawns" in str(refusal.value)
        assert "t.py::test_resident" in str(refusal.value)

    def test_each_lane_on_its_own_runs(self) -> None:
        """Both correctly split selections have to survive the gate.

        Mutation it catches: treating a test that declares both marks as
        belonging to the resident side. The subprocess lane carries exactly
        those tests, so it would then refuse itself and no split could pass.
        """
        subprocess_lane = [
            _FakeItem("t.py::test_spawns", "integration", "subprocess_gpu"),
            _FakeItem("t.py::test_spawns_too", "subprocess_gpu"),
        ]
        resident_lane = [
            _FakeItem("t.py::test_resident", "integration"),
            _FakeItem("t.py::test_quality", "quality"),
        ]

        enforce_device_tier_isolation(subprocess_lane)
        enforce_device_tier_isolation(resident_lane)

    def test_the_performance_lane_is_not_refused_for_a_tier_it_never_selects(
        self,
    ) -> None:
        """A tier with no subprocess tests must not be judged as if it had them.

        Mutation it catches: modelling the hazard from the marker expression
        instead of the selection. Every resident tier could in principle carry
        a subprocess test, so an expression-based gate refuses ``-m
        performance`` to protect it from tests that selection never holds.
        """
        enforce_device_tier_isolation(
            [_FakeItem("t.py::test_throughput", "performance")]
        )

    def test_the_fast_lane_is_not_a_device_tier(self) -> None:
        """Unit tests load nothing, so they cannot be the resident side."""
        subprocess_ids, resident_ids = coscheduled_device_tiers(
            [
                _FakeItem("t.py::test_spawns", "subprocess_gpu"),
                _FakeItem("t.py::test_pure", "unit"),
            ]
        )

        assert subprocess_ids == ["t.py::test_spawns"]
        assert resident_ids == []

    def test_mps_cannot_share_a_selection_with_cuda_tiers(self) -> None:
        """The Apple hardware guard must never enter a CUDA-coordinated run."""
        items = [
            _FakeItem("t.py::test_apple", "mps"),
            _FakeItem("t.py::test_nvidia", "cuda"),
        ]

        with pytest.raises(pytest.UsageError) as refusal:
            enforce_device_tier_isolation(items)

        assert "MPS tests must run in their own hardware tier" in str(refusal.value)

    def test_mps_lane_alone_runs(self) -> None:
        """A correctly isolated MPS selection remains executable."""
        items = [_FakeItem("t.py::test_apple", "mps")]

        enforce_device_tier_isolation(items)
        assert coscheduled_mps_tiers(items) == (["t.py::test_apple"], [])


def test_mps_acceptance_proves_each_model_parameter_device() -> None:
    """Dense, sparse, and reranker placement must be checked independently."""
    source = (Path(__file__).parent / "integration" / "test_mps_backend.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    labels = {
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_assert_parameters_on_mps"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }
    assert labels == {"dense model", "sparse model", "reranker"}


def test_main_push_runs_the_prepublication_mps_gate() -> None:
    """The support guard must run before a later release advertises MPS."""
    workflow = (
        Path(__file__).parents[3] / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")
    macos_job = workflow.split("  tests-macos:", 1)[1].split("  gpu-tests:", 1)[0]
    assert "github.event_name == 'push'" in macos_job
    assert "run: just test mps" in macos_job
