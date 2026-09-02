"""Floor, unreadable-ledger, workload-derivation and load-window guards.

Each test states the mutation that makes it fail, and every one of those
mutations was run: the guard broken open one at a time, the named test run
alone, observed to fail on the assertion it names, the source restored, the
test re-run and observed to pass.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from ..._fd_lock import lock_fd_exclusive, unlock_fd
from ..._gpu_admission import (
    DEVICE_CONTENDED_MESSAGE,
    REASON_BELOW_FLOOR,
    REASON_DEVICE_UNREADABLE,
    REASON_LOAD_IN_PROGRESS,
    REASON_NO_CUDA,
    REASON_TORCH_ABSENT,
    UNREADABLE_ADMISSION_LIMIT,
    DeviceAdmission,
    admission_from_reading,
    admit_accelerator_load,
    device_load_reading,
    device_load_window,
    device_refusal_message,
    load_window_lock_path,
    observe_unreadable_streak,
)
from ..._units import bytes_to_mib
from ...config._settings import rag_default
from ...config._types import EnvVar
from ...memory_probe import CudaDeviceMemory
from ..conftest import managed_env

if TYPE_CHECKING:
    from pathlib import Path

from .conftest import (
    _BELOW_FLOOR_MIB,
    _CHILD_REAP_SECONDS,
    _CROWDED,
    _FLOOR,
    _HOLDER_SOURCE,
    _MEASURED_PEAK_NET_DEMAND_MIB,
    _MEASURED_RESIDENT_STACK_MIB,
    _RELEASE_DEADLINE_SECONDS,
    _RELEASE_POLL_SECONDS,
    _ROOMY,
    _SCENARIO_MARGIN_MIB,
    _SCENARIO_TOTAL_MIB,
    _UNREADABLE_WITH_TOTAL,
    _windowed,
)

pytestmark = [pytest.mark.unit]


def test_device_load_reading_uses_the_detected_mps_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production's zero-argument health probe must not fall back to CUDA."""
    fake_torch = ModuleType("torch")
    fake_torch.__dict__.update(
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    reading = device_load_reading()

    assert reading is not None
    assert reading["admitted"] is True
    assert reading["reason"] == ""
    assert reading["floor_mib"] == 0


#: An arbitrary floor pinned for the predicate tests below, deliberately NOT
#: the shipped default: those tests are about how a reading and a floor combine,
#: so they must not move when the default's derivation changes. The default's own
#: soundness is asserted separately, against the measurements.
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
        assert admission.free_mib == _BELOW_FLOOR_MIB
        assert admission.total_mib == _SCENARIO_TOTAL_MIB
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
            free_mib=float(_FLOOR),
            total_mib=float(_SCENARIO_TOTAL_MIB),
            own_reserved_mib=0.0,
        )

        admission = admission_from_reading(reading, floor_mib=_FLOOR)

        assert admission.admitted is True
        assert admission.reason == ""

    def test_the_process_s_own_checkout_is_credited_back_to_free(self) -> None:
        """A card crowded by this process's own residency admits its reload.

        The device-wide free figure counts every block this process's own
        allocator has checked out - resident models and cache alike - so a
        long-lived process releasing one stack while still holding another
        would otherwise be refused on its own memory, with the refusal naming
        a foreign consumer that does not exist. The comparison is therefore
        ``free + own`` against the floor, boundary inclusive; an unreadable
        own figure credits nothing, the conservative direction.

        Mutation: dropped the credit from the comparison, back to ``free_mib
        >= floor_mib``. Observed this assertion fail on ``covered.admitted is
        True``.
        """
        gap = _FLOOR - _BELOW_FLOOR_MIB
        covered = admission_from_reading(
            CudaDeviceMemory(
                torch_present=True,
                cuda_present=True,
                free_mib=float(_BELOW_FLOOR_MIB),
                total_mib=float(_SCENARIO_TOTAL_MIB),
                own_reserved_mib=float(gap),
            ),
            floor_mib=_FLOOR,
        )
        short = admission_from_reading(
            CudaDeviceMemory(
                torch_present=True,
                cuda_present=True,
                free_mib=float(_BELOW_FLOOR_MIB),
                total_mib=float(_SCENARIO_TOTAL_MIB),
                own_reserved_mib=float(gap - 1),
            ),
            floor_mib=_FLOOR,
        )
        unreadable_own = admission_from_reading(
            CudaDeviceMemory(
                torch_present=True,
                cuda_present=True,
                free_mib=float(_BELOW_FLOOR_MIB),
                total_mib=float(_SCENARIO_TOTAL_MIB),
                own_reserved_mib=None,
            ),
            floor_mib=_FLOOR,
        )

        assert covered.admitted is True
        assert covered.reason == ""
        assert covered.own_mib == gap
        assert short.admitted is False
        assert short.reason == REASON_BELOW_FLOOR
        assert unreadable_own.admitted is False
        assert unreadable_own.own_mib is None

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
                free_mib=_FLOOR - 0.4,
                total_mib=float(_SCENARIO_TOTAL_MIB),
                own_reserved_mib=0.0,
            ),
            floor_mib=_FLOOR,
        )
        over = admission_from_reading(
            CudaDeviceMemory(
                torch_present=True,
                cuda_present=True,
                free_mib=_FLOOR + 0.4,
                total_mib=float(_SCENARIO_TOTAL_MIB),
                own_reserved_mib=0.0,
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
                free_mib=None,
                total_mib=None,
                own_reserved_mib=None,
            ),
            floor_mib=_FLOOR,
        )
        cpu_only = admission_from_reading(
            CudaDeviceMemory(
                torch_present=True,
                cuda_present=False,
                free_mib=None,
                total_mib=None,
                own_reserved_mib=None,
            ),
            floor_mib=_FLOOR,
        )

        assert absent.reason == REASON_TORCH_ABSENT
        assert cpu_only.reason == REASON_NO_CUDA
        assert absent.admitted is False
        assert cpu_only.admitted is False
        assert absent.free_mib is None
        assert cpu_only.free_mib is None

    def test_one_unreadable_reading_is_a_hiccup_and_is_admitted(self) -> None:
        """A single refused memory query must not refuse all GPU work.

        The deliberate fail-open, kept for the case it was written for: one
        driver blip says nothing about whether the device will answer the next
        question, and the per-job CUDA ceiling and the allocator's own backoff
        remain in force behind this gate. Asserted so the choice stays visible
        rather than incidental - and so the refusal below is proven to be about
        persistence rather than about unreadability as such.

        Mutation: widened the streak comparison to ``>= 0`` so every unreadable
        reading refused. Observed this assertion fail on ``admitted is True``.
        """
        admission = admission_from_reading(
            _UNREADABLE_WITH_TOTAL,
            floor_mib=_FLOOR,
            unreadable_streak=1,
        )

        assert admission.admitted is True
        assert admission.reason == ""
        assert admission.free_mib is None

    def test_a_persistently_unreadable_device_is_refused(self) -> None:
        """A device that has stopped answering is a fault, not a hiccup.

        The defect this guard exists for: with no memory of previous readings
        the gate admitted an unbounded run of loads onto a device that had
        stopped answering, and every job it admitted failed on a driver error
        it could not attribute. The streak is the whole difference, so it is
        the only input that moves between this test and the one above.

        Mutation: restored the unconditional ``admitted=True`` this branch
        shipped with. Observed this assertion fail on ``admitted is False``.
        """
        admission = admission_from_reading(
            _UNREADABLE_WITH_TOTAL,
            floor_mib=_FLOOR,
            unreadable_streak=UNREADABLE_ADMISSION_LIMIT,
        )

        assert admission.admitted is False
        assert admission.reason == REASON_DEVICE_UNREADABLE
        assert admission.free_mib is None

    def test_the_last_tolerated_reading_still_admits(self) -> None:
        """The threshold is a boundary, and it is asserted as one.

        A guard that only ever checks a streak far past the limit cannot tell a
        correct threshold from one placed a reading early or late, which is the
        off-by-one this fixes in place.

        Mutation: changed the comparison to ``>`` so the limit itself admitted.
        Observed the refusal assertion below fail on ``admitted is False``.
        """
        tolerated = admission_from_reading(
            _UNREADABLE_WITH_TOTAL,
            floor_mib=_FLOOR,
            unreadable_streak=UNREADABLE_ADMISSION_LIMIT - 1,
        )
        refused = admission_from_reading(
            _UNREADABLE_WITH_TOTAL,
            floor_mib=_FLOOR,
            unreadable_streak=UNREADABLE_ADMISSION_LIMIT,
        )

        assert tolerated.admitted is True
        assert refused.admitted is False

    def test_an_unreadable_refusal_is_told_apart_from_an_absent_device(
        self,
    ) -> None:
        """Two refusals that send an operator to two different places.

        A device present but not answering is a driver fault; a device that is
        not there is an installation or hardware question. Collapsing them
        points the operator at the wrong thing, which is the same failure the
        torch-absent/no-CUDA split already exists to prevent.

        Mutation: reused ``REASON_NO_CUDA`` for the unreadable refusal.
        Observed this assertion fail on the reason inequality.
        """
        unreadable = admission_from_reading(
            _UNREADABLE_WITH_TOTAL,
            floor_mib=_FLOOR,
            unreadable_streak=UNREADABLE_ADMISSION_LIMIT,
        )
        absent = admission_from_reading(
            CudaDeviceMemory(
                torch_present=True,
                cuda_present=False,
                free_mib=None,
                total_mib=None,
                own_reserved_mib=None,
            ),
            floor_mib=_FLOOR,
        )

        assert unreadable.reason != absent.reason
        assert unreadable.reason == REASON_DEVICE_UNREADABLE
        assert absent.reason == REASON_NO_CUDA

    def test_the_unreadable_refusal_names_the_driver_not_the_floor(self) -> None:
        """The remedy has to match the fault the operator actually has.

        Nothing about an unreadable device is fixed by waiting for a tenant or
        by lowering the admission floor, and a message that offered either
        would send an operator to spend time on a knob that cannot help.

        Mutation: rendered the contended prose for this reason too. Observed
        this assertion fail on the floor-knob absence check.
        """
        message = device_refusal_message(
            admission_from_reading(
                _UNREADABLE_WITH_TOTAL,
                floor_mib=_FLOOR,
                unreadable_streak=UNREADABLE_ADMISSION_LIMIT,
            )
        )

        assert "nvidia-smi" in message
        assert EnvVar.GPU_ADMISSION_FLOOR_MIB.value not in message
        assert DEVICE_CONTENDED_MESSAGE not in message

    def test_the_refusal_message_names_free_the_floor_and_a_way_out(self) -> None:
        """An operator can only act on a refusal that carries the figures.

        Mutation: dropped the reading from the rendered message, leaving the
        standing prose alone. Observed this assertion fail on the free-memory
        membership check.
        """
        message = device_refusal_message(
            admission_from_reading(_CROWDED, floor_mib=_FLOOR)
        )

        assert f"{_BELOW_FLOOR_MIB} MiB free" in message
        assert f"{_FLOOR} MiB floor" in message
        assert EnvVar.GPU_ADMISSION_FLOOR_MIB.value in message

    def test_the_refusal_message_names_the_process_s_own_checkout(self) -> None:
        """A refusal that credited residency must show the credited figure.

        Without it the message's free reading understates what the comparison
        actually saw, and an operator reconciling the figure against the floor
        would find a verdict the printed numbers do not reproduce.

        Mutation: dropped the own-checkout clause from the rendered message.
        Observed this assertion fail on the ``already holds`` membership
        check.
        """
        own = _SCENARIO_MARGIN_MIB // 2
        message = device_refusal_message(
            admission_from_reading(
                CudaDeviceMemory(
                    torch_present=True,
                    cuda_present=True,
                    free_mib=float(_BELOW_FLOOR_MIB),
                    total_mib=float(_SCENARIO_TOTAL_MIB),
                    own_reserved_mib=float(own),
                ),
                floor_mib=_FLOOR,
            )
        )

        assert f"plus {own} MiB this process already holds" in message
        assert f"{_BELOW_FLOOR_MIB} MiB free" in message


