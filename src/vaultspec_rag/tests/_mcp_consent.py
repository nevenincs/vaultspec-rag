"""Explicit executable grants for installation tests in an isolated user home."""

from __future__ import annotations

from contextvars import Context
from typing import TYPE_CHECKING, Unpack

from vaultspec_core.core.enums import Tool
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
    _mcp_preview_projection,
    _requested_fresh_mcp_providers,
    _resolve_install_mode,
)
from ..commands._mcp_host_state import launches_to_enroll
from ..commands._mcp_topology import inspect_required_mcp_topology
from ..commands._mode import resolve_rag_mode

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from vaultspec_core.core.enums import InstallMode


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


def grant_launches(
    authority: Path,
    work: Path,
    *,
    mode: InstallMode,
    enrolled: Iterable[Tool] | None,
) -> None:
    """Grant, for *authority*'s paths, every launch a sync of *work* would enroll."""
    launches = Context().run(
        launches_to_enroll, authority, work, mode=mode, enrolled=enrolled
    )
    grant(
        [
            McpApproval.capture(
                authority,
                launch.authority_target,
                launch.name,
                launch.authority_path,
                launch.config,
                launch.digest,
            )
            for launch in launches
        ]
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
    sync that enrolls them. The launches an install will leave are whatever its
    own projection holds after seeding, so they are read from that projection
    rather than guessed, and nothing is written into *root*. Approval is a real
    grant in the user's home; production sync still enforces it, so a launch
    not approved here is skipped exactly as it would be.
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
    upgrade = options.get("upgrade", False)
    resolved = _resolve_install_mode(
        root, options.get("mode"), upgrade=upgrade, skip=skipped
    ).mode
    with _mcp_preview_projection(
        root,
        install_mcp=options.get("install_mcp", False),
        force=options.get("force", False),
        upgrade=upgrade,
        mode=resolved,
    ) as projection:
        grant_launches(
            root,
            projection,
            mode=resolved,
            enrolled=_requested_fresh_mcp_providers(root, skipped),
        )
