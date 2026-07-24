"""Unit coverage for the shared byte/mebibyte vocabulary and its projections."""

from __future__ import annotations

import pytest

from .._units import bytes_to_mib, human_bytes, mib_to_bytes
from ..memory_probe import MemoryBudgetSnapshot, snapshot_resource_bytes

pytestmark = [pytest.mark.unit]

_MIB = 1024 * 1024


def _snapshot(
    *,
    peak_rss_mb: float = 0.0,
    peak_cuda_allocated_mb: float = 0.0,
    peak_cuda_reserved_mb: float = 0.0,
) -> MemoryBudgetSnapshot:
    """Build a snapshot carrying only the fields a projection reads."""
    return MemoryBudgetSnapshot(
        label="probe",
        rss_mb=peak_rss_mb,
        rss_available=True,
        peak_rss_mb=peak_rss_mb,
        rss_ceiling_mb=None,
        cuda_allocated_mb=peak_cuda_allocated_mb,
        cuda_available=True,
        peak_cuda_allocated_mb=peak_cuda_allocated_mb,
        cuda_reserved_mb=peak_cuda_reserved_mb,
        peak_cuda_reserved_mb=peak_cuda_reserved_mb,
        cuda_ceiling_mb=None,
    )


class TestConversions:
    """The divisor is binary, and the two directions agree."""

    def test_bytes_to_mib_uses_the_binary_divisor(self):
        """A decimal divisor would make this 1.048576."""
        assert bytes_to_mib(_MIB) == 1.0
        assert bytes_to_mib(3 * _MIB) == 3.0

    def test_mib_to_bytes_is_the_inverse(self):
        assert mib_to_bytes(1.0) == _MIB
        assert mib_to_bytes(bytes_to_mib(7 * _MIB)) == 7 * _MIB

    def test_mib_to_bytes_truncates_rather_than_rounds(self):
        """A projection must never round a high-water upward into headroom.

        Rounding a fractional byte up would report a peak fractionally larger
        than the one measured, which a ceiling comparison would then honour.
        """
        assert mib_to_bytes(1.9999999 / _MIB) == 1

    def test_zero_and_negative_survive_the_round_trip(self):
        assert bytes_to_mib(0) == 0.0
        assert mib_to_bytes(0.0) == 0
        assert bytes_to_mib(-_MIB) == -1.0


class TestHumanBytes:
    """Operator-facing rendering picks the largest unit above one."""

    @pytest.mark.parametrize(
        ("num_bytes", "expected"),
        [
            (0, "0 B"),
            (512, "512 B"),
            (_MIB, "1.0 MiB"),
            (1024 * _MIB, "1.0 GiB"),
            (68719476736, "64.0 GiB"),
        ],
    )
    def test_rendering(self, num_bytes: int, expected: str):
        assert human_bytes(num_bytes) == expected

    def test_whole_bytes_render_without_a_fraction(self):
        """ "0.0 B" reads as an unset field where "0 B" reads as a measurement."""
        assert human_bytes(0) == "0 B"

    def test_the_sign_survives(self):
        assert human_bytes(-_MIB) == "-1.0 MiB"


class TestSnapshotProjection:
    """The projection every indexer shares."""

    def test_the_cuda_dimension_carries_allocated_never_reserved(self):
        """Reserved must not reach the corpus-limit dimension.

        Reserved ratchets with the allocator's retention history rather than
        with the work, so projecting it would fail well-sized jobs on
        fragmentation inherited from earlier runs. The two peaks are
        deliberately different here: an implementation that reads the reserved
        field returns 8 MiB of bytes instead of 2 and fails on that number, so
        this must not be relaxed to a shared-field assertion.
        """
        snapshot = _snapshot(peak_cuda_allocated_mb=2.0, peak_cuda_reserved_mb=8.0)

        _, cuda_bytes = snapshot_resource_bytes(snapshot)

        assert cuda_bytes == 2 * _MIB

    def test_the_rss_dimension_carries_the_high_water(self):
        snapshot = _snapshot(peak_rss_mb=5.0)

        rss_bytes, _ = snapshot_resource_bytes(snapshot)

        assert rss_bytes == 5 * _MIB
