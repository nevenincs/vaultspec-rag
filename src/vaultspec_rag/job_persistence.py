"""Versioned codec and atomic filesystem storage for canonical job state."""

from __future__ import annotations

import json
import logging
import math
import os
import uuid
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol, cast

from .job_models import (
    DesiredJobState,
    IndexResilienceSnapshot,
    JobAttempt,
    JobInitiator,
    JobMode,
    JobOperation,
    JobProgress,
    JobResourceSnapshot,
    JobRuntimeSnapshot,
    JobSnapshot,
    JobSource,
    JobSpec,
    JobState,
    JobTimestamps,
    ProcessResourceSnapshot,
    ResumeStrategy,
    active_work_identity,
    capabilities_for_state,
    job_spec_error,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_IDEMPOTENCY_KEY_LENGTH",
    "IdempotencyBinding",
    "PersistedManagerState",
    "PersistenceWriteError",
    "load_persisted_state",
    "save_persisted_state",
]

MAX_IDEMPOTENCY_KEY_LENGTH = 256

_SCHEMA = "vaultspec.rag.jobs"
_VERSION = 1


@dataclass(frozen=True, slots=True)
class IdempotencyBinding:
    """One durable request signature bound to its exact logical job."""

    signature: tuple[JobSpec, JobInitiator, bool]
    job_id: str


@dataclass(frozen=True, slots=True)
class PersistedManagerState:
    """One complete generation of manager-owned durable values."""

    jobs: tuple[JobSnapshot, ...]
    bindings: tuple[tuple[str, IdempotencyBinding], ...]


class PersistenceWriteError(Exception):
    """Report whether a failed save may already be visible on disk."""

    def __init__(self, detail: str, *, published: bool) -> None:
        super().__init__(detail)
        self.published = published


