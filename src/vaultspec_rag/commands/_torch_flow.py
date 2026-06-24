"""The cu130 torch-config sub-flow shared by install and uninstall."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .. import torch_config
from ..torch_config import TorchConfigAction
from ._util import _exception_caused_by
from ._uv_sync import _run_uv_sync_torch

if TYPE_CHECKING:
    from pathlib import Path

    from ._models import ConfirmFn, InstallReport, UninstallReport

logger = logging.getLogger(__name__)

__all__ = ["_run_torch_config_install", "_run_torch_config_uninstall"]


def _confirm_torch_patch(
    pyproject: Path,
    report: InstallReport,
    assume_yes: bool,
    force: bool,
    confirm: ConfirmFn | None,
) -> bool:
    effective_assume_yes = assume_yes or force
    if not effective_assume_yes:
        if confirm is None:
            report.torch_config_action = TorchConfigAction.SKIPPED_NON_TTY
            report.warnings.append(
                "torch-config patch requires confirmation - pass --yes "
                "(or --force) to apply, or --no-torch-config to opt out. "
                "See pyproject.toml shape in `vaultspec-rag install --help`."
            )
            return False
        try:
            approved = confirm(
                f"Patch {pyproject} with the cu130 torch index? "
                f"This lets uv resolve the CUDA torch wheel."
            )
        except KeyboardInterrupt:
            report.torch_config_action = TorchConfigAction.DECLINED
            report.warnings.append("torch-config patch declined by user")
            return False
        except EOFError:
            report.torch_config_action = TorchConfigAction.SKIPPED_EOF
            report.warnings.append(
                "torch-config patch skipped: confirmation prompt hit EOF "
                "(non-interactive stdin). Re-run with --yes or --force "
                "to apply, or --no-torch-config to opt out."
            )
            return False
        except Exception as exc:
            if _exception_caused_by(exc, EOFError):
                report.torch_config_action = TorchConfigAction.SKIPPED_EOF
                report.warnings.append(
                    "torch-config patch skipped: confirmation prompt hit EOF "
                    "(non-interactive stdin). Re-run with --yes or --force "
                    "to apply, or --no-torch-config to opt out."
                )
                return False
            logger.warning(
                "torch-config confirm() raised %s: %s", type(exc).__name__, exc
            )
            report.torch_config_action = TorchConfigAction.DECLINED
            report.warnings.append(
                f"torch-config patch skipped: confirm prompt raised "
                f"{type(exc).__name__}. Re-run with --yes or --force to bypass "
                f"the prompt, or --no-torch-config to opt out."
            )
            return False
        if not approved:
            report.torch_config_action = TorchConfigAction.DECLINED
            report.warnings.append(
                "torch-config patch declined; "
                "re-run with --yes or --force to apply, "
                "or --no-torch-config to opt out."
            )
            return False
    return True


def _handle_canonical_state(
    pyproject: Path,
    target: Path,
    report: InstallReport,
    sync_after: bool,
    torch_group: str | None,
) -> None:
    report.torch_config_action = TorchConfigAction.ALREADY
    _ensure_torch_direct_dep(pyproject, report, torch_group)
    if sync_after and report.torch_direct_dep_action in {"already", "applied"}:
        _run_uv_sync_torch(target=target, report=report)


def _handle_customised_state(pyproject: Path, report: InstallReport) -> None:
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
        "skipping patch - resolve manually or run with different flags"
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
    torch_group: str | None = None,
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
        _handle_canonical_state(pyproject, target, report, sync_after, torch_group)
        return
    if state == torch_config.TorchConfigState.CUSTOMISED:
        _handle_customised_state(pyproject, report)
        return

    # state is MISSING.
    if dry_run:
        report.torch_config_action = TorchConfigAction.DRY_RUN
        if not torch_config.has_direct_torch_dep(pyproject)[0]:
            preview_location = (
                f"[dependency-groups].{torch_group}"
                if torch_group is not None
                else "[project].dependencies"
            )
            report.warnings.append(
                "(dry-run preview) torch-config would add "
                f"direct dependency `{torch_config.DIRECT_TORCH_REQUIREMENT}` to "
                f"{preview_location} so uv applies the cu130 source pin."
            )
            if torch_group is not None:
                report.warnings.append(_inert_pin_warning(torch_group))
        return

    if not _confirm_torch_patch(pyproject, report, assume_yes, force, confirm):
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

    # The patch landed; the workspace is now in CANONICAL state. Ensure
    # torch is also a direct dependency so uv actually applies the source pin.
    _ensure_torch_direct_dep(pyproject, report, torch_group)

    if sync_after and report.torch_direct_dep_action in {"already", "applied"}:
        _run_uv_sync_torch(target=target, report=report)


def _inert_pin_warning(torch_group: str) -> str:
    """Operator guidance for a group-placed dep whose pin is otherwise inert.

    uv applies a ``[tool.uv.sources]`` pin to a group dependency only
    when that group is enabled for the resolve, so a group-placed torch
    is a silently inert pin until the operator enables the group.
    """
    return (
        f"torch was added to [dependency-groups].{torch_group}; enable that "
        f"group for the resolve (`uv sync --group {torch_group}` or a "
        "configured default group) for the cu130 source pin to apply."
    )


def _ensure_torch_direct_dep(
    pyproject: Path, report: InstallReport, torch_group: str | None = None
) -> None:
    """Make the direct ``torch`` dependency match the cu130 source pin.

    With ``torch_group`` set, the managed dep is placed in the named PEP
    735 group instead of ``[project].dependencies`` so torch stays out
    of a dev-only consumer's published metadata. Migration is out of
    scope: when torch is already managed in a surface other than the
    requested group target, the existing placement is left untouched and
    a warning explains it will not be moved.
    """
    dep_report = torch_config.ensure_direct_torch_dep(
        pyproject, torch_group=torch_group
    )
    report.torch_direct_dep_action = dep_report.action
    report.torch_direct_dep_location = dep_report.location
    report.torch_config_conflicts.extend(dep_report.conflicts)
    if dep_report.action == "applied":
        report.warnings.append(
            f"added direct dependency `{torch_config.DIRECT_TORCH_REQUIREMENT}` to "
            f"{dep_report.location} so uv applies the cu130 torch source pin."
        )
        if torch_group is not None:
            report.warnings.append(_inert_pin_warning(torch_group))
    elif dep_report.action == "already":
        # torch is already a direct dep somewhere. When a group target was
        # requested and the existing placement differs, do not migrate -
        # warn that the existing placement wins. The placement may be a
        # user-declared (unmarked) torch, which we never touch regardless.
        if torch_group is not None:
            requested = f"[dependency-groups].{torch_group}"
            if dep_report.location != requested:
                report.warnings.append(
                    f"torch is already a direct dependency in "
                    f"{dep_report.location}; vaultspec-rag will NOT migrate it "
                    f"to {requested}. Remove it from {dep_report.location} "
                    f"first if you want it managed in the group."
                )
            else:
                # Already in the requested group: still remind the operator to
                # enable it so the pin is not silently inert on a re-run.
                report.warnings.append(_inert_pin_warning(torch_group))
    elif dep_report.action == "conflict":
        report.warnings.append(
            "torch-config patched, but vaultspec-rag could not add the direct "
            "torch dependency automatically; resolve pyproject.toml manually."
        )


def _run_torch_config_uninstall(
    *,
    target: Path,
    report: UninstallReport,
    dry_run: bool,
) -> None:
    """Remove the cu130 torch-config block from the consumer pyproject.

    Always attempts symmetric reversal - silent no-op when state is
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
        # remove_patch is safe to call on CUSTOMISED - it short-circuits
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
            "skipping removal - resolve manually"
        )
        return

    # state is CANONICAL.
    if dry_run:
        report.torch_config_action = TorchConfigAction.DRY_RUN
        report.torch_direct_dep_action = "dry_run"
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
    if patch_report.action == TorchConfigAction.REMOVED:
        dep_report = torch_config.remove_managed_direct_torch_dep(pyproject)
        report.torch_direct_dep_action = dep_report.action
        report.torch_direct_dep_location = dep_report.location
        report.torch_config_conflicts.extend(dep_report.conflicts)
        if dep_report.action == "removed":
            report.warnings.append(
                "removed vaultspec-rag managed "
                f"`{torch_config.DIRECT_TORCH_REQUIREMENT}` from "
                f"{dep_report.location}."
            )
