"""``vaultspec-rag install`` orchestration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from vaultspec_core.core.commands import sync_provider

from ..builtins import seed_builtins
from ._models import InstallReport
from ._torch_flow import _run_torch_config_install
from ._workspace import _ensure_workspace_dirs, _init_core_context, _resolve_target

if TYPE_CHECKING:
    from pathlib import Path

    from ._models import ConfirmFn

logger = logging.getLogger(__name__)


def install_run(
    path: Path | None = None,
    *,
    upgrade: bool = False,
    dry_run: bool = False,
    force: bool = False,
    skip: set[str] | None = None,
    configure_torch: bool = True,
    assume_yes: bool = False,
    sync_after: bool = False,
    confirm: ConfirmFn | None = None,
) -> InstallReport:
    """Install vaultspec-rag enrollment into a workspace.

    Self-sufficient: idempotently creates any missing directories rag
    needs, seeds rag's bundled rule and MCP source files into
    ``.vaultspec/rules/``, then invokes core's ``sync_provider`` to
    propagate the new sources into ``.mcp.json`` and provider dirs.

    When ``configure_torch`` is True (the default), also patches the
    consumer's ``pyproject.toml`` with the canonical cu130 torch index
    and source pin. This step is gated by an interactive confirmation
    prompt (bypassed with ``assume_yes=True``). In non-TTY contexts
    without ``assume_yes``, the step is skipped with a warning that
    names the ``--yes`` / ``--no-torch-config`` flags.

    Args:
        path: Workspace target. Defaults to current working directory.
        upgrade: Re-seed bundled files even if they already exist.
        dry_run: Compute changes without writing.
        force: Overwrite existing files. Also passed through to
            ``sync_provider`` where it maps to ``prune=True`` for the
            reconciling sync resources.
        skip: Components to skip (passed through to ``sync_provider``).
        configure_torch: When True, patch ``pyproject.toml`` with the
            cu130 torch config block.
        assume_yes: Skip the interactive confirmation prompt.
        sync_after: After a successful torch-config patch, shell out
            to ``uv sync --reinstall-package torch``. Off by default.
        confirm: Optional callback for the confirmation prompt. The
            CLI wires this to Rich's ``Confirm.ask``; tests and
            programmatic callers can pass their own. When ``None`` the
            step is non-interactive and falls through to the
            ``assume_yes`` gate.

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
        # Pass an out-list so partial progress is captured BEFORE any
        # exception propagates. seed_builtins now raises OSError on
        # the first per-file failure (no more silent partial seeds).
        # On failure we roll back only the files this install actually
        # wrote, surface the error as a warning, and re-raise so the
        # caller sees the failure.
        try:
            seed_builtins(rules_dir, force=force or upgrade, written=report.seeded)
        except Exception:
            _rollback_seeded(rules_dir, report.seeded, report)
            raise
    else:
        # Compute what would be written without touching disk.
        from ..builtins import list_builtins

        bundled = list_builtins()
        report.seeded = [
            rel for rel in bundled if not (rules_dir / rel).exists() or force or upgrade
        ]

    # sync_provider needs core's runtime context. Initialise it here
    # (instead of in _resolve_target) so the manifest write is paired
    # 1:1 with an actual sync invocation - see COHAB-01 fix in
    # _init_core_context. Dry-run skips both the init and the sync.
    if dry_run:
        report.warnings.append(
            "dry-run: core sync_provider not invoked (would propagate "
            "seeded files to .mcp.json and provider dirs)"
        )
    elif "core" not in skip:
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
                logger.error("sync_provider failed during install: %s", exc)
                report.warnings.append(
                    f"core sync failed: {exc} "
                    f"(seeded files left in place; re-run install or "
                    f"uninstall --force to clean up)"
                )

    _run_torch_config_install(
        target=target,
        report=report,
        dry_run=dry_run,
        force=force,
        configure_torch=configure_torch,
        assume_yes=assume_yes,
        sync_after=sync_after,
        confirm=confirm,
    )
    if not dry_run:
        _maybe_warn_hf_auth(report)

    # INSTALL-04: ``--sync`` is gated by ``patch_report.action ==
    # "applied"`` inside ``_run_torch_config_install``. Any path that
    # leaves torch-config in a non-applied state (disabled / dry_run /
    # declined / customised / conflict / already / skipped-non-tty /
    # skipped-eof / error) silently drops the sync. Surface a warning
    # so the user knows their explicit ``--sync`` request did not run.
    # ``torch_sync_action == "skipped"`` is the post-init default
    # untouched by ``_run_uv_sync_torch``.
    if sync_after and report.torch_sync_action == "skipped":
        report.warnings.append(
            f"--sync requested but skipped: torch-config step did not apply "
            f"and torch direct-dep step did not run "
            f"(torch_config_action={report.torch_config_action}, "
            f"torch_direct_dep_action={report.torch_direct_dep_action}). Run "
            f"`uv sync --reinstall-package torch` manually after resolving "
            f"the reported torch configuration issue."
        )

    return report


def _maybe_warn_hf_auth(report: InstallReport) -> None:
    """Warn when HuggingFace credentials are not configured locally."""
    try:
        from huggingface_hub import get_token
    except ImportError:
        report.warnings.append(
            "huggingface_hub is not installed; install dependencies before "
            "downloading embedding models."
        )
        return

    if get_token():
        return
    report.warnings.append(
        "HuggingFace token not found. Run `huggingface-cli login` before "
        "model warmup, indexing, or search if model downloads require auth."
    )


def _rollback_seeded(rules_dir: Path, seeded: list[str], report: InstallReport) -> None:
    """Best-effort cleanup of files seeded during a failed install.

    Removes only files that *this* install actually wrote (recorded in
    ``seeded``). Never removes pre-existing files. Errors during
    rollback are recorded as warnings - they cannot mask the original
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
