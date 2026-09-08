"""Tests for canonical watcher-controller service facts."""

from __future__ import annotations

import time

import pytest

from ..api import controller_snapshot_envelope
from ..watcher_controller import (
    ControllerMeasurement,
    ControllerReason,
    ControllerScope,
    ControllerSnapshot,
    ControllerState,
    ControllerTransition,
    ScopeObservation,
)
from ..watcher_retry import WatcherCircuitState, WatcherPathEvent, WatcherSource

pytestmark = pytest.mark.unit


def test_controller_projection_contains_complete_actionable_truth() -> None:
    observation = ScopeObservation(
        relative_path="src/example.py",
        source=WatcherSource.CODE,
        first_observed_at=100.0,
        latest_observed_at=120.0,
        event_kinds=frozenset({WatcherPathEvent.MODIFIED}),
        generation=3,
    )
    measurement = ControllerMeasurement(
        generation=8,
        observed_at=125.0,
        job_backlog=2,
        index_in_flight=1,
        index_waiters=1,
        search_in_flight=None,
        search_latency_seconds=None,
        gpu_pressure=True,
        storage_available=True,
        service_quiesced=False,
    )
    transition = ControllerTransition(
        source_state=ControllerState.READY,
        destination_state=ControllerState.BACKPRESSURED,
        reason=ControllerReason.GPU_PRESSURE,
        wall_time=125.0,
        deadline=130.0,
        measurement_generation=8,
    )
    snapshot = ControllerSnapshot(
        canonical_root="C:/work/project",
        source=WatcherSource.CODE,
        state=ControllerState.BACKPRESSURED,
        reason=ControllerReason.GPU_PRESSURE,
        scope=ControllerScope(
            generation=3,
            pending=(observation,),
            captured_generation=2,
            captured=(observation,),
        ),
        observed_at=125.0,
        next_decision_at=130.0,
        freshness_deadline=400.0,
        measurement=measurement,
        backpressure=(ControllerReason.GPU_PRESSURE,),
        last_transition=transition,
        job_id="job-1",
        retry_at=140.0,
        circuit_state=WatcherCircuitState.HALF_OPEN,
    )

    projected = controller_snapshot_envelope(
        snapshot, observed_at=150.0, monotonic_at=150.0
    )

    assert projected == {
        "root": "C:/work/project",
        "source": "code",
        "state": "backpressured",
        "reason": "gpu_pressure",
        "pending_count": 1,
        "oldest_age_seconds": 50.0,
        "first_observed_at": 100.0,
        "latest_observed_at": 120.0,
        "captured_generation": 2,
        "captured_count": 1,
        "next_decision_at": 130.0,
        "freshness_deadline": 400.0,
        "measurement": {
            "generation": 8,
            "observed_at": 125.0,
            "job_backlog": 2,
            "index_in_flight": 1,
            "index_waiters": 1,
            "search_in_flight": None,
            "search_latency_seconds": None,
            "gpu_pressure": True,
            "storage_available": True,
            "service_quiesced": False,
        },
        "measurement_unavailable": [
            "search_in_flight",
            "search_latency_seconds",
        ],
        "backpressure": ["gpu_pressure"],
        "last_transition": {
            "source_state": "ready",
            "destination_state": "backpressured",
            "reason": "gpu_pressure",
            "wall_time": 125.0,
            "deadline": 130.0,
            "measurement_generation": 8,
        },
        "job_id": "job-1",
        "retry_at": 140.0,
        "circuit_state": "half_open",
        "remediation": None,
    }


def test_refused_controller_has_actionable_default_remediation() -> None:
    snapshot = ControllerSnapshot(
        canonical_root="C:/work/project",
        source=WatcherSource.VAULT,
        state=ControllerState.REFUSED,
        reason=ControllerReason.FULL_REINDEX_REQUIRED,
        scope=ControllerScope(generation=1),
        observed_at=1.0,
    )

    projected = controller_snapshot_envelope(
        snapshot, observed_at=2.0, monotonic_at=2.0
    )

    assert projected["remediation"] == (
        "Inspect the refusal reason and request an explicit rebuild."
    )
    assert projected["measurement_unavailable"] == [
        "gpu_pressure",
        "index_in_flight",
        "index_waiters",
        "job_backlog",
        "search_in_flight",
        "search_latency_seconds",
        "service_quiesced",
        "storage_available",
    ]


def test_real_clock_projection_converts_scheduler_times_to_wall_time() -> None:
    monotonic_now = time.monotonic()
    wall_now = time.time()
    observation = ScopeObservation(
        relative_path="src/example.py",
        source=WatcherSource.CODE,
        first_observed_at=monotonic_now - 12.0,
        latest_observed_at=monotonic_now - 2.0,
        event_kinds=frozenset({WatcherPathEvent.MODIFIED}),
        generation=1,
    )
    snapshot = ControllerSnapshot(
        canonical_root="C:/work/project",
        source=WatcherSource.CODE,
        state=ControllerState.COLLECTING,
        reason=ControllerReason.COALESCE_WINDOW_ACTIVE,
        scope=ControllerScope(generation=1, pending=(observation,)),
        observed_at=wall_now,
        monotonic_at=monotonic_now,
        next_decision_at=monotonic_now + 3.0,
        freshness_deadline=monotonic_now + 288.0,
        measurement=ControllerMeasurement(
            generation=1,
            observed_at=monotonic_now,
        ),
    )

    projected = controller_snapshot_envelope(snapshot)

    assert projected["oldest_age_seconds"] == pytest.approx(12.0, abs=0.2)
    assert projected["first_observed_at"] == pytest.approx(wall_now - 12.0, abs=0.2)
    assert projected["next_decision_at"] == pytest.approx(wall_now + 3.0, abs=0.2)
    assert projected["freshness_deadline"] == pytest.approx(wall_now + 288.0, abs=0.2)
    measurement = projected["measurement"]
    assert isinstance(measurement, dict)
    assert measurement["observed_at"] == pytest.approx(wall_now, abs=0.2)
