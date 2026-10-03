"""Automatic CUDA admission credits capacity already held by the allocator."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from .. import memory_probe
from .._job_errors import JobError, JobErrorKind
from ..memory_probe import CudaDeviceMemory, MemoryBudget

pytestmark = pytest.mark.unit

BASELINE_MIB = 2958.4
RECORDED_FORWARD_PEAK_MIB = 11853.1
RESERVATION_CEILING_MIB = 12929.0
PROFILE_MIB = 12288.0


@pytest.fixture
def device_observation(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Replace only the guarded device observation, without loading Torch."""
    observation = Mock(
        return_value=CudaDeviceMemory(True, True, 10497.0, 16375.0, 4480.0)
    )
    monkeypatch.setattr(memory_probe, "cuda_device_memory", observation)
    return observation


def test_own_reservation_admits_recorded_forward(device_observation: Mock) -> None:
    """Omitting production reservation credit rejects this completed forward."""
    ceiling = memory_probe.resolve_index_cuda_ceiling_mib(
        configured_mib=0.0,
        headroom_mib=2048.0,
        profile_cuda_mib=PROFILE_MIB,
        baseline_mib=BASELINE_MIB,
    )
    budget = MemoryBudget(cuda_ceiling_mib=ceiling, cuda_baseline_mib=BASELINE_MIB)
    try:
        snapshot = budget.observe(
            label="recorded completed forward",
            rss_mib=0.0,
            cuda_allocated_mib=RECORDED_FORWARD_PEAK_MIB,
            cuda_reserved_mib=12666.0,
        )
    except JobError as exc:
        pytest.fail(f"own reservation must admit the recorded forward: {exc}")
    assert snapshot.peak_cuda_allocated_mib == RECORDED_FORWARD_PEAK_MIB
    assert snapshot.cuda_ceiling_mib == RESERVATION_CEILING_MIB
    device_observation.assert_called_once_with()


def test_credited_capacity_still_rejects_excessive_actual_peak(
    device_observation: Mock,
) -> None:
    """Both sides remain absolute while the comparison subtracts the baseline."""
    ceiling = memory_probe.resolve_index_cuda_ceiling_mib(
        configured_mib=0.0,
        headroom_mib=2048.0,
        profile_cuda_mib=PROFILE_MIB,
        baseline_mib=BASELINE_MIB,
    )
    budget = MemoryBudget(cuda_ceiling_mib=ceiling, cuda_baseline_mib=BASELINE_MIB)
    exact = budget.observe(
        label="allocated peak exactly at ceiling",
        rss_mib=0.0,
        cuda_allocated_mib=RESERVATION_CEILING_MIB,
        cuda_reserved_mib=15000.0,
    )
    assert exact.peak_cuda_allocated_mib == exact.cuda_ceiling_mib
    with pytest.raises(JobError) as caught:
        budget.observe(
            label="allocated peak exceeds ceiling",
            rss_mib=0.0,
            cuda_allocated_mib=RESERVATION_CEILING_MIB + 1.0,
            cuda_reserved_mib=15000.0,
        )
    assert caught.value.error_kind is JobErrorKind.CUDA_MEMORY_CEILING
    assert "allocated peak exceeds ceiling" in str(caught.value)
    device_observation.assert_called_once_with()


@pytest.mark.parametrize(
    ("reading", "configured_mib", "headroom_mib", "expected_mib"),
    [
        pytest.param(
            CudaDeviceMemory(True, True, 10497.0, 16375.0, 4480.0),
            0.0,
            2048.0,
            RESERVATION_CEILING_MIB,
            id="reservation-includes-baseline",
        ),
        pytest.param(
            CudaDeviceMemory(True, True, 10497.0, 16375.0, 0.0),
            0.0,
            2048.0,
            8449.0,
            id="readable-zero-is-not-unknown",
        ),
        pytest.param(
            CudaDeviceMemory(True, True, 10497.0, 16375.0, None),
            0.0,
            2048.0,
            11407.4,
            id="unreadable-reservation-credits-only-baseline",
        ),
        pytest.param(
            CudaDeviceMemory(True, True, 15000.0, 16375.0, 4480.0),
            0.0,
            2048.0,
            14327.0,
            id="total-clamp",
        ),
        pytest.param(
            CudaDeviceMemory(True, True, 10497.0, 16375.0, 4480.0),
            0.0,
            4096.0,
            10881.0,
            id="configured-headroom-preserved",
        ),
        pytest.param(
            CudaDeviceMemory(True, True, 10497.0, 16375.0, 4480.0),
            15000.0,
            2048.0,
            15000.0,
            id="override-raises-past-profile-and-total-clamp",
        ),
        pytest.param(
            CudaDeviceMemory(True, True, 10497.0, 16375.0, 4480.0),
            6000.0,
            2048.0,
            6000.0,
            id="override-lowers",
        ),
        pytest.param(
            CudaDeviceMemory(True, True, None, 16375.0, 4480.0),
            0.0,
            2048.0,
            14327.0,
            id="unreadable-free-retains-total-fallback",
        ),
        pytest.param(
            CudaDeviceMemory(True, True, 10497.0, None, 4480.0),
            0.0,
            2048.0,
            PROFILE_MIB,
            id="unreadable-total-retains-profile-fallback",
        ),
        pytest.param(
            CudaDeviceMemory(True, True, None, None, None),
            0.0,
            2048.0,
            PROFILE_MIB,
            id="unreadable-device-retains-profile-fallback",
        ),
        pytest.param(
            CudaDeviceMemory(True, False, None, None, None),
            0.0,
            2048.0,
            PROFILE_MIB,
            id="cpu-only-profile-fallback",
        ),
        pytest.param(
            CudaDeviceMemory(False, False, None, None, None),
            0.0,
            2048.0,
            PROFILE_MIB,
            id="torch-absent-profile-fallback",
        ),
        pytest.param(
            CudaDeviceMemory(True, True, 500.0, 16375.0, 1000.0),
            0.0,
            2048.0,
            0.0,
            id="negative-capacity-clamps-to-zero",
        ),
    ],
)
def test_resolver_preserves_capacity_boundaries(
    device_observation: Mock,
    reading: CudaDeviceMemory,
    configured_mib: float,
    headroom_mib: float,
    expected_mib: float,
) -> None:
    """One guarded observation determines the shared admission result."""
    device_observation.return_value = reading
    ceiling = memory_probe.resolve_index_cuda_ceiling_mib(
        configured_mib=configured_mib,
        headroom_mib=headroom_mib,
        profile_cuda_mib=PROFILE_MIB,
        baseline_mib=BASELINE_MIB,
    )
    assert ceiling == expected_mib
    device_observation.assert_called_once_with()
