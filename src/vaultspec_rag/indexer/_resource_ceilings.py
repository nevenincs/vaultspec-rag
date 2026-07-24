"""Memory-ceiling admission shared by the code and document indexers.

Both indexers freeze the same three figures before dispatching work - the
process RSS ceiling, the CUDA ceiling, and the resident-model baseline the CUDA
comparison is taken net of - from the same three inputs: operator config, the
admitted support profile, and whether the encoding model is on the GPU at all.
What each indexer does with them afterwards differs (they enforce through
different budget objects), so only the derivation lives here.

This is the code that decides whether a running job is killed for memory, which
is precisely why it is not duplicated. A divergence between the two copies would
not announce itself: one source type would simply be admitted under a ceiling
the other is not, and the first evidence would be a job dying on a corpus that
its sibling indexes without complaint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..index_profiles import SupportProfileLimits

__all__ = [
    "AdmittedCeilings",
    "admit_index_ceilings",
]


@dataclass(frozen=True, slots=True)
class AdmittedCeilings:
    """The memory ceilings one index run is admitted under."""

    rss_ceiling_mb: float
    cuda_ceiling_mb: float
    cuda_baseline_mb: float | None
    uses_cuda: bool

    @property
    def enforced_cuda_ceiling_mb(self) -> float | None:
        """Return the CUDA ceiling only where CUDA is actually enforced.

        Off the GPU path the derived figure is a profile default rather than
        anything the host can honour, and every reading it would be compared
        against is structurally zero, so no ceiling is admitted at all.
        """
        return self.cuda_ceiling_mb if self.uses_cuda else None


def admit_index_ceilings(
    model: object,
    limits: SupportProfileLimits | None,
) -> AdmittedCeilings:
    """Freeze one run's memory ceilings from config, profile, and device.

    ``limits`` is optional because the code indexer measures its corpus - and
    so resolves its profile - as a separate step before admission; a caller
    that has not reached that step yet is held to the configured ceiling alone
    rather than to no ceiling.

    The allocator cache is released before the baseline is read so this
    process's own retention cannot depress the free-memory reading the device-
    derived ceiling is built from.
    """
    from .._units import bytes_to_mib
    from ..config import get_config
    from ..memory_probe import (
        reset_cuda_peak_memory_stats,
        resident_cuda_baseline_mb,
        resolve_index_cuda_ceiling_mb,
    )

    config = get_config()
    rss_ceiling_mb = config.index_rss_ceiling_mb
    profile_cuda_mb = config.index_cuda_ceiling_mb
    if limits is not None:
        rss_ceiling_mb = min(rss_ceiling_mb, bytes_to_mib(limits.rss_bytes))
        profile_cuda_mb = bytes_to_mib(limits.cuda_bytes)
    uses_cuda = getattr(model, "device", None) == "cuda"
    if uses_cuda:
        reset_cuda_peak_memory_stats()
    cuda_baseline_mb = resident_cuda_baseline_mb() if uses_cuda else None
    return AdmittedCeilings(
        rss_ceiling_mb=rss_ceiling_mb,
        cuda_ceiling_mb=resolve_index_cuda_ceiling_mb(
            configured_mb=config.index_cuda_ceiling_mb,
            headroom_mb=config.index_cuda_headroom_mb,
            profile_cuda_mb=profile_cuda_mb,
            baseline_mb=cuda_baseline_mb or 0.0,
        ),
        cuda_baseline_mb=cuda_baseline_mb,
        uses_cuda=uses_cuda,
    )
