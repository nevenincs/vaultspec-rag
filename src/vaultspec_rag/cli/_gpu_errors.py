"""Actionable GPU / torch remediation messages and the error handler."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

import vaultspec_rag.cli as _cli

from ._core import logger

if TYPE_CHECKING:
    from typing import NoReturn

__all__ = [
    "_cpu_only_message",
    "_handle_gpu_error",
    "_no_gpu_message",
    "_no_torch_message",
]


def _cpu_only_message() -> str:
    """Return the CPU_ONLY remediation copy as plain text."""
    return (
        "Error: PyTorch was installed without CUDA support "
        "(CPU-only wheel). Your GPU is fine.\n\n"
        "  uv run vaultspec-rag install patches your pyproject.toml "
        "with the cu130 torch index and adds torch>=2.4 as a direct "
        "dependency when needed. After patching, rerun "
        "uv sync --reinstall-package torch.\n\n"
        "  If install has already run and you are still here, verify:\n"
        "    1. pyproject.toml has [[tool.uv.index]] "
        'name = "pytorch-cu130" and [tool.uv.sources] torch = ...\n'
        "    2. pyproject.toml has torch>=2.4 as a direct dependency "
        "in [project].dependencies or [dependency-groups].dev\n"
        "    3. uv.lock has a torch entry with source = "
        '{ registry = "https://download.pytorch.org/whl/cu130" } '
        "(not pypi.org/simple)\n"
        "    4. If the lockfile still points at PyPI, rerun "
        "uv lock --refresh-package torch && uv sync.\n\n"
        "  Or configure manually by adding this to your pyproject.toml:"
    )


def _no_torch_message() -> str:
    """Return the NO_TORCH remediation copy as plain text."""
    return (
        "Error: PyTorch is not installed.\n\n"
        "  uv add vaultspec-rag && uv run vaultspec-rag install "
        "configures the cu130 torch index and installs the GPU build."
    )


def _no_gpu_message() -> str:
    """Return the NO_GPU remediation copy as plain text."""
    return (
        "Error: No CUDA GPU detected.\n"
        "  PyTorch is built with CUDA support, but no CUDA device "
        "is available.\n\n"
        "  Quick checks:\n"
        "    1. nvidia-smi - confirms the driver sees the GPU. "
        "If this fails, install/repair the NVIDIA driver.\n"
        '    2. python -c "import torch; print(torch.version.cuda)" '
        "- prints the CUDA version torch was built against. Your "
        "driver must support at least this CUDA major.\n"
        "    3. WSL/Docker users: confirm GPU passthrough is enabled "
        "(--gpus all for docker, GPU support enabled in WSL2). "
        "A GPU visible to the host is not automatically visible inside "
        "the container/VM."
    )


def _handle_gpu_error(exc: Exception) -> NoReturn:
    """Print an actionable message for torch / CUDA failures and exit.

    Distinguishes three failure states so the remediation hint matches
    the actual problem:

    - torch not installed at all (``ImportError``)
    - torch installed without CUDA support - the CPU-only PyPI wheel
      (``torch.version.cuda is None``)
    - torch built with CUDA but no GPU visible - driver or hardware
      issue (``torch.version.cuda`` set, ``is_available()`` False)

    Args:
        exc: The caught exception (``ImportError`` or ``RuntimeError``).

    Raises:
        typer.Exit: Always exits with code 1.
    """
    from ..torch_config import (
        TorchDiagnosis,
        diagnose_torch,
        manual_snippet,
    )

    diagnosis: TorchDiagnosis
    if isinstance(exc, ImportError):
        diagnosis = TorchDiagnosis.NO_TORCH
    else:
        try:
            import torch

            diagnosis = diagnose_torch(torch.version.cuda, torch.cuda.is_available())
        except Exception as _diag_exc:
            # Broad except: torch import succeeded but probing the
            # CUDA state failed in an unexpected way (driver
            # mismatch, opaque ABI error). Treat as "no torch" for
            # diagnosis purposes; debug-log so the swallow stays
            # observable per the no-swallow rule.
            logger.debug("torch CUDA diagnosis failed: %s", _diag_exc, exc_info=True)
            diagnosis = TorchDiagnosis.NO_TORCH

    if diagnosis == TorchDiagnosis.NO_TORCH:
        _cli.console.print(_no_torch_message(), markup=False, highlight=False)
    elif diagnosis == TorchDiagnosis.CPU_ONLY:
        _cli.console.print(_cpu_only_message(), markup=False, highlight=False)
        _cli.console.print(manual_snippet(), markup=False, highlight=False)
    elif diagnosis == TorchDiagnosis.NO_GPU:
        _cli.console.print(_no_gpu_message(), markup=False, highlight=False)
    else:
        _cli.console.print(f"Error: {exc}", markup=False, highlight=False)
    raise typer.Exit(code=1)
