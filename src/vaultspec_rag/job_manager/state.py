"""Shared internal state records for the canonical job manager."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ..job_models import JobSnapshot
from .models import JobAttemptContext, JobExecutionResult, QuiescedDispatchClaim

if TYPE_CHECKING:
    import asyncio
    import threading
    from collections import OrderedDict, deque

    from .. import job_persistence as _job_persistence
    from ..job_control import (
        CancelRequested,
        PauseRequested,
        QuiesceRequested,
        RunControlToken,
        ShutdownRequested,
    )
    from ..service_quiesce import ComputeTicket

MANAGED_STATE_FILENAME = "jobs-state.json"


if TYPE_CHECKING:

    class JobManagerState(Protocol):
        """Static contract for concrete owners operating on one coordinator."""

        _next_dispatch_binding_nonce: int
        _next_quiesced_dispatch_generation: int
        _pending_quiesced_dispatches: dict[str, QuiescedDispatchClaim]
        _service_loop: asyncio.AbstractEventLoop | None

        def __getattr__(self, name: str) -> Any: ...

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
