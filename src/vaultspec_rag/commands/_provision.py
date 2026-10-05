"""Unified provisioning front door over the per-dependency backends.

A single opt-out orchestrator that drives the three external
dependencies vaultspec-rag needs - the cu130 torch configuration, the
Hugging Face embedding/reranker models, and the pinned Qdrant server
binary - through their existing backends and reports each step through
the shared sync vocabulary (``created`` / ``updated`` / ``unchanged`` /
``skipped`` / ``failed``, plus ``dry_run`` for the preview path).

This is a *front door*, not a rewrite: every step delegates to the
backend that already knows how to provision its dependency (the torch
configurator in :mod:`vaultspec_rag.torch_config`, the model fetch in
:mod:`._model_fetch`, and the Qdrant runtime provisioner in
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

Only a host installation provisions. A client loads no model and never
runs the service, so every step answers ``skipped`` for it before its
backend is reached, whichever command asked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, Unpack

from .._sync_vocabulary import ProvisionAction

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path

    from ..qdrant_runtime._constants import ProvisionReport
    from ._model_fetch import ModelRepoResult
    from ._models import ConfirmFn, InstallReport

logger = logging.getLogger(__name__)

_CLIENT_SKIP = (
    "not needed by a client installation; the host installation that runs "
    "the service provides it"
)

#: Machine-readable reasons the Qdrant step failed for want of a binary. A
#: binary that resolves but may not run carries the resolver's own code.
QDRANT_MISSING = "qdrant_missing"
QDRANT_PROVISION_FAILED = "qdrant_provision_failed"


class ProvisionProgress(Protocol):
    """Where the front door reports a fetch while it runs.

    Defined here, by the code that reports, so the front door depends on no
    console: a command supplies an implementation over whatever it prints to,
    and a caller with nothing to print to supplies none.
    """

    def stage(self, label: str) -> None:
        """Declare the activity now running."""

    def download(self, heading: str) -> AbstractContextManager[type[Any] | None]:
        """Report one model snapshot download for the duration of the block.

        The block yields the progress-bar class to hand the hub, which is the
        only seam the hub reports byte and file counts through, or ``None`` to
        leave the hub's own reporting in place.
        """
        ...


class _ProvisionOptions(TypedDict, total=False):
    local_only: bool
    skip: set[str] | None
    dry_run: bool
    configure_torch: bool
    assume_yes: bool
    sync_after: bool
    confirm: ConfirmFn | None
    progress: ProvisionProgress | None


@dataclass(frozen=True)
class _ProvisionRequest:
    target: Path
    local_only: bool = False
    skip: set[str] | None = None
    dry_run: bool = False
    configure_torch: bool = True
    assume_yes: bool = False
    sync_after: bool = False
    confirm: ConfirmFn | None = None
    progress: ProvisionProgress | None = None


@dataclass(frozen=True)
class _TorchProvisionRequest:
    target: Path
    dry_run: bool
    skip: set[str]
    configure_torch: bool
    assume_yes: bool
    sync_after: bool
    confirm: ConfirmFn | None


__all__ = [
    "QDRANT_MISSING",
    "QDRANT_PROVISION_FAILED",
    "ModelsStepResult",
    "ProvisionOutcome",
    "ProvisionProgress",
    "ProvisionStep",
    "ProvisionStepResult",
    "client_skip",
    "ensure_runtime_dependencies",
    "provision_dependencies",
    "provision_models",
    "provision_qdrant_binary",
]


class ProvisionStep(StrEnum):
    """The external dependencies the front door provisions.

    Each member is also the canonical token a caller passes in the
    ``skip`` set to opt that step out (e.g. ``skip={"torch"}``).
    """

    TORCH = "torch"
    MODELS = "models"
    QDRANT = "qdrant"


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
        code: A stable machine-readable reason for a ``FAILED`` step, for a
            caller that must report the failure under its own name; empty
            when the step has none.
    """

    step: ProvisionStep
    action: ProvisionAction
    detail: str = ""
    sync_pending: bool = False
    code: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of this step result."""
        return {
            "step": str(self.step),
            "action": str(self.action),
            "detail": self.detail,
            "sync_pending": self.sync_pending,
            "code": self.code,
        }


@dataclass
class ModelsStepResult(ProvisionStepResult):
    """The model step's outcome, with what happened to each repository.

    Attributes:
        repos: One result per configured model repository, in inventory
            order; empty when the step did not reach the cache at all.
    """

    repos: tuple[ModelRepoResult, ...] = ()


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

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of the whole outcome."""
        return {
            "status": self.status,
            "dry_run": self.dry_run,
            "steps": [r.to_dict() for r in self.steps],
        }


