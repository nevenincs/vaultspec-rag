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
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vaultspec_core.config.workspace import resolve_workspace
from vaultspec_core.core.commands import sync_provider
from vaultspec_core.core.types import init_paths

from . import torch_config
from .builtins import seed_builtins
from .torch_config import TorchConfigAction

ConfirmFn = Callable[[str], bool]

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
    torch_config_action: TorchConfigAction = TorchConfigAction.SKIPPED
    torch_config_conflicts: list[str] = field(default_factory=list)
    torch_sync_action: str = "skipped"

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
            "torch_config_action": self.torch_config_action,
            "torch_config_conflicts": list(self.torch_config_conflicts),
            "torch_sync_action": self.torch_sync_action,
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
    torch_config_action: TorchConfigAction = TorchConfigAction.SKIPPED
    torch_config_conflicts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": str(self.target),
            "removed": list(self.removed),
            "data_removed": self.data_removed,
            "sync_pruned": sum(getattr(r, "pruned", 0) for r in self.sync_results),
            "warnings": list(self.warnings),
            "torch_config_action": self.torch_config_action,
            "torch_config_conflicts": list(self.torch_config_conflicts),
        }


def _resolve_target(path: Path | None, *, bootstrap: bool) -> Path:
    """Resolve the install target to an absolute workspace path.

    When ``bootstrap`` is True, this pre-creates the bare minimum
    directories core's ``resolve_workspace`` requires (``target/``,
    ``.vault/``, ``.vaultspec/``). It does NOT call
    :func:`vaultspec_core.core.types.init_paths` — that's deferred to
    the ``sync_provider`` call site via :func:`_init_core_context`.

    Why deferred: ``init_paths`` materialises core's
    ``.vaultspec/providers.json`` manifest as a side effect, which a
    later ``vaultspec-core install`` interprets as "already
    installed" and refuses to proceed without ``--upgrade`` /
    ``--force``. That contradicts rag's companion-package contract
    (rag is independent of core; both should cohabit cleanly without
    one blocking the other). COHAB-01.

    When ``bootstrap`` is False (dry-run path), only the path itself
    is resolved and no filesystem mutation occurs.
    """
    target = (path or Path.cwd()).resolve()
    if not bootstrap:
        return target
    target.mkdir(parents=True, exist_ok=True)
    (target / ".vault").mkdir(exist_ok=True)
    (target / ".vaultspec").mkdir(exist_ok=True)
    return target


def _init_core_context(target: Path) -> None:
    """Initialise core's runtime context just before a ``sync_provider``
    call. Scoped here (instead of in :func:`_resolve_target`) so the
    manifest write is paired 1:1 with an actual core API invocation —
    rag never seeds a manifest just for being instantiated. COHAB-01.
    """
    layout = resolve_workspace(target_override=target)
    init_paths(layout)


