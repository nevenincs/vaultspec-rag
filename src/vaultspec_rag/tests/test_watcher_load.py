"""In-process load proofs through the production controller scheduler path."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

import pytest

from ..server._watcher import _WatcherScheduler
from ..watcher_controller import (
    ControllerEventKind,
    ControllerLimits,
    ControllerMeasurement,
    ControllerReason,
    ControllerScope,
    ControllerSnapshot,
    ControllerState,
    ScopeObservation,
    WatcherController,
)
from ..watcher_retry import WatcherSource

if TYPE_CHECKING:
    from pathlib import Path

    from ..watcher_admission import AdmissionSelection

pytestmark = pytest.mark.unit


@dataclass(slots=True)
class _Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


def _controller(root: Path, source: WatcherSource, clock: _Clock) -> WatcherController:
    return WatcherController(
        ControllerSnapshot(
            canonical_root=str(root.resolve()),
            source=source,
            state=ControllerState.IDLE,
            reason=ControllerReason.CONVERGED,
            scope=ControllerScope(generation=0),
            observed_at=clock.now,
        ),
        monotonic=clock,
        wall_clock=clock,
        limits=ControllerLimits(
            coalesce_min_seconds=2.0,
            coalesce_max_seconds=20.0,
            maximum_freshness_seconds=30.0,
            measurement_reevaluation_seconds=2.0,
        ),
    )


def _scope(
    source: WatcherSource,
    *,
    generation: int,
    first: float,
    latest: float,
) -> ControllerScope:
    return ControllerScope(
        generation=generation,
        pending=(
            ScopeObservation(
                relative_path="src/repeated.py",
                source=source,
                first_observed_at=first,
                latest_observed_at=latest,
                event_kinds=frozenset({ControllerEventKind.MODIFIED}),
                generation=generation,
            ),
        ),
    )


def _measurement(
    clock: _Clock,
    generation: int,
    *,
    backlog: int = 0,
    storage_available: bool = True,
) -> ControllerMeasurement:
    return ControllerMeasurement(
        generation=generation,
        observed_at=clock.now,
        job_backlog=backlog,
        storage_available=storage_available,
        service_quiesced=False,
    )


def _admit(
    controller: WatcherController,
    admitted: list[tuple[str, WatcherSource]],
    selection: AdmissionSelection,
) -> None:
    controller.select()
    controller.admit(f"load-{len(admitted)}")
    admitted.append((selection.canonical_root, selection.source))


async def test_adaptive_load_batches_churn_and_bounds_freshness(
    tmp_path: Path,
) -> None:
    clock = _Clock(9.0)
    controller = _controller(tmp_path, WatcherSource.CODE, clock)
    scheduler = _WatcherScheduler(reevaluation_seconds=2.0, monotonic=clock)
    admitted: list[tuple[str, WatcherSource]] = []
    pressure = 0
    measurement_generation = 0

    def reevaluate() -> None:
        nonlocal measurement_generation
        measurement_generation += 1
        controller.evaluate(
            _measurement(clock, measurement_generation, backlog=pressure)
        )

    scheduler.register(
        controller,
        reevaluate=reevaluate,
        admit=partial(_admit, controller, admitted),
    )
    controller.observe(_scope(WatcherSource.CODE, generation=100, first=0, latest=9))
    quiet_deadline = controller.snapshot.next_decision_at
    assert quiet_deadline is not None
    clock.now = quiet_deadline
    await scheduler._run_cycle()
    assert len(admitted) == 1
    assert len(admitted) * 10 < 100

    controller = _controller(tmp_path / "sustained", WatcherSource.CODE, clock)
    scheduler = _WatcherScheduler(reevaluation_seconds=2.0, monotonic=clock)
    admitted = []
    pressure = 1
    measurement_generation = 0
    controller.observe(
        _scope(
            WatcherSource.CODE,
            generation=300,
            first=clock.now,
            latest=clock.now + 29,
        )
    )
    freshness = controller.snapshot.freshness_deadline
    assert freshness is not None
    scheduler.register(
        controller,
        reevaluate=reevaluate,
        admit=partial(_admit, controller, admitted),
    )
    clock.now = controller.snapshot.next_decision_at or clock.now
    await scheduler._run_cycle()
    assert controller.snapshot.state is ControllerState.BACKPRESSURED
    assert controller.snapshot.next_decision_at is not None
    assert controller.snapshot.next_decision_at <= freshness
    clock.now = freshness
    await scheduler._run_cycle()
    assert len(admitted) == 1


async def test_load_scheduler_rotates_fairly_and_recovers_without_herd(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    scheduler = _WatcherScheduler(reevaluation_seconds=1.0, monotonic=clock)
    admitted: list[tuple[str, WatcherSource]] = []
    pressure = 1
    for root_name, source in (
        ("a", WatcherSource.CODE),
        ("a", WatcherSource.DOCUMENT),
        ("b", WatcherSource.CODE),
    ):
        controller = _controller(tmp_path / root_name, source, clock)
        controller.observe(_scope(source, generation=1, first=0, latest=0))

        def reevaluate(current: WatcherController = controller) -> None:
            current.evaluate(_measurement(clock, 1, backlog=pressure))

        scheduler.register(
            controller,
            reevaluate=reevaluate,
            admit=partial(_admit, controller, admitted),
        )

    clock.now = max(item.next_decision_at or 0 for item in scheduler.snapshots())
    await scheduler._run_cycle()
    assert admitted == []
    pressure = 0
    scheduler.wake()
    clock.now = max(
        item.next_decision_at or clock.now for item in scheduler.snapshots()
    )
    for expected_count in (1, 2, 3):
        await scheduler._run_cycle()
        assert len(admitted) == expected_count
    assert len(set(admitted)) == 3


async def test_safety_pressure_visibly_breaches_freshness_without_admission(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    controller = _controller(tmp_path, WatcherSource.VAULT, clock)
    controller.observe(_scope(WatcherSource.VAULT, generation=1, first=0, latest=0))
    freshness = controller.snapshot.freshness_deadline
    assert freshness is not None
    admitted: list[tuple[str, WatcherSource]] = []
    scheduler = _WatcherScheduler(reevaluation_seconds=2.0, monotonic=clock)

    def reevaluate() -> None:
        controller.evaluate(_measurement(clock, 1, storage_available=False))

    scheduler.register(
        controller,
        reevaluate=reevaluate,
        admit=partial(_admit, controller, admitted),
    )
    clock.now = freshness + 5
    await scheduler._run_cycle()
    assert admitted == []
    assert controller.snapshot.state is ControllerState.BACKPRESSURED
    assert controller.snapshot.reason is ControllerReason.STORAGE_PRESSURE
    assert clock.now > freshness
