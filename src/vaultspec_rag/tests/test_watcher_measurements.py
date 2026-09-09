"""Tests for canonical service-owned watcher measurements."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ..job_models import JobMode
from ..server._watcher_measurements import (
    WatcherMeasurementFacts,
    compose_watcher_measurement,
)

pytestmark = pytest.mark.unit


def test_measurement_composes_existing_service_facts_without_inference() -> None:
    measurement = compose_watcher_measurement(
        WatcherMeasurementFacts(
            generation=7,
            observed_at=42.0,
            jobs=(),
            limiter_snapshot={
                "index": {"borrowed_tokens": 1, "waiting": 2},
                "search": {"borrowed_tokens": 3, "waiting": 0},
            },
            search_snapshot={
                "counts": {"active": 4},
                "recent": [
                    {"total_seconds": 0.25},
                    {"total_seconds": 1.5},
                ],
            },
            pressure_tier="elevated",
            storage_available=True,
            quiesce=None,
            retry_state=None,
            requested_cost=JobMode.INCREMENTAL,
            effective_cost=JobMode.INCREMENTAL,
        )
    )

    assert measurement.controller.generation == 7
    assert measurement.controller.job_backlog == 2
    assert measurement.controller.index_in_flight == 1
    assert measurement.controller.index_waiters == 2
    assert measurement.controller.search_in_flight == 4
    assert measurement.controller.search_latency_seconds == 1.5
    assert measurement.controller.gpu_pressure is True
    assert measurement.controller.storage_available is True
    assert measurement.requested_cost is JobMode.INCREMENTAL
    assert measurement.effective_cost is JobMode.INCREMENTAL
    assert measurement.unavailable == {"quiesce", "retry"}


def test_missing_measurements_remain_explicitly_unavailable() -> None:
    measurement = compose_watcher_measurement(
        WatcherMeasurementFacts(
            generation=0,
            observed_at=0.0,
            jobs=(),
            limiter_snapshot=None,
            search_snapshot=None,
            pressure_tier=None,
            storage_available=None,
            quiesce=None,
            retry_state=None,
            effective_cost=None,
        )
    )

    assert measurement.controller.index_in_flight is None
    assert measurement.controller.index_waiters is None
    assert measurement.controller.search_in_flight is None
    assert measurement.controller.search_latency_seconds is None
    assert measurement.controller.gpu_pressure is None
    assert measurement.controller.storage_available is None
    assert measurement.controller.service_quiesced is None
    assert measurement.unavailable == {
        "effective_cost",
        "index_limiter",
        "machine_pressure",
        "quiesce",
        "retry",
        "search_activity",
        "search_latency",
        "search_limiter",
        "storage",
    }


def test_measurement_is_immutable() -> None:
    measurement = compose_watcher_measurement(
        WatcherMeasurementFacts(
            generation=1,
            observed_at=2.0,
            jobs=(),
            limiter_snapshot=None,
            search_snapshot=None,
            pressure_tier=None,
            storage_available=None,
            quiesce=None,
            retry_state=None,
        )
    )

    field_name = "generation"
    with pytest.raises(FrozenInstanceError):
        setattr(measurement, field_name, 2)
