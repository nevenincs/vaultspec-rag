"""Tests for immutable watcher controller facts."""

from __future__ import annotations

import os
import random
from dataclasses import FrozenInstanceError, dataclass
from typing import TYPE_CHECKING

import pytest

from vaultspec_rag.watcher_controller import (
    ControllerEventKind,
    ControllerLimits,
    ControllerMeasurement,
    ControllerReason,
    ControllerScope,
    ControllerSnapshot,
    ControllerState,
    ControllerTransition,
    ScopeObservation,
    WatcherController,
)
from vaultspec_rag.watcher_retry import (
    WatcherCircuitState,
    WatcherPathEvent,
    WatcherPathObservation,
    WatcherRetryPolicy,
    WatcherSource,
    _WatcherRetryOptions,
)

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from pathlib import Path


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@dataclass(frozen=True, slots=True)
class _MeasurementEvidence:
    job_backlog: int | None = None
    search_in_flight: int | None = None
    gpu_pressure: bool | None = None
    storage_available: bool | None = None
    service_quiesced: bool | None = None


def _controller(
    clock: _Clock,
    *,
    scope: ControllerScope | None = None,
    limits: ControllerLimits | None = None,
) -> WatcherController:
    return WatcherController(
        ControllerSnapshot(
            canonical_root="C:/work/project",
            source=WatcherSource.CODE,
            state=ControllerState.IDLE,
            reason=ControllerReason.CONVERGED,
            scope=scope or ControllerScope(generation=0),
            observed_at=clock.now,
        ),
        monotonic=clock,
        wall_clock=clock,
        limits=limits,
    )


def _measurement(
    clock: _Clock,
    evidence: _MeasurementEvidence | None = None,
) -> ControllerMeasurement:
    evidence = evidence or _MeasurementEvidence()
    return ControllerMeasurement(
        generation=1,
        observed_at=clock.now,
        job_backlog=evidence.job_backlog,
        search_in_flight=evidence.search_in_flight,
        gpu_pressure=evidence.gpu_pressure,
        storage_available=evidence.storage_available,
        service_quiesced=evidence.service_quiesced,
    )


def _observation(path: str = "src/example.py") -> ScopeObservation:
    return ScopeObservation(
        relative_path=path,
        source=WatcherSource.CODE,
        first_observed_at=10.0,
        latest_observed_at=12.0,
        event_kinds=frozenset(
            {ControllerEventKind.ADDED, ControllerEventKind.MODIFIED}
        ),
        generation=3,
    )


def _retry_policy(path: Path, root: Path, *, now: float) -> WatcherRetryPolicy:
    return WatcherRetryPolicy(
        path,
        _WatcherRetryOptions(
            canonical_root=os.path.normcase(str(root.resolve())),
            source=WatcherSource.CODE,
            base_seconds=1.0,
            max_seconds=8.0,
            jitter_fraction=0.0,
            failure_threshold=3,
            now=now,
        ),
    )


def _path_observation(path: str, *, observed_at: float) -> WatcherPathObservation:
    return WatcherPathObservation(
        relative_path=path,
        source=WatcherSource.CODE,
        first_observed_at=observed_at,
        latest_observed_at=observed_at,
        event_kinds=frozenset({WatcherPathEvent.MODIFIED}),
        generation=1,
    )


def test_controller_vocabulary_matches_the_public_contract() -> None:
    assert {state.value for state in ControllerState} == {
        "idle",
        "collecting",
        "ready",
        "admitted",
        "running",
        "cooling_down",
        "backpressured",
        "retrying",
        "refused",
        "converged",
    }
    assert {reason.value for reason in ControllerReason} == {
        "change_observed",
        "coalesce_window_active",
        "quiet_tree_deadline",
        "batch_limit_reached",
        "maximum_freshness_due",
        "fair_turn_selected",
        "job_admitted",
        "job_started",
        "job_completed",
        "job_cancelled",
        "job_superseded",
        "post_success_cost_delay",
        "job_backlog",
        "search_pressure",
        "gpu_pressure",
        "storage_pressure",
        "service_quiesced",
        "retry_delay_active",
        "retry_admitted",
        "circuit_open",
        "full_reindex_required",
        "scope_state_invalid",
        "scope_capacity_exceeded",
        "controller_schema_unsupported",
        "converged",
    }


