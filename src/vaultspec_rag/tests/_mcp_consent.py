"""Explicit executable grants for installation tests in an isolated user home.

Also reads back what core then did with them: the sync it plans and the
ownership it recorded.
"""

from __future__ import annotations

from contextvars import Context
from pathlib import Path
from typing import TYPE_CHECKING, Unpack

from vaultspec_core.core.enums import InstallMode, McpScope, Tool
from vaultspec_core.core.mcps import mcp_sync, ownership_path, read_ownership
from vaultspec_core.core.mcps_definitions import collect_mcp_servers
from vaultspec_core.core.mcps_mode import (
    render_definition_for_sync,
    render_mcp_definition_for_mode,
)
from vaultspec_core.core.mcps_native import normalized_sources
from vaultspec_core.core.mcps_targets import resolve_mcp_targets
from vaultspec_core.core.mcps_trust import McpApproval, grant
from vaultspec_core.core.types import SyncResult, init_paths
from vaultspec_core.core.workspace_mode import (
    CORE_DISTRIBUTION_NAME,
    resolve_render_mode,
)

from ..builtins import seed_builtins
from ..commands._install import (
    _InstallRunOptions,
    _InstallRunRequest,
    _planned_launches,
)
from ..commands._mcp_host_state import launches_to_enroll
from ..commands._mcp_topology import inspect_required_mcp_topology
from ..commands._mcp_trust import approvals_for
from ..commands._mode import resolve_rag_mode

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..commands._mcp_host_state import LaunchToEnroll


def dry_sync(root: Path, *, enrolled: Iterable[Tool] | None = None) -> SyncResult:
    """Run core's own sync of *root* as a later invocation would, writing nothing."""
    return Context().run(
        mcp_sync,
        dry_run=True,
        mode=InstallMode.TOOL,
        provider="all",
        scope="project",
        target_dir=root,
        enrolled=enrolled,
    )


def rag_tags(result: SyncResult) -> list[str]:
    """What a sync did with rag's entry on each host, in the order it reached them."""
    return [tag for name, tag in result.items if name == "vaultspec-rag"]


def owned_config_paths(root: Path) -> set[Path]:
    """Return the native config paths core records *root*'s ownership at."""
    targets = read_ownership(ownership_path(root, McpScope.PROJECT))["targets"]
    return {Path(path) for record in targets.values() if (path := record.get("path"))}


def approve_workspace_launches(root: Path, mode: InstallMode | None = None) -> None:
    """Review exact seeded launch bytes; production sync still enforces consent."""
    seed_builtins(root / ".vaultspec")
    context = Context()
    context.run(init_paths, root)
    selected = resolve_rag_mode(root, mode).mode
    digests: dict[Path, str] = {}
    sources = {
        name: (
            path,
            render_mcp_definition_for_mode(definition, selected)
            if name == "vaultspec-rag"
            else render_definition_for_sync(definition, selected, root),
        )
        for name, (path, definition) in context.run(
            collect_mcp_servers, target=root, digests=digests
        ).items()
    }
    targets = context.run(
        resolve_mcp_targets,
        "all",
        target_dir=root,
        enrolled=(Tool.CLAUDE, Tool.CODEX),
    )
    approvals: list[McpApproval] = []
    for target in targets:
        result = SyncResult()
        for name, (path, config) in normalized_sources(sources, target, result).items():
            approvals.append(
                McpApproval.capture(root, target, name, path, config, digests[path])
            )
        assert not result.errors, result.errors
    assert approvals, "the test must approve a real executable definition"
    grant(approvals)


def grant_planned(authority: Path, launches: Iterable[LaunchToEnroll]) -> None:
    """Grant *launches* at *authority*'s own paths, as an operator reviewing them."""
    grant(approvals_for(authority, launches))


def grant_launches(
    authority: Path,
    work: Path,
    *,
    mode: InstallMode,
    enrolled: Iterable[Tool] | None,
) -> None:
    """Grant, for *authority*'s paths, every launch a sync of *work* would enroll."""
    grant_planned(
        authority,
        Context().run(
            launches_to_enroll, authority, work, mode=mode, enrolled=enrolled
        ),
    )


def approve_core_launches(root: Path) -> None:
    """Approve every launch core's own sync will enroll from *root*'s sources.

    The sources are already in place, so nothing is projected: the launches are
    rendered exactly as core renders them for *root*, and approval is a real
    grant in the user's home.
    """
    mode = resolve_render_mode(root, package=CORE_DISTRIBUTION_NAME)
    grant_launches(root, root, mode=mode, enrolled=None)


def approve_install_launches(root: Path, **options: Unpack[_InstallRunOptions]) -> None:
    """Approve what an install of *root* is about to enroll, as an operator would.

    Takes the options the install itself is about to run with. An operator
    reviews the launches an install leaves behind and approves them before the
    sync that enrolls them, with core's own trust command. The launches an
    install will leave are whatever its own plan holds after seeding, so they
    are read from that plan rather than guessed, and nothing is written into
    *root*. Approval is a real grant in the user's home; production sync still
    enforces it, so a launch not approved here is skipped exactly as it would be.
    """
    skipped = options.get("skip") or set()
    if {"core", "mcp"} & skipped:
        return
    try:
        inspect_required_mcp_topology(root)
    except OSError:
        # The install runs this same preflight first and refuses an unsafe
        # topology before any launch is enrolled, so there is nothing to approve.
        return
    grant_planned(
        root, _planned_launches(_InstallRunRequest(path=root, **options), root)
    )