class _MoveFileExW(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(
        self,
        existing_path: str,
        new_path: str,
        flags: int,
        /,
    ) -> int: ...


def load_persisted_state(path: Path) -> PersistedManagerState:
    """Read and validate one complete persisted manager generation."""
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    return _parse_persisted_manager_state(payload)


def save_persisted_state(path: Path, state: PersistedManagerState) -> None:
    """Atomically make one complete manager generation durable."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        payload = _persisted_manager_state_to_dict(state)
        _ensure_parent_directory(path.parent)
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _atomic_replace(temporary, path)
    except PersistenceWriteError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            logger.debug("could not remove failed job-state temp file", exc_info=True)
        raise
    except (OSError, TypeError, ValueError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            logger.debug("could not remove failed job-state temp file", exc_info=True)
        raise PersistenceWriteError(str(exc), published=False) from exc


def _persisted_manager_state_to_dict(
    state: PersistedManagerState,
) -> dict[str, object]:
    return {
        "schema": _SCHEMA,
        "version": _VERSION,
        "jobs": [job.to_dict() for job in state.jobs],
        "idempotency": [
            _idempotency_binding_to_dict(key, binding)
            for key, binding in state.bindings
        ],
    }


def _idempotency_binding_to_dict(
    key: str,
    binding: IdempotencyBinding,
) -> dict[str, object]:
    spec, initiator, start_paused = binding.signature
    return {
        "key": key,
        "job_id": binding.job_id,
        "spec": {
            "operation": spec.operation.value,
            "source": spec.source.value,
            "project_root": spec.project_root,
            "mode": spec.mode.value if spec.mode is not None else None,
        },
        "initiator": {
            "kind": initiator.kind,
            "command": initiator.command,
            "project_root": initiator.project_root,
        },
        "start_paused": start_paused,
    }


def _atomic_replace(source: Path, destination: Path) -> None:
    """Durably publish one state file, in this layer's error vocabulary.

    The replace itself, its Windows write-through, and the sharing-violation
    ladder live in ``_atomic_write``. What stays here is the translation: a
    sync failure means the state IS published and only its crash-durability is
    in doubt, which this layer reports as ``published=True`` so a caller does
    not roll back a write every reader can already see.
    """
    from ._atomic_write import NotDurableError, replace_durably

    try:
        replace_durably(source, destination)
    except NotDurableError as exc:
        raise PersistenceWriteError(str(exc), published=True) from exc
    except OSError as exc:
        if os.name != "nt":
            raise
        raise PersistenceWriteError(str(exc), published=True) from exc


def _ensure_parent_directory(directory: Path) -> None:
    missing: list[Path] = []
    cursor = directory
    while not cursor.exists():
        missing.append(cursor)
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        for created in reversed(missing):
            _fsync_directory(created.parent)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parse_persisted_manager_state(payload: object) -> PersistedManagerState:
    root = _required_mapping(payload, "job state")
    version = root.get("version")
    if (
        root.get("schema") != _SCHEMA
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version != _VERSION
    ):
        raise ValueError("unsupported job-state schema or version")
    raw_jobs = _required_list(root.get("jobs"), "jobs")
    jobs = [
        _normalize_legacy_start_paused(_job_snapshot_from_dict(item))
        for item in raw_jobs
    ]
    ids = [job.id for job in jobs]
    if len(ids) != len(set(ids)):
        raise ValueError("persisted job IDs must be unique")

    raw_bindings = _required_list(root.get("idempotency"), "idempotency")
    bindings: list[tuple[str, IdempotencyBinding]] = []
    keys: set[str] = set()
    for item in raw_bindings:
        record = _required_mapping(item, "idempotency entry")
        key = _required_str(record.get("key"), "idempotency key")
        if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise ValueError("persisted idempotency key exceeds the supported length")
        if key in keys:
            raise ValueError("persisted idempotency keys must be unique")
        keys.add(key)
        job_id = _required_str(record.get("job_id"), "idempotency job_id")
        spec = _job_spec_from_dict(record.get("spec"))
        initiator = _job_initiator_from_dict(record.get("initiator"))
        start_paused = record.get("start_paused")
        if not isinstance(start_paused, bool):
            raise TypeError("idempotency start_paused must be boolean")
        bindings.append(
            (
                key,
                IdempotencyBinding(
                    signature=(spec, initiator, start_paused),
                    job_id=job_id,
                ),
            )
        )
    _validate_persisted_generation(jobs, bindings)
    return PersistedManagerState(jobs=tuple(jobs), bindings=tuple(bindings))


def _normalize_legacy_start_paused(job: JobSnapshot) -> JobSnapshot:
    """Upgrade the exact start-paused timestamp shape emitted by the v1 writer."""
    timestamps = job.timestamps
    acknowledgement = timestamps.control_acknowledged_at
    if (
        job.state is JobState.PAUSED
        and job.desired_state is DesiredJobState.PAUSED
        and job.attempt.number == 1
        and timestamps.started_at is None
        and timestamps.finished_at is None
        and timestamps.control_requested_at is None
        and acknowledgement is not None
        and acknowledgement == timestamps.created_at
        and timestamps.state_changed_at == timestamps.created_at
    ):
        return replace(
            job,
            timestamps=replace(
                timestamps,
                control_requested_at=acknowledgement,
            ),
        )
    return job


def _validate_persisted_generation(
    jobs: list[JobSnapshot],
    bindings: list[tuple[str, IdempotencyBinding]],
) -> None:
    by_id = {job.id: job for job in jobs}
    active_identities: set[
        tuple[JobOperation, JobSource, JobMode | None, str | None]
    ] = set()
    for job in jobs:
        _validate_persisted_job(job)
        if not job.state.is_terminal:
            identity = active_work_identity(job.spec)
            if identity in active_identities:
                raise ValueError("persisted active jobs contain equivalent work")
            active_identities.add(identity)

    for key, binding in bindings:
        referenced = by_id.get(binding.job_id)
        if referenced is None:
            raise ValueError(f"idempotency key {key!r} references a missing job")
        spec, _initiator, _start_paused = binding.signature
        spec_error = job_spec_error(spec)
        if spec_error is not None:
            raise ValueError(f"idempotency key {key!r}: {spec_error}")
        if active_work_identity(spec) != active_work_identity(referenced.spec):
            raise ValueError(
                f"idempotency key {key!r} does not identify equivalent work"
            )


def _validate_persisted_job(job: JobSnapshot) -> None:
    spec_error = job_spec_error(job.spec)
    if spec_error is not None:
        raise ValueError(f"job {job.id}: {spec_error}")
    _validate_persisted_timestamps(job)
    _validate_persisted_lifecycle(job)
    _validate_persisted_attempt(job)
    if (
        job.progress is not None
        and job.progress.total is not None
        and job.progress.completed > job.progress.total
    ):
        raise ValueError(f"job {job.id}: progress exceeds total")


def _validate_persisted_timestamps(job: JobSnapshot) -> None:
    timestamps = job.timestamps
    if timestamps.state_changed_at < timestamps.created_at:
        raise ValueError(f"job {job.id}: state change predates creation")
    for name, value in (
        ("started_at", timestamps.started_at),
        ("finished_at", timestamps.finished_at),
        ("control_requested_at", timestamps.control_requested_at),
        ("control_acknowledged_at", timestamps.control_acknowledged_at),
        ("admission_acquired_at", timestamps.admission_acquired_at),
    ):
        if value is not None and value < timestamps.created_at:
            raise ValueError(f"job {job.id}: {name} predates creation")
    if timestamps.admission_acquired_at is not None and timestamps.started_at is None:
        raise ValueError(f"job {job.id}: admission stamp lacks an attempt start")
    if (
        timestamps.control_acknowledged_at is not None
        and timestamps.control_requested_at is None
    ):
        raise ValueError(f"job {job.id}: control acknowledgement lacks a request")
    if (
        timestamps.control_requested_at is not None
        and timestamps.control_acknowledged_at is not None
        and timestamps.control_acknowledged_at < timestamps.control_requested_at
    ):
        raise ValueError(f"job {job.id}: control acknowledgement predates request")
    if (
        timestamps.started_at is not None
        and timestamps.finished_at is not None
        and timestamps.finished_at < timestamps.started_at
    ):
        raise ValueError(f"job {job.id}: finish time predates attempt start")
    if (
        timestamps.finished_at is not None
        and timestamps.finished_at < timestamps.state_changed_at
    ):
        raise ValueError(f"job {job.id}: finish time predates the final state change")
    if job.state.is_terminal != (timestamps.finished_at is not None):
        raise ValueError(f"job {job.id}: terminal state and finish time disagree")


def _validate_persisted_lifecycle(job: JobSnapshot) -> None:
    expected_desired: dict[JobState, set[DesiredJobState]] = {
        JobState.QUEUED: {DesiredJobState.RUNNING},
        JobState.RUNNING: {DesiredJobState.RUNNING},
        JobState.PAUSING: {DesiredJobState.PAUSED, DesiredJobState.RUNNING},
        JobState.PAUSED: {DesiredJobState.PAUSED},
        JobState.CANCELLING: {DesiredJobState.CANCELLED},
        JobState.CANCELLED: {DesiredJobState.CANCELLED},
    }
    allowed_desired = expected_desired.get(job.state)
    if allowed_desired is not None and job.desired_state not in allowed_desired:
        raise ValueError(f"job {job.id}: observed and desired states disagree")
    if (
        job.state in {JobState.RUNNING, JobState.PAUSING, JobState.CANCELLING}
        and job.timestamps.started_at is None
    ):
        raise ValueError(f"job {job.id}: live attempt lacks a start time")
    if job.state not in {JobState.QUEUED, JobState.PAUSED}:
        return
    resources = job.resources
    if (
        job.runtime.task_active
        or job.runtime.worker_active
        or any(
            (
                resources.index_capacity_held,
                resources.project_lease_held,
                resources.writer_lock_held,
                resources.pipeline_active,
            )
        )
    ):
        raise ValueError(f"job {job.id}: inactive state retains live resources")


def _validate_persisted_attempt(job: JobSnapshot) -> None:
    attempt = job.attempt
    if attempt.number == 1:
        if (
            attempt.resumed_from_attempt is not None
            or attempt.resume_strategy is not None
        ):
            raise ValueError(f"job {job.id}: first attempt claims resume lineage")
    elif (
        attempt.resumed_from_attempt != attempt.number - 1
        or attempt.resume_strategy is not ResumeStrategy.RECONCILE
    ):
        raise ValueError(f"job {job.id}: invalid resume attempt lineage")
    if attempt.parent_job_id == job.id:
        raise ValueError(f"job {job.id}: retry parent cannot reference itself")


def _job_snapshot_from_dict(value: object) -> JobSnapshot:
    raw = _required_mapping(value, "job")
    spec = _job_spec_from_dict(raw.get("spec"))
    state = JobState(_required_str(raw.get("state"), "job state"))
    desired_state = DesiredJobState(
        _required_str(raw.get("desired_state"), "job desired_state")
    )
    attempt_number = _required_int(raw.get("attempt"), "job attempt", minimum=1)
    resumed_from = _optional_int(
        raw.get("resumed_from_attempt"),
        "job resumed_from_attempt",
        minimum=1,
    )
    resume_raw = _optional_str(raw.get("resume_strategy"), "job resume_strategy")
    progress_raw = raw.get("progress")
    progress = None if progress_raw is None else _job_progress_from_dict(progress_raw)
    return JobSnapshot(
        id=_required_str(raw.get("id"), "job id"),
        revision=_required_int(raw.get("revision"), "job revision", minimum=1),
        spec=spec,
        state=state,
        desired_state=desired_state,
        capabilities=capabilities_for_state(spec, state),
        attempt=JobAttempt(
            number=attempt_number,
            parent_job_id=_optional_str(raw.get("parent_job_id"), "parent_job_id"),
            resumed_from_attempt=resumed_from,
            resume_strategy=(
                ResumeStrategy(resume_raw) if resume_raw is not None else None
            ),
        ),
        timestamps=JobTimestamps(
            created_at=_required_float(raw.get("created_at"), "created_at"),
            state_changed_at=_required_float(
                raw.get("state_changed_at"), "state_changed_at"
            ),
            started_at=_optional_float(raw.get("started_at"), "started_at"),
            finished_at=_optional_float(raw.get("finished_at"), "finished_at"),
            control_requested_at=_optional_float(
                raw.get("control_requested_at"), "control_requested_at"
            ),
            control_acknowledged_at=_optional_float(
                raw.get("control_acknowledged_at"), "control_acknowledged_at"
            ),
            admission_acquired_at=_optional_float(
                raw.get("admission_acquired_at"), "admission_acquired_at"
            ),
        ),
        progress=progress,
        result=_optional_str(raw.get("result"), "job result"),
        error_kind=_optional_str(raw.get("error_kind"), "job error_kind"),
        initiator=_job_initiator_from_dict(raw.get("initiator")),
        runtime=_job_runtime_from_dict(raw.get("runtime")),
        resources=_job_resources_from_dict(raw.get("resources")),
        resilience=_job_resilience_from_dict(raw.get("resilience")),
        reuse=_optional_telemetry_block(raw.get("reuse"), "job reuse"),
        drift=_optional_telemetry_block(raw.get("drift"), "job drift"),
        gpu_lock_wait_seconds=_optional_float(
            raw.get("gpu_lock_wait_seconds"), "gpu_lock_wait_seconds"
        ),
    )


def _job_spec_from_dict(value: object) -> JobSpec:
    raw = _required_mapping(value, "job spec")
    mode = _optional_str(raw.get("mode"), "job mode")
    return JobSpec(
        operation=JobOperation(_required_str(raw.get("operation"), "job operation")),
        source=JobSource(_required_str(raw.get("source"), "job source")),
        project_root=_optional_str(raw.get("project_root"), "job project_root"),
        mode=JobMode(mode) if mode is not None else None,
    )


def _job_initiator_from_dict(value: object) -> JobInitiator:
    raw = _required_mapping(value, "job initiator")
    return JobInitiator(
        kind=_required_str(raw.get("kind"), "initiator kind"),
        command=_required_str(raw.get("command"), "initiator command"),
        project_root=_optional_str(raw.get("project_root"), "initiator project_root"),
    )


def _job_progress_from_dict(value: object) -> JobProgress:
    raw = _required_mapping(value, "job progress")
    return JobProgress(
        step=_required_str(raw.get("step"), "progress step"),
        completed=_required_int(raw.get("completed"), "progress completed", minimum=0),
        total=_optional_int(raw.get("total"), "progress total", minimum=0),
        last_updated=_required_float(raw.get("last_updated"), "progress last_updated"),
    )


def _job_runtime_from_dict(value: object) -> JobRuntimeSnapshot:
    raw = _required_mapping(value, "job runtime")
    task_active = raw.get("task_active")
    worker_active = raw.get("worker_active")
    if not isinstance(task_active, bool) or not isinstance(worker_active, bool):
        raise TypeError("runtime activity fields must be boolean")
    return JobRuntimeSnapshot(
        pid=_required_int(raw.get("pid"), "runtime pid", minimum=0),
        parent_pid=_required_int(
            raw.get("parent_pid"), "runtime parent_pid", minimum=0
        ),
        user=_required_str(raw.get("user"), "runtime user", allow_empty=True),
        executable=_required_str(
            raw.get("executable"), "runtime executable", allow_empty=True
        ),
        prefix=_required_str(raw.get("prefix"), "runtime prefix", allow_empty=True),
        base_prefix=_required_str(
            raw.get("base_prefix"), "runtime base_prefix", allow_empty=True
        ),
        virtual_env=_optional_str(raw.get("virtual_env"), "runtime virtual_env"),
        task_active=task_active,
        worker_active=worker_active,
    )


def _job_resources_from_dict(value: object) -> JobResourceSnapshot:
    raw = _required_mapping(value, "job resources")
    booleans: dict[str, bool] = {}
    for field in (
        "index_capacity_held",
        "project_lease_held",
        "writer_lock_held",
        "pipeline_active",
    ):
        field_value = raw.get(field)
        if not isinstance(field_value, bool):
            raise TypeError(f"resource {field} must be boolean")
        booleans[field] = field_value
    return JobResourceSnapshot(
        started=_process_resources_from_dict(raw.get("started")),
        finished=_process_resources_from_dict(raw.get("finished")),
        index_capacity_held=booleans["index_capacity_held"],
        project_lease_held=booleans["project_lease_held"],
        writer_lock_held=booleans["writer_lock_held"],
        pipeline_active=booleans["pipeline_active"],
    )


def _process_resources_from_dict(value: object) -> ProcessResourceSnapshot | None:
    if value is None:
        return None
    raw = _required_mapping(value, "process resources")
    return ProcessResourceSnapshot(
        rss_mb=_required_nonnegative_float(raw.get("rss_mb"), "resource rss_mb"),
        cuda_allocated_mb=_required_nonnegative_float(
            raw.get("cuda_allocated_mb"), "resource cuda_allocated_mb"
        ),
        cuda_reserved_mb=_required_nonnegative_float(
            raw.get("cuda_reserved_mb"), "resource cuda_reserved_mb"
        ),
    )


def _job_resilience_from_dict(value: object) -> IndexResilienceSnapshot | None:
    if value is None:
        return None
    raw = _required_mapping(value, "job resilience")
    checkpoint_compatible = raw.get("checkpoint_compatible")
    if checkpoint_compatible is not None and not isinstance(
        checkpoint_compatible, bool
    ):
        raise TypeError("resilience checkpoint_compatible must be boolean or null")
    return IndexResilienceSnapshot(
        generation_id=_optional_str(
            raw.get("generation_id"),
            "resilience generation_id",
        ),
        committed_units=_required_int(
            raw.get("committed_units", 0),
            "resilience committed_units",
            minimum=0,
        ),
        replayed_units=_required_int(
            raw.get("replayed_units", 0),
            "resilience replayed_units",
            minimum=0,
        ),
        checkpoint_compatible=checkpoint_compatible,
        last_durable_progress_at=_optional_float(
            raw.get("last_durable_progress_at"),
            "resilience last_durable_progress_at",
        ),
        no_progress_timeout_seconds=_optional_float(
            raw.get("no_progress_timeout_seconds"),
            "resilience no_progress_timeout_seconds",
        ),
        no_progress_remaining_seconds=_optional_float(
            raw.get("no_progress_remaining_seconds"),
            "resilience no_progress_remaining_seconds",
        ),
        circuit_state=_optional_str(
            raw.get("circuit_state"),
            "resilience circuit_state",
        ),
        next_retry_at=_optional_float(
            raw.get("next_retry_at"),
            "resilience next_retry_at",
        ),
        peak_rss_mb=_optional_float(
            raw.get("peak_rss_mb"),
            "resilience peak_rss_mb",
        ),
        rss_ceiling_mb=_optional_float(
            raw.get("rss_ceiling_mb"),
            "resilience rss_ceiling_mb",
        ),
        peak_cuda_allocated_mb=_optional_float(
            raw.get("peak_cuda_allocated_mb"),
            "resilience peak_cuda_allocated_mb",
        ),
        peak_cuda_reserved_mb=_optional_float(
            raw.get("peak_cuda_reserved_mb"),
            "resilience peak_cuda_reserved_mb",
        ),
        cuda_ceiling_mb=_optional_float(
            raw.get("cuda_ceiling_mb"),
            "resilience cuda_ceiling_mb",
        ),
        support_profile=_optional_str(
            raw.get("support_profile"),
            "resilience support_profile",
        ),
        terminal_outcome=_optional_str(
            raw.get("terminal_outcome"),
            "resilience terminal_outcome",
        ),
    )


def _optional_telemetry_block(value: object, name: str) -> dict[str, object] | None:
    """Read one optional run-telemetry block, absent on older persisted state."""
    if value is None:
        return None
    return dict(_required_mapping(value, name))


def _required_mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object with string keys")
    untyped = cast("dict[object, object]", value)
    if not all(isinstance(key, str) for key in untyped):
        raise TypeError(f"{name} must be an object with string keys")
    return cast("dict[str, object]", value)


def _required_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    return cast("list[object]", value)


def _required_str(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _optional_str(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _required_str(value, name, allow_empty=True)


def _required_int(value: object, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TypeError(f"{name} must be an integer of at least {minimum}")
    return value


def _optional_int(value: object, name: str, *, minimum: int) -> int | None:
    if value is None:
        return None
    return _required_int(value, name, minimum=minimum)


def _required_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError(f"{name} must be finite")
    return resolved


def _required_nonnegative_float(value: object, name: str) -> float:
    resolved = _required_float(value, name)
    if resolved < 0:
        raise ValueError(f"{name} must not be negative")
    return resolved


def _optional_float(value: object, name: str) -> float | None:
    if value is None:
        return None
    return _required_float(value, name)
