"""Detect, write, and remove the canonical cu130 torch block in a user's
``pyproject.toml``.

This package is the pure-logic layer for rag's ``install`` /
``uninstall`` torch-config step. It mirrors the per-resource module
pattern core follows for ``gitignore.py`` / ``gitattributes.py`` /
``mcps.py``: no Typer, no Rich, no prompts, no process side-effects
beyond a single atomic write.

Canonical block shape - see :func:`manual_snippet` for the exact
bytes rag emits (three module constants compose the shape).

The three module-level constants are the single source of truth for
that shape - apply and remove compare against them, and
``manual_snippet`` renders them verbatim. Symmetric apply/remove is
guaranteed by construction.

This module was split into a package (``torch_config/``) per the
``2026-06-01-module-split-adr``: shared constants / enums / report
dataclasses in ``_constants``, TOML inspection + classification in
``_inspect``, mutation + the canonical-snippet builder in ``_mutate``,
direct-dep management in ``_direct_dep``, and install diagnosis in
``_diagnose``. The verbatim public surface - plus the
``_is_torch_requirement`` helper tests import directly via the module
alias - is re-exported here unchanged so no caller or test edit is
required.

See :doc:`.vault/adr/2026-04-22-install-cuda-adr` for the
torch-config architectural decision.
"""

from __future__ import annotations

from ._constants import (
    CU130_INDEX_NAME,
    CU130_INDEX_URL,
    CU130_MARKER,
    DIRECT_TORCH_REQUIREMENT,
    TORCH_MIN_VERSION,
    DirectTorchDepReport,
    PatchReport,
    TorchConfigAction,
    TorchConfigState,
    TorchDiagnosis,
)
from ._diagnose import diagnose_torch
from ._direct_dep import (
    _is_torch_requirement,  # pyright: ignore[reportPrivateUsage]  # test-facing re-export of intra-package helper
    ensure_direct_torch_dep,
    has_direct_torch_dep,
    remove_managed_direct_torch_dep,
)
from ._inspect import detect_state
from ._mutate import (
    apply_patch,
    manual_snippet,
    preview_patch,
    remove_patch,
)

__all__ = [
    "CU130_INDEX_NAME",
    "CU130_INDEX_URL",
    "CU130_MARKER",
    "DIRECT_TORCH_REQUIREMENT",
    "TORCH_MIN_VERSION",
    "DirectTorchDepReport",
    "PatchReport",
    "TorchConfigAction",
    "TorchConfigState",
    "TorchDiagnosis",
    "_is_torch_requirement",
    "apply_patch",
    "detect_state",
    "diagnose_torch",
    "ensure_direct_torch_dep",
    "has_direct_torch_dep",
    "manual_snippet",
    "preview_patch",
    "remove_managed_direct_torch_dep",
    "remove_patch",
]
