"""Explicit executable grants for installation tests in an isolated user home."""

from __future__ import annotations

from contextvars import Context
from typing import TYPE_CHECKING

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

from ..builtins import seed_builtins
from ..commands._mode import resolve_rag_mode

if TYPE_CHECKING:
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
