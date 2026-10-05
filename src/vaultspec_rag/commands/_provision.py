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

The model files and the Qdrant server are fetched only for an environment
that can run the service. Each of those steps asks the one judgement of
that, the same one a start makes, before its backend is reached, whichever
command asked. A client is answered ``skipped`` because it never runs the
service, and a host whose accelerator stack is not usable yet is answered
``skipped`` with the reason and the command that fetches them later. The
torch step is the exception by necessity: it is what makes a host able to
run the service, so it is gated on the installation role alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, TypedDict, Unpack

from .._sync_vocabulary import ProvisionAction

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ..config._settings import VaultSpecConfigWrapper
    from ..operator_state._service_environment import ServiceEnvironment
    from ..qdrant_runtime._constants import ProvisionReport
    from ..qdrant_runtime._resolve import QdrantBinaryError
    from ._model_fetch import ModelRepoResult
    from ._models import ConfirmFn, InstallReport
    from ._snapshot_progress import SnapshotCounts

logger = logging.getLogger(__name__)

_CLIENT_SKIP = (
    "not needed by a client installation; the host installation that runs "
    "the service provides it"
)

#: Why the Qdrant step fetches nothing when the on-disk store is the backend.
LOCAL_STORE_SELECTED = (
    "the on-disk local-only store is selected; no Qdrant server binary is needed"
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

    def downloading(self, heading: str, counts: SnapshotCounts) -> None:
        """Report how far the model snapshot download named *heading* has got.

        Called whenever the counts change. The download itself runs in another
        process, so counts are all that reaches here.
        """


class _ProvisionOptions(TypedDict, total=False):
    local_only: bool
    skip: set[str] | None
    dry_run: bool
    configure_torch: bool
    assume_yes: bool
    sync_after: bool
    confirm: ConfirmFn | None
    progress: ProvisionProgress | None
    environment: ServiceEnvironment | None


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
    environment: ServiceEnvironment | None = None


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
    "LOCAL_STORE_SELECTED",
    "QDRANT_MISSING",
    "QDRANT_PROVISION_FAILED",
    "BackendDecision",
    "ModelsStepResult",
    "ProvisionOutcome",
    "ProvisionProgress",
    "ProvisionStep",
    "ProvisionStepResult",
    "SavedBackend",
    "client_skip",
    "decide_backend",
    "ensure_runtime_dependencies",
    "managed_server_unneeded",
    "provision_dependencies",
    "provision_models",
    "provision_qdrant_binary",
    "unable_skip",
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


@dataclass(frozen=True, slots=True)
class SavedBackend:
    """What an install did about the saved backend choice.

    Attributes:
        saved: Whether this run wrote the choice.
        local_only: The choice written, or ``None`` when nothing was.
        detail: Why it was or was not written, and what a plain
            ``server start`` will therefore do.
    """

    saved: bool
    local_only: bool | None
    detail: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of the saved choice."""
        return {
            "saved": self.saved,
            "local_only": self.local_only,
            "detail": self.detail,
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
        backend: What the run did about the saved backend choice; ``None``
            for a run that has no part in saving one, which is every run
            but an install's.
    """

    steps: list[ProvisionStepResult] = field(default_factory=list)
    dry_run: bool = False
    backend: SavedBackend | None = None

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
            "backend": None if self.backend is None else self.backend.to_dict(),
        }


def client_skip(step: ProvisionStep) -> ProvisionStepResult | None:
    """Answer *step* as skipped when this installation is a client.

    The gate of the torch step alone. That step is what gives a host its
    accelerator stack, so it cannot wait for the stack to be usable, and the
    installation role is all there is to ask. The role is read through the
    module rather than bound at import, which is the one reading a caller can
    pin.
    """
    from ..operator_state import _compute
    from ..operator_state._installation import InstallRole

    if _compute.installed_role()[0] is InstallRole.HOST:
        return None
    return ProvisionStepResult(step, ProvisionAction.SKIPPED, _CLIENT_SKIP)


