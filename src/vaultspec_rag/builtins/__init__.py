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

from importlib import resources
from pathlib import Path

from vaultspec_core.core.helpers import (
    atomic_write,
)

from .._plain_directory import open_plain_directory


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


def _classify_action(dest: Path, src_file: Path) -> str:
    """Classify a builtin as ``[ADD]`` / ``[UPDATE]`` / ``[UNCHANGED]``.

    Assumes the caller has already decided to act on ``dest`` (it does not
    exist, or *force* is set). A read failure on the existing dest is treated
    as changed so the file is rewritten.
    """
    if not dest.exists():
        return "[ADD]"
    try:
        unchanged = dest.read_bytes() == src_file.read_bytes()
    except OSError:
        unchanged = False
    return "[UNCHANGED]" if unchanged else "[UPDATE]"


def seed_builtins(
    target_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    written: list[str] | None = None,
    exclude_prefixes: tuple[str, ...] = (),
) -> list[tuple[str, str]]:
    """Copy rag's bundled builtins into a target ``.vaultspec/`` directory.

    The bundled tree folds flat into ``target_dir`` exactly as core's seeder
    folds its own tree: ``rules/`` -> ``.vaultspec/rules/``, ``mcps/`` ->
    ``.vaultspec/mcps/``, ``skills/<name>/`` -> ``.vaultspec/skills/<name>/``.
    Files that already exist are left untouched unless *force* is ``True``; a
    forced file whose content already matches is classified ``[UNCHANGED]`` and
    not rewritten.

    Reporting matches ``vaultspec_core.builtins.seed_builtins``: a
    ``(relative_path, action)`` pair per builtin acted on, ``action`` in
    ``[ADD]`` / ``[UPDATE]`` / ``[UNCHANGED]``. rag additionally keeps its own
    seed hardening that core's minimal seeder omits: destination containment
    (``target_dir`` and every directory beneath it on the way to a member must
    be a real directory, so a link cannot carry a write outside it), crash-safe
    ``atomic_write``, a **raised** per-file ``OSError`` (never a silent partial
    seed), and an optional ``written`` out-list of the paths actually written
    so a caller can roll back a partial seed before the error propagates.

    Args:
        target_dir: The ``.vaultspec/`` framework directory to populate.
        force: Overwrite existing files (unchanged content stays untouched).
        dry_run: Classify every builtin without writing - previews an upgrade.
        written: Optional out-list of ``[ADD]``/``[UPDATE]`` relative paths
            actually written, in order, for targeted rollback.
        exclude_prefixes: Forward-slash relative-path prefixes to omit before
            classification or writing. This lets a component skip protect its
            complete source domain rather than seeding and then reversing it.

    Returns:
        Sorted list of ``(relative_path, action)`` pairs for every builtin the
        call acted on (or would act on, under *dry_run*). Files skipped because
        they exist and *force* is False are omitted.

    Raises:
        OSError: If a destination file write fails, or ``target_dir`` or a
            directory beneath it is a link or not a directory.
    """
    src_root = _builtins_root()
    if written is None:
        written = []
    results: list[tuple[str, str]] = []
    for src_file in _iter_builtin_files(src_root):
        rel = str(src_file.relative_to(src_root)).replace("\\", "/")
        if rel.startswith(exclude_prefixes):
            continue
        dest = target_dir / rel
        container = (Path(target_dir.name) / rel).parent
        with open_plain_directory(target_dir.parent, container, create=not dry_run):
            if dest.exists() and not force:
                continue
            action = _classify_action(dest, src_file)
            if action != "[UNCHANGED]" and not dry_run:
                atomic_write(dest, src_file.read_text(encoding="utf-8"))
                written.append(rel)
            results.append((rel, action))
    results.sort()
    return results


def list_builtins() -> list[str]:
    """Return relative paths of all bundled builtin files (forward-slash)."""
    src_root = _builtins_root()
    return sorted(
        str(f.relative_to(src_root)).replace("\\", "/")
        for f in _iter_builtin_files(src_root)
    )


__all__ = ["list_builtins", "seed_builtins"]
