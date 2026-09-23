"""Decide what the current interpreter is and whether it can run inference.

This is the one place the role and the compute capability of an environment
are classified. It runs in whichever process asks: the service reads its own
environment directly, and a torch-free client asks the daemon interpreter by
running :func:`environment_report` in a child process.

torch is only ever imported inside :func:`local_compute` at the verify depth,
behind a guard, because this is a read-only probe that must answer on a host
without torch rather than raise.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from importlib import metadata
from typing import TYPE_CHECKING, cast

from ._installation import ComputeCapability, InstallRole
from ._models import ComputeReport

if TYPE_CHECKING:
    from types import ModuleType

__all__ = [
    "ProbeDepth",
    "classify_torch",
    "environment_report",
    "installed_role",
    "local_compute",
    "metadata_verdict",
    "role_for",
]

_MIB = 1024 * 1024


class ProbeDepth(StrEnum):
    """How far a compute check goes before it answers."""

    METADATA = "metadata"
    VERIFY = "verify"


def _installed_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def installed_role() -> tuple[InstallRole, bool]:
    """Return this environment's role and whether it carries the MCP adapter."""
    return (
        role_for(_installed_version("sentence-transformers")),
        _installed_version("mcp") is not None,
    )


def role_for(inference_stack_version: str | None) -> InstallRole:
    """A host carries the inference stack the ``gpu`` extra installs."""
    return InstallRole.CLIENT if inference_stack_version is None else InstallRole.HOST


def metadata_verdict(
    inference_stack_version: str | None,
    torch_version: str | None,
    platform: str,
) -> ComputeCapability:
    """Classify an environment from what is installed, without importing torch.

    A client never needs torch, so it is ``NOT_APPLICABLE`` whatever else is
    installed; a host without torch has lost it.
    """
    if role_for(inference_stack_version) is InstallRole.CLIENT:
        return ComputeCapability.NOT_APPLICABLE
    if torch_version is None:
        return ComputeCapability.TORCH_MISSING
    return _metadata_capability(torch_version, platform)


def _metadata_capability(torch_version: str, platform: str) -> ComputeCapability:
    """Read the torch build from its version, never claiming a working device.

    Without a local version tag, PyPI ships CPU-only torch for Windows and CUDA
    torch for Linux; macOS builds carry MPS.
    """
    local = torch_version.partition("+")[2].lower()
    if local.startswith("cpu"):
        return ComputeCapability.CPU_ONLY_BUILD
    if local.startswith("cu"):
        return ComputeCapability.BUILD_PRESENT
    if local:
        return ComputeCapability.UNKNOWN
    if platform == "win32":
        return ComputeCapability.CPU_ONLY_BUILD
    return ComputeCapability.BUILD_PRESENT


def classify_torch(torch_module: ModuleType) -> ComputeReport:
    """Classify an already-imported torch against the accelerator contract."""
    from .._gpu import resolve_accelerator

    version = str(getattr(torch_module, "__version__", "")) or None
    cuda_build = getattr(torch_module.version, "cuda", None)
    mps_visible = False
    try:
        mps_visible = bool(torch_module.backends.mps.is_available())
        context = resolve_accelerator(torch_module)
    except Exception as exc:
        if mps_visible:
            capability = ComputeCapability.MPS_POLICY_REFUSED
        elif cuda_build:
            capability = ComputeCapability.NO_DEVICE
        else:
            capability = ComputeCapability.CPU_ONLY_BUILD
        return ComputeReport(
            capability=capability, torch_version=version, detail=str(exc)
        )
    memory_mib = None
    if context.backend == "cuda":
        total = torch_module.cuda.get_device_properties(0).total_memory
        memory_mib = int(total // _MIB)
    else:
        # Unified memory has no VRAM total; the recommended working set is the
        # figure that bounds what inference may use.
        recommended = getattr(
            getattr(torch_module, "mps", None), "recommended_max_memory", None
        )
        if callable(recommended):
            memory_mib = int(cast("int", recommended()) // _MIB)
    return ComputeReport(
        capability=ComputeCapability.READY,
        torch_version=version,
        backend=context.backend,
        device_name=context.name,
        memory_mib=memory_mib,
    )


def local_compute(depth: ProbeDepth = ProbeDepth.VERIFY) -> ComputeReport:
    """Classify this process's own environment.

    The metadata depth reads installed versions only. The verify depth goes on
    to import torch only when the metadata leaves a device to check.
    """
    torch_version = _installed_version("torch")
    capability = metadata_verdict(
        _installed_version("sentence-transformers"), torch_version, sys.platform
    )
    if depth is ProbeDepth.METADATA or capability in {
        ComputeCapability.NOT_APPLICABLE,
        ComputeCapability.TORCH_MISSING,
    }:
        return ComputeReport(capability=capability, torch_version=torch_version)
    try:
        import torch
    except Exception as exc:
        return ComputeReport(
            capability=ComputeCapability.TORCH_IMPORT_FAILED,
            torch_version=torch_version,
            detail=f"{type(exc).__name__}: {exc}",
        )
    return classify_torch(torch)


def environment_report(depth: ProbeDepth) -> dict[str, object]:
    """Describe this interpreter as the JSON a probing client parses."""
    role, mcp_adapter = installed_role()
    return {
        "role": role.value,
        "mcp_adapter": mcp_adapter,
        "executable": sys.executable,
        "prefix": sys.prefix,
        "compute": local_compute(depth).model_dump(mode="json"),
    }
