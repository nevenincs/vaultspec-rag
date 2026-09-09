"""Canonical service evidence consumed by automatic watcher admission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from ..job_models import JobMode, JobOperation
from ..service_quiesce import QuiesceState
from ..watcher_controller import ControllerMeasurement

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ..job_models import JobSnapshot
    from ..service import ServiceRegistry
    from ..service_quiesce import QuiesceSnapshot
    from ..watcher_retry import WatcherRetryState, WatcherSource

__all__ = [
    "ActiveIndexGeneration",
    "WatcherMeasurementFacts",
    "WatcherServiceMeasurement",
    "capture_watcher_measurement",
    "compose_watcher_measurement",
]

_PRESSURED_TIERS: Final = frozenset({"elevated", "critical"})


@dataclass(frozen=True, slots=True)
class ActiveIndexGeneration:
    """Identity of one canonical nonterminal index attempt."""

    job_id: str
    revision: int
    attempt: int
    source: str
    state: str


@dataclass(frozen=True, slots=True)
class WatcherServiceMeasurement:
    """Immutable service snapshot used for one controller evaluation."""

    generation: int
    observed_at: float
    controller: ControllerMeasurement
    active_index_generations: tuple[ActiveIndexGeneration, ...]
    machine_pressure_tier: str | None
    requested_cost: JobMode | None
    effective_cost: JobMode | None
    failure_kind: str | None
    circuit_state: str | None
    unavailable: frozenset[str]

    def __post_init__(self) -> None:
        if self.generation < 0 or self.observed_at < 0:
            raise ValueError("measurement generation and time must be non-negative")


@dataclass(frozen=True, slots=True)
class WatcherMeasurementFacts:
    """Canonical inputs captured by the service at one instant."""

    generation: int
    observed_at: float
    jobs: Sequence[JobSnapshot]
    limiter_snapshot: Mapping[str, Mapping[str, object]] | None
    search_snapshot: Mapping[str, object] | None
    pressure_tier: str | None
    storage_available: bool | None
    quiesce: QuiesceSnapshot | None
    retry_state: WatcherRetryState | None
    requested_cost: JobMode | None = JobMode.INCREMENTAL
    effective_cost: JobMode | None = None


def capture_watcher_measurement(
    registry: ServiceRegistry,
    *,
    key: tuple[str, WatcherSource],
    retry_state: WatcherRetryState,
    generation: int,
    observed_at: float,
) -> WatcherServiceMeasurement:
    """Capture the service-owned facts used by production admission."""
    import time

    from .. import _job_evidence
    from ..concurrency import limiter_stats
    from ._state import search_activity_ledger

    root, source = key
    jobs = tuple(registry.create_job_manager().list_jobs())
    pressure = _job_evidence.machine_pressure(
        now=time.time(),
        forwards=[],
        project_root=root,
        source=source.value,
    )
    alive = _mapping_path(pressure, "evidence", "backend", "alive")
    storage_available = alive if isinstance(alive, bool) else None
    tier = pressure.get("tier")
    return compose_watcher_measurement(
        WatcherMeasurementFacts(
            generation=generation,
            observed_at=observed_at,
            jobs=jobs,
            limiter_snapshot=limiter_stats(),
            search_snapshot=search_activity_ledger().snapshot(include_query=False),
            pressure_tier=tier if isinstance(tier, str) else None,
            storage_available=storage_available,
            quiesce=registry.quiesce_snapshot(),
            retry_state=retry_state,
            requested_cost=JobMode.INCREMENTAL,
            effective_cost=JobMode.INCREMENTAL,
        )
    )


@dataclass(frozen=True, slots=True)
class _PoolReadings:
    """The concurrency and search readings one measurement is derived from.

    Every field is independently optional because each is read from a snapshot
    the service may not have been able to take. They are held together because
    both the controller projection and the unavailability report need the same
    readings, and taking them twice could disagree.
    """

    index_in_flight: int | None
    index_waiters: int | None
    search_borrowed: int | None
    search_in_flight: int | None
    search_latency: float | None


def _pool_readings(facts: WatcherMeasurementFacts) -> _PoolReadings:
    """Read the limiter and search snapshots the facts arrived with."""
    index_in_flight, index_waiters = _limiter_values(facts.limiter_snapshot, "index")
    search_borrowed, _ = _limiter_values(facts.limiter_snapshot, "search")
    search_in_flight, search_latency = _search_values(facts.search_snapshot)
    return _PoolReadings(
        index_in_flight=index_in_flight,
        index_waiters=index_waiters,
        search_borrowed=search_borrowed,
        search_in_flight=search_in_flight,
        search_latency=search_latency,
    )


def _unavailable_readings(
    facts: WatcherMeasurementFacts, readings: _PoolReadings
) -> frozenset[str]:
    """Name every reading this measurement could not take.

    A controller that could not tell an absent reading from a zero would admit
    work against evidence it never had, so absence is reported as its own fact
    rather than folded into the value.
    """
    absent = {
        "index_limiter": readings.index_in_flight is None
        or readings.index_waiters is None,
        "search_limiter": readings.search_borrowed is None,
        "search_activity": readings.search_in_flight is None,
        "search_latency": readings.search_latency is None,
        "machine_pressure": facts.pressure_tier is None,
        "storage": facts.storage_available is None,
        "quiesce": facts.quiesce is None,
        "retry": facts.retry_state is None,
        "effective_cost": facts.effective_cost is None,
    }
    return frozenset(name for name, missing in absent.items() if missing)


def _active_index_generations(
    jobs: Sequence[JobSnapshot],
) -> tuple[ActiveIndexGeneration, ...]:
    """Identify every index attempt still in flight when the facts were taken."""
    return tuple(
        ActiveIndexGeneration(
            job_id=job.id,
            revision=job.revision,
            attempt=job.attempt.number,
            source=job.spec.source.value,
            state=job.state.value,
        )
        for job in jobs
        if job.spec.operation is JobOperation.INDEX and not job.state.is_terminal
    )


def _controller_measurement(
    facts: WatcherMeasurementFacts,
    readings: _PoolReadings,
    active_count: int,
) -> ControllerMeasurement:
    """Project the service readings onto the controller's measurement shape.

    In-flight search falls back to the limiter's borrowed count when the
    activity ledger could not answer, because the two count the same work and
    the limiter is the reading that survives a ledger reset.
    """
    quiesce = facts.quiesce
    tier = facts.pressure_tier
    return ControllerMeasurement(
        generation=facts.generation,
        observed_at=facts.observed_at,
        job_backlog=active_count + (readings.index_waiters or 0),
        index_in_flight=readings.index_in_flight,
        index_waiters=readings.index_waiters,
        search_in_flight=(
            readings.search_borrowed
            if readings.search_in_flight is None
            else readings.search_in_flight
        ),
        search_latency_seconds=readings.search_latency,
        gpu_pressure=None if tier is None else tier in _PRESSURED_TIERS,
        storage_available=facts.storage_available,
        service_quiesced=(
            None if quiesce is None else quiesce.state is not QuiesceState.RUNNING
        ),
    )


def _failure_kind(retry_state: WatcherRetryState | None) -> str | None:
    """Name the kind of the last recorded failure, if one was recorded."""
    if retry_state is None or retry_state.last_error_kind is None:
        return None
    return retry_state.last_error_kind.value


def compose_watcher_measurement(
    facts: WatcherMeasurementFacts,
) -> WatcherServiceMeasurement:
    """Compose already-owned service facts without performing new probes."""
    readings = _pool_readings(facts)
    active = _active_index_generations(facts.jobs)
    retry_state = facts.retry_state
    return WatcherServiceMeasurement(
        generation=facts.generation,
        observed_at=facts.observed_at,
        controller=_controller_measurement(facts, readings, len(active)),
        active_index_generations=active,
        machine_pressure_tier=facts.pressure_tier,
        requested_cost=facts.requested_cost,
        effective_cost=facts.effective_cost,
        failure_kind=_failure_kind(retry_state),
        circuit_state=(
            None if retry_state is None else retry_state.circuit_state.value
        ),
        unavailable=_unavailable_readings(facts, readings),
    )


def _limiter_values(
    snapshot: Mapping[str, Mapping[str, object]] | None, pool: str
) -> tuple[int | None, int | None]:
    if snapshot is None or pool not in snapshot:
        return None, None
    facts = snapshot[pool]
    borrowed = facts.get("borrowed_tokens")
    waiters = facts.get("waiting")
    return _non_negative_int(borrowed), _non_negative_int(waiters)


def _search_values(
    snapshot: Mapping[str, object] | None,
) -> tuple[int | None, float | None]:
    if snapshot is None:
        return None, None
    active = _mapping_path(snapshot.get("counts"), "active")
    latencies = _recent_latencies(snapshot.get("recent"))
    return _non_negative_int(active), (max(latencies) if latencies else None)


def _recent_latencies(recent: object) -> list[float]:
    """Collect every well-formed duration from the recent-search window.

    Rows are skipped rather than defaulted: a search whose duration was not
    recorded is not a search that took no time, and averaging one in would
    understate exactly the latency the controller backs off on.
    """
    if not isinstance(recent, list):
        return []
    latencies: list[float] = []
    for row in cast("list[object]", recent):
        value = _mapping_path(row, "total_seconds")
        if not isinstance(value, int | float) or isinstance(value, bool):
            continue
        if value >= 0:
            latencies.append(float(value))
    return latencies


def _mapping_path(source: object, *keys: str) -> object:
    """Read a nested key path from a value that may not be a mapping at all.

    These snapshots cross a JSON-shaped boundary, so nothing about their
    interior is guaranteed and every step has to re-establish that it is still
    looking at a mapping before reading the next key.
    """
    for key in keys:
        if not isinstance(source, dict):
            return None
        source = cast("dict[str, object]", source).get(key)
    return source


def _non_negative_int(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )
