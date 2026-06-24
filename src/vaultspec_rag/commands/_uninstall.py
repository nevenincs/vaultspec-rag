"""``vaultspec-rag uninstall`` orchestration."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from vaultspec_core.core.commands import (  # pyright: ignore[reportMissingTypeStubs]
    sync_provider,
)

from ..builtins import list_builtins
from ._models import UninstallReport
from ._torch_flow import _run_torch_config_uninstall
from ._workspace import _init_core_context, _resolve_target

logger = logging.getLogger(__name__)


def _remove_candidates(target: Path, dry_run: bool, report: UninstallReport) -> None:
    # Mirror install symmetrically: remove exactly the files that
    # ``seed_builtins`` would write, derived from the same package tree
    # via ``list_builtins``. A new bundled file is then seeded and
    # removed by one source of truth and can never be orphaned.
    rules_dir = target / ".vaultspec" / "rules"
    candidates = [rules_dir / rel for rel in list_builtins()]
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


def _remove_data_dir(target: Path, dry_run: bool, report: UninstallReport) -> None:
    data_dir = target / ".vault" / "data"
    if data_dir.is_symlink():
        msg = (
            f"refusing to --remove-data: {data_dir} is a symlink. "
            f"Resolve the symlink manually and re-run uninstall."
        )
        logger.warning(msg)
        report.warnings.append(msg)
    elif data_dir.is_dir():
        if not dry_run:
            try:
                shutil.rmtree(data_dir, onexc=_rmtree_safe_onexc)
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", data_dir, exc)
                report.warnings.append(f"failed to remove .vault/data: {exc}")
            else:
                report.data_removed = True
        else:
            report.data_removed = True
            # Preview the concrete target so --force operators see exactly what
            # --remove-data will delete (resolved path + size).
            try:
                size_bytes = sum(
                    f.stat().st_size for f in data_dir.rglob("*") if f.is_file()
                )
                logger.info(
                    "Would remove %s (%.1f MB) with --remove-data",
                    data_dir.resolve(),
                    size_bytes / 1_000_000,
                )
            except OSError as exc:
                logger.debug("could not size %s for preview: %s", data_dir, exc)


def uninstall_run(
    path: Path | None = None,
    *,
    remove_data: bool = False,
    dry_run: bool = False,
    force: bool = False,
    skip: set[str] | None = None,
    assume_yes: bool = False,
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
        assume_yes: Present for CLI symmetry with ``install``. Uninstall
            is already a destructive-by-intent operation (it always
            attempts symmetric reversal of install), so this flag
            currently has no prompt to bypass; it is accepted for
            forward compatibility.

    Returns:
        :class:`UninstallReport` with the structured result.
    """
    # assume_yes is reserved for future prompts; uninstall currently
    # has no prompt to bypass. Suppress the unused-argument lint
    # without ``del`` - keeping the parameter in the public signature
    # so callers don't churn when the future behaviour lands.
    _ = assume_yes
    skip = skip or set()

    # Default-safe: refuse to mutate without --force, return preview.
    if not force:
        dry_run = True

    # IMPORTANT: uninstall must NEVER create workspace directories.
    # A user running ``vaultspec-rag uninstall --force`` in an empty
    # or wrong directory expects a no-op (or a clear error), not the
    # creation of fresh ``.vault/`` and ``.vaultspec/`` artefacts. We
    # therefore resolve the path without bootstrapping; if no
    # ``.vaultspec/`` exists at the target there is nothing rag could
    # have installed and we return an empty report immediately.
    target = _resolve_target(path, bootstrap=False)
    action = "dry_run" if dry_run else "uninstall"
    report = UninstallReport(action=action, target=target)

    if not (target / ".vaultspec").is_dir():
        # No ``.vaultspec/`` means rag was never installed at this
        # target - anything we found in ``pyproject.toml`` belongs to
        # the user (or to a different project that happened to land in
        # the same directory). Mutating their file here is a data-loss
        # surprise, not a symmetric reversal. The torch-config sweep
        # therefore demotes to a dry-run regardless of ``--force`` so
        # the report still surfaces the canonical block (and the path
        # to remove it) without rewriting a file rag does not own.
        report.warnings.append(f"no .vaultspec/ at {target}; nothing to uninstall")
        _run_torch_config_uninstall(target=target, report=report, dry_run=True)
        return report

    _remove_candidates(target, dry_run, report)

    if dry_run:
        report.warnings.append(
            "dry-run: core sync_provider not invoked (would propagate "
            "removal to .mcp.json and provider dirs)"
        )
    elif "core" not in skip:
        # sync_provider needs core's runtime context. Only bootstrap
        # it now (after we've confirmed .vaultspec/ exists), so we
        # never create workspace state during uninstall. Same scoped-
        # init pattern as install (see COHAB-01).
        try:
            _init_core_context(target)
        except Exception as exc:
            logger.error("workspace context bootstrap failed: %s", exc)
            report.warnings.append(f"workspace bootstrap failed: {exc}")
        else:
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

    _run_torch_config_uninstall(target=target, report=report, dry_run=dry_run)

    if remove_data:
        _remove_data_dir(target, dry_run, report)

    return report


def _rmtree_safe_onexc(_func: object, path: str | bytes, exc: BaseException) -> None:
    """``shutil.rmtree`` error handler (Python 3.12+ ``onexc`` form)
    that unlinks symlinks instead of following them.

    Defensive secondary guard against the case where a symlink is
    encountered inside ``.vault/data/`` after the top-level
    ``is_symlink`` check has already passed. Python 3.12+ ``onexc``
    receives the exception instance directly instead of an
    ``exc_info`` tuple.
    """
    p = Path(os.fsdecode(path))
    if p.is_symlink():
        try:
            p.unlink()
        except OSError as e:
            logger.warning("Failed to unlink symlink %s: %s", p, e)
        return
    # Re-raise the original error for non-symlink failures.
    raise exc
