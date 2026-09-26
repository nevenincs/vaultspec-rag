"""The one place a CUDA torch repair is spelled for an operator.

Every surface that refuses work because an environment's torch cannot use an
accelerator - the installer's tool repair, the post-install warning, the
service start pre-flight, the ephemeral-environment warnings and the doctor -
asks here for what to print. They differ in framing, never in the command, and
never in the precondition that has to hold before the command is safe.

A ``uv tool`` installation keeps its GPU build across upgrades only through
its receipt, which is the one state uv consults on every upgrade. Recording a
CUDA index and the strategy that reaches it makes torch resolve accelerated
each time, while recording a wheel URL or an exact version makes the same
installation resolve nothing new ever again. So the receipt is a verdict in
its own right: an environment whose torch works today but whose receipt
carries no CUDA source is one upgrade away from a CPU build.

Nothing here imports torch, so the service-control paths can use it.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from packaging.requirements import Requirement

from .._operator_commands import server_start_command, server_stop_command
from ..torch_config._index import CU130_INDEX_URL
from ._topology import TOOL_RECEIPT_NAME, RuntimeEnvKind, environment_root

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CU130_INDEX_STRATEGY",
    "CudaRemediation",
    "CudaRepairKind",
    "ToolReceiptVerdict",
    "classify_tool_receipt",
    "cuda_remediation",
    "inplace_cuda_command",
    "published_wheel_platform_tag",
    "read_receipt",
    "tool_package_requirement",
    "tool_repair_arguments",
    "tool_repair_command",
    "tool_upgrade_commands",
    "upgrade_command_for_mode",
]

#: The tool request a CUDA repair falls back to when the receipt records none.
#: Only an inference host has torch to repair, so the request carries the
#: inference stack; the MCP adapter's own launch needs only the ``mcp`` extra.
_HOST_TOOL_REQUEST = "vaultspec-rag[gpu,mcp]"

#: The index strategy that both resolves this package and cannot prefer a CPU
#: build over an available accelerated one. uv's default stops at the first
#: index that publishes a name, which the CUDA mirror does for packages it
#: carries at versions this package cannot use, leaving the request
#: unsatisfiable; the best-match strategy takes the highest version from any
#: index, which silently selects PyPI's CPU torch whenever PyPI publishes a
#: release first.
CU130_INDEX_STRATEGY = "unsafe-first-match"

#: The machine architectures PyTorch publishes accelerated Linux wheels for.
_CUDA_LINUX_MACHINES = frozenset({"x86_64", "aarch64"})

#: The machine architectures PyTorch publishes accelerated Windows wheels for.
_CUDA_WINDOWS_MACHINES = frozenset({"amd64", "x86_64"})

#: What an operator has to know before the repair runs. It is applied in
#: place, so nothing has to stop, but the processes already running keep the
#: packages they loaded at startup until they are restarted.
RESTART_NOTE = (
    "The repair applies in place, so nothing has to be stopped for it. A "
    f"service already running keeps the build it started with: restart it "
    f"with `{server_stop_command()}` then `{server_start_command()}`."
)


class ToolReceiptVerdict(StrEnum):
    """Whether a tool installation will still be a GPU host after an upgrade.

    The receipt is what uv re-applies on every upgrade, so this is a verdict
    about the future rather than about the torch build installed now.
    """

    DURABLE = "durable"
    VERSION_PINNED = "version_pinned"
    TORCH_WHEEL_PINNED = "torch_wheel_pinned"
    NO_CUDA_SOURCE = "no_cuda_source"
    UNREADABLE = "unreadable"

    @property
    def label(self) -> str:
        """Plain-language statement of what the receipt will do next."""
        return {
            ToolReceiptVerdict.DURABLE: (
                "upgrades keep the GPU build and the release moves"
            ),
            ToolReceiptVerdict.VERSION_PINNED: (
                "pinned to one release, so upgrades report nothing to upgrade"
            ),
            ToolReceiptVerdict.TORCH_WHEEL_PINNED: (
                "pinned to one torch wheel, so a release needing a newer "
                "torch cannot resolve"
            ),
            ToolReceiptVerdict.NO_CUDA_SOURCE: (
                "records no CUDA source, so the next upgrade resolves a CPU-only torch"
            ),
            ToolReceiptVerdict.UNREADABLE: (
                "no readable installation receipt, so what an upgrade would "
                "resolve cannot be told"
            ),
        }[self]

    @property
    def durable(self) -> bool:
        """Whether an upgrade of this installation keeps the GPU build."""
        return self is ToolReceiptVerdict.DURABLE

    def fix(self, interpreter: str) -> str | None:
        """The one command that makes this receipt durable, if one is needed."""
        return None if self.durable else tool_repair_command(interpreter)


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
class CudaRemediation:
    """What one environment needs, as the operator should read it.

    ``steps`` is the whole operator-facing remediation, in order, and is what
    every surface prints. The individual commands are carried beside it for
    the surfaces that also report them structurally; they are the same strings
    the steps already contain, never a second derivation.
    """

    kind: CudaRepairKind
    steps: tuple[str, ...]
    repair_command: str = ""
    upgrade_commands: tuple[str, ...] = ()


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


def published_wheel_platform_tag(platform_name: str, machine: str) -> str | None:
    """The published PyTorch CUDA wheel platform segment, or ``None``.

    ``None`` means PyTorch publishes no accelerated wheel for this platform at
    all: macOS uses Metal instead, the CUDA index carries no ARM64 Windows
    wheel, and the accelerated Linux wheels exist for two architectures.
    Offering the CUDA index where it publishes nothing for the host resolves
    to a CPU build anyway, and reads to an operator as a repair they failed to
    apply rather than one that does not exist.
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


