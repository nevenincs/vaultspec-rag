"""Durable CUDA repair for a ``uv tool`` environment.

The repair changes torch in place and records the CUDA index in the
installation receipt, so nothing has to be stopped for it and later upgrades
keep the GPU build. It is run only on explicit consent, and what it did is
verified afterwards rather than assumed from an exit code.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from .._process_probe import (
    EnvironmentHolder,
    EnvironmentHolders,
    environment_holders,
)
from .._test_isolation import enforce_pytest_singleton_containment
from ..operator_state._holders import holder_summary, holder_wire
from ..operator_state._installation import ComputeCapability
from ..operator_state._provisioning import (
    CudaRemediation,
    ToolReceiptVerdict,
    classify_tool_receipt,
    cuda_remediation,
    tool_repair_steps,
)
from ..operator_state._topology import (
    RuntimeEnvKind,
    classify_environment,
    environment_root,
)
from ._util import confirmation_outcome

if TYPE_CHECKING:
    from ._models import ConfirmFn

#: Holders are listed for an operator to act on, not dumped exhaustively.
HOLDER_REPORT_LIMIT = 10

#: How long the holder scan may take before the refusal gives up on it. Generous
#: on purpose: this runs once, immediately before an operator is handed a
#: command that removes an environment's contents, and a scan cut short reports
#: FEWER holders than exist. Slow and complete beats fast and blind here, and a
#: busy machine - the case where holders are most likely - is exactly the case
#: where the walk takes longest.
HOLDER_SCAN_BUDGET_SECONDS = 60.0

#: How long the repair may run before it is abandoned. It resolves a full
#: dependency set and downloads an accelerated torch build, which is gigabytes
#: over a link the product does not control, so the bound is generous; what it
#: exists for is a uv that never returns, not a slow network.
REPAIR_TIMEOUT_SECONDS = 1800.0

#: What the operator is asked before anything is changed. It names the one
#: mutation and the one thing that does not happen, because the previous
#: repair replaced the whole environment and this one does not.
#: How long uv may take to report where its tool directory is. It reads
#: configuration and prints a path, so a second is generous; the bound exists
#: because the repair must not hang on a uv that never answers.
_TOOL_DIR_TIMEOUT_SECONDS = 30.0

#: The tool directory entry this package installs as.
_TOOL_ENTRY_NAME = "vaultspec-rag"

CONSENT_PROMPT = (
    "Install the CUDA build of torch into this tool environment and record "
    "the CUDA index in its receipt? Nothing is removed and nothing has to be "
    "stopped."
)

__all__ = [
    "HOLDER_REPORT_LIMIT",
    "ToolRepairRequest",
    "ToolTorchRepairAction",
    "ToolTorchRepairOutcome",
    "repair_tool_torch",
]


class ToolTorchRepairAction(StrEnum):
    """One terminal result for a persistent tool environment repair."""

    NOT_APPLICABLE = "not_applicable"
    ALREADY_READY = "already_ready"
    DRY_RUN = "dry_run"
    REPAIRED = "repaired"
    REPAIR_FAILED = "repair_failed"
    HOLDER_DETECTED = "holder_detected"
    HANDOFF_REQUIRED = "handoff_required"
    CUDA_UNVERIFIED = "cuda_unverified"


@dataclass(frozen=True, slots=True)
class ToolTorchRepairOutcome:
    """One truthful repair result, including its safe remediation steps.

    ``commands`` is the repair an operator is handed, in the order it has to
    run, kept as its own field for the structured report; ``steps`` is the
    whole remediation as it should be read, built where every other surface
    builds it, so a refusal here and a warning elsewhere cannot describe the
    same environment differently.

    ``capability`` is the verdict this transaction obtained about the
    interpreter, carried so that nothing downstream asks a second time. The
    probe starts a child interpreter and imports torch in it; running it twice
    in one command doubles the wait and can answer differently, which is how
    one run came to print two disagreeing diagnoses of one environment. It is
    ``None`` only where no probe ran.
    """

    action: ToolTorchRepairAction
    detail: str
    commands: tuple[str, ...] = ()
    holders: tuple[EnvironmentHolder, ...] = ()
    steps: tuple[str, ...] = field(default_factory=tuple)
    capability: ComputeCapability | None = None
    receipt: ToolReceiptVerdict | None = None
    #: Why this environment needs attention, in one line. The detail below it
    #: is a block; a report that has to open with the condition needs the
    #: sentence rather than its first line, which names the environment.
    reason: str = ""

    @property
    def blocks_install(self) -> bool:
        """Whether continuing would hide an unresolved tool CUDA failure."""
        return self.action in {
            ToolTorchRepairAction.HOLDER_DETECTED,
            ToolTorchRepairAction.HANDOFF_REQUIRED,
            ToolTorchRepairAction.CUDA_UNVERIFIED,
            ToolTorchRepairAction.REPAIR_FAILED,
        }

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON-safe report shape."""
        return {
            "action": self.action.value,
            "detail": self.detail,
            "commands": list(self.commands),
            "steps": list(self.steps),
            "capability": (
                self.capability.value if self.capability is not None else None
            ),
            "receipt": (self.receipt.value if self.receipt is not None else None),
            "reason": self.reason,
            **holder_wire(self.holders, limit=HOLDER_REPORT_LIMIT),
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
    remediation: CudaRemediation,
    need: _RepairNeed | None = None,
    answer: str = "",
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
    if need is not None:
        lines.append(f"  {need.reason}; {answer}")
    if found.self_held:
        lines.append("  this command is running inside that environment")
    if found.holders:
        lines.append(
            "  running out of it now, and still on the old build until restarted:"
        )
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
        action,
        "\n".join(lines),
        remediation.repair_commands,
        found.holders,
        remediation.steps,
        None if need is None else need.capability,
        None if need is None else need.receipt,
        "" if need is None else need.reason,
    )


