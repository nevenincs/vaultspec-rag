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
- **models**: are the configured dense, sparse, and reranker repos
  present in the Hugging Face cache? Probed with
  ``try_to_load_from_cache`` - the same idempotency probe the warmup
  verb and the model provisioning step use - so no download and no GPU
  load happens.
- **qdrant**: where does the qdrant binary resolve from (managed /
  operator-supplied / on PATH / absent), and - when server mode is the
  effective backend - is the supervised child live?

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
        holders: Bounded holder facts: pid, relation and image path. Command
            lines are deliberately omitted; this snapshot is also served over
            HTTP, and an argument vector can carry material the readiness
            route has no business republishing.
    """

    scanned: bool = True
    held: bool = False
    certain: bool = True
    holders: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of the holder snapshot."""
        return {
            "scanned": self.scanned,
            "held": self.held,
            "certain": self.certain,
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


def compute_readiness(*, include_holders: bool = False) -> ReadinessReport:
    """Aggregate the bounded per-dependency readiness snapshot.

    Read-only: probes torch's observable accelerator attributes, the Hugging
    Face cache, and the qdrant runtime/resolution state without loading
    a model, touching the GPU, downloading, or mutating any state.

    Args:
        include_holders: Scan for processes running out of this interpreter's
            environment. Off by default because the walk costs seconds and
            every caller pays it; an operator diagnosing a machine wants it,
            a polled route does not.

    Returns:
        A :class:`ReadinessReport` with one node per known dependency
        (torch, models, qdrant), in that order.
    """
    from .config._settings import get_config

    cfg = get_config()
    server_mode = bool(cfg.effective_server_mode())

    return ReadinessReport(
        dependencies=[
            _torch_readiness(),
            _models_readiness(),
            _qdrant_readiness(server_mode=server_mode),
        ],
        server_mode=server_mode,
        environment_holders=(
            _environment_holders_readiness()
            if include_holders
            else EnvironmentHoldersReadiness(scanned=False, certain=False)
        ),
    )


def _environment_holders_readiness() -> EnvironmentHoldersReadiness:
    """Report the live processes running out of this interpreter's environment.

    Bounded twice over: the scan carries a short budget because this reporter
    also answers an HTTP route, and the reported list is capped because an
    operator acts on holders one at a time rather than reading a census.
    """
    import sys
    from pathlib import Path

    from ._process_probe import environment_holders

    found = environment_holders(Path(sys.prefix), timeout=_HOLDER_SCAN_BUDGET_SECONDS)
    return EnvironmentHoldersReadiness(
        held=found.held,
        certain=found.certain,
        holders=[
            {
                "pid": holder.pid,
                "relation": str(holder.relation),
                "image": holder.image,
            }
            for holder in found.holders[:_HOLDER_REPORT_LIMIT]
        ],
    )


def _torch_readiness() -> DependencyReadiness:
    """Report supported accelerator availability without forcing a model load.

    The guarded function-local import keeps this read-only probe valid on a
    torch-free service client. Device resolution delegates to the canonical
    CUDA-first, MPS-second contract and never allocates a model.
    """
    try:
        import torch
    except ImportError:
        return DependencyReadiness(
            name="torch",
            status=ReadinessStatus.NOT_READY,
            detail=(
                "torch is not installed; run install to provision an accelerator build"
            ),
            info={
                "installed": False,
                "accelerator_available": False,
                "backend": None,
                "memory_kind": None,
                "cuda_available": False,
                "mps_available": False,
            },
        )

    from ._gpu import resolve_accelerator
    from .torch_config._constants import TorchDiagnosis
    from .torch_config._diagnose import diagnose_torch

    cuda_build = getattr(torch.version, "cuda", None)
    cuda_available = bool(torch.cuda.is_available())
    mps_available = bool(torch.backends.mps.is_available())
    diagnosis = diagnose_torch(cuda_build, cuda_available, mps_available)

    accelerator = None
    resolution_error: str | None = None
    try:
        accelerator = resolve_accelerator(torch)
    except RuntimeError as exc:
        resolution_error = str(exc)

    info: dict[str, object] = {
        "installed": True,
        "accelerator_available": accelerator is not None,
        "backend": accelerator.backend if accelerator is not None else None,
        "memory_kind": accelerator.memory_kind if accelerator is not None else None,
        "cuda_build": cuda_build,
        "cuda_available": cuda_available,
        "mps_available": mps_available,
        "diagnosis": str(diagnosis),
        "device_name": accelerator.name if accelerator is not None else None,
    }

    if accelerator is not None:
        return DependencyReadiness(
            name="torch",
            status=ReadinessStatus.READY,
            detail=f"{accelerator.backend.upper()} available on {accelerator.name}",
            info=info,
        )
    if resolution_error is not None and diagnosis == TorchDiagnosis.WORKING:
        return DependencyReadiness(
            name="torch",
            status=ReadinessStatus.NOT_READY,
            detail=resolution_error,
            info=info,
        )
    if diagnosis == TorchDiagnosis.CPU_ONLY:
        return DependencyReadiness(
            name="torch",
            status=ReadinessStatus.NOT_READY,
            detail=(
                "torch has no usable CUDA or MPS accelerator; CPU inference is disabled"
            ),
            info=info,
        )
    # NO_GPU: a CUDA wheel is installed but no supported device is visible.
    return DependencyReadiness(
        name="torch",
        status=ReadinessStatus.NOT_READY,
        detail="CUDA torch is installed but no supported accelerator is available",
        info=info,
    )


def _models_readiness() -> DependencyReadiness:
    """Report model presence by probing the Hugging Face cache.

    Checks the configured dense, sparse, and reranker repos with
    ``try_to_load_from_cache`` - the same probe the warmup verb and the
    model provisioning step use - so this neither downloads nor loads a
    model onto the GPU.
    """
    try:
        from huggingface_hub import (
            try_to_load_from_cache,
        )
    except ImportError:
        return DependencyReadiness(
            name="models",
            status=ReadinessStatus.UNKNOWN,
            detail="huggingface_hub is not installed; cannot probe the model cache",
            info={"repos": {}},
        )

    from .config._settings import configured_model_repos

    repos = [repo for _label, repo in configured_model_repos()]

    cached: dict[str, bool] = {
        repo: try_to_load_from_cache(repo, "config.json") is not None for repo in repos
    }
    missing = [repo for repo, present in cached.items() if not present]

    info: dict[str, object] = {"repos": cached}

    if not missing:
        return DependencyReadiness(
            name="models",
            status=ReadinessStatus.READY,
            detail=f"all {len(repos)} model repos present in the cache",
            info=info,
        )
    return DependencyReadiness(
        name="models",
        status=ReadinessStatus.NOT_READY,
        detail=(
            f"{len(missing)} of {len(repos)} model repo(s) missing from the cache: "
            + ", ".join(missing)
            + "; run install to provision them"
        ),
        info=info,
    )


def _qdrant_readiness(*, server_mode: bool) -> DependencyReadiness:
    """Report the qdrant binary resolution source plus supervised liveness.

    Reads the resolution order (operator env / managed dir / PATH /
    absent) and the live runtime snapshot without spawning a process.
    When server mode is the effective backend, the binary must resolve
    and - if a child is being supervised in this process - it must be
    alive for the dimension to read ``READY``. In local-only mode the
    binary is not required, so an absent binary is ``READY`` (the
    on-disk store needs no server).
    """
    from .qdrant_runtime._resolve import resolve_binary
    from .qdrant_runtime._supervise import runtime_state

    state = runtime_state()
    resolved = resolve_binary()
    source = resolved.source if resolved is not None else "absent"

    info: dict[str, object] = {
        "binary_source": source,
        "binary_path": str(resolved.path) if resolved is not None else None,
        "server_mode": server_mode,
        "runtime": state.to_dict(),
    }

    if not server_mode:
        return DependencyReadiness(
            name="qdrant",
            status=ReadinessStatus.READY,
            detail=(
                "local-only backend selected; the on-disk store needs no "
                f"server binary (binary source: {source})"
            ),
            info=info,
        )

    if resolved is None:
        return DependencyReadiness(
            name="qdrant",
            status=ReadinessStatus.NOT_READY,
            detail=(
                "server mode is the default but no qdrant binary resolves; "
                "run install to provision it, or start with --local-only"
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
