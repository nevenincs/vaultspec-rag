"""Bounded, read-only readiness reporter for the external dependencies.

The mirror of the unified provisioning front door
(:mod:`vaultspec_rag.commands._provision`): where the front door *sets
up* the three external dependencies vaultspec-rag needs, this reporter
*tells the operator what is ready* - so a user learns what is missing
before a runtime failure rather than after one.

It reports, per dependency, whether it is provisioned and usable:

- **torch**: is a supported accelerator compute path available? Read from the already
  imported torch's observable attributes, never by loading a model onto
  the GPU.
- **models**: are complete snapshots of the configured dense, sparse, and
  reranker repos cached at their required revisions? Uses the shared offline
  snapshot probe from warmup and provisioning, without downloading or loading
  models onto the GPU.
- **qdrant**: where does the qdrant binary resolve from (managed /
  operator-supplied / absent), and - when server mode is the effective
  backend - would a start accept it, and is the supervised child live?

This is a *report*, not a fixer: it performs no provisioning, no
download, and no mutation. It is bounded to the known dependency set
(it never accretes into a general health console), and it lives in the
service domain so the CLI verb and MCP tool adapt to this shared
behaviour rather than duplicating it.

The structured :class:`ReadinessReport` is designed to serve both a
human render and a JSON envelope: every node is a serialisable dataclass
with a ``to_dict``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from .operator_state._compute import local_compute
from .operator_state._installation import ComputeCapability

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from .config._types import ModelRepo
    from .operator_state._models import ComputeReport
    from .qdrant_runtime._constants import ResolvedBinary

logger = logging.getLogger(__name__)

#: A full process-table walk costs 4-6.5s on a developer machine with ~1700
#: processes (measured 2026-09-04). That is affordable for an operator who
#: typed a diagnostic and waited for it, and not for a route a broker polls,
#: which is why holder scanning is opt-in rather than budget-limited: a
#: budget short enough for the route would report "cannot tell" every time
#: and teach an operator to ignore the dimension.
_HOLDER_SCAN_BUDGET_SECONDS = 20.0

#: An operator clears holders one at a time; a census helps nobody.
_HOLDER_REPORT_LIMIT = 10

#: Hashing the server executable takes well under a second on a healthy disk.
#: The budget is for the unhealthy one: a stalled volume or a scanner holding
#: the file must not hang a status command.
_BINARY_VERIFY_BUDGET_SECONDS = 10.0

#: Reported when that budget runs out. Distinct from a failed check: the file
#: was not shown to be wrong, only not shown to be right.
_BINARY_UNCHECKED = "qdrant_binary_unchecked"

__all__ = [
    "DependencyReadiness",
    "EnvironmentHoldersReadiness",
    "ReadinessReport",
    "ReadinessStatus",
    "compute_readiness",
]


class ReadinessStatus(StrEnum):
    """Bounded readiness vocabulary for a single dependency dimension.

    Deliberately small - a readiness report answers "is this dependency
    provisioned and usable?", not a graded health score. ``StrEnum``
    members compare equal to their string value so JSON consumers can
    filter on the same strings.

    Values:
        READY: the dependency is provisioned and usable.
        NOT_READY: the dependency is absent or unusable; ``detail``
            carries what is missing and (where applicable) the
            remediation.
        UNKNOWN: readiness could not be determined without an action the
            reporter must not take (e.g. probing a dependency whose
            client is not importable). Distinct from ``NOT_READY`` so a
            missing prerequisite is not misreported as a broken
            dependency.
    """

    READY = "ready"
    NOT_READY = "not_ready"
    UNKNOWN = "unknown"


@dataclass
class DependencyReadiness:
    """Readiness of one external dependency dimension.

    Attributes:
        name: The dependency this node describes (``"torch"`` /
            ``"models"`` / ``"qdrant"``).
        status: The bounded :class:`ReadinessStatus` outcome.
        detail: Human-readable summary. For ``NOT_READY`` it names what
            is missing; informational otherwise.
        info: Dimension-specific structured facts that a human render
            or JSON consumer can surface without re-deriving them (e.g.
            the qdrant resolution source, the per-repo cache hits, the
            accelerator backend and device name). Always JSON-serialisable.
    """

    name: str
    status: ReadinessStatus
    detail: str = ""
    info: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of this dependency node."""
        return {
            "name": self.name,
            "status": str(self.status),
            "detail": self.detail,
            "info": self.info,
        }


