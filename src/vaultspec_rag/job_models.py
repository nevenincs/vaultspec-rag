"""Canonical immutable models for service-owned jobs."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

__all__ = [
    "DesiredJobState",
    "IndexResilienceSnapshot",
    "JobAttempt",
    "JobCapabilities",
    "JobInitiator",
    "JobMode",
    "JobOperation",
    "JobOutcome",
    "JobOutcomeStatus",
    "JobProgress",
    "JobResourceSnapshot",
    "JobRuntimeSnapshot",
    "JobSnapshot",
    "JobSource",
    "JobSpec",
    "JobState",
    "JobTimestamps",
    "ProcessResourceSnapshot",
    "ResumeStrategy",
    "is_encode_bearing",
]


class JobOperation(StrEnum):
    """Stable service-domain operation vocabulary."""

    INDEX = "index"
    MAINTENANCE = "maintenance"


class JobSource(StrEnum):
    """Corpus or service resource acted on by a job."""

    VAULT = "vault"
    CODE = "code"
    DOCUMENT = "document"
    MAINTENANCE = "maintenance"


class JobMode(StrEnum):
    """Requested indexing convergence mode."""

    INCREMENTAL = "incremental"
    REBUILD = "rebuild"


class JobState(StrEnum):
    """Canonical observed lifecycle state."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

    @property
    def is_terminal(self) -> bool:
        """Return whether no transition may rewrite this job resource."""
        return self in {
            JobState.CANCELLED,
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.INTERRUPTED,
        }


class DesiredJobState(StrEnum):
    """Canonical operator intent, distinct from observed state."""

    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ResumeStrategy(StrEnum):
    """How a later attempt continues paused logical work."""

    RECONCILE = "reconcile"


class JobOutcomeStatus(StrEnum):
    """Stable disposition for service-domain command outcomes."""

    ACCEPTED = "accepted"
    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class JobSpec:
    """Immutable instructions for one logical job resource."""

    operation: JobOperation
    source: JobSource
    project_root: str | None
    mode: JobMode | None


@dataclass(frozen=True, slots=True)
class JobInitiator:
    """Immutable attribution retained across execution attempts."""

    kind: str
    command: str
    project_root: str | None


@dataclass(frozen=True, slots=True)
class JobCapabilities:
    """Actions currently supported for an exact job resource."""

    pausable: bool
    resumable: bool
    cancellable: bool
    retryable: bool
    deletable: bool
    force_killable: bool = False


@dataclass(frozen=True, slots=True)
class JobAttempt:
    """Attempt and retry lineage for one logical job resource."""

    number: int
    parent_job_id: str | None = None
    resumed_from_attempt: int | None = None
    resume_strategy: ResumeStrategy | None = None

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("job attempt number must be at least 1")
        if self.resumed_from_attempt is not None and self.resumed_from_attempt < 1:
            raise ValueError("resumed attempt number must be at least 1")
        if self.number == 1 and (
            self.resumed_from_attempt is not None or self.resume_strategy is not None
        ):
            raise ValueError("first job attempt cannot carry resume lineage")
        if self.number > 1 and (
            self.resumed_from_attempt != self.number - 1
            or self.resume_strategy is not ResumeStrategy.RECONCILE
        ):
            raise ValueError("resumed job attempt must name its coherent predecessor")


@dataclass(frozen=True, slots=True)
class JobTimestamps:
    """Lifecycle clocks carried by every canonical snapshot.

    ``admission_acquired_at`` marks when the attempt's worker actually
    began executing - for an encode-bearing job, the moment it won the
    machine-wide encode admission slot. A live attempt whose value is
    still ``None`` is honestly waiting for admission, and the span from
    ``started_at`` to this stamp is the measurable admission wait.
    """

    created_at: float
    state_changed_at: float
    started_at: float | None = None
    finished_at: float | None = None
    control_requested_at: float | None = None
    control_acknowledged_at: float | None = None
    admission_acquired_at: float | None = None