def test_scope_retains_exact_source_qualified_event_evidence() -> None:
    observation = _observation()
    scope = ControllerScope(generation=3, pending=(observation,))

    assert scope.pending == (observation,)
    assert observation.source is WatcherSource.CODE
    assert observation.event_kinds == {
        ControllerEventKind.ADDED,
        ControllerEventKind.MODIFIED,
    }
    field_name = "generation"
    with pytest.raises(FrozenInstanceError):
        setattr(observation, field_name, 4)


@pytest.mark.parametrize(
    "path", ["", "/absolute.py", "C:/absolute.py", "../escape.py", "src\\foreign.py"]
)
def test_scope_rejects_noncanonical_relative_paths(path: str) -> None:
    with pytest.raises(ValueError, match="relative_path"):
        _observation(path)


def test_scope_keeps_later_pending_event_for_a_captured_path() -> None:
    observation = _observation()
    scope = ControllerScope(
        generation=3,
        pending=(observation,),
        captured_generation=3,
        captured=(observation,),
    )

    assert scope.pending == scope.captured


def test_snapshot_composes_scope_measurement_transition_and_deadlines() -> None:
    measurement = ControllerMeasurement(
        generation=9,
        observed_at=20.0,
        job_backlog=2,
        index_in_flight=1,
        search_in_flight=4,
        gpu_pressure=True,
        storage_available=True,
        service_quiesced=False,
    )
    transition = ControllerTransition(
        source_state=ControllerState.READY,
        destination_state=ControllerState.BACKPRESSURED,
        reason=ControllerReason.GPU_PRESSURE,
        wall_time=20.0,
        deadline=30.0,
        measurement_generation=measurement.generation,
    )
    snapshot = ControllerSnapshot(
        canonical_root="C:/work/project",
        source=WatcherSource.CODE,
        state=ControllerState.BACKPRESSURED,
        reason=ControllerReason.GPU_PRESSURE,
        scope=ControllerScope(generation=3, pending=(_observation(),)),
        observed_at=20.0,
        next_decision_at=25.0,
        freshness_deadline=30.0,
        measurement=measurement,
        backpressure=(ControllerReason.GPU_PRESSURE,),
        last_transition=transition,
    )

    assert snapshot.measurement is measurement
    assert snapshot.last_transition is transition
    assert snapshot.scope.pending[0].relative_path == "src/example.py"


def test_snapshot_rejects_non_backpressure_reason_in_backpressure_evidence() -> None:
    with pytest.raises(ValueError, match="backpressure reasons"):
        ControllerSnapshot(
            canonical_root="C:/work/project",
            source=WatcherSource.VAULT,
            state=ControllerState.COLLECTING,
            reason=ControllerReason.CHANGE_OBSERVED,
            scope=ControllerScope(generation=1),
            observed_at=2.0,
            backpressure=(ControllerReason.CHANGE_OBSERVED,),
        )


def test_measurement_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="counts"):
        ControllerMeasurement(generation=1, observed_at=2.0, job_backlog=-1)


def test_observation_uses_adaptive_coalescing_bounded_by_freshness() -> None:
    clock = _Clock(12.0)
    controller = _controller(
        clock,
        limits=ControllerLimits(
            coalesce_min_seconds=2.0,
            coalesce_max_seconds=10.0,
            maximum_freshness_seconds=15.0,
        ),
    )
    scope = ControllerScope(generation=3, pending=(_observation(),))

    snapshot = controller.observe(scope)

    assert snapshot.state is ControllerState.COLLECTING
    assert snapshot.reason is ControllerReason.CHANGE_OBSERVED
    assert snapshot.freshness_deadline == 25.0
    assert snapshot.next_decision_at is not None
    assert snapshot.freshness_deadline is not None
    assert 14.0 <= snapshot.next_decision_at <= snapshot.freshness_deadline
    collecting = controller.evaluate(_measurement(clock))
    assert collecting.reason is ControllerReason.COALESCE_WINDOW_ACTIVE