@dataclass
class EnvironmentHoldersReadiness:
    """Who is running out of this interpreter's environment, if anyone.

    Deliberately NOT a dependency node. Nothing here can make the service
    unhealthy: a held environment serves requests perfectly well, and the
    holders matter only to an operator about to replace it, for whom a forced
    reinstall would remove the packages and then fail on the held files. Adding
    it to :attr:`ReadinessReport.dependencies` would fold that into the
    aggregate ``ready`` boolean and turn a healthy machine red.

    Attributes:
        held: Whether at least one holder was positively identified.
        scanned: Whether a scan was performed at all. False means nobody
            asked, which is neither "held" nor "clear".
        certain: Whether an empty list may be read as "nothing holds this".
            False when a process could not be inspected or the scan could not
            finish - absence of evidence, not evidence of absence.
        total: How many holders were found, which the bounded list may not
            show all of. A capped list with no total reads as the whole story.
        self_held: Whether the asking process, or something that launched it,
            runs out of this environment. It is left out of the list because
            it is not an obstacle the reader can clear, and reported here so
            they are told once.
        holders: Bounded holder facts: pids, relation, role, the port a
            service holder serves on, and the image path. Command lines are
            deliberately omitted; this snapshot is also served over HTTP, and
            an argument vector can carry material the readiness route has no
            business republishing. The role is derived from the command line
            in this process, so the reader learns what each holder is without
            the argument vector leaving it.
    """

    scanned: bool = True
    held: bool = False
    certain: bool = True
    total: int = 0
    self_held: bool = False
    holders: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of the holder snapshot."""
        return {
            "scanned": self.scanned,
            "held": self.held,
            "certain": self.certain,
            "total": self.total,
            "self_held": self.self_held,
            "holders": self.holders,
        }


@dataclass
class ReadinessReport:
    """Bounded readiness snapshot across the known dependency set.

    Holds one :class:`DependencyReadiness` per external dependency the
    reporter knows about, in a stable order. The aggregate
    :attr:`ready` is true only when every dimension is ``READY`` - the
    single boolean a caller checks to answer "can the intended
    configuration run?".

    Attributes:
        dependencies: One node per dependency, in report order
            (torch, models, qdrant).
        server_mode: Whether the supervised server backend is the
            effective runtime backend at report time. Carried so a
            consumer can explain why the qdrant liveness dimension is
            (or is not) relevant.
    """

    dependencies: list[DependencyReadiness] = field(default_factory=list)
    server_mode: bool = False
    environment_holders: EnvironmentHoldersReadiness = field(
        default_factory=lambda: EnvironmentHoldersReadiness()
    )

    @property
    def ready(self) -> bool:
        """True when every known dependency dimension is ``READY``."""
        return bool(self.dependencies) and all(
            dep.status == ReadinessStatus.READY for dep in self.dependencies
        )

    def dimension(self, name: str) -> DependencyReadiness | None:
        """Return the readiness node named *name*, or ``None``."""
        for dep in self.dependencies:
            if dep.name == name:
                return dep
        return None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of the whole report.

        Carries the bounded storage-schema descriptor so a consumer can assert
        compatibility against the Qdrant data shape before a direct read. The
        descriptor is config-derived and torch-free, so it stays inside the
        no-GPU readiness contract.
        """
        from . import store_schema
        from .config._settings import get_config
        from .index_profiles import index_support_profile_status
        from .serviceclient._compat import (
            SERVICE_VERSION_FIELD,
            local_package_version,
        )

        degraded_reasons = [
            dep.detail
            for dep in self.dependencies
            if dep.status is not ReadinessStatus.READY and dep.detail
        ]

        return {
            "ready": self.ready,
            "server_mode": self.server_mode,
            "dependencies": [dep.to_dict() for dep in self.dependencies],
            "degraded_reasons": degraded_reasons,
            "environment_holders": self.environment_holders.to_dict(),
            "support_profile": index_support_profile_status(
                get_config().index_support_profile
            ),
            "schema": store_schema.describe_storage_schema(),
            SERVICE_VERSION_FIELD: local_package_version(),
        }


