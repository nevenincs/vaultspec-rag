"""Unified provisioning front door over the per-dependency backends.

A single opt-out orchestrator that drives the three external
dependencies vaultspec-rag needs - the cu130 torch configuration, the
Hugging Face embedding/reranker models, and the pinned Qdrant server
binary - through their existing backends and reports each step through
the shared sync vocabulary (``created`` / ``updated`` / ``unchanged`` /
``skipped`` / ``failed``, plus ``dry_run`` for the preview path).

This is a *front door*, not a rewrite: every step delegates to the
backend that already knows how to provision its dependency (the torch
configurator in :mod:`vaultspec_rag.torch_config`, the warmup
snapshot-download path, and the Qdrant runtime provisioner in
:mod:`vaultspec_rag.qdrant_runtime`). The orchestrator only sequences
them, maps their heterogeneous outcomes onto the shared vocabulary, and
surfaces the heterogeneity honestly - the torch step is two-phase (it
patches the consumer pyproject and needs a follow-up sync), so it
reports ``configured, sync pending`` distinct from a fetched binary's
``downloaded`` / ``unchanged``.

Default polarity is opt-out, matching the server-first default:
provisioning runs by default; ``local_only`` skips the Qdrant binary
(the headline escape hatch), and a finer ``skip`` set drops individual
steps. Every step is idempotent (re-running a satisfied dependency is
an ``unchanged`` no-op with no network) and honours ``dry_run``.

See the ADR ``2026-06-13-provisioning-setup-adr`` for the decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from ..qdrant_runtime import QdrantProvisionAction
    from ._models import ConfirmFn, InstallReport

logger = logging.getLogger(__name__)

__all__ = [
    "ProvisionAction",
    "ProvisionOutcome",
    "ProvisionStep",
    "ProvisionStepResult",
    "provision_dependencies",
    "provision_models",
]


class ProvisionStep(StrEnum):
    """The external dependencies the front door provisions.

    Each member is also the canonical token a caller passes in the
    ``skip`` set to opt that step out (e.g. ``skip={"torch"}``).
    """

    TORCH = "torch"
    MODELS = "models"
    QDRANT = "qdrant"


class ProvisionAction(StrEnum):
    """Shared sync vocabulary for a single provisioning step.

    Mirrors the project-wide vocabulary so JSON consumers can filter on
    the same strings the qdrant provisioner and torch configurator
    already emit. ``StrEnum`` members compare equal to their string
    value.

    Values:
        CREATED: the dependency was provisioned for the first time.
        UPDATED: an existing provision was replaced / advanced.
        UNCHANGED: a satisfied dependency; an idempotent no-op with no
            network.
        SKIPPED: the step did not run this invocation; ``detail``
            always carries the reason.
        FAILED: the step ran and failed; ``detail`` carries the cause.
        DRY_RUN: a preview that did not touch the network or disk.
    """

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    FAILED = "failed"
    DRY_RUN = "dry_run"


@dataclass
class ProvisionStepResult:
    """Honest outcome of one provisioning step.

    Attributes:
        step: Which dependency this result describes.
        action: The shared-vocabulary outcome.
        detail: Human-readable detail. Mandatory for ``SKIPPED`` (the
            reason) and ``FAILED`` (the cause); informational
            otherwise.
        sync_pending: True only for the torch step, which configures
            the consumer pyproject but cannot complete the install
            itself - the follow-up ``uv sync`` is the user's to run.
            This is the heterogeneity the front door reports honestly:
            a ``created``/``updated`` torch step with
            ``sync_pending=True`` reads as "configured, sync pending",
            distinct from a fetched binary that is fully done.
    """

    step: ProvisionStep
    action: ProvisionAction
    detail: str = ""
    sync_pending: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of this step result."""
        return {
            "step": str(self.step),
            "action": str(self.action),
            "detail": self.detail,
            "sync_pending": self.sync_pending,
        }


