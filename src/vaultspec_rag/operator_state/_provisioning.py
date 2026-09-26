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
    "durable_upgrade_commands",
    "environment_python_request",
    "inplace_cuda_command",
    "installed_tool_release",
    "published_wheel_platform_tag",
    "read_receipt",
    "release_upgrade_command",
    "restart_service_command",
    "tool_package_requirement",
    "tool_receipt_arguments",
    "tool_repair_commands",
    "tool_repair_steps",
    "tool_swap_arguments",
    "tool_upgrade_commands",
    "upgrade_commands_for_mode",
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

    def fix(self, interpreter: str) -> tuple[str, ...]:
        """The commands that make this receipt durable, in the order they run.

        Empty when nothing is needed. A sequence rather than one block of
        text, because the order is load-bearing and a reader given the two
        joined by a newline runs the visible one: the package change alone
        leaves a receipt the next upgrade resolves straight back to a
        CPU-only build.
        """
        return () if self.durable else tool_repair_commands(interpreter)


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
    repair_commands: tuple[str, ...] = ()
    upgrade_commands: tuple[str, ...] = ()
    #: What to do once the repair has been applied, as the operator should
    #: read it. Carried by name because it is the step a successful repair
    #: reports on its own, where reaching into ``steps`` by position picks up
    #: whatever happens to be last.
    restart_step: str = ""


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
    """Whether the receipt names one torch build instead of a source for it.

    uv records a direct requirement under ``url`` for an http one and
    ``path`` for a local file, and an exact specifier pins just as hard: each
    one makes the next upgrade re-apply the build recorded here rather than
    resolve an accelerated one. Reading only the first reported a receipt
    written the other two ways as durable.
    """
    for record in requirements:
        name = record.get("name")
        if not isinstance(name, str) or name.lower() != "torch":
            continue
        specifier = record.get("specifier")
        if (
            record.get("url")
            or record.get("path")
            or (isinstance(specifier, str) and "==" in specifier)
        ):
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


def environment_python_request(interpreter: str) -> str | None:
    """The ``--python`` request naming the version an environment already runs.

    Read out of the environment's own configuration rather than from the
    process asking, because they are routinely different: an install run from
    a project virtual environment is asking about a tool environment built on
    another interpreter. uv treats a request that does not match as a request
    for a different environment and rebuilds, which is destructive; matching
    it exactly is what keeps the repair in place.

    ``None`` when the environment cannot be read. uv then keeps the
    interpreter the environment already has, which is the outcome wanted, and
    records no version request of its own.
    """
    config = environment_root(interpreter) / "pyvenv.cfg"
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    values = {
        key.strip().lower(): value.strip()
        for key, _, value in (line.partition("=") for line in lines)
        if value
    }
    version = values.get("version_info") or values.get("version") or ""
    parts = version.split(".")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    request = f"{parts[0]}.{parts[1]}"
    # A free-threaded build is a different interpreter to uv, and the version
    # alone does not say so; uv names it in the interpreter it points home at.
    return f"{request}t" if "freethreaded" in values.get("home", "") else request


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


def environment_distribution_version(interpreter: str, distribution: str) -> str | None:
    """The version of *distribution* installed in *interpreter*'s environment.

    Read out of that environment's own installed metadata, not out of the
    process asking: an install run from a project environment is repairing a
    tool environment whose releases are unrelated to its own. Absent metadata
    is an ordinary state - a damaged environment has lost distributions - and
    yields ``None`` rather than an exception.
    """
    root = environment_root(interpreter)
    candidates = [root / "Lib" / "site-packages"]
    candidates.extend(sorted(root.glob("lib/python*/site-packages")))
    prefix = f"{distribution.replace('-', '_').lower()}-"
    for site in candidates:
        try:
            entries = sorted(site.glob("*.dist-info"))
        except OSError:
            continue
        for entry in entries:
            if entry.name.lower().startswith(prefix):
                return entry.name[len(prefix) : -len(".dist-info")]
    return None


