"""Durable CUDA repair for the active ``uv tool`` environment."""

from __future__ import annotations

import importlib.metadata
import json
import sys
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast
from urllib.parse import unquote

from packaging.requirements import InvalidRequirement, Requirement
from packaging.tags import Tag, cpython_tags
from packaging.version import InvalidVersion, Version

from .._process_probe import (
    EnvironmentHolder,
    HolderRelation,
    environment_holders,
)
from ..torch_config._constants import CU130_INDEX_URL, TORCH_TOOL_PIN_VERSION

#: Holders are listed for an operator to act on, not dumped exhaustively.
HOLDER_REPORT_LIMIT = 10

__all__ = [
    "HOLDER_REPORT_LIMIT",
    "ToolCudaInstallSpec",
    "ToolTorchRepairAction",
    "ToolTorchRepairOutcome",
    "repair_tool_torch",
    "tool_cuda_install_spec",
]


class ToolTorchRepairAction(StrEnum):
    """One terminal result for a persistent tool environment repair.

    There is no success value. A repair replaces the whole environment, and
    this process runs inside the only environment it ever targets, so its own
    interpreter is one of the files the replacement must remove. Every path
    therefore ends in a refusal that hands the operator a command to run from
    a shell that holds nothing.
    """

    NOT_APPLICABLE = "not_applicable"
    ALREADY_READY = "already_ready"
    DRY_RUN = "dry_run"
    HOLDER_DETECTED = "holder_detected"
    HANDOFF_REQUIRED = "handoff_required"
    CUDA_UNVERIFIED = "cuda_unverified"


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
class ToolTorchRepairOutcome:
    """One truthful repair result, including its safe remediation command."""

    action: ToolTorchRepairAction
    detail: str
    command: str = ""
    holders: tuple[EnvironmentHolder, ...] = ()

    @property
    def blocks_install(self) -> bool:
        """Whether continuing would hide an unresolved tool CUDA failure."""
        return self.action in {
            ToolTorchRepairAction.HOLDER_DETECTED,
            ToolTorchRepairAction.HANDOFF_REQUIRED,
            ToolTorchRepairAction.CUDA_UNVERIFIED,
        }

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON-safe report shape."""
        return {
            "action": self.action.value,
            "detail": self.detail,
            "command": self.command,
            "holders": [
                {
                    "pid": holder.pid,
                    "relation": holder.relation.value,
                    "image": holder.image,
                    "cmdline": holder.cmdline,
                }
                for holder in self.holders
            ],
        }


def _wheel_torch_version(installed: str | None) -> str:
    """Return the CUDA release matching an installed torch distribution."""
    if installed is None:
        return TORCH_TOOL_PIN_VERSION
    try:
        return Version(installed).base_version
    except InvalidVersion:
        return TORCH_TOOL_PIN_VERSION


def _wheel_platform_tag(platform_name: str, machine: str) -> str:
    """Return the published PyTorch wheel platform segment."""
    if platform_name == "win32":
        return "win_amd64"
    return f"manylinux_2_28_{machine.lower()}"


def _tool_package_spec() -> str:
    """Read the one tool-mode package request from the bundled definition."""
    from importlib.resources import files

    source = files("vaultspec_rag.builtins") / "mcps" / "vaultspec-rag.builtin.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    value = data.get("_vaultspec_mode_tool_spec")
    if not isinstance(value, str) or not value:
        raise RuntimeError("bundled tool definition has no tool package specification")
    return value


def _receipt_package_extras(receipt: Path, package: str) -> tuple[str, ...] | None:
    """Return the extras the receipt records for *package*, if it records any.

    The operator chose those extras. A repair that re-specifies the tool has
    no business widening them, so what is already recorded is what gets asked
    for again.
    """
    try:
        data = tomllib.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    tool = data.get("tool")
    requirements = tool.get("requirements") if isinstance(tool, dict) else None
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


def _tool_package_requirement(interpreter: str) -> str:
    """Render the package request a repair may ask for, and no more.

    A bare name resolves to whatever is newest, so the command that repairs a
    torch wheel would also upgrade the tool and impose this build's extras on
    an operator who chose otherwise. The installed version is pinned and the
    receipt's own extras are reused; the bundled specification is the fallback
    for an environment that records neither.
    """
    fallback = _tool_package_spec()
    package = Requirement(fallback).name
    extras = _receipt_package_extras(
        _tool_root(interpreter) / "uv-receipt.toml", package
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
) -> ToolCudaInstallSpec:
    """Build the durable CUDA request from the running interpreter's tags."""
    import platform

    if torch_version is None:
        try:
            installed = importlib.metadata.version("torch")
        except importlib.metadata.PackageNotFoundError:
            installed = None
        torch_version = _wheel_torch_version(installed)
    tag = tag or next(iter(cpython_tags()))
    platform_tag = platform_tag or _wheel_platform_tag(sys.platform, platform.machine())
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
            package_spec or _tool_package_spec(),
            "--with",
            f"torch @ {wheel_url}",
        ),
        wheel_url=wheel_url,
    )