def compute_readiness(
    *,
    holders_root: str | Path | None = None,
    compute: ComputeReport | None = None,
    verify_models: bool = False,
) -> ReadinessReport:
    """Aggregate the bounded per-dependency readiness snapshot.

    Read-only: probes torch's observable accelerator attributes, the Hugging
    Face cache, and the qdrant runtime/resolution state without loading
    a model, touching the GPU, downloading, or mutating any state.

    Args:
        verify_models: Hash each pinned model's snapshot against its
            committed digests instead of only listing its files. Off by
            default because it reads gigabytes and costs seconds; the deep
            health command asks for it, a polled route does not.
        holders_root: The environment to scan for holders, or ``None`` to
            skip the scan. Off by default because the walk costs seconds and
            every caller pays it; an operator diagnosing a machine wants it,
            a polled route does not. The root is asked for rather than
            assumed, because the environment a caller needs to know about is
            the one that would run the service, which is not necessarily the
            one this process runs in.
        compute: The compute verdict for the environment being assessed. A
            torch-free caller supplies the one it probed out of process;
            when omitted, this process classifies its own environment.

    Returns:
        A :class:`ReadinessReport` with one node per known dependency
        (torch, models, qdrant), in that order.
    """
    from .config._settings import get_config

    cfg = get_config()
    server_mode = bool(cfg.effective_server_mode())
    judged = local_compute() if compute is None else compute

    return ReadinessReport(
        dependencies=[
            _torch_readiness(judged),
            _models_readiness(verify=verify_models, capability=judged.capability),
            _qdrant_readiness(server_mode=server_mode, capability=judged.capability),
        ],
        server_mode=server_mode,
        environment_holders=(
            EnvironmentHoldersReadiness(scanned=False, certain=False)
            if holders_root is None
            else _environment_holders_readiness(holders_root)
        ),
    )


def _environment_holders_readiness(root: str | Path) -> EnvironmentHoldersReadiness:
    """Report the live processes running out of the environment at *root*.

    Bounded twice over: the scan carries a short budget because this reporter
    also answers an HTTP route, and the reported list is capped because an
    operator acts on holders one at a time rather than reading a census.

    The asking process and its launch chain are left out. This list exists to
    be worked through, and the command producing it is not something its
    reader can clear.
    """
    from ._process_probe import environment_holders
    from .operator_state._holders import holder_wire

    found = environment_holders(
        root, exclude_launch_chain=True, timeout=_HOLDER_SCAN_BUDGET_SECONDS
    )
    wire = holder_wire(found.holders, limit=_HOLDER_REPORT_LIMIT)
    return EnvironmentHoldersReadiness(
        held=found.held,
        certain=found.certain,
        total=cast("int", wire["total"]),
        self_held=found.self_held,
        holders=cast("list[dict[str, object]]", wire["holders"]),
    )


#: Capabilities whose probe detail explains them: an import error's message,
#: or why a check did not finish.
_DETAIL_IS_DIAGNOSIS = frozenset({"torch_import_failed", "unknown"})


