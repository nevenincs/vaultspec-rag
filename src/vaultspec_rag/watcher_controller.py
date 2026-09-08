"""Immutable facts used by adaptive watcher convergence control."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

from .watcher_retry import WatcherCircuitState, WatcherSource

__all__ = [
    "ControllerEventKind",
    "ControllerMeasurement",
    "ControllerReason",
    "ControllerScope",
    "ControllerSnapshot",
    "ControllerState",
    "ControllerTransition",
    "ScopeObservation",
]


class ControllerState(StrEnum):
    """Stable states of one root/source convergence controller."""

    IDLE = "idle"
    COLLECTING = "collecting"
    READY = "ready"
    ADMITTED = "admitted"
    RUNNING = "running"
    COOLING_DOWN = "cooling_down"
    BACKPRESSURED = "backpressured"
    RETRYING = "retrying"
    REFUSED = "refused"
    CONVERGED = "converged"


class ControllerReason(StrEnum):
    """Stable explanations for controller states and transitions."""

    CHANGE_OBSERVED = "change_observed"
    COALESCE_WINDOW_ACTIVE = "coalesce_window_active"
    QUIET_TREE_DEADLINE = "quiet_tree_deadline"
    BATCH_LIMIT_REACHED = "batch_limit_reached"
    MAXIMUM_FRESHNESS_DUE = "maximum_freshness_due"
    FAIR_TURN_SELECTED = "fair_turn_selected"
    JOB_ADMITTED = "job_admitted"
    JOB_STARTED = "job_started"
    JOB_COMPLETED = "job_completed"
    JOB_CANCELLED = "job_cancelled"
    JOB_SUPERSEDED = "job_superseded"
    POST_SUCCESS_COST_DELAY = "post_success_cost_delay"
    JOB_BACKLOG = "job_backlog"
    SEARCH_PRESSURE = "search_pressure"
    GPU_PRESSURE = "gpu_pressure"
    STORAGE_PRESSURE = "storage_pressure"
    SERVICE_QUIESCED = "service_quiesced"
    RETRY_DELAY_ACTIVE = "retry_delay_active"
    RETRY_ADMITTED = "retry_admitted"
    CIRCUIT_OPEN = "circuit_open"
    FULL_REINDEX_REQUIRED = "full_reindex_required"
    SCOPE_STATE_INVALID = "scope_state_invalid"
    SCOPE_CAPACITY_EXCEEDED = "scope_capacity_exceeded"
    CONTROLLER_SCHEMA_UNSUPPORTED = "controller_schema_unsupported"
    CONVERGED = "converged"


class ControllerEventKind(StrEnum):
    """Filesystem facts retained for each changed path."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class ScopeObservation:
    """Durable root-relative evidence for one changed path."""

    relative_path: str
    source: WatcherSource
    first_observed_at: float
    latest_observed_at: float
    event_kinds: frozenset[ControllerEventKind]
    generation: int

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative_path)
        if (
            not self.relative_path
            or path.is_absolute()
            or path.parts[0].endswith(":")
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            msg = "relative_path must be a non-empty relative path"
            raise ValueError(msg)
        if "\\" in self.relative_path:
            msg = "relative_path must use canonical forward slashes"
            raise ValueError(msg)
        if self.generation < 1:
            msg = "generation must be positive"
            raise ValueError(msg)
        if not self.event_kinds:
            msg = "event_kinds must not be empty"
            raise ValueError(msg)
        if self.first_observed_at < 0 or self.latest_observed_at < 0:
            msg = "observation times must be non-negative"
            raise ValueError(msg)
        if self.latest_observed_at < self.first_observed_at:
            msg = "latest observation cannot precede first observation"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ControllerScope:
    """Exact pending and attempt-fenced scope for one controller."""

    generation: int
    pending: tuple[ScopeObservation, ...] = field(default_factory=tuple)
    captured_generation: int | None = None
    captured: tuple[ScopeObservation, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.generation < 0:
            msg = "generation must be non-negative"
            raise ValueError(msg)
        if (self.captured_generation is None) != (not self.captured):
            msg = "captured observations require a captured generation"
            raise ValueError(msg)
        if (
            self.captured_generation is not None
            and self.captured_generation > self.generation
        ):
            msg = "captured generation cannot exceed the current generation"
            raise ValueError(msg)
        groups = (("pending", self.pending), ("captured", self.captured))
        for name, observations in groups:
            identities = {(item.source, item.relative_path) for item in observations}
            if len(identities) != len(observations):
                msg = f"{name} observations must have unique source/path identities"
                raise ValueError(msg)
            if any(item.generation > self.generation for item in observations):
                msg = "observation generation cannot exceed the current generation"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ControllerMeasurement:
    """One immutable service-owned measurement sample used for evaluation."""

    generation: int
    observed_at: float
    job_backlog: int | None = None
    index_in_flight: int | None = None
    index_waiters: int | None = None
    search_in_flight: int | None = None
    search_latency_seconds: float | None = None
    gpu_pressure: bool | None = None
    storage_available: bool | None = None
    service_quiesced: bool | None = None

    def __post_init__(self) -> None:
        if self.generation < 0 or self.observed_at < 0:
            msg = "measurement generation and time must be non-negative"
            raise ValueError(msg)
        counts = (self.job_backlog, self.index_in_flight, self.index_waiters)
        if any(value is not None and value < 0 for value in counts):
            msg = "measurement counts must be non-negative"
            raise ValueError(msg)
        if self.search_in_flight is not None and self.search_in_flight < 0:
            msg = "search_in_flight must be non-negative"
            raise ValueError(msg)
        if self.search_latency_seconds is not None and self.search_latency_seconds < 0:
            msg = "search latency must be non-negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ControllerTransition:
    """Auditable record of one controller state change."""

    source_state: ControllerState
    destination_state: ControllerState
    reason: ControllerReason
    wall_time: float
    deadline: float | None
    measurement_generation: int | None

    def __post_init__(self) -> None:
        if self.wall_time < 0 or (self.deadline is not None and self.deadline < 0):
            msg = "transition times must be non-negative"
            raise ValueError(msg)
        if self.measurement_generation is not None and self.measurement_generation < 0:
            msg = "measurement generation must be non-negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ControllerSnapshot:
    """Canonical observable truth for one root/source controller."""

    canonical_root: str
    source: WatcherSource
    state: ControllerState
    reason: ControllerReason
    scope: ControllerScope
    observed_at: float
    next_decision_at: float | None = None
    freshness_deadline: float | None = None
    measurement: ControllerMeasurement | None = None
    backpressure: tuple[ControllerReason, ...] = field(default_factory=tuple)
    last_transition: ControllerTransition | None = None
    job_id: str | None = None
    retry_at: float | None = None
    circuit_state: WatcherCircuitState = WatcherCircuitState.CLOSED
    remediation: str | None = None

    def __post_init__(self) -> None:
        if not self.canonical_root:
            msg = "canonical_root must not be empty"
            raise ValueError(msg)
        if self.observed_at < 0:
            msg = "observed_at must be non-negative"
            raise ValueError(msg)
        for name in ("next_decision_at", "freshness_deadline", "retry_at"):
            value = getattr(self, name)
            if value is not None and value < 0:
                msg = f"{name} must be non-negative"
                raise ValueError(msg)
        if any(reason not in _BACKPRESSURE_REASONS for reason in self.backpressure):
            msg = "backpressure may contain only backpressure reasons"
            raise ValueError(msg)
        observations = self.scope.pending + self.scope.captured
        if any(observation.source is not self.source for observation in observations):
            msg = "scope observations must belong to the controller source"
            raise ValueError(msg)


_BACKPRESSURE_REASONS: Final = frozenset(
    {
        ControllerReason.POST_SUCCESS_COST_DELAY,
        ControllerReason.JOB_BACKLOG,
        ControllerReason.SEARCH_PRESSURE,
        ControllerReason.GPU_PRESSURE,
        ControllerReason.STORAGE_PRESSURE,
        ControllerReason.SERVICE_QUIESCED,
    }
)
