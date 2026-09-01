"""Durable CUDA repair for the active ``uv tool`` environment."""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote

from packaging.tags import Tag, cpython_tags
from packaging.version import InvalidVersion, Version

from ..torch_config._constants import CU130_INDEX_URL, TORCH_TOOL_PIN_VERSION

if TYPE_CHECKING:
    from ._models import ConfirmFn

__all__ = [
    "ToolCudaInstallSpec",
    "ToolTorchRepairAction",
    "ToolTorchRepairOutcome",
    "repair_tool_torch",
    "tool_cuda_install_spec",
]


class ToolTorchRepairAction(StrEnum):
    """One terminal result for a persistent tool environment repair."""

    NOT_APPLICABLE = "not_applicable"
    ALREADY_READY = "already_ready"
    DRY_RUN = "dry_run"
    DECLINED = "declined"
    SKIPPED_NON_TTY = "skipped_non_tty"
    SKIPPED_EOF = "skipped_eof"
    SERVICE_HELD = "service_held"
    UV_UNAVAILABLE = "uv_unavailable"
    UV_FAILED = "uv_failed"
    CUDA_UNVERIFIED = "cuda_unverified"
    RECEIPT_UNVERIFIED = "receipt_unverified"
    REPAIRED = "repaired"


@dataclass(frozen=True, slots=True)
class ToolCudaInstallSpec:
    """The one receipt-carrying CUDA tool installation request."""

    args: tuple[str, ...]
    wheel_url: str

    @property
    def command(self) -> str:
        """Render the request for an operator without reparsing it later."""
        return " ".join(
            f'"{part}"' if " " in part or "[" in part else part
            for part in self.args
        )


@dataclass(frozen=True, slots=True)
class ToolTorchRepairOutcome:
    """One truthful repair result, including its safe remediation command."""

    action: ToolTorchRepairAction
    detail: str
    command: str = ""

    @property
    def blocks_install(self) -> bool:
        """Whether continuing would hide an unresolved tool CUDA failure."""
        return self.action in {
            ToolTorchRepairAction.DECLINED,
            ToolTorchRepairAction.SKIPPED_NON_TTY,
            ToolTorchRepairAction.SKIPPED_EOF,
            ToolTorchRepairAction.SERVICE_HELD,
            ToolTorchRepairAction.UV_UNAVAILABLE,
            ToolTorchRepairAction.UV_FAILED,
            ToolTorchRepairAction.CUDA_UNVERIFIED,
            ToolTorchRepairAction.RECEIPT_UNVERIFIED,
        }

    def to_dict(self) -> dict[str, str]:
        """Return the stable JSON-safe report shape."""
        return {
            "action": self.action.value,
            "detail": self.detail,
            "command": self.command,
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


def tool_cuda_install_spec(
    *,
    torch_version: str | None = None,
    tag: Tag | None = None,
    platform_tag: str | None = None,
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
            _tool_package_spec(),
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
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str) and expected in unquote(value):
            return True
    return False


def _confirmation_outcome(
    confirm: ConfirmFn | None,
    *,
    assume_yes: bool,
    command: str,
) -> ToolTorchRepairOutcome | None:
    if assume_yes:
        return None
    if confirm is None:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.SKIPPED_NON_TTY,
            "tool CUDA repair requires confirmation; rerun with --yes",
            command,
        )
    try:
        approved = confirm(
            "Reinstall this uv tool environment with the CUDA torch wheel?"
        )
    except KeyboardInterrupt:
        approved = False
    except EOFError:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.SKIPPED_EOF,
            "tool CUDA repair confirmation reached EOF; rerun with --yes",
            command,
        )
    except Exception as exc:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.DECLINED,
            f"tool CUDA repair confirmation failed: {type(exc).__name__}",
            command,
        )
    if approved:
        return None
    return ToolTorchRepairOutcome(
        ToolTorchRepairAction.DECLINED,
        "tool CUDA repair declined by user",
        command,
    )


