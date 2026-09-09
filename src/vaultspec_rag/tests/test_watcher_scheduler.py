"""Deterministic lifecycle proofs for the watcher controller scheduler."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from ..server._watcher import _WatcherScheduler
from ..watcher_controller import (
    ControllerReason,
    ControllerScope,
    ControllerSnapshot,
    ControllerState,
    WatcherController,
)
from ..watcher_retry import WatcherSource

if TYPE_CHECKING:
    from pathlib import Path

    from ..watcher_admission import AdmissionSelection

pytestmark = pytest.mark.unit


@dataclass(slots=True)
class _Clock:
    now: float

    def __call__(self) -> float:
        return self.now


def _controller(
    root: Path,
    clock: _Clock,
    *,
    state: ControllerState,
    deadline: float | None,
) -> WatcherController:
    return WatcherController(
        ControllerSnapshot(
            canonical_root=str(root.resolve()),
            source=WatcherSource.CODE,
            state=state,
            reason=ControllerReason.QUIET_TREE_DEADLINE,
            scope=ControllerScope(generation=1),
            observed_at=clock.now,
            next_decision_at=deadline,
            freshness_deadline=deadline,
        ),
        monotonic=clock,
        wall_clock=clock,
    )


def test_earliest_deadline_is_capped_by_measurement_reevaluation(
    tmp_path: Path,
) -> None:
    clock = _Clock(10.0)
    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=clock)
    scheduler.register(
        _controller(
            tmp_path / "later", clock, state=ControllerState.COLLECTING, deadline=19.0
        ),
        reevaluate=lambda: None,
        admit=lambda _selection: None,
    )
    scheduler.register(
        _controller(
            tmp_path / "earlier",
            clock,
            state=ControllerState.COLLECTING,
            deadline=13.0,
        ),
        reevaluate=lambda: None,
        admit=lambda _selection: None,
    )

    assert scheduler._next_timeout() == 3.0

    scheduler.unregister_root(tmp_path / "earlier")
    assert scheduler._next_timeout() == 5.0


async def test_event_wakeup_reevaluates_without_waiting_for_deadline(
    tmp_path: Path,
) -> None:
    clock = _Clock(10.0)
    waited: list[float] = []
    reevaluated = asyncio.Event()

    async def wait_for_wakeup(_event: asyncio.Event, timeout: float) -> bool:
        waited.append(timeout)
        return True

    scheduler = _WatcherScheduler(
        reevaluation_seconds=5.0,
        monotonic=clock,
        wait_for_wakeup=wait_for_wakeup,
    )

    def reevaluate() -> None:
        reevaluated.set()
        scheduler.unregister_root(tmp_path)

    scheduler.register(
        _controller(tmp_path, clock, state=ControllerState.COLLECTING, deadline=100.0),
        reevaluate=reevaluate,
        admit=lambda _selection: None,
    )

    await scheduler.run()

    assert reevaluated.is_set()
    assert waited == [5.0]


async def test_overdue_recovery_uses_stable_bounded_jitter(tmp_path: Path) -> None:
    clock = _Clock(10.0)
    admitted: list[AdmissionSelection] = []
    controller = _controller(tmp_path, clock, state=ControllerState.READY, deadline=9.0)
    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=clock)
    scheduler.register(
        controller,
        reevaluate=lambda: None,
        admit=admitted.append,
    )
    registration = next(iter(scheduler._registrations.values()))
    not_before = registration.recovery_not_before

    assert not_before is not None
    assert 10.0 <= not_before <= 11.0
    await scheduler._run_cycle()
    assert admitted == []

    same = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=clock)
    same.register(controller, reevaluate=lambda: None, admit=lambda _selection: None)
    assert next(iter(same._registrations.values())).recovery_not_before == not_before

    clock.now = not_before
    await scheduler._run_cycle()
    assert len(admitted) == 1


async def test_scheduler_loop_honours_recovery_jitter_timeout(tmp_path: Path) -> None:
    clock = _Clock(10.0)
    waits: list[float] = []
    scheduler: _WatcherScheduler

    async def wait_for_wakeup(_event: asyncio.Event, timeout: float) -> bool:
        waits.append(timeout)
        if len(waits) == 1:
            return True
        clock.now += timeout
        return False

    def admit(_selection: AdmissionSelection) -> None:
        scheduler.unregister_root(tmp_path)

    scheduler = _WatcherScheduler(
        reevaluation_seconds=5.0,
        monotonic=clock,
        wait_for_wakeup=wait_for_wakeup,
    )
    scheduler.register(
        _controller(tmp_path, clock, state=ControllerState.READY, deadline=9.0),
        reevaluate=lambda: None,
        admit=admit,
    )
    not_before = next(iter(scheduler._registrations.values())).recovery_not_before
    assert not_before is not None

    await scheduler.run()

    assert waits == [not_before - 10.0, not_before - 10.0]


async def test_callback_failure_does_not_terminate_scheduler(tmp_path: Path) -> None:
    clock = _Clock(10.0)
    admitted = asyncio.Event()
    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=clock)

    def fail() -> None:
        raise RuntimeError("measurement source unavailable")

    def admit(_selection: AdmissionSelection) -> None:
        admitted.set()

    scheduler.register(
        _controller(tmp_path, clock, state=ControllerState.READY, deadline=11.0),
        reevaluate=fail,
        admit=admit,
    )
    clock.now = 11.0

    await scheduler._run_cycle()

    assert admitted.is_set()


def test_registration_revives_scheduler_committed_to_last_root_stop(
    tmp_path: Path,
) -> None:
    clock = _Clock(10.0)
    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=clock)
    first = tmp_path / "first"
    second = tmp_path / "second"
    scheduler.register(
        _controller(first, clock, state=ControllerState.IDLE, deadline=None),
        reevaluate=lambda: None,
        admit=lambda _selection: None,
    )
    scheduler.unregister_root(first)
    assert scheduler._stopping is True

    scheduler.register(
        _controller(second, clock, state=ControllerState.IDLE, deadline=None),
        reevaluate=lambda: None,
        admit=lambda _selection: None,
    )

    assert scheduler._stopping is False
    assert scheduler.empty is False


async def test_unregister_joins_in_flight_dispatch(tmp_path: Path) -> None:
    clock = _Clock(10.0)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def admit(_selection: AdmissionSelection) -> None:
        entered.set()
        await release.wait()

    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=clock)
    scheduler.register(
        _controller(tmp_path, clock, state=ControllerState.READY, deadline=11.0),
        reevaluate=lambda: None,
        admit=admit,
    )
    clock.now = 11.0
    cycle = asyncio.create_task(scheduler._run_cycle())
    await entered.wait()

    scheduler.unregister_root(tmp_path)
    joined = asyncio.create_task(scheduler.wait_root_released(tmp_path, deadline=20.0))
    assert not joined.done()

    release.set()
    assert await joined is True
    await cycle
