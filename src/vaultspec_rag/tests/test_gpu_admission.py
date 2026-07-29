"""Guards for the model-load admission gate.

Every check in the admission gate is a guard, so each test below states the
mutation that makes it fail and every one of those mutations was run: the guard
broken open one at a time, the named test run alone, observed to fail on the
assertion it names, the source restored, the test re-run and observed to pass.
One uninterrupted sequence per guard, with nothing left mutated on disk.

Two design choices make these guards real rather than decorative. The device
reading is supplied as a value wherever the judgement rather than the
measurement is under test, so an absent torch, a CPU-only build, a driver that
refused the memory query, and a figure exactly at the floor are all exercised
without a machine that happens to present them. And the lock is always the real
OS advisory lock on a real file - only the anchor moves, into a temp dir, so a
test never contends for the machine-global lock another tenant may legitimately
hold, and never gets a green result from a lock that was not taken.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING

import pytest

from .._fd_lock import lock_fd_exclusive, unlock_fd
from .._gpu_admission import (
    REASON_BELOW_FLOOR,
    REASON_LOAD_IN_PROGRESS,
    REASON_NO_CUDA,
    REASON_TORCH_ABSENT,
    DeviceAdmission,
    admission_from_reading,
    admit_gpu_load,
    clear_gpu_admission_latch,
    device_contended_message,
    device_load_reading,
    device_load_window,
    device_load_wire,
    load_window_lock_path,
)
from ..config._settings import rag_default
from ..config._types import EnvVar
from ..memory_probe import CudaDeviceMemory
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from contextlib import AbstractContextManager
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: A 16 GiB card with room to spare, and the same card with a resident stack on
#: it. The pair is what the floor is meant to separate.
_ROOMY = CudaDeviceMemory(
    torch_present=True,
    cuda_present=True,
    free_mb=14000.0,
    total_mb=16376.0,
)
_CROWDED = CudaDeviceMemory(
    torch_present=True,
    cuda_present=True,
    free_mb=2000.0,
    total_mb=16376.0,
)

#: An arbitrary floor pinned for the predicate tests below, deliberately NOT
#: the shipped default: those tests are about how a reading and a floor combine,
#: so they must not move when the default is recalibrated. The shipped default's
#: own soundness is asserted separately, against the measurements.
_FLOOR = 8448

#: The device this project targets, in MiB, as the driver reports it - a 16 GiB
#: card measures slightly under its nominal size.
_DEVICE_TOTAL_MIB = 16376

#: The two measured figures the shipped floor has to clear: what the embedding,
#: sparse, and reranker stacks occupy together once all three are resident, and
#: the largest legitimate demand one of them then places above that residency.
#: Named here so the soundness properties below are derived from the
#: measurements rather than restating the floor they are checking.
_MEASURED_RESIDENT_STACK_MIB = 6301
_MEASURED_PEAK_NET_DEMAND_MIB = 4609

#: How long to keep re-attempting a claim on an anchor whose holder has been
#: killed, before reporting that it never came free.
#:
#: This is a FAILURE BOUND, not a synchronisation device, and the difference is
#: the whole reason the loop below is shaped this way. Lengthening it cannot turn
#: a failing run into a passing one for a lock that genuinely never frees - it
#: only changes how long a real regression in crash-safe release takes to
#: report. That asymmetry is what separates a bound from a widened tolerance: a
#: tolerance admits a wrong answer, whereas this admits only a slower right one.
#: So it is deliberately generous, and it must never be traded for a sleep long
#: enough to "usually" work, which is the shape it replaced.
_RELEASE_DEADLINE_SECONDS = 15.0

#: How long to pause between claim attempts. Bounds the polling rate and nothing
#: else: the verdict is decided by whether ANY attempt succeeded before the
#: deadline, so this value cannot change the outcome - a larger one only means
#: fewer observations inside the same window.
_RELEASE_POLL_SECONDS = 0.05

#: How long to wait for a killed child to be reaped. Cleanup hygiene, so the
#: test leaves no process behind; deliberately not load-bearing for anything
#: asserted, because a reap is not a release.
_CHILD_REAP_SECONDS = 10.0

#: A child that takes the production advisory lock on the anchor it is given,
#: announces the hold, and then blocks until its stdin closes or it is killed.
#: It goes through ``_fd_lock`` rather than the platform call so the test
#: contends against the same primitive production uses.
_HOLDER_SOURCE = """
import os
import sys

