"""Actionable GPU / torch remediation messages and the error handler."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from ..operator_state._installation import ComputeCapability
from ._render import _emit_json_error_and_exit, _plain

if TYPE_CHECKING:
    from typing import NoReturn

    from .._gpu_owner import GpuOwnership

__all__ = [
    "_handle_gpu_error",
    "_no_gpu_message",
    "_no_torch_message",
    "refuse_gpu_owned",
    "warn_if_active_torch_not_accelerator",
]


def refuse_gpu_owned(
    ownership: GpuOwnership, *, command: str, json_mode: bool
) -> NoReturn:
    """Refuse local compute because this process does not own the GPU.

    One refusal for every local compute surface - the search pre-check and a
    load refused deep inside a command alike - so an operator meets one message
    and one list of next actions, and a JSON caller one ``gpu_owned`` envelope.
    """
    from .._gpu_owner import (
        gpu_owned_message,
        gpu_owned_remediation,
        gpu_owner_wire,
    )

    message = gpu_owned_message(ownership)
    remediation = list(gpu_owned_remediation(ownership))
    if json_mode:
        _emit_json_error_and_exit(
            command,
            "gpu_owned",
            message,
            1,
            gpu_owner=gpu_owner_wire(ownership),
            remediation=remediation,
        )
    steps = "\n".join(
        f"  {number}. {step}" for number, step in enumerate(remediation, start=1)
    )
    _plain(f"Error: {message}\nNext actions:\n{steps}")
    raise typer.Exit(code=1)


def _no_torch_message() -> str:
    """Return the NO_TORCH remediation copy as plain text."""
    import sys

    if sys.platform == "darwin":
        return (
            f"Error: {ComputeCapability.TORCH_MISSING.label}.\n\n"
            "  Install vaultspec-rag in this interpreter to provision the "
            "macOS torch build with Apple MPS support."
        )
    return (
        f"Error: {ComputeCapability.TORCH_MISSING.label}.\n\n"
        '  uv add "vaultspec-rag[gpu]" && uv run vaultspec-rag install '
        "configures the cu130 torch index and installs the GPU build."
    )


def _no_gpu_message() -> str:
    """Return the NO_GPU remediation copy as plain text."""
    return (
        f"Error: {ComputeCapability.NO_DEVICE.label}.\n"
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


def _no_mps_message() -> str:
    """Return MPS remediation copy for a macOS host."""
    return (
        "Error: No Apple Metal accelerator detected.\n"
        "  PyTorch is installed, but MPS is unavailable. vaultspec-rag never "
        "runs inference on CPU.\n\n"
        "  Quick checks:\n"
        "    1. Confirm this is an Apple silicon Mac running macOS 12.3 or later.\n"
        '    2. python -c "import torch; print(torch.backends.mps.is_built(), '
        'torch.backends.mps.is_available())"\n'
        "    3. Reinstall the supported macOS torch wheel if MPS is not built in."
    )


def warn_if_active_torch_not_accelerator(
    *, capability: ComputeCapability | None = None
) -> None:
    """Warn when the running interpreter cannot use a supported accelerator.

    vaultspec-rag is GPU-only. A configured ``pyproject.toml`` does not
    guarantee a usable accelerator in the active interpreter - a ``uv tool`` / ``pip``
    install resolves torch from PyPI (CPU), since the cu130 source pin is
    project-scoped and is not part of the published wheel metadata. This probes
    the actual wheel in a child interpreter, so the CLI never imports torch,
    and when it is CPU-only, absent, or GPU-less, prints a prominent
    topology-aware warning so a configured-but-CPU install never passes
    silently. A client installation never asked for torch and is not warned.

    ``capability`` is a verdict about this same interpreter that the caller
    already obtained. The probe starts a child interpreter and imports torch
    in it, so asking twice in one command doubles the wait and can answer
    differently; a caller holding the answer passes it instead.
    """
    import sys

    from ..operator_state._compute import ProbeDepth
    from ..operator_state._environment_probe import probe_interpreter

    if capability is None:
        capability = probe_interpreter(
            sys.executable, ProbeDepth.VERIFY
        ).compute.capability
    if not capability.is_defect:
        return
    if capability is ComputeCapability.MPS_POLICY_REFUSED:
        from .._gpu import MPS_FALLBACK_MESSAGE

        _plain(f"\nWARNING: {MPS_FALLBACK_MESSAGE}")
        return

    from ..operator_state._provisioning import cuda_remediation
    from ..operator_state._topology import (
        RuntimeEnvKind,
        classify_environment,
        environment_root,
    )

    lines = [
        "",
        "WARNING: the active interpreter's torch has no supported accelerator.",
    ]
    if capability is ComputeCapability.CPU_ONLY_BUILD:
        lines.append(
            "  The installed torch is a CPU-only wheel - vaultspec-rag is "
            "GPU-only and the service will not start."
        )
    elif capability.fixed_by_torch_reinstall:
        lines.append(f"  In the active interpreter, {capability.label}.")
    else:
        lines.append(f"  In the active interpreter, {capability.label}.")
        lines.append(
            "  Confirm the accelerator is visible: python -c "
            '"import torch; print(torch.backends.mps.is_available())"'
            if sys.platform == "darwin"
            else "  Confirm the driver sees the GPU: nvidia-smi"
        )
        _plain("\n".join(lines))
        return

    kind = classify_environment(environment_root(sys.executable))
    if kind is RuntimeEnvKind.UVX_EPHEMERAL:
        lines.append(
            f"  This interpreter is a uvx EPHEMERAL cache environment "
            f"({sys.prefix}) - not the installed tool. uvx silently falls "
            "back to it when the installed tool environment is broken or the "
            "request does not match it."
        )
    lines.append("")
    lines.extend(
        f"  {step}" for step in cuda_remediation(sys.executable, env_kind=kind).steps
    )
    _plain("\n".join(lines))


def _handle_gpu_error(
    exc: Exception, *, command: str = "", json_mode: bool = False
) -> NoReturn:
    """Print an actionable message for torch / CUDA failures and exit.

    A load refused because another process owns the GPU is answered first and
    as itself: nothing about this environment's torch is wrong, and
    classifying it would import torch to report a working build. That refusal
    is emitted as *command*'s one JSON envelope when *json_mode* is set, since
    the command that reached a model load may have been asked for JSON.

    Otherwise classifies this process's environment so the remediation hint
    matches the actual problem: torch absent or unloadable, a CPU-only wheel, a
    CUDA build with no visible device, or a refused MPS fallback policy. Unlike
    the post-install warning, which asks a child interpreter, this runs after a
    compute path in this very process failed, so it classifies the torch that
    failed here rather than starting another interpreter to ask.

    Args:
        exc: The caught exception (``ImportError`` or ``RuntimeError``).

    Raises:
        typer.Exit: Always exits with code 1.
    """
    import sys

    from .._gpu_owner import GpuOwnedError

    if isinstance(exc, GpuOwnedError):
        refuse_gpu_owned(exc.ownership, command=command, json_mode=json_mode)

    from .._gpu import MPS_FALLBACK_MESSAGE
    from ..operator_state._compute import classify_torch, local_compute
    from ..operator_state._installation import ComputeCapability
    from ..operator_state._provisioning import cuda_remediation

    loaded = sys.modules.get("torch")
    capability = (
        classify_torch(loaded).capability
        if loaded is not None
        else local_compute().capability
    )
    if capability is ComputeCapability.MPS_POLICY_REFUSED:
        _plain(f"Error: {MPS_FALLBACK_MESSAGE}")
    elif capability in {
        ComputeCapability.NOT_APPLICABLE,
        ComputeCapability.TORCH_MISSING,
        ComputeCapability.TORCH_IMPORT_FAILED,
    }:
        _plain(_no_torch_message())
    elif sys.platform == "darwin":
        _plain(_no_mps_message())
    elif capability is ComputeCapability.CPU_ONLY_BUILD:
        # The repair depends on what kind of environment this is, and the
        # project advice printed here was wrong for every tool installation
        # that met it: patching a pyproject.toml changes nothing about an
        # environment uv resolved from a receipt.
        _plain(f"Error: {capability.label}. Your GPU is fine.")
        for step in cuda_remediation(sys.executable).steps:
            _plain(f"  {step}", soft_wrap=True)
    elif capability is ComputeCapability.NO_DEVICE:
        _plain(_no_gpu_message())
    else:
        _plain(f"Error: {exc}")
    raise typer.Exit(code=1)
