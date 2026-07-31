"""Centralized, GPU-gated torch loader for local (in-process) mode.

vaultspec-rag is a GPU-only project. Service-mode code paths never load
torch - they call a running daemon over HTTP and must stay torch-free.
Every local-mode site that needs torch for *compute* must obtain it through
``load_torch()`` so there is exactly one place that imports torch, asserts a
CUDA device is present, and fails hard when only a CPU-only build is
installed. Never write a naked ``import torch`` on a compute path; route it
through this function so who, when, and how torch loads stays controlled.

The torch import is function-local, so importing this module never pulls
torch into ``sys.modules`` - the service-mode torch-freedom invariant holds
even for modules that import this one.

Read-only probes that must tolerate a CPU-only or torch-absent host (the
``/health`` and ``/metrics`` reporters, the readiness diagnosis, the memory
probe) are the deliberate exception: they report ``cuda=False`` rather than
raise, so they keep their own guarded function-local import and do not call
``load_torch()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

__all__ = [
    "CUDA_REQUIRED_MESSAGE",
    "TORCH_MISSING_MESSAGE",
    "is_cuda_out_of_memory",
    "load_torch",
]

TORCH_MISSING_MESSAGE = (
    "GPU RAG dependencies not installed: torch is missing. Run `uv sync`, "
    "then `vaultspec-rag install` to provision the cu130 CUDA torch wheel."
)

CUDA_REQUIRED_MESSAGE = (
    "CUDA GPU required: no CUDA device is available. vaultspec-rag is a "
    "GPU-only project and never runs inference on CPU. The installed torch is "
    "a CPU-only build, or no NVIDIA GPU is present - install the cu130 torch "
    "wheel with `vaultspec-rag install` on a CUDA-capable machine."
)


def is_cuda_out_of_memory(exc: BaseException) -> bool:
    """Classify a Torch allocator failure without importing Torch elsewhere."""
    try:
        import torch
    except ImportError:
        return False
    return isinstance(exc, torch.cuda.OutOfMemoryError)


def load_torch() -> ModuleType:
    """Import torch for a local-mode compute path, asserting CUDA, or fail hard.

    The single gate every local-mode torch *compute* load must pass through.
    Returns the imported ``torch`` module. Raises ``ImportError`` when torch is
    not installed, ``RuntimeError`` when torch is installed but exposes no CUDA
    device (a CPU-only build, or no GPU) - it never silently degrades to CPU
    compute - and ``RuntimeError`` when the device has no room for a model
    stack, so a contended card is refused instead of starved.

    The device is checked once per process, before the first successful load,
    and the verdict is latched: a later call is exactly as cheap as it was
    before the check existed, and - the load-bearing half - the admitted
    workload's remaining components come up without re-interrogation. A release
    of resident models retires the latch; the fresh verdict a reload then takes
    credits whatever this process still holds, so its own residency is never
    read back as foreign pressure.
    """
    from ._gpu_admission import admit_gpu_load

    return admit_gpu_load(_import_torch_for_compute)


def _import_torch_for_compute() -> ModuleType:
    """Import torch, require a CUDA device, and apply the process allocator cap.

    The load itself, separated from the admission that precedes it so the two
    concerns stay legible: this function answers "can torch run compute here at
    all", and the admission gate answers "is there room for it right now".
    """
    try:
        import torch
    except ImportError as exc:
        raise ImportError(TORCH_MISSING_MESSAGE) from exc
    if not torch.cuda.is_available():
        raise RuntimeError(CUDA_REQUIRED_MESSAGE)
    from .config._settings import get_config

    torch.cuda.set_per_process_memory_fraction(  # pyright: ignore[reportUnknownMemberType] - torch stub gap
        get_config().index_cuda_allocator_fraction,
    )
    return torch
