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

    task: asyncio.Task[Any] | None
    control: RunControlToken | None
    worker_active: bool = False
    worker_thread: threading.Thread | None = None
    compute_ticket: ComputeTicket | None = None


@dataclass(slots=True)
class ManagedJob:
    snapshot: JobSnapshot
    runtime: JobRuntimeOwner


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
