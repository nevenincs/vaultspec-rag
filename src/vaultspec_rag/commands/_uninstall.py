"""``vaultspec-rag uninstall`` orchestration."""

from __future__ import annotations

import logging
import tempfile
from contextvars import Context
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, Unpack

from vaultspec_core.core.commands import (
    sync_provider,
)
from vaultspec_core.core.mcps import (
    mcp_uninstall,
)

from .._rmtree import remove_tree
from .._workspace_layout import (
    VAULT_DATA_DIR,
    WORKSPACE_DIR,
)
from ..builtins import list_builtins
from ._mcp_extra import reconcile_mcp_extra
from ._mcp_topology import (
    LINKED_NODES_NOT_REMOVABLE,
    RequiredMcpTopology,
    inspect_required_mcp_topology,
    record_mcp_failure,
    topology_materialization_failure,
    topology_preflight_failure,
)
from ._mode import resolve_rag_mode
from ._models import UninstallReport
from ._torch_flow import _run_torch_config_uninstall
from ._workspace import _init_core_context, _resolve_target

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _UninstallRequest:
    path: Path | None = None
    remove_data: bool = False
    dry_run: bool = False
    force: bool = False
    skip: set[str] | None = None
    assume_yes: bool = False


class _UninstallOptions(TypedDict, total=False):
    remove_data: bool
    dry_run: bool
    force: bool
    skip: set[str] | None
    assume_yes: bool


