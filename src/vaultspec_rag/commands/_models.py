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
from typing import TYPE_CHECKING, Any, cast

from ..torch_config import TorchConfigAction

if TYPE_CHECKING:
    from pathlib import Path

    from ._provision import ProvisionOutcome

ConfirmFn = Callable[[str], bool]

__all__ = [
    "ConfirmFn",
    "InstallReport",
    "UninstallReport",
]

_SYNC_COUNTERS = (
    "added",
    "updated",
    "unchanged",
    "skipped",
    "pruned",
    "errored",
)


def _empty_provider_outcome() -> dict[str, Any]:
    return {
        **dict.fromkeys(_SYNC_COUNTERS, 0),
        "errors": [],
        "warnings": [],
        "items": [],
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in cast("list[object]", value)]


def _sync_items(value: object) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    normalised: list[list[str]] = []
    for item in cast("list[object]", value):
        if not isinstance(item, tuple):
            continue
        parts = cast("tuple[object, ...]", item)  # ty: ignore[redundant-cast]
        if len(parts) != 2:
            continue
        path, action = parts
        if isinstance(path, str) and isinstance(action, str):
            normalised.append([path, action])
    return normalised


def _merge_provider_outcome(outcome: dict[str, Any], provider_result: object) -> None:
    for counter in _SYNC_COUNTERS:
        value = getattr(provider_result, counter, 0)
        if isinstance(value, int):
            outcome[counter] += value
    outcome["errors"].extend(_string_list(getattr(provider_result, "errors", [])))
    outcome["warnings"].extend(_string_list(getattr(provider_result, "warnings", [])))
    outcome["items"].extend(_sync_items(getattr(provider_result, "items", [])))


def _provider_sync_outcomes(results: list[Any]) -> dict[str, dict[str, Any]]:
    """Aggregate Core's typed ``per_tool`` results without flattening hosts."""
    outcomes: dict[str, dict[str, Any]] = {}
    for result in results:
        per_tool = getattr(result, "per_tool", None)
        if not isinstance(per_tool, dict):
            continue
        for provider, provider_result in cast("dict[object, object]", per_tool).items():
            if not isinstance(provider, str):
                continue
            outcome = outcomes.setdefault(provider, _empty_provider_outcome())
            _merge_provider_outcome(outcome, provider_result)
    return {provider: outcomes[provider] for provider in sorted(outcomes)}


@dataclass
class InstallReport:
    """Structured result of an install run.

    Attributes:
        action: One of ``"install"``, ``"upgrade"``, ``"dry_run"``.
        target: Resolved workspace path.
        created_dirs: Workspace-relative directories rag ensured exist.
        seeded: ``(relative_path, action)`` pairs for each bundled file the seed
            acted on, ``action`` in ``[ADD]`` / ``[UPDATE]`` / ``[UNCHANGED]`` -
            the same shape core's seeder returns. Paths fold flat into
            ``.vaultspec/`` (``rules/`` / ``mcps/`` / ``skills/``).
        sync_results: ``SyncResult`` objects returned by core's
            ``sync_provider`` (one per sync pass).
        warnings: Non-fatal warnings collected during the run.
    """

    action: str
    target: Path
    created_dirs: list[str] = field(default_factory=list)
    seeded: list[tuple[str, str]] = field(default_factory=list)
    sync_results: list[Any] = field(default_factory=list)
    mcp_sync_results: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    torch_config_action: TorchConfigAction = TorchConfigAction.SKIPPED
    torch_config_conflicts: list[str] = field(default_factory=list)
    torch_direct_dep_action: str = "skipped"
    torch_direct_dep_location: str = ""
    torch_sync_action: str = "skipped"
    # Whether install ensured the optional ``[mcp]`` extra (the MCP server's
    # dependency). ``skipped`` when ``--no-mcp`` was passed; otherwise the
    # ``uv add vaultspec-rag[mcp]`` outcome (``succeeded`` / ``failed`` /
    # ``uv-not-found`` / ``would-add`` for a dry run).
    mcp_extra_action: str = "skipped"
    # Heterogeneous per-dependency provisioning outcome from the unified
    # front door (``provision_dependencies``). ``None`` when provisioning
    # did not run (e.g. ``provision=False``); otherwise carries one result
    # per considered dependency for the renderer to surface honestly,
    # including torch's two-phase "configured, sync pending" state.
    provision_outcome: ProvisionOutcome | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": str(self.target),
            "created_dirs": list(self.created_dirs),
            "seeded": [[rel, action] for rel, action in self.seeded],
            "sync_added": sum(getattr(r, "added", 0) for r in self.sync_results),
            "sync_updated": sum(getattr(r, "updated", 0) for r in self.sync_results),
            "sync_pruned": sum(getattr(r, "pruned", 0) for r in self.sync_results),
            "sync_providers": _provider_sync_outcomes(self.mcp_sync_results),
            "warnings": list(self.warnings),
            "torch_config_action": self.torch_config_action,
            "torch_config_conflicts": list(self.torch_config_conflicts),
            "torch_direct_dep_action": self.torch_direct_dep_action,
            "torch_direct_dep_location": self.torch_direct_dep_location,
            "torch_sync_action": self.torch_sync_action,
            "mcp_extra_action": self.mcp_extra_action,
            "provisioning": (
                self.provision_outcome.to_dict()
                if self.provision_outcome is not None
                else None
            ),
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
    mcp_sync_results: list[Any] = field(default_factory=list)
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
            "sync_providers": _provider_sync_outcomes(self.mcp_sync_results),
            "warnings": list(self.warnings),
            "torch_config_action": self.torch_config_action,
            "torch_config_conflicts": list(self.torch_config_conflicts),
            "torch_direct_dep_action": self.torch_direct_dep_action,
            "torch_direct_dep_location": self.torch_direct_dep_location,
        }
