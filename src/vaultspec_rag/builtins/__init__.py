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
from importlib import resources
from pathlib import Path

from vaultspec_core.core.helpers import atomic_write

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

    # Editable install - walk up to the repo root and use the canonical
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


def seed_builtins(
    target_rules_dir: Path,
    *,
    force: bool = False,
    written: list[str] | None = None,
) -> list[str]:
    """Copy bundled builtins into a target ``.vaultspec/rules/`` directory.

    Only copies files that don't already exist unless *force* is ``True``.
    Iterates the explicit :data:`_BUNDLED_FILES` manifest so editable and
    wheel installs both seed exactly the same set.

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

    for rel in _BUNDLED_FILES:
        # Defense in depth: even though _BUNDLED_FILES is a static
        # tuple, refuse anything that could escape target_rules_dir.
        # Future maintainers must not be able to introduce a path
        # traversal by editing the manifest without noticing.
        if rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
            logger.warning("Refusing unsafe bundled rel path: %s", rel)
            continue

        src_file = src_root / rel
        if not src_file.is_file():
            logger.warning("Bundled file missing at source: %s", src_file)
            continue

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
    return sorted(_BUNDLED_FILES)


__all__ = ["list_builtins", "seed_builtins"]
