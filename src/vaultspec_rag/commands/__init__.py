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
All such state changes flow through core. See the ADR
``2026-04-12-vaultspec-rag-install-adr`` for the architectural decision.

This module was split into a package (``commands/``) per the
``2026-06-01-module-split-adr``. The verbatim public surface — the two
orchestrators, their report dataclasses, and the ``_classify_uv_sync_result``
helper that tests import directly — is re-exported here unchanged.
"""

from __future__ import annotations

from ._install import install_run
from ._models import InstallReport, UninstallReport
from ._uninstall import uninstall_run
from ._uv_sync import _classify_uv_sync_result

__all__ = [
    "InstallReport",
    "UninstallReport",
    "_classify_uv_sync_result",
    "install_run",
    "uninstall_run",
]
