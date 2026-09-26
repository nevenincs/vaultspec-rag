"""The one place a CUDA torch repair is spelled for an operator.

Every surface that refuses work because an environment's torch cannot use an
accelerator - the installer's tool repair, the post-install warning, the
service start pre-flight, the ephemeral-environment warnings and the doctor -
asks here for what to print. They differ in framing, never in the command, and
never in the precondition that has to hold before the command is safe.

Nothing here imports torch, so the service-control paths can use it.
"""

from __future__ import annotations

import importlib.metadata
import sys
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from packaging.requirements import Requirement
from packaging.tags import Tag, cpython_tags

from ..torch_config._index import CU130_INDEX_URL
from ._topology import TOOL_RECEIPT_NAME, RuntimeEnvKind, environment_root

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CudaRemediation",
    "CudaRepairKind",
    "ToolCudaInstallSpec",
    "cuda_remediation",
    "inplace_cuda_command",
    "published_wheel_platform_tag",
    "read_receipt",
    "tool_cuda_install_spec",
    "tool_package_requirement",
]

#: The tool request a CUDA repair falls back to when the receipt records none.
#: Only an inference host has torch to repair, so the request carries the
#: inference stack; the MCP adapter's own launch needs only the ``mcp`` extra.
_HOST_TOOL_REQUEST = "vaultspec-rag[gpu,mcp]"

#: The machine architectures PyTorch publishes accelerated Linux wheels for.
_CUDA_LINUX_MACHINES = frozenset({"x86_64", "aarch64"})

#: The machine architectures PyTorch publishes accelerated Windows wheels for.
_CUDA_WINDOWS_MACHINES = frozenset({"amd64", "x86_64"})

#: What has to be true before a forced reinstall can succeed, said once. uv
#: removes an environment's contents before writing the new ones, so a file it
#: cannot remove stops it half-way and leaves nothing runnable behind.
HOLDER_PRECONDITION = (
    "Run that command from a shell that holds nothing in this environment, "
    "with the service stopped and every editor or agent session running an "
    "MCP stdio transport closed. A held file stops the forced reinstall after "
    "it has removed the old packages, leaving the environment unrunnable."
)


class CudaRepairKind(StrEnum):
    """What kind of repair an environment and its platform allow."""

    TOOL_ENVIRONMENT = "tool_environment"
    EPHEMERAL_ENVIRONMENT = "ephemeral_environment"
    PROJECT_ENVIRONMENT = "project_environment"
    APPLE_METAL = "apple_metal"
    NO_PUBLISHED_WHEEL = "no_published_wheel"

    @property
    def repairable(self) -> bool:
        """Whether any command can make this environment run the GPU stack."""
        return self is not CudaRepairKind.NO_PUBLISHED_WHEEL


@dataclass(frozen=True, slots=True)
class ToolCudaInstallSpec:
    """The one receipt-carrying CUDA tool installation request."""

    args: tuple[str, ...]
    wheel_url: str

    @property
    def command(self) -> str:
        """Render the request for an operator without reparsing it later."""
        return " ".join(
            f'"{part}"' if " " in part or "[" in part else part for part in self.args
        )


@dataclass(frozen=True, slots=True)
class CudaRemediation:
    """What one environment needs, as the operator should read it.

    ``steps`` is the whole operator-facing remediation, in order, and is what
    every surface prints. The individual commands are carried beside it for
    the surfaces that also report them structurally; they are the same strings
    the steps already contain, never a second derivation.
    """

    kind: CudaRepairKind
    steps: tuple[str, ...]
    immediate_command: str = ""
    durable_command: str = ""
    spec: ToolCudaInstallSpec | None = None


def read_receipt(receipt: Path) -> dict[str, object] | None:
    """Parse a uv tool receipt, or return ``None`` when it cannot be read.

    An absent, unreadable or malformed receipt is an ordinary state - the
    environment may not be a tool environment at all - so every caller gets a
    value to branch on rather than an exception to remember.
    """
    try:
        return tomllib.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None


def _wheel_torch_version(installed: str | None) -> str:
    """Return the CUDA release matching an installed torch distribution."""
    from packaging.version import InvalidVersion, Version

    from ..torch_config._constants import TORCH_TOOL_PIN_VERSION

    if installed is None:
        return TORCH_TOOL_PIN_VERSION
    try:
        return Version(installed).base_version
    except InvalidVersion:
        return TORCH_TOOL_PIN_VERSION


def published_wheel_platform_tag(platform_name: str, machine: str) -> str | None:
    """The published PyTorch CUDA wheel platform segment, or ``None``.

    ``None`` means PyTorch publishes no accelerated wheel for this platform at
    all: macOS uses Metal instead, the CUDA index carries no ARM64 Windows
    wheel, and the accelerated Linux wheels exist for two architectures. A tag
    invented for any of those names a URL that cannot be fetched, which reads
    to an operator as a repair they failed to apply rather than one that does
    not exist.
    """
    normalised = machine.lower()
    if platform_name == "win32":
        return "win_amd64" if normalised in _CUDA_WINDOWS_MACHINES else None
    if platform_name == "linux":
        return (
            f"manylinux_2_28_{normalised}"
            if normalised in _CUDA_LINUX_MACHINES
            else None
        )
    return None