@dataclass(frozen=True, slots=True)
class JobProgress:
    """Immutable view of the canonical progress stream."""

    step: str
    completed: int
    total: int | None
    last_updated: float


@dataclass(frozen=True, slots=True)
class JobRuntimeSnapshot:
    """Process identity and live execution ownership for one snapshot."""

    pid: int
    parent_pid: int
    user: str
    executable: str
    prefix: str
    base_prefix: str
    virtual_env: str | None
    task_active: bool = False
    worker_active: bool = False


@dataclass(frozen=True, slots=True)
class ProcessResourceSnapshot:
    """Best-effort process memory readings at one lifecycle boundary."""

    rss_mb: float
    cuda_allocated_mb: float
    cuda_reserved_mb: float


@dataclass(frozen=True, slots=True)
class JobResourceSnapshot:
    """Execution-resource ownership and boundary memory readings."""

    started: ProcessResourceSnapshot | None
    finished: ProcessResourceSnapshot | None
    index_capacity_held: bool = False
    project_lease_held: bool = False
    writer_lock_held: bool = False
    pipeline_active: bool = False


@dataclass(frozen=True, slots=True)
class IndexResilienceSnapshot:
    """Canonical service-owned checkpoint, liveness, and limit projection."""

    generation_id: str | None = None
    committed_units: int = 0
    replayed_units: int = 0
    checkpoint_compatible: bool | None = None
    last_durable_progress_at: float | None = None
    no_progress_timeout_seconds: float | None = None
    no_progress_remaining_seconds: float | None = None
    circuit_state: str | None = None
    next_retry_at: float | None = None
    peak_rss_mb: float | None = None
    rss_ceiling_mb: float | None = None
    peak_cuda_allocated_mb: float | None = None
    peak_cuda_reserved_mb: float | None = None
    cuda_ceiling_mb: float | None = None
    support_profile: str | None = None
    terminal_outcome: str | None = None

    def __post_init__(self) -> None:
        for name in ("committed_units", "replayed_units"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name in (
            "last_durable_progress_at",
            "no_progress_timeout_seconds",
            "no_progress_remaining_seconds",
            "next_retry_at",
            "peak_rss_mb",
            "rss_ceiling_mb",
            "peak_cuda_allocated_mb",
            "peak_cuda_reserved_mb",
            "cuda_ceiling_mb",
        ):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value < 0.0
            ):
                raise ValueError(f"{name} must be a finite non-negative number")


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    """Immutable exact-ID view of one canonical job resource."""

    id: str
    revision: int
    spec: JobSpec
    state: JobState
    desired_state: DesiredJobState
    capabilities: JobCapabilities
    attempt: JobAttempt
    timestamps: JobTimestamps
    progress: JobProgress | None
    result: str | None
    error_kind: str | None
    initiator: JobInitiator
    runtime: JobRuntimeSnapshot
    resources: JobResourceSnapshot
    resilience: IndexResilienceSnapshot | None = None
    #: Donor vector-reuse telemetry from the finished attempt's execution
    #: result, or ``None`` when reuse was disabled or the attempt never
    #: reached the encode pipeline. Carried on the canonical resource so
    #: the served job view reports it; the legacy activity record is
    #: shadowed by this snapshot for every manager-owned job.
    reuse: dict[str, object] | None = None
    #: Source-drift telemetry from the finished attempt: how many paths moved
    #: while the run was recording them and had to be superseded, and any left
    #: stale for the next generation. Carried here because a run that
    #: remediates drift succeeds, so the circuit breaker - which counts faults
    #: only - is deliberately blind to it, and this is where drift volume
    #: becomes visible instead.
    drift: dict[str, object] | None = None
    #: Seconds the finished (or in-flight, at last publication) attempt
    #: spent waiting to acquire the process GPU lock, accumulated across
    #: every timed acquisition. ``None`` until the attempt first publishes
    #: it; together with the admission stamp this splits a job's wall
    #: clock into admission wait, lock wait, and work.
    gpu_lock_wait_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("job revision must be at least 1")

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON-ready resource representation."""
        return {
            "id": self.id,
            "revision": self.revision,
            "spec": {
                "operation": self.spec.operation.value,
                "source": self.spec.source.value,
                "project_root": self.spec.project_root,
                "mode": self.spec.mode.value if self.spec.mode is not None else None,
            },
            "state": self.state.value,
            "desired_state": self.desired_state.value,
            "capabilities": {
                "pausable": self.capabilities.pausable,
                "resumable": self.capabilities.resumable,
                "cancellable": self.capabilities.cancellable,
                "retryable": self.capabilities.retryable,
                "deletable": self.capabilities.deletable,
                "force_killable": self.capabilities.force_killable,
            },
            "attempt": self.attempt.number,
            "parent_job_id": self.attempt.parent_job_id,
            "resumed_from_attempt": self.attempt.resumed_from_attempt,
            "resume_strategy": (
                self.attempt.resume_strategy.value
                if self.attempt.resume_strategy is not None
                else None
            ),
            "created_at": self.timestamps.created_at,
            "state_changed_at": self.timestamps.state_changed_at,
            "started_at": self.timestamps.started_at,
            "finished_at": self.timestamps.finished_at,
            "control_requested_at": self.timestamps.control_requested_at,
            "control_acknowledged_at": self.timestamps.control_acknowledged_at,
            "admission_acquired_at": self.timestamps.admission_acquired_at,
            "gpu_lock_wait_seconds": self.gpu_lock_wait_seconds,
            "progress": _progress_to_dict(self.progress),
            "result": self.result,
            "error_kind": self.error_kind,
            "initiator": {
                "kind": self.initiator.kind,
                "command": self.initiator.command,
                "project_root": self.initiator.project_root,
            },
            "runtime": _runtime_to_dict(self.runtime),
            "resources": _resources_to_dict(self.resources),
            "resilience": _resilience_to_dict(self.resilience),
            "reuse": dict(self.reuse) if self.reuse is not None else None,
            "drift": dict(self.drift) if self.drift is not None else None,
        }


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """One structured service-domain result for a job command."""

    command: str
    status: JobOutcomeStatus
    code: str
    message: str
    job: JobSnapshot | None = None

    def to_dict(self) -> dict[str, object]:
        """Return one adapter-ready outcome envelope."""
        return {
            "command": self.command,
            "status": self.status.value,
            "code": self.code,
            "message": self.message,
            "job": self.job.to_dict() if self.job is not None else None,
        }


def _progress_to_dict(progress: JobProgress | None) -> dict[str, object] | None:
    if progress is None:
        return None
    return {
        "step": progress.step,
        "completed": progress.completed,
        "total": progress.total,
        "last_updated": progress.last_updated,
    }


def _runtime_to_dict(runtime: JobRuntimeSnapshot) -> dict[str, object]:
    return {
        "pid": runtime.pid,
        "parent_pid": runtime.parent_pid,
        "user": runtime.user,
        "executable": runtime.executable,
        "prefix": runtime.prefix,
        "base_prefix": runtime.base_prefix,
        "virtual_env": runtime.virtual_env,
        "task_active": runtime.task_active,
        "worker_active": runtime.worker_active,
    }


def _process_resources_to_dict(
    resources: ProcessResourceSnapshot | None,
) -> dict[str, object] | None:
    if resources is None:
        return None
    return {
        "rss_mb": resources.rss_mb,
        "cuda_allocated_mb": resources.cuda_allocated_mb,
        "cuda_reserved_mb": resources.cuda_reserved_mb,
    }


def _resources_to_dict(resources: JobResourceSnapshot) -> dict[str, object]:
    return {
        "started": _process_resources_to_dict(resources.started),
        "finished": _process_resources_to_dict(resources.finished),
        "index_capacity_held": resources.index_capacity_held,
        "project_lease_held": resources.project_lease_held,
        "writer_lock_held": resources.writer_lock_held,
        "pipeline_active": resources.pipeline_active,
    }


def _resilience_to_dict(
    resilience: IndexResilienceSnapshot | None,
) -> dict[str, object] | None:
    if resilience is None:
        return None
    return {
        "generation_id": resilience.generation_id,
        "committed_units": resilience.committed_units,
        "replayed_units": resilience.replayed_units,
        "checkpoint_compatible": resilience.checkpoint_compatible,
        "last_durable_progress_at": resilience.last_durable_progress_at,
        "no_progress_timeout_seconds": resilience.no_progress_timeout_seconds,
        "no_progress_remaining_seconds": resilience.no_progress_remaining_seconds,
        "circuit_state": resilience.circuit_state,
        "next_retry_at": resilience.next_retry_at,
        "peak_rss_mb": resilience.peak_rss_mb,
        "rss_ceiling_mb": resilience.rss_ceiling_mb,
        "peak_cuda_allocated_mb": resilience.peak_cuda_allocated_mb,
        "peak_cuda_reserved_mb": resilience.peak_cuda_reserved_mb,
        "cuda_ceiling_mb": resilience.cuda_ceiling_mb,
        "support_profile": resilience.support_profile,
        "terminal_outcome": resilience.terminal_outcome,
    }


def is_encode_bearing(spec: JobSpec) -> bool:
    """Return whether a job specification will run GPU encoding.

    Indexing any corpus (vault, code, or document) encodes on the single
    GPU, so those jobs must take the machine-wide encode admission slot.
    Maintenance and every read-only operation stay outside the gate so
    lifecycle-inert work can never starve or deadlock behind an encode job.
    """
    return spec.operation is JobOperation.INDEX and spec.source in {
        JobSource.VAULT,
        JobSource.CODE,
        JobSource.DOCUMENT,
    }


def job_spec_error(spec: JobSpec) -> str | None:
    """Return the canonical validation error for a submitted specification."""
    if spec.operation is not JobOperation.INDEX:
        return "Only indexing operations are managed by the controllable job runtime."
    if spec.source not in {JobSource.VAULT, JobSource.CODE, JobSource.DOCUMENT}:
        return "Indexing jobs require a vault, code, or document source."
    if spec.mode is None:
        return "Indexing jobs require an incremental or rebuild mode."
    if spec.project_root is None or not spec.project_root.strip():
        return "Indexing jobs require a non-empty absolute project_root."
    if not Path(spec.project_root).expanduser().is_absolute():
        return "Indexing jobs require an absolute project_root."
    return None


def active_work_identity(
    spec: JobSpec,
) -> tuple[JobOperation, JobSource, JobMode | None, str | None]:
    """Return the normalized identity used to deduplicate active work."""
    root = spec.project_root
    normalized_root = (
        None
        if root is None
        else os.path.normcase(
            os.path.realpath(os.path.abspath(os.path.expanduser(root)))
        )
    )
    return spec.operation, spec.source, spec.mode, normalized_root


def capabilities_for_state(spec: JobSpec, state: JobState) -> JobCapabilities:
    """Derive truthful operations supported by a specification and state."""
    if spec.operation is not JobOperation.INDEX or spec.source is JobSource.MAINTENANCE:
        return JobCapabilities(
            pausable=False,
            resumable=False,
            cancellable=False,
            retryable=False,
            deletable=False,
        )
    return JobCapabilities(
        pausable=state in {JobState.QUEUED, JobState.RUNNING},
        resumable=state in {JobState.PAUSING, JobState.PAUSED},
        cancellable=not state.is_terminal,
        retryable=state in {JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED},
        deletable=state.is_terminal,
    )
