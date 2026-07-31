"""Shared internal state records for the canonical job manager."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..job_models import JobSnapshot
from .models import JobAttemptContext, JobExecutionResult, QuiescedDispatchClaim

if TYPE_CHECKING:
    import asyncio
    import threading
    from collections import OrderedDict, deque
    from pathlib import Path
    from typing import Literal

    from .. import job_persistence as _job_persistence
    from ..job_control import (
        CancelRequested,
        PauseRequested,
        QuiesceRequested,
        RunControlToken,
        ShutdownRequested,
    )
    from ..job_models import (
        JobInitiator,
        JobOutcome,
        JobRuntimeSnapshot,
        JobSpec,
        ProcessResourceSnapshot,
    )
    from ..service_quiesce import ComputeTicket, ServiceQuiesceController
    from ._control import AttemptTerminal, RequestAttribution
    from ._persistence import PendingProgressFlush, SnapshotTransition

    type JobLifecycleState = Literal["new", "running", "stopping", "stopped"]
    """The manager's own lifecycle, named once for the contract and its owner.

    Written as a literal in both this contract and the concrete initialiser,
    the two copies drift the moment a state is added: the annotation that
    keeps the old set still type-checks against the value it already holds,
    so nothing reports the disagreement.
    """

MANAGED_STATE_FILENAME = "jobs-state.json"


if TYPE_CHECKING:

    class JobManagerState(Protocol):
        """Static contract for concrete owners operating on one coordinator.

        Responsibility for one coordinator is split across several owner
        classes that are only ever combined into a single concrete manager, so
        each one reads state and calls behaviour that a sibling owns. This
        contract is where that shared surface is declared exactly once: the
        attributes the concrete manager's initialiser establishes, and the
        methods an owner other than the caller implements. Declaring a member
        here is the only sanctioned way for one owner to reach another, and
        keeps every such reference checked rather than untyped.
        """

        _accepting_dispatch: bool
        _active: dict[str, ManagedJob]
        _dispatchers: dict[str, JobDispatchBinding]
        _flushed_generation: int
        _idempotency: OrderedDict[str, _job_persistence.IdempotencyBinding]
        _job_idempotency_keys: dict[str, set[str]]
        _last_flush_monotonic: float
        _lifecycle_state: JobLifecycleState
        _lock: threading.RLock
        _max_idempotency: int
        _max_nonterminal: int
        _max_terminal_history: int
        _next_dispatch_binding_nonce: int
        _next_quiesced_dispatch_generation: int
        _pending_quiesced_dispatches: dict[str, QuiescedDispatchClaim]
        _persistence_dirty: bool
        _quiesce_controller: ServiceQuiesceController
        _retiring_tasks: set[asyncio.Task[AttemptExit]]
        _service_loop: asyncio.AbstractEventLoop | None
        _startup_restore_incomplete: bool
        _state_generation: int
        _state_path: Path | None
        _terminal: deque[ManagedJob]
        _write_lock: threading.Lock

        def _archive_terminal_locked(self, managed: ManagedJob) -> None: ...
        def _begin_progress_flush_locked(self) -> PendingProgressFlush | None: ...
        def _bind_idempotency_locked(
            self,
            key: str,
            signature: tuple[JobSpec, JobInitiator, bool],
            job_id: str,
        ) -> None: ...
        def _capture_state_locked(self) -> ManagerStateBackup: ...
        def _clear_quiesced_dispatch_claim_locked(
            self, claim: QuiescedDispatchClaim | None
        ) -> None: ...
        def _complete_progress_flush(
            self, pending: PendingProgressFlush
        ) -> _job_persistence.PersistenceWriteError | None: ...
        def _consume_quiesced_dispatch_claim_locked(
            self,
            claim: QuiescedDispatchClaim,
            managed: ManagedJob,
            binding: JobDispatchBinding,
        ) -> bool: ...
        def _error(
            self,
            command: str,
            code: str,
            message: str,
            managed: ManagedJob | None = None,
            *,
            attribution: RequestAttribution | None = None,
        ) -> JobOutcome: ...
        def _find_equivalent_active_locked(
            self, spec: JobSpec
        ) -> JobSnapshot | None: ...
        def _forget_idempotency_locked(self, job_id: str) -> None: ...
        def _get_locked(self, job_id: str) -> JobSnapshot | None: ...
        def _get_terminal_locked(self, job_id: str) -> ManagedJob | None: ...
        def _live_runtime_ids_locked(self) -> tuple[str, ...]: ...
        def _note_progress_mutation_locked(self) -> None: ...
        def _persist_locked(self) -> _job_persistence.PersistenceWriteError | None: ...
        @staticmethod
        def _persistence_error(
            command: str,
            detail: str | _job_persistence.PersistenceWriteError,
            job: JobSnapshot | None = None,
            *,
            code: str = "job_persistence_failed",
        ) -> JobOutcome: ...
        @staticmethod
        def _process_resource_snapshot() -> ProcessResourceSnapshot: ...
        @staticmethod
        def _process_runtime_snapshot() -> JobRuntimeSnapshot: ...
        def _replace_snapshot_locked(
            self, managed: ManagedJob, transition: SnapshotTransition, /
        ) -> None: ...
        def _restore_state_locked(self, backup: ManagerStateBackup) -> None: ...
        def _snapshot_locked(self, managed: ManagedJob) -> JobSnapshot: ...
        def _supersede_quiesced_dispatch_claim_locked(self, job_id: str) -> None: ...
        def acknowledge_control(
            self,
            job_id: str,
            *,
            attempt: int,
            task: asyncio.Task[AttemptExit],
        ) -> JobOutcome: ...
        def dispatch(
            self,
            job_id: str,
            *,
            _quiesced_claim: QuiescedDispatchClaim | None = None,
        ) -> JobOutcome: ...
        async def dispatch_async(self, job_id: str) -> JobOutcome: ...
        def finish_attempt(
            self, job_id: str, terminal: AttemptTerminal
        ) -> JobOutcome: ...
        def flush_persistence(self) -> JobOutcome: ...
        def get(self, job_id: str) -> JobSnapshot | None: ...
        def release_execution_resources(
            self,
            job_id: str,
            *,
            task: asyncio.Task[AttemptExit],
            finished: ProcessResourceSnapshot,
        ) -> bool: ...
        def set_worker_active(
            self,
            job_id: str,
            *,
            task: asyncio.Task[AttemptExit],
            active: bool,
            worker_thread: threading.Thread | None = None,
        ) -> bool: ...
        def start_attempt(
            self,
            job_id: str,
            *,
            task: asyncio.Task[AttemptExit],
            control: RunControlToken,
        ) -> JobOutcome: ...

else:

    class JobManagerState:
        """Runtime base for concrete owners operating on one coordinator."""


class ConfiguredStatePath:
    __slots__ = ()


CONFIGURED_STATE_PATH = ConfiguredStatePath()

type JobAttemptRunner = Callable[[JobAttemptContext], JobExecutionResult]
type JobAttemptStartedCallback = Callable[[JobSnapshot], None]
type JobAttemptFinishedCallback = Callable[
    [JobSnapshot, float, JobExecutionResult | None, BaseException | None], None
]


@dataclass(frozen=True, slots=True)
class JobDispatchBinding:
    runner: JobAttemptRunner
    nonce: int
    on_started: JobAttemptStartedCallback | None = None
    on_finished: JobAttemptFinishedCallback | None = None
    loop: asyncio.AbstractEventLoop | None = None


@dataclass(frozen=True, slots=True)
class AttemptExit:
    result: JobExecutionResult | None
    control_signal: (
        PauseRequested | CancelRequested | QuiesceRequested | ShutdownRequested | None
    )
    error: BaseException | None
    duration_seconds: float
    release_persisted: bool


@dataclass(frozen=True, slots=True)
class JobRuntimeOwner:
    """Strong references to the live execution for one exact job ID."""

    task: asyncio.Task[AttemptExit] | None
    control: RunControlToken | None
    worker_active: bool = False
    worker_thread: threading.Thread | None = None
    compute_ticket: ComputeTicket | None = None


UNOWNED_RUNTIME = JobRuntimeOwner(task=None, control=None)
"""The runtime owner of a job with no live attempt attached."""


@dataclass(slots=True)
class ManagedJob:
    snapshot: JobSnapshot
    runtime: JobRuntimeOwner


def assign_runtime_owner(managed: ManagedJob, runtime: JobRuntimeOwner) -> None:
    """Install one job's runtime owner, releasing admission it stops carrying.

    Compute admission is tracked by ticket identity, so an owner replacement
    that simply drops the outgoing ticket leaves it counted against the drain
    with nothing left able to release it, and the service can never quiesce
    again. Every replacement routes here, which is the only place the manager
    releases a ticket: the outgoing ticket is released exactly when the
    incoming owner does not carry it forward. Releasing an already-released
    ticket is a tracked no-op, so a path that released early stays correct.
    """
    outgoing = managed.runtime.compute_ticket
    if outgoing is not None and outgoing is not runtime.compute_ticket:
        outgoing.release()
    managed.runtime = runtime


@dataclass(slots=True)
class ManagerStateBackup:
    active: dict[str, ManagedJob]
    terminal: deque[ManagedJob]
    snapshots: dict[str, JobSnapshot]
    runtimes: dict[str, JobRuntimeOwner]
    idempotency: OrderedDict[str, _job_persistence.IdempotencyBinding]
    job_idempotency_keys: dict[str, set[str]]
    dispatchers: dict[str, JobDispatchBinding]
    persistence_dirty: bool