def unable_skip(
    step: ProvisionStep, environment: ServiceEnvironment | None
) -> ProvisionStepResult | None:
    """Answer *step* as skipped when this environment cannot run the service.

    Asked ahead of the model and Qdrant backends, so no entry point can fetch
    either for an environment that has no use for it by reaching a step some
    other way. A caller that has already judged the environment passes its
    verdict, so one command asks once; a caller that has not leaves it out
    and the judgement is made here.

    A client is told it needs nothing. A host that cannot run the service yet
    is told why, what repairs it, and that a start fetches what was skipped:
    this is the ordinary state of a project whose torch configuration was
    just written and not yet synced, and it is not a failure.
    """
    from ..operator_state._service_environment import judge_service_environment

    judged = judge_service_environment() if environment is None else environment
    if judged.can_run_service:
        return None
    if judged.is_client:
        return ProvisionStepResult(step, ProvisionAction.SKIPPED, _CLIENT_SKIP)
    repair = judged.capability.remediation
    return ProvisionStepResult(
        step,
        ProvisionAction.SKIPPED,
        f"not fetched, because this environment cannot run the service yet: "
        f"{judged.reason}. "
        + (f"{repair} " if repair else "")
        + "`vaultspec-rag server start` fetches it once the environment is ready",
    )


@dataclass(frozen=True, slots=True)
class BackendDecision:
    """The storage backend one command selected.

    Made once per command and read by everything in it that depends on the
    backend. A start reads it twice: in the preflight, which fetches the
    Qdrant server only for a daemon that will run one, and in the spawn, which
    hands the daemon exactly what a flag decided. When those two read the
    options separately, a start with no backend flag fetched a server on the
    strength of the flags alone and then told the daemon to ignore the choice
    its own settings held.

    Attributes:
        local_only: What ``--local-only`` or ``--qdrant`` decided for the
            on-disk store, or ``None`` when no flag spoke to it. ``None`` is
            written nowhere, so a daemon reads its own environment and the
            saved choice.
        qdrant: What ``--qdrant/--no-qdrant`` decided for server mode, or
            ``None`` likewise.
        server_unneeded: Why no managed Qdrant server will be run, or
            ``None`` when one will be.
    """

    local_only: bool | None
    qdrant: bool | None
    server_unneeded: str | None