def client_skip(step: ProvisionStep) -> ProvisionStepResult | None:
    """Answer *step* as skipped when this installation is a client.

    Asked ahead of every step's backend, so no entry point can provision for a
    client by reaching a step some other way. The role is read through the
    module rather than bound at import, which is the one reading a caller can
    pin.
    """
    from ..operator_state import _compute
    from ..operator_state._installation import InstallRole

    if _compute.installed_role()[0] is InstallRole.HOST:
        return None
    return ProvisionStepResult(step, ProvisionAction.SKIPPED, _CLIENT_SKIP)


def provision_dependencies(
    target: Path,
    **options: Unpack[_ProvisionOptions],
) -> ProvisionOutcome:
    """Provision torch, models, and the Qdrant binary behind one door."""
    return _provision_dependencies(_ProvisionRequest(target, **options))


def _provision_dependencies(request: _ProvisionRequest) -> ProvisionOutcome:
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
        progress: Where the model and Qdrant fetches report while they run;
            silent when omitted.

    Returns:
        A :class:`ProvisionOutcome` carrying one result per considered
        dependency.
    """
    (
        target,
        local_only,
        skip,
        dry_run,
        configure_torch,
        assume_yes,
        sync_after,
        confirm,
        progress,
    ) = (
        request.target,
        request.local_only,
        request.skip,
        request.dry_run,
        request.configure_torch,
        request.assume_yes,
        request.sync_after,
        request.confirm,
        request.progress,
    )
    skip = {s.lower() for s in (skip or set())}
    outcome = ProvisionOutcome(dry_run=dry_run)

    outcome.steps.append(
        client_skip(ProvisionStep.TORCH)
        or _provision_torch(
            _TorchProvisionRequest(
                target,
                dry_run,
                skip,
                configure_torch,
                assume_yes,
                sync_after,
                confirm,
            )
        )
    )

    outcome.steps.append(
        provision_models(dry_run=dry_run, skip=skip, progress=progress)
    )

    outcome.steps.append(
        _provision_qdrant(
            dry_run=dry_run, skip=skip, local_only=local_only, progress=progress
        )
    )

    return outcome


def _provision_torch(request: _TorchProvisionRequest) -> ProvisionStepResult:
    """Run the torch-config step and map it onto the shared vocabulary.

    The torch backend is two-phase: it patches the consumer pyproject
    but the follow-up ``uv sync`` completes the install. So a successful
    configuration reports ``configured, sync pending`` (sync_pending
    True) unless ``sync_after`` actually ran the sync. The front door must
    surface this heterogeneity honestly, distinct from a fetched binary's
    terminal ``downloaded``.
    """
    (
        target,
        dry_run,
        skip,
        configure_torch,
        assume_yes,
        sync_after,
        confirm,
    ) = (
        request.target,
        request.dry_run,
        request.skip,
        request.configure_torch,
        request.assume_yes,
        request.sync_after,
        request.confirm,
    )
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

    from ..torch_config._constants import TorchConfigAction
    from ._models import InstallReport
    from ._torch_flow import TorchInstallOptions, _run_torch_config_install

    report = InstallReport(action="provision", target=target)
    _run_torch_config_install(
        target=target,
        report=report,
        options=TorchInstallOptions(
            dry_run=dry_run,
            configure_torch=True,
            assume_yes=assume_yes,
            sync_after=sync_after,
            confirm=confirm,
        ),
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
        TorchConfigAction.NOT_APPLICABLE,
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
        detail = f"torch configuration {action}" + (
            f": {conflicts}" if conflicts else ""
        )
    return ProvisionStepResult(
        step=ProvisionStep.TORCH,
        action=ProvisionAction.FAILED,
        detail=detail,
    )


def _torch_skip_reason(action: object, report: InstallReport) -> str:
    """Pick the most specific skip reason from the torch report."""
    from ..operator_state._installation import ComputeCapability
    from ..torch_config._constants import TorchConfigAction

    if action == TorchConfigAction.NOT_APPLICABLE:
        return f"torch configuration {ComputeCapability.NOT_APPLICABLE.label}"
    if report.warnings:
        return report.warnings[-1]
    return f"torch configuration {action}"


def provision_models(
    *,
    dry_run: bool = False,
    skip: set[str] | None = None,
    progress: ProvisionProgress | None = None,
) -> ModelsStepResult:
    """Ensure the configured embedding and reranker models are cached.

    The model step of the front door, and the one way any command reaches the
    model fetch: ``install``, ``server warmup``, and the preflight of
    ``server start`` all call this. A client is answered ``skipped`` before
    the cache is probed.

    No model is constructed and no GPU is touched - only snapshot files are
    fetched - so it is safe on a path that must not load torch.

    Args:
        dry_run: Report what would be fetched without touching the
            network.
        skip: When it contains ``"models"``, the step is opted out.
        progress: Where to report the cache probe and each download while
            they run; silent when omitted.

    Returns:
        The step's outcome in the shared sync vocabulary, with one result per
        configured repository when the cache was reached.
    """
    client = client_skip(ProvisionStep.MODELS)
    if client is not None:
        return ModelsStepResult(client.step, client.action, client.detail)
    if ProvisionStep.MODELS in {s.lower() for s in (skip or set())}:
        return ModelsStepResult(
            step=ProvisionStep.MODELS,
            action=ProvisionAction.SKIPPED,
            detail="model provisioning opted out",
        )

    from ._model_fetch import fetch_models

    fetched = fetch_models(dry_run=dry_run, progress=progress)
    return ModelsStepResult(
        step=ProvisionStep.MODELS,
        action=fetched.action,
        detail=fetched.detail,
        code=fetched.code,
        repos=fetched.repos,
    )


def ensure_runtime_dependencies(
    *,
    local_only: bool,
    qdrant_auto_provision: bool,
    progress: ProvisionProgress | None = None,
) -> ProvisionOutcome:
    """Fetch what a daemon needs and does not have, before it is spawned.

    The narrower entry ``server start`` uses: the two fetch-and-go
    dependencies, in the order the daemon needs them, through the same steps
    ``install`` runs. Torch is not among them - the environment that runs the
    daemon is judged, never changed, by a start. The sequence stops at the
    first step that fails, so a host that cannot get its models is not also
    sent to download a server it cannot use yet.

    Args:
        local_only: The on-disk store is selected, so no Qdrant server is
            needed.
        qdrant_auto_provision: Whether an absent Qdrant server may be
            downloaded. Off, an absent server is a failure naming the install
            command.
        progress: Where the fetches report while they run; silent when
            omitted.

    Returns:
        One result per step that ran, in order.
    """
    outcome = ProvisionOutcome()
    models = provision_models(progress=progress)
    outcome.steps.append(models)
    if models.action == ProvisionAction.FAILED:
        return outcome
    outcome.steps.append(
        _provision_qdrant(
            dry_run=False,
            skip=set(),
            local_only=local_only,
            auto_provision=qdrant_auto_provision,
            progress=progress,
        )
    )
    return outcome


def _provision_qdrant(
    *,
    dry_run: bool,
    skip: set[str],
    local_only: bool,
    auto_provision: bool = True,
    progress: ProvisionProgress | None = None,
) -> ProvisionStepResult:
    """Ensure a Qdrant server binary resolves and may run, fetching one if not.

    A binary that already resolves is checked against what its source holds it
    to and left alone; that includes one the operator named, which is never
    replaced by a download. Only when nothing resolves is the pinned release
    provisioned, and only when ``auto_provision`` allows it. The provisioner's
    verify-before-execute contract is untouched: it reports in the shared
    vocabulary, so there is nothing to translate.
    """
    client = client_skip(ProvisionStep.QDRANT)
    if client is not None:
        return client
    if local_only:
        return ProvisionStepResult(
            step=ProvisionStep.QDRANT,
            action=ProvisionAction.SKIPPED,
            detail="the on-disk local-only store is selected; no Qdrant server "
            "binary is needed",
        )
    if ProvisionStep.QDRANT in skip:
        return ProvisionStepResult(
            step=ProvisionStep.QDRANT,
            action=ProvisionAction.SKIPPED,
            detail="qdrant binary provisioning opted out",
        )
    present = _resolved_qdrant()
    if present is not None:
        return present
    if not auto_provision:
        return ProvisionStepResult(
            step=ProvisionStep.QDRANT,
            action=ProvisionAction.FAILED,
            detail="the managed Qdrant server is not installed and automatic "
            "download is switched off; run: vaultspec-rag server qdrant install",
            code=QDRANT_MISSING,
        )
    return _download_qdrant(dry_run=dry_run, progress=progress)


def _resolved_qdrant() -> ProvisionStepResult | None:
    """Answer for a binary that already resolves, or ``None`` when none does.

    The binary is held to its source's check here, in the foreground, so one
    that may not run is refused where an operator sees the reason rather than
    in the service log after the daemon has been spawned. An operator-supplied
    binary is named as such in the detail: no committed pin vouches for it,
    and that has to be visible wherever the outcome is shown.
    """
    from ..config._types import EnvVar
    from ..qdrant_runtime._constants import BinarySource
    from ..qdrant_runtime._resolve import (
        QdrantBinaryError,
        resolve_binary,
        verify_resolved_binary,
    )

    try:
        resolved = resolve_binary()
        if resolved is None:
            return None
        verify_resolved_binary(resolved)
    except QdrantBinaryError as exc:
        return ProvisionStepResult(
            step=ProvisionStep.QDRANT,
            action=ProvisionAction.FAILED,
            detail=str(exc),
            code=exc.error,
        )
    if resolved.source is BinarySource.OPERATOR_SETTING:
        detail = (
            f"operator-supplied binary {resolved.path} (source: "
            f"{resolved.source.value}, named by {EnvVar.QDRANT_BINARY.value}); "
            "no checksum pin applies and it runs as named"
        )
    elif resolved.source.operator_supplied:
        detail = (
            f"operator-supplied binary {resolved.path} (source: "
            f"{resolved.source.value}); verified against the digest recorded "
            "when it was registered"
        )
    else:
        detail = _qdrant_default_detail(ProvisionAction.UNCHANGED)
    return ProvisionStepResult(
        step=ProvisionStep.QDRANT,
        action=ProvisionAction.UNCHANGED,
        detail=detail,
    )


def _download_qdrant(
    *, dry_run: bool, progress: ProvisionProgress | None
) -> ProvisionStepResult:
    """Provision the pinned release and confirm that it now resolves."""
    from ..qdrant_runtime._resolve import resolve_binary

    # A first-use provision downloads and verifies a native archive over the
    # network, which is the longest stall a first start can hit. The stage line
    # says it started; the provisioner's own lines carry the byte counts
    # underneath it, so a slow link is distinguishable from a wedged one.
    if progress is not None and not dry_run:
        progress.stage("Downloading the Qdrant server (first use)...")
    report = provision_qdrant_binary(
        dry_run=dry_run, on_progress=None if progress is None else progress.stage
    )
    if report.action == ProvisionAction.FAILED:
        return ProvisionStepResult(
            step=ProvisionStep.QDRANT,
            action=ProvisionAction.FAILED,
            detail=report.message,
            code=QDRANT_PROVISION_FAILED,
        )
    if report.action != ProvisionAction.DRY_RUN and resolve_binary() is None:
        return ProvisionStepResult(
            step=ProvisionStep.QDRANT,
            action=ProvisionAction.FAILED,
            detail="provisioning reported success but no Qdrant server binary "
            "resolves afterwards; run: vaultspec-rag server qdrant install "
            "--upgrade",
            code=QDRANT_PROVISION_FAILED,
        )
    return ProvisionStepResult(
        step=ProvisionStep.QDRANT,
        action=report.action,
        detail=report.message or _qdrant_default_detail(report.action),
    )


def provision_qdrant_binary(
    *,
    upgrade: bool = False,
    dry_run: bool = False,
    binary: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> ProvisionReport:
    """Provision the pinned Qdrant server binary, on a host installation only.

    The one way any command reaches the Qdrant provisioner, so the role is
    judged in one place: a client gets a ``skipped`` report and the
    provisioner - its download, its staging directory, and the registration of
    an operator binary alike - is never entered.

    Args:
        upgrade: Replace an install that no longer matches the pin.
        dry_run: Report what would happen without network or disk effects.
        binary: Operator-supplied executable to register instead of
            downloading.
        on_progress: Sink for stage and byte-progress lines; silent when
            omitted.

    Returns:
        The provisioner's report, or a ``skipped`` report for a client.
    """
    client = client_skip(ProvisionStep.QDRANT)
    if client is not None:
        from ..qdrant_runtime._constants import ProvisionReport

        return ProvisionReport(action=client.action, message=client.detail)

    from ..qdrant_runtime._provision import provision

    if on_progress is None:
        return provision(upgrade=upgrade, dry_run=dry_run, binary=binary)
    return provision(
        upgrade=upgrade, dry_run=dry_run, binary=binary, on_progress=on_progress
    )


def _qdrant_default_detail(action: ProvisionAction) -> str:
    """Provide a detail line when the provisioner left ``message`` empty."""
    from .._sync_vocabulary import ProvisionAction

    if action == ProvisionAction.CREATED:
        return "downloaded and verified the pinned qdrant binary"
    if action == ProvisionAction.UPDATED:
        return "replaced the qdrant binary with the pinned version"
    if action == ProvisionAction.UNCHANGED:
        return "verified qdrant binary already present"
    return ""
