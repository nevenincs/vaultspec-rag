"""The operator's approval of vaultspec-rag's own MCP launch, obtained at install.

Core refuses to enrol an MCP launch until the operator has reviewed the exact
definition, command, arguments and environment and approved them at a terminal
(``vaultspec-core spec mcps trust``). No flag stands in for that review, so an
install that never asked would seed the definition and then skip the
enrolment. This module asks, for exactly vaultspec-rag's own definition and no
other source, and records the answer through core's own grant.

Core binds an approval to where a definition really lives, and an install
holds a linked definition or native config as a regular copy until it commits.
The approval is therefore recorded at the real location first, which is what
every later sync of the workspace asks about. For the length of the run it is
recorded at the copy's location as well, which is what the install's own sync
asks about. That second record is the same reviewed launch at the one other
path core will look at, so it creates no consent; it is made only for a launch
already approved at its real location, and it matches nothing once the link is
back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from vaultspec_core.core.exceptions import VaultSpecError
from vaultspec_core.core.mcps_trust import McpApproval, grant

from ._mcp_host_state import approved_launches
from ._mode import RAG_DISTRIBUTION_NAME
from ._util import confirmation_outcome

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from ._mcp_host_state import LaunchToEnroll
    from ._models import ConfirmFn

__all__ = [
    "OWN_LAUNCH_UNAPPROVED",
    "RagLaunchConsent",
    "approvals_for",
    "replace_own_launch_skip",
    "review_rag_launch",
]

#: What a failed read or write of the approval record can raise.
_GRANT_FAILURES = (OSError, VaultSpecError)

#: How core opens the warning for a launch it skipped as unapproved.
_CORE_UNAPPROVED_PREFIX = f"MCP server '{RAG_DISTRIBUTION_NAME}' is not approved for "

#: The one cause and the one command an operator needs when this package's own
#: launch was skipped. Core's warning names its own CLI, which a tool install of
#: vaultspec-rag does not put on PATH, and lists several alternatives.
OWN_LAUNCH_UNAPPROVED = (
    "The vaultspec-rag MCP integration was not enrolled because its launch is "
    "not approved. Run `vaultspec-rag install` at a terminal to review and "
    "approve it."
)


def approvals_for(root: Path, launches: Iterable[LaunchToEnroll]) -> list[McpApproval]:
    """Return what approving *launches* would record, at the paths they hold now."""
    return [
        McpApproval.capture(
            root,
            launch.authority_target,
            launch.name,
            launch.authority_path,
            launch.config,
            launch.digest,
        )
        for launch in launches
    ]


def _review_prompt(approvals: list[McpApproval]) -> str:
    """Render exactly what an approval records, one block per distinct launch.

    Every value is shown as JSON with non-ASCII escaped, as core's own review
    shows it, so a control character or a markup-like fragment in a definition
    cannot hide or rewrite what the operator is approving.
    """
    blocks: dict[tuple[str, str, str], list[McpApproval]] = {}
    for approval in approvals:
        blocks.setdefault(
            (approval.source, approval.definition_digest, approval.launch), []
        ).append(approval)
    lines = [f"Approve the {RAG_DISTRIBUTION_NAME} MCP server for this workspace?"]
    for (source, digest, launch), hosts in blocks.items():
        lines.append(f"  definition: {json.dumps(source, ensure_ascii=True)}")
        lines.append(f"  digest:     {json.dumps(digest, ensure_ascii=True)}")
        lines.append(f"  launch:     {launch}")
        lines.extend(
            f"  host:       {json.dumps(host.provider)} ({json.dumps(host.scope)}) "
            f"{json.dumps(host.target, ensure_ascii=True)}"
            for host in hosts
        )
    lines.append(
        "These hosts may later run this command as you, with your credentials "
        "and environment. The approval is stored outside this workspace and "
        "covers exactly this definition and launch; any change asks again."
    )
    return "\n".join(lines)


@dataclass(slots=True)
class RagLaunchConsent:
    """What the operator has approved of vaultspec-rag's own launch for a root."""

    root: Path
    #: The launches approved at their real locations, before or by this review.
    approved: list[LaunchToEnroll] = field(default_factory=list)
    #: The approval keys recorded for *approved*, at those real locations.
    recorded: frozenset[str] = frozenset()
    #: Operator-facing problems met while asking or recording.
    warnings: list[str] = field(default_factory=list)

    def carry_into_transaction(self) -> None:
        """Record each approved launch where this run holds it, when that differs.

        Call it once the run's links are materialized and before its sync. It
        writes nothing for a workspace with no link in the way, because the
        keys are then the ones already recorded.
        """
        held = [
            approval
            for approval in approvals_for(self.root, self.approved)
            if approval.key not in self.recorded
        ]
        if not held:
            return
        try:
            grant(held)
        except _GRANT_FAILURES as exc:
            self.warnings.append(
                f"MCP approval could not be carried into this install: {exc}"
            )


def review_rag_launch(
    root: Path,
    planned: Iterable[LaunchToEnroll],
    *,
    confirm: ConfirmFn | None,
    assume_yes: bool,
) -> RagLaunchConsent:
    """Ask the operator to approve vaultspec-rag's own launch, then record it.

    Only the definition named for this package is considered; every other
    source stays the operator's to approve with core. Nobody is asked when
    there is nobody to ask (*confirm* is ``None``) or when the run was told to
    assume consent (*assume_yes*): a flag is not a review, and core's own sync
    then skips the launch with the command that grants it.
    """
    own = [launch for launch in planned if launch.name == RAG_DISTRIBUTION_NAME]
    consent = RagLaunchConsent(root)
    approved = approved_launches(own, root)
    missing = [launch for launch in own if launch not in approved]
    if missing and confirm is not None and not assume_yes:
        outcome = confirmation_outcome(
            confirm, _review_prompt(approvals_for(root, missing))
        )
        if outcome.startswith("error:"):
            consent.warnings.append(
                f"MCP approval could not be asked of the operator ({outcome})."
            )
        elif outcome == "approved":
            try:
                grant(approvals_for(root, missing))
            except _GRANT_FAILURES as exc:
                consent.warnings.append(f"MCP approval could not be recorded: {exc}")
            else:
                approved = own
    consent.approved = approved
    consent.recorded = frozenset(
        approval.key for approval in approvals_for(root, approved)
    )
    return consent


def replace_own_launch_skip(result: object, warnings: list[str]) -> None:
    """Swap core's skip warnings for this package's launch for one notice.

    Core reports the skip once per provider, each time naming a command a tool
    install cannot run. Every such warning is removed from *result* and its
    per-provider outcomes, and :data:`OWN_LAUNCH_UNAPPROVED` is added to
    *warnings* once. Skips of any other source are core's to explain and stay.
    """
    holders: list[object] = [result]
    per_tool: object = getattr(result, "per_tool", None)
    if isinstance(per_tool, dict):
        holders.extend(cast("dict[object, object]", per_tool).values())
    found = False
    for holder in holders:
        raw: object = getattr(holder, "warnings", None)
        if not isinstance(raw, list):
            continue
        messages = cast("list[object]", raw)
        kept = [
            message
            for message in messages
            if not str(message).startswith(_CORE_UNAPPROVED_PREFIX)
        ]
        if len(kept) != len(messages):
            found = True
            messages[:] = kept
    if found and OWN_LAUNCH_UNAPPROVED not in warnings:
        warnings.append(OWN_LAUNCH_UNAPPROVED)