def decide_backend(
    *, local_only: bool, qdrant: bool | None = None, saved_choice: bool = True
) -> BackendDecision:
    """Decide the storage backend from a command's flags and the settings.

    Precedence, highest first: a flag on the command, an exported variable,
    the choice ``install`` saved, and the default, which is the managed
    server. ``--local-only`` outranks ``--qdrant`` when both are passed.
    ``--qdrant`` asks for the managed server outright, so it overrides a saved
    or exported local-only choice as well as a server mode that was switched
    off; ``--no-qdrant`` switches server mode off and says nothing about the
    on-disk choice, which could only agree with it.

    The address of a server that is already running is not a backend choice
    and no flag overrides it: server mode then uses that server, and none is
    run or fetched here.

    The flags are applied as overrides to the one settings resolution every
    other reader goes through, rather than compared against the settings
    here, so the lower rungs are not restated and cannot drift from what a
    daemon resolves for itself. A daemon is handed the flags and nothing
    else, and reaches the same answer from the same environment.

    Args:
        local_only: Whether ``--local-only`` was passed.
        qdrant: ``True`` for ``--qdrant``, ``False`` for ``--no-qdrant``,
            ``None`` when neither was passed or the command has no such flag.
        saved_choice: Whether the saved choice is an input. It is for every
            command but the one that writes it: an install that read back the
            choice an earlier install saved could never change it.
    """
    from vaultspec_core.config import env_value

    from ..config._registry import entry
    from ..config._settings import VaultSpecConfigWrapper, rag_default
    from ..config._types import EnvVar

    flags: dict[str, bool] = {}
    if qdrant is not None:
        flags["qdrant_server"] = qdrant
    if local_only:
        flags["local_only"] = True
    elif qdrant:
        flags["local_only"] = False
    overrides: dict[str, object] = dict(flags)
    exported = env_value(entry(EnvVar.LOCAL_ONLY)) is not None
    if not saved_choice and "local_only" not in overrides and not exported:
        # The only rung beneath an exported variable that is not the saved
        # choice is the default, so naming the default here is what takes the
        # saved choice out of the resolution without restating the rest.
        overrides["local_only"] = rag_default("local_only")
    decided = VaultSpecConfigWrapper.from_environment(overrides)
    return BackendDecision(
        local_only=flags.get("local_only"),
        qdrant=flags.get("qdrant_server"),
        server_unneeded=managed_server_unneeded(decided),
    )


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

    The Qdrant step also follows the backend the settings select: an
    exported local-only choice, a server mode switched off, or the address
    of a server that is already running each mean there is no server to
    fetch. The choice an earlier install saved is not consulted, because
    this is the command that writes it.

    Args:
        target: Workspace whose ``pyproject.toml`` the torch step
            patches.
        local_only: When True, skip the Qdrant binary step entirely
            (reported as ``skipped`` with the local-only reason).
        environment: The caller's judgement of whether this environment
            can run the service, when it has already made one; judged here
            when omitted.
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
    from ..operator_state._service_environment import judge_service_environment

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

    # Judged after the torch step, which may be what makes this environment
    # able to run the service, and once for both fetches.
    environment = request.environment or judge_service_environment()

    outcome.steps.append(
        provision_models(
            dry_run=dry_run, skip=skip, progress=progress, environment=environment
        )
    )

    backend = decide_backend(local_only=local_only, saved_choice=False)
    opted_out = (
        "qdrant binary provisioning opted out" if ProvisionStep.QDRANT in skip else None
    )
    outcome.steps.append(
        _provision_qdrant(
            dry_run=dry_run,
            unneeded=backend.server_unneeded or opted_out,
            environment=environment,
            progress=progress,
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
    environment: ServiceEnvironment | None = None,
) -> ModelsStepResult:
    """Ensure the configured embedding and reranker models are cached.

    The model step of the front door, and the one way any command reaches the
    model fetch: ``install``, ``server warmup``, and the preflight of
    ``server start`` all call this. An environment that cannot run the
    service is answered ``skipped`` before the cache is probed.

    No model is constructed and no GPU is touched - only snapshot files are
    fetched - so it is safe on a path that must not load torch.

    Args:
        dry_run: Report what would be fetched without touching the
            network.
        skip: When it contains ``"models"``, the step is opted out.
        progress: Where to report the cache probe and each download while
            they run; silent when omitted.
        environment: The caller's judgement of whether this environment can
            run the service, when it has already made one; judged here when
            omitted.

    Returns:
        The step's outcome in the shared sync vocabulary, with one result per
        configured repository when the cache was reached.
    """
    unable = unable_skip(ProvisionStep.MODELS, environment)
    if unable is not None:
        return ModelsStepResult(unable.step, unable.action, unable.detail)
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


def managed_server_unneeded(settings: VaultSpecConfigWrapper) -> str | None:
    """Say why *settings* call for no managed Qdrant server, or ``None``.

    The daemon runs the managed server in server mode, and only when no
    address of a server that is already running is configured. Those are the
    two states with nothing to fetch, and the sentence returned is the reason
    the Qdrant step reports for skipping. A caller whose command line can
    override the backend asks with settings that already carry its flags, so
    the answer is the one the daemon it spawns will reach.

    The address itself is not repeated: it may carry a credential, and the
    variable's name is what an operator needs to find it.
    """
    from ..config._types import EnvVar

    if not settings.effective_server_mode():
        return LOCAL_STORE_SELECTED
    if str(settings.qdrant_url or ""):
        return (
            f"{EnvVar.QDRANT_URL.value} names a Qdrant server that is already "
            "running, so none is run from this machine and no Qdrant server "
            "binary is needed"
        )
    return None


def ensure_runtime_dependencies(
    *,
    environment: ServiceEnvironment,
    server_unneeded: str | None,
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
        environment: The start's own judgement of the interpreter that will
            run the daemon. It is required here because a start has always
            made it by this point, and both steps answer to it.
        server_unneeded: Why the daemon about to be spawned will run no
            managed Qdrant server, as :func:`managed_server_unneeded` words
            it, or ``None`` when it will run one.
        qdrant_auto_provision: Whether an absent Qdrant server may be
            downloaded. Off, an absent server is a failure naming the install
            command.
        progress: Where the fetches report while they run; silent when
            omitted.

    Returns:
        One result per step that ran, in order.
    """
    outcome = ProvisionOutcome()
    models = provision_models(progress=progress, environment=environment)
    outcome.steps.append(models)
    if models.action == ProvisionAction.FAILED:
        return outcome
    outcome.steps.append(
        _provision_qdrant(
            dry_run=False,
            unneeded=server_unneeded,
            environment=environment,
            auto_provision=qdrant_auto_provision,
            progress=progress,
        )
    )
    return outcome


def _provision_qdrant(
    *,
    dry_run: bool,
    unneeded: str | None,
    environment: ServiceEnvironment,
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

    ``unneeded`` is the reason this run fetches no server, when it has one:
    the backend runs none, or the caller opted the step out. The step is then
    skipped with that reason before anything is resolved, verified or
    fetched. An environment that cannot run the service is answered first,
    because that is the reason that holds whatever else was asked for.
    """
    unable = unable_skip(ProvisionStep.QDRANT, environment)
    if unable is not None:
        return unable
    if unneeded is not None:
        return ProvisionStepResult(
            step=ProvisionStep.QDRANT,
            action=ProvisionAction.SKIPPED,
            detail=unneeded,
        )
    present = _resolved_qdrant(dry_run=dry_run, environment=environment)
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
    return _download_qdrant(dry_run=dry_run, progress=progress, environment=environment)


def _refused_qdrant(exc: QdrantBinaryError) -> ProvisionStepResult:
    """Pass a refusal of the resolved binary on whole, under its own code."""
    return ProvisionStepResult(
        step=ProvisionStep.QDRANT,
        action=ProvisionAction.FAILED,
        detail=str(exc),
        code=exc.error,
    )


def _resolved_qdrant(
    *, dry_run: bool, environment: ServiceEnvironment
) -> ProvisionStepResult | None:
    """Answer for a binary that already resolves, or ``None`` when none does.

    The binary is held to its source's check here, in the foreground, so one
    that may not run is refused where an operator sees the reason rather than
    in the service log after the daemon has been spawned. That covers every
    refusal resolution itself makes: an operator path without its digest, an
    operator file that is not the one declared, and a managed install whose
    executable is not the pinned release, cannot be read, or is not a file.
    The refusal's own sentence names the supported routes and is passed on
    whole.

    An operator-supplied binary is named as such in the detail: the pin that
    vouches for it is the operator's, not this release's, and that has to be
    visible wherever the outcome is shown.

    A managed install that resolves is still handed to the provisioner. It
    downloads nothing for an executable that already is the pinned release,
    and it is what writes a missing manifest again and removes the working
    files of a run that was killed, so neither waits for someone to ask.
    """
    from ..config._types import EnvVar
    from ..qdrant_runtime._resolve import QdrantBinaryError, resolve_binary
    from ..qdrant_runtime._spawn_trust import verify_resolved_binary

    try:
        resolved = resolve_binary()
        if resolved is None:
            return None
        verify_resolved_binary(resolved)
    except QdrantBinaryError as exc:
        return _refused_qdrant(exc)
    if resolved.source.operator_supplied:
        return ProvisionStepResult(
            step=ProvisionStep.QDRANT,
            action=ProvisionAction.UNCHANGED,
            detail=(
                f"operator-supplied binary {resolved.path} (source: "
                f"{resolved.source.value}, named by {EnvVar.QDRANT_BINARY.value}); "
                "verified against the digest declared in "
                f"{EnvVar.QDRANT_BINARY_SHA256.value}"
            ),
        )
    report = provision_qdrant_binary(dry_run=dry_run, environment=environment)
    if report.action == ProvisionAction.FAILED:
        return ProvisionStepResult(
            step=ProvisionStep.QDRANT,
            action=ProvisionAction.FAILED,
            detail=report.message,
            code=QDRANT_PROVISION_FAILED,
        )
    settled = report.action in {ProvisionAction.UNCHANGED, ProvisionAction.DRY_RUN}
    return ProvisionStepResult(
        step=ProvisionStep.QDRANT,
        action=ProvisionAction.UNCHANGED if settled else report.action,
        detail=(
            _qdrant_default_detail(ProvisionAction.UNCHANGED)
            if settled
            else report.message
        ),
    )


def _download_qdrant(
    *,
    dry_run: bool,
    progress: ProvisionProgress | None,
    environment: ServiceEnvironment,
) -> ProvisionStepResult:
    """Provision the pinned release and confirm that it now resolves.

    The confirmation asks the resolver, and a resolver that refuses what was
    just installed is a failed step with the resolver's own reason and code,
    the same as a refusal met before provisioning. It must not leave here as
    an exception: a start reports every outcome that stops it as one
    document.
    """
    from ..qdrant_runtime._resolve import QdrantBinaryError, resolve_binary

    # A first-use provision downloads and verifies a native archive over the
    # network, which is the longest stall a first start can hit. The stage line
    # says it started; the provisioner's own lines carry the byte counts
    # underneath it, so a slow link is distinguishable from a wedged one.
    if progress is not None and not dry_run:
        progress.stage("Downloading the Qdrant server (first use)...")
    report = provision_qdrant_binary(
        dry_run=dry_run,
        on_progress=None if progress is None else progress.stage,
        environment=environment,
    )
    if report.action == ProvisionAction.FAILED:
        return ProvisionStepResult(
            step=ProvisionStep.QDRANT,
            action=ProvisionAction.FAILED,
            detail=report.message,
            code=QDRANT_PROVISION_FAILED,
        )
    try:
        resolves = report.action == ProvisionAction.DRY_RUN or (
            resolve_binary() is not None
        )
    except QdrantBinaryError as exc:
        return _refused_qdrant(exc)
    if not resolves:
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
    archive: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
    environment: ServiceEnvironment | None = None,
) -> ProvisionReport:
    """Provision the pinned Qdrant server binary, where the service can run.

    The one way any command reaches the Qdrant provisioner, so the
    environment is judged in one place: one that cannot run the service gets
    a ``skipped`` report and the provisioner - its download, its staging
    directory, and an install from a local archive alike - is never entered.

    Args:
        upgrade: Replace an install that no longer matches the pin.
        dry_run: Report what would happen without network or disk effects.
        archive: A local copy of the pinned release archive to install from
            in place of a download. It passes the same checks as a download
            and no request is made.
        on_progress: Sink for stage and byte-progress lines; silent when
            omitted.
        environment: The caller's judgement of whether this environment can
            run the service, when it has already made one; judged here when
            omitted.

    Returns:
        The provisioner's report, or a ``skipped`` report for an environment
        that cannot run the service.
    """
    unable = unable_skip(ProvisionStep.QDRANT, environment)
    if unable is not None:
        from ..qdrant_runtime._constants import ProvisionReport

        return ProvisionReport(action=unable.action, message=unable.detail)

    from ..qdrant_runtime._provision import provision

    if on_progress is None:
        return provision(upgrade=upgrade, dry_run=dry_run, archive=archive)
    return provision(
        upgrade=upgrade, dry_run=dry_run, archive=archive, on_progress=on_progress
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
