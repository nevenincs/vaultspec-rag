"""Top-level orchestration for ``vaultspec-rag install`` and ``uninstall``.

This package is the orchestration layer for rag's enrollment commands.
It mirrors the role of :mod:`vaultspec_core.core.commands` in core: thin
public functions that own the install/uninstall flow, importable
independently of Typer so the CLI wrapper in :mod:`vaultspec_rag.cli`
stays trivial and integration tests can drive the flow directly.

Both commands are pure mirrors of each other:

- ``install_run`` seeds rag's bundled builtin source files into the
  workspace's ``.vaultspec/rules/`` directories and then invokes core's
  ``sync_provider`` to propagate them to ``.mcp.json`` and provider dirs.
- ``uninstall_run`` removes the same source files and then invokes the
  same ``sync_provider`` to propagate the removal. Pruning of the
  resulting orphans depends on vaultspec-core 0.1.10+'s reconciling
  ``mcp_sync``.

rag never reads or writes shared repository files (``.gitignore``,
``.gitattributes``, ``.mcp.json``, manifest, provider dirs) directly.
All such state changes flow through core.

This module was split into a package (``commands/``) from a former monolith.
The verbatim public surface - the two
orchestrators and their report dataclasses - is re-exported here unchanged.
"""

from __future__ import annotations

from ._install import install_run
from ._models import InstallReport, UninstallReport
from ._provision import (
    ProvisionAction,
    ProvisionOutcome,
    ProvisionStep,
    ProvisionStepResult,
    provision_dependencies,
    provision_models,
)
from ._uninstall import uninstall_run

__all__ = [
    "InstallReport",
    "ProvisionAction",
    "ProvisionOutcome",
    "ProvisionStep",
    "ProvisionStepResult",
    "UninstallReport",
    "install_run",
    "provision_dependencies",
    "provision_models",
    "uninstall_run",
]
