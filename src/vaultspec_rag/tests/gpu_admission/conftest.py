"""Shared scenario values and fixtures for the admission-gate guards.

The device reading is supplied as a value wherever the judgement rather than
the measurement is under test, so an absent torch, a CPU-only build, a driver
that refused the memory query, and a figure exactly at the floor are all
exercised without a machine that happens to present them. The lock is always
the real OS advisory lock on a real file; only the anchor moves, into a temp
dir, so a test never contends for the machine-global lock another tenant may
legitimately hold, and never gets a green result from a lock that was not taken.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..._gpu_admission import (
    DeviceAdmission,
    clear_accelerator_admission_latch,
    device_load_window,
    observe_unreadable_streak,
)
from ...config._types import EnvVar
from ...memory_probe import CudaDeviceMemory
from ..conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from contextlib import AbstractContextManager
    from pathlib import Path

pytestmark = [pytest.mark.unit]
_FLOOR = 8448

#: The scenario device every reading below describes, stated as a relation to the
#: floor under test rather than as any real card: a total twice the floor, with
#: free memory a margin above it in one reading and the same margin below it in
#: the other. What the floor separates is those two figures, and naming a
#: particular device would tie these guards to one machine while asserting
#: nothing extra - the comparison does not know how large the card is.
_SCENARIO_TOTAL_MIB = _FLOOR * 2
_SCENARIO_MARGIN_MIB = 2048
_ABOVE_FLOOR_MIB = _FLOOR + _SCENARIO_MARGIN_MIB
_BELOW_FLOOR_MIB = _FLOOR - _SCENARIO_MARGIN_MIB

#: Room to spare, and the same device with a FOREIGN tenant's stack resident on
#: it. The pair is what the floor is meant to separate. Both carry a zero own
#: checkout on purpose: the crowding is entirely another process's, so nothing
#: is credited back and the free figure alone decides.
_ROOMY = CudaDeviceMemory(
    torch_present=True,
    cuda_present=True,
    free_mib=float(_ABOVE_FLOOR_MIB),
    total_mib=float(_SCENARIO_TOTAL_MIB),
    own_reserved_mib=0.0,
)
_CROWDED = CudaDeviceMemory(
    torch_present=True,
    cuda_present=True,
    free_mib=float(_BELOW_FLOOR_MIB),
    total_mib=float(_SCENARIO_TOTAL_MIB),
    own_reserved_mib=0.0,
)

#: A present device whose driver answered presence and then refused the memory
#: query. Its verdict is the one no floor was consulted for - which is what the
#: latch has to tell apart - and, below the streak limit, an admitted one. It
#: carries no device size on purpose: nothing asserted about the latch depends
#: on one, and a figure here would tie this guard to a particular card without
#: buying it anything.
_UNREADABLE = CudaDeviceMemory(
    torch_present=True,
    cuda_present=True,
    free_mib=None,
    total_mib=None,
    own_reserved_mib=None,
)

#: The same refused query on a device that did report its size. Total memory is
#: readable through a different call than free memory, so a driver can answer
#: one and refuse the other; the predicate tests use this reading so they are
#: exercising an absent FREE figure specifically rather than a reading that is
#: empty in every dimension.
_UNREADABLE_WITH_TOTAL = CudaDeviceMemory(
    torch_present=True,
    cuda_present=True,
    free_mib=None,
    total_mib=float(_SCENARIO_TOTAL_MIB),
    own_reserved_mib=None,
)

#: Two measured properties of this project's MODELS, in MiB: what the embedding,
#: sparse, and reranker stacks occupy together once all three are resident, and
#: the largest legitimate demand one of them then places above that residency.
#: Model weights occupy what they occupy on any card, so these travel with the
#: software rather than with the machine they were measured on - which is what
#: lets them check the profile's declared demand without asserting a device size.
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
    """Leave the latch clear and the unreadable ledger settled at both edges.

    The latch is per-process by design, so a test that sets it would otherwise
    hand the next test an admission it never asked for - and the latch's whole
    job is to suppress a second evaluation, which would make that next test pass
    without exercising anything.

    The unreadable streak is per-process for the same reason and needs the same
    treatment in the other direction: a test that leaves it near the limit would
    hand the next one a refusal it never asked for. It is settled by feeding the
    ledger a reading that answers - the production reset path, not a back door
    into the counter - which is also the behaviour under test in the ledger
    guards below, so nothing here can pass on a reset that production lacks.
    """
    clear_accelerator_admission_latch()
    observe_unreadable_streak(_ROOMY)
    try:
        yield
    finally:
        clear_accelerator_admission_latch()
        observe_unreadable_streak(_ROOMY)


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
