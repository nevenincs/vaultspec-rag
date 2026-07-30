"""Provisioning-mode resolution and persistence for rag's install flow.

Vaultspec-rag adopts the three-placement mode model (``tool`` / ``dependency``
/ ``dev``) that vaultspec-core owns, calling into core's ``workspace_mode``
module with ``package="vaultspec-rag"`` rather than reimplementing precedence,
detection, or the shared per-package ``.vaultspec/workspace.json`` declaration.
This module is the thin rag-side seam that threads that shared machinery through
rag's own install path: it resolves rag's mode through core's precedence
chain, persists rag's own entry in the shared declaration without disturbing
core's sibling entry, and re-renders rag's MCP server entry to its own declared
mode's launch shape.

Everything mode-related routes through a single core comparator. Detection,
precedence, the leak advisory predicate, and the launch renderer all live in
core; this module only names ``vaultspec-rag`` as the package the shared
machinery operates on, so rag and core cannot drift on what a mode means.
"""

from __future__ import annotations

import logging
from contextvars import Context
from typing import TYPE_CHECKING, cast

from vaultspec_core.core.enums import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    InstallMode,
)
from vaultspec_core.core.mcps import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    mcp_status,
    mcp_sync,
)
from vaultspec_core.core.workspace_mode import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    ModeProvenance,
    PackageDeclaration,
    ResolvedMode,
    read_package_declaration,
    resolve_install_mode,
    resolve_install_mode_with_provenance,
    write_package_declaration,
)

if TYPE_CHECKING:
    from pathlib import Path

    from vaultspec_core.core.types import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
        SyncResult,
    )

logger = logging.getLogger(__name__)

#: The distribution name rag declares its own entry under in the shared
#: per-package ``.vaultspec/workspace.json`` map. Passed as the ``package``
#: argument to every core ``workspace_mode`` call so rag resolves, persists, and
#: renders its own entry and never core's sibling entry.
RAG_DISTRIBUTION_NAME = "vaultspec-rag"

#: The runnable module rag's MCP server launches as ``python -m``. Matches the
#: ``_vaultspec_mode_module`` token in rag's mode-neutral MCP builtin so the
#: observed-shape matcher and the renderer reconstruct the same launch.
RAG_MCP_MODULE = "vaultspec_rag.server"


def resolve_rag_mode(target: Path, explicit: InstallMode | None) -> ResolvedMode:
    """Resolve rag's provisioning mode through core's precedence chain.

    The fresh-``install`` resolver: it defers entirely to core's
    :func:`~vaultspec_core.core.workspace_mode.resolve_install_mode_with_provenance`
    with ``package="vaultspec-rag"``, so an explicit ``--mode`` flag, rag's own
    persisted declaration, ``pyproject.toml`` detection for the rag
    distribution, and the tool-mode default all apply in the same order core
    uses for its own package. The returned provenance drives the leak advisory
    at the moment of choice.

    Args:
        target: Workspace root directory.
        explicit: The mode requested via ``--mode``, or ``None``.

    Returns:
        The resolved mode paired with its provenance.

    Raises:
        VaultSpecError: Propagated from core when *explicit* names an
            impossible combination (dependency/dev mode with no
            ``pyproject.toml``) or a persisted declaration is malformed.
    """
    return resolve_install_mode_with_provenance(
        target, explicit=explicit, package=RAG_DISTRIBUTION_NAME
    )


def infer_rag_upgrade_mode(
    target: Path,
    explicit: InstallMode | None,
    *,
    allow_mcp_status: bool = True,
) -> ResolvedMode:
    """Infer rag's provisioning mode for an ``install --upgrade``.

    Mirrors core's ``_infer_upgrade_mode`` precedence exactly, substituting
    rag's own deployed artifact for core's: an explicit ``--mode`` flag wins
    (and is validated for impossible combinations), an already-persisted rag
    declaration wins next so a second upgrade is idempotent, and a legacy
    workspace with neither has its mode inferred from its own deployed state.
    Rag has no pre-commit hook to read, so its deployed-state signal is the
    observed shape of its own ``.mcp.json`` server entry
    (:func:`~vaultspec_core.core.diagnosis.collectors.observed_mcp_mode` for
    ``vaultspec-rag``): dependency mode only when that launch is
    ``uv run``-shaped *and* the target's ``pyproject.toml`` lists
    ``vaultspec-rag``; tool mode in every other case.

    Reading the observed shape through core's shared collector keeps rag's
    migration and any diagnosis in agreement on what a deployed launch shape
    means: everything routes through one core comparator, so rag and core
    cannot drift on what a deployed launch shape means.

    Args:
        target: Workspace root directory.
        explicit: The mode requested via ``--mode``, or ``None``.
        allow_mcp_status: Whether legacy inference may inspect native MCP deployment
            state. Component-skipped installs disable this and use only durable
            declaration or package-placement evidence.

    Returns:
        The inferred mode paired with its provenance.

    Raises:
        VaultSpecError: Propagated from core when *explicit* names an
            impossible combination or a persisted declaration is malformed.
    """
    if explicit is not None:
        return resolve_install_mode_with_provenance(
            target, explicit=explicit, package=RAG_DISTRIBUTION_NAME
        )
    if read_package_declaration(target, RAG_DISTRIBUTION_NAME) is not None:
        return resolve_install_mode_with_provenance(
            target, explicit=None, package=RAG_DISTRIBUTION_NAME
        )

    detected = resolve_install_mode(
        target, explicit=None, package=RAG_DISTRIBUTION_NAME
    )
    # Any deployed provider is evidence of the legacy mode: a pre-dual
    # workspace could only ever enroll the one provider that existed, so
    # requiring every provider would misread it as tool mode.
    if detected in {InstallMode.DEPENDENCY, InstallMode.DEV} and (
        not allow_mcp_status or mode_is_deployed(target, require_all=False)
    ):
        return ResolvedMode(detected, ModeProvenance.INFERRED)
    return ResolvedMode(InstallMode.TOOL, ModeProvenance.INFERRED)


