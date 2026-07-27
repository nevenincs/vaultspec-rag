"""Concrete job-manager responsibility owner."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from typing import Any, cast

from .. import job_persistence as _job_persistence
from ..job_models import (
    DesiredJobState,
    JobAttempt,
    JobOutcome,
    JobOutcomeStatus,
    JobSnapshot,
    JobState,
)
from ..job_models import (
    capabilities_for_state as _capabilities_for_state,
)
from .state import (
    JobManagerState,
    JobRuntimeOwner,
    ManagedJob,
    ManagerStateBackup,
)

logger = logging.getLogger("vaultspec_rag.jobs")


class JobManagerPersistence(JobManagerState):
    def _restore_snapshot_locked(self, snapshot: JobSnapshot, *, now: float) -> None:
        """Restore one validated snapshot with no live execution resources."""
        resumable = snapshot.state in {JobState.QUEUED, JobState.PAUSED}
        restored_runtime = (
            self._process_runtime_snapshot()
            if resumable
            else replace(
                snapshot.runtime,
                task_active=False,
                worker_active=False,
            )
        )
        managed = ManagedJob(
            snapshot=replace(
                snapshot,
                runtime=restored_runtime,
                resources=replace(
                    snapshot.resources,
                    index_capacity_held=False,
                    project_lease_held=False,
                    writer_lock_held=False,
                    pipeline_active=False,
                ),
            ),
            runtime=JobRuntimeOwner(task=None, control=None),
        )
        if resumable:
            self._active[snapshot.id] = managed
            return
        if snapshot.state.is_live_attempt:
            self._active[snapshot.id] = managed
            self._replace_snapshot_locked(
                managed,
                state=JobState.INTERRUPTED,
                desired_state=snapshot.desired_state,
                now=now,
                finished_at=now,
                result="The service stopped before the attempt acknowledged.",
                error_kind="interrupted",
            )
            self._archive_terminal_locked(managed)
            return
        self._terminal.append(managed)

    def _restore_jobs_locked(
        self,
        restored_jobs: tuple[JobSnapshot, ...],
        *,
        now: float,
    ) -> None:
        """Restore terminal history before active and interrupted resources."""
        restore_order = [
            *(job for job in restored_jobs if job.state.is_terminal),
            *(job for job in restored_jobs if not job.state.is_terminal),
        ]
        for snapshot in restore_order:
            self._restore_snapshot_locked(snapshot, now=now)

    def _trim_restored_history_locked(self) -> None:
        """Apply the configured terminal bound to restored history."""
        while len(self._terminal) > self._max_terminal_history:
            evicted = self._terminal.popleft()
            self._forget_idempotency_locked(evicted.snapshot.id)

    def _restore_bindings_locked(
        self,
        restored_bindings: tuple[
            tuple[str, _job_persistence.IdempotencyBinding],
            ...,
        ],
    ) -> None:
        """Restore only bindings whose target survived configured retention."""
        retained_ids = {
            *self._active,
            *(managed.snapshot.id for managed in self._terminal),
        }
        for key, binding in restored_bindings:
            if binding.job_id in retained_ids:
                self._bind_idempotency_locked(
                    key,
                    binding.signature,
                    binding.job_id,
                )

    def restore_persisted(self) -> JobOutcome:
        """Restore durable jobs without partially applying an invalid state file."""
        command = "restore_jobs"
        loaded = self._load_restore_state(command)
        if isinstance(loaded, JobOutcome):
            return loaded
        persisted = loaded

        restored_jobs = persisted.jobs
        restored_bindings = persisted.bindings
        active_count = sum(
            job.state in {JobState.QUEUED, JobState.PAUSED} for job in restored_jobs
        )
        if active_count > self._max_nonterminal:
            return self._persistence_error(
                command,
                (
                    f"persisted nonterminal count {active_count} exceeds configured "
                    f"capacity {self._max_nonterminal}"
                ),
                code="job_state_capacity_exceeded",
            )
        with self._lock:
            if self._active or self._terminal:
                return self._error(
                    command,
                    "manager_not_empty",
                    "Persisted state can only be restored into an empty manager.",
                )
            backup = self._capture_state_locked()
            now = time.time()
            self._restore_jobs_locked(restored_jobs, now=now)
            self._trim_restored_history_locked()
            self._restore_bindings_locked(restored_bindings)

            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                return self._persistence_error(command, persistence_error)
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="job_state_restored",
                message=(
                    f"Restored {len(self._active)} nonterminal jobs and "
                    f"{len(self._terminal)} interrupted records."
                ),
            )

    def _load_restore_state(
        self,
        command: str,
    ) -> _job_persistence.PersistedManagerState | JobOutcome:
        """Load the all-or-nothing restoration input or its stable outcome."""
        path = self._state_path
        if path is None:
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="persistence_disabled",
                message="This job manager has no persistence path.",
            )
        try:
            return _job_persistence.load_persisted_state(path)
        except FileNotFoundError:
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="no_persisted_jobs",
                message="No persisted job state exists.",
            )
        except (OSError, UnicodeError, KeyError, TypeError, ValueError) as exc:
            return self._persistence_error(command, str(exc), code="job_state_invalid")

    def _replace_snapshot_locked(
        self,
        managed: ManagedJob,
        transition: _SnapshotTransition | None = None,
        **legacy: object,
    ) -> None:
        if transition is None:
            transition = _SnapshotTransition(**cast("dict[str, Any]", legacy))
        elif legacy:
            raise TypeError("use either _SnapshotTransition or named inputs")
        previous = managed.snapshot
        timestamps = previous.timestamps
        managed.snapshot = replace(
            previous,
            revision=previous.revision + 1,
            state=transition.state,
            desired_state=transition.desired_state,
            capabilities=_capabilities_for_state(previous.spec, transition.state),
            attempt=transition.attempt or previous.attempt,
            timestamps=replace(
                timestamps,
                state_changed_at=transition.now,
                started_at=(
                    timestamps.started_at
                    if transition.started_at is ...
                    else cast("float | None", transition.started_at)
                ),
                # Admission is a per-attempt fact: any transition that
                # rewrites the start clock (a fresh start, a requeued
                # resume) discards the previous attempt's admission stamp.
                admission_acquired_at=(
                    timestamps.admission_acquired_at
                    if transition.started_at is ...
                    else None
                ),
                control_requested_at=(
                    timestamps.control_requested_at
                    if transition.control_requested_at is ...
                    else cast("float | None", transition.control_requested_at)
                ),
                control_acknowledged_at=(
                    timestamps.control_acknowledged_at
                    if transition.control_acknowledged_at is ...
                    else cast("float | None", transition.control_acknowledged_at)
                ),
                finished_at=(
                    timestamps.finished_at
                    if transition.finished_at is ...
                    else cast("float | None", transition.finished_at)
                ),
            ),
            result=(
                previous.result
                if transition.result is ...
                else cast("str | None", transition.result)
            ),
            error_kind=(
                previous.error_kind
                if transition.error_kind is ...
                else cast("str | None", transition.error_kind)
            ),
            reuse=(
                previous.reuse
                if transition.reuse is ...
                else cast("dict[str, object] | None", transition.reuse)
            ),
        )

    def _get_terminal_locked(self, job_id: str) -> ManagedJob | None:
        for managed in reversed(self._terminal):
            if managed.snapshot.id == job_id:
                return managed
        return None

    def _capture_state_locked(self) -> ManagerStateBackup:
        managed_jobs = [*self._active.values(), *self._terminal]
        return ManagerStateBackup(
            active=dict(self._active),
            terminal=deque(self._terminal),
            snapshots={job.snapshot.id: job.snapshot for job in managed_jobs},
            runtimes={job.snapshot.id: job.runtime for job in managed_jobs},
            idempotency=OrderedDict(self._idempotency),
            job_idempotency_keys={
                job_id: set(keys) for job_id, keys in self._job_idempotency_keys.items()
            },
            dispatchers=dict(self._dispatchers),
            persistence_dirty=self._persistence_dirty,
        )

    def _restore_state_locked(self, backup: ManagerStateBackup) -> None:
        for managed in [*backup.active.values(), *backup.terminal]:
            job_id = managed.snapshot.id
            snapshot = backup.snapshots.get(job_id)
            runtime = backup.runtimes.get(job_id)
            if snapshot is not None:
                managed.snapshot = snapshot
            if runtime is not None:
                managed.runtime = runtime
        self._active = backup.active
        self._terminal = backup.terminal
        self._idempotency = OrderedDict(backup.idempotency)
        self._job_idempotency_keys = backup.job_idempotency_keys
        self._dispatchers = backup.dispatchers
        self._persistence_dirty = backup.persistence_dirty

    def _persist_locked(
        self,
    ) -> _job_persistence.PersistenceWriteError | None:
        path = self._state_path
        if path is None:
            self._persistence_dirty = False
            return None
        retained_ids = {
            *self._active,
            *(managed.snapshot.id for managed in self._terminal),
        }
        persisted = _job_persistence.PersistedManagerState(
            jobs=tuple(
                self._snapshot_locked(managed)
                for managed in [*self._active.values(), *self._terminal]
            ),
            bindings=tuple(
                (key, binding)
                for key, binding in self._idempotency.items()
                if binding.job_id in retained_ids
            ),
        )
        try:
            _job_persistence.save_persisted_state(path, persisted)
        except _job_persistence.PersistenceWriteError as exc:
            self._persistence_dirty = True
            logger.error("job state persistence failed: %s", exc)
            return exc
        self._persistence_dirty = False
        return None

    @staticmethod
    def _persistence_error(
        command: str,
        detail: str | _job_persistence.PersistenceWriteError,
        job: JobSnapshot | None = None,
        *,
        code: str = "job_persistence_failed",
    ) -> JobOutcome:
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.ERROR,
            code=code,
            message=f"Job state could not be persisted: {detail}",
            job=job,
        )


@dataclass(frozen=True, slots=True)
class _SnapshotTransition:
    state: JobState
    desired_state: DesiredJobState
    now: float
    attempt: JobAttempt | None = None
    started_at: float | object | None = ...
    control_requested_at: float | object | None = ...
    control_acknowledged_at: float | object | None = ...
    finished_at: float | object | None = ...
    result: str | object | None = ...
    error_kind: str | object | None = ...
    reuse: dict[str, object] | object | None = ...