def _tool_root(interpreter: str) -> Path:
    binary = Path(interpreter).resolve()
    if binary.parent.name.lower() in {"scripts", "bin"}:
        return binary.parent.parent
    return binary.parent


def _receipt_has_cuda_requirement(receipt: Path, wheel_url: str) -> bool:
    """Check uv's parsed receipt retains the exact direct CUDA requirement."""
    try:
        data = tomllib.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False
    expected = unquote(wheel_url)
    pending: list[object] = [data]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            record = cast("dict[str, object]", value)
            name = record.get("name")
            url = record.get("url")
            if (
                isinstance(name, str)
                and name.lower() == "torch"
                and isinstance(url, str)
                and unquote(url) == expected
            ):
                return True
            pending.extend(record.values())
        elif isinstance(value, list):
            pending.extend(cast("list[object]", value))
        elif isinstance(value, str):
            try:
                requirement = Requirement(value)
            except InvalidRequirement:
                continue
            if (
                requirement.name.lower() == "torch"
                and requirement.url is not None
                and unquote(requirement.url) == expected
            ):
                return True
    return False


def _holder_summary(holder: EnvironmentHolder) -> str:
    """One holder line, with the remediation its relation actually needs."""
    if holder.relation is HolderRelation.IMAGE:
        action = "end this process"
    else:
        action = "move this process out of the directory"
    return f"    pid {holder.pid} ({action}): {holder.image or 'unknown image'}"


def _handoff_outcome(
    interpreter: str, spec: ToolCudaInstallSpec, command: str
) -> ToolTorchRepairOutcome:
    """Refuse to replace this environment, and say what has to happen instead.

    The replacement is never run from here. uv removes an environment's
    contents before writing the new ones, and a file it cannot remove stops it
    half-way, leaving nothing runnable behind - so the one process guaranteed
    to be holding this environment is the one that would be issuing the
    command. Holders are reported because the operator has to clear them
    first, and a working-directory holder needs different handling from a
    process to end.
    """
    root = _tool_root(interpreter)
    found = environment_holders(root)
    lines = [
        f"tool CUDA repair must run from outside {root}",
        "  the environment is replaced wholesale, and this process runs inside it",
    ]
    if found.holders:
        lines.append("  holders to clear first:")
        lines.extend(
            _holder_summary(holder) for holder in found.holders[:HOLDER_REPORT_LIMIT]
        )
        remaining = len(found.holders) - HOLDER_REPORT_LIMIT
        if remaining > 0:
            lines.append(f"    ... and {remaining} more")
    if not found.certain:
        lines.append(
            "  some processes could not be inspected, so this list may be short"
        )
    if _receipt_has_cuda_requirement(root / "uv-receipt.toml", spec.wheel_url):
        lines.append("  the receipt already pins this wheel; the environment does not")
    action = (
        ToolTorchRepairAction.HOLDER_DETECTED
        if found.holders
        else ToolTorchRepairAction.HANDOFF_REQUIRED
    )
    return ToolTorchRepairOutcome(action, "\n".join(lines), command, found.holders)


def repair_tool_torch(
    *,
    dry_run: bool,
    interpreter: str | None = None,
) -> ToolTorchRepairOutcome:
    """Report what a defective persistent tool interpreter needs.

    Nothing is mutated, so nothing is asked. The transaction inspects the
    environment and returns the command an operator must run from outside it;
    consent belonged to a replacement this no longer performs, and keeping the
    prompt would have blocked non-interactive installs on a question with no
    consequence.
    """
    from ..cli._gpu_errors import RuntimeEnvKind, classify_interpreter_env
    from ..cli._process import (
        _probe_daemon_accelerator,
        accelerator_probe_is_torch_installation_defect,
    )

    interpreter = interpreter or sys.executable
    if classify_interpreter_env(interpreter) is not RuntimeEnvKind.UV_TOOL:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.NOT_APPLICABLE,
            "active interpreter is not a persistent uv tool environment",
        )
    probe = _probe_daemon_accelerator(interpreter)
    if probe is None:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.ALREADY_READY,
            "tool interpreter already has CUDA-ready torch",
        )
    blocking, detail = probe
    if not blocking or not accelerator_probe_is_torch_installation_defect(detail):
        return ToolTorchRepairOutcome(ToolTorchRepairAction.CUDA_UNVERIFIED, detail)

    return _repair_defective_tool(interpreter, detail, dry_run=dry_run)


def _repair_defective_tool(
    interpreter: str, detail: str, *, dry_run: bool
) -> ToolTorchRepairOutcome:
    spec = tool_cuda_install_spec(package_spec=_tool_package_requirement(interpreter))
    command = spec.command
    if dry_run:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.DRY_RUN,
            f"tool CUDA repair is needed because {detail}",
            command,
        )
    return _handoff_outcome(interpreter, spec, command)
