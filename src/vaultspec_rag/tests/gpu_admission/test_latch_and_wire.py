"""Admission-latch, wire-reading and torch-freedom guards.

Each test states the mutation that makes it fail, and every one of those
mutations was run, one uninterrupted sequence per guard, with nothing left
mutated on disk.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from typing import TYPE_CHECKING

import pytest

from ..._gpu_admission import (
    REASON_BELOW_FLOOR,
    DeviceAdmission,
    admit_accelerator_load,
    clear_accelerator_admission_latch,
    device_load_reading,
    device_load_window,
    device_load_wire,
    evaluate_device_admission,
)
from ...memory_probe import CudaDeviceMemory

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

from .conftest import (
    _CROWDED,
    _ROOMY,
    _SCENARIO_TOTAL_MIB,
    _UNREADABLE,
    windowed,
)

pytestmark = [pytest.mark.unit]


class TestTheAdmissionLatch:
    """One evaluation per process, and why a second would be wrong."""

    def test_mps_capability_admission_uses_and_latches_the_load_window(
        self,
        tmp_path: Path,
    ) -> None:
        """MPS admits on capability and shares the serialized load window.

        Mutation: omitted ``capability_evaluated`` from the MPS verdict. The
        second call then entered the source again and failed on the entry count.
        """
        from contextlib import contextmanager

        entries: list[int] = []

        @contextmanager
        def source() -> Generator[DeviceAdmission]:
            entries.append(1)
            with device_load_window(
                backend="mps",
                anchor=tmp_path / "load-window.lock",
            ) as admission:
                yield admission

        verdict = evaluate_device_admission("mps")
        assert verdict.admitted is True
        assert verdict.free_mib is None
        assert (
            admit_accelerator_load(lambda: "first", backend="mps", window=source)
            == "first"
        )
        assert (
            admit_accelerator_load(lambda: "second", backend="mps", window=source)
            == "second"
        )
        assert len(entries) == 1

    def test_a_later_load_is_not_refused_by_this_process_s_own_residency(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """The latch is a correctness device, not an optimisation.

        The second reading here is what the device genuinely looks like once
        this process's models are resident: crowded, by its own doing. An
        unlatched gate would read that as contention and refuse the process it
        just admitted, so the assertion is that the window is never entered a
        second time at all.

        Mutation: removed the ``_admitted`` fast path and the latch re-check.
        Observed this assertion fail with ``RuntimeError`` naming the contended
        device, raised from the second ``admit_accelerator_load``.
        """
        del floor
        entries: list[int] = []
        source = windowed(
            tmp_path / "load-window.lock",
            [_ROOMY, _CROWDED],
            entries,
        )

        assert admit_accelerator_load(lambda: "first", window=source) == "first"
        assert admit_accelerator_load(lambda: "second", window=source) == "second"
        assert len(entries) == 1

    def test_a_refused_load_is_never_latched(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """A refusal must not be remembered as an admission.

        Mutation: moved the ``_admitted = True`` assignment above the refusal
        check. Observed this assertion fail on ``len(entries) == 2``: the
        refused first call had latched itself as admitted, so the second load
        rode that latch and never reached the window at all.
        """
        del floor
        entries: list[int] = []
        source = windowed(
            tmp_path / "load-window.lock",
            [_CROWDED, _ROOMY],
            entries,
        )

        with pytest.raises(RuntimeError, match="too contended"):
            admit_accelerator_load(lambda: "refused", window=source)
        assert admit_accelerator_load(lambda: "admitted", window=source) == "admitted"
        assert len(entries) == 2

    def test_the_loader_s_own_failure_is_not_restated_as_contention(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """An absent device is the loader's verdict, given once.

        Two messages for one condition is the drift this avoids: the gate must
        pass a torch-free or CPU-only reading through to the loader rather than
        answering it itself.

        Mutation: added ``REASON_NO_CUDA`` to the refusing set. Observed this
        assertion fail on ``ImportError``, the gate having pre-empted the
        loader with its own ``RuntimeError``.
        """
        del floor
        entries: list[int] = []
        cpu_only = CudaDeviceMemory(
            torch_present=True,
            cuda_present=False,
            free_mib=None,
            total_mib=None,
            own_reserved_mib=None,
        )
        source = windowed(tmp_path / "load-window.lock", [cpu_only], entries)

        def _loader() -> str:
            raise ImportError("the loader's own verdict")

        with pytest.raises(ImportError, match="the loader's own verdict"):
            admit_accelerator_load(_loader, window=source)

    def test_clearing_the_latch_re_admits_against_a_fresh_reading(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """A released resident stack must not leave its verdict behind.

        Mutation: made ``clear_accelerator_admission_latch`` a no-op. Observed this
        assertion fail on ``pytest.raises(RuntimeError)``, the second load
        riding the first load's stale admission.
        """
        del floor
        entries: list[int] = []
        source = windowed(
            tmp_path / "load-window.lock",
            [_ROOMY, _CROWDED],
            entries,
        )

        assert admit_accelerator_load(lambda: "first", window=source) == "first"
        clear_accelerator_admission_latch()
        with pytest.raises(RuntimeError, match="too contended"):
            admit_accelerator_load(lambda: "second", window=source)

    def test_a_resident_release_retires_the_standing_admission(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """The release path is wired to the latch, not merely able to clear it.

        Asserted through the production release entry point rather than through
        the clear itself: a clear nothing calls protects nothing, and that
        omission is invisible to every other test here.

        Mutation: removed the ``clear_accelerator_admission_latch()`` call from
        ``rebase_resident_cuda_baseline``. Observed this assertion fail on
        ``pytest.raises(RuntimeError)``.
        """
        del floor
        from ...memory_probe import rebase_resident_cuda_baseline

        entries: list[int] = []
        source = windowed(
            tmp_path / "load-window.lock",
            [_ROOMY, _CROWDED],
            entries,
        )

        assert admit_accelerator_load(lambda: "first", window=source) == "first"
        rebase_resident_cuda_baseline()
        with pytest.raises(RuntimeError, match="too contended"):
            admit_accelerator_load(lambda: "second", window=source)

    def test_a_verdict_that_never_reached_the_floor_is_not_latched(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """A reading that was never taken must not retire the gate.

        The first verdict here is the driver answering presence and refusing the
        memory query: admitted, because turning a hiccup into a refusal of all
        GPU work costs more than it buys - but admitted without the floor ever
        being consulted. Latching that would mean one transient probe failure on
        a working device left the floor unevaluated for the life of the process,
        with the gate still reporting itself present. So the second call must
        reach the window again, and the roomy figure it finds there is the first
        real evaluation this process has made.

        Mutation: restored the unconditional ``_admitted = True``. Observed this
        assertion fail on ``len(entries) == 2`` with ``entries == [1]`` - the
        second load rode a latch earned by a reading that never happened. The
        sibling refusal-not-latched guard passes under that same mutation,
        because a refusal raises before the assignment either way.
        """
        del floor
        entries: list[int] = []
        source = windowed(
            tmp_path / "load-window.lock",
            [_UNREADABLE, _ROOMY],
            entries,
        )

        assert admit_accelerator_load(lambda: "first", window=source) == "first"
        assert admit_accelerator_load(lambda: "second", window=source) == "second"
        assert len(entries) == 2

    def test_a_refusal_reached_after_an_unevaluated_load_still_refuses(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """No allowance survives a load that ran without a verdict.

        The first load here went through under a driver that refused the
        memory query, so no floor was consulted and nothing latched. The retry
        that opens must still be a real gate: the verdict it reaches credits
        whatever this process holds, so a below-floor figure with a zero own
        checkout - as here - is genuinely foreign crowding and refuses. An
        escape for "the figure might be my own residency" would let one probe
        hiccup exempt the process from the floor for its remaining loads.

        Mutation: reintroduced that escape - recorded the unevaluated load in a
        flag and downgraded the refusal to a warning while it was set. Observed
        this assertion fail on ``pytest.raises(RuntimeError)``, the second load
        proceeding over the crowded verdict.
        """
        del floor
        entries: list[int] = []
        source = windowed(
            tmp_path / "load-window.lock",
            [_UNREADABLE, _CROWDED],
            entries,
        )

        assert admit_accelerator_load(lambda: "first", window=source) == "first"
        with pytest.raises(RuntimeError, match="too contended"):
            admit_accelerator_load(lambda: "second", window=source)
        assert len(entries) == 2

    def test_two_threads_racing_the_first_load_are_both_admitted(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """This process must never be refused by its own OS lock.

        The window here takes the real advisory lock, and an advisory lock is
        held per descriptor rather than per process, so two threads entering it
        together would have the second refused as if a sibling process held the
        card. The process-local guard is what prevents that, and the assertion
        is that exactly one thread ever entered the window while both loads
        completed.

        Mutation: removed the ``_admission_guard`` acquisition from
        ``admit_accelerator_load``. Observed this assertion fail on ``not failures``,
        carrying a ``RuntimeError`` whose message named another process holding
        the model-load window.
        """
        del floor
        entries: list[int] = []
        source = windowed(tmp_path / "load-window.lock", [_ROOMY], entries)
        start = threading.Barrier(2)
        results: list[str] = []
        failures: list[Exception] = []
        lock = threading.Lock()

        def _race() -> None:
            try:
                start.wait(timeout=5.0)
                loaded = admit_accelerator_load(lambda: "loaded", window=source)
            except Exception as exc:  # recorded, then asserted on below
                with lock:
                    failures.append(exc)
            else:
                with lock:
                    results.append(loaded)

        threads = [threading.Thread(target=_race, name=f"race-{n}") for n in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10.0)

        assert not [thread for thread in threads if thread.is_alive()]
        assert not failures, failures
        assert results == ["loaded", "loaded"]
        assert len(entries) == 1


class TestTheWireReading:
    """The one device-load reading every surface (health, jobs, preflight)
    publishes over JSON: projection and absent-not-raised behaviour, guarded
    once here rather than per surface.
    """

    def test_the_wire_shape_projects_every_field(self) -> None:
        """A renamed key breaks every consumer reading it.

        Mutation: renamed the ``free_mib`` key to ``free_mb`` in the
        projection. Observed this assertion fail on
        ``wire["free_mib"] == 2000``. Re-proven for the own-checkout figure:
        renaming the ``own_mib`` key failed this test on
        ``wire["own_mib"] == 384`` with ``KeyError: 'own_mib'``.
        """
        admission = DeviceAdmission(
            admitted=False,
            free_mib=2000,
            total_mib=_SCENARIO_TOTAL_MIB,
            own_mib=384,
            floor_mib=6400,
            reason=REASON_BELOW_FLOOR,
        )

        wire = device_load_wire(admission)

        assert wire["free_mib"] == 2000
        assert wire["total_mib"] == _SCENARIO_TOTAL_MIB
        assert wire["own_mib"] == 384
        assert wire["floor_mib"] == 6400
        assert wire["admitted"] is False
        assert wire["reason"] == REASON_BELOW_FLOOR

    def test_device_load_reading_projects_the_evaluated_verdict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reading composes the live evaluator with the wire projection.

        Mutation: had the reading return the raw admission instead of its
        wire projection. Observed this assertion fail on
        ``isinstance(reading, dict)`` (a ``DeviceAdmission`` has no
        ``__getitem__``).
        """
        admission = DeviceAdmission(
            admitted=True,
            free_mib=9000,
            total_mib=_SCENARIO_TOTAL_MIB,
            own_mib=None,
            floor_mib=6400,
            reason="",
        )
        monkeypatch.setattr(
            "vaultspec_rag._gpu_admission.evaluate_device_admission",
            lambda _backend="cuda": admission,
        )

        reading = device_load_reading()

        assert reading is not None
        assert reading["free_mib"] == 9000
        assert reading["admitted"] is True

    def test_an_unreadable_probe_is_reported_absent_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No caller of this reading may fail because a diagnostic probe threw.

        Mutation: removed the ``try/except`` around the admission call in
        ``device_load_reading``. Observed this assertion fail with the
        injected ``RuntimeError`` propagating out of the call instead of
        being swallowed into ``None``.
        """

        def _boom(_backend: str = "cuda") -> DeviceAdmission:
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(
            "vaultspec_rag._gpu_admission.evaluate_device_admission", _boom
        )

        assert device_load_reading() is None


class TestTorchFreedom:
    """The gate may not drag torch onto a path that must stay without it.

    That this module imports no torch is asserted by the enumerated
    fresh-interpreter guard that already owns the invariant for every local-mode
    module, which this module was added to rather than given a second check of
    its own. What lives here is the behaviour that guard cannot see: whether the
    predicate still answers on a host where torch, or the device probe itself,
    is unreachable.
    """

    def test_the_predicate_answers_on_a_torch_free_host(self) -> None:
        """The predicate must report an absent torch, never raise on it.

        Run in a child interpreter with the torch import poisoned, because this
        one has torch installed: the branch cannot be reached in-process, and a
        test that never reaches it proves nothing about the hosts that do.

        Mutation: made ``cuda_device_memory`` report ``torch_present=True``
        unconditionally, collapsing the absent-torch host into the CPU-only one.
        Observed the child exit non-zero with its assertion naming
        ``reason == REASON_TORCH_ABSENT`` over a ``no_cuda`` verdict.
        """
        probe = (
            "import sys\n"
            "sys.modules['torch'] = None\n"
            "from vaultspec_rag._gpu_admission import (\n"
            "    REASON_TORCH_ABSENT,\n"
            "    evaluate_device_admission,\n"
            ")\n"
            "admission = evaluate_device_admission()\n"
            "assert admission.admitted is False, admission\n"
            "assert admission.reason == REASON_TORCH_ABSENT, admission\n"
            "assert admission.free_mib is None, admission\n"
            "assert admission.floor_mib > 0, admission\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr

    def test_the_predicate_answers_when_the_device_probe_is_unreachable(self) -> None:
        """A diagnostics surface must not fail because a reading could not be
        taken, so the predicate absorbs a fault at its own probe boundary.

        The probe module is made unimportable in the child, which is the one
        fault the predicate cannot foresee and the reason it carries a guard at
        all. Poisoning the boundary rather than the device keeps the fault real:
        the import genuinely fails.

        Mutation: removed the guard from ``evaluate_device_admission``. Observed
        the child exit non-zero on ``ModuleNotFoundError: import of
        vaultspec_rag.memory_probe halted; None in sys.modules``.
        """
        probe = (
            "import sys\n"
            "import vaultspec_rag._gpu_admission as gate\n"
            "sys.modules['vaultspec_rag.memory_probe'] = None\n"
            "admission = gate.evaluate_device_admission()\n"
            "assert admission.admitted is False, admission\n"
            "assert admission.reason == gate.REASON_NO_CUDA, admission\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