def _torch_readiness(compute: ComputeReport) -> DependencyReadiness:
    """Report supported accelerator availability from a compute verdict.

    The verdict comes from the operator state compute check, which never
    allocates a model and keeps any torch import guarded and function-local.
    """
    from .operator_state._installation import ComputeCapability

    capability = compute.capability
    if capability is ComputeCapability.READY:
        status = ReadinessStatus.READY
        detail = f"{str(compute.backend).upper()} available on {compute.device_name}"
    else:
        # A client never needs torch, so its absence is ready rather than a
        # defect; a build nobody has verified is not yet known either way.
        if capability is ComputeCapability.NOT_APPLICABLE:
            status = ReadinessStatus.READY
        elif capability.is_defect:
            status = ReadinessStatus.NOT_READY
        else:
            status = ReadinessStatus.UNKNOWN
        # The raw detail is the diagnosis only where the capability cannot
        # say what went wrong on its own; elsewhere it restates the label.
        diagnostic = compute.detail if capability in _DETAIL_IS_DIAGNOSIS else None
        detail = capability.label + (f" ({diagnostic})" if diagnostic else "")
    return DependencyReadiness(
        name="torch",
        status=status,
        detail=detail,
        info=compute.model_dump(mode="json"),
    )


#: The detail of a dependency a client installation has no use for. A client
#: never runs the service, so nothing is looked for and nothing is missing.
_CLIENT_NEEDS_NONE = (
    "not needed (this installation is a client); the host installation that "
    "runs the service provides it"
)


def _fetch_remedy(capability: ComputeCapability, command: str) -> str:
    """Say how a missing dependency gets fetched in this environment.

    An environment that can run the service is given *command*, whole. One
    that cannot yet is not: every command that fetches would decline it, so
    it is told what fetches the dependency once the environment is repaired.
    The torch row beside this one says what the repair is.
    """
    if capability.blocks_start:
        return (
            "`vaultspec-rag server start` fetches it once this environment "
            "can run the service"
        )
    return f"run `{command}`"


def _probe_models(
    models: Sequence[ModelRepo], *, verify: bool
) -> tuple[dict[str, bool], dict[str, str]]:
    """Return which model snapshots are usable, and why the others are not.

    Without *verify* a snapshot is usable when its files are present and no
    reason is recorded for one that is not. With it each snapshot is checked
    as a load would check it, and a failing one carries the check's own words.

    Raises:
        ImportError: If the hub client is not installed.
    """
    from ._model_cache import (
        ModelSnapshotError,
        cached_snapshot_is_complete,
        verify_snapshot,
    )

    usable: dict[str, bool] = {}
    faults: dict[str, str] = {}
    for model in models:
        if not verify:
            usable[model.repo] = cached_snapshot_is_complete(
                model.repo, revision=model.revision
            )
            continue
        try:
            verify_snapshot(model.repo, revision=model.revision)
        except ModelSnapshotError as fault:
            usable[model.repo] = False
            faults[model.repo] = fault.detail
        else:
            usable[model.repo] = True
    return usable, faults


