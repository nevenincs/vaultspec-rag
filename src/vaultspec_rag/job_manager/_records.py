"""Concrete job-manager responsibility owner."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, replace

from .. import job_persistence as _job_persistence
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
    JobManagerState,
    JobRuntimeOwner,
    ManagedJob,
    ManagerStateBackup,
)

logger = logging.getLogger("vaultspec_rag.jobs")


@dataclass(frozen=True)
class _CreateRequest:
    """Validated values needed to create one job while holding the manager lock."""

    spec: JobSpec
    initiator: JobInitiator
    idempotency_key: str | None
    start_paused: bool
    job_id: str | None

    @property
    def signature(self) -> tuple[JobSpec, JobInitiator, bool]:
        """Return the immutable identity used by idempotency bindings."""
        return self.spec, self.initiator, self.start_paused


class JobManagerRecords(JobManagerState):
    def _replay_idempotent_locked(
        self,
        normalized_key: str | None,
        signature: tuple[JobSpec, JobInitiator, bool],
    ) -> JobOutcome | None:
        """Resolve an idempotency key against existing bindings.

        Returns the outcome to hand back when the key conflicts with a
        different request or replays an existing job, or ``None`` when
        admission should proceed - including when the bound job has since
        disappeared, whose stale binding is dropped here.
        """
        if normalized_key is None:
            return None
        binding = self._idempotency.get(normalized_key)
        if binding is None:
            return None
        self._idempotency.move_to_end(normalized_key)
        existing = self._get_locked(binding.job_id)
        if binding.signature != signature:
            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.ERROR,
                code="idempotency_key_conflict",
                message=(
                    "The idempotency key is already bound to a different job request."
                ),
                job=existing,
            )
        if existing is not None:
            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.OK,
                code="idempotency_replayed",
                message="The original job creation result was replayed.",
                job=existing,
            )
        self._idempotency.pop(normalized_key, None)
        return None

    def _adopt_equivalent_locked(
        self,
        equivalent: JobSnapshot,
        *,
        normalized_key: str | None,
        signature: tuple[JobSpec, JobInitiator, bool],
        backup: ManagerStateBackup,
    ) -> JobOutcome:
        """Bind an optional replay key to equivalent active work durably."""
        if normalized_key is not None:
            self._bind_idempotency_locked(
                normalized_key,
                signature,
                equivalent.id,
            )
            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                return self._persistence_error(
                    "create",
                    persistence_error,
                    equivalent,
                )
        return JobOutcome(
            command="create",
            status=JobOutcomeStatus.OK,
            code="active_job_exists",
            message="Equivalent active work is already registered.",
            job=equivalent,
        )

    def create(
        self,
        spec: JobSpec,
        initiator: JobInitiator,
        *,
        idempotency_key: str | None = None,
        start_paused: bool = False,
        job_id: str | None = None,
    ) -> JobOutcome:
        """Admit one logical job, or replay/deduplicate an existing resource."""
        spec_error = _job_spec_error(spec)
        if spec_error is not None:
            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.ERROR,
                code="invalid_job_spec",
                message=spec_error,
            )
        try:
            normalized_key = self._normalize_idempotency_key(idempotency_key)
        except ValueError as exc:
            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.ERROR,
                code="invalid_idempotency_key",
                message=str(exc),
            )
        request = _CreateRequest(
            spec=spec,
            initiator=initiator,
            idempotency_key=normalized_key,
            start_paused=start_paused,
            job_id=job_id,
        )

        with self._lock:
            return self._create_locked(request)

    def _create_locked(self, request: _CreateRequest) -> JobOutcome:
        """Create a validated request while the manager lock is held."""
        backup = self._capture_state_locked()
        replay = self._replay_idempotent_locked(
            request.idempotency_key, request.signature
        )
        if replay is not None:
            return replay

        equivalent = self._find_equivalent_active_locked(request.spec)
        if equivalent is not None:
            return self._adopt_equivalent_locked(
                equivalent,
                normalized_key=request.idempotency_key,
                signature=request.signature,
                backup=backup,
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

        resolved_id = request.job_id or str(uuid.uuid4())
        if self._get_locked(resolved_id) is not None:
            return JobOutcome(
                command="create",
                status=JobOutcomeStatus.ERROR,
                code="job_id_conflict",
                message=f"Job ID {resolved_id!r} is already registered.",
                job=self._get_locked(resolved_id),
            )

        now = time.time()
        state = JobState.PAUSED if request.start_paused else JobState.QUEUED
        desired_state = (
            DesiredJobState.PAUSED if request.start_paused else DesiredJobState.RUNNING
        )
        created = JobSnapshot(
            id=resolved_id,
            revision=1,
            spec=request.spec,
            state=state,
            desired_state=desired_state,
            capabilities=_capabilities_for_state(request.spec, state),
            attempt=JobAttempt(number=1),
            timestamps=JobTimestamps(
                created_at=now,
                state_changed_at=now,
                control_requested_at=now if request.start_paused else None,
                control_acknowledged_at=now if request.start_paused else None,
            ),
            progress=None,
            result=None,
            error_kind=None,
            initiator=request.initiator,
            runtime=self._process_runtime_snapshot(),
            resources=JobResourceSnapshot(started=None, finished=None),
        )
        self._active[resolved_id] = ManagedJob(
            snapshot=created,
            runtime=JobRuntimeOwner(task=None, control=None),
        )
        if request.idempotency_key is not None:
            self._bind_idempotency_locked(
                request.idempotency_key,
                request.signature,
                resolved_id,
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
        managed.runtime = JobRuntimeOwner(task=None, control=None)
        self._dispatchers.pop(managed.snapshot.id, None)
        self._terminal.append(managed)
        while len(self._terminal) > self._max_terminal_history:
            evicted = self._terminal.popleft()
            self._forget_idempotency_locked(evicted.snapshot.id)

    def _snapshot_locked(self, managed: ManagedJob) -> JobSnapshot:
        owner = managed.runtime
        task_active = owner.task is not None and not owner.task.done()
        runtime = replace(
            managed.snapshot.runtime,
            task_active=task_active,
            worker_active=owner.worker_active,
        )
        return replace(managed.snapshot, runtime=runtime)

    def _bind_idempotency_locked(
        self,
        key: str,
        signature: tuple[JobSpec, JobInitiator, bool],
        job_id: str,
    ) -> None:
        previous = self._idempotency.pop(key, None)
        if previous is not None:
            previous_keys = self._job_idempotency_keys.get(previous.job_id)
            if previous_keys is not None:
                previous_keys.discard(key)
                if not previous_keys:
                    self._job_idempotency_keys.pop(previous.job_id, None)
        self._idempotency[key] = _job_persistence.IdempotencyBinding(signature, job_id)
        self._job_idempotency_keys.setdefault(job_id, set()).add(key)
        while len(self._idempotency) > self._max_idempotency:
            evicted_key, evicted = self._idempotency.popitem(last=False)
            job_keys = self._job_idempotency_keys.get(evicted.job_id)
            if job_keys is not None:
                job_keys.discard(evicted_key)
                if not job_keys:
                    self._job_idempotency_keys.pop(evicted.job_id, None)

    def _forget_idempotency_locked(self, job_id: str) -> None:
        for key in self._job_idempotency_keys.pop(job_id, set()):
            binding = self._idempotency.get(key)
            if binding is not None and binding.job_id == job_id:
                self._idempotency.pop(key, None)

    @staticmethod
    def _normalize_idempotency_key(key: str | None) -> str | None:
        if key is None:
            return None
        normalized = key.strip()
        if not normalized:
            raise ValueError("idempotency_key must not be empty")
        if len(normalized) > _job_persistence.MAX_IDEMPOTENCY_KEY_LENGTH:
            raise ValueError(
                "idempotency_key must not exceed "
                f"{_job_persistence.MAX_IDEMPOTENCY_KEY_LENGTH} characters"
            )
        return normalized

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