def test_batch_limit_and_quiet_deadline_make_work_ready() -> None:
    clock = _Clock(12.0)
    controller = _controller(clock, limits=ControllerLimits(batch_path_limit=1))
    controller.observe(ControllerScope(generation=3, pending=(_observation(),)))

    assert (
        controller.evaluate(_measurement(clock)).reason
        is ControllerReason.BATCH_LIMIT_REACHED
    )

    clock = _Clock(12.0)
    controller = _controller(clock)
    observed = controller.observe(
        ControllerScope(generation=3, pending=(_observation(),))
    )
    assert observed.next_decision_at is not None
    clock.now = observed.next_decision_at
    ready = controller.evaluate(_measurement(clock))
    assert ready.state is ControllerState.READY
    assert ready.reason is ControllerReason.QUIET_TREE_DEADLINE


@pytest.mark.parametrize(
    ("job_backlog", "search_in_flight", "gpu_pressure", "reason"),
    [
        (1, None, None, ControllerReason.JOB_BACKLOG),
        (None, 1, None, ControllerReason.SEARCH_PRESSURE),
        (None, None, True, ControllerReason.GPU_PRESSURE),
    ],
)
def test_ordinary_pressure_defers_only_to_freshness(
    job_backlog: int | None,
    search_in_flight: int | None,
    gpu_pressure: bool | None,
    reason: ControllerReason,
) -> None:
    clock = _Clock(12.0)
    controller = _controller(clock)
    observed = controller.observe(
        ControllerScope(generation=3, pending=(_observation(),))
    )

    measurement = _measurement(
        clock,
        _MeasurementEvidence(
            job_backlog=job_backlog,
            search_in_flight=search_in_flight,
            gpu_pressure=gpu_pressure,
        ),
    )
    pressured = controller.evaluate(measurement)
    assert pressured.state is ControllerState.BACKPRESSURED
    assert pressured.reason is reason
    assert pressured.next_decision_at is not None
    assert observed.freshness_deadline is not None
    assert pressured.next_decision_at <= observed.freshness_deadline

    clock.now = observed.freshness_deadline
    due = controller.evaluate(measurement)
    assert due.reason is ControllerReason.MAXIMUM_FRESHNESS_DUE


@pytest.mark.parametrize(
    ("service_quiesced", "storage_available", "reason"),
    [
        (True, None, ControllerReason.SERVICE_QUIESCED),
        (None, False, ControllerReason.STORAGE_PRESSURE),
    ],
)
def test_safety_pressure_may_exceed_freshness(
    service_quiesced: bool | None,
    storage_available: bool | None,
    reason: ControllerReason,
) -> None:
    clock = _Clock(400.0)
    controller = _controller(clock)
    controller.observe(ControllerScope(generation=3, pending=(_observation(),)))

    snapshot = controller.evaluate(
        _measurement(
            clock,
            _MeasurementEvidence(
                service_quiesced=service_quiesced,
                storage_available=storage_available,
            ),
        )
    )

    assert snapshot.reason is reason
    assert snapshot.next_decision_at == 405.0
    assert snapshot.freshness_deadline == 310.0


def test_retry_delay_circuit_and_retry_admission_are_deterministic() -> None:
    clock = _Clock(12.0)
    controller = _controller(clock)
    controller.observe(ControllerScope(generation=3, pending=(_observation(),)))

    delayed = controller.evaluate(_measurement(clock), retry_at=20.0)
    assert delayed.reason is ControllerReason.RETRY_DELAY_ACTIVE
    opened = controller.evaluate(
        _measurement(clock),
        retry_at=20.0,
        circuit_state=WatcherCircuitState.OPEN,
    )
    assert opened.reason is ControllerReason.CIRCUIT_OPEN
    clock.now = 20.0
    admitted = controller.evaluate(_measurement(clock), retry_at=20.0)
    assert admitted.reason is ControllerReason.RETRY_ADMITTED