def _models_readiness(
    *, verify: bool, capability: ComputeCapability
) -> DependencyReadiness:
    """Report the model snapshots in the Hugging Face cache.

    Two depths, and the wording keeps them apart. Without *verify* only the
    set of files is looked at: a snapshot is *present* or not, and nothing is
    said about its content. With *verify* each snapshot is put through the
    check a load makes, which for a pinned model hashes every file against
    the digests committed for it; only then is a model called verified.

    Either way each model is reported as *pinned* or *unpinned*: whether file
    digests are committed for that repository at the commit it is used at. An
    unpinned model is one the operator named, or a default moved to another
    commit, and no depth of check can vouch for its content.

    *capability* is what the environment being assessed can do. A client
    needs no model files and its cache is not probed. Any other environment
    is told the truth about its cache, with a remedy it can act on.

    This neither downloads files nor imports torch or loads a model onto the
    GPU.
    """
    from .config._settings import configured_model_repos

    if capability is ComputeCapability.NOT_APPLICABLE:
        return DependencyReadiness(
            name="models",
            status=ReadinessStatus.READY,
            detail=_CLIENT_NEEDS_NONE,
            info={"repos": {}},
        )

    models = configured_model_repos()
    try:
        cached, faults = _probe_models(models, verify=verify)
    except ImportError:
        return DependencyReadiness(
            name="models",
            status=ReadinessStatus.UNKNOWN,
            detail="huggingface_hub is not installed; cannot probe the model cache",
            info={"repos": {}},
        )

    unpinned = [model.repo for model in models if not model.pinned]
    info: dict[str, object] = {
        "repos": cached,
        "pinned": {model.repo: model.pinned for model in models},
        "revisions": {model.repo: model.revision for model in models},
        "verified": verify,
    }
    unpinned_note = f"; unpinned: {', '.join(unpinned)}" if unpinned else ""
    unusable = [repo for repo, usable in cached.items() if not usable]
    if not unusable:
        checked = len(models) - len(unpinned)
        return DependencyReadiness(
            name="models",
            status=ReadinessStatus.READY,
            detail=(
                (
                    f"all {len(models)} model repos present; {checked} verified "
                    "against committed digests"
                    if verify
                    else f"all {len(models)} model repos present in the cache"
                )
                + unpinned_note
            ),
            info=info,
        )
    if faults:
        return DependencyReadiness(
            name="models",
            status=ReadinessStatus.NOT_READY,
            detail=(
                f"{len(faults)} of {len(models)} model repo(s) cannot be used: "
                + "; ".join(f"{repo} {detail}" for repo, detail in faults.items())
                + "; "
                + _fetch_remedy(capability, "vaultspec-rag server warmup")
                + unpinned_note
            ),
            info=info,
        )
    return DependencyReadiness(
        name="models",
        status=ReadinessStatus.NOT_READY,
        detail=(
            f"{len(unusable)} of {len(models)} model repo(s) missing from the "
            "cache: "
            + ", ".join(unusable)
            + "; "
            + _fetch_remedy(capability, "vaultspec-rag server warmup")
        ),
        info=info,
    )


def _binary_refusal(
    *, budget: float
) -> tuple[ResolvedBinary | None, tuple[str, str] | None]:
    """Resolve the binary a start would run and say whether it would be refused.

    Returns the resolved binary, if any, and the refusal as ``(code,
    detail)`` or ``None``. Both steps hash a file - resolution hashes the
    managed executable to decide whether an install exists at all, and the
    check a spawn runs hashes whatever resolved - so a binary that merely has
    a name on disk is never reported usable.

    Bounded as one judgement, because this is a report: when it does not
    finish within *budget* seconds the binary is reported as unchecked and
    not ready. It is never reported ready on the strength of a check that did
    not finish.
    """
    from ._process_probe import bounded_call
    from .qdrant_runtime._resolve import QdrantBinaryError, resolve_binary
    from .qdrant_runtime._spawn_trust import verify_resolved_binary

    def judge() -> tuple[ResolvedBinary | None, tuple[str, str] | None]:
        resolved: ResolvedBinary | None = None
        try:
            resolved = resolve_binary()
            if resolved is not None:
                verify_resolved_binary(resolved)
        except QdrantBinaryError as exc:
            return resolved, (exc.error, str(exc))
        return resolved, None

    return bounded_call(
        judge,
        timeout=budget,
        fallback=(
            None,
            (
                _BINARY_UNCHECKED,
                f"the qdrant binary could not be verified within {budget:.0f}s, "
                "so it is not known to be usable",
            ),
        ),
        label="qdrant-binary-verify",
    )


def _server_binary_unneeded(
    *, server_mode: bool, capability: ComputeCapability, remote: bool
) -> str | None:
    """Say why this machine needs no Qdrant server binary, or ``None``."""
    from .config._types import EnvVar

    if capability is ComputeCapability.NOT_APPLICABLE:
        return _CLIENT_NEEDS_NONE
    if not server_mode:
        return "local-only backend selected; the on-disk store needs no server binary"
    if remote:
        # The address is not repeated: it may carry a credential.
        return (
            f"{EnvVar.QDRANT_URL.value} names a Qdrant server that is already "
            "running; no server binary is needed on this machine"
        )
    return None


