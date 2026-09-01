"""Centralized accelerator-gated torch loader for local compute paths.

Service-mode clients never load torch. Every in-process compute site resolves
its accelerator here, where CUDA wins over MPS and CPU is never a candidate.
The import remains function-local so importing this module is torch-free.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from types import ModuleType

AcceleratorBackend = Literal["cuda", "mps"]
MemoryKind = Literal["vram", "unified"]

__all__ = [
    "ACCELERATOR_REQUIRED_MESSAGE",
    "MPS_FALLBACK_MESSAGE",
    "TORCH_MISSING_MESSAGE",
    "AcceleratorBackend",
    "AcceleratorContext",
    "MemoryKind",
    "detect_accelerator_backend",
    "load_accelerator",
    "resolve_accelerator",
]

TORCH_MISSING_MESSAGE = (
    "GPU RAG dependencies not installed: torch is missing. Install "
    "`vaultspec-rag[gpu]`, then run `vaultspec-rag install --sync` to "
    "provision torch for this platform."
)

ACCELERATOR_REQUIRED_MESSAGE = (
    "Supported accelerator required: neither CUDA nor Apple MPS is available. "
    "vaultspec-rag never runs inference on CPU. Install the supported torch "
    "build on a CUDA-capable or Apple silicon machine."
)

MPS_FALLBACK_MESSAGE = (
    "Apple MPS CPU fallback must be disabled: "
    "PYTORCH_ENABLE_MPS_FALLBACK=1 can move unsupported operators to CPU, but "
    "vaultspec-rag never runs inference on CPU. Unset it or set it to 0."
)


@dataclass(frozen=True, slots=True)
class AcceleratorContext:
    """The selected accelerator and the backend operations callers need."""

    torch: ModuleType
    backend: AcceleratorBackend
    device: str
    name: str
    memory_kind: MemoryKind

    def is_out_of_memory(self, exc: BaseException) -> bool:
        """Return whether *exc* is this backend's allocator exhaustion."""
        error_type = (
            getattr(self.torch.cuda, "OutOfMemoryError", None)
            if self.backend == "cuda"
            else getattr(self.torch, "OutOfMemoryError", None)
        )
        return isinstance(error_type, type) and isinstance(exc, error_type)

    def release_cache(self) -> None:
        """Return unused allocator blocks to the selected backend."""
        getattr(self.torch, self.backend).empty_cache()


def _mps_fallback_enabled() -> bool:
    """Whether PyTorch's documented MPS-to-CPU fallback switch is enabled."""
    return os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK", "").strip() == "1"


def detect_accelerator_backend(
    torch_module: ModuleType,
) -> AcceleratorBackend | None:
    """Return the first available supported backend without changing state."""
    if torch_module.cuda.is_available():
        return "cuda"
    mps = getattr(getattr(torch_module, "backends", None), "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return None


def resolve_accelerator(torch_module: ModuleType) -> AcceleratorContext:
    """Resolve CUDA first, then MPS, and refuse an accelerator-less host."""
    backend = detect_accelerator_backend(torch_module)
    if backend == "cuda":
        return AcceleratorContext(
            torch=torch_module,
            backend="cuda",
            device="cuda",
            name=str(torch_module.cuda.get_device_name(0)),
            memory_kind="vram",
        )

    if backend == "mps":
        if _mps_fallback_enabled():
            raise RuntimeError(MPS_FALLBACK_MESSAGE)
        return AcceleratorContext(
            torch=torch_module,
            backend="mps",
            device="mps",
            name="Apple MPS",
            memory_kind="unified",
        )

    raise RuntimeError(ACCELERATOR_REQUIRED_MESSAGE)


def _import_accelerator_for_compute() -> AcceleratorContext:
    """Import torch and resolve the supported accelerator for compute."""
    try:
        import torch
    except ImportError as exc:
        raise ImportError(TORCH_MISSING_MESSAGE) from exc
    return resolve_accelerator(torch)


def load_accelerator() -> AcceleratorContext:
    """Resolve and admit the accelerator for a local compute path."""
    from ._gpu_admission import admit_accelerator_load

    accelerator = _import_accelerator_for_compute()

    def configure() -> AcceleratorContext:
        if accelerator.backend == "cuda":
            from .config._settings import get_config

            accelerator.torch.cuda.set_per_process_memory_fraction(  # pyright: ignore[reportUnknownMemberType] - torch stub gap
                get_config().index_cuda_allocator_fraction,
            )
        return accelerator

    return admit_accelerator_load(
        configure,
        backend=accelerator.backend,
    )
