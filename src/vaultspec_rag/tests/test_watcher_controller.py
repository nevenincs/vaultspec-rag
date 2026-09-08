"""Tests for immutable watcher controller facts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from vaultspec_rag.watcher_controller import (
    ControllerEventKind,
    ControllerMeasurement,
    ControllerReason,
    ControllerScope,
    ControllerSnapshot,
    ControllerState,
    ControllerTransition,
    ScopeObservation,
)
from vaultspec_rag.watcher_retry import WatcherSource

pytestmark = pytest.mark.unit


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