def _service_holder_outcome(command: str) -> ToolTorchRepairOutcome | None:
    from ..serviceclient._discovery import (
        DISCOVERY_STATE_ABSENT,
        resolve_machine_service,
    )

    resolution = resolve_machine_service()
    if resolution.state == DISCOVERY_STATE_ABSENT:
        return None
    return ToolTorchRepairOutcome(
        ToolTorchRepairAction.SERVICE_HELD,
        "tool CUDA repair refused because " + resolution.evidence(),
        command,
    )


def _uv_failure_detail(proc: subprocess.CompletedProcess[bytes]) -> str:
    output = (proc.stderr or proc.stdout).decode("utf-8", errors="replace").strip()
    suffix = f": {output[:500]}" if output else ""
    return f"uv tool reinstall exited with code {proc.returncode}{suffix}"


def repair_tool_torch(
    *,
    assume_yes: bool,
    confirm: ConfirmFn | None,
    dry_run: bool,
    interpreter: str | None = None,
) -> ToolTorchRepairOutcome:
    """Repair a defective persistent tool interpreter and verify its receipt."""
    from ..cli._gpu_errors import RuntimeEnvKind, classify_interpreter_env
    from ..cli._process import _probe_daemon_cuda

    interpreter = interpreter or sys.executable
    if classify_interpreter_env(interpreter) is not RuntimeEnvKind.UV_TOOL:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.NOT_APPLICABLE,
            "active interpreter is not a persistent uv tool environment",
        )
    probe = _probe_daemon_cuda(interpreter)
    if probe is None:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.ALREADY_READY,
            "tool interpreter already has CUDA-ready torch",
        )
    blocking, detail = probe
    if not blocking:
        return ToolTorchRepairOutcome(ToolTorchRepairAction.CUDA_UNVERIFIED, detail)

    return _repair_defective_tool(
        interpreter, detail, assume_yes=assume_yes, confirm=confirm, dry_run=dry_run
    )


def _repair_defective_tool(
    interpreter: str,
    detail: str,
    *,
    assume_yes: bool,
    confirm: ConfirmFn | None,
    dry_run: bool,
) -> ToolTorchRepairOutcome:
    spec = tool_cuda_install_spec()
    command = spec.command
    if dry_run:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.DRY_RUN,
            f"tool CUDA repair would run because {detail}",
            command,
        )
    confirmation = _confirmation_outcome(
        confirm,
        assume_yes=assume_yes,
        command=command,
    )
    if confirmation is not None:
        return confirmation
    service_holder = _service_holder_outcome(command)
    if service_holder is not None:
        return service_holder
    launch = _run_tool_reinstall(spec, command)
    if launch is not None:
        return launch
    return _verify_tool_repair(interpreter, spec, command)


def _run_tool_reinstall(
    spec: ToolCudaInstallSpec, command: str
) -> ToolTorchRepairOutcome | None:
    try:
        proc = subprocess.run(spec.args, capture_output=True, check=False)
    except FileNotFoundError:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.UV_UNAVAILABLE,
            "uv executable is unavailable for tool CUDA repair",
            command,
        )
    except OSError as exc:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.UV_FAILED,
            f"could not start uv tool reinstall: {exc}",
            command,
        )
    if proc.returncode:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.UV_FAILED, _uv_failure_detail(proc), command
        )
    return None


def _verify_tool_repair(
    interpreter: str, spec: ToolCudaInstallSpec, command: str
) -> ToolTorchRepairOutcome:
    from ..cli._process import _probe_daemon_cuda

    verified = _probe_daemon_cuda(interpreter)
    if verified is not None:
        _, detail = verified
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.CUDA_UNVERIFIED,
            f"tool reinstall completed but CUDA verification failed: {detail}",
            command,
        )
    receipt = _tool_root(interpreter) / "uv-receipt.toml"
    if not _receipt_has_cuda_requirement(receipt, spec.wheel_url):
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.RECEIPT_UNVERIFIED,
            f"tool reinstall completed but receipt lacks CUDA requirement: {receipt}",
            command,
        )
    return ToolTorchRepairOutcome(
        ToolTorchRepairAction.REPAIRED,
        "tool interpreter and receipt both verify the CUDA torch requirement",
        command,
    )