def mode_is_deployed(target: Path, *, require_all: bool = True) -> bool:
    from vaultspec_core.core.enums import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
        Tool,
    )

    status = Context().run(
        lambda: cast(
            "dict[str, object]",
            mcp_status(provider="all", scope="project", target_dir=target),
        )
    )
    providers = status.get("providers")
    if not isinstance(providers, dict) or not providers:
        enrolled: list[Tool] = []
        if (target / ".mcp.json").exists():
            enrolled.append(Tool.CLAUDE)
        if (target / ".codex" / "config.toml").exists():
            enrolled.append(Tool.CODEX)
        if not enrolled:
            return False
        status = Context().run(
            lambda: cast(
                "dict[str, object]",
                mcp_status(
                    provider="all",
                    scope="project",
                    target_dir=target,
                    enrolled=enrolled,
                ),
            )
        )
        providers = status.get("providers")
    if not isinstance(providers, dict) or not providers:
        return False
    states: list[tuple[set[str], set[str], set[str]]] = []
    for state_value in cast("dict[str, object]", providers).values():
        if not isinstance(state_value, dict):
            return False
        state = cast("dict[str, object]", state_value)
        managed = _status_names(state.get("managed"))
        missing = _status_names(state.get("missing"))
        drifted = _status_names(state.get("drifted"))
        states.append((managed, missing, drifted))
    if require_all:
        return all(
            RAG_DISTRIBUTION_NAME in managed
            and RAG_DISTRIBUTION_NAME not in missing
            and RAG_DISTRIBUTION_NAME not in drifted
            for managed, missing, drifted in states
        )
    return any(
        RAG_DISTRIBUTION_NAME in managed or RAG_DISTRIBUTION_NAME in drifted
        for managed, _missing, drifted in states
    )


def _status_names(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in cast("list[object]", value) if isinstance(item, str)}


def persist_rag_mode(target: Path, mode: InstallMode) -> None:
    """Write rag's committed mode entry, preserving its floor and any siblings.

    Reads and writes only ``vaultspec-rag``'s own entry in the shared
    per-package map through core's
    :func:`~vaultspec_core.core.workspace_mode.write_package_declaration`, whose
    read-modify-write under the advisory lock leaves every sibling entry (a
    ``vaultspec-core`` declaration provisioned into the same workspace) untouched.
    A per-package ``minimum_version`` floor a prior run recorded is read back and
    preserved, since the provisioning mode and the floor are independent axes of
    the same entry.

    Args:
        target: Workspace root directory.
        mode: The resolved provisioning mode to persist for ``vaultspec-rag``.
    """
    existing = read_package_declaration(target, RAG_DISTRIBUTION_NAME)
    floor = existing.minimum_version if existing is not None else None
    write_package_declaration(
        target,
        RAG_DISTRIBUTION_NAME,
        PackageDeclaration(install_mode=mode, minimum_version=floor),
    )


def migrate_rag_mcp_entry(mode: InstallMode) -> SyncResult:
    """Force rag's already-managed MCP entry into *mode*'s launch shape.

    The mode-flip seam, the direct analogue of core's own force-managed pass in
    ``commands.py``. From the ``0.1.44`` floor core's ``sync_provider`` renders
    every companion MCP definition at *its own* declaring package's committed
    mode (rag's entry names ``vaultspec-rag`` through the ``_vaultspec_mode_package``
    token), so a fresh install and a same-mode re-install already write rag's
    ``.mcp.json`` entry in rag's own shape natively - no re-render needed. The one
    gap the native sync leaves is an ``install --upgrade`` that *flips* rag's
    mode without ``--force``: the plain sync's force-gate skips the
    already-managed rag entry still carrying the old mode's launch shape. This
    closes that gap by re-running core's
    :func:`~vaultspec_core.core.mcps.mcp_sync` at rag's resolved *mode* while
    scoping the overwrite to rag's own managed entry via ``force_managed``, so
    any sibling ``vaultspec-core`` entry that differs is left exactly as core's
    own sync wrote it. It must run after core's context is established (the sync
    pass) and is a no-op when rag's entry already matches *mode*.

    The returned sync statistics are intentionally discarded: the only surface
    this touches is rag's own entry, and a benign "sibling entry differs" skip
    on the ``vaultspec-core`` entry is expected, not an install warning.

    Args:
        mode: The provisioning mode whose launch shape rag's entry should carry.
    """
    return mcp_sync(
        mode=mode,
        force_managed=frozenset({RAG_DISTRIBUTION_NAME}),
        provider="all",
        scope="project",
    )
