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
    evidence = pressure.get("evidence")
    evidence_map = (
        cast("dict[str, object]", evidence) if isinstance(evidence, dict) else None
    )
    backend = evidence_map.get("backend") if evidence_map is not None else None
    backend_map = (
        cast("dict[str, object]", backend) if isinstance(backend, dict) else None
    )
    storage_available = backend_map.get("alive") if backend_map is not None else None
    if not isinstance(storage_available, bool):
        storage_available = None
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
    index_borrowed, index_waiters = _limiter_values(limiter_snapshot, "index")
    search_borrowed, _ = _limiter_values(limiter_snapshot, "search")
    search_in_flight, search_latency = _search_values(search_snapshot)
    unavailable = {
        name
        for name, missing in {
            "index_limiter": index_borrowed is None or index_waiters is None,
            "search_limiter": search_borrowed is None,
            "search_activity": search_in_flight is None,
            "search_latency": search_latency is None,
            "machine_pressure": pressure_tier is None,
            "storage": storage_available is None,
            "quiesce": quiesce is None,
            "retry": retry_state is None,
            "effective_cost": effective_cost is None,
        }.items()
        if missing
    }

    controller = _compose_controller_measurement(
        facts,
        active_count=len(active),
        index_values=(index_borrowed, index_waiters),
        search_values=(search_borrowed, search_in_flight, search_latency),
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


def _compose_controller_measurement(
    facts: WatcherMeasurementFacts,
    *,
    active_count: int,
    index_values: tuple[int | None, int | None],
    search_values: tuple[int | None, int | None, float | None],
) -> ControllerMeasurement:
    """Build the controller-facing projection from narrowed service facts."""
    generation = facts.generation
    observed_at = facts.observed_at
    pressure_tier = facts.pressure_tier
    storage_available = facts.storage_available
    quiesce = facts.quiesce
    index_in_flight, index_waiters = index_values
    search_borrowed, search_in_flight, search_latency_seconds = search_values
    return ControllerMeasurement(
        generation=generation,
        observed_at=observed_at,
        job_backlog=active_count + (index_waiters or 0),
        index_in_flight=index_in_flight,
        index_waiters=index_waiters,
        search_in_flight=(
            search_in_flight if search_in_flight is not None else search_borrowed
        ),
        search_latency_seconds=search_latency_seconds,
        gpu_pressure=(
            None if pressure_tier is None else pressure_tier in _PRESSURED_TIERS
        ),
        storage_available=storage_available,
        service_quiesced=(
            None if quiesce is None else quiesce.state is not QuiesceState.RUNNING
        ),
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
    counts_map = cast("dict[str, object]", counts) if isinstance(counts, dict) else None
    active = counts_map.get("active") if counts_map is not None else None
    recent = snapshot.get("recent")
    latencies: list[float] = []
    if isinstance(recent, list):
        recent_values = cast("list[object]", recent)
        for raw_row in recent_values:
            if not isinstance(raw_row, dict):
                continue
            row = cast("dict[str, object]", raw_row)
            value = row.get("total_seconds")
            if (
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and value >= 0
            ):
                latencies.append(float(value))
    return _non_negative_int(active), (max(latencies) if latencies else None)


def _non_negative_int(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )
