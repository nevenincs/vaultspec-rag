"""Canonical service evidence consumed by automatic watcher admission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ..job_models import JobMode, JobOperation
from ..service_quiesce import QuiesceState
from ..watcher_controller import ControllerMeasurement

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ..job_models import JobSnapshot
    from ..service_quiesce import QuiesceSnapshot
    from ..watcher_retry import WatcherRetryState

__all__ = [
    "ActiveIndexGeneration",
    "WatcherMeasurementFacts",
    "WatcherServiceMeasurement",
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


def compose_watcher_measurement(
    facts: WatcherMeasurementFacts,
) -> WatcherServiceMeasurement:
    """Compose already-owned service facts without performing new probes."""
    generation = facts.generation
    observed_at = facts.observed_at
    jobs = facts.jobs
    limiter_snapshot = facts.limiter_snapshot
    search_snapshot = facts.search_snapshot
    pressure_tier = facts.pressure_tier
    storage_available = facts.storage_available
    quiesce = facts.quiesce
    retry_state = facts.retry_state
    requested_cost = facts.requested_cost
    effective_cost = facts.effective_cost
    active = tuple(
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
    unavailable: set[str] = set()

    index_borrowed, index_waiters = _limiter_values(limiter_snapshot, "index")
    if index_borrowed is None or index_waiters is None:
        unavailable.add("index_limiter")
    search_borrowed, _ = _limiter_values(limiter_snapshot, "search")
    if search_borrowed is None:
        unavailable.add("search_limiter")

    search_in_flight, search_latency = _search_values(search_snapshot)
    if search_in_flight is None:
        unavailable.add("search_activity")
    if search_latency is None:
        unavailable.add("search_latency")
    if pressure_tier is None:
        unavailable.add("machine_pressure")
    if storage_available is None:
        unavailable.add("storage")
    if quiesce is None:
        unavailable.add("quiesce")
    if retry_state is None:
        unavailable.add("retry")
    if effective_cost is None:
        unavailable.add("effective_cost")

    controller = ControllerMeasurement(
        generation=generation,
        observed_at=observed_at,
        job_backlog=len(active) + (index_waiters or 0),
        index_in_flight=index_borrowed,
        index_waiters=index_waiters,
        search_in_flight=(
            search_in_flight if search_in_flight is not None else search_borrowed
        ),
        search_latency_seconds=search_latency,
        gpu_pressure=(
            None if pressure_tier is None else pressure_tier in _PRESSURED_TIERS
        ),
        storage_available=storage_available,
        service_quiesced=(
            None if quiesce is None else quiesce.state is not QuiesceState.RUNNING
        ),
    )
    return WatcherServiceMeasurement(
        generation=generation,
        observed_at=observed_at,
        controller=controller,
        active_index_generations=active,
        machine_pressure_tier=pressure_tier,
        requested_cost=requested_cost,
        effective_cost=effective_cost,
        failure_kind=(
            None
            if retry_state is None or retry_state.last_error_kind is None
            else retry_state.last_error_kind.value
        ),
        circuit_state=(
            None if retry_state is None else retry_state.circuit_state.value
        ),
        unavailable=frozenset(unavailable),
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
    counts = snapshot.get("counts")
    active = counts.get("active") if isinstance(counts, dict) else None
    recent = snapshot.get("recent")
    latencies = (
        [
            float(value)
            for row in recent
            if isinstance(row, dict)
            and isinstance((value := row.get("total_seconds")), int | float)
            and not isinstance(value, bool)
            and value >= 0
        ]
        if isinstance(recent, list)
        else []
    )
    return _non_negative_int(active), (max(latencies) if latencies else None)


def _non_negative_int(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )
