"""Concrete job-manager responsibility owner."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import threading
    from collections import deque

from .._runtime_identity import process_identity_fields
from ..job_models import (
    DesiredJobState,
    JobAttempt,
    JobInitiator,
    JobOutcome,
    JobOutcomeStatus,
    JobResourceSnapshot,
    JobRuntimeSnapshot,
    JobSnapshot,
    JobSpec,
    JobState,
    JobTimestamps,
    ProcessResourceSnapshot,
)
from ..job_models import (
    active_work_identity as _active_work_identity,
)
from ..job_models import (
    capabilities_for_state as _capabilities_for_state,
)
from ..job_models import (
    job_spec_error as _job_spec_error,
)
from .state import (
    UNOWNED_RUNTIME,
    JobDispatchBinding,
    JobManagerState,
    ManagedJob,
    assign_runtime_owner,
)

logger = logging.getLogger("vaultspec_rag.jobs")


class JobManagerRecords(JobManagerState):
    #: Owned and initialized by the composed ``JobManager`` (``manager.py``).
    #: The shared ``JobManagerState`` protocol exposes every attribute it does
    #: not enumerate through one catch-all ``Any`` fallback; redeclaring the
    #: concrete types this owner actually reads keeps that fallback from
    #: leaking into every lock, map and count access below.
    _lock: threading.RLock
    _active: dict[str, ManagedJob]
    _terminal: deque[ManagedJob]
    _dispatchers: dict[str, JobDispatchBinding]
    _max_nonterminal: int
    _max_terminal_history: int

    def create(
        self,
        spec: JobSpec,
        initiator: JobInitiator,
        *,
        job_id: str | None = None,
    ) -> JobOutcome:
        """Admit one logical job, or deduplicate against equivalent active work."""
        spec_error = _job_spec_error(spec)
        if spec_error is not None:
            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.ERROR,
                code="invalid_job_spec",
                message=spec_error,
            )
        with self._lock:
            return self._create_locked(spec, initiator, job_id)

    def _create_locked(
        self,
        spec: JobSpec,
        initiator: JobInitiator,
        job_id: str | None,
    ) -> JobOutcome:
        """Create a validated request while the manager lock is held."""
        backup = self._capture_state_locked()
        equivalent = self._find_equivalent_active_locked(spec)
        if equivalent is not None:
            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.OK,
                code="active_job_exists",
                message="Equivalent active work is already registered.",
                job=equivalent,
            )

        if len(self._active) >= self._max_nonterminal:
            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.ERROR,
                code="job_capacity_exceeded",
                message=(
                    "The service has reached its configured nonterminal job "
                    f"capacity ({self._max_nonterminal})."
                ),
            )

        resolved_id = job_id or str(uuid.uuid4())
        if self._get_locked(resolved_id) is not None:
            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.ERROR,
                code="job_id_conflict",
                message=f"Job ID {resolved_id!r} is already registered.",
                job=self._get_locked(resolved_id),
            )

        now = time.time()
        state = JobState.QUEUED
        desired_state = DesiredJobState.RUNNING
        created = JobSnapshot(
            id=resolved_id,
            revision=1,
            spec=spec,
            state=state,
            desired_state=desired_state,
            capabilities=_capabilities_for_state(
                spec, state, desired_state=desired_state
            ),
            attempt=JobAttempt(number=1),
            timestamps=JobTimestamps(
                created_at=now,
                state_changed_at=now,
            ),
            progress=None,
            result=None,
            error_kind=None,
            initiator=initiator,
            runtime=self._process_runtime_snapshot(),
            resources=JobResourceSnapshot(started=None, finished=None),
        )
        self._active[resolved_id] = ManagedJob(
            snapshot=created,
            runtime=UNOWNED_RUNTIME,
        )

        persistence_error = self._persist_locked()
        if persistence_error is not None:
            if not persistence_error.published:
                self._restore_state_locked(backup)
            return self._persistence_error(
                "create",
                persistence_error,
                self._get_locked(resolved_id),
            )

        return JobOutcome(
            command="create",
            status=JobOutcomeStatus.ACCEPTED,
            code="job_created",
            message="The job was admitted.",
            job=created,
        )

    def get(self, job_id: str) -> JobSnapshot | None:
        """Return an immutable snapshot for one full, exact job ID."""
        with self._lock:
            return self._get_locked(job_id)

    def list_jobs(self) -> list[JobSnapshot]:
        """Return active work first, then separately bounded terminal history."""
        with self._lock:
            active = sorted(
                (self._snapshot_locked(job) for job in self._active.values()),
                key=lambda job: job.timestamps.created_at,
                reverse=True,
            )
            terminal = [self._snapshot_locked(job) for job in reversed(self._terminal)]
            return [*active, *terminal]

    def active(self) -> list[JobSnapshot]:
        """Return every nonterminal job without eviction or prefix matching."""
        with self._lock:
            return [self._snapshot_locked(job) for job in self._active.values()]

    def terminal(self) -> list[JobSnapshot]:
        """Return retained terminal history newest first."""
        with self._lock:
            return [self._snapshot_locked(job) for job in reversed(self._terminal)]

    def _get_locked(self, job_id: str) -> JobSnapshot | None:
        active = self._active.get(job_id)
        if active is not None:
            return self._snapshot_locked(active)
        terminal = self._get_terminal_locked(job_id)
        return self._snapshot_locked(terminal) if terminal is not None else None

    def _find_equivalent_active_locked(self, spec: JobSpec) -> JobSnapshot | None:
        identity = _active_work_identity(spec)
        for managed in self._active.values():
            if _active_work_identity(managed.snapshot.spec) == identity:
                return self._snapshot_locked(managed)
        return None

    def _archive_terminal_locked(self, managed: ManagedJob) -> None:
        """Move one terminal resource into bounded history.

        Transition methods call this while holding ``self._lock``. Keeping the
        retention operation here makes it impossible for terminal eviction to
        touch the nonterminal ownership map.
        """
        if not managed.snapshot.state.is_terminal:
            raise ValueError("only terminal jobs may enter terminal history")
        self._active.pop(managed.snapshot.id, None)
        assign_runtime_owner(managed, UNOWNED_RUNTIME)
        self._dispatchers.pop(managed.snapshot.id, None)
        self._terminal.append(managed)
        while len(self._terminal) > self._max_terminal_history:
            self._terminal.popleft()

    def _snapshot_locked(self, managed: ManagedJob) -> JobSnapshot:
        owner = managed.runtime
        task_active = owner.task is not None and not owner.task.done()
        runtime = replace(
            managed.snapshot.runtime,
            task_active=task_active,
            worker_active=owner.worker_active,
        )
        return replace(managed.snapshot, runtime=runtime)

    @staticmethod
    def _process_runtime_snapshot() -> JobRuntimeSnapshot:
        return JobRuntimeSnapshot(**process_identity_fields())

    @staticmethod
    def _process_resource_snapshot() -> ProcessResourceSnapshot:
        from ..memory_probe import current_cuda_mib, current_rss_mib

        cuda_allocated_mib, cuda_reserved_mib = current_cuda_mib()
        return ProcessResourceSnapshot(
            rss_mib=round(current_rss_mib(), 1),
            cuda_allocated_mib=round(cuda_allocated_mib, 1),
            cuda_reserved_mib=round(cuda_reserved_mib, 1),
        )
