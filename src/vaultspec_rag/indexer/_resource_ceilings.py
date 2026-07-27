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


def _require_cuda_headroom(
    *,
    ceiling_mb: float,
    baseline_mb: float,
    configured_mb: float,
) -> None:
    """Refuse before dispatch when the ceiling admits no forward at all.

    Enforcement compares peak and ceiling NET of the resident baseline, so a
    ceiling at or below that baseline leaves zero admissible headroom: every
    forward, however small, breaches it. Enforcing such a ceiling turns one
    admission-time fact into a run's worth of mid-forward failures, each
    reporting a "0.0 MiB ceiling" that names neither the baseline that consumed
    it nor the knob that would restore it.

    The threshold is strictly "no headroom at all". A ceiling with any positive
    room above the baseline is admitted and enforced exactly as before - a
    deliberately tiny budget is a legitimate configuration, and a floor that
    rejected it would refuse the jobs whose whole purpose is to prove the
    ceiling still fires.

    The two ways headroom disappears need different operator actions, so the
    detail names which one happened rather than leaving both under the shared
    "stop competing GPU work" remediation.

    Raises:
        JobError: With ``CUDA_MEMORY_CEILING``, so the refusal carries the same
            typed identity, envelope, and remediation channel as the mid-run
            breach it replaces.
    """
    if ceiling_mb - baseline_mb > 0.0:
        return
    from .._job_errors import JobError, JobErrorKind

    if configured_mb > 0:
        detail = (
            f"the configured CUDA ceiling of {configured_mb:.1f} MiB is at or "
            f"below the {baseline_mb:.1f} MiB resident model baseline, leaving "
            "no memory for any forward pass; raise the configured ceiling "
            "above the baseline, or load fewer models"
        )
    else:
        detail = (
            f"no CUDA memory remains above the {baseline_mb:.1f} MiB resident "
            "model baseline; free device memory or stop competing GPU work "
            "before indexing"
        )
    raise JobError(JobErrorKind.CUDA_MEMORY_CEILING, detail)


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
    from ..config._settings import get_config
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
    cuda_ceiling_mb = resolve_index_cuda_ceiling_mb(
        configured_mb=config.index_cuda_ceiling_mb,
        headroom_mb=config.index_cuda_headroom_mb,
        profile_cuda_mb=profile_cuda_mb,
        baseline_mb=cuda_baseline_mb or 0.0,
    )
    # Only where CUDA is actually enforced: off the GPU path every reading the
    # ceiling would be compared against is structurally zero, so a ceiling that
    # looks empty there costs nothing and must not refuse the run.
    if uses_cuda:
        _require_cuda_headroom(
            ceiling_mb=cuda_ceiling_mb,
            baseline_mb=cuda_baseline_mb or 0.0,
            configured_mb=config.index_cuda_ceiling_mb,
        )
    return AdmittedCeilings(
        rss_ceiling_mb=rss_ceiling_mb,
        cuda_ceiling_mb=cuda_ceiling_mb,
        cuda_baseline_mb=cuda_baseline_mb,
        uses_cuda=uses_cuda,
    )