def _qdrant_readiness(
    *,
    server_mode: bool,
    capability: ComputeCapability = ComputeCapability.READY,
    verify_budget: float = _BINARY_VERIFY_BUDGET_SECONDS,
) -> DependencyReadiness:
    """Report the qdrant binary resolution source plus supervised liveness.

    Reads the resolution order (operator setting / managed dir / absent)
    and the live runtime snapshot without spawning a process.
    When server mode is the effective backend, the binary must resolve,
    pass the check a spawn would make of it, and - if a child is being
    supervised in this process - that child must be alive for the dimension
    to read ``READY``. A binary a start would refuse - operator settings that
    name no usable binary, a managed executable that is not the pinned
    release or cannot be read, or an operator file that fails its declared
    digest - is ``NOT_READY`` with the refusal as the detail.

    In local-only mode no server binary runs, so none is looked for and
    nothing is hashed: the dimension is ``READY`` and says the binary is not
    needed. The same holds for a client installation, which never runs the
    service, and for a server that is already running at a configured
    address, which this machine does not run.
    """
    from .qdrant_runtime._supervise import runtime_state

    state = runtime_state()
    unneeded = _server_binary_unneeded(
        server_mode=server_mode, capability=capability, remote=state.mode == "remote"
    )
    if unneeded is not None:
        return DependencyReadiness(
            name="qdrant",
            status=ReadinessStatus.READY,
            detail=unneeded,
            info={
                "binary_source": "not_needed",
                "binary_path": None,
                "server_mode": server_mode,
                "runtime": state.to_dict(),
            },
        )

    resolved, refusal = _binary_refusal(budget=verify_budget)
    if resolved is not None:
        source: str = resolved.source
    elif refusal is None:
        source = "absent"
    else:
        # Nothing resolved and something was refused: either what is there may
        # not run, or the judgement did not finish and nothing is known.
        source = "unchecked" if refusal[0] == _BINARY_UNCHECKED else "invalid"

    info: dict[str, object] = {
        "binary_source": source,
        "binary_path": str(resolved.path) if resolved is not None else None,
        "server_mode": server_mode,
        "runtime": state.to_dict(),
    }
    if refusal is not None:
        info["binary_error"] = refusal[0]

    if refusal is not None:
        return DependencyReadiness(
            name="qdrant",
            status=ReadinessStatus.NOT_READY,
            detail=refusal[1],
            info=info,
        )

    if resolved is None:
        return DependencyReadiness(
            name="qdrant",
            status=ReadinessStatus.NOT_READY,
            detail=(
                "server mode is the default but no qdrant binary resolves; "
                + _fetch_remedy(capability, "vaultspec-rag server qdrant install")
                + ", or select the on-disk store with "
                "`vaultspec-rag server start --local-only`"
            ),
            info=info,
        )

    # The binary resolves. If a supervised child is being tracked in
    # this process, its liveness is the live signal; alive is None when
    # no child is supervised here (e.g. a CLI process reading the state).
    alive = state.alive
    if alive is False:
        return DependencyReadiness(
            name="qdrant",
            status=ReadinessStatus.NOT_READY,
            detail=(
                f"qdrant binary resolves from {source} but the supervised "
                "server is not live"
            ),
            info=info,
        )
    if alive is True:
        return DependencyReadiness(
            name="qdrant",
            status=ReadinessStatus.READY,
            detail=f"qdrant binary resolves from {source}; supervised server is live",
            info=info,
        )
    # No child supervised in this process: the binary is provisioned and
    # usable, which is the readiness signal a read-only reporter can
    # honestly give without spawning a server to test it.
    return DependencyReadiness(
        name="qdrant",
        status=ReadinessStatus.READY,
        detail=f"qdrant binary resolves from {source}",
        info=info,
    )