def test_fair_selection_admission_start_and_successful_convergence() -> None:
    clock = _Clock(12.0)
    controller = _controller(clock, limits=ControllerLimits(batch_path_limit=1))
    controller.observe(ControllerScope(generation=3, pending=(_observation(),)))
    controller.evaluate(_measurement(clock))

    assert controller.select().reason is ControllerReason.FAIR_TURN_SELECTED
    assert controller.admit("job-1").state is ControllerState.ADMITTED
    assert controller.start().state is ControllerState.RUNNING
    completed = controller.complete(
        ControllerScope(generation=3),
        run_duration=10.0,
        publication_duration=2.0,
    )
    assert completed.state is ControllerState.CONVERGED
    assert completed.reason is ControllerReason.CONVERGED
    assert completed.job_id is None


def test_success_with_later_work_cools_and_freshness_caps_delay() -> None:
    clock = _Clock(12.0)
    controller = _controller(clock, limits=ControllerLimits(batch_path_limit=1))
    scope = ControllerScope(generation=3, pending=(_observation(),))
    controller.observe(scope)
    controller.evaluate(_measurement(clock))
    controller.admit("job-1")
    controller.start()

    cooling = controller.complete(scope, run_duration=500.0, publication_duration=1.0)
    assert cooling.state is ControllerState.COOLING_DOWN
    assert cooling.reason is ControllerReason.JOB_COMPLETED
    assert cooling.next_decision_at == 132.0
    clock.now = 20.0
    assert (
        controller.evaluate(_measurement(clock)).reason
        is ControllerReason.POST_SUCCESS_COST_DELAY
    )


@pytest.mark.parametrize("superseded", [False, True])
def test_release_restores_exact_scope(superseded: bool) -> None:
    clock = _Clock(12.0)
    controller = _controller(clock, limits=ControllerLimits(batch_path_limit=1))
    scope = ControllerScope(generation=3, pending=(_observation(),))
    controller.observe(scope)
    controller.evaluate(_measurement(clock))
    controller.admit("job-1")
    controller.start()

    released = controller.release(scope, superseded=superseded)

    expected = (
        ControllerReason.JOB_SUPERSEDED
        if superseded
        else ControllerReason.JOB_CANCELLED
    )
    assert released.reason is expected
    assert released.scope == scope
    assert released.job_id is None


@pytest.mark.parametrize("reason", list(ControllerReason)[-5:-1])
def test_typed_refusal_stops_admission_with_remediation(
    reason: ControllerReason,
) -> None:
    clock = _Clock(12.0)
    controller = _controller(clock)

    refused = controller.refuse(reason, remediation="run an explicit full index")

    assert refused.state is ControllerState.REFUSED
    assert refused.next_decision_at is None
    assert refused.remediation == "run an explicit full index"


def test_generated_pressure_sequences_never_defer_past_freshness() -> None:
    for seed in range(64):
        generator = random.Random(seed)
        clock = _Clock(12.0)
        limits = ControllerLimits(
            coalesce_min_seconds=2.0,
            coalesce_max_seconds=30.0,
            maximum_freshness_seconds=60.0,
            measurement_reevaluation_seconds=5.0,
        )
        controller = _controller(clock, limits=limits)
        observed = controller.observe(
            ControllerScope(generation=3, pending=(_observation(),))
        )
        deadline = observed.freshness_deadline
        assert deadline is not None
        assert deadline == 70.0

        while clock.now < deadline:
            evidence = generator.choice(
                (
                    _MeasurementEvidence(job_backlog=1),
                    _MeasurementEvidence(search_in_flight=1),
                    _MeasurementEvidence(gpu_pressure=True),
                )
            )
            decision = controller.evaluate(_measurement(clock, evidence))
            assert decision.state is ControllerState.BACKPRESSURED
            next_decision = decision.next_decision_at
            assert next_decision is not None
            assert clock.now < next_decision <= deadline
            clock.now = next_decision

        due = controller.evaluate(
            _measurement(clock, _MeasurementEvidence(job_backlog=1))
        )
        assert due.state is ControllerState.READY
        assert due.reason is ControllerReason.MAXIMUM_FRESHNESS_DUE


