"""Actionable GPU / torch remediation messages and the error handler.

The three ``_*_message`` helpers return Rich-markup strings so the
rendered output is testable without monkey-patching
:func:`_handle_gpu_error`; :func:`_handle_gpu_error` classifies a
torch/CUDA failure and prints the matching message before exiting.
"""

from __future__ import annotations

import typer

import vaultspec_rag.cli as _cli

from ._core import logger


def _cpu_only_message() -> str:
    """Return the CPU_ONLY remediation copy as a Rich-markup string.

    Extracted so the rendered output is testable without monkey-patching
    :func:`_handle_gpu_error`. ``markup=True`` makes Rich parse
    ``[name]...[/name]`` as markup, so every literal ``[`` in TOML keys
    must be backslash-escaped (``\\[``). Closing ``]`` outside a tag
    context is already literal and must NOT be escaped - Rich passes
    ``\\]`` through verbatim and leaves a stray backslash in the
    rendered output.
    """
    return (
        "[bold red]Error:[/] PyTorch was installed without CUDA support "
        "(CPU-only wheel). Your GPU is fine.\n\n"
        "  [cyan]uv run vaultspec-rag install[/] patches your "
        "pyproject.toml with the cu130 torch index and adds "
        "[cyan]torch>=2.4[/] as a direct dependency when needed. After "
        "patching, "
        "rerun [cyan]uv sync --reinstall-package torch[/].\n\n"
        "  If install has already run and you are still here, verify:\n"
        "    1. [cyan]pyproject.toml[/] has \\[\\[tool.uv.index]] "
        '[cyan]name = "pytorch-cu130"[/] and '
        "[cyan]\\[tool.uv.sources][/] torch = ...\n"
        "    2. [cyan]pyproject.toml[/] has [cyan]torch>=2.4[/] as "
        "a direct dependency in [cyan]\\[project].dependencies[/] "
        "or [cyan]\\[dependency-groups].dev[/]\n"
        "    3. [cyan]uv.lock[/] has a torch entry with "
        "[cyan]source = "
        '{ registry = "https://download.pytorch.org/whl/cu130" }[/] '
        "(not pypi.org/simple)\n"
        "    4. If the lockfile still points at PyPI, rerun "
        "[cyan]uv lock --refresh-package torch && uv sync[/].\n\n"
        "  Or configure manually by adding this to your pyproject.toml:"
    )


def _no_torch_message() -> str:
    """Return the NO_TORCH remediation copy as a Rich-markup string.

    Extracted so the rendered output is testable without monkey-
    patching ``_handle_gpu_error``. TEST-11.
    """
    return (
        "[bold red]Error:[/] PyTorch is not installed.\n\n"
        "  [cyan]uv add vaultspec-rag && uv run vaultspec-rag install[/] "
        "configures the cu130 torch index and installs the GPU build."
    )


def _no_gpu_message() -> str:
    """Return the NO_GPU remediation copy as a Rich-markup string.

    Extracted so the rendered output is testable without monkey-
    patching ``_handle_gpu_error``. TEST-04.
    """
    return (
        "[bold red]Error:[/] No CUDA GPU detected.\n"
        "  PyTorch is built with CUDA support, but no CUDA device "
        "is available.\n\n"
        "  Quick checks:\n"
        "    1. [cyan]nvidia-smi[/] - confirms the driver sees the GPU. "
        "If this fails, install/repair the NVIDIA driver.\n"
        '    2. [cyan]python -c "import torch; print(torch.version.cuda)"[/] '
        "- prints the CUDA version torch was built against. Your "
        "driver must support at least this CUDA major.\n"
        "    3. WSL/Docker users: confirm GPU passthrough is enabled "
        "([cyan]--gpus all[/] for docker, GPU support enabled in WSL2). "
        "A GPU visible to the host is not automatically visible inside "
        "the container/VM."
    )


def _handle_gpu_error(exc: Exception) -> None:
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
    from ..torch_config import TorchDiagnosis, diagnose_torch, manual_snippet

    diagnosis: TorchDiagnosis
    if isinstance(exc, ImportError):
        diagnosis = TorchDiagnosis.NO_TORCH
    else:
        try:
            import torch

            diagnosis = diagnose_torch(torch.version.cuda, torch.cuda.is_available())
        except Exception as exc:
            # Broad except: torch import succeeded but probing the
            # CUDA state failed in an unexpected way (driver
            # mismatch, opaque ABI error). Treat as "no torch" for
            # diagnosis purposes; debug-log so the swallow stays
            # observable per the no-swallow rule.
            logger.debug("torch CUDA diagnosis failed: %s", exc, exc_info=True)
            diagnosis = TorchDiagnosis.NO_TORCH

    if diagnosis == TorchDiagnosis.NO_TORCH:
        _cli.console.print(_no_torch_message())
    elif diagnosis == TorchDiagnosis.CPU_ONLY:
        _cli.console.print(_cpu_only_message(), markup=True)
        # Rich interprets ``[[tool.uv.index]]`` as markup; emit the
        # snippet with markup disabled so brackets render verbatim.
        _cli.console.print(manual_snippet(), markup=False, highlight=False)
    elif diagnosis == TorchDiagnosis.NO_GPU:
        _cli.console.print(_no_gpu_message())
    else:
        _cli.console.print(f"[bold red]Error:[/] {exc}")
    raise typer.Exit(code=1)
