"""Classify an installed torch build from its observable CUDA attributes."""

from __future__ import annotations

from ._constants import TorchDiagnosis


def diagnose_torch(cuda: str | None, available: bool) -> TorchDiagnosis:
    """Classify a torch install from its observable CUDA attributes.

    Args:
        cuda: ``torch.version.cuda`` — ``None`` for the CPU-only
            wheel, a version string like ``"13.0"`` for the CUDA
            wheels.
        available: ``torch.cuda.is_available()`` result.

    Returns:
        One of :class:`TorchDiagnosis`. ``(None, True)`` is an
        anomaly not produced by any supported torch build; we fall
        back to ``CPU_ONLY`` because the remediation (reinstall from
        cu130) is the safer of the two.
    """
    if cuda is None:
        return TorchDiagnosis.CPU_ONLY
    if available:
        return TorchDiagnosis.WORKING
    return TorchDiagnosis.NO_GPU