def _exception_caused_by(exc: BaseException, target_type: type) -> bool:
    """Return True if any exception in ``exc``'s ``__cause__`` /
    ``__context__`` chain (or ``exc`` itself) is a ``target_type``.

    Rich's ``Confirm.ask`` on some non-TTY platforms wraps an
    ``EOFError`` from stdin in a ``click.Abort``; the chain still
    points back to the original cause. Without walking the chain,
    we'd misclassify those as user-intent declines.
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, target_type):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


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
        from .builtins import list_builtins

        bundled = list_builtins()
        report.seeded = [
            rel for rel in bundled if not (rules_dir / rel).exists() or force or upgrade
        ]

    # sync_provider needs core's runtime context. Initialise it here
    # (instead of in _resolve_target) so the manifest write is paired
    # 1:1 with an actual sync invocation — see COHAB-01 fix in
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
            f"(torch_config_action={report.torch_config_action}). Run "
            f"`uv sync --reinstall-package torch` manually if you still want "
            f"to refresh the torch wheel."
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


def _run_torch_config_install(
    *,
    target: Path,
    report: InstallReport,
    dry_run: bool,
    force: bool,
    configure_torch: bool,
    assume_yes: bool,
    sync_after: bool,
    confirm: ConfirmFn | None,
) -> None:
    """Apply the cu130 torch-config patch to the consumer pyproject.

    Decisions are recorded on ``report``. The body converts the
    raise-paths from :mod:`vaultspec_rag.torch_config`
    (``tomlkit.exceptions.ParseError`` on corrupt TOML, ``OSError``
    from the atomic write) into non-fatal warnings so install's
    overall contract matches the ``sync_provider`` handling above.

    See :mod:`vaultspec_rag.torch_config` for the matching predicate.
    """
    if not configure_torch:
        report.torch_config_action = TorchConfigAction.DISABLED
        return

    pyproject = target / "pyproject.toml"
    try:
        state = torch_config.detect_state(pyproject)
    except Exception as exc:
        logger.error("torch_config.detect_state failed: %s", exc)
        report.torch_config_action = TorchConfigAction.ERROR
        report.warnings.append(f"torch-config inspect failed: {exc}")
        return

    if state == torch_config.TorchConfigState.NO_PROJECT_FILE:
        report.torch_config_action = TorchConfigAction.ABSENT
        report.warnings.append(
            f"no pyproject.toml at {pyproject}; skipped torch-config patch"
        )
        return
    if state == torch_config.TorchConfigState.CANONICAL:
        report.torch_config_action = TorchConfigAction.ALREADY
        # Idempotent re-runs still need the transitive-dep diagnostic —
        # the fix is required every run, not just on the first write.
        # Without this, a user who ran install once, never added torch
        # as a direct dep, and runs install again gets "already" with
        # no warning even though resolution still pulls cpu-torch.
        _maybe_warn_transitive_dep(pyproject, report)
        return
    if state == torch_config.TorchConfigState.CUSTOMISED:
        # Detect returns no conflicts on CUSTOMISED; run apply to get
        # the structured conflict list. apply_patch will not mutate.
        try:
            report_patch = torch_config.apply_patch(pyproject)
        except Exception as exc:
            logger.error("torch_config.apply_patch failed on CUSTOMISED: %s", exc)
            report.torch_config_action = TorchConfigAction.ERROR
            report.warnings.append(f"torch-config inspect failed: {exc}")
            return
        report.torch_config_action = TorchConfigAction.CONFLICT
        report.torch_config_conflicts = list(report_patch.conflicts)
        report.warnings.append(
            "pyproject.toml has a non-canonical cu130 block; "
            "skipping patch — resolve manually or run with different flags"
        )
        return

    # state is MISSING.
    if dry_run:
        report.torch_config_action = TorchConfigAction.DRY_RUN
        # Surface the transitive-dep preview during dry-run too, so the
        # most actionable warning is not hidden behind the wet-run gate.
        # Otherwise the "preview" misleads: clean preview, then surprise.
        _maybe_warn_transitive_dep(pyproject, report, dry_run=True)
        return

    # ``--force`` is the user's blanket opt-in for destructive intent
    # across the install (re-seed bundled files, prune sync state). It
    # would be surprising for it not to also bypass the torch-config
    # confirmation: a user who has typed ``--force`` once expects the
    # whole flow to land. Treat ``force`` as implying ``assume_yes``
    # for this step.
    effective_assume_yes = assume_yes or force

    if not effective_assume_yes:
        if confirm is None:
            # Non-interactive caller (or programmatic use without a
            # prompt hook). Refuse to guess — name the opt-in flags.
            report.torch_config_action = TorchConfigAction.SKIPPED_NON_TTY
            report.warnings.append(
                "torch-config patch requires confirmation — pass --yes "
                "(or --force) to apply, or --no-torch-config to opt out. "
                "See pyproject.toml shape in `vaultspec-rag install --help`."
            )
            return
        try:
            approved = confirm(
                f"Patch {pyproject} with the cu130 torch index? "
                f"This lets uv resolve the CUDA torch wheel."
            )
        except KeyboardInterrupt:
            # User actively interrupted. Treat as a decline; do not
            # rewrite the action label, since this is the only branch
            # that genuinely reflects user intent.
            report.torch_config_action = TorchConfigAction.DECLINED
            report.warnings.append("torch-config patch declined by user")
            return
        except EOFError:
            # Non-interactive harness (CI, pipe, IDE-managed shell)
            # where ``isatty()`` lied. The prompt hit end-of-stream
            # instead of getting an answer — the user was never asked.
            # Distinguish from "declined" so users don't read this as
            # their own choice; name the flag that bypasses the prompt.
            report.torch_config_action = TorchConfigAction.SKIPPED_EOF
            report.warnings.append(
                "torch-config patch skipped: confirmation prompt hit EOF "
                "(non-interactive stdin). Re-run with --yes or --force "
                "to apply, or --no-torch-config to opt out."
            )
            return
        except Exception as exc:
            # Any other exception from a custom ``confirm`` hook (e.g.
            # ``click.Abort`` raised by Rich's Confirm.ask in some
            # detached-stdio terminals, or an IDE-injected callback
            # raising its own type) must NOT tear down the rest of the
            # install. Torch-config is documented as a non-fatal step;
            # fold the failure into the same warning taxonomy as the
            # other prompt-side branches and continue.
            #
            # Special case: Rich's ``Confirm.ask`` on Windows wraps EOF
            # input as ``click.Abort`` rather than re-raising the bare
            # ``EOFError``. Walk the exception chain to detect that and
            # re-route to the same SKIPPED_EOF taxonomy the explicit
            # ``except EOFError`` branch produces. BEHAV-02.
            if _exception_caused_by(exc, EOFError):
                report.torch_config_action = TorchConfigAction.SKIPPED_EOF
                report.warnings.append(
                    "torch-config patch skipped: confirmation prompt hit EOF "
                    "(non-interactive stdin). Re-run with --yes or --force "
                    "to apply, or --no-torch-config to opt out."
                )
                return
            logger.warning(
                "torch-config confirm() raised %s: %s", type(exc).__name__, exc
            )
            report.torch_config_action = TorchConfigAction.DECLINED
            report.warnings.append(
                f"torch-config patch skipped: confirm prompt raised "
                f"{type(exc).__name__}. Re-run with --yes or --force to bypass "
                f"the prompt, or --no-torch-config to opt out."
            )
            return
        if not approved:
            # INSTALL-07: keep the decline branch consistent with every
            # other "skipped" variant — emit a one-line warning naming
            # the bypass flags so programmatic consumers iterating
            # ``report.warnings`` get a signal, not just renderer-side
            # colour. The other not-applied-by-user-choice branches
            # (KeyboardInterrupt, EOFError, skipped-non-tty) already do
            # this; declined was the asymmetric outlier.
            report.torch_config_action = TorchConfigAction.DECLINED
            report.warnings.append(
                "torch-config patch declined; "
                "re-run with --yes or --force to apply, "
                "or --no-torch-config to opt out."
            )
            return

    try:
        patch_report = torch_config.apply_patch(pyproject)
    except Exception as exc:
        logger.error("torch_config.apply_patch failed: %s", exc)
        report.torch_config_action = TorchConfigAction.ERROR
        report.warnings.append(f"torch-config write failed: {exc}")
        return
    report.torch_config_action = patch_report.action
    report.torch_config_conflicts = list(patch_report.conflicts)

    if patch_report.action != "applied":
        return

    # The patch landed; the workspace is now in CANONICAL state. Surface
    # the same transitive-dep diagnostic the CANONICAL short-circuit
    # surfaces, so the warning fires regardless of whether bytes were
    # written today.
    _maybe_warn_transitive_dep(pyproject, report)

    if sync_after:
        _run_uv_sync_torch(target=target, report=report)


def _maybe_warn_transitive_dep(
    pyproject: Path, report: InstallReport, *, dry_run: bool = False
) -> None:
    """Append the transitive-dep warning when ``torch`` is not a direct dep.

    uv silently ignores ``[tool.uv.sources]`` for purely-transitive
    packages, so the cu130 pin is a no-op when ``torch`` only enters
    resolution via ``vaultspec-rag``'s ``Requires-Dist``. The check
    must fire on every wet-run path that leaves the workspace in a
    canonical state (fresh apply AND idempotent re-run) and on dry-run
    previews of MISSING — otherwise the warning hides behind paths
    the user hits more often than first install.

    Args:
        pyproject: Path to the consumer's ``pyproject.toml``.
        report: The install report to mutate.
        dry_run: When True, prefix the warning with "(dry-run preview)"
            so the user knows the diagnostic reflects what the wet run
            would do, not state on disk after the call.
    """
    direct, _location = torch_config.has_direct_torch_dep(pyproject)
    if direct:
        return
    prefix = "(dry-run preview) " if dry_run else ""
    report.warnings.append(
        f"{prefix}torch-config patched, but `torch` is not a direct dependency "
        "of this project. uv ignores [tool.uv.sources] for purely "
        "transitive packages, so the cu130 pin will not take effect. "
        f"Add `torch>={torch_config.TORCH_MIN_VERSION}` to "
        "[project].dependencies or [dependency-groups].dev, then run "
        "`uv lock --refresh-package torch && uv sync`."
    )


def _run_uv_sync_torch(*, target: Path, report: InstallReport) -> None:
    """Shell out to ``uv sync --reinstall-package torch``.

    Non-fatal: failures are recorded as warnings, never raised. Runs
    with ``check=False`` so we can surface uv's own stderr in the
    report without a Python traceback. Result-classification logic
    lives in :func:`_classify_uv_sync_result` so it can be exercised
    by tests without going through ``subprocess`` PATH resolution
    (Windows ``CreateProcess`` only auto-tries ``.exe``, which makes
    ``.cmd`` / ``.bat`` stubs unreliable cross-platform).
    """
    try:
        proc = subprocess.run(
            ["uv", "sync", "--reinstall-package", "torch"],
            cwd=str(target),
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        report.torch_sync_action = "uv-not-found"
        report.warnings.append(
            "--sync requested but `uv` is not on PATH; "
            "run `uv sync --reinstall-package torch` manually"
        )
        return
    except OSError as exc:
        report.torch_sync_action = "error"
        report.warnings.append(f"uv sync failed to launch: {exc}")
        return

    action, warning = _classify_uv_sync_result(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )
    report.torch_sync_action = action
    if warning is not None:
        report.warnings.append(warning)


def _classify_uv_sync_result(
    *, returncode: int, stdout: str, stderr: str
) -> tuple[str, str | None]:
    """Classify the outcome of ``uv sync`` by exit code and streams.

    Pure function: takes the captured streams from ``subprocess.run``
    and returns ``(action, warning_or_none)`` for the install report.
    Centralising the stream-priority logic here lets tests pin every
    branch (success, stderr-failed, stdout-only-failed, both-empty
    failed) without forging subprocesses.

    uv writes resolution failures to stderr most of the time, but
    certain ``--locked`` mismatches and lockfile-conflict renderings
    land on stdout — surface whichever stream carries a payload so
    the user has something actionable to read.
    """
    if returncode == 0:
        return "succeeded", None
    stderr_s = stderr.strip()
    stdout_s = stdout.strip()
    if stderr_s:
        tail = "\n".join(stderr_s.splitlines()[-5:])
        return (
            "failed",
            f"uv sync --reinstall-package torch exited with code "
            f"{returncode}; last stderr lines:\n{tail}",
        )
    if stdout_s:
        tail = "\n".join(stdout_s.splitlines()[-5:])
        return (
            "failed",
            f"uv sync --reinstall-package torch exited with code "
            f"{returncode}; last stdout lines:\n{tail}",
        )
    return (
        "failed",
        f"uv sync --reinstall-package torch exited with code {returncode}",
    )


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
    # without ``del`` — keeping the parameter in the public signature
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
        # target — anything we found in ``pyproject.toml`` belongs to
        # the user (or to a different project that happened to land in
        # the same directory). Mutating their file here is a data-loss
        # surprise, not a symmetric reversal. The torch-config sweep
        # therefore demotes to a dry-run regardless of ``--force`` so
        # the report still surfaces the canonical block (and the path
        # to remove it) without rewriting a file rag does not own.
        report.warnings.append(f"no .vaultspec/ at {target}; nothing to uninstall")
        _run_torch_config_uninstall(target=target, report=report, dry_run=True)
        return report

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
                    shutil.rmtree(data_dir, onexc=_rmtree_safe_onexc)
                except OSError as exc:
                    logger.warning("Failed to remove %s: %s", data_dir, exc)
                    report.warnings.append(f"failed to remove .vault/data: {exc}")
                else:
                    report.data_removed = True
            else:
                report.data_removed = True

    return report


def _run_torch_config_uninstall(
    *,
    target: Path,
    report: UninstallReport,
    dry_run: bool,
) -> None:
    """Remove the cu130 torch-config block from the consumer pyproject.

    Always attempts symmetric reversal — silent no-op when state is
    MISSING or NO_PROJECT_FILE. CUSTOMISED entries are left alone
    with a warning. Parse / write errors from
    :mod:`vaultspec_rag.torch_config` are captured as non-fatal
    warnings, mirroring the install-side contract.
    """
    pyproject = target / "pyproject.toml"
    try:
        state = torch_config.detect_state(pyproject)
    except Exception as exc:
        logger.error("torch_config.detect_state failed: %s", exc)
        report.torch_config_action = TorchConfigAction.ERROR
        report.warnings.append(f"torch-config inspect failed: {exc}")
        return

    if state == torch_config.TorchConfigState.NO_PROJECT_FILE:
        report.torch_config_action = TorchConfigAction.ABSENT
        return
    if state == torch_config.TorchConfigState.MISSING:
        report.torch_config_action = TorchConfigAction.ABSENT
        return
    if state == torch_config.TorchConfigState.CUSTOMISED:
        # remove_patch is safe to call on CUSTOMISED — it short-circuits
        # before any write and returns the conflict list. Call it in
        # both dry-run and wet modes so the report is symmetric with
        # the install side (which calls apply_patch unconditionally).
        try:
            patch_report = torch_config.remove_patch(pyproject)
        except Exception as exc:
            logger.error("torch_config.remove_patch failed on CUSTOMISED: %s", exc)
            report.torch_config_action = TorchConfigAction.ERROR
            report.warnings.append(f"torch-config inspect failed: {exc}")
            return
        report.torch_config_action = TorchConfigAction.SKIPPED
        report.torch_config_conflicts = list(patch_report.conflicts)
        report.warnings.append(
            "pyproject.toml has a non-canonical cu130 block; "
            "skipping removal — resolve manually"
        )
        return

    # state is CANONICAL.
    if dry_run:
        report.torch_config_action = TorchConfigAction.DRY_RUN
        return

    try:
        patch_report = torch_config.remove_patch(pyproject)
    except Exception as exc:
        logger.error("torch_config.remove_patch failed: %s", exc)
        report.torch_config_action = TorchConfigAction.ERROR
        report.warnings.append(f"torch-config write failed: {exc}")
        return
    report.torch_config_action = patch_report.action
    report.torch_config_conflicts = list(patch_report.conflicts)


def _rmtree_safe_onexc(_func, path, exc) -> None:
    """``shutil.rmtree`` error handler (Python 3.12+ ``onexc`` form)
    that unlinks symlinks instead of following them.

    Defensive secondary guard against the case where a symlink is
    encountered inside ``.vault/data/`` after the top-level
    ``is_symlink`` check has already passed. ``onerror`` was
    deprecated in 3.12; ``onexc`` receives the exception instance
    directly instead of an ``exc_info`` tuple.
    """
    p = Path(path)
    if p.is_symlink():
        try:
            p.unlink()
        except OSError as e:
            logger.warning("Failed to unlink symlink %s: %s", p, e)
        return
    # Re-raise the original error for non-symlink failures.
    raise exc