@dataclass(frozen=True, slots=True)
class ToolRepairRequest:
    """One caller's terms for a tool-environment repair.

    ``stream`` lets the child write to the terminal, which a human run needs
    and a JSON run must not have: one envelope is the whole of that output.
    """

    dry_run: bool = False
    interpreter: str | None = None
    assume_yes: bool = False
    confirm: ConfirmFn | None = None
    stream: bool = False


@dataclass(frozen=True, slots=True)
class _RepairNeed:
    """Why this environment needs the repair, as the operator should read it."""

    capability: ComputeCapability
    receipt: ToolReceiptVerdict
    reason: str


def _assess(interpreter: str) -> ToolTorchRepairOutcome | _RepairNeed:
    """Decide whether this environment needs the repair, and why.

    Two conditions need the same one. A torch build that cannot use the GPU
    is the visible one. The other is an installation whose receipt records no
    CUDA source: its torch may work today, and the next upgrade resolves a
    CPU build over it, so walking past it leaves a host that breaks itself
    later without anyone touching it.
    """
    from ..operator_state._compute import ProbeDepth
    from ..operator_state._environment_probe import probe_interpreter

    kind = classify_environment(environment_root(interpreter))
    if kind is not RuntimeEnvKind.UV_TOOL:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.NOT_APPLICABLE,
            "active interpreter is not a persistent uv tool environment",
        )
    capability = probe_interpreter(interpreter, ProbeDepth.VERIFY).compute.capability
    if capability is ComputeCapability.NOT_APPLICABLE:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.NOT_APPLICABLE,
            "torch was never requested in this environment; install the GPU "
            "extra to run searches locally",
            capability=capability,
        )
    receipt = classify_tool_receipt(interpreter)
    ready = capability is ComputeCapability.READY
    if ready and receipt.durable:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.ALREADY_READY,
            "tool interpreter has CUDA-ready torch and a receipt that keeps it",
            capability=capability,
            receipt=receipt,
        )
    if not ready and not capability.fixed_by_torch_reinstall:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.CUDA_UNVERIFIED,
            capability.label,
            capability=capability,
            receipt=receipt,
            reason=capability.label,
        )
    reason = f"the installation receipt {receipt.label}" if ready else capability.label
    return _RepairNeed(capability=capability, receipt=receipt, reason=reason)


def repair_tool_torch(request: ToolRepairRequest) -> ToolTorchRepairOutcome:
    """Report what a persistent tool environment needs, and fix it on consent.

    With consent the repair runs from here, because it changes torch in place
    and needs nothing stopped. Without consent the command is handed over and
    the install stops, which is what it has always done.
    """
    interpreter = request.interpreter or sys.executable
    assessed = _assess(interpreter)
    if isinstance(assessed, ToolTorchRepairOutcome):
        return assessed
    return _repair_defective_tool(interpreter, assessed, request)


