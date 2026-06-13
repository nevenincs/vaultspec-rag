"""Bounded, read-only readiness reporter for the external dependencies.

The mirror of the unified provisioning front door
(:mod:`vaultspec_rag.commands._provision`): where the front door *sets
up* the three external dependencies vaultspec-rag needs, this reporter
*tells the operator what is ready* - so a user learns what is missing
before a runtime failure rather than after one.

It reports, per dependency, whether it is provisioned and usable:

- **torch**: is the CUDA compute path available? Read from the already
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
(it never accretes into a general health console) per the
``operator-views-are-bounded`` rule, and it lives in the service domain
so the CLI verb and MCP tool adapt to this shared behaviour rather than
duplicating it, per the ``service-domain-owns-operability`` rule.

The structured :class:`ReadinessReport` is designed to serve both a
human render and a JSON envelope: every node is a serialisable dataclass
with a ``to_dict``.

See the ADR ``2026-06-13-provisioning-setup-adr`` for the readiness
decision and the plan ``2026-06-13-server-first-default-plan`` (W03.P07).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)

__all__ = [
    "DependencyReadiness",
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
            CUDA device name). Always JSON-serialisable.
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
        """Return a JSON-serialisable view of the whole report."""
        return {
            "ready": self.ready,
            "server_mode": self.server_mode,
            "dependencies": [dep.to_dict() for dep in self.dependencies],
        }


def compute_readiness() -> ReadinessReport:
    """Aggregate the bounded per-dependency readiness snapshot.

    Read-only: probes torch's observable CUDA attributes, the Hugging
    Face cache, and the qdrant runtime/resolution state without loading
    a model, touching the GPU, downloading, or mutating any state.

    Returns:
        A :class:`ReadinessReport` with one node per known dependency
        (torch, models, qdrant), in that order.
    """
    from .config import get_config

    cfg = get_config()
    server_mode = bool(cfg.effective_server_mode())

    return ReadinessReport(
        dependencies=[
            _torch_readiness(),
            _models_readiness(),
            _qdrant_readiness(server_mode=server_mode),
        ],
        server_mode=server_mode,
    )


def _torch_readiness() -> DependencyReadiness:
    """Report CUDA availability without forcing a model load.

    Reads ``torch.version.cuda`` and ``torch.cuda.is_available()`` only
    - the same observable attributes the torch diagnosis classifier
    consumes - so the GPU compute path is reported without allocating
    anything on the device.
    """
    try:
        import torch
    except ImportError:
        return DependencyReadiness(
            name="torch",
            status=ReadinessStatus.NOT_READY,
            detail="torch is not installed; run install to configure the cu130 wheel",
            info={"installed": False, "cuda_available": False},
        )

    from .torch_config import TorchDiagnosis, diagnose_torch

    cuda_build = getattr(torch.version, "cuda", None)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]  # torch.version is loosely typed
    available = bool(torch.cuda.is_available())
    diagnosis = diagnose_torch(cuda_build, available)

    device_name: str | None = None
    if available:
        try:
            device_name = torch.cuda.get_device_name(0)
        except Exception as exc:
            logger.debug("torch.cuda.get_device_name failed: %s", exc)

    info: dict[str, object] = {
        "installed": True,
        "cuda_build": cuda_build,
        "cuda_available": available,
        "diagnosis": str(diagnosis),
        "device_name": device_name,
    }

    if diagnosis == TorchDiagnosis.WORKING:
        return DependencyReadiness(
            name="torch",
            status=ReadinessStatus.READY,
            detail=(
                f"CUDA available on {device_name}" if device_name else "CUDA available"
            ),
            info=info,
        )
    if diagnosis == TorchDiagnosis.CPU_ONLY:
        return DependencyReadiness(
            name="torch",
            status=ReadinessStatus.NOT_READY,
            detail="torch is the CPU-only build; reinstall the cu130 wheel for GPU",
            info=info,
        )
    # NO_GPU: a CUDA wheel is installed but no usable device is visible.
    return DependencyReadiness(
        name="torch",
        status=ReadinessStatus.NOT_READY,
        detail="cu130 torch is installed but no CUDA device is available",
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
            try_to_load_from_cache,  # pyright: ignore[reportUnknownVariableType]  # huggingface_hub stubs partially unknown
        )
    except ImportError:
        return DependencyReadiness(
            name="models",
            status=ReadinessStatus.UNKNOWN,
            detail="huggingface_hub is not installed; cannot probe the model cache",
            info={"repos": {}},
        )

    from .config import get_config

    cfg = get_config()
    repos = [
        str(cfg.embedding_model),
        str(cfg.sparse_model),
        str(cfg.reranker_model),
    ]

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
    from .qdrant_runtime import resolve_binary, runtime_state

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
