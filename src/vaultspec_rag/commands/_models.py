"""Report dataclasses and shared constants for the enrollment commands.

Holds the structured result types (:class:`InstallReport`,
:class:`UninstallReport`), the ``ConfirmFn`` callback alias, and the
relative paths of the bundled rag enrollment artefacts. Defined here
once so install and uninstall stay symmetric and tests can assert
against a single source of truth.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..torch_config import TorchConfigAction

ConfirmFn = Callable[[str], bool]


# Names of the bundled rag enrollment artefacts (relative to
# ``.vaultspec/rules/``). Defined here once so install and uninstall
# stay symmetric and tests can assert against a single source of truth.
_RAG_RULE_REL_PATH = Path("rules") / "vaultspec-rag.builtin.md"
_RAG_MCP_REL_PATH = Path("mcps") / "vaultspec-rag.builtin.json"


@dataclass
class InstallReport:
    """Structured result of an install run.

    Attributes:
        action: One of ``"install"``, ``"upgrade"``, ``"dry_run"``.
        target: Resolved workspace path.
        created_dirs: Workspace-relative directories rag ensured exist.
        seeded: Workspace-relative paths of bundled files seeded.
        sync_results: ``SyncResult`` objects returned by core's
            ``sync_provider`` (one per sync pass).
        warnings: Non-fatal warnings collected during the run.
    """

    action: str
    target: Path
    created_dirs: list[str] = field(default_factory=list)
    seeded: list[str] = field(default_factory=list)
    sync_results: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    torch_config_action: TorchConfigAction = TorchConfigAction.SKIPPED
    torch_config_conflicts: list[str] = field(default_factory=list)
    torch_direct_dep_action: str = "skipped"
    torch_direct_dep_location: str = ""
    torch_sync_action: str = "skipped"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": str(self.target),
            "created_dirs": list(self.created_dirs),
            "seeded": list(self.seeded),
            "sync_added": sum(getattr(r, "added", 0) for r in self.sync_results),
            "sync_updated": sum(getattr(r, "updated", 0) for r in self.sync_results),
            "sync_pruned": sum(getattr(r, "pruned", 0) for r in self.sync_results),
            "warnings": list(self.warnings),
            "torch_config_action": self.torch_config_action,
            "torch_config_conflicts": list(self.torch_config_conflicts),
            "torch_direct_dep_action": self.torch_direct_dep_action,
            "torch_direct_dep_location": self.torch_direct_dep_location,
            "torch_sync_action": self.torch_sync_action,
        }


@dataclass
class UninstallReport:
    """Structured result of an uninstall run.

    Attributes:
        action: One of ``"uninstall"``, ``"dry_run"``.
        target: Resolved workspace path.
        removed: Workspace-relative paths of source files rag deleted.
        data_removed: True when ``--remove-data`` purged
            ``.vault/data/``.
        sync_results: ``SyncResult`` objects from the propagation pass.
        warnings: Non-fatal warnings collected during the run.
    """

    action: str
    target: Path
    removed: list[str] = field(default_factory=list)
    data_removed: bool = False
    sync_results: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    torch_config_action: TorchConfigAction = TorchConfigAction.SKIPPED
    torch_config_conflicts: list[str] = field(default_factory=list)
    torch_direct_dep_action: str = "skipped"
    torch_direct_dep_location: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": str(self.target),
            "removed": list(self.removed),
            "data_removed": self.data_removed,
            "sync_pruned": sum(getattr(r, "pruned", 0) for r in self.sync_results),
            "warnings": list(self.warnings),
            "torch_config_action": self.torch_config_action,
            "torch_config_conflicts": list(self.torch_config_conflicts),
            "torch_direct_dep_action": self.torch_direct_dep_action,
            "torch_direct_dep_location": self.torch_direct_dep_location,
        }