def _receipt_package_extras(receipt: Path, package: str) -> tuple[str, ...] | None:
    """Return the extras the receipt records for *package*, if it records any.

    The operator chose those extras. A repair that re-specifies the tool has
    no business widening them, so what is already recorded is what gets asked
    for again.
    """
    data = read_receipt(receipt)
    if data is None:
        return None
    tool = data.get("tool")
    requirements = (
        cast("dict[str, object]", tool).get("requirements")
        if isinstance(tool, dict)
        else None
    )
    if not isinstance(requirements, list):
        return None
    for entry in cast("list[object]", requirements):
        if not isinstance(entry, dict):
            continue
        record = cast("dict[str, object]", entry)
        name = record.get("name")
        if not isinstance(name, str) or name.lower() != package.lower():
            continue
        extras = record.get("extras")
        if isinstance(extras, list):
            return tuple(str(extra) for extra in cast("list[object]", extras))
        return ()
    return None


def tool_package_requirement(interpreter: str) -> str:
    """Render the package request a repair may ask for, and no more.

    A bare name resolves to whatever is newest, so the command that repairs a
    torch wheel would also upgrade the tool and impose this build's extras on
    an operator who chose otherwise. The installed version is pinned and the
    receipt's own extras are reused; the host request is the fallback for an
    environment that records neither.
    """
    fallback = _HOST_TOOL_REQUEST
    package = Requirement(fallback).name
    extras = _receipt_package_extras(
        environment_root(interpreter) / TOOL_RECEIPT_NAME, package
    )
    if extras is None:
        return fallback
    try:
        version = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return fallback
    rendered = f"{package}[{','.join(sorted(extras))}]" if extras else package
    return f"{rendered}=={version}"


def tool_cuda_install_spec(
    *,
    torch_version: str | None = None,
    tag: Tag | None = None,
    platform_tag: str | None = None,
    package_spec: str | None = None,
) -> ToolCudaInstallSpec | None:
    """Build the durable CUDA request from the running interpreter's tags.

    Returns ``None`` when the host has no published CUDA wheel, so a caller
    cannot hand an operator a URL the index will refuse.

    The wheel URL names one interpreter and one ABI, so both tags are read off
    the running interpreter rather than written down: hardcoding them hands a
    3.13 wheel to whoever runs 3.14, and uv rejects the mismatch with a tag
    error that says nothing about why the command was wrong. The two tags are
    NOT interchangeable - a free-threaded build is ``cp314-cp314t`` while
    ``sys.version_info`` is ``(3, 14)`` for both builds - so ``packaging``
    resolves them from ``Py_GIL_DISABLED`` instead of a rule re-derived here.

    The manylinux level stays hand-picked, because it must match what PyTorch
    actually publishes rather than the first tag the host offers, while the
    machine architecture is read from the host.

    The torch version tracks the distribution already installed (the CPU wheel
    being replaced), with the local suffix stripped: the same release is
    guaranteed to exist in the CUDA flavour for an interpreter that resolved
    it, where a baked constant goes stale against an environment that has not
    caught up with the workspace pin.

    The command carries ``--python`` because ``uv tool install --force``
    rebuilds the environment with uv's default python request, not the
    interpreter that printed the command. The request is parsed out of the
    same tag as the wheel filename so the two cannot diverge, and uv records
    it in the receipt, so upgrades keep resolving on the matching interpreter.
    """
    import platform

    if torch_version is None:
        try:
            installed = importlib.metadata.version("torch")
        except importlib.metadata.PackageNotFoundError:
            installed = None
        torch_version = _wheel_torch_version(installed)
    tag = tag or next(iter(cpython_tags()))
    platform_tag = platform_tag or published_wheel_platform_tag(
        sys.platform, platform.machine()
    )
    if platform_tag is None:
        return None
    python_request = f"{tag.interpreter[2]}.{tag.interpreter[3:]}"
    if tag.abi.endswith("t"):
        python_request += "t"
    wheel_url = (
        f"{CU130_INDEX_URL}/torch-{torch_version}%2Bcu130"
        f"-{tag.interpreter}-{tag.abi}-{platform_tag}.whl"
    )
    return ToolCudaInstallSpec(
        args=(
            "uv",
            "tool",
            "install",
            "--force",
            "--python",
            python_request,
            package_spec or _HOST_TOOL_REQUEST,
            "--with",
            f"torch @ {wheel_url}",
        ),
        wheel_url=wheel_url,
    )