from vaultspec_rag._fd_lock import lock_fd_exclusive

fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
lock_fd_exclusive(fd)
sys.stdout.write("locked\\n")
sys.stdout.flush()
sys.stdin.read()
"""


@pytest.fixture(autouse=True)
def unlatched_admission() -> Generator[None]:
    """Leave the process-wide admission latch clear at both test boundaries.

    The latch is per-process by design, so a test that sets it would otherwise
    hand the next test an admission it never asked for - and the latch's whole
    job is to suppress a second evaluation, which would make that next test pass
    without exercising anything.
    """
    clear_gpu_admission_latch()
    try:
        yield
    finally:
        clear_gpu_admission_latch()


@pytest.fixture
def floor() -> Generator[int]:
    """Pin the admission floor for one test through the real settings path."""
    with managed_env(**{EnvVar.GPU_ADMISSION_FLOOR_MIB.value: str(_FLOOR)}):
        yield _FLOOR


def _windowed(
    anchor: Path,
    readings: list[CudaDeviceMemory],
    entries: list[int],
) -> Callable[[], AbstractContextManager[DeviceAdmission]]:
    """Return an admission source over the real window and *readings* in turn.

    The window itself is production code taking a real OS lock on *anchor*;
    only the device observation is supplied, and *entries* counts how many times
    the window was actually entered - the figure the latch guards assert on,
    because "did not re-read the device" is the property under test and a
    verdict alone cannot show it.
    """

    def factory() -> AbstractContextManager[DeviceAdmission]:
        index = min(len(entries), len(readings) - 1)
        entries.append(1)
        return device_load_window(anchor=anchor, reading=readings[index])

    return factory


class TestTheFloorPredicate:
    """The verdict a reading and a floor produce, without a device to ask."""

    def test_free_memory_below_the_floor_is_refused(self) -> None:
        """Mutation: replaced the comparison with an unconditional ``admitted =
        True``, the shape a gate regresses into when the floor stops being
        consulted. Observed this assertion fail on ``admitted is False``.
        """
        admission = admission_from_reading(_CROWDED, floor_mib=_FLOOR)

        assert admission.admitted is False
        assert admission.reason == REASON_BELOW_FLOOR
        assert admission.free_mib == 2000
        assert admission.total_mib == 16376
        assert admission.floor_mib == _FLOOR

    def test_free_memory_at_the_floor_is_admitted(self) -> None:
        """The boundary is inclusive, and asserted so the comparison cannot
        silently become strict.

        Mutation: tightened the comparison to ``free_mib > floor_mib``.
        Observed this assertion fail on ``admitted is True``.
        """
        reading = CudaDeviceMemory(
            torch_present=True,
            cuda_present=True,
            free_mb=float(_FLOOR),
            total_mb=16376.0,
        )

        admission = admission_from_reading(reading, floor_mib=_FLOOR)

        assert admission.admitted is True
        assert admission.reason == ""

    def test_free_memory_is_truncated_never_rounded_up(self) -> None:
        """The float-to-whole-MiB step must not decide anything on its own.

        The readings arrive as floats and the verdict carries whole mebibytes.
        Because the floor is an integer, truncating is decision-preserving - a
        truncated figure clears an integer bound exactly when the float did - so
        both sides of the boundary are pinned here: a hair under the floor stays
        refused, and a hair over it stays admitted even though truncation drops
        the fraction that put it there.

        Mutation: replaced the ``int()`` truncation with ``round()``. Observed
        this assertion fail on ``free_mib == _FLOOR - 1`` as ``assert 8448 ==
        (8448 - 1)``, because ``8447.6`` rounds up onto the floor and admits.
        """
        under = admission_from_reading(
            CudaDeviceMemory(
                torch_present=True,
                cuda_present=True,
                free_mb=_FLOOR - 0.4,
                total_mb=16376.0,
            ),
            floor_mib=_FLOOR,
        )
        over = admission_from_reading(
            CudaDeviceMemory(
                torch_present=True,
                cuda_present=True,
                free_mb=_FLOOR + 0.4,
                total_mb=16376.0,
            ),
            floor_mib=_FLOOR,
        )

        assert under.free_mib == _FLOOR - 1
        assert under.reason == REASON_BELOW_FLOOR
        assert over.free_mib == _FLOOR
        assert over.admitted is True

    def test_an_absent_torch_and_a_cpu_only_build_are_told_apart(self) -> None:
        """Two absences, two tokens - a consumer has to distinguish them.

        Mutation: collapsed the two branches by reporting ``no_cuda`` for both.
        Observed this assertion fail on ``reason == REASON_TORCH_ABSENT``.
        """
        absent = admission_from_reading(
            CudaDeviceMemory(
                torch_present=False,
                cuda_present=False,
                free_mb=None,
                total_mb=None,
            ),
            floor_mib=_FLOOR,
        )
        cpu_only = admission_from_reading(
            CudaDeviceMemory(
                torch_present=True,
                cuda_present=False,
                free_mb=None,
                total_mb=None,
            ),
            floor_mib=_FLOOR,
        )

        assert absent.reason == REASON_TORCH_ABSENT
        assert cpu_only.reason == REASON_NO_CUDA
        assert absent.admitted is False
        assert cpu_only.admitted is False
        assert absent.free_mib is None
        assert cpu_only.free_mib is None

    def test_a_present_device_with_an_unreadable_figure_is_admitted(self) -> None:
        """An unmeasurable device admits rather than refusing all GPU work.

        The deliberate fail-open: a driver that answers presence but refuses the
        memory query is a hiccup, and the per-job CUDA ceiling and the
        allocator's own backoff remain in force behind this gate. Asserted so
        the choice is visible rather than incidental.

        Mutation: refused the unreadable case with ``no_cuda``. Observed this
        assertion fail on ``admitted is True``.
        """
        admission = admission_from_reading(
            CudaDeviceMemory(
                torch_present=True,
                cuda_present=True,
                free_mb=None,
                total_mb=16376.0,
            ),
            floor_mib=_FLOOR,
        )

        assert admission.admitted is True
        assert admission.reason == ""
        assert admission.free_mib is None

    def test_the_refusal_message_names_free_the_floor_and_a_way_out(self) -> None:
        """An operator can only act on a refusal that carries the figures.

        Mutation: dropped the reading from the rendered message, leaving the
        standing prose alone. Observed this assertion fail on the ``2000 MiB``
        membership check.
        """
        message = device_contended_message(
            admission_from_reading(_CROWDED, floor_mib=_FLOOR)
        )

        assert "2000 MiB free" in message
        assert f"{_FLOOR} MiB floor" in message
        assert EnvVar.GPU_ADMISSION_FLOOR_MIB.value in message


class TestTheShippedFloorIsSound:
    """The shipped default must refuse a second tenant, whatever its value.

    These pin the PROPERTY, never the numeral. A test asserting the floor equals
    some number would have passed just as happily at a value where a resident
    tenant still left room to admit a second stack - reporting the defect as
    healthy, which is worse than having no test at all. Both assertions here are
    derived from the two measured figures, so they keep their meaning if those
    measurements are revised and they fail if the floor drifts below what the
    measurements require.
    """

    def test_the_floor_exceeds_a_stack_plus_its_own_peak_demand(self) -> None:
        """A load needs room for what it creates AND what it then does.

        Mutation: returned the floor to a value sized to the resident stack plus
        a generic headroom figure (8448). Observed this assertion fail on
        ``8448 > 10910``.
        """
        shipped = int(rag_default("gpu_admission_floor_mib"))
        required = _MEASURED_RESIDENT_STACK_MIB + _MEASURED_PEAK_NET_DEMAND_MIB

        assert shipped > required, (
            f"the shipped floor is {shipped} MiB, which does not exceed the "
            f"{required} MiB a load actually needs ({_MEASURED_RESIDENT_STACK_MIB} "
            f"MiB resident plus {_MEASURED_PEAK_NET_DEMAND_MIB} MiB of demand "
            "above it); a load admitted at this floor can still run the device out"
        )

    def test_the_free_memory_one_resident_tenant_leaves_is_refused(self) -> None:
        """The incident arrangement, stated as a reading and refused.

        This is the case a residency-sized floor admitted: one tenant already
        holds the card, and the free memory it leaves behind must not be enough
        to bring a second stack up beside it.

        Mutation: returned the floor to 8448. Observed this assertion fail on
        ``admitted is False``, the second stack being admitted onto a card that
        could not hold both.
        """
        shipped = int(rag_default("gpu_admission_floor_mib"))
        free_beside_one_tenant = _DEVICE_TOTAL_MIB - _MEASURED_RESIDENT_STACK_MIB

        admission = admission_from_reading(
            CudaDeviceMemory(
                torch_present=True,
                cuda_present=True,
                free_mb=float(free_beside_one_tenant),
                total_mb=float(_DEVICE_TOTAL_MIB),
            ),
            floor_mib=shipped,
        )

        assert admission.admitted is False, (
            f"{free_beside_one_tenant} MiB free - what one resident tenant "
            f"leaves on this device - was admitted against a {shipped} MiB floor"
        )
        assert admission.reason == REASON_BELOW_FLOOR


class TestTheLoadWindow:
    """The real OS lock that makes check-then-load atomic between processes."""

    def test_a_concurrent_holder_refuses_the_window(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """A second loader is refused instantly instead of reading the same
        free figure and admitting alongside the first.

        The held descriptor takes the real advisory lock on the real byte, so
        the refusal is genuine rather than simulated - but it is a second
        descriptor of THIS process, which is the weaker half of the claim. The
        cross-process case is asserted separately below; this one pins the
        in-process semantics the intra-process guard depends on.

        Mutation: made ``claim_anchor`` read a refused lock call as
        ``UNAVAILABLE`` and degrade, instead of as ``CONTENDED``. Observed this
        assertion fail on ``assert True is False``, the verdict arriving as an
        ordinary admitted reading.
        """
        anchor = tmp_path / "load-window.lock"
        held = os.open(anchor, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            lock_fd_exclusive(held)
            with device_load_window(anchor=anchor, reading=_ROOMY) as admission:
                assert admission.admitted is False
                assert admission.reason == REASON_LOAD_IN_PROGRESS
                assert admission.floor_mib == floor
                assert admission.free_mib is None
        finally:
            unlock_fd(held)
            os.close(held)

    def test_a_second_process_holding_the_window_refuses_this_one(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """The mechanism exists to exclude another PROCESS, so prove that.

        A real child interpreter takes the real advisory lock and holds it while
        this process attempts the window. That is the arrangement the incident
        was - two independent processes, each about to load a model stack - and
        it is the one thing a second descriptor of this process cannot stand in
        for, because it shares this process's own view of the lock.

        The child is then killed rather than asked to release, which proves the
        crash-safety claim the design rests on: nothing releases this lock in
        software, the kernel does it when the holder dies, so a killed loader
        cannot strand the window for the next one.

        Mutation: made ``claim_anchor`` read a refused lock call as
        ``UNAVAILABLE`` and degrade. Observed this assertion fail on ``the
        window must refuse while a sibling process holds it``.
        """
        # Reclaiming after the kill waits on the OBSERVED release, never on an
        # elapsed interval. Waiting on `holder.wait()` returning is what this
        # test used to do and it was wrong: the process object is signalled once
        # its threads are gone, which precedes the kernel finishing with its
        # handle table, so a claim attempted the instant `wait()` returned could
        # still lose to a holder that was dead but not yet reaped.
        del floor
        anchor = tmp_path / "load-window.lock"
        holder = subprocess.Popen(
            [sys.executable, "-c", _HOLDER_SOURCE, str(anchor)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            assert holder.stdout is not None
            assert holder.stdout.readline().strip() == "locked", (
                "premise: the child must report holding the OS lock"
            )

            with device_load_window(anchor=anchor, reading=_ROOMY) as contended:
                assert contended.admitted is False, (
                    "the window must refuse while a sibling process holds it"
                )
                assert contended.reason == REASON_LOAD_IN_PROGRESS
        finally:
            # Cleanup only. Neither call orders anything the assertion below
            # depends on - the retry loop owns that - so neither can carry the
            # timing assumption that made this test racy. Do not promote either
            # back into a synchronisation point.
            holder.kill()
            holder.wait(timeout=_CHILD_REAP_SECONDS)
            if holder.stdout is not None:
                holder.stdout.close()
            if holder.stdin is not None:
                holder.stdin.close()

        admitted_after_death = False
        deadline = time.monotonic() + _RELEASE_DEADLINE_SECONDS
        while time.monotonic() < deadline:
            with device_load_window(anchor=anchor, reading=_ROOMY) as after_death:
                admitted_after_death = after_death.admitted
            if admitted_after_death:
                break
            time.sleep(_RELEASE_POLL_SECONDS)

        assert admitted_after_death is True, (
            "the kernel must release a dead holder's lock, leaving no state "
            "for a later loader to reclaim"
        )

    def test_the_window_is_released_on_exit(self, tmp_path: Path, floor: int) -> None:
        """The hold covers the window and nothing after it.

        A lock that outlived the window would wedge every later loader on the
        machine, and would do so silently - the first caller still succeeds.

        Mutation: dropped the ``finally`` release in ``device_load_window``.
        Observed this assertion fail on the second window's ``admitted is
        True``, over a ``load_in_progress`` verdict from the first window's
        surviving hold.
        """
        del floor
        anchor = tmp_path / "load-window.lock"
        with device_load_window(anchor=anchor, reading=_ROOMY) as first:
            assert first.admitted is True
        with device_load_window(anchor=anchor, reading=_ROOMY) as second:
            assert second.admitted is True
            assert second.reason == ""

    def test_an_unopenable_anchor_degrades_to_the_floor_check(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """A filesystem fault costs the lock, never all GPU work.

        The anchor's parent is a regular file here, so creating the directory
        fails for real. Degrading is the point: converting a disk fault into a
        total refusal of compute would be a worse outcome than losing the
        cross-process half of the protection, and the floor still decides.

        Mutation: made ``claim_anchor`` report ``CONTENDED`` when the anchor
        cannot be opened. Observed this assertion fail on ``assert False is
        True``, over a ``load_in_progress`` verdict.
        """
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("", encoding="utf-8")
        anchor = blocker / "load-window.lock"

        with device_load_window(anchor=anchor, reading=_ROOMY) as admitted:
            assert admitted.admitted is True
            assert admitted.floor_mib == floor
        with device_load_window(anchor=anchor, reading=_CROWDED) as refused:
            assert refused.admitted is False
            assert refused.reason == REASON_BELOW_FLOOR

    def test_the_machine_anchor_is_configuration_independent(
        self,
        tmp_path: Path,
    ) -> None:
        """The device is machine hardware, so its lock cannot follow a
        configured directory into a private tree.

        Mutation: resolved the anchor through the managed status dir. Observed
        this assertion fail on the ``tmp_path`` containment check, the lock
        having become private to whichever tree the caller was pointed at.
        """
        with managed_env(**{EnvVar.STATUS_DIR.value: str(tmp_path / "managed")}):
            relocated = load_window_lock_path()

        assert tmp_path not in relocated.parents
        assert relocated == load_window_lock_path()


class TestTheAdmissionLatch:
    """One evaluation per process, and why a second would be wrong."""

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
        device, raised from the second ``admit_gpu_load``.
        """
        del floor
        entries: list[int] = []
        source = _windowed(
            tmp_path / "load-window.lock",
            [_ROOMY, _CROWDED],
            entries,
        )

        assert admit_gpu_load(lambda: "first", window=source) == "first"
        assert admit_gpu_load(lambda: "second", window=source) == "second"
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
        source = _windowed(
            tmp_path / "load-window.lock",
            [_CROWDED, _ROOMY],
            entries,
        )

        with pytest.raises(RuntimeError, match="too contended"):
            admit_gpu_load(lambda: "refused", window=source)
        assert admit_gpu_load(lambda: "admitted", window=source) == "admitted"
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
            free_mb=None,
            total_mb=None,
        )
        source = _windowed(tmp_path / "load-window.lock", [cpu_only], entries)

        def _loader() -> str:
            raise ImportError("the loader's own verdict")

        with pytest.raises(ImportError, match="the loader's own verdict"):
            admit_gpu_load(_loader, window=source)

    def test_clearing_the_latch_re_admits_against_a_fresh_reading(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """A released resident stack must not leave its verdict behind.

        Mutation: made ``clear_gpu_admission_latch`` a no-op. Observed this
        assertion fail on ``pytest.raises(RuntimeError)``, the second load
        riding the first load's stale admission.
        """
        del floor
        entries: list[int] = []
        source = _windowed(
            tmp_path / "load-window.lock",
            [_ROOMY, _CROWDED],
            entries,
        )

        assert admit_gpu_load(lambda: "first", window=source) == "first"
        clear_gpu_admission_latch()
        with pytest.raises(RuntimeError, match="too contended"):
            admit_gpu_load(lambda: "second", window=source)

    def test_a_resident_release_retires_the_standing_admission(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """The release path is wired to the latch, not merely able to clear it.

        Asserted through the production release entry point rather than through
        the clear itself: a clear nothing calls protects nothing, and that
        omission is invisible to every other test here.

        Mutation: removed the ``clear_gpu_admission_latch()`` call from
        ``rebase_resident_cuda_baseline``. Observed this assertion fail on
        ``pytest.raises(RuntimeError)``.
        """
        del floor
        from ..memory_probe import rebase_resident_cuda_baseline

        entries: list[int] = []
        source = _windowed(
            tmp_path / "load-window.lock",
            [_ROOMY, _CROWDED],
            entries,
        )

        assert admit_gpu_load(lambda: "first", window=source) == "first"
        rebase_resident_cuda_baseline()
        with pytest.raises(RuntimeError, match="too contended"):
            admit_gpu_load(lambda: "second", window=source)

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
        ``admit_gpu_load``. Observed this assertion fail on ``not failures``,
        carrying a ``RuntimeError`` whose message named another process holding
        the model-load window.
        """
        del floor
        entries: list[int] = []
        source = _windowed(tmp_path / "load-window.lock", [_ROOMY], entries)
        start = threading.Barrier(2)
        results: list[str] = []
        failures: list[Exception] = []
        lock = threading.Lock()

        def _race() -> None:
            try:
                start.wait(timeout=5.0)
                loaded = admit_gpu_load(lambda: "loaded", window=source)
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
        ``wire["free_mib"] == 2000``.
        """
        admission = DeviceAdmission(
            admitted=False,
            free_mib=2000,
            total_mib=16376,
            floor_mib=6400,
            reason=REASON_BELOW_FLOOR,
        )

        wire = device_load_wire(admission)

        assert wire["free_mib"] == 2000
        assert wire["total_mib"] == 16376
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
            admitted=True, free_mib=9000, total_mib=16376, floor_mib=6400, reason=""
        )
        monkeypatch.setattr(
            "vaultspec_rag._gpu_admission.evaluate_device_admission",
            lambda: admission,
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

        def _boom() -> DeviceAdmission:
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
