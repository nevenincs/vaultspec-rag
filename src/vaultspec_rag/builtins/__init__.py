"""Bundled builtin resources deployed during ``vaultspec-rag install``.

Contains the canonical rule (``vaultspec-rag.builtin.md``) and MCP server
definition (``vaultspec-rag.builtin.json``) seeded into ``.vaultspec/rules/``
on first install. Consumed by :mod:`vaultspec_rag.commands` via
:func:`seed_builtins` and :func:`list_builtins`. Uses
:mod:`importlib.resources` for package-relative file access.

Unlike :mod:`vaultspec_core.builtins` (which bundles a recursive tree of
core-owned content), rag bundles only the two files it exclusively owns.
The list lives in :data:`_BUNDLED_FILES` as the single source of truth so
the manifest is identical between editable and wheel builds.
"""

from __future__ import annotations

import logging
import shutil
from importlib import resources
from pathlib import Path

logger = logging.getLogger(__name__)

# The exact set of relative paths (under ``.vaultspec/rules/``) that
# vaultspec-rag owns and seeds during install. Each entry must match
# both the wheel ``force-include`` mapping in ``pyproject.toml`` and
# the source location under ``.vaultspec/rules/`` in the repo.
_BUNDLED_FILES: tuple[str, ...] = (
    "rules/vaultspec-rag.builtin.md",
    "mcps/vaultspec-rag.builtin.json",
)


def _builtins_root() -> Path:
    """Return the filesystem path to the bundled builtins directory.

    For installed (wheel) builds the content lives alongside this module
    under ``vaultspec_rag/builtins/`` (laid down by hatch
    ``force-include``). For editable / development installs the content
    is not copied into ``src/``; instead we resolve the canonical
    ``.vaultspec/rules/`` directory at the repository root.
    """
    pkg_dir = Path(str(resources.files(__package__)))

    # Wheel build: at least one of the bundled files lives under pkg_dir.
    if any((pkg_dir / rel).is_file() for rel in _BUNDLED_FILES):
        return pkg_dir

    # Editable install — walk up to the repo root and use the canonical
    # source directly. The repo root is identified by ``pyproject.toml``.
    candidate = pkg_dir
    for _ in range(10):
        candidate = candidate.parent
        if (candidate / "pyproject.toml").is_file():
            rules = candidate / ".vaultspec" / "rules"
            if rules.is_dir():
                return rules
            break

    # Fallback: return the package directory regardless.
    return pkg_dir


def seed_builtins(target_rules_dir: Path, *, force: bool = False) -> list[str]:
    """Copy bundled builtins into a target ``.vaultspec/rules/`` directory.

    Only copies files that don't already exist unless *force* is ``True``.
    Iterates the explicit :data:`_BUNDLED_FILES` manifest so editable and
    wheel installs both seed exactly the same set.

    Args:
        target_rules_dir: The ``.vaultspec/rules/`` directory to populate.
        force: Overwrite existing files.

    Returns:
        Sorted list of relative paths (forward-slash separated) that were
        actually written.
    """
    src_root = _builtins_root()
    written: list[str] = []

    for rel in _BUNDLED_FILES:
        src_file = src_root / rel
        if not src_file.is_file():
            logger.warning("Bundled file missing at source: %s", src_file)
            continue

        dest = target_rules_dir / rel
        if dest.exists() and not force:
            continue

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)
        except OSError as exc:
            logger.warning("Failed to seed %s: %s", rel, exc)
            continue
        written.append(rel)

    written.sort()
    return written


def list_builtins() -> list[str]:
    """Return relative paths of all bundled builtin files.

    Returns:
        Sorted list of relative paths (forward-slash separated) that
        rag owns and seeds.
    """
    return sorted(_BUNDLED_FILES)


__all__ = ["list_builtins", "seed_builtins"]
