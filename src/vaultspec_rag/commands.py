"""Top-level orchestration for ``vaultspec-rag install`` and ``uninstall``.

This module is the orchestration layer for rag's enrollment commands.
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
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vaultspec_core.config.workspace import resolve_workspace
from vaultspec_core.core.commands import sync_provider
from vaultspec_core.core.types import init_paths

from .builtins import seed_builtins

logger = logging.getLogger(__name__)

__all__ = ["InstallReport", "UninstallReport", "install_run", "uninstall_run"]


# Names of the bundled rag enrollment artefacts (relative to
# ``.vaultspec/rules/``). Defined here once so install and uninstall
# stay symmetric and tests can assert against a single source of truth.
_RAG_RULE_REL_PATH = Path("rules") / "vaultspec-rag.builtin.md"
_RAG_MCP_REL_PATH = Path("mcps") / "vaultspec-rag.builtin.json"


@dataclass
class InstallReport:
    """Structured result of an install run.

    Attributes:
        action: One of ``"install"``, ``"upgrade"``, ``"dry_run"``.
        target: Resolved workspace path.
        created_dirs: Workspace-relative directories rag ensured exist.
        seeded: Workspace-relative paths of bundled files seeded.
        sync_results: ``SyncResult`` objects returned by core's
            ``sync_provider`` (one per sync pass).
        warnings: Non-fatal warnings collected during the run.
    """

    action: str
    target: Path
    created_dirs: list[str] = field(default_factory=list)
    seeded: list[str] = field(default_factory=list)
    sync_results: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": str(self.target),
            "created_dirs": list(self.created_dirs),
            "seeded": list(self.seeded),
            "sync_added": sum(getattr(r, "added", 0) for r in self.sync_results),
            "sync_updated": sum(getattr(r, "updated", 0) for r in self.sync_results),
            "sync_pruned": sum(getattr(r, "pruned", 0) for r in self.sync_results),
            "warnings": list(self.warnings),
        }


@dataclass
class UninstallReport:
    """Structured result of an uninstall run.

    Attributes:
        action: One of ``"uninstall"``, ``"dry_run"``.
        target: Resolved workspace path.
        removed: Workspace-relative paths of source files rag deleted.
        data_removed: True when ``--remove-data`` purged
            ``.vault/data/``.
        sync_results: ``SyncResult`` objects from the propagation pass.
        warnings: Non-fatal warnings collected during the run.
    """

    action: str
    target: Path
    removed: list[str] = field(default_factory=list)
    data_removed: bool = False
    sync_results: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": str(self.target),
            "removed": list(self.removed),
            "data_removed": self.data_removed,
            "sync_pruned": sum(getattr(r, "pruned", 0) for r in self.sync_results),
            "warnings": list(self.warnings),
        }


def _resolve_target(path: Path | None, *, bootstrap: bool) -> Path:
    """Resolve the install target to an absolute workspace path.

    When ``bootstrap`` is True, this also pre-creates the bare minimum
    directories core's ``resolve_workspace`` requires (``target/``,
    ``.vault/``, ``.vaultspec/``) and bootstraps core's runtime context
    via ``init_paths``. The latter is required by ``sync_provider`` —
    it reads the active context to locate ``.vaultspec/`` and
    ``.mcp.json``.

    When ``bootstrap`` is False (dry-run path), only the path itself is
    resolved and no filesystem mutation occurs. The caller must avoid
    calling ``sync_provider`` since core's context is not initialised.

    rag is fully self-sufficient: this bootstrap step is what allows
    install to run in a completely empty directory without requiring
    the user to call ``vaultspec-core install`` first.
    """
    target = (path or Path.cwd()).resolve()
    if not bootstrap:
        return target
    target.mkdir(parents=True, exist_ok=True)
    (target / ".vault").mkdir(exist_ok=True)
    (target / ".vaultspec").mkdir(exist_ok=True)
    layout = resolve_workspace(target_override=target)
    init_paths(layout)
    return target


def _ensure_workspace_dirs(target: Path, *, dry_run: bool) -> list[str]:
    """Idempotently create the directories rag needs to operate.

    rag is fully self-sufficient: it never assumes core has already
    bootstrapped the workspace. The dirs created here are exactly the
    minimum rag's enrollment requires; core's ``install_run`` will
    create the same dirs (and more) without conflict.
    """
    needed = [
        target / ".vault",
        target / ".vault" / "data",
        target / ".vaultspec",
        target / ".vaultspec" / "rules",
        target / ".vaultspec" / "rules" / "rules",
        target / ".vaultspec" / "rules" / "mcps",
    ]
    created: list[str] = []
    for d in needed:
        if d.is_dir():
            continue
        if not dry_run:
            d.mkdir(parents=True, exist_ok=True)
        created.append(str(d.relative_to(target)).replace("\\", "/"))
    return created


def install_run(
    path: Path | None = None,
    *,
    upgrade: bool = False,
    dry_run: bool = False,
    force: bool = False,
    skip: set[str] | None = None,
) -> InstallReport:
    """Install vaultspec-rag enrollment into a workspace.

    Self-sufficient: idempotently creates any missing directories rag
    needs, seeds rag's bundled rule and MCP source files into
    ``.vaultspec/rules/``, then invokes core's ``sync_provider`` to
    propagate the new sources into ``.mcp.json`` and provider dirs.

    Args:
        path: Workspace target. Defaults to current working directory.
        upgrade: Re-seed bundled files even if they already exist.
        dry_run: Compute changes without writing.
        force: Overwrite existing files. Also passed through to
            ``sync_provider`` where it maps to ``prune=True`` for the
            reconciling sync resources.
        skip: Components to skip (passed through to ``sync_provider``).

    Returns:
        :class:`InstallReport` with the structured result.
    """
    target = _resolve_target(path, bootstrap=not dry_run)
    skip = skip or set()
    action = "dry_run" if dry_run else ("upgrade" if upgrade else "install")

    report = InstallReport(action=action, target=target)
    report.created_dirs = _ensure_workspace_dirs(target, dry_run=dry_run)

    rules_dir = target / ".vaultspec" / "rules"
    if not dry_run:
        # Wrap seed + sync in a single try/except so a failure inside
        # seed_builtins (or sync_provider) does not leave the
        # workspace partially seeded with no record of what was
        # written. On failure we attempt to remove only files that
        # *this* install actually created (tracked in report.seeded),
        # surface the error as a warning, and re-raise so the caller
        # sees the failure.
        try:
            report.seeded = seed_builtins(rules_dir, force=force or upgrade)
        except Exception:
            _rollback_seeded(rules_dir, report.seeded, report)
            raise
    else:
        # Compute what would be written without touching disk.
        from .builtins import list_builtins

        bundled = list_builtins()
        report.seeded = [
            rel for rel in bundled if not (rules_dir / rel).exists() or force or upgrade
        ]

    # sync_provider can only be called once core's runtime context has
    # been bootstrapped via init_paths, which only happens on the
    # non-dry-run resolve path. Dry-run reports list the planned
    # propagation as a warning instead of trying to compute it.
    if dry_run:
        report.warnings.append(
            "dry-run: core sync_provider not invoked (would propagate "
            "seeded files to .mcp.json and provider dirs)"
        )
    elif "core" not in skip:
        try:
            report.sync_results = sync_provider(
                "all",
                dry_run=False,
                force=force,
                skip=skip,
            )
        except Exception as exc:
            logger.error("sync_provider failed during install: %s", exc)
            report.warnings.append(
                f"core sync failed: {exc} "
                f"(seeded files left in place; re-run install or "
                f"uninstall --force to clean up)"
            )

    return report


def _rollback_seeded(rules_dir: Path, seeded: list[str], report: InstallReport) -> None:
    """Best-effort cleanup of files seeded during a failed install.

    Removes only files that *this* install actually wrote (recorded in
    ``seeded``). Never removes pre-existing files. Errors during
    rollback are recorded as warnings — they cannot mask the original
    install failure since the caller re-raises.
    """
    for rel in seeded:
        try:
            (rules_dir / rel).unlink(missing_ok=True)
        except OSError as exc:
            report.warnings.append(f"rollback: failed to remove {rel}: {exc}")
    report.warnings.append(
        f"install failed mid-seed; rolled back {len(seeded)} file(s)"
    )


def uninstall_run(
    path: Path | None = None,
    *,
    remove_data: bool = False,
    dry_run: bool = False,
    force: bool = False,
    skip: set[str] | None = None,
) -> UninstallReport:
    """Remove vaultspec-rag enrollment from a workspace.

    Symmetric mirror of :func:`install_run`. Removes rag's bundled
    source files from ``.vaultspec/rules/``, then invokes core's
    ``sync_provider`` to propagate the removal to ``.mcp.json`` and
    provider dirs. Propagation cleanup depends on vaultspec-core
    0.1.10+'s reconciling ``mcp_sync``.

    rag's uninstall NEVER touches core's installation. It removes only
    files rag owns and lets core's sync handle propagation. ``.vault/``
    documents are always preserved. The rag index under ``.vault/data/``
    is preserved unless ``remove_data`` is set.

    Args:
        path: Workspace target. Defaults to current working directory.
        remove_data: Also delete ``.vault/data/`` (rag's index).
        dry_run: Compute changes without writing.
        force: Required to execute. Without it, returns a dry-run
            preview. Also passed through to ``sync_provider`` to enable
            orphan pruning during propagation.
        skip: Components to skip (passed through to ``sync_provider``).

    Returns:
        :class:`UninstallReport` with the structured result.
    """
    skip = skip or set()

    # Default-safe: refuse to mutate without --force, return preview.
    if not force:
        dry_run = True

    target = _resolve_target(path, bootstrap=not dry_run)
    action = "dry_run" if dry_run else "uninstall"
    report = UninstallReport(action=action, target=target)

    rules_dir = target / ".vaultspec" / "rules"
    candidates = [
        rules_dir / _RAG_RULE_REL_PATH,
        rules_dir / _RAG_MCP_REL_PATH,
    ]
    for src_file in candidates:
        if not src_file.exists():
            continue
        rel = str(src_file.relative_to(target)).replace("\\", "/")
        if not dry_run:
            try:
                src_file.unlink()
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", rel, exc)
                report.warnings.append(f"failed to remove {rel}: {exc}")
                continue
        report.removed.append(rel)

    if dry_run:
        report.warnings.append(
            "dry-run: core sync_provider not invoked (would propagate "
            "removal to .mcp.json and provider dirs)"
        )
    elif "core" not in skip:
        try:
            report.sync_results = sync_provider(
                "all",
                dry_run=False,
                force=force,
                skip=skip,
            )
        except Exception as exc:
            logger.error("sync_provider failed during uninstall: %s", exc)
            report.warnings.append(f"core sync failed: {exc}")

    if remove_data:
        data_dir = target / ".vault" / "data"
        # Symlink containment guard: rag must NEVER follow a symlink
        # out of the workspace and rmtree somewhere unexpected. If
        # ``.vault/data/`` is a symlink (even one pointing inside the
        # workspace), refuse the destructive operation and surface a
        # clear warning. The user must resolve the symlink manually
        # before re-running uninstall, which forces an explicit
        # decision about what to delete.
        if data_dir.is_symlink():
            msg = (
                f"refusing to --remove-data: {data_dir} is a symlink. "
                f"Resolve the symlink manually and re-run uninstall."
            )
            logger.warning(msg)
            report.warnings.append(msg)
        elif data_dir.is_dir():
            # is_dir() is False for symlinks-to-files but True for
            # symlinks-to-dirs, so the symlink check above must run
            # first. Belt-and-braces: also pass ``onerror`` so any
            # symlink encountered *inside* the tree is unlinked
            # rather than followed.
            if not dry_run:
                try:
                    shutil.rmtree(data_dir, onerror=_rmtree_safe_onerror)
                except OSError as exc:
                    logger.warning("Failed to remove %s: %s", data_dir, exc)
                    report.warnings.append(f"failed to remove .vault/data: {exc}")
                else:
                    report.data_removed = True
            else:
                report.data_removed = True

    return report


def _rmtree_safe_onerror(_func, path, exc_info) -> None:
    """``shutil.rmtree`` error handler that unlinks symlinks instead
    of following them.

    Defensive secondary guard against the case where a symlink is
    encountered inside ``.vault/data/`` after the top-level
    ``is_symlink`` check has already passed.
    """
    p = Path(path)
    if p.is_symlink():
        try:
            p.unlink()
        except OSError as exc:
            logger.warning("Failed to unlink symlink %s: %s", p, exc)
        return
    # Re-raise the original error for non-symlink failures.
    raise exc_info[1]
