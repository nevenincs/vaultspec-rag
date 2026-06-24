"""Bundled builtin resources deployed during ``vaultspec-rag install``.

Contains the canonical rule (``rules/vaultspec-rag.builtin.md``) and MCP
server definition (``mcps/vaultspec-rag.builtin.json``) seeded into
``.vaultspec/rules/`` on first install. Consumed by
:mod:`vaultspec_rag.commands` via :func:`seed_builtins` and
:func:`list_builtins`. Uses :mod:`importlib.resources` for
package-relative file access.

The builtin files live as committed package data under this package,
mirroring :mod:`vaultspec_core.builtins`: the package directory is the
single source of truth, and the seed/list helpers walk that tree. rag
bundles only the files it exclusively owns; the broader
``.vaultspec/rules/`` tree is core-managed and not authored here.
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

    The builtin files ship as package data under this package, so the
    package directory is the root in both editable and wheel installs.
    Mirrors :func:`vaultspec_core.builtins._builtins_root`.
    """
    return Path(str(resources.files(__package__)))


def _iter_builtin_files(src_root: Path) -> list[Path]:
    """Return the bundled builtin files, skipping Python package artifacts.

    Walks the package tree like :mod:`vaultspec_core.builtins` so the
    manifest is whatever ships under this package, never a hardcoded list
    that can drift from the files on disk.
    """
    files: list[Path] = []
    for path in sorted(src_root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in ("__init__.py", "__pycache__") or "__pycache__" in str(path):
            continue
        files.append(path)
    return files


def seed_builtins(
    target_rules_dir: Path,
    *,
    force: bool = False,
    written: list[str] | None = None,
) -> list[str]:
    """Copy bundled builtins into a target ``.vaultspec/rules/`` directory.

    Only copies files that don't already exist unless *force* is ``True``.
    Walks the package builtins tree like :mod:`vaultspec_core.builtins`, so
    the seeded set is exactly the files shipped under this package.

    Per-file ``OSError`` is **raised**, not swallowed. Silent partial
    seeding would leave the workspace half-installed and bypass the
    rollback path callers rely on. Callers may pass an out-parameter
    ``written`` list to capture progress before the exception
    propagates, enabling targeted rollback.

    Args:
        target_rules_dir: The ``.vaultspec/rules/`` directory to populate.
        force: Overwrite existing files.
        written: Optional out-list. The function appends each
            successfully-written relative path before continuing to
            the next file. Pass an empty list to capture progress
            even if a later iteration raises.

    Returns:
        Sorted list of relative paths (forward-slash separated) that
        were actually written. Same content as ``written`` if the
        out-list was provided.

    Raises:
        OSError: If a destination file write fails (permissions,
            disk full, etc.).
    """
    src_root = _builtins_root()
    target_resolved = target_rules_dir.resolve()
    if written is None:
        written = []

    for src_file in _iter_builtin_files(src_root):
        rel = str(src_file.relative_to(src_root)).replace("\\", "/")
        dest = target_rules_dir / rel
        try:
            dest_resolved = dest.resolve()
        except OSError as exc:
            logger.warning("Cannot resolve dest %s: %s", dest, exc)
            continue
        # Containment check: dest_resolved must be inside
        # target_resolved. Path.is_relative_to is the canonical test
        # since 3.9; rag targets 3.13.
        if not dest_resolved.is_relative_to(target_resolved):
            logger.warning(
                "Refusing dest outside target: %s (target=%s)",
                dest_resolved,
                target_resolved,
            )
            continue

        if dest.exists() and not force:
            continue

        # Per-file write failure is fatal: raise so the caller can
        # roll back the partial state. Logging-and-continuing would
        # leave a half-installed workspace and a "successful" report.
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Use core's atomic_write (tmp + os.replace) per the ADR.
        # Both bundled files are UTF-8 text (Markdown rule + JSON
        # MCP definition); reading and writing as text preserves
        # content correctly. Crash consistency is the same as
        # core's own builtin seeding pipeline.
        atomic_write(dest, src_file.read_text(encoding="utf-8"))
        written.append(rel)

    written.sort()
    return written


def list_builtins() -> list[str]:
    """Return relative paths of all bundled builtin files.

    Returns:
        Sorted list of relative paths (forward-slash separated) that
        rag owns and seeds.
    """
    src_root = _builtins_root()
    return sorted(
        str(f.relative_to(src_root)).replace("\\", "/")
        for f in _iter_builtin_files(src_root)
    )


__all__ = ["list_builtins", "seed_builtins"]