@dataclass
class ProvisionOutcome:
    """Heterogeneous per-dependency result of a front-door run.

    Holds one :class:`ProvisionStepResult` per dependency the front
    door considered (skipped steps included, so the report is complete).
    The aggregate :attr:`status` collapses the per-step actions into a
    single run outcome using the project's sync aggregation: ``failed``
    if any step failed, ``mixed`` if steps disagree, otherwise the
    common action.

    Attributes:
        steps: One result per considered dependency, in run order.
        dry_run: True when the whole run was a preview.
    """

    steps: list[ProvisionStepResult] = field(default_factory=list)
    dry_run: bool = False

    @property
    def status(self) -> str:
        """Collapse the per-step actions into one run-level outcome."""
        actions = {r.action for r in self.steps}
        if not actions:
            return "unchanged"
        if ProvisionAction.FAILED in actions:
            return str(ProvisionAction.FAILED)
        if len(actions) == 1:
            return str(next(iter(actions)))
        return "mixed"

    @property
    def ok(self) -> bool:
        """True when no step failed."""
        return all(r.action != ProvisionAction.FAILED for r in self.steps)

    def result_for(self, step: ProvisionStep) -> ProvisionStepResult | None:
        """Return the result for *step*, or ``None`` if not considered."""
        for result in self.steps:
            if result.step == step:
                return result
        return None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of the whole outcome."""
        return {
            "status": self.status,
            "dry_run": self.dry_run,
            "steps": [r.to_dict() for r in self.steps],
        }


def provision_dependencies(
    target: Path,
    *,
    local_only: bool = False,
    skip: set[str] | None = None,
    dry_run: bool = False,
    configure_torch: bool = True,
    assume_yes: bool = False,
    sync_after: bool = False,
    confirm: ConfirmFn | None = None,
) -> ProvisionOutcome:
    """Provision torch, models, and the Qdrant binary behind one door.

    Opt-out by default: every step runs unless opted out. ``local_only``
    is the headline escape hatch - it skips the Qdrant binary step (the
    runtime selection of the local store is the caller's concern). The
    finer ``skip`` set drops individual steps by their
    :class:`ProvisionStep` token (``"torch"`` / ``"models"`` /
    ``"qdrant"``). Each step delegates to its existing backend, is
    idempotent, and honours ``dry_run``.

    Args:
        target: Workspace whose ``pyproject.toml`` the torch step
            patches.
        local_only: When True, skip the Qdrant binary step entirely
            (reported as ``skipped`` with the local-only reason).
        skip: Per-dependency opt-out tokens; finer than ``local_only``.
        dry_run: Preview every step without touching the network or
            disk.
        configure_torch: When False, skip the torch step (mirrors the
            install command's existing flag).
        assume_yes: Bypass the torch-config confirmation prompt.
        sync_after: After a torch patch lands, run ``uv sync`` for
            torch. Off by default; the front door reports
            ``sync_pending`` regardless so the user knows the boundary.
        confirm: Optional confirmation callback for the torch step.

    Returns:
        A :class:`ProvisionOutcome` carrying one result per considered
        dependency.
    """
    skip = {s.lower() for s in (skip or set())}
    outcome = ProvisionOutcome(dry_run=dry_run)

    outcome.steps.append(
        _provision_torch(
            target=target,
            dry_run=dry_run,
            skip=skip,
            configure_torch=configure_torch,
            assume_yes=assume_yes,
            sync_after=sync_after,
            confirm=confirm,
        )
    )

    outcome.steps.append(provision_models(dry_run=dry_run, skip=skip))

    outcome.steps.append(
        _provision_qdrant(dry_run=dry_run, skip=skip, local_only=local_only)
    )

    return outcome


def _provision_torch(
    *,
    target: Path,
    dry_run: bool,
    skip: set[str],
    configure_torch: bool,
    assume_yes: bool,
    sync_after: bool,
    confirm: ConfirmFn | None,
) -> ProvisionStepResult:
    """Run the torch-config step and map it onto the shared vocabulary.

    The torch backend is two-phase: it patches the consumer pyproject
    but the follow-up ``uv sync`` completes the install. So a successful
    configuration reports ``configured, sync pending`` (sync_pending
    True) unless ``sync_after`` actually ran the sync. This is the
    heterogeneity the ADR requires the front door to surface honestly,
    distinct from a fetched binary's terminal ``downloaded``.
    """
    if not configure_torch or ProvisionStep.TORCH in skip:
        # Distinguish the two skip reasons so the report is not misread as an
        # operator opt-out when torch was simply configured by the dedicated step.
        if ProvisionStep.TORCH in skip:
            detail = (
                "torch configuration handled by the dedicated PyTorch step "
                "(it patches pyproject.toml; see 'PyTorch configuration' above) - "
                "not re-run here"
            )
        else:
            detail = (
                "torch configuration skipped by request - pyproject.toml was not "
                "patched with the cu130 index and source pin"
            )
        return ProvisionStepResult(
            step=ProvisionStep.TORCH,
            action=ProvisionAction.SKIPPED,
            detail=detail,
        )

    from ..torch_config import TorchConfigAction
    from ._models import InstallReport
    from ._torch_flow import _run_torch_config_install

    report = InstallReport(action="provision", target=target)
    _run_torch_config_install(
        target=target,
        report=report,
        dry_run=dry_run,
        force=False,
        configure_torch=True,
        assume_yes=assume_yes,
        sync_after=sync_after,
        confirm=confirm,
    )

    action = report.torch_config_action
    conflicts = ", ".join(report.torch_config_conflicts)

    if action == TorchConfigAction.DRY_RUN:
        return ProvisionStepResult(
            step=ProvisionStep.TORCH,
            action=ProvisionAction.DRY_RUN,
            detail="would configure the cu130 torch index and source pin",
            sync_pending=True,
        )
    if action == TorchConfigAction.APPLIED:
        # The pyproject is configured. The follow-up sync is the
        # second phase; it is pending unless sync_after actually ran it.
        synced = report.torch_sync_action != "skipped"
        return ProvisionStepResult(
            step=ProvisionStep.TORCH,
            action=ProvisionAction.CREATED,
            detail=(
                "configured cu130 torch index and source pin"
                if synced
                else "configured cu130 torch index and source pin; sync pending"
            ),
            sync_pending=not synced,
        )
    if action == TorchConfigAction.ALREADY:
        synced = report.torch_sync_action != "skipped"
        return ProvisionStepResult(
            step=ProvisionStep.TORCH,
            action=ProvisionAction.UNCHANGED,
            detail=(
                "torch already configured"
                if synced
                else "torch already configured; sync pending"
            ),
            sync_pending=not synced,
        )
    if action in {
        TorchConfigAction.DISABLED,
        TorchConfigAction.ABSENT,
        TorchConfigAction.DECLINED,
        TorchConfigAction.SKIPPED,
        TorchConfigAction.SKIPPED_NON_TTY,
        TorchConfigAction.SKIPPED_EOF,
    }:
        return ProvisionStepResult(
            step=ProvisionStep.TORCH,
            action=ProvisionAction.SKIPPED,
            detail=_torch_skip_reason(action, report),
        )
    # CONFLICT or ERROR.
    if action == TorchConfigAction.CONFLICT:
        detail = (
            "torch configuration conflict - pyproject.toml has a non-canonical "
            "(hand-edited) torch / cu130 index block the installer refused to "
            "overwrite" + (f": {conflicts}" if conflicts else "") + ". Remove the "
            "manual edit from pyproject.toml and re-run so the installer can apply "
            "the canonical cu130 configuration."
        )
    else:
        detail = (
            f"torch configuration {action}" + (f": {conflicts}" if conflicts else "")
        )
    return ProvisionStepResult(
        step=ProvisionStep.TORCH,
        action=ProvisionAction.FAILED,
        detail=detail,
    )


def _torch_skip_reason(action: object, report: InstallReport) -> str:
    """Pick the most specific skip reason from the torch report."""
    if report.warnings:
        return report.warnings[-1]
    return f"torch configuration {action}"


def provision_models(
    *,
    dry_run: bool = False,
    skip: set[str] | None = None,
) -> ProvisionStepResult:
    """Ensure the configured embedding/reranker models are present.

    Reuses the warmup snapshot-download path: for each configured repo
    (dense, sparse, reranker) it checks the Hugging Face cache via
    ``try_to_load_from_cache`` - the same idempotency probe the
    ``server warmup`` verb uses - and downloads only the repos that are
    absent. Idempotent: a fully-cached set reports ``unchanged`` with no
    network; a download reports ``created``.

    No GPU or model load happens here - this only fetches the snapshot
    files, exactly like warmup's download loop, so it is safe to run in
    a provisioning front door that must not touch the single GPU.

    Args:
        dry_run: Report what would be fetched without touching the
            network.
        skip: When it contains ``"models"``, the step is opted out.

    Returns:
        A :class:`ProvisionStepResult` in the shared sync vocabulary.
    """
    skip = {s.lower() for s in (skip or set())}
    if ProvisionStep.MODELS in skip:
        return ProvisionStepResult(
            step=ProvisionStep.MODELS,
            action=ProvisionAction.SKIPPED,
            detail="model provisioning opted out",
        )

    try:
        from huggingface_hub import (
            snapshot_download,  # pyright: ignore[reportUnknownVariableType]  # huggingface_hub stubs partially unknown
            try_to_load_from_cache,
        )
    except ImportError:
        return ProvisionStepResult(
            step=ProvisionStep.MODELS,
            action=ProvisionAction.SKIPPED,
            detail="huggingface_hub is not installed; cannot ensure models",
        )

    from ..config import get_config

    cfg = get_config()
    repos = [
        str(cfg.embedding_model),
        str(cfg.sparse_model),
        str(cfg.reranker_model),
    ]

    missing = [
        repo for repo in repos if try_to_load_from_cache(repo, "config.json") is None
    ]

    if not missing:
        return ProvisionStepResult(
            step=ProvisionStep.MODELS,
            action=ProvisionAction.UNCHANGED,
            detail=f"all {len(repos)} model repos already cached",
        )

    if dry_run:
        return ProvisionStepResult(
            step=ProvisionStep.MODELS,
            action=ProvisionAction.DRY_RUN,
            detail=f"would download {len(missing)} missing model repo(s): "
            + ", ".join(missing),
        )

    downloaded: list[str] = []
    for repo in missing:
        try:
            snapshot_download(repo)
        except Exception as exc:
            logger.error("model provisioning failed for %s: %s", repo, exc)
            return ProvisionStepResult(
                step=ProvisionStep.MODELS,
                action=ProvisionAction.FAILED,
                detail=f"failed to download {repo}: {exc}",
            )
        downloaded.append(repo)

    return ProvisionStepResult(
        step=ProvisionStep.MODELS,
        action=ProvisionAction.CREATED,
        detail=f"downloaded {len(downloaded)} model repo(s): " + ", ".join(downloaded),
    )


def _provision_qdrant(
    *,
    dry_run: bool,
    skip: set[str],
    local_only: bool,
) -> ProvisionStepResult:
    """Delegate to the Qdrant runtime provisioner and map its action.

    Preserves the provisioner's verify-before-execute security contract
    untouched - this is a pure delegation that only translates the
    returned :class:`QdrantProvisionAction` onto the front door's
    vocabulary.
    """
    if local_only:
        return ProvisionStepResult(
            step=ProvisionStep.QDRANT,
            action=ProvisionAction.SKIPPED,
            detail="--local-only selected; using the on-disk store, no binary",
        )
    if ProvisionStep.QDRANT in skip:
        return ProvisionStepResult(
            step=ProvisionStep.QDRANT,
            action=ProvisionAction.SKIPPED,
            detail="qdrant binary provisioning opted out",
        )

    from ..qdrant_runtime import provision

    report = provision(dry_run=dry_run)
    return ProvisionStepResult(
        step=ProvisionStep.QDRANT,
        action=_map_qdrant_action(report.action),
        detail=report.message or _qdrant_default_detail(report.action),
    )


def _map_qdrant_action(action: QdrantProvisionAction) -> ProvisionAction:
    """Map the qdrant provisioner's action onto the shared vocabulary.

    The qdrant vocabulary already mirrors the shared one one-for-one,
    so this is a direct value translation that keeps the front door's
    enum the single contract surface callers filter on.
    """
    from ..qdrant_runtime import QdrantProvisionAction

    mapping = {
        QdrantProvisionAction.CREATED: ProvisionAction.CREATED,
        QdrantProvisionAction.UPDATED: ProvisionAction.UPDATED,
        QdrantProvisionAction.UNCHANGED: ProvisionAction.UNCHANGED,
        QdrantProvisionAction.SKIPPED: ProvisionAction.SKIPPED,
        QdrantProvisionAction.FAILED: ProvisionAction.FAILED,
        QdrantProvisionAction.DRY_RUN: ProvisionAction.DRY_RUN,
    }
    return mapping[action]


def _qdrant_default_detail(action: QdrantProvisionAction) -> str:
    """Provide a detail line when the provisioner left ``message`` empty."""
    from ..qdrant_runtime import QdrantProvisionAction

    if action == QdrantProvisionAction.CREATED:
        return "downloaded and verified the pinned qdrant binary"
    if action == QdrantProvisionAction.UPDATED:
        return "replaced the qdrant binary with the pinned version"
    if action == QdrantProvisionAction.UNCHANGED:
        return "verified qdrant binary already present"
    return ""