def test_every_eligible_controller_can_claim_selection_independently() -> None:
    controllers: list[WatcherController] = []
    for index, source in enumerate(WatcherSource):
        clock = _Clock(20.0)
        observation = ScopeObservation(
            relative_path=f"src/{source.value}.txt",
            source=source,
            first_observed_at=10.0,
            latest_observed_at=10.0,
            event_kinds=frozenset({ControllerEventKind.MODIFIED}),
            generation=1,
        )
        controller = WatcherController(
            ControllerSnapshot(
                canonical_root=f"C:/work/project-{index}",
                source=source,
                state=ControllerState.IDLE,
                reason=ControllerReason.CONVERGED,
                scope=ControllerScope(generation=0),
                observed_at=clock.now,
            ),
            monotonic=clock,
            wall_clock=clock,
            limits=ControllerLimits(batch_path_limit=1),
        )
        controller.observe(ControllerScope(generation=1, pending=(observation,)))
        controller.evaluate(_measurement(clock))
        controllers.append(controller)

    selected = [controller.select() for controller in controllers]

    assert [item.source for item in selected] == list(WatcherSource)
    assert all(item.reason is ControllerReason.FAIR_TURN_SELECTED for item in selected)
    assert len({item.canonical_root for item in selected}) == len(selected)


def test_generated_durable_sequences_preserve_exact_scope_once(tmp_path: Path) -> None:
    state_path = tmp_path / "code.json"
    policy = _retry_policy(state_path, tmp_path, now=0.0)
    expected: set[str] = set()
    generator = random.Random(470)

    for step in range(80):
        observed_paths = {
            f"src/item-{generator.randrange(12)}.py"
            for _ in range(generator.randrange(1, 5))
        }
        expected.update(observed_paths)
        state = policy.mark_scope_pending(
            tuple(
                _path_observation(path, observed_at=float(step))
                for path in sorted(observed_paths)
            ),
            now=float(step),
        )
        assert {item.relative_path for item in state.pending_paths} == expected
        assert not state.unscoped_required

        decision = policy.admit_reserved(
            policy.reserve_admission(), now=float(step), job_id=f"job-{step}"
        )
        assert decision.admitted
        captured = {item.relative_path for item in policy.state.captured_paths}
        assert captured == expected
        assert not policy.state.pending_paths

        if generator.randrange(3) == 0:
            later = f"src/later-{step}.py"
            expected.add(later)
            policy.mark_scope_pending(
                (_path_observation(later, observed_at=float(step) + 0.25),),
                now=float(step) + 0.25,
            )

        generation = decision.attempt_generation
        assert generation is not None
        if generator.randrange(2) == 0:
            settled = policy.record_interrupted(generation, now=float(step) + 0.5)
            assert {item.relative_path for item in settled.pending_paths} == expected
        else:
            expected.difference_update(captured)
            settled = policy.record_success(generation, now=float(step) + 0.5)
            assert {item.relative_path for item in settled.pending_paths} == expected
        assert not settled.captured_paths
        assert not settled.unscoped_required


def test_restart_preserves_fenced_exact_scope_without_unscoped_escalation(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "code.json"
    policy = _retry_policy(state_path, tmp_path, now=0.0)
    paths = {"src/a.py", "src/b.py"}
    policy.mark_scope_pending(
        tuple(_path_observation(path, observed_at=1.0) for path in sorted(paths)),
        now=1.0,
    )
    decision = policy.admit_reserved(
        policy.reserve_admission(), now=2.0, job_id="job-restart"
    )
    assert decision.admitted

    restarted = _retry_policy(state_path, tmp_path, now=3.0)

    assert restarted.state.attempt_generation == decision.attempt_generation
    assert restarted.state.attempt_job_id == "job-restart"
    assert {item.relative_path for item in restarted.state.captured_paths} == paths
    assert not restarted.state.pending_paths
    assert not restarted.state.unscoped_required
    assert restarted.state.scope_refusal is None
