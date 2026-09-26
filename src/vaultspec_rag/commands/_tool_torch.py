"""Durable CUDA repair for the active ``uv tool`` environment."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING
from urllib.parse import unquote

from .._process_probe import (
    EnvironmentHolder,
    HolderRelation,
    environment_holders,
)
from ..operator_state._provisioning import (
    ToolCudaInstallSpec,
    cuda_remediation,
    receipt_torch_wheel_url,
)
from ..operator_state._topology import (
    TOOL_RECEIPT_NAME,
    RuntimeEnvKind,
    classify_environment,
    environment_root,
)

if TYPE_CHECKING:
    from pathlib import Path

#: Holders are listed for an operator to act on, not dumped exhaustively.
HOLDER_REPORT_LIMIT = 10

#: How long the holder scan may take before the refusal gives up on it. Generous
#: on purpose: this runs once, immediately before an operator is handed a
#: command that removes an environment's contents, and a scan cut short reports
#: FEWER holders than exist. Slow and complete beats fast and blind here, and a
#: busy machine - the case where holders are most likely - is exactly the case
#: where the walk takes longest.
HOLDER_SCAN_BUDGET_SECONDS = 60.0

__all__ = [
    "HOLDER_REPORT_LIMIT",
    "ToolTorchRepairAction",
    "ToolTorchRepairOutcome",
    "repair_tool_torch",
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
class ToolTorchRepairOutcome:
    """One truthful repair result, including its safe remediation steps.

    ``command`` is the durable request an operator is handed, kept as its own
    field for the structured report; ``steps`` is the whole remediation as it
    should be read, built where every other surface builds it, so a refusal
    here and a warning elsewhere cannot describe the same environment
    differently.
    """

    action: ToolTorchRepairAction
    detail: str
    command: str = ""
    holders: tuple[EnvironmentHolder, ...] = ()
    steps: tuple[str, ...] = field(default_factory=tuple)

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
            "steps": list(self.steps),
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


def _receipt_has_cuda_requirement(receipt: Path, wheel_url: str) -> bool:
    """Check uv's parsed receipt retains the exact direct CUDA requirement.

    Both URLs are decoded before they are compared: uv re-encodes what it was
    given, so two spellings of one wheel differ as strings while naming the
    same file.
    """
    recorded = receipt_torch_wheel_url(receipt)
    return recorded is not None and unquote(recorded) == unquote(wheel_url)


def _holder_summary(holder: EnvironmentHolder) -> str:
    """One holder line, with the remediation its relation actually needs.

    Only a working-directory holder is asked to move: it is a shell or an
    editor whose binary has nothing to do with this environment. Anything
    running the environment's own interpreter - by image path, or by the
    launch path a symlinked POSIX venv presents - has to end.
    """
    if holder.relation is HolderRelation.WORKING_DIRECTORY:
        action = "move this process out of the directory"
    else:
        action = "end this process"
    return f"    pid {holder.pid} ({action}): {holder.image or 'unknown image'}"


def _handoff_outcome(
    interpreter: str, spec: ToolCudaInstallSpec, steps: tuple[str, ...]
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
    root = environment_root(interpreter)
    found = environment_holders(root, timeout=HOLDER_SCAN_BUDGET_SECONDS)
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
    if _receipt_has_cuda_requirement(root / TOOL_RECEIPT_NAME, spec.wheel_url):
        lines.append("  the receipt already pins this wheel; the environment does not")
    action = (
        ToolTorchRepairAction.HOLDER_DETECTED
        if found.holders
        else ToolTorchRepairAction.HANDOFF_REQUIRED
    )
    return ToolTorchRepairOutcome(
        action, "\n".join(lines), spec.command, found.holders, steps
    )


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
    from ..operator_state._compute import ProbeDepth
    from ..operator_state._environment_probe import probe_interpreter
    from ..operator_state._installation import ComputeCapability

    interpreter = interpreter or sys.executable
    kind = classify_environment(environment_root(interpreter))
    if kind is not RuntimeEnvKind.UV_TOOL:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.NOT_APPLICABLE,
            "active interpreter is not a persistent uv tool environment",
        )
    capability = probe_interpreter(interpreter, ProbeDepth.VERIFY).compute.capability
    if capability is ComputeCapability.READY:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.ALREADY_READY,
            "tool interpreter already has CUDA-ready torch",
        )
    if capability is ComputeCapability.NOT_APPLICABLE:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.NOT_APPLICABLE,
            "torch was never requested in this environment; install the GPU "
            "extra to run searches locally",
        )
    detail = capability.label
    if not capability.fixed_by_torch_reinstall:
        return ToolTorchRepairOutcome(ToolTorchRepairAction.CUDA_UNVERIFIED, detail)

    return _repair_defective_tool(interpreter, detail, dry_run=dry_run)


def _repair_defective_tool(
    interpreter: str, detail: str, *, dry_run: bool
) -> ToolTorchRepairOutcome:
    """Ask the one remediation builder what this environment needs.

    A host PyTorch publishes no accelerated wheel for has no repair to hand
    over, so the defect is reported as unresolved with the plain reason rather
    than as a command that cannot work.
    """
    remediation = cuda_remediation(interpreter, env_kind=RuntimeEnvKind.UV_TOOL)
    if remediation.spec is None:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.CUDA_UNVERIFIED,
            detail,
            steps=remediation.steps,
        )
    if dry_run:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.DRY_RUN,
            f"tool CUDA repair is needed because {detail}",
            remediation.durable_command,
            steps=remediation.steps,
        )
    return _handoff_outcome(interpreter, remediation.spec, remediation.steps)
