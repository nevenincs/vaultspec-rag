"""``vaultspec-rag install`` orchestration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from vaultspec_core.core.commands import (  # pyright: ignore[reportMissingTypeStubs]
    sync_provider,
)

from ..builtins import seed_builtins, seed_skills
from ._models import InstallReport
from ._torch_flow import _run_torch_config_install
from ._workspace import (
    _ensure_workspace_dirs,
    _init_core_context,
    _resolve_target,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ._models import ConfirmFn

logger = logging.getLogger(__name__)


def _seed_rules(
    rules_dir: Path,
    report: InstallReport,
    dry_run: bool,
    force: bool,
    upgrade: bool,
) -> None:
    if not dry_run:
        try:
            seed_builtins(rules_dir, force=force or upgrade, written=report.seeded)
        except Exception:
            _rollback_seeded(rules_dir, report.seeded, report)
            raise
    else:
        from ..builtins import list_builtins

        bundled = list_builtins()
        report.seeded = [
            rel for rel in bundled if not (rules_dir / rel).exists() or force or upgrade
        ]


def _seed_skills(
    skills_dir: Path,
    report: InstallReport,
    dry_run: bool,
    force: bool,
    upgrade: bool,
) -> None:
    if not dry_run:
        seeded: list[str] = []
        try:
            seed_skills(skills_dir, force=force or upgrade, written=seeded)
        except Exception:
            _rollback_seeded(skills_dir, seeded, report)
            raise
        report.seeded.extend(seeded)
    else:
        from ..builtins import list_skills

        bundled = list_skills()
        report.seeded.extend(
            rel
            for rel in bundled
            if not (skills_dir / rel).exists() or force or upgrade
        )


def _run_core_sync(
    target: Path,
    report: InstallReport,
    dry_run: bool,
    force: bool,
    skip: set[str],
) -> None:
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
    provision: bool = False,
    local_only: bool = False,
    provision_skip: set[str] | None = None,
    torch_group: str | None = None,
    install_mcp: bool = False,
) -> InstallReport:
    """Install vaultspec-rag enrollment into a workspace.

    Self-sufficient: idempotently creates any missing directories rag
    needs, seeds rag's bundled rule and MCP source files into
    ``.vaultspec/rules/`` and its bundled skills into ``.vaultspec/skills/``,
    then invokes core's ``sync_provider`` to propagate the new sources into
    ``.mcp.json`` and provider dirs.

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
        provision: When True, run the unified provisioning front door
            (models, qdrant binary) after enrollment and thread its
            heterogeneous per-dependency outcome onto the report. The
            operator-facing opt-out polarity lives at the CLI edge, which
            passes ``provision=True`` by default to match the server-first
            default; this orchestrator defaults it ``False`` so existing
            programmatic callers (and their network-free unit tests) keep
            the enrollment-only behaviour unless they ask to provision.
        local_only: When True, the headline escape hatch: the front door
            skips the qdrant binary step and the install persists the
            local backend selection (via ``persist_local_only``) so a
            later ``server start`` honours it without re-passing the flag.
        provision_skip: Finer per-dependency opt-out tokens
            (``"torch"`` / ``"models"`` / ``"qdrant"``) forwarded to the
            front door's ``skip`` set, for callers wanting some but not
            all steps.
        torch_group: When given, the managed direct ``torch`` dependency
            is written to the PEP 735 ``[dependency-groups].<torch_group>``
            surface instead of ``[project].dependencies`` so a dev-only
            consumer does not leak torch into its published runtime
            requirements. ``None`` (the default) preserves the historic
            project-deps placement byte-for-byte.

    Returns:
        :class:`InstallReport` with the structured result, including the
        provisioning outcome on ``report.provision_outcome`` when
        provisioning ran.
    """
    target = _resolve_target(path, bootstrap=not dry_run)
    skip = skip or set()
    action = "dry_run" if dry_run else ("upgrade" if upgrade else "install")

    report = InstallReport(action=action, target=target)
    report.created_dirs = _ensure_workspace_dirs(target, dry_run=dry_run)

    rules_dir = target / ".vaultspec" / "rules"
    _seed_rules(rules_dir, report, dry_run, force, upgrade)

    # Skills seed into ``.vaultspec/skills/`` (core's skill collector scans
    # there), separate from the rules/mcps root above.
    skills_dir = target / ".vaultspec" / "skills"
    _seed_skills(skills_dir, report, dry_run, force, upgrade)

    # sync_provider needs core's runtime context. Initialise it here
    # (instead of in _resolve_target) so the manifest write is paired
    # 1:1 with an actual sync invocation - see COHAB-01 fix in
    # _init_core_context. Dry-run skips both the init and the sync.
    _run_core_sync(target, report, dry_run, force, skip)

    _run_torch_config_install(
        target=target,
        report=report,
        dry_run=dry_run,
        force=force,
        configure_torch=configure_torch,
        assume_yes=assume_yes,
        sync_after=sync_after,
        confirm=confirm,
        torch_group=torch_group,
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

    # Ensure the optional [mcp] extra. Install wires up the MCP surface (it
    # seeds the rag MCP config that `uv run vaultspec-search-mcp` launches), so
    # the operator-facing default installs that server's dependency too - mcp is
    # a base-install opt-out, not a setup-time opt-in. The opt-out polarity lives
    # at the CLI edge (which passes ``install_mcp=True`` by default for --mcp);
    # this orchestrator defaults it ``False`` so programmatic callers and their
    # network-free unit tests do not shell out, mirroring ``provision``. --no-mcp
    # skips it for a CLI-only setup. Non-fatal: a failure is a warning, since the
    # guarded entry point still tells the operator what to install.
    if install_mcp:
        if dry_run:
            report.mcp_extra_action = "would-add"
        else:
            from ._uv_sync import _run_uv_add_mcp_extra

            _run_uv_add_mcp_extra(target=target, report=report)

    if provision:
        _run_provisioning(
            target=target,
            report=report,
            dry_run=dry_run,
            local_only=local_only,
            provision_skip=provision_skip,
            assume_yes=assume_yes,
            sync_after=sync_after,
            confirm=confirm,
        )

        # Persist the local-only runtime selection so the resident service
        # honours the chosen backend on a later ``server start`` without
        # the operator re-passing ``--local-only``. Gated on ``provision``
        # (the setup path) so a plain enrollment-only call never writes
        # runtime state, and on ``not dry_run`` because a preview must not
        # touch disk. The explicit choice is persisted either way
        # (``False`` records a deliberate server-mode selection) so the
        # marker is unambiguous; env / flag still override it at
        # resolution time.
        if not dry_run:
            _persist_runtime_selection(report, local_only)

    return report


def _persist_runtime_selection(report: InstallReport, local_only: bool) -> None:
    """Write the local-only runtime marker, degrading to a warning on error.

    A persisted runtime hint must never crash setup, so an OSError on the
    write is logged and surfaced as a recoverable warning naming the
    runtime escape hatches, rather than raised.
    """
    from ..config import persist_local_only

    try:
        persist_local_only(local_only)
    except OSError as exc:
        logger.error("failed to persist local-only selection: %s", exc)
        report.warnings.append(
            f"could not persist the local-only selection: {exc}; "
            f"pass --local-only on `server start` or set "
            f"VAULTSPEC_RAG_LOCAL_ONLY to select the local backend."
        )


def _run_provisioning(
    *,
    target: Path,
    report: InstallReport,
    dry_run: bool,
    local_only: bool,
    provision_skip: set[str] | None,
    assume_yes: bool,
    sync_after: bool,
    confirm: ConfirmFn | None,
) -> None:
    """Run the provisioning front door and attach its outcome to the report.

    Torch is already configured by the enrollment torch step above (its
    honest two-phase state lives on ``report.torch_config_action`` and the
    renderer surfaces it), so the front door is told to skip torch here -
    re-running it would double-prompt and double-report. The front door
    therefore drives the two fetch-and-go dependencies, models and the
    qdrant binary, and its heterogeneous outcome is carried on
    ``report.provision_outcome`` for the renderer. A failed step is
    surfaced as a warning rather than raised, because enrollment already
    succeeded and provisioning is the recoverable, re-runnable phase.
    """
    from ._provision import provision_dependencies

    # The enrollment torch step already ran (and is reported on its own
    # report fields); fold "torch" into the front door's skip set so its
    # torch result is an honest opted-out, never a misleading re-run.
    skip = set(provision_skip or set())
    skip.add("torch")

    outcome = provision_dependencies(
        target,
        local_only=local_only,
        skip=skip,
        dry_run=dry_run,
        configure_torch=False,
        assume_yes=assume_yes,
        sync_after=sync_after,
        confirm=confirm,
    )
    report.provision_outcome = outcome
    if not outcome.ok:
        failed = [r for r in outcome.steps if r.action == "failed"]
        for result in failed:
            report.warnings.append(
                f"provisioning step {result.step} failed: {result.detail}"
            )


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