class TestTheUnreadableLedger:
    """What the gate remembers between readings, and what clears it."""

    def test_consecutive_unreadable_readings_accumulate(self) -> None:
        """Without accumulation the threshold can never be reached.

        Mutation: made the ledger return a constant 1. Observed this assertion
        fail on the second element of the observed sequence.
        """
        observed = [observe_unreadable_streak(_UNREADABLE_WITH_TOTAL) for _ in range(3)]

        assert observed == [1, 2, 3]

    def test_a_reading_that_answers_clears_the_streak(self) -> None:
        """A hiccup must cost nothing once the device answers again.

        This is the half that keeps the refusal narrow: without it, a device
        that blips occasionally over a long-lived process eventually
        accumulates its way to a refusal it never deserved.

        Mutation: dropped the reset branch so the counter only ever grew.
        Observed this assertion fail on ``cleared == 0``.
        """
        for _ in range(UNREADABLE_ADMISSION_LIMIT):
            observe_unreadable_streak(_UNREADABLE_WITH_TOTAL)

        cleared = observe_unreadable_streak(_ROOMY)
        after = observe_unreadable_streak(_UNREADABLE_WITH_TOTAL)

        assert cleared == 0
        assert after == 1

    def test_a_reading_that_never_reached_the_question_leaves_it_alone(
        self,
    ) -> None:
        """An absent device is not evidence that a faulty one recovered.

        A CPU-only or torch-free reading answers a question about the
        installation, not about a device that has stopped responding. Letting
        it clear the streak would let an unplugged card launder a real fault
        into a fresh start on the next reading.

        Mutation: replaced the ``cuda_present`` test with a bare ``else``, so
        an absent device counted toward the streak like an unreadable one.
        Observed this assertion fail on ``preserved == 2``, the streak having
        reached three.
        """
        observe_unreadable_streak(_UNREADABLE_WITH_TOTAL)
        observe_unreadable_streak(_UNREADABLE_WITH_TOTAL)

        observe_unreadable_streak(
            CudaDeviceMemory(
                torch_present=True,
                cuda_present=False,
                free_mib=None,
                total_mib=None,
                own_reserved_mib=None,
            )
        )
        preserved = observe_unreadable_streak(_UNREADABLE_WITH_TOTAL) - 1

        assert preserved == 2

    def test_a_supplied_reading_is_judged_by_the_ledger_too(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """The window's supplied reading must not bypass the streak.

        A supplied reading that skipped the ledger would exercise a predicate
        production never runs, which is the failure a guard is meant to catch
        rather than embody. Driven through the real window on a real lock, so
        what is asserted is the production composition and not a re-derivation
        of it.

        Mutation: judged the supplied reading against the floor alone, the
        shape this path had before the ledger existed. Observed this assertion
        fail on ``verdicts[-1].admitted is False``.
        """
        del floor
        anchor = tmp_path / "load-window.lock"
        verdicts: list[DeviceAdmission] = []
        for _ in range(UNREADABLE_ADMISSION_LIMIT):
            with device_load_window(
                anchor=anchor,
                reading=_UNREADABLE_WITH_TOTAL,
            ) as admission:
                verdicts.append(admission)

        assert verdicts[0].admitted is True
        assert verdicts[-1].admitted is False
        assert verdicts[-1].reason == REASON_DEVICE_UNREADABLE

    def test_a_diagnostic_reading_advances_the_streak_a_load_then_sees(
        self,
        tmp_path: Path,
        floor: int,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The polling a daemon already does is what makes the limit reachable.

        The health payload and the jobs listing publish this verdict, so a
        long-lived process on a failing card takes readings whether or not a
        load is ever attempted. Those readings feed the same ledger the load
        gate consults, which is what puts the refusal within seconds of the
        fault instead of within however long it takes to attempt three loads -
        on a daemon asked for model work rarely, that is the difference between
        a limit that is reached and one that is not.

        The coupling is the audit's, not a test's invention: the two figures
        that set the real-time window - this limit and the cadence of whatever
        polls - live in different modules, and nothing else states that they
        compose. A later refactor sparing the read-only path from touching
        mutable state would read as a tidy-up and would silently put the streak
        back on load attempts alone.

        Asserted across both paths at once, driving the probed reading through
        the diagnostic entry point and the load through the real window, because
        neither path's own guards can see the ledger they share.

        Mutation: judged the probed reading against the floor alone, sparing the
        diagnostic path the ledger. Observed this fail on ``DID NOT RAISE
        RuntimeError``, the load arriving as the streak's first unreadable
        reading and being admitted as a hiccup.
        """
        del floor
        monkeypatch.setattr(
            "vaultspec_rag.memory_probe.cuda_device_memory",
            lambda: _UNREADABLE_WITH_TOTAL,
        )
        for _ in range(UNREADABLE_ADMISSION_LIMIT - 1):
            assert device_load_reading() is not None

        source = _windowed(
            tmp_path / "load-window.lock",
            [_UNREADABLE_WITH_TOTAL],
            [],
        )

        def _loader() -> str:
            return "loaded"

        with pytest.raises(RuntimeError, match="present but not answering"):
            admit_accelerator_load(_loader, window=source)

    def test_a_persistently_unreadable_device_stops_the_load(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """The refusal has to reach the loader, not merely be reported.

        A reason the gate computes but does not act on is the whole defect in
        another form: the incident was not a missing verdict but an unbounded
        run of loads admitted alongside one.

        Mutation: left ``REASON_DEVICE_UNREADABLE`` out of the refusing set.
        Observed this fail on ``DID NOT RAISE RuntimeError`` - the gate having
        computed the refusal and handed the loader the device anyway, which is
        the defect's exact shape one layer up.
        """
        del floor
        entries: list[int] = []
        loads: list[str] = []
        source = _windowed(
            tmp_path / "load-window.lock",
            [_UNREADABLE_WITH_TOTAL],
            entries,
        )

        def _loader() -> str:
            loads.append("loaded")
            return "loaded"

        for _ in range(UNREADABLE_ADMISSION_LIMIT - 1):
            admit_accelerator_load(_loader, window=source)
        with pytest.raises(RuntimeError, match="present but not answering"):
            admit_accelerator_load(_loader, window=source)

        assert len(loads) == UNREADABLE_ADMISSION_LIMIT - 1

    def test_a_refused_unreadable_verdict_does_not_latch(
        self,
        tmp_path: Path,
        floor: int,
    ) -> None:
        """An unverifiable observation must never retire the floor check.

        The refusal reached no floor comparison, so latching it would leave the
        gate reporting itself present while the predicate it exists for had
        stopped running - the worst direction for unverifiable state to move
        protection.

        Mutation: latched on any verdict rather than only on one that reached
        the comparison. Observed this assertion fail on ``entries``, the second
        load riding the refused verdict instead of re-reading the device.
        """
        del floor
        entries: list[int] = []
        source = _windowed(
            tmp_path / "load-window.lock",
            [_UNREADABLE_WITH_TOTAL, _UNREADABLE_WITH_TOTAL, _ROOMY],
            entries,
        )

        def _loader() -> str:
            return "loaded"

        for _ in range(UNREADABLE_ADMISSION_LIMIT - 1):
            admit_accelerator_load(_loader, window=source)
        assert admit_accelerator_load(_loader, window=source) == "loaded"

        assert len(entries) == UNREADABLE_ADMISSION_LIMIT


class TestTheFloorIsDerivedFromTheWorkload:
    """The floor is a statement about the models, never about one card.

    A shipped absolute cannot be right on more than one device: sized to a large
    card it refuses every load on a smaller one - permanently, because free
    memory can never reach it - and sized to a small one it under-protects a
    larger card, where two stacks still collide beneath the figure it names. So
    what is pinned here is that the floor tracks the declared CUDA demand of the
    workload, that it moves when that declaration does, and that an operator
    keeps the last word for a card they know better.
    """

    def test_the_shipped_configuration_names_no_device_size(self) -> None:
        """The default must be a derivation, not a figure.

        Mutation: restored an absolute default (11264). Observed this assertion
        fail on ``shipped == 0``, the shipped configuration once again asserting
        a size for a card it has never seen.
        """
        assert int(rag_default("gpu_admission_floor_mib")) == 0

    def test_the_floor_covers_the_configured_workload_s_declared_demand(
        self,
    ) -> None:
        """A load needs room for what it creates AND what it then does.

        The profile declares that demand per content domain and the per-job CUDA
        ceiling is derived from the same declaration, so the floor covering it is
        what makes "room for one workload" mean the same thing on both sides.

        Mutation: derived the floor from ``min`` of the two domains instead of
        ``max``. Observed this assertion fail on the code domain's 12288 MiB
        against a floor of 12288 for a profile whose domains differ - and on the
        ``>=`` for a profile where the document domain is the larger.
        """
        from ..._gpu_admission import _workload_floor_mib
        from ...config._settings import get_config
        from ...index_profiles import get_index_support_profile

        profile = get_index_support_profile(get_config().index_support_profile)
        declared_mib = max(
            bytes_to_mib(profile.code.cuda_bytes),
            bytes_to_mib(profile.document.cuda_bytes),
        )

        assert _workload_floor_mib() >= int(declared_mib), (
            "the derived floor does not cover one workload's declared CUDA "
            "demand, so a second stack can be admitted beside a resident one"
        )

    def test_a_smaller_workload_profile_yields_a_smaller_floor(self) -> None:
        """The floor moves with the workload, which is the whole point.

        The two shipped profiles declare different CUDA demand, so a derivation
        that tracks the workload must separate them. A constant cannot.

        Mutation: returned a fixed figure from ``_workload_floor_mib``. Observed
        this assertion fail on ``embedded < managed`` with both figures equal.
        """
        from ..._gpu_admission import _workload_floor_mib

        with managed_env(**{EnvVar.INDEX_SUPPORT_PROFILE.value: "managed-service"}):
            managed = _workload_floor_mib()
        with managed_env(**{EnvVar.INDEX_SUPPORT_PROFILE.value: "embedded-local"}):
            embedded = _workload_floor_mib()

        assert embedded < managed

    def test_an_operator_figure_overrides_the_derivation(self) -> None:
        """One card's owner may know it better than any derivation.

        Mutation: dropped the ``configured > 0`` branch from
        ``_configured_floor_mib``. Observed this assertion fail on
        ``floor == _FLOOR``, the override silently replaced by the derived
        figure.
        """
        from ..._gpu_admission import _configured_floor_mib, _workload_floor_mib

        with managed_env(**{EnvVar.GPU_ADMISSION_FLOOR_MIB.value: str(_FLOOR)}):
            assert _configured_floor_mib() == _FLOOR
        assert _configured_floor_mib() == _workload_floor_mib()

    def test_the_declared_demand_covers_this_project_s_measured_stack(
        self,
    ) -> None:
        """The declaration has to be sound, not merely present.

        A derivation is only as good as what it derives from: a profile
        declaring less CUDA demand than the models actually take would produce a
        floor that admits a second stack onto a card holding one. The two figures
        it is checked against are measurements of this project's models - a
        property of the software, not of any device - so this stays meaningful on
        hardware none of them was taken on.

        Mutation: halved the profile's ``cuda_bytes`` declaration. Observed this
        assertion fail on ``declared >= required`` with 6144 against 10910.
        """
        from ...config._settings import get_config
        from ...index_profiles import get_index_support_profile

        profile = get_index_support_profile(get_config().index_support_profile)
        declared = min(
            bytes_to_mib(profile.code.cuda_bytes),
            bytes_to_mib(profile.document.cuda_bytes),
        )
        required = _MEASURED_RESIDENT_STACK_MIB + _MEASURED_PEAK_NET_DEMAND_MIB

        assert declared >= required, (
            f"the profile declares {declared:.0f} MiB of CUDA demand but the "
            f"stacks measure {_MEASURED_RESIDENT_STACK_MIB} MiB resident plus "
            f"{_MEASURED_PEAK_NET_DEMAND_MIB} MiB of demand above them; a floor "
            "derived from this declaration would admit a load the card cannot hold"
        )


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
