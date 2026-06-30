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

from typing import Any

__all__ = ["CUDA_REQUIRED_MESSAGE", "TORCH_MISSING_MESSAGE", "load_torch"]

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


def load_torch() -> Any:
    """Import torch for a local-mode compute path, asserting CUDA, or fail hard.

    The single gate every local-mode torch *compute* load must pass through.
    Returns the imported ``torch`` module. Raises ``ImportError`` when torch is
    not installed, or ``RuntimeError`` when torch is installed but exposes no
    CUDA device (a CPU-only build, or no GPU) - it never silently degrades to
    CPU compute.
    """
    try:
        import torch
    except ImportError as exc:
        raise ImportError(TORCH_MISSING_MESSAGE) from exc
    if not torch.cuda.is_available():
        raise RuntimeError(CUDA_REQUIRED_MESSAGE)
    return torch
