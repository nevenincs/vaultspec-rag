"""Immutable facts used by adaptive watcher convergence control."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from .watcher_retry import (
    WatcherCircuitState,
    WatcherPathEvent,
    WatcherSource,
    is_valid_watcher_relative_path,
)

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "ControllerLimits",
    "ControllerMeasurement",
    "ControllerReason",
    "ControllerScope",
    "ControllerSnapshot",
    "ControllerState",
    "ControllerTransition",
    "ScopeObservation",
    "WatcherController",
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


@dataclass(frozen=True, slots=True)
class ControllerLimits:
    """Validated runtime limits consumed by the pure controller."""

    coalesce_min_seconds: float = 2.0
    coalesce_max_seconds: float = 30.0
    cooling_max_seconds: float = 120.0
    maximum_freshness_seconds: float = 300.0
    measurement_reevaluation_seconds: float = 5.0
    batch_path_limit: int = 10_000

    def __post_init__(self) -> None:
        values = (
            self.coalesce_min_seconds,
            self.coalesce_max_seconds,
            self.cooling_max_seconds,
            self.maximum_freshness_seconds,
            self.measurement_reevaluation_seconds,
        )
        if any(value < 0 for value in values):
            msg = "controller limits must be non-negative"
            raise ValueError(msg)
        if self.coalesce_min_seconds > self.coalesce_max_seconds:
            msg = "minimum coalescing cannot exceed maximum coalescing"
            raise ValueError(msg)
        if self.maximum_freshness_seconds < self.coalesce_max_seconds:
            msg = "maximum freshness cannot be shorter than coalescing"
            raise ValueError(msg)
        if self.measurement_reevaluation_seconds <= 0:
            msg = "measurement reevaluation must be positive"
            raise ValueError(msg)
        if self.batch_path_limit < 1:
            msg = "batch path limit must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ScopeObservation:
    """Durable root-relative evidence for one changed path."""

    relative_path: str
    source: WatcherSource
    first_observed_at: float
    latest_observed_at: float
    event_kinds: frozenset[WatcherPathEvent]
    generation: int

    def __post_init__(self) -> None:
        if not is_valid_watcher_relative_path(self.relative_path):
            msg = "relative_path must be a non-empty relative path"
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
    monotonic_at: float | None = None
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
        if self.monotonic_at is not None and self.monotonic_at < 0:
            msg = "monotonic_at must be non-negative"
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

_REFUSAL_REASONS: Final = frozenset(
    {
        ControllerReason.FULL_REINDEX_REQUIRED,
        ControllerReason.SCOPE_STATE_INVALID,
        ControllerReason.SCOPE_CAPACITY_EXCEEDED,
        ControllerReason.CONTROLLER_SCHEMA_UNSUPPORTED,
    }
)


class WatcherController:
    """Deterministic state machine for one canonical root/source."""

    __slots__ = (
        "_limits",
        "_monotonic",
        "_prior_success_duration",
        "_snapshot",
        "_wall_clock",
    )

    def __init__(
        self,
        snapshot: ControllerSnapshot,
        *,
        monotonic: Callable[[], float],
        wall_clock: Callable[[], float],
        limits: ControllerLimits | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._limits = limits or ControllerLimits()
        self._prior_success_duration = 0.0

    @property
    def snapshot(self) -> ControllerSnapshot:
        """Return the current immutable controller truth."""
        return self._snapshot

    def observe(self, scope: ControllerScope) -> ControllerSnapshot:
        """Accept already-merged exact scope and begin adaptive collection."""
        now = self._monotonic()
        freshness = self._freshness_deadline(scope)
        coalesce = min(now + self._coalesce_delay(scope), freshness)
        return self._transition(
            ControllerState.COLLECTING,
            ControllerReason.CHANGE_OBSERVED,
            scope=scope,
            next_decision_at=coalesce,
            freshness_deadline=freshness,
            job_id=None,
            remediation=None,
        )

    def evaluate(
        self,
        measurement: ControllerMeasurement,
        *,
        retry_at: float | None = None,
        circuit_state: WatcherCircuitState = WatcherCircuitState.CLOSED,
    ) -> ControllerSnapshot:
        """Evaluate collection, cooling, retry, and service-pressure evidence."""
        now = self._monotonic()
        snapshot = self._snapshot
        if snapshot.state is ControllerState.REFUSED:
            return self._transition(
                ControllerState.REFUSED,
                snapshot.reason,
                measurement=measurement,
                next_decision_at=None,
            )
        if not snapshot.scope.pending and not snapshot.scope.captured:
            return self._transition(
                ControllerState.CONVERGED,
                ControllerReason.CONVERGED,
                measurement=measurement,
                next_decision_at=None,
                freshness_deadline=None,
            )
        retry_decision = self._evaluate_retry(
            measurement,
            now=now,
            retry_at=retry_at,
            circuit_state=circuit_state,
        )
        if retry_decision is not None:
            return retry_decision
        return self._evaluate_pending(measurement, now=now, retry_at=retry_at)

    def _evaluate_retry(
        self,
        measurement: ControllerMeasurement,
        *,
        now: float,
        retry_at: float | None,
        circuit_state: WatcherCircuitState,
    ) -> ControllerSnapshot | None:
        if circuit_state is WatcherCircuitState.OPEN:
            return self._transition(
                ControllerState.RETRYING,
                ControllerReason.CIRCUIT_OPEN,
                measurement=measurement,
                circuit_state=circuit_state,
                retry_at=retry_at,
                next_decision_at=retry_at,
            )
        if retry_at is not None and retry_at > now:
            return self._transition(
                ControllerState.RETRYING,
                ControllerReason.RETRY_DELAY_ACTIVE,
                measurement=measurement,
                circuit_state=circuit_state,
                retry_at=retry_at,
                next_decision_at=retry_at,
            )
        return None

    def _evaluate_pending(
        self,
        measurement: ControllerMeasurement,
        *,
        now: float,
        retry_at: float | None,
    ) -> ControllerSnapshot:
        snapshot = self._snapshot
        safety_reason = self._safety_pressure(measurement)
        if safety_reason is not None:
            return self._backpressure(safety_reason, measurement, cap_freshness=False)
        freshness = snapshot.freshness_deadline
        if freshness is not None and now >= freshness:
            return self._transition(
                ControllerState.READY,
                ControllerReason.MAXIMUM_FRESHNESS_DUE,
                measurement=measurement,
                next_decision_at=now,
                circuit_state=WatcherCircuitState.CLOSED,
                retry_at=retry_at,
            )
        deadline = snapshot.next_decision_at
        if (
            snapshot.state is ControllerState.COOLING_DOWN
            and deadline is not None
            and now < deadline
        ):
            return self._transition(
                snapshot.state,
                ControllerReason.POST_SUCCESS_COST_DELAY,
                measurement=measurement,
                next_decision_at=deadline,
            )
        capacity_decision = self._evaluate_capacity_pressure(measurement, now=now)
        if capacity_decision is not None:
            return capacity_decision
        if deadline is not None and now < deadline:
            return self._transition(
                snapshot.state,
                ControllerReason.COALESCE_WINDOW_ACTIVE,
                measurement=measurement,
                next_decision_at=deadline,
            )
        reason = (
            ControllerReason.RETRY_ADMITTED
            if retry_at is not None
            else ControllerReason.QUIET_TREE_DEADLINE
        )
        return self._transition(
            ControllerState.READY,
            reason,
            measurement=measurement,
            next_decision_at=now,
            retry_at=retry_at,
        )

    def _evaluate_capacity_pressure(
        self,
        measurement: ControllerMeasurement,
        *,
        now: float,
    ) -> ControllerSnapshot | None:
        snapshot = self._snapshot
        if len(snapshot.scope.pending) >= self._limits.batch_path_limit:
            return self._transition(
                ControllerState.READY,
                ControllerReason.BATCH_LIMIT_REACHED,
                measurement=measurement,
                next_decision_at=now,
            )
        pressure = self._ordinary_pressure(measurement)
        if pressure is not None:
            return self._backpressure(pressure, measurement, cap_freshness=True)
        return None

    def admit(self, job_id: str) -> ControllerSnapshot:
        """Bind the canonical incremental job admitted for this controller."""
        if self._snapshot.state is not ControllerState.READY or not job_id:
            msg = "admission requires a ready controller and job identity"
            raise ValueError(msg)
        return self._transition(
            ControllerState.ADMITTED,
            ControllerReason.JOB_ADMITTED,
            job_id=job_id,
            next_decision_at=None,
        )

    def advance(self, reason: ControllerReason) -> ControllerSnapshot:
        """Apply one non-admission execution transition."""
        transitions = {
            ControllerReason.FAIR_TURN_SELECTED: (
                ControllerState.READY,
                ControllerState.READY,
                "only a ready controller may be selected",
            ),
            ControllerReason.JOB_STARTED: (
                ControllerState.ADMITTED,
                ControllerState.RUNNING,
                "only an admitted controller may start",
            ),
        }
        try:
            required, destination, error = transitions[reason]
        except KeyError as exc:
            raise ValueError("reason is not an execution transition") from exc
        if self._snapshot.state is not required:
            raise ValueError(error)
        return self._transition(destination, reason)

    def complete(
        self,
        scope: ControllerScope,
        *,
        run_duration: float,
        publication_duration: float,
    ) -> ControllerSnapshot:
        """Settle a successful attempt and cool remaining exact work."""
        if self._snapshot.state is not ControllerState.RUNNING:
            msg = "only a running controller may complete"
            raise ValueError(msg)
        if run_duration < 0 or publication_duration < 0:
            msg = "successful durations must be non-negative"
            raise ValueError(msg)
        self._prior_success_duration = run_duration + publication_duration
        if not scope.pending and not scope.captured:
            return self._transition(
                ControllerState.CONVERGED,
                ControllerReason.CONVERGED,
                scope=scope,
                job_id=None,
                next_decision_at=None,
                freshness_deadline=None,
            )
        now = self._monotonic()
        freshness = self._freshness_deadline(scope)
        cooling = min(
            now
            + min(
                run_duration + publication_duration, self._limits.cooling_max_seconds
            ),
            freshness,
        )
        return self._transition(
            ControllerState.COOLING_DOWN,
            ControllerReason.JOB_COMPLETED,
            scope=scope,
            job_id=None,
            next_decision_at=cooling,
            freshness_deadline=freshness,
        )

    def release(
        self,
        scope: ControllerScope,
        *,
        superseded: bool = False,
    ) -> ControllerSnapshot:
        """Restore exact captured work after cancellation or supersession."""
        if self._snapshot.state not in {
            ControllerState.ADMITTED,
            ControllerState.RUNNING,
        }:
            msg = "only admitted or running work may be released"
            raise ValueError(msg)
        reason = (
            ControllerReason.JOB_SUPERSEDED
            if superseded
            else ControllerReason.JOB_CANCELLED
        )
        now = self._monotonic()
        freshness = self._freshness_deadline(scope)
        return self._transition(
            ControllerState.COLLECTING,
            reason,
            scope=scope,
            job_id=None,
            next_decision_at=min(now + self._coalesce_delay(scope), freshness),
            freshness_deadline=freshness,
        )

    def refuse(
        self,
        reason: ControllerReason,
        *,
        remediation: str,
    ) -> ControllerSnapshot:
        """Stop unsafe automatic admission with a typed actionable reason."""
        if reason not in _REFUSAL_REASONS or not remediation:
            msg = "refusal requires a refusal reason and remediation"
            raise ValueError(msg)
        return self._transition(
            ControllerState.REFUSED,
            reason,
            next_decision_at=None,
            remediation=remediation,
            job_id=None,
        )

    def _coalesce_delay(self, scope: ControllerScope) -> float:
        observations = scope.pending
        if not observations:
            return self._limits.coalesce_min_seconds
        oldest = min(item.first_observed_at for item in observations)
        latest = max(item.latest_observed_at for item in observations)
        span = max(latest - oldest, 1.0)
        event_count = sum(len(item.event_kinds) for item in observations)
        arrival_rate = event_count / span
        repeated_ratio = max(0.0, 1.0 - len(observations) / event_count)
        cardinality_factor = min(len(observations) / 1000.0, 1.0)
        pressure = min(arrival_rate / 10.0, 1.0)
        duration_factor = min(
            self._prior_success_duration / max(self._limits.cooling_max_seconds, 1.0),
            1.0,
        )
        weight = min(
            1.0,
            pressure * 0.4
            + repeated_ratio * 0.2
            + cardinality_factor * 0.2
            + duration_factor * 0.2,
        )
        width = self._limits.coalesce_max_seconds - self._limits.coalesce_min_seconds
        return self._limits.coalesce_min_seconds + width * weight

    def _freshness_deadline(self, scope: ControllerScope) -> float:
        observations = scope.pending + scope.captured
        if not observations:
            return self._monotonic()
        oldest = min(item.first_observed_at for item in observations)
        return oldest + self._limits.maximum_freshness_seconds

    @staticmethod
    def _safety_pressure(
        measurement: ControllerMeasurement,
    ) -> ControllerReason | None:
        if measurement.service_quiesced is True:
            return ControllerReason.SERVICE_QUIESCED
        if measurement.storage_available is False:
            return ControllerReason.STORAGE_PRESSURE
        return None

    @staticmethod
    def _ordinary_pressure(
        measurement: ControllerMeasurement,
    ) -> ControllerReason | None:
        if measurement.job_backlog:
            return ControllerReason.JOB_BACKLOG
        if measurement.search_in_flight:
            return ControllerReason.SEARCH_PRESSURE
        if measurement.gpu_pressure is True:
            return ControllerReason.GPU_PRESSURE
        return None

    def _backpressure(
        self,
        reason: ControllerReason,
        measurement: ControllerMeasurement,
        *,
        cap_freshness: bool,
    ) -> ControllerSnapshot:
        deadline = self._monotonic() + self._limits.measurement_reevaluation_seconds
        freshness = self._snapshot.freshness_deadline
        if cap_freshness and freshness is not None:
            deadline = min(deadline, freshness)
        return self._transition(
            ControllerState.BACKPRESSURED,
            reason,
            measurement=measurement,
            next_decision_at=deadline,
            backpressure=(reason,),
        )

    def _transition(
        self,
        state: ControllerState,
        reason: ControllerReason,
        **changes: object,
    ) -> ControllerSnapshot:
        if state is not ControllerState.BACKPRESSURED:
            changes.setdefault("backpressure", ())
        deadline = changes.get("next_decision_at", self._snapshot.next_decision_at)
        measurement = changes.get("measurement", self._snapshot.measurement)
        generation = (
            measurement.generation
            if isinstance(measurement, ControllerMeasurement)
            else None
        )
        process_now = self._monotonic()
        wall_now = self._wall_clock()
        transition = ControllerTransition(
            source_state=self._snapshot.state,
            destination_state=state,
            reason=reason,
            wall_time=wall_now,
            deadline=deadline if isinstance(deadline, float) else None,
            measurement_generation=generation,
        )
        self._snapshot = replace(
            self._snapshot,
            state=state,
            reason=reason,
            observed_at=wall_now,
            monotonic_at=process_now,
            last_transition=transition,
            **changes,
        )
        return self._snapshot
