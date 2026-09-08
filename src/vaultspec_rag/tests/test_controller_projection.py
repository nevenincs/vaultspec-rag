"""Tests for canonical watcher-controller service facts."""

from __future__ import annotations

import pytest

from ..api import controller_snapshot_envelope
from ..watcher_controller import (
    ControllerEventKind,
    ControllerMeasurement,
    ControllerReason,
    ControllerScope,
    ControllerSnapshot,
    ControllerState,
    ControllerTransition,
    ScopeObservation,
)
from ..watcher_retry import WatcherCircuitState, WatcherSource

pytestmark = pytest.mark.unit


def test_controller_projection_contains_complete_actionable_truth() -> None:
    observation = ScopeObservation(
        relative_path="src/example.py",
        source=WatcherSource.CODE,
        first_observed_at=100.0,
        latest_observed_at=120.0,
        event_kinds=frozenset({ControllerEventKind.MODIFIED}),
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

    projected = controller_snapshot_envelope(snapshot, observed_at=150.0)

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

    projected = controller_snapshot_envelope(snapshot, observed_at=2.0)

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
