"""Workspace layout resolution for vaultspec-rag.

Thin re-export shim over :mod:`vaultspec_core.config.workspace`. RAG previously
maintained a parallel implementation; it is now delegated to core so the two
packages cannot silently diverge.
"""

from __future__ import annotations

from vaultspec_core.config.workspace import (
    GitInfo,
    LayoutMode,
    WorkspaceError,
    WorkspaceLayout,
    discover_git,
    resolve_workspace,
)

__all__ = [
    "GitInfo",
    "LayoutMode",
    "WorkspaceError",
    "WorkspaceLayout",
    "discover_git",
    "resolve_workspace",
]