def _remove_candidates(
    target: Path,
    dry_run: bool,
    report: UninstallReport,
    *,
    skip_mcp: bool,
) -> None:
    # Mirror install symmetrically: remove exactly the files that
    # ``seed_builtins`` would write, derived from the same package tree
    # via ``list_builtins``. A new bundled file is then seeded and
    # removed by one source of truth and can never be orphaned.
    vaultspec_dir = target / WORKSPACE_DIR
    candidates = [
        vaultspec_dir / rel
        for rel in list_builtins()
        if not (skip_mcp and rel.startswith("mcps/"))
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


#: Obsolete runtime sentinels older installs may have left in the project
#: tree (issue #236). Current rag keeps all runtime state outside the repo
#: (the machine-global status dir and ``.vault/data/``), so these are only
#: ever stale residue; uninstall removes them defensively and idempotently.
_OBSOLETE_SENTINEL_FILES = (".qdrant-initialized",)
_OBSOLETE_SENTINEL_DIRS = (WORKSPACE_DIR / "runtime",)


def _remove_obsolete_sentinels(
    target: Path, dry_run: bool, report: UninstallReport
) -> None:
    for name in _OBSOLETE_SENTINEL_FILES:
        sentinel = target / name
        if not sentinel.is_file():
            continue
        if not dry_run:
            try:
                sentinel.unlink()
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", name, exc)
                report.warnings.append(f"failed to remove {name}: {exc}")
                continue
        report.removed.append(name)
    for relative in _OBSOLETE_SENTINEL_DIRS:
        sentinel_dir = target / relative
        if not sentinel_dir.is_dir() or sentinel_dir.is_symlink():
            continue
        rel = relative.as_posix()
        if not dry_run:
            try:
                remove_tree(sentinel_dir)
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", rel, exc)
                report.warnings.append(f"failed to remove {rel}: {exc}")
                continue
        report.removed.append(rel)


def _remove_data_dir(target: Path, dry_run: bool, report: UninstallReport) -> None:
    data_dir = target / VAULT_DATA_DIR
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
                remove_tree(data_dir)
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


def _run_mcp_cleanup(
    target: Path,
    report: UninstallReport,
    *,
    dry_run: bool,
) -> None:
    """Remove only RAG-owned provider projections through Core's authority."""

    def cleanup() -> object:
        return mcp_uninstall(
            target,
            dry_run=dry_run,
            provider="all",
            scope="project",
            names=frozenset({"vaultspec-rag"}),
        )

    result = Context().run(cleanup) if dry_run else cleanup()
    report.sync_results.append(result)
    report.mcp_sync_results.append(result)


def _record_extra_failure(
    report: UninstallReport,
    action: str,
    messages: list[str],
) -> None:
    report.mcp_extra_action = action
    for detail in messages:
        message = f"MCP extra: {detail}"
        record_mcp_failure(report, message)


def _reverse_mcp_extra(
    target: Path,
    report: UninstallReport,
    *,
    dry_run: bool,
) -> bool:
    """Preflight and commit owned extra reversal before MCP teardown."""
    try:
        resolved_mode = resolve_rag_mode(target, None).mode
        preview = reconcile_mcp_extra(
            target / "pyproject.toml",
            mode=resolved_mode,
            enabled=False,
            dry_run=True,
        )
    except Exception as exc:
        logger.debug("MCP-extra reversal inspection failed during uninstall: %s", exc)
        _record_extra_failure(report, "error", [f"reversal inspection failed: {exc}"])
        return False

    report.mcp_extra_action = preview.action
    report.mcp_extra_location = preview.location
    if preview.conflicts:
        _record_extra_failure(report, "conflict", preview.conflicts)
        return False
    if dry_run:
        return True

    try:
        committed = reconcile_mcp_extra(
            target / "pyproject.toml",
            mode=resolved_mode,
            enabled=False,
            dry_run=False,
        )
    except Exception as exc:
        logger.debug("MCP-extra reversal failed during uninstall: %s", exc)
        _record_extra_failure(report, "error", [f"reversal failed: {exc}"])
        return False

    report.mcp_extra_action = committed.action
    report.mcp_extra_location = committed.location
    if committed.conflicts:
        _record_extra_failure(report, "conflict", committed.conflicts)
        return False
    return True


def _run_core_cleanup(
    target: Path,
    report: UninstallReport,
    *,
    dry_run: bool,
    force: bool,
    skip: set[str],
) -> None:
    """Reconcile non-MCP resources and selectively remove RAG MCP entries."""
    if "core" in skip:
        return

    if dry_run:
        report.warnings.append(
            "dry-run: non-MCP sync_provider not invoked "
            "(would propagate bundled-source removal to provider dirs)"
        )
    else:
        try:
            _init_core_context(target)
        except Exception as exc:
            logger.error("workspace context bootstrap failed: %s", exc)
            report.warnings.append(f"workspace bootstrap failed: {exc}")
        else:
            try:
                report.sync_results.extend(
                    sync_provider(
                        "all",
                        dry_run=False,
                        force=force,
                        skip={*skip, "mcp"},
                    )
                )
            except Exception as exc:
                logger.error("sync_provider failed during uninstall: %s", exc)
                report.warnings.append(f"core sync failed: {exc}")

    if "mcp" not in skip:
        try:
            _run_mcp_cleanup(target, report, dry_run=dry_run)
        except Exception as exc:
            logger.error("MCP cleanup failed during uninstall: %s", exc)
            report.mcp_errors.append(f"MCP cleanup failed: {exc}")


def _run_mcp_disenrollment_transaction(
    target: Path,
    report: UninstallReport,
    topology: RequiredMcpTopology,
    *,
    dry_run: bool,
    rollback_on_failure: bool = True,
) -> bool:
    """Reverse placement and native enrollment as one failure boundary."""
    if not dry_run:
        try:
            topology.materialize()
        except Exception as exc:
            message = topology_materialization_failure(exc)
            record_mcp_failure(report, message)
            return False
    if not _reverse_mcp_extra(target, report, dry_run=dry_run):
        if not dry_run and rollback_on_failure:
            _record_topology_errors(report, topology.finish(commit=False))
        return False
    try:
        _run_mcp_cleanup(target, report, dry_run=dry_run)
    except Exception as exc:
        logger.error("MCP cleanup failed during uninstall: %s", exc)
        report.mcp_errors.append(f"MCP cleanup failed: {exc}")
    if report.mcp_sync_failed:
        if not dry_run and rollback_on_failure:
            _record_topology_errors(report, topology.finish(commit=False))
        return False
    if not dry_run:
        _record_topology_errors(report, topology.finish(commit=True))
    return not report.mcp_sync_failed


def _record_topology_errors(report: UninstallReport, errors: list[str]) -> None:
    for message in errors:
        record_mcp_failure(report, message)


def uninstall_run(
    path: Path | None = None,
    **options: Unpack[_UninstallOptions],
) -> UninstallReport:
    """Remove vaultspec-rag enrollment from a workspace."""
    return _uninstall_run(_UninstallRequest(path=path, **options))


def _uninstall_run(request: _UninstallRequest) -> UninstallReport:
    """Remove vaultspec-rag enrollment from a workspace.

    Symmetric mirror of :func:`install_run`. Removes rag's bundled
    source files from ``.vaultspec/``, then invokes Core's ordinary
    provider sync for non-MCP resources and its project-scoped
    ``mcp_uninstall`` for MCP entries. The latter is filtered to
    ``vaultspec-rag`` so sibling Core and user entries remain untouched.

    rag's uninstall NEVER touches core's installation. It removes only
    files and provider entries RAG owns. ``.vault/`` documents are always
    preserved. The rag index under ``.vault/data/`` is preserved unless
    ``remove_data`` is set.

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
    path, remove_data, dry_run, force, skip, assume_yes = (
        request.path,
        request.remove_data,
        request.dry_run,
        request.force,
        request.skip,
        request.assume_yes,
    )
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

    topology: RequiredMcpTopology | None = None
    if "mcp" not in skip:
        try:
            topology = inspect_required_mcp_topology(target)
        except Exception as exc:
            message = topology_preflight_failure(exc)
            record_mcp_failure(report, message)
            return report
        if topology.disenrollment_links:
            message = LINKED_NODES_NOT_REMOVABLE
            record_mcp_failure(report, message)
            return report

    if not (target / WORKSPACE_DIR).is_dir():
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

    mcp_skipped = "mcp" in skip
    if not mcp_skipped and not dry_run and topology is not None:
        with tempfile.TemporaryDirectory(prefix="vaultspec-rag-mcp-replay-") as raw:
            replay_target = Path(raw) / "workspace"
            topology.populate_projection(replay_target)
            replay_topology = inspect_required_mcp_topology(replay_target)
            replay_report = UninstallReport(action="uninstall", target=replay_target)
            Context().run(
                _run_mcp_disenrollment_transaction,
                replay_target,
                replay_report,
                replay_topology,
                dry_run=False,
                rollback_on_failure=False,
            )
            topology.capture_expected_projection(replay_target)
    if (
        not mcp_skipped
        and topology is not None
        and not _run_mcp_disenrollment_transaction(
            target,
            report,
            topology,
            dry_run=dry_run,
        )
    ):
        return report

    _remove_candidates(target, dry_run, report, skip_mcp=mcp_skipped)
    _remove_obsolete_sentinels(target, dry_run, report)

    _run_core_cleanup(
        target,
        report,
        dry_run=dry_run,
        force=force,
        skip={*skip, "mcp"},
    )

    _run_torch_config_uninstall(target=target, report=report, dry_run=dry_run)

    if remove_data:
        _remove_data_dir(target, dry_run, report)

    return report