def _public_version(version: str | None) -> str | None:
    """A version without its local segment, which no index publishes under.

    ``2.14.0+cpu`` and ``2.14.0+cu130`` are the same release built twice. The
    request names the release; which build answers it is what the index and
    the strategy decide.
    """
    if version is None:
        return None
    from packaging.version import InvalidVersion, Version

    try:
        return Version(version).public
    except InvalidVersion:
        return version.partition("+")[0] or None


def tool_swap_arguments(interpreter: str) -> tuple[str, ...]:
    """Bring a tool environment to its recorded request on the CUDA source.

    This is uv's pip interface, not ``uv tool install``, and the difference is
    the whole reason the repair is two steps: a ``uv tool install`` that
    changes any package re-installs the tool's launchers afterwards, cannot
    replace one that is running, and then removes the environment. Nothing
    here touches a launcher.

    The request names the package at the release already installed, so a
    damaged environment regains the distributions it lost without gaining a
    release it did not ask for, and torch is reinstalled at the release it
    already has, from the CUDA index under the strategy that reaches it. A
    version that cannot be read is left unnamed, which resolves the newest;
    that is why nothing runs this command on the operator's behalf without a
    release to name (see :func:`installed_tool_release`).
    """
    package = tool_package_requirement(interpreter)
    installed = installed_tool_release(interpreter)
    torch_version = _public_version(
        environment_distribution_version(interpreter, "torch")
    )
    return (
        "uv",
        "pip",
        "install",
        "--python",
        interpreter,
        "--index",
        CU130_INDEX_URL,
        "--index-strategy",
        CU130_INDEX_STRATEGY,
        "--reinstall-package",
        "torch",
        package if installed is None else f"{package}=={installed}",
        *(() if torch_version is None else (f"torch=={torch_version}",)),
    )


def _recorded_tool_release(interpreter: str) -> str | None:
    """The exact release the receipt pins the tool to, if it pins one.

    uv writes what it was asked to install. An environment whose installed
    metadata is gone still has this, and it is the release the operator
    chose rather than whatever is newest today.
    """
    data = read_receipt(environment_root(interpreter) / TOOL_RECEIPT_NAME)
    if data is None:
        return None
    package = Requirement(_HOST_TOOL_REQUEST).name
    for record in _receipt_requirements(data):
        name = record.get("name")
        specifier = record.get("specifier")
        if (
            isinstance(name, str)
            and name.lower() == package.lower()
            and isinstance(specifier, str)
            and specifier.startswith("==")
        ):
            return specifier.removeprefix("==").strip() or None
    return None


def installed_tool_release(interpreter: str) -> str | None:
    """The release a repair must re-install, from either source that has it.

    The environment's own installed metadata first, because that is what is
    there now. The receipt's exact pin second, for an environment damaged
    badly enough to have lost the metadata but not the receipt.

    ``None`` means neither source could answer. A repair that names no
    release resolves the newest one, which is an upgrade the operator did
    not ask for under a prompt about torch, so nothing runs it for them.
    """
    return environment_distribution_version(
        interpreter, Requirement(_HOST_TOOL_REQUEST).name
    ) or _recorded_tool_release(interpreter)


def tool_receipt_arguments(interpreter: str) -> tuple[str, ...]:
    """Record the CUDA source in the receipt, changing no package.

    Run after the swap, when the environment already satisfies the request,
    uv reports the tool as installed and writes the options; it re-installs
    nothing, so no launcher is touched. It carries no ``--upgrade``,
    ``--reinstall``, ``--force`` or ``--with``: each of those changes a
    package, and a package change is what turns this into a removal of the
    environment while a launcher runs.

    ``--python`` names the version the target environment already runs, read
    out of that environment. A request uv reads as a different interpreter is
    not applied in place at all: uv rebuilds the environment wholesale. An
    environment that cannot be read is given no request, which uv applies in
    place and records nothing for.
    """
    python = environment_python_request(interpreter)
    return (
        "uv",
        "tool",
        "install",
        *(() if python is None else ("--python", python)),
        tool_package_requirement(interpreter),
        "--index",
        CU130_INDEX_URL,
        "--index-strategy",
        CU130_INDEX_STRATEGY,
    )