#: How each answer to the consent prompt reads in a report. An end of input
#: is a non-interactive run rather than a refusal, and saying so is what tells
#: a script author about the flag that would have worked.
_CONSENT_ANSWERS = {
    "approved": "authorised at the prompt",
    "declined": "declined at the prompt",
    "eof": "confirmation prompt hit end of input; re-run with --yes",
    "interrupted": "confirmation interrupted",
}


def _consented(assume_yes: bool, confirm: ConfirmFn | None) -> tuple[bool, str]:
    """Whether the operator authorised the repair, and how they answered."""
    if assume_yes:
        return True, "authorised with --yes"
    if confirm is None:
        return False, "no terminal to ask for confirmation; re-run with --yes"
    outcome = confirmation_outcome(confirm, CONSENT_PROMPT)
    answer = _CONSENT_ANSWERS.get(
        outcome, f"confirmation could not be asked ({outcome})"
    )
    return outcome == "approved", answer


def _run_repair(interpreter: str, *, stream: bool) -> tuple[bool, str]:
    """Run the repair's steps in order, bounded, and say what happened.

    uv is resolved through the PATH rather than assumed: the product does not
    provision it, and an absent uv is an ordinary state on a machine whose
    tool installation was made elsewhere.

    The steps run in order and stop at the first failure. The order is what
    makes the second one safe: it changes no package only because the first
    has already brought the environment to the recorded request, and a
    ``uv tool install`` that changes a package re-installs the tool's
    launchers, cannot replace one that is running, and then removes the
    environment.

    In human mode the child writes straight to the terminal, because a
    multi-gigabyte download with no output reads as a hang. In JSON mode its
    output is captured instead, so the one envelope stays the only thing on
    stdout.
    """
    # The one mutation this product performs on an environment it did not
    # create. Under pytest it must stay inside the session's own temporary
    # tree: a test that substitutes a classifier can otherwise point this at
    # the machine's real tool installation, and uv rebuilding that
    # environment removes its contents before it fails on the held files.
    # Inert outside pytest, where an operator's own environment is the point.
    enforce_pytest_singleton_containment(
        environment_root(interpreter), operation="repair a tool environment"
    )
    uv = shutil.which("uv")
    if uv is None:
        return False, "uv is not on PATH, so the repair could not be run here"
    mismatch = _target_mismatch(uv, interpreter)
    if mismatch is not None:
        return False, mismatch
    for step in tool_repair_steps(interpreter):
        ran, detail = _run_uv(uv, step, stream=stream)
        if not ran:
            return False, detail
    return True, "uv applied the repair"


def _run_uv(uv: str, step: tuple[str, ...], *, stream: bool) -> tuple[bool, str]:
    """Run one bounded uv invocation and report what it did."""
    try:
        # Argument form, with uv resolved off the PATH: no shell is involved.
        completed = subprocess.run(
            (uv, *step[1:]),
            capture_output=not stream,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=REPAIR_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"the repair did not finish within {REPAIR_TIMEOUT_SECONDS:.0f}s"
    except OSError as exc:
        return False, f"the repair could not be started: {exc}"
    if completed.returncode == 0:
        return True, "uv applied the step"
    tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-5:]
    detail = "; ".join(line.strip() for line in tail if line.strip())
    return False, f"uv exited with code {completed.returncode}" + (
        f": {detail}" if detail else ""
    )


