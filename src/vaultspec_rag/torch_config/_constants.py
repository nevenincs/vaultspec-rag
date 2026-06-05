"""Shared types, constants, enums, and report dataclasses for torch-config.

These are the single source of truth for the canonical cu130 block shape
and the closed action / state / diagnosis vocabularies. The inspection,
mutation, direct-dep, and diagnosis submodules all import from here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from tomlkit.container import OutOfOrderTableProxy
from tomlkit.items import InlineTable, Table

# tomlkit returns ``OutOfOrderTableProxy`` for any ``[tool.X]`` whose
# child tables (``[tool.X.Y]``, ``[tool.X.Z]``) are interleaved with
# unrelated sections - the dominant pyproject.toml shape (e.g.
# ``[tool.uv]``, ``[tool.ruff]``, ``[tool.uv.sources]`` interspersed).
# It implements the same Mapping API we exercise (``get``, ``setdefault``,
# ``__setitem__``, ``__delitem__``, ``__bool__``) but does not subclass
# ``Table``. ``InlineTable`` is the third shape (``sources = { ... }``
# inline form) the reader can encounter at the same surfaces. All
# three expose the same Mapping API; a plain ``isinstance(x, Table)``
# check rejects the others and forces apply / detect onto the wrong
# code path. Treat all three as table-like throughout the module.
#
# ``_TABLE_LIKE_TYPES`` is a plain tuple (no ``Final[tuple[type, ...]]``
# annotation) so static type-checkers (ty/pyright) narrow ``x`` to
# ``Table | OutOfOrderTableProxy | InlineTable`` after
# ``isinstance(x, _TABLE_LIKE_TYPES)``. The matching ``TableLike``
# alias is the union form for return types and parameter annotations.
TableLike = Table | OutOfOrderTableProxy | InlineTable
_TABLE_LIKE_TYPES = (Table, OutOfOrderTableProxy, InlineTable)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


CU130_INDEX_NAME: Final[str] = "pytorch-cu130"
CU130_INDEX_URL: Final[str] = "https://download.pytorch.org/whl/cu130"
CU130_MARKER: Final[str] = "sys_platform == 'linux' or sys_platform == 'win32'"
# Minimum supported torch version. Surfaced in three places: the
# educational comment in :func:`manual_snippet`, the warning text in
# ``commands._maybe_warn_transitive_dep``, and the README's
# direct-dep example. Extracting the value as a single constant keeps
# the three surfaces in lockstep when PyTorch drops a major version.
TORCH_MIN_VERSION: Final[str] = "2.4"
DIRECT_TORCH_REQUIREMENT: Final[str] = f"torch>={TORCH_MIN_VERSION}"
_MANAGED_DIRECT_DEP_KEY: Final[str] = "managed-torch-direct-dependency"


class TorchConfigState(StrEnum):
    """Classification of a ``pyproject.toml`` relative to rag's cu130 block."""

    MISSING = "missing"
    CANONICAL = "canonical"
    CUSTOMISED = "customised"
    NO_PROJECT_FILE = "no_project_file"


class TorchDiagnosis(StrEnum):
    """Classification of a torch install's CUDA support."""

    NO_TORCH = "no_torch"
    CPU_ONLY = "cpu_only"
    NO_GPU = "no_gpu"
    WORKING = "working"


class TorchConfigAction(StrEnum):
    """Closed set of action strings emitted on the install / uninstall
    report's ``torch_config_action`` field.

    The set was historically an open string surface; round-2 audit
    surfaced a JSON-contract gap (the ADR documented 5 values but the
    code emitted 13). Pinning the vocabulary to a ``StrEnum`` makes
    the contract self-documenting and lets static type-checkers catch
    typos. ``StrEnum`` members compare equal to their string value,
    so existing consumers that filter on ``"applied"`` keep working.

    Values:
        APPLIED: cu130 block was just written.
        ALREADY: pyproject is already canonical; nothing to write.
        CONFLICT: a non-canonical cu130 block exists; refused to mutate.
        ABSENT: no pyproject.toml at the target.
        REMOVED: cu130 block was just removed (uninstall side only).
        DISABLED: ``configure_torch=False`` opted out.
        DRY_RUN: dry-run preview, no write.
        DECLINED: user declined the prompt (or a custom confirm hook
            raised an exception we converted to a decline).
        SKIPPED: torch-config step did nothing this run; the report
            field's default before the orchestrator updates it.
        SKIPPED_NON_TTY: non-interactive caller without a confirm hook.
        SKIPPED_EOF: confirmation prompt hit end-of-stream (CI / pipe).
        ERROR: parse or write failure during inspect / patch.
    """

    APPLIED = "applied"
    ALREADY = "already"
    CONFLICT = "conflict"
    ABSENT = "absent"
    REMOVED = "removed"
    DISABLED = "disabled"
    DRY_RUN = "dry_run"
    DECLINED = "declined"
    SKIPPED = "skipped"
    SKIPPED_NON_TTY = "skipped-non-tty"
    SKIPPED_EOF = "skipped-eof"
    ERROR = "error"


@dataclass
class PatchReport:
    """Structured outcome of an apply / remove pass.

    Attributes:
        action: A :class:`TorchConfigAction` member describing the
            outcome (``APPLIED``, ``ALREADY``, ``CONFLICT``,
            ``ABSENT``, ``REMOVED``, or ``SKIPPED`` as the default).
            Subclasses ``str``, so legacy consumers comparing with
            string literals (``action == "applied"``) keep working.
        path: The pyproject.toml inspected.
        conflicts: Human-readable descriptions of conflicting keys
            when ``action == TorchConfigAction.CONFLICT``.
        preview: The TOML snippet that would be (or was) written,
            for dry-run / display purposes.
    """

    action: TorchConfigAction
    path: Path
    conflicts: list[str] = field(default_factory=list)
    preview: str = ""


@dataclass
class DirectTorchDepReport:
    """Structured outcome of managing the direct ``torch`` dependency."""

    action: str
    path: Path
    location: str = ""
    conflicts: list[str] = field(default_factory=list)