def _receipt_requirements(data: dict[str, object]) -> list[dict[str, object]]:
    """The parsed requirement records a receipt carries, if any."""
    tool = data.get("tool")
    requirements = (
        cast("dict[str, object]", tool).get("requirements")
        if isinstance(tool, dict)
        else None
    )
    if not isinstance(requirements, list):
        return []
    return [
        cast("dict[str, object]", entry)
        for entry in cast("list[object]", requirements)
        if isinstance(entry, dict)
    ]


def _receipt_options(data: dict[str, object]) -> dict[str, object]:
    """The resolver options a receipt records and re-applies on upgrade."""
    tool = data.get("tool")
    options = (
        cast("dict[str, object]", tool).get("options")
        if isinstance(tool, dict)
        else None
    )
    return cast("dict[str, object]", options) if isinstance(options, dict) else {}


def _records_cuda_index(options: dict[str, object]) -> bool:
    """Whether the receipt's own options reach the CUDA index on an upgrade.

    uv writes each index as a table carrying its URL, so the URL is read out
    of the record rather than compared against a rendered option string.
    """
    if options.get("index-strategy") != CU130_INDEX_STRATEGY:
        return False
    index = options.get("index")
    entries = cast("list[object]", index) if isinstance(index, list) else [index]
    for entry in entries:
        url = (
            cast("dict[str, object]", entry).get("url")
            if isinstance(entry, dict)
            else entry
        )
        if isinstance(url, str) and url.rstrip("/") == CU130_INDEX_URL.rstrip("/"):
            return True
    return False


def _pins_a_torch_wheel(requirements: list[dict[str, object]]) -> bool:
    """Whether the receipt names one torch file instead of a source for it."""
    for record in requirements:
        name = record.get("name")
        if isinstance(name, str) and name.lower() == "torch" and record.get("url"):
            return True
    return False


def _pins_a_version(requirements: list[dict[str, object]], package: str) -> bool:
    """Whether the receipt pins the tool to the exact release installed now."""
    for record in requirements:
        name = record.get("name")
        specifier = record.get("specifier")
        if (
            isinstance(name, str)
            and name.lower() == package.lower()
            and isinstance(specifier, str)
            and "==" in specifier
        ):
            return True
    return False


def classify_tool_receipt(interpreter: str) -> ToolReceiptVerdict:
    """Judge what an upgrade of this tool installation would resolve.

    The two pins are reported before the missing source, because an
    installation carrying either one cannot move at all and says so for a
    different reason than one that merely resolves from the wrong index.
    """
    data = read_receipt(environment_root(interpreter) / TOOL_RECEIPT_NAME)
    if data is None:
        return ToolReceiptVerdict.UNREADABLE
    requirements = _receipt_requirements(data)
    if _pins_a_torch_wheel(requirements):
        return ToolReceiptVerdict.TORCH_WHEEL_PINNED
    if _pins_a_version(requirements, Requirement(_HOST_TOOL_REQUEST).name):
        return ToolReceiptVerdict.VERSION_PINNED
    if not _records_cuda_index(_receipt_options(data)):
        return ToolReceiptVerdict.NO_CUDA_SOURCE
    return ToolReceiptVerdict.DURABLE