def _target_mismatch(uv: str, interpreter: str) -> str | None:
    """Refuse unless the target is this process's own tool environment.

    Two things have to hold, and both are asked before anything is launched.

    The target must be the environment this process is running out of. That
    is what the accepted decision permits the product to change, and the one
    environment whose state it has just read; anything else is a stranger's,
    reached through a substituted classifier or a caller that does not exist.

    uv's own entry for the package must be that same environment. ``uv tool
    install`` acts on the tool directory's entry, not on the path it is
    given, and when the two differ uv rebuilds that entry wholesale, removing
    its contents before it fails on anything held.

    Both comparisons are by name rather than by resolved path, because an
    environment's interpreter is a symlink out of the tree on POSIX.
    ``uv tool dir`` reads configuration and writes nothing.
    """
    target = environment_root(interpreter)
    running = environment_root(sys.executable)
    if running != target:
        return (
            f"{target} is not the environment this command is running in "
            f"({running}); the repair stopped rather than change another "
            "environment"
        )
    try:
        located = subprocess.run(
            (uv, "tool", "dir"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TOOL_DIR_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return f"uv could not report its tool directory, so the repair stopped: {exc}"
    if located.returncode != 0:
        return "uv could not report its tool directory, so the repair stopped"
    entry = Path(os.path.abspath(located.stdout.strip())) / _TOOL_ENTRY_NAME
    if entry == target:
        return None
    return (
        f"uv would install into {entry}, which is not the environment being "
        f"repaired ({target}); the repair stopped rather than rebuild another "
        "environment"
    )


def _verify_repair(interpreter: str) -> tuple[bool, str]:
    """Check what the repair actually produced, rather than trusting uv.

    Both halves are asked: the build now installed, and the receipt that
    decides what the next upgrade resolves. A run that fixed the build and
    recorded nothing leaves the same host broken again at the next upgrade,
    which is the failure this whole cycle exists to end. The probe is a second
    verify-depth read of this interpreter in one command, and the only one
    justified: the environment changed in between.
    """
    from ..operator_state._compute import ProbeDepth
    from ..operator_state._environment_probe import probe_interpreter
    from ..operator_state._provisioning import tool_upgrade_commands

    capability = probe_interpreter(interpreter, ProbeDepth.VERIFY).compute.capability
    receipt = classify_tool_receipt(interpreter)
    if capability is ComputeCapability.CPU_ONLY_BUILD:
        # The request named the release the environment already had, and the
        # CUDA index publishes no build of it. Saying so is the difference
        # between a repair that failed and one that cannot succeed at this
        # release; taking a newer one is what changes the answer.
        return False, (
            f"after the repair, {capability.label}: the CUDA index publishes "
            "no accelerated build of the torch release this environment asks "
            f"for. Take a newer release with: {tool_upgrade_commands(interpreter)[0]}"
        )
    if capability is not ComputeCapability.READY:
        return False, f"after the repair, {capability.label}"
    if not receipt.durable:
        return False, f"after the repair, the receipt {receipt.label}"
    return True, "CUDA-ready torch, and a receipt that keeps it across upgrades"


def _repair_defective_tool(
    interpreter: str, need: _RepairNeed, request: ToolRepairRequest
) -> ToolTorchRepairOutcome:
    """Ask the one remediation builder what to run, then run it or hand it over.

    A host PyTorch publishes no accelerated wheel for has no repair to offer,
    so the defect is reported as unresolved with the plain reason rather than
    as a command that cannot work.
    """
    remediation = cuda_remediation(interpreter, env_kind=RuntimeEnvKind.UV_TOOL)
    if not remediation.kind.repairable:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.CUDA_UNVERIFIED,
            need.capability.label,
            steps=remediation.steps,
            capability=need.capability,
            receipt=need.receipt,
            reason=need.capability.label,
        )
    if request.dry_run:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.DRY_RUN,
            f"tool CUDA repair is needed because {need.reason}",
            remediation.repair_commands,
            steps=remediation.steps,
            capability=need.capability,
            receipt=need.receipt,
        )
    consented, answer = _consented(request.assume_yes, request.confirm)
    if not consented:
        return _handoff_outcome(interpreter, remediation, need, answer)
    ran, detail = _run_repair(interpreter, stream=request.stream)
    if ran:
        ran, detail = _verify_repair(interpreter)
    if not ran:
        return ToolTorchRepairOutcome(
            ToolTorchRepairAction.REPAIR_FAILED,
            detail,
            remediation.repair_commands,
            steps=remediation.steps,
            capability=need.capability,
            receipt=classify_tool_receipt(interpreter),
            reason=detail,
        )
    return ToolTorchRepairOutcome(
        ToolTorchRepairAction.REPAIRED,
        detail,
        capability=ComputeCapability.READY,
        receipt=classify_tool_receipt(interpreter),
        steps=(remediation.restart_step,),
    )
