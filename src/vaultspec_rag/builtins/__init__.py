"""Bundled builtin resources deployed during ``vaultspec-rag install``.

Contains the canonical rule (``rules/vaultspec-rag.builtin.md``), the MCP
server definition (``mcps/vaultspec-rag.builtin.json``), and the bundled
skills (``skills/<name>/SKILL.md`` plus optional ``references/`` / ``agents/``
subdirs). Rules and MCPs seed into ``.vaultspec/rules/``; skills seed into
``.vaultspec/skills/`` so vaultspec-core's skill collector and provider sync
pick them up exactly as they do core's own skills. Consumed by
:mod:`vaultspec_rag.commands` via :func:`seed_builtins` / :func:`seed_skills`
and :func:`list_builtins` / :func:`list_skills`. Uses
:mod:`importlib.resources` for package-relative file access.

The builtin files live as committed package data under this package: the
package directory is the single source of truth, and the seed/list helpers
walk that tree, never a hardcoded manifest that can drift from the files on
disk.
"""

from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path

from vaultspec_core.core.helpers import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    atomic_write,
)

logger = logging.getLogger(__name__)

# Bundled skills live under this subdirectory of the package builtins tree and
# seed into ``.vaultspec/skills/`` (not ``.vaultspec/rules/``), so they are
# excluded from the rules/mcps seed pass and handled by ``seed_skills``.
_SKILLS_SUBDIR = "skills"


def _builtins_root() -> Path:
    """Return the filesystem path to the bundled builtins directory.

    The builtin files ship as package data under this package, so the package
    directory is the root in both editable and wheel installs. Mirrors
    :func:`vaultspec_core.builtins._builtins_root`.
    """
    return Path(str(resources.files(__package__)))


def _iter_builtin_files(root: Path, *, exclude_subdir: str | None = None) -> list[Path]:
    """Return bundled files under ``root``, skipping Python package artifacts.

    Walks the tree like :mod:`vaultspec_core.builtins` so the manifest is
    whatever ships under ``root``, never a hardcoded list that can drift. When
    ``exclude_subdir`` is given, files whose first path segment (relative to
    ``root``) equals it are omitted - used to keep the ``skills/`` subtree out
    of the rules/mcps seed pass. Returns an empty list when ``root`` is absent.
    """
    if not root.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "__init__.py" or "__pycache__" in str(path):
            continue
        if exclude_subdir is not None:
            rel_parts = path.relative_to(root).parts
            if rel_parts and rel_parts[0] == exclude_subdir:
                continue
        files.append(path)
    return files


def _copy_seed_files(
    files: list[Path],
    rel_base: Path,
    target_dir: Path,
    *,
    force: bool,
    written: list[str],
) -> None:
    """Copy ``files`` (paths relative to ``rel_base``) into ``target_dir``.

    Shared body of :func:`seed_builtins` and :func:`seed_skills`. Enforces
    destination containment (a member can never escape ``target_dir``), writes
    via core's ``atomic_write`` (tmp + os.replace), and records each written
    relative path in ``written`` before continuing so a later failure can be
    rolled back by the caller. Per-file ``OSError`` from the write is **raised**,
    not swallowed: a silent partial seed would leave the workspace
    half-installed and bypass the caller's rollback path.
    """
    target_resolved = target_dir.resolve()
    for src_file in files:
        rel = str(src_file.relative_to(rel_base)).replace("\\", "/")
        dest = target_dir / rel
        try:
            dest_resolved = dest.resolve()
        except OSError as exc:
            logger.warning("Cannot resolve dest %s: %s", dest, exc)
            continue
        if not dest_resolved.is_relative_to(target_resolved):
            logger.warning(
                "Refusing dest outside target: %s (target=%s)",
                dest_resolved,
                target_resolved,
            )
            continue
        if dest.exists() and not force:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(dest, src_file.read_text(encoding="utf-8"))
        written.append(rel)


def seed_builtins(
    target_rules_dir: Path,
    *,
    force: bool = False,
    written: list[str] | None = None,
) -> list[str]:
    """Copy bundled rules and the MCP definition into ``.vaultspec/rules/``.

    The ``skills/`` subtree is excluded here; skills seed via
    :func:`seed_skills` into ``.vaultspec/skills/``. Only copies files that do
    not already exist unless *force* is ``True``.

    Callers may pass an out-parameter ``written`` list to capture progress
    before an exception propagates, enabling targeted rollback.

    Args:
        target_rules_dir: The ``.vaultspec/rules/`` directory to populate.
        force: Overwrite existing files.
        written: Optional out-list; each successfully-written relative path is
            appended before continuing to the next file.

    Returns:
        Sorted list of relative paths (forward-slash separated) written.

    Raises:
        OSError: If a destination file write fails.
    """
    src_root = _builtins_root()
    if written is None:
        written = []
    files = _iter_builtin_files(src_root, exclude_subdir=_SKILLS_SUBDIR)
    _copy_seed_files(files, src_root, target_rules_dir, force=force, written=written)
    written.sort()
    return written


def seed_skills(
    target_skills_dir: Path,
    *,
    force: bool = False,
    written: list[str] | None = None,
) -> list[str]:
    """Copy bundled skills into ``.vaultspec/skills/``.

    Each skill is a directory (``skills/<name>/SKILL.md`` plus optional
    ``references/`` / ``agents/`` subdirs) copied wholesale so vaultspec-core's
    skill collector and provider sync treat it exactly like a core skill. Only
    copies files that do not already exist unless *force* is ``True``. Same
    containment/atomic-write/rollback contract as :func:`seed_builtins`.

    Args:
        target_skills_dir: The ``.vaultspec/skills/`` directory to populate.
        force: Overwrite existing files.
        written: Optional out-list capturing progress for rollback.

    Returns:
        Sorted list of relative paths (forward-slash separated) written.

    Raises:
        OSError: If a destination file write fails.
    """
    skills_root = _builtins_root() / _SKILLS_SUBDIR
    if written is None:
        written = []
    files = _iter_builtin_files(skills_root)
    _copy_seed_files(
        files, skills_root, target_skills_dir, force=force, written=written
    )
    written.sort()
    return written


def list_builtins() -> list[str]:
    """Return relative paths of all bundled rule/MCP files (skills excluded)."""
    src_root = _builtins_root()
    return sorted(
        str(f.relative_to(src_root)).replace("\\", "/")
        for f in _iter_builtin_files(src_root, exclude_subdir=_SKILLS_SUBDIR)
    )


def list_skills() -> list[str]:
    """Return relative paths of all bundled skill files (under ``skills/``)."""
    skills_root = _builtins_root() / _SKILLS_SUBDIR
    return sorted(
        str(f.relative_to(skills_root)).replace("\\", "/")
        for f in _iter_builtin_files(skills_root)
    )


__all__ = ["list_builtins", "list_skills", "seed_builtins", "seed_skills"]
