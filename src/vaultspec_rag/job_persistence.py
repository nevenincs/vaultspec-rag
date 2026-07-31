"""Versioned codec and atomic filesystem storage for canonical job state.

How this file format is allowed to change
-----------------------------------------

The daemon writes this file itself on every lifecycle transition and reads it
back on the next start, so a reader that refuses what an earlier writer emitted
costs an operator their whole job history. Two properties keep a routine change
from having that consequence:

- **Growth is additive and does not move the version.** The reader takes only
  the keys it knows and defaults every optional one, so a file carrying fields
  a build has never heard of loads cleanly, and so does a file predating a
  field that build now writes. Adding an optional field is therefore not a
  format change at all, which is what keeps ``version`` from moving for
  reasons that never justified it.
- **``version`` is a supported range, not one number.** It moves only for a
  re-layout no additive read can absorb, and :data:`_MINIMUM_READABLE_VERSION`
  stays behind when it does, so the build that introduces a new layout still
  reads every file written before it. A file numbered above what a build knows
  is refused rather than read blind, because guessing at a layout that has
  genuinely changed is how a misread record becomes a wrong decision.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from . import _typed_fields
from ._atomic_write import (
    JsonWriteOptions,
    NotDurableError,
    fsync_directory,
    write_json_atomically,
)
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

#: The newest layout this build emits and can interpret.
_VERSION = 1

#: The oldest layout this build still reads. Raising ``_VERSION`` for a real
#: re-layout must leave this behind, so the release that changes the layout
#: still loads every file written before it.
_MINIMUM_READABLE_VERSION = 1

#: How long an unpublished temporary must have sat untouched before recovery
#: reclaims it. A publication holds the write lock and completes in
#: milliseconds, so a window this wide cannot reach a write still in flight -
#: including one belonging to another process sharing the directory.
_ORPHANED_TEMPORARY_GRACE_SECONDS = 24 * 60 * 60


#: Stated once because the reader narrows this field and the producer is held
#: to it; two spellings of one requirement is how the pair drifts apart.
_START_PAUSED_REQUIREMENT = "idempotency start_paused must be boolean"


@dataclass(frozen=True, slots=True)
class IdempotencyBinding:
    """One durable request signature bound to its exact logical job."""

    signature: tuple[JobSpec, JobInitiator, bool]
    job_id: str

    def __post_init__(self) -> None:
        _required_str(self.job_id, "idempotency job_id")
        # The reader checks this flag's type explicitly, so anything else
        # written here is a binding that loads fine today and is refused on
        # the next start, in another process. Refused at the producer instead.
        _typed_fields.required_bool(
            self.signature[2],
            on_invalid=lambda: TypeError(_START_PAUSED_REQUIREMENT),
        )


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


def load_persisted_state(path: Path) -> PersistedManagerState:
    """Read and validate one complete persisted manager generation.

    Reclaims this writer's abandoned temporaries first, because a start is the
    only moment at which one can be told apart from a write still in progress.
    """
    _reclaim_orphaned_temporaries(path)
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    return _parse_persisted_manager_state(payload)


def save_persisted_state(path: Path, state: PersistedManagerState) -> None:
    """Atomically make one complete manager generation durable.

    The write, its temporary's cleanup, and the Windows sharing-violation
    ladder all belong to the shared atomic publisher. What stays here is the
    translation into this layer's error vocabulary, and it turns on one
    question only: did the replace land?

    ``NotDurableError`` is the sole way that publisher reports a landed replace
    it could not force to disk. The state IS published then, and only its
    crash-durability is in doubt, so this reports ``published=True`` and the
    caller does not roll back a write every reader can already see.

    Every other failure means the bytes never became visible and the previous
    generation is still the one on disk. Reporting those as published would
    strand a caller's in-memory mutation with no rollback and no record on
    disk, which is the opposite of what happened.
    """
    try:
        payload = _persisted_manager_state_to_dict(state)
        _ensure_parent_directory(path.parent)
        write_json_atomically(
            path,
            payload,
            JsonWriteOptions(sort_keys=True, durable=True),
        )
    except NotDurableError as exc:
        raise PersistenceWriteError(str(exc), published=True) from exc
    # RecursionError joins the serialization faults: a telemetry block nested
    # past the encoder's limit is a payload this generation cannot be written
    # from, and letting it escape untranslated would break the one exception
    # type every caller of this function handles.
    except (OSError, TypeError, ValueError, RecursionError) as exc:
        raise PersistenceWriteError(str(exc), published=False) from exc


def _reclaim_orphaned_temporaries(path: Path) -> None:
    """Delete this writer's temporaries that no publication ever consumed.

    A temporary only survives its writer when the process died between
    creating it and replacing the state file with it - a kill or a power loss,
    where no cleanup of any kind gets to run. They accumulate for the life of
    the installation otherwise, because nothing else ever looks at them.

    Deleting one destroys nothing an operator can use, which is what separates
    this from the state file itself: the state file is the only copy of the
    history it holds, while a temporary by construction never became visible
    to any reader and never superseded anything. Two conditions still gate it:

    - **Positive identification, never a pattern sweep.** Only a sibling whose
      name is this exact target's temporary form is a candidate. The state file
      carries no leading dot, and a file set aside for diagnosis carries
      neither the leading dot nor the suffix, so preserved evidence cannot be
      named by this and is not merely unlikely to be.
    - **A grace window read from the filesystem's own record.** The candidate's
      last-modified time is a durable observation that survives restarts, so a
      writer that is merely slow, or one in another process, keeps its
      temporary. Anything a clock skew or a fresh timestamp makes ambiguous is
      left alone, so a race can only spare a temporary, never take a live one.

    Reclaiming is housekeeping, never a precondition for reading. Any failure
    leaves the file for the next start rather than turning a startup into a
    failure over a file nobody needs.
    """
    prefix = f".{path.name}."
    now = time.time()
    reclaimed = 0
    try:
        candidates = list(path.parent.iterdir())
    except OSError:
        logger.debug(
            "could not scan for abandoned job-state temporaries", exc_info=True
        )
        return
    for candidate in candidates:
        name = candidate.name
        if not name.startswith(prefix) or not name.endswith(".tmp"):
            continue
        try:
            if not candidate.is_file():
                continue
            if now - candidate.stat().st_mtime < _ORPHANED_TEMPORARY_GRACE_SECONDS:
                continue
            candidate.unlink()
        except OSError:
            logger.debug(
                "could not reclaim abandoned job-state temporary", exc_info=True
            )
            continue
        reclaimed += 1
    if reclaimed:
        logger.info(
            "reclaimed %d abandoned job-state temporary file(s) from %s",
            reclaimed,
            path.parent,
        )


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
    for created in reversed(missing):
        fsync_directory(created.parent)


def _parse_persisted_manager_state(payload: object) -> PersistedManagerState:
    root = _required_mapping(payload, "job state")
    _validate_schema_header(root)
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
        start_paused = _typed_fields.required_bool(
            record.get("start_paused"),
            on_invalid=lambda: TypeError(_START_PAUSED_REQUIREMENT),
        )
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


def _validate_schema_header(root: dict[str, object]) -> None:
    """Accept every layout this build reads, and name what it refuses and why.

    One message for three unrelated conditions left an operator unable to tell
    a file this build predates from one it cannot parse at all, so each states
    the direction of the mismatch and the range that would have been read.
    """
    schema = root.get("schema")
    if schema != _SCHEMA:
        raise ValueError(
            f"job state declares schema {schema!r}, but this build reads {_SCHEMA!r}"
        )
    version = root.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("job-state version must be an integer")
    if version > _VERSION:
        raise ValueError(
            f"job-state version {version} was written by a newer build; this one "
            f"reads versions {_MINIMUM_READABLE_VERSION} to {_VERSION}"
        )
    if version < _MINIMUM_READABLE_VERSION:
        raise ValueError(
            f"job-state version {version} is no longer readable; this build "
            f"reads versions {_MINIMUM_READABLE_VERSION} to {_VERSION}"
        )


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
        # A paused job wanting to run is how work parked by a service quiesce
        # is told apart from work an operator paused: the resume pass selects
        # on exactly that pair. Refusing it here rejects a file the manager
        # writes itself whenever a daemon dies inside a quiesce window.
        JobState.PAUSED: {DesiredJobState.PAUSED, DesiredJobState.RUNNING},
        JobState.CANCELLING: {DesiredJobState.CANCELLED},
        JobState.CANCELLED: {DesiredJobState.CANCELLED},
    }
    allowed_desired = expected_desired.get(job.state)
    if allowed_desired is not None and job.desired_state not in allowed_desired:
        raise ValueError(f"job {job.id}: observed and desired states disagree")
    if job.state.is_live_attempt and job.timestamps.started_at is None:
        raise ValueError(f"job {job.id}: live attempt lacks a start time")
    if not job.state.is_idle:
        return
    resources = job.resources
    if job.runtime.task_active or job.runtime.worker_active or resources.holds_anything:
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
        # Capabilities are written - they belong to the one resource
        # representation the served views also render - and deliberately not
        # read. They are a total function of the specification and the state,
        # both of which round-trip exactly, so deriving them again yields what
        # the writer emitted. Reading them instead would let a file assert an
        # action this build no longer supports.
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
        rss_mib=_required_nonnegative_float(raw.get("rss_mib"), "resource rss_mib"),
        cuda_allocated_mib=_required_nonnegative_float(
            raw.get("cuda_allocated_mib"), "resource cuda_allocated_mib"
        ),
        cuda_reserved_mib=_required_nonnegative_float(
            raw.get("cuda_reserved_mib"), "resource cuda_reserved_mib"
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
        peak_rss_mib=_optional_float(
            raw.get("peak_rss_mib"),
            "resilience peak_rss_mib",
        ),
        rss_ceiling_mib=_optional_float(
            raw.get("rss_ceiling_mib"),
            "resilience rss_ceiling_mib",
        ),
        peak_cuda_allocated_mib=_optional_float(
            raw.get("peak_cuda_allocated_mib"),
            "resilience peak_cuda_allocated_mib",
        ),
        peak_cuda_reserved_mib=_optional_float(
            raw.get("peak_cuda_reserved_mib"),
            "resilience peak_cuda_reserved_mib",
        ),
        cuda_ceiling_mib=_optional_float(
            raw.get("cuda_ceiling_mib"),
            "resilience cuda_ceiling_mib",
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
    """Read one optional run-telemetry block, absent on older persisted state.

    Narrows the block to its declared type only. What the values inside it may
    be is the model's contract, enforced once at construction for the writer
    and the reader alike, so this cannot refuse a shape the writer can emit.
    """
    if value is None:
        return None
    return dict(_required_mapping(value, name))


def _required_mapping(value: object, name: str) -> dict[str, object]:
    return _typed_fields.required_mapping(
        value,
        on_invalid=lambda: TypeError(f"{name} must be an object with string keys"),
    )


def _required_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    return cast("list[object]", value)


def _required_str(value: object, name: str, *, allow_empty: bool = False) -> str:
    return _typed_fields.required_str(
        value,
        allow_empty=allow_empty,
        on_invalid=lambda: TypeError(f"{name} must be a non-empty string"),
    )


def _optional_str(value: object, name: str) -> str | None:
    return None if value is None else _required_str(value, name, allow_empty=True)


def _required_int(value: object, name: str, *, minimum: int) -> int:
    return _typed_fields.required_int(
        value,
        minimum=minimum,
        on_invalid=lambda: TypeError(
            f"{name} must be an integer of at least {minimum}"
        ),
    )


def _optional_int(value: object, name: str, *, minimum: int) -> int | None:
    return None if value is None else _required_int(value, name, minimum=minimum)


def _required_float(value: object, name: str) -> float:
    return _typed_fields.required_float(
        value,
        on_invalid=lambda: TypeError(f"{name} must be numeric"),
        on_not_finite=lambda: ValueError(f"{name} must be finite"),
    )


def _required_nonnegative_float(value: object, name: str) -> float:
    resolved = _required_float(value, name)
    if resolved < 0:
        raise ValueError(f"{name} must not be negative")
    return resolved


def _optional_float(value: object, name: str) -> float | None:
    return None if value is None else _required_float(value, name)
