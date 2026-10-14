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
already approved at its real location, whichever definition it came from, and
it matches nothing once the link is back.

Core keys which entries it owns by the same resolved path, so the ownership of
a linked native config travels the same way: to the copy for the run, and back
to the real location before the install commits or rolls back.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from vaultspec_core.core.exceptions import VaultSpecError
from vaultspec_core.core.mcps_trust import McpApproval, grant

from ._mcp_host_state import OwnershipCarry, approved_launches
from ._mode import RAG_DISTRIBUTION_NAME
from ._util import confirmation_outcome

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable
    from pathlib import Path

    from ._mcp_host_state import LaunchToEnroll
    from ._models import ConfirmFn

__all__ = ["LaunchConsent", "approvals_for", "review_rag_launch"]

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


@dataclass(slots=True)
class LaunchConsent:
    """What the operator has approved of the launches an install will enrol."""

    root: Path
    #: The launches approved at their real locations, before or by this review.
    approved: list[LaunchToEnroll] = field(default_factory=list)
    #: The approval keys recorded for *approved*, at those real locations.
    recorded: frozenset[str] = frozenset()
    #: Core's ownership of the native configs this run syncs.
    ownership: OwnershipCarry = field(init=False)
    #: Operator-facing problems met while asking or recording.
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.ownership = OwnershipCarry(self.root)

    @contextmanager
    def carried_into_transaction(self) -> Generator[None]:
        """Carry the host-local state to where this run holds it, and back.

        Enter once the run's links are materialized and before its sync. Each
        approved launch is recorded where the run holds it when that differs
        from where it is recorded, which writes nothing for a workspace with no
        link in the way, and stays there matching nothing once the link is back.
        Ownership moves to the copies and returns to the real locations on the
        way out, whether the run finished or failed, so that rollback finds it
        where the replay expects it.
        """
        self._carry_approvals()
        held = self._hold_ownership()
        try:
            yield
        finally:
            if held:
                self._release_ownership()

    def _carry_approvals(self) -> None:
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

    def _hold_ownership(self) -> bool:
        try:
            self.ownership.hold()
        except OSError as exc:
            self.warnings.append(
                f"MCP ownership could not be carried into this install: {exc}"
            )
            return False
        return True

    def _release_ownership(self) -> None:
        try:
            self.ownership.release()
        except OSError as exc:
            self.warnings.append(
                "MCP ownership could not be returned to the real location of "
                f"a linked config: {exc}"
            )


def review_rag_launch(
    root: Path,
    planned: Iterable[LaunchToEnroll],
    *,
    confirm: ConfirmFn | None,
    assume_yes: bool,
) -> LaunchConsent:
    """Ask the operator to approve vaultspec-rag's own launch, then record it.

    Only the definition named for this package is put to the operator; every
    other source stays theirs to approve with core, and one already approved
    is carried along unchanged. Nobody is asked when there is nobody to ask
    (*confirm* is ``None``) or when the run was told to assume consent
    (*assume_yes*): a flag is not a review, and core's own sync then skips the
    launch with the command that grants it.
    """
    planned = list(planned)
    own = [launch for launch in planned if launch.name == RAG_DISTRIBUTION_NAME]
    consent = LaunchConsent(root)
    consent.ownership.capture(planned)
    approved = approved_launches(planned, root)
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
                approved = [*approved, *missing]
    consent.approved = approved
    consent.recorded = frozenset(
        approval.key for approval in approvals_for(root, approved)
    )
    return consent
