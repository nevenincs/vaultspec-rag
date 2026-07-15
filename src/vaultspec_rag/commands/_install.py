"""``vaultspec-rag install`` orchestration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from tomlkit.exceptions import ParseError
from vaultspec_core.core.commands import (  # pyright: ignore[reportMissingTypeStubs]
    sync_provider,
)
from vaultspec_core.core.mcps import mcp_sync  # pyright: ignore[reportMissingTypeStubs]
from vaultspec_core.core.workspace_mode import (  # pyright: ignore[reportMissingTypeStubs]
    dependency_leak_advisory,
    newly_establishes_dependency,
    read_package_declaration,
)

from ..builtins import list_builtins, seed_builtins
from ._mcp_extra import reconcile_mcp_extra
from ._mode import (
    RAG_DISTRIBUTION_NAME,
    infer_rag_upgrade_mode,
    migrate_rag_mcp_entry,
    persist_rag_mode,
    resolve_rag_mode,
)
from ._models import InstallReport
from ._torch_flow import _run_torch_config_install
from ._workspace import (
    _ensure_workspace_dirs,
    _init_core_context,
    _resolve_target,
)

if TYPE_CHECKING:
    from pathlib import Path

    from vaultspec_core.core.enums import (  # pyright: ignore[reportMissingTypeStubs]
        InstallMode,
    )

    from ._models import ConfirmFn

logger = logging.getLogger(__name__)


def _seed_builtins(
    vaultspec_dir: Path,
    report: InstallReport,
    dry_run: bool,
    force: bool,
    upgrade: bool,
    install_mcp: bool,
) -> None:
    """Seed rag's whole bundled tree flat into ``.vaultspec/`` (core's fold).

    ``seed_builtins`` folds ``rules/`` / ``mcps/`` / ``skills/`` into
    ``.vaultspec/rules/`` / ``.vaultspec/mcps/`` / ``.vaultspec/skills/``. On a
    write failure the partially-seeded files are rolled back before the error
    propagates.
    """
    if not dry_run:
        written: list[str] = []
        try:
            seeded = seed_builtins(
                vaultspec_dir, force=force or upgrade, written=written
            )
        except Exception:
            _rollback_seeded(vaultspec_dir, written, report)
            raise
    else:
        seeded = seed_builtins(vaultspec_dir, force=force or upgrade, dry_run=True)

    mcp_sources = {rel for rel in list_builtins() if rel.startswith("mcps/")}
    report.seeded = [item for item in seeded if item[0] not in mcp_sources]
    if install_mcp:
        report.seeded.extend(item for item in seeded if item[0] in mcp_sources)
        return
    for rel in sorted(mcp_sources):
        source = vaultspec_dir / rel
        if not source.exists():
            continue
        if not dry_run:
            source.unlink()
        report.seeded.append((rel, "[REMOVE]"))


def _reconcile_mcp_extra(
    target: Path,
    report: InstallReport,
    mode: InstallMode,
    *,
    enabled: bool,
    dry_run: bool,
) -> None:
    try:
        result = reconcile_mcp_extra(
            target / "pyproject.toml", mode=mode, enabled=enabled, dry_run=dry_run
        )
    except ParseError as exc:
        report.mcp_extra_action = "error"
        report.warnings.append(f"MCP extra inspect failed: {exc}")
        return
    report.mcp_extra_action = result.action
    report.warnings.extend(f"MCP extra: {conflict}" for conflict in result.conflicts)


def _run_core_sync(
    target: Path,
    report: InstallReport,
    dry_run: bool,
    force: bool,
    skip: set[str],
    mode: InstallMode,
) -> None:
    if "core" in skip:
        return
    if not dry_run:
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
                    skip={*skip, "mcp"},
                )
            except Exception as exc:
                logger.error("sync_provider failed during install: %s", exc)
                report.warnings.append(
                    f"core sync failed: {exc} "
                    f"(seeded files left in place; re-run install or "
                    f"uninstall --force to clean up)"
                )
    if "mcp" in skip:
        return
    try:
        result = mcp_sync(
            dry_run=dry_run,
            force=force,
            prune=True,
            mode=mode,
            provider="all",
            scope="project",
            target_dir=target,
        )
    except Exception as exc:
        logger.error("project MCP sync failed during install: %s", exc)
        report.warnings.append(f"project MCP sync failed: {exc}")
    else:
        report.sync_results.append(result)
        report.mcp_sync_results.append(result)


def _persist_mode_and_detect_flip(
    target: Path,
    mode: InstallMode,
    *,
    dry_run: bool,
    skip: set[str],
) -> bool:
    """Persist rag's mode before the sync and report whether it flips the launch.

    From the 0.1.44 floor core's sync renders each companion MCP definition at
    its own declaring package's committed mode, so writing rag's entry *before*
    the sync lets the sync render rag's ``.mcp.json`` launch in rag's own shape
    natively for the fresh and same-mode cases. The write reads and rewrites only
    rag's own entry under the advisory lock, leaving a sibling ``vaultspec-core``
    entry untouched, and needs only the target path, not core's runtime context.

    Rag's deployed launch shape is captured here, before the sync overwrites it,
    so an ``install --upgrade`` that flips rag's mode is detectable: the returned
    flag drives the post-sync force-managed seam that migrates a stale managed
    entry the plain sync's force-gate would otherwise skip. A dry run or a
    core-skipped run neither persists nor flips.

    Args:
        target: Workspace root directory.
        mode: Rag's resolved provisioning mode to persist.
        dry_run: When ``True``, neither persist nor detect (no writes on a preview).
        skip: Sync skip tokens; a ``"core"`` skip disables both.

    Returns:
        ``True`` when rag's deployed launch shape diverges from *mode* and must
        be force-migrated after the sync; ``False`` otherwise.
    """
    if dry_run or "core" in skip:
        return False
    declaration = read_package_declaration(target, RAG_DISTRIBUTION_NAME)
    previous_mode = (
        declaration.install_mode
        if declaration is not None
        else infer_rag_upgrade_mode(target, None).mode
    )
    mcp_mode_flipped = previous_mode != mode
    persist_rag_mode(target, mode)
    return mcp_mode_flipped


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
    mode: InstallMode | None = None,
) -> InstallReport:
    """Install vaultspec-rag enrollment into a workspace.

    Self-sufficient: idempotently creates any missing directories rag
    needs, seeds rag's bundled tree flat into ``.vaultspec/`` (rules into
    ``.vaultspec/rules/``, the MCP into ``.vaultspec/mcps/``, skills into
    ``.vaultspec/skills/`` - the same fold core uses), then invokes core's
    ``sync_provider`` to propagate the new sources into ``.mcp.json`` and
    provider dirs.

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
        mode: The provisioning mode requested via ``--mode``
            (``tool`` / ``dependency`` / ``dev``), or ``None`` to fall through
            to rag's persisted declaration, ``pyproject.toml`` detection, and
            the tool-mode default in turn. Resolved through core's shared
            ``workspace_mode`` precedence with ``package="vaultspec-rag"``,
            persisted into rag's own entry in the shared
            ``.vaultspec/workspace.json`` without disturbing a sibling
            ``vaultspec-core`` entry, and used to render rag's MCP launch shape.
            An explicit ``dependency`` or ``dev`` request with no
            ``pyproject.toml`` raises rather than silently falling back.

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

    # Resolve rag's provisioning mode through core's shared precedence chain
    # before seeding, so an impossible explicit request (dependency/dev mode
    # with no pyproject.toml) raises a loud, typed refusal here rather than
    # after files have been seeded. The upgrade path re-infers from rag's own
    # deployed MCP shape; a fresh install resolves at provision time. The
    # provenance rides along so the dependency-leak advisory fires only when
    # this run is the one electing dependency mode, not on a persisted read.
    resolved = (
        infer_rag_upgrade_mode(target, mode)
        if upgrade
        else resolve_rag_mode(target, mode)
    )

    # Seed rag's bundled tree flat into ``.vaultspec/`` exactly as core does
    # (rules/ -> .vaultspec/rules/, mcps/ -> .vaultspec/mcps/, skills/<name>/
    # -> .vaultspec/skills/<name>/), so core's collectors and sync pick them up
    # like any core builtin.
    vaultspec_dir = target / ".vaultspec"
    _reconcile_mcp_extra(
        target,
        report,
        resolved.mode,
        enabled=install_mcp,
        dry_run=dry_run,
    )
    _seed_builtins(vaultspec_dir, report, dry_run, force, upgrade, install_mcp)

    # Persist rag's own entry in the shared per-package declaration BEFORE core's
    # sync runs, and capture whether this run flips rag's deployed launch shape.
    mcp_mode_flipped = _persist_mode_and_detect_flip(
        target, resolved.mode, dry_run=dry_run, skip=skip
    )

    # sync_provider needs core's runtime context. Initialise it here
    # (instead of in _resolve_target) so the manifest write is paired
    # 1:1 with an actual sync invocation - see COHAB-01 fix in
    # _init_core_context. Dry-run skips both the init and the sync.
    _run_core_sync(target, report, dry_run, force, skip, resolved.mode)

    # Mode-flip seam, the analogue of core's own force-managed pass: a plain
    # (non-forced) sync's force-gate skips an already-managed rag entry whose
    # deployed launch shape diverges from the newly-resolved mode, so an upgrade
    # that flips rag's mode would leave the stale shape in place. Force just
    # rag's own managed entry into the new mode. Skipped on a fresh install
    # (nothing deployed to flip), when --force already rewrote every entry, or
    # when the mode did not flip - the common case the native sync already
    # handled above.
    if mcp_mode_flipped and not force and not dry_run and "core" not in skip:
        migration = migrate_rag_mcp_entry(resolved.mode)
        report.sync_results.append(migration)
        report.mcp_sync_results.append(migration)

    # Surface the moment-of-choice dependency-leak advisory (install-parity ADR
    # D3): fires only when this run newly elects the full-leak dependency
    # placement for rag, so a persisted-declaration workspace is not nagged on
    # every subsequent install.
    if newly_establishes_dependency(resolved):
        report.warnings.append(dependency_leak_advisory(RAG_DISTRIBUTION_NAME))

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


def _rollback_seeded(base_dir: Path, seeded: list[str], report: InstallReport) -> None:
    """Best-effort cleanup of files seeded during a failed install.

    Removes only files that *this* install actually wrote (recorded in
    ``seeded``). Never removes pre-existing files. Errors during rollback are
    recorded as warnings - they cannot mask the original install failure since
    the caller re-raises.
    """
    for rel in seeded:
        try:
            (base_dir / rel).unlink(missing_ok=True)
        except OSError as exc:
            report.warnings.append(f"rollback: failed to remove {rel}: {exc}")
    report.warnings.append(
        f"install failed mid-seed; rolled back {len(seeded)} file(s)"
    )
