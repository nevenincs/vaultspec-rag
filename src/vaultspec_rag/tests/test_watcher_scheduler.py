"""Deterministic lifecycle proofs for the watcher controller scheduler."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from .._root_identity import canonical_root_key
from ..server._watcher import _WatcherScheduler
from ..watcher_controller import (
    ControllerMeasurement,
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
            canonical_root=canonical_root_key(root),
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
    reevaluated = asyncio.Event()
    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=clock)

    def reevaluate() -> None:
        reevaluated.set()
        scheduler.unregister_root(tmp_path)

    scheduler.register(
        _controller(tmp_path, clock, state=ControllerState.COLLECTING, deadline=100.0),
        reevaluate=reevaluate,
        admit=lambda _selection: None,
    )

    # The wait is capped at the reevaluation interval, never the far deadline.
    assert scheduler._next_timeout() == 5.0
    loop = asyncio.get_running_loop()
    started = loop.time()
    await scheduler.run()
    elapsed = loop.time() - started

    assert reevaluated.is_set()
    assert elapsed < 1.0, "the registration wake-up did not short-circuit the wait"


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
    """An overdue recovery is admitted only once its jitter delay has elapsed.

    The loop runs on the event loop's own clock, as the service does, so the
    jitter delay is waited out for real. Mutation: admitting without the
    not-before comparison admits on the first cycle and fails the elapsed
    assertion below.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    clock = _Clock(started)
    admitted: list[float] = []
    scheduler: _WatcherScheduler

    def admit(_selection: AdmissionSelection) -> None:
        admitted.append(loop.time())
        scheduler.unregister_root(tmp_path)

    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=loop.time)
    scheduler.register(
        _controller(
            tmp_path, clock, state=ControllerState.READY, deadline=started - 1.0
        ),
        reevaluate=lambda: None,
        admit=admit,
    )
    not_before = next(iter(scheduler._registrations.values())).recovery_not_before
    assert not_before is not None
    assert started <= not_before <= started + 1.0

    async with asyncio.timeout(10):
        await scheduler.run()

    assert len(admitted) == 1
    assert admitted[0] >= not_before


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


async def test_only_a_changed_state_or_reason_is_logged_as_a_transition(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Every reevaluation stamps a fresh transition record. Logging each record
    # wrote one line per controller per scheduler turn, which rotated the whole
    # service log away within seconds. Mutation: comparing transition records
    # instead of state and reason logs all three reevaluations below.
    clock = _Clock(10.0)
    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=clock)
    controller = _controller(
        tmp_path, clock, state=ControllerState.COLLECTING, deadline=100.0
    )
    generations = iter(range(1, 4))

    def reevaluate() -> None:
        clock.now += 1.0
        controller.evaluate(
            ControllerMeasurement(generation=next(generations), observed_at=clock.now)
        )

    scheduler.register(controller, reevaluate=reevaluate, admit=lambda _selection: None)
    key = (controller.snapshot.canonical_root, controller.snapshot.source)
    caplog.set_level(logging.INFO, logger="vaultspec_rag.server")

    for _ in range(3):
        await scheduler._invoke(key, reevaluate)

    transitions = [
        record
        for record in caplog.records
        if "service.watcher.controller event=transition" in record.getMessage()
    ]
    assert len(transitions) == 1
    assert controller.snapshot.state is ControllerState.CONVERGED
