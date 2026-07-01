"""Bundled builtin resources deployed during ``vaultspec-rag install``.

Contains rag's canonical rule (``rules/vaultspec-rag.builtin.md``), MCP server
definition (``mcps/vaultspec-rag.builtin.json``), and bundled skills
(``skills/<name>/SKILL.md``), seeded directly into ``.vaultspec/`` on first
install with the same fold vaultspec-core uses: the bundled tree maps flat into
``.vaultspec/`` (``rules/`` -> ``.vaultspec/rules/``, ``mcps/`` ->
``.vaultspec/mcps/``, ``skills/<name>/`` -> ``.vaultspec/skills/<name>/``), so
core's collectors and provider sync pick them up like any core builtin. Consumed
by :mod:`vaultspec_rag.commands`. Uses :mod:`importlib.resources` for
package-relative file access.

rag is a sibling of vaultspec-core and follows its seed fold. The seed path is
crash-consistent (``atomic_write``) with a caller-driven rollback contract that
core's minimal seeder omits; the shared ``check_outdated`` primitive mirrors
core's upgrade-management surface.
"""

from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path

from vaultspec_core.core.helpers import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    atomic_write,
)

logger = logging.getLogger(__name__)


def _builtins_root() -> Path:
    """Return the filesystem path to the bundled builtins directory.

    The builtin files ship as package data under this package, so the package
    directory is the root in both editable and wheel installs. Mirrors
    :func:`vaultspec_core.builtins._builtins_root`.
    """
    return Path(str(resources.files(__package__)))


def _iter_builtin_files(root: Path) -> list[Path]:
    """Return every bundled file under ``root``, skipping Python artifacts.

    Walks the tree like :mod:`vaultspec_core.builtins` so the manifest is
    whatever ships under the package, never a hardcoded list that can drift.
    """
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in ("__init__.py", "__pycache__") or "__pycache__" in str(path):
            continue
        files.append(path)
    return files


def seed_builtins(
    target_dir: Path,
    *,
    force: bool = False,
    written: list[str] | None = None,
) -> list[str]:
    """Copy rag's bundled builtins into a target ``.vaultspec/`` directory.

    The bundled tree folds flat into ``target_dir`` exactly as core's seeder
    folds its own tree: ``rules/`` -> ``.vaultspec/rules/``, ``mcps/`` ->
    ``.vaultspec/mcps/``, ``skills/<name>/`` -> ``.vaultspec/skills/<name>/``.
    Only copies files that do not already exist unless *force* is ``True``.

    Destination containment is enforced (a member can never escape
    ``target_dir``), writes use core's ``atomic_write`` (tmp + os.replace), and
    per-file ``OSError`` from the write is **raised**, not swallowed: a silent
    partial seed would leave the workspace half-installed and bypass the
    caller's rollback path. Callers may pass a ``written`` out-list to capture
    progress before an exception propagates, enabling targeted rollback.

    Args:
        target_dir: The ``.vaultspec/`` framework directory to populate.
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
    target_resolved = target_dir.resolve()
    for src_file in _iter_builtin_files(src_root):
        rel = str(src_file.relative_to(src_root)).replace("\\", "/")
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
    written.sort()
    return written


def list_builtins() -> list[str]:
    """Return relative paths of all bundled builtin files (forward-slash)."""
    src_root = _builtins_root()
    return sorted(
        str(f.relative_to(src_root)).replace("\\", "/")
        for f in _iter_builtin_files(src_root)
    )


def check_outdated(target_dir: Path) -> list[str]:
    """Compare bundled builtins against a deployed ``.vaultspec/`` tree.

    Mirrors :func:`vaultspec_core.builtins.check_outdated`.

    Returns:
        Relative paths (forward-slash) present in the package but missing or
        content-different at the target.
    """
    src_root = _builtins_root()
    outdated: list[str] = []
    for src_file in _iter_builtin_files(src_root):
        rel = str(src_file.relative_to(src_root)).replace("\\", "/")
        dest = target_dir / rel
        if not dest.exists():
            outdated.append(rel)
            continue
        try:
            if src_file.read_bytes() != dest.read_bytes():
                outdated.append(rel)
        except OSError:
            outdated.append(rel)
    return outdated


__all__ = ["check_outdated", "list_builtins", "seed_builtins"]