def tool_repair_steps(interpreter: str) -> tuple[tuple[str, ...], ...]:
    """The repair, in the order it must run: swap the build, then record it."""
    return (tool_swap_arguments(interpreter), tool_receipt_arguments(interpreter))


def tool_repair_commands(interpreter: str) -> tuple[str, ...]:
    """The repair as lines an operator can paste, in order."""
    return tuple(_render_command(step) for step in tool_repair_steps(interpreter))


def release_upgrade_command() -> str:
    """The command that takes a newer release, and nothing else.

    uv's own verb is the only thing in this cycle that moves the release. It
    keeps the GPU build because the receipt carries the CUDA source, and it
    leaves the environment whole with a launcher running, where an install
    would remove it. Named rather than picked out of a sequence by position:
    the sequence starts with a receipt install whenever the receipt is not
    durable yet, and that command takes no release at all.
    """
    return f"uv tool upgrade {Requirement(_HOST_TOOL_REQUEST).name}"


def durable_upgrade_commands() -> tuple[str, ...]:
    """Upgrading an installation whose receipt already carries the source."""
    return (release_upgrade_command(), restart_service_command())


def tool_upgrade_commands(
    interpreter: str, verdict: ToolReceiptVerdict | None = None
) -> tuple[str, ...]:
    """How to take a newer release of a tool installation, and then serve it.

    A durable receipt upgrades with uv's own verb, which keeps the GPU build
    and leaves the environment whole even when a launcher of the tool is
    running. A receipt that is not durable yet is brought onto the cycle
    first, by the options-only install that changes no package. Either way the
    running daemon keeps the release it started with until it is restarted.
    """
    if verdict is None:
        verdict = classify_tool_receipt(interpreter)
    if verdict.durable:
        return durable_upgrade_commands()
    return (
        _render_command(tool_receipt_arguments(interpreter)),
        *durable_upgrade_commands(),
    )


def restart_service_command() -> str:
    """Restart the service, which is how a new build reaches the daemon."""
    return f"{server_stop_command()} && {server_start_command()}"


def upgrade_commands_for_mode(mode: str, interpreter: str) -> tuple[str, ...]:
    """The commands that upgrade an installation declared in *mode*, in order.

    A project installation is upgraded through its own lockfile, whatever
    group it sits in; only a standalone tool needs the receipt-aware
    sequence, which is more than one command whenever its receipt does not
    yet carry the CUDA source. *mode* is the declared provisioning mode as it
    is recorded in the workspace declaration.
    """
    if mode == "tool":
        return tool_upgrade_commands(interpreter)
    return (f"uv sync --upgrade-package {Requirement(_HOST_TOOL_REQUEST).name}",)


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
        repair_commands=(command,),
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
        repair_commands=(command,),
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
    repair = tool_repair_commands(interpreter)
    upgrade = tool_upgrade_commands(interpreter)
    if kind is RuntimeEnvKind.UVX_EPHEMERAL:
        return CudaRemediation(
            kind=CudaRepairKind.EPHEMERAL_ENVIRONMENT,
            steps=(
                "Install the tool itself, so the environment that serves is "
                "the one carrying the GPU build:",
                *repair,
                RESTART_NOTE,
            ),
            repair_commands=repair,
            upgrade_commands=upgrade,
            restart_step=RESTART_NOTE,
        )
    return CudaRemediation(
        kind=CudaRepairKind.TOOL_ENVIRONMENT,
        steps=(
            "Install the CUDA build of torch into this environment, then "
            "record the index it came from, in this order:",
            *repair,
            "The first command changes torch alone, in place; the second "
            "changes no package and only writes the index into the "
            "installation receipt, so later upgrades keep the GPU build.",
            RESTART_NOTE,
            # After this repair the receipt carries the CUDA source, so
            # the command that takes a release later is uv's own verb - not
            # whatever this installation needs first today.
            f"Take a newer release later with: {release_upgrade_command()}",
        ),
        repair_commands=repair,
        upgrade_commands=upgrade,
        restart_step=RESTART_NOTE,
    )