def inplace_cuda_command(interpreter: str) -> str:
    """The in-place CUDA wheel repair for *interpreter*.

    Works in any environment and is undone by the next tool re-resolution
    (``--torch-backend`` is a ``uv pip`` option and is not recorded in a tool
    receipt), so a tool environment is offered the durable request as well.
    """
    backend = CU130_INDEX_URL.rsplit("/", 1)[-1]
    return (
        f'uv pip install --python "{interpreter}" '
        f"--reinstall --torch-backend={backend} torch"
    )


def _metal_remediation(interpreter: str) -> CudaRemediation:
    """macOS has no CUDA build; say so and name the wheel that does work."""
    command = f'uv pip install --python "{interpreter}" --reinstall torch'
    return CudaRemediation(
        kind=CudaRepairKind.APPLE_METAL,
        steps=(
            "There is no CUDA build for macOS; vaultspec-rag runs on Apple "
            "Metal (MPS) there.",
            f"Install the macOS torch build in this environment: {command}",
            'Confirm Metal is usable: python -c "import torch; '
            'print(torch.backends.mps.is_available())"',
        ),
        immediate_command=command,
    )


def _project_remediation(interpreter: str, *, project: bool) -> CudaRemediation:
    """Repair an environment no tool receipt governs.

    A project environment is served by the project surfaces, which write the
    CUDA index into the project and keep it across syncs. Anything else has no
    durable surface to write to, so it is offered the in-place repair that
    works in any environment, and told where the durable one lives.
    """
    if project:
        return CudaRemediation(
            kind=CudaRepairKind.PROJECT_ENVIRONMENT,
            steps=(
                "Provision the GPU torch build in this project: "
                "vaultspec-rag install, then uv sync --reinstall-package torch.",
            ),
        )
    command = inplace_cuda_command(interpreter)
    return CudaRemediation(
        kind=CudaRepairKind.PROJECT_ENVIRONMENT,
        steps=(
            f"Provision the GPU torch build in this environment: {command}",
            "In a project, vaultspec-rag install writes the CUDA index into "
            "pyproject.toml and uv sync --reinstall-package torch applies it, "
            "so the build survives a resolve.",
        ),
        immediate_command=command,
    )


def cuda_remediation(
    interpreter: str,
    *,
    env_kind: RuntimeEnvKind | None = None,
    platform_name: str | None = None,
    machine: str | None = None,
) -> CudaRemediation:
    """What *interpreter*'s environment needs to run the GPU-only stack.

    The platform is asked before the environment, because a host PyTorch
    publishes no accelerated wheel for cannot be repaired by any command and
    must be told so plainly instead of being handed a URL that returns an
    error from the index.
    """
    import platform as platform_module

    from ._topology import classify_environment

    platform_name = sys.platform if platform_name is None else platform_name
    machine = platform_module.machine() if machine is None else machine
    if platform_name == "darwin":
        return _metal_remediation(interpreter)
    platform_tag = published_wheel_platform_tag(platform_name, machine)
    if platform_tag is None:
        return CudaRemediation(
            kind=CudaRepairKind.NO_PUBLISHED_WHEEL,
            steps=(
                f"PyTorch publishes no CUDA build for {platform_name} "
                f"{machine}, so no reinstall can make this environment run "
                "the GPU-only stack. Run the service on a host with a "
                "supported GPU and use this installation as a client.",
            ),
        )
    kind = (
        classify_environment(environment_root(interpreter))
        if env_kind is None
        else env_kind
    )
    if kind is RuntimeEnvKind.PROJECT_VENV or kind is RuntimeEnvKind.OTHER:
        return _project_remediation(
            interpreter, project=kind is RuntimeEnvKind.PROJECT_VENV
        )
    spec = tool_cuda_install_spec(
        platform_tag=platform_tag, package_spec=tool_package_requirement(interpreter)
    )
    if spec is None:  # pragma: no cover - the platform was checked above
        raise AssertionError("a supported platform yielded no CUDA install spec")
    durable = spec.command
    if kind is RuntimeEnvKind.UVX_EPHEMERAL:
        return CudaRemediation(
            kind=CudaRepairKind.EPHEMERAL_ENVIRONMENT,
            steps=(
                f"Reinstall the tool so its own environment carries the GPU "
                f"wheel: {durable}",
                HOLDER_PRECONDITION,
            ),
            durable_command=durable,
            spec=spec,
        )
    immediate = inplace_cuda_command(interpreter)
    return CudaRemediation(
        kind=CudaRepairKind.TOOL_ENVIRONMENT,
        steps=(
            f"Repair this environment now, until the next tool upgrade "
            f"re-resolves torch: {immediate}",
            f"Make upgrades keep the GPU wheel: {durable}",
            HOLDER_PRECONDITION,
        ),
        immediate_command=immediate,
        durable_command=durable,
        spec=spec,
    )
