"""The operator's approval of vaultspec-rag's own MCP launch, obtained at install.

Core refuses to enrol an MCP launch until the operator has reviewed the exact
definition, command, arguments and environment and approved them at a terminal
(``vaultspec-core spec mcps trust``). No flag stands in for that review, so an
install that never asked would seed the definition and then skip the
enrolment. This module asks, for exactly vaultspec-rag's own definition and no
other source, and records the answer through core's own grant.

"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

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

__all__ = ["approvals_for", "review_rag_launch"]

#: What a failed read or write of the approval record can raise.
_GRANT_FAILURES = (OSError, VaultSpecError)


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


def review_rag_launch(
    root: Path,
    planned: Iterable[LaunchToEnroll],
    *,
    confirm: ConfirmFn | None,
    assume_yes: bool,
) -> list[str]:
    """Ask the operator to approve vaultspec-rag's own launch, then record it.

    Only the definition named for this package is considered; every other
    source stays the operator's to approve with core. Nobody is asked when
    there is nobody to ask (*confirm* is ``None``) or when the run was told to
    assume consent (*assume_yes*): a flag is not a review, and core's own sync
    then skips the launch with the command that grants it.

    Returns:
        The operator-facing problems met while asking or recording, if any.
    """
    own = [launch for launch in planned if launch.name == RAG_DISTRIBUTION_NAME]
    approved = approved_launches(own, root)
    missing = [launch for launch in own if launch not in approved]
    if not missing or confirm is None or assume_yes:
        return []
    outcome = confirmation_outcome(
        confirm, _review_prompt(approvals_for(root, missing))
    )
    if outcome.startswith("error:"):
        return [f"MCP approval could not be asked of the operator ({outcome})."]
    if outcome != "approved":
        return []
    try:
        grant(approvals_for(root, missing))
    except _GRANT_FAILURES as exc:
        return [f"MCP approval could not be recorded: {exc}"]
    return []
