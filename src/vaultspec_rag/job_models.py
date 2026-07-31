"""Canonical immutable models for service-owned jobs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from . import _typed_fields

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

    @property
    def is_corpus(self) -> bool:
        """Return whether this source names a corpus rather than housekeeping.

        Indexing a corpus encodes on the single GPU and takes the machine-wide
        admission slot; maintenance is the service's own storage work and
        stays outside that gate. Four call sites drew the line by listing the
        three corpora, so adding a fourth would have had to be remembered in
        all four before it could be indexed at all.
        """
        return self is not JobSource.MAINTENANCE


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
    #: A retryable terminal record whose linked retry has since succeeded.
    #: The record is preserved as history, but it no longer advertises
    #: retryability: the work it represents got through, so offering retry
    #: again would send an operator around a loop that can never resolve.
    SUPERSEDED = "superseded"

    @property
    def is_terminal(self) -> bool:
        """Return whether no attempt may ever run for this resource again.

        A terminal record never returns to the active set. The one terminal
        transition that remains is resolution: a retryable terminal record
        becomes superseded when a linked retry succeeds.
        """
        return self in {
            JobState.CANCELLED,
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.INTERRUPTED,
            JobState.SUPERSEDED,
        }

    @property
    def is_live_attempt(self) -> bool:
        """Return whether an attempt is in flight in this state.

        Running, pausing and cancelling all mean a worker is still holding the
        attempt: it is progressing, winding down, or being torn down. Three
        call sites tested for it by listing the members - accepting progress,
        restoring a snapshot, and asserting a live attempt has a start time -
        which is one grouping written three ways.
        """
        return self in {
            JobState.RUNNING,
            JobState.PAUSING,
            JobState.CANCELLING,
        }

    @property
    def is_retryable(self) -> bool:
        """Return whether a finished attempt in this state may be retried.

        Narrower than :attr:`is_terminal`: a succeeded job is terminal and has
        nothing to retry, and a superseded job's work already succeeded
        through a linked retry. One of the two call sites already called its result
        `retryable`; the other described the same set as "terminal" in an
        error message it shows an operator, which is the imprecision that
        having no name for the grouping produces.
        """
        return self in {
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.INTERRUPTED,
        }

    @property
    def is_idle(self) -> bool:
        """Return whether no worker attempt is holding this job.

        Covers both ends of never having started: queued work waiting for a
        worker, and paused work a worker has released. Six call sites tested
        for it by listing the members - restoring persisted state, bounding
        active job counts, validating an inactive state holds no live
        resources, cancelling immediately rather than requesting a teardown,
        preparing same-id resume after a quiesce, and recording watcher
        progress - which is one grouping written six times.
        """
        return self in {
            JobState.QUEUED,
            JobState.PAUSED,
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


def _rejection(name: str, requirement: str, *, optional: bool) -> ValueError:
    return ValueError(f"{name} must be {requirement}{' or None' if optional else ''}")


def _integer_requirement(minimum: int) -> str:
    if minimum == 0:
        return "a non-negative integer"
    return f"an integer of at least {minimum}"


def _number_requirement(minimum: float | None) -> str:
    if minimum is None:
        return "a finite number"
    if minimum == 0:
        return "a finite non-negative number"
    return f"a finite number of at least {minimum}"


def _require_int(
    name: str, value: object, *, minimum: int, optional: bool = False
) -> None:
    if optional and value is None:
        return
    requirement = _integer_requirement(minimum)
    _typed_fields.required_int(
        value,
        minimum=minimum,
        on_invalid=lambda: _rejection(name, requirement, optional=optional),
    )


def _require_number(
    name: str, value: object, *, minimum: float | None = None, optional: bool = False
) -> None:
    if optional and value is None:
        return
    requirement = _number_requirement(minimum)

    def reject() -> ValueError:
        return _rejection(name, requirement, optional=optional)

    resolved = _typed_fields.required_float(
        value, on_invalid=reject, on_not_finite=reject
    )
    if minimum is not None and resolved < minimum:
        raise reject()


def _require_str(
    name: str, value: object, *, allow_empty: bool = False, optional: bool = False
) -> None:
    if optional and value is None:
        return
    requirement = "a string" if allow_empty else "a non-empty string"
    _typed_fields.required_str(
        value,
        allow_empty=allow_empty,
        on_invalid=lambda: _rejection(name, requirement, optional=optional),
    )


def _require_bool(name: str, value: object, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    _typed_fields.required_bool(
        value,
        on_invalid=lambda: _rejection(name, "a boolean", optional=optional),
    )


def _require_string_keyed_mapping(name: str, value: object) -> None:
    if value is None:
        return
    _typed_fields.required_mapping(
        value,
        on_invalid=lambda: _rejection(
            name, "a mapping with string keys", optional=True
        ),
    )


@dataclass(frozen=True, slots=True)
class JobSpec:
    """Immutable instructions for one logical job resource."""

    operation: JobOperation
    source: JobSource
    project_root: str | None
    mode: JobMode | None

    def __post_init__(self) -> None:
        _require_str("project_root", self.project_root, allow_empty=True, optional=True)


@dataclass(frozen=True, slots=True)
class JobInitiator:
    """Immutable attribution retained across execution attempts."""

    kind: str
    command: str
    project_root: str | None

    def __post_init__(self) -> None:
        _require_str("kind", self.kind)
        _require_str("command", self.command)
        _require_str("project_root", self.project_root, allow_empty=True, optional=True)


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
        _require_int("number", self.number, minimum=1)
        _require_int(
            "resumed_from_attempt", self.resumed_from_attempt, minimum=1, optional=True
        )
        _require_str(
            "parent_job_id", self.parent_job_id, allow_empty=True, optional=True
        )
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

    def __post_init__(self) -> None:
        _require_number("created_at", self.created_at)
        _require_number("state_changed_at", self.state_changed_at)
        _require_number("started_at", self.started_at, optional=True)
        _require_number("finished_at", self.finished_at, optional=True)
        _require_number(
            "control_requested_at", self.control_requested_at, optional=True
        )
        _require_number(
            "control_acknowledged_at", self.control_acknowledged_at, optional=True
        )
        _require_number(
            "admission_acquired_at", self.admission_acquired_at, optional=True
        )


@dataclass(frozen=True, slots=True)
class JobProgress:
    """Immutable view of the canonical progress stream."""

    step: str
    completed: int
    total: int | None
    last_updated: float

    def __post_init__(self) -> None:
        _require_str("step", self.step)
        _require_int("completed", self.completed, minimum=0)
        _require_int("total", self.total, minimum=0, optional=True)
        _require_number("last_updated", self.last_updated)
        if self.total is not None and self.completed > self.total:
            raise ValueError("completed must not exceed total")


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

    def __post_init__(self) -> None:
        _require_int("pid", self.pid, minimum=0)
        _require_int("parent_pid", self.parent_pid, minimum=0)
        _require_str("user", self.user, allow_empty=True)
        _require_str("executable", self.executable, allow_empty=True)
        _require_str("prefix", self.prefix, allow_empty=True)
        _require_str("base_prefix", self.base_prefix, allow_empty=True)
        _require_str("virtual_env", self.virtual_env, allow_empty=True, optional=True)
        _require_bool("task_active", self.task_active)
        _require_bool("worker_active", self.worker_active)


@dataclass(frozen=True, slots=True)
class ProcessResourceSnapshot:
    """Best-effort process memory readings at one lifecycle boundary.

    Best-effort refers to how the readings are obtained, never to whether
    they are present: a probe that cannot answer reports zero. A missing or
    non-numeric reading is rejected here, at the boundary that produced it,
    because these values outlive the process that took them. Accepting one
    would place a record on disk that the loader must refuse, stranding the
    failure in a later process with no way back to the producer.
    """

    rss_mib: float
    cuda_allocated_mib: float
    cuda_reserved_mib: float

    def __post_init__(self) -> None:
        _require_number("rss_mib", self.rss_mib, minimum=0.0)
        _require_number("cuda_allocated_mib", self.cuda_allocated_mib, minimum=0.0)
        _require_number("cuda_reserved_mib", self.cuda_reserved_mib, minimum=0.0)


@dataclass(frozen=True, slots=True)
class JobResourceSnapshot:
    """Execution-resource ownership and boundary memory readings."""

    started: ProcessResourceSnapshot | None
    finished: ProcessResourceSnapshot | None
    index_capacity_held: bool = False
    project_lease_held: bool = False
    writer_lock_held: bool = False
    pipeline_active: bool = False

    def __post_init__(self) -> None:
        _require_bool("index_capacity_held", self.index_capacity_held)
        _require_bool("project_lease_held", self.project_lease_held)
        _require_bool("writer_lock_held", self.writer_lock_held)
        _require_bool("pipeline_active", self.pipeline_active)

    @property
    def holds_anything(self) -> bool:
        """Return whether this attempt still owns an execution resource.

        The job manager and the persistence validator each answered this by
        listing all four flags. A fifth resource would have been added to the
        snapshot and silently missing from both questions, which is how a job
        holding something comes to look idle.
        """
        return (
            self.index_capacity_held
            or self.project_lease_held
            or self.writer_lock_held
            or self.pipeline_active
        )


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
    peak_rss_mib: float | None = None
    rss_ceiling_mib: float | None = None
    peak_cuda_allocated_mib: float | None = None
    peak_cuda_reserved_mib: float | None = None
    cuda_ceiling_mib: float | None = None
    support_profile: str | None = None
    terminal_outcome: str | None = None

    def __post_init__(self) -> None:
        _require_int("committed_units", self.committed_units, minimum=0)
        _require_int("replayed_units", self.replayed_units, minimum=0)
        for name, reading in (
            ("last_durable_progress_at", self.last_durable_progress_at),
            ("no_progress_timeout_seconds", self.no_progress_timeout_seconds),
            ("no_progress_remaining_seconds", self.no_progress_remaining_seconds),
            ("next_retry_at", self.next_retry_at),
            ("peak_rss_mib", self.peak_rss_mib),
            ("rss_ceiling_mib", self.rss_ceiling_mib),
            ("peak_cuda_allocated_mib", self.peak_cuda_allocated_mib),
            ("peak_cuda_reserved_mib", self.peak_cuda_reserved_mib),
            ("cuda_ceiling_mib", self.cuda_ceiling_mib),
        ):
            _require_number(name, reading, minimum=0.0, optional=True)
        for name, label in (
            ("generation_id", self.generation_id),
            ("circuit_state", self.circuit_state),
            ("support_profile", self.support_profile),
            ("terminal_outcome", self.terminal_outcome),
        ):
            _require_str(name, label, allow_empty=True, optional=True)
        _require_bool(
            "checkpoint_compatible", self.checkpoint_compatible, optional=True
        )


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
        _require_str("id", self.id)
        _require_int("revision", self.revision, minimum=1)
        _require_str("result", self.result, allow_empty=True, optional=True)
        _require_str("error_kind", self.error_kind, allow_empty=True, optional=True)
        _require_number(
            "gpu_lock_wait_seconds",
            self.gpu_lock_wait_seconds,
            minimum=0.0,
            optional=True,
        )
        _require_string_keyed_mapping("reuse", self.reuse)
        _require_string_keyed_mapping("drift", self.drift)

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
        "rss_mib": resources.rss_mib,
        "cuda_allocated_mib": resources.cuda_allocated_mib,
        "cuda_reserved_mib": resources.cuda_reserved_mib,
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
        "peak_rss_mib": resilience.peak_rss_mib,
        "rss_ceiling_mib": resilience.rss_ceiling_mib,
        "peak_cuda_allocated_mib": resilience.peak_cuda_allocated_mib,
        "peak_cuda_reserved_mib": resilience.peak_cuda_reserved_mib,
        "cuda_ceiling_mib": resilience.cuda_ceiling_mib,
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
    return spec.operation is JobOperation.INDEX and spec.source.is_corpus


def job_spec_error(spec: JobSpec) -> str | None:
    """Return the canonical validation error for a submitted specification."""
    if spec.operation is not JobOperation.INDEX:
        return "Only indexing operations are managed by the controllable job runtime."
    if not spec.source.is_corpus:
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
        retryable=state.is_retryable,
        deletable=state.is_terminal,
    )
