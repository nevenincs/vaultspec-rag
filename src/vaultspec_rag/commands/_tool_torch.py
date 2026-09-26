"""Durable CUDA repair for the active ``uv tool`` environment."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import StrEnum

from .._process_probe import (
    EnvironmentHolder,
    EnvironmentHolders,
    environment_holders,
)
from ..operator_state._holders import holder_role, holder_summary
from ..operator_state._installation import ComputeCapability
from ..operator_state._provisioning import cuda_remediation
from ..operator_state._topology import (
    RuntimeEnvKind,
    classify_environment,
    environment_root,
)

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
    """One terminal result for a persistent tool environment repair."""

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

    ``capability`` is the verdict this transaction obtained about the
    interpreter, carried so that nothing downstream asks a second time. The
    probe starts a child interpreter and imports torch in it; running it twice
    in one command doubles the wait and can answer differently, which is how
    one run came to print two disagreeing diagnoses of one environment. It is
    ``None`` only where no probe ran.
    """

    action: ToolTorchRepairAction
    detail: str
    command: str = ""
    holders: tuple[EnvironmentHolder, ...] = ()
    steps: tuple[str, ...] = field(default_factory=tuple)
    capability: ComputeCapability | None = None

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
            "capability": (
                self.capability.value if self.capability is not None else None
            ),
            "holders": [
                {
                    "pid": holder.pid,
                    "launcher_pid": holder.launcher_pid,
                    "relation": holder.relation.value,
                    "role": holder_role(holder).value,
                    "image": holder.image,
                    "cmdline": holder.cmdline,
                }
                for holder in self.holders
            ],
        }


def _uninspected_note(found: EnvironmentHolders) -> str | None:
    """Say what the scan could not see, as a count rather than a shrug.

    "Some processes" is the same sentence whether one protected system
    process was unreadable or the whole table was another user's, and those
    are different situations for someone deciding whether the list in front
    of them is the whole story.
    """
    if not found.complete:
        return "  the holder scan did not finish, so this list may be short"
    if found.uninspectable:
        count = found.uninspectable
        noun = "process" if count == 1 else "processes"
        return (
            f"  {count} {noun} could not be inspected (another user's, or "
            "exiting), so this list may be short"
        )
    return None


def _handoff_outcome(
    interpreter: str,
    command: str,
    steps: tuple[str, ...],
    *,
    capability: ComputeCapability | None = None,
) -> ToolTorchRepairOutcome:
    """Hand over the command that repairs this environment, and who is in it.

    The repair changes torch in place and needs nothing stopped, so the
    holders are reported for what they are: processes that keep the build
    they loaded at startup until they are restarted.
    """
    root = environment_root(interpreter)
    found = environment_holders(
        root, exclude_launch_chain=True, timeout=HOLDER_SCAN_BUDGET_SECONDS
    )
    lines = [f"tool CUDA repair for {root}"]
    if found.self_held:
        lines.append("  this command is running inside that environment")
    if found.holders:
        lines.append("  running out of it now, and unchanged until restarted:")
        lines.extend(
            f"    {holder_summary(holder)}"
            for holder in found.holders[:HOLDER_REPORT_LIMIT]
        )
        remaining = len(found.holders) - HOLDER_REPORT_LIMIT
        if remaining > 0:
            lines.append(f"    ... and {remaining} more")
    note = _uninspected_note(found)
    if note is not None:
        lines.append(note)
    action = (
        ToolTorchRepairAction.HOLDER_DETECTED
        if found.holders
        else ToolTorchRepairAction.HANDOFF_REQUIRED
    )
    return ToolTorchRepairOutcome(
        action, "\n".join(lines), command, found.holders, steps, capability
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
            capability=capability,
        )
    if capability is ComputeCapability.NOT_APPLICABLE:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.NOT_APPLICABLE,
            "torch was never requested in this environment; install the GPU "
            "extra to run searches locally",
            capability=capability,
        )
    if not capability.fixed_by_torch_reinstall:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.CUDA_UNVERIFIED,
            capability.label,
            capability=capability,
        )

    return _repair_defective_tool(interpreter, capability, dry_run=dry_run)


def _repair_defective_tool(
    interpreter: str, capability: ComputeCapability, *, dry_run: bool
) -> ToolTorchRepairOutcome:
    """Ask the one remediation builder what this environment needs.

    A host PyTorch publishes no accelerated wheel for has no repair to hand
    over, so the defect is reported as unresolved with the plain reason rather
    than as a command that cannot work.
    """
    remediation = cuda_remediation(interpreter, env_kind=RuntimeEnvKind.UV_TOOL)
    if not remediation.kind.repairable:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.CUDA_UNVERIFIED,
            capability.label,
            steps=remediation.steps,
            capability=capability,
        )
    if dry_run:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.DRY_RUN,
            f"tool CUDA repair is needed because {capability.label}",
            remediation.repair_command,
            steps=remediation.steps,
            capability=capability,
        )
    return _handoff_outcome(
        interpreter,
        remediation.repair_command,
        remediation.steps,
        capability=capability,
    )