def _receipt_package_extras(receipt: Path, package: str) -> tuple[str, ...] | None:
    """Return the extras the receipt records for *package*, if it records any.

    The operator chose those extras. A repair that re-specifies the tool has
    no business widening them, so what is already recorded is what gets asked
    for again.
    """
    data = read_receipt(receipt)
    if data is None:
        return None
    for record in _receipt_requirements(data):
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

    A repair that re-specified the tool would impose this build's extras on
    an operator who chose otherwise, so the receipt's own extras are reused;
    the host request is the fallback for an environment that records none.

    No version is pinned. The repair changes the torch build and nothing
    else, and a pin is what stops every later upgrade from resolving at all.
    """
    fallback = _HOST_TOOL_REQUEST
    package = Requirement(fallback).name
    extras = _receipt_package_extras(
        environment_root(interpreter) / TOOL_RECEIPT_NAME, package
    )
    if extras is None:
        return fallback
    return f"{package}[{','.join(sorted(extras))}]" if extras else package


def _render_command(args: tuple[str, ...]) -> str:
    """Render an argument list as one line an operator can paste."""
    return " ".join(
        f'"{part}"' if " " in part or "[" in part else part for part in args
    )


def tool_repair_arguments(
    interpreter: str, *, upgrade: bool = False
) -> tuple[str, ...]:
    """The in-place repair, as the argument list the product itself runs.

    It re-installs the tool with the extras and interpreter already recorded,
    adds the CUDA index and the strategy that reaches it - which uv writes
    into the receipt and re-applies on every later upgrade - and upgrades
    torch alone, because uv otherwise keeps a CPU build that still satisfies
    the requirement. There is no ``--force``: a wholesale replacement is what
    destroys an environment something is running out of, and nothing in this
    cycle needs one.

    ``upgrade`` takes the newest release in the same step, for an
    installation whose receipt cannot carry the CUDA source across a bare
    upgrade yet.
    """
    # ``--python`` names the interpreter itself: uv rebuilds a tool
    # environment with its own default python request, so an installation
    # made against another interpreter silently moves without it.
    args = (
        "uv",
        "tool",
        "install",
        "--python",
        interpreter,
        tool_package_requirement(interpreter),
        "--index",
        CU130_INDEX_URL,
        "--index-strategy",
        CU130_INDEX_STRATEGY,
    )
    return (*args, "--upgrade") if upgrade else (*args, "--upgrade-package", "torch")


def tool_repair_command(interpreter: str, *, upgrade: bool = False) -> str:
    """The in-place repair as one line an operator can paste."""
    return _render_command(tool_repair_arguments(interpreter, upgrade=upgrade))


def tool_upgrade_commands(
    interpreter: str, verdict: ToolReceiptVerdict | None = None
) -> tuple[str, ...]:
    """How to take a newer release of a tool installation, and then serve it.

    A durable receipt upgrades with uv's own verb and keeps the GPU build. A
    receipt that is not durable yet is brought onto the cycle by the repair
    with a full upgrade, which does both in one step. Either way the running
    daemon keeps the release it started with until it is restarted.
    """
    if verdict is None:
        verdict = classify_tool_receipt(interpreter)
    package = Requirement(_HOST_TOOL_REQUEST).name
    upgrade = (
        f"uv tool upgrade {package}"
        if verdict.durable
        else tool_repair_command(interpreter, upgrade=True)
    )
    return (upgrade, f"{server_stop_command()} && {server_start_command()}")


def upgrade_command_for_mode(mode: str, interpreter: str) -> str:
    """The upgrade command for an installation declared in *mode*.

    A project installation is upgraded through its own lockfile, whatever
    group it sits in; only a standalone tool needs the receipt-aware form.
    *mode* is the declared provisioning mode as it is recorded in the
    workspace declaration.
    """
    if mode == "tool":
        return tool_upgrade_commands(interpreter)[0]
    return f"uv sync --upgrade-package {Requirement(_HOST_TOOL_REQUEST).name}"


def inplace_cuda_command(interpreter: str) -> str:
    """The in-place CUDA wheel repair for an environment uv does not own.

    ``--torch-backend`` is a ``uv pip`` option and is recorded nowhere, so
    this repairs the environment in front of it and nothing later. A tool
    environment is offered the receipt-carrying request instead, which
    survives the next upgrade.
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
        repair_command=command,
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
        repair_command=command,
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
    must be told so plainly instead of being handed an index that resolves a
    CPU build for it.
    """
    import platform as platform_module

    from ._topology import classify_environment

    platform_name = sys.platform if platform_name is None else platform_name
    machine = platform_module.machine() if machine is None else machine
    if platform_name == "darwin":
        return _metal_remediation(interpreter)
    if published_wheel_platform_tag(platform_name, machine) is None:
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
    repair = tool_repair_command(interpreter)
    upgrade, restart = tool_upgrade_commands(interpreter)
    if kind is RuntimeEnvKind.UVX_EPHEMERAL:
        return CudaRemediation(
            kind=CudaRepairKind.EPHEMERAL_ENVIRONMENT,
            steps=(
                "Install the tool itself, so the environment that serves is "
                f"the one carrying the GPU build: {repair}",
                RESTART_NOTE,
            ),
            repair_command=repair,
            upgrade_commands=(upgrade, restart),
        )
    return CudaRemediation(
        kind=CudaRepairKind.TOOL_ENVIRONMENT,
        steps=(
            f"Install the CUDA build of torch into this environment: {repair}",
            "It changes torch alone, in place, and records the CUDA index in "
            "the installation receipt, so later upgrades keep the GPU build.",
            RESTART_NOTE,
            f"Take a newer release later with: {upgrade}",
        ),
        repair_command=repair,
        upgrade_commands=(upgrade, restart),
    )
