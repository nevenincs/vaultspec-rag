"""Classify an installed torch build from observable accelerator attributes."""

from __future__ import annotations

from ._constants import TorchDiagnosis


def diagnose_torch(
    cuda: str | None,
    cuda_available: bool,
    mps_available: bool = False,
) -> TorchDiagnosis:
    """Classify a torch install from observable accelerator attributes.

    Args:
        cuda: ``torch.version.cuda`` - ``None`` for the CPU-only
            wheel, a version string like ``"13.0"`` for the CUDA
            wheels.
        cuda_available: ``torch.cuda.is_available()`` result.
        mps_available: ``torch.backends.mps.is_available()`` result.

    Returns:
        One of :class:`TorchDiagnosis`. A usable CUDA or MPS device is
        ``WORKING``. Without either device, a CUDA-capable build is
        ``NO_GPU`` and a build with no CUDA runtime is ``CPU_ONLY``.
    """
    if cuda_available or mps_available:
        return TorchDiagnosis.WORKING
    return TorchDiagnosis.CPU_ONLY if cuda is None else TorchDiagnosis.NO_GPU
