"""Deterministic fairness tests for watcher admission."""

from __future__ import annotations

import pytest

from ..watcher_admission import WatcherAdmissionArbiter
from ..watcher_controller import (
    ControllerReason,
    ControllerScope,
    ControllerSnapshot,
    ControllerState,
)
from ..watcher_retry import WatcherSource

pytestmark = pytest.mark.unit


def _snapshot(
    root: str,
    source: WatcherSource,
    deadline: float,
    *,
    state: ControllerState = ControllerState.READY,
    decision_at: float = 1.0,
) -> ControllerSnapshot:
    return ControllerSnapshot(
        canonical_root=root,
        source=source,
        state=state,
        reason=ControllerReason.QUIET_TREE_DEADLINE,
        scope=ControllerScope(generation=1),
        observed_at=1.0,
        next_decision_at=decision_at,
        freshness_deadline=deadline,
    )


def test_oldest_eligible_deadline_wins_regardless_of_input_order() -> None:
    arbiter = WatcherAdmissionArbiter()
    newer = _snapshot("b", WatcherSource.CODE, 30.0)
    oldest = _snapshot("a", WatcherSource.VAULT, 10.0)

    selected = arbiter.select((newer, oldest), now=5.0)

    assert selected is not None
    assert (selected.canonical_root, selected.source) == ("a", WatcherSource.VAULT)
    assert selected.deadline == 10.0


def test_new_noisy_work_cannot_displace_older_eligible_work() -> None:
    arbiter = WatcherAdmissionArbiter()
    old = _snapshot("old", WatcherSource.CODE, 20.0)
    noisy = tuple(
        _snapshot(f"new-{index}", WatcherSource.CODE, 100.0 + index)
        for index in range(20)
    )

    selected = arbiter.select((*noisy, old), now=5.0)

    assert selected is not None
    assert selected.canonical_root == "old"


def test_equal_deadlines_rotate_in_canonical_root_source_order() -> None:
    arbiter = WatcherAdmissionArbiter()
    candidates = (
        _snapshot("b", WatcherSource.VAULT, 10.0),
        _snapshot("a", WatcherSource.VAULT, 10.0),
        _snapshot("a", WatcherSource.CODE, 10.0),
    )

    selections = [arbiter.select(candidates, now=5.0) for _ in range(6)]

    assert all(selection is not None for selection in selections)
    assert [(item.canonical_root, item.source) for item in selections if item] == [
        ("a", WatcherSource.CODE),
        ("a", WatcherSource.VAULT),
        ("b", WatcherSource.VAULT),
    ] * 2
    assert selections[0] is not None
    assert selections[0].reason is ControllerReason.FAIR_TURN_SELECTED
    assert len(selections[0].tied_candidates) == 3


def test_ineligible_states_and_future_decisions_are_excluded() -> None:
    arbiter = WatcherAdmissionArbiter()
    collecting = _snapshot(
        "a", WatcherSource.CODE, 5.0, state=ControllerState.COLLECTING
    )
    future = _snapshot("b", WatcherSource.CODE, 6.0, decision_at=20.0)

    assert arbiter.select((collecting, future), now=10.0) is None


def test_rotation_survives_tie_membership_changes() -> None:
    arbiter = WatcherAdmissionArbiter()
    a = _snapshot("a", WatcherSource.CODE, 10.0)
    b = _snapshot("b", WatcherSource.CODE, 10.0)
    c = _snapshot("c", WatcherSource.CODE, 10.0)
    selections = (
        arbiter.select((a, b, c), now=5.0),
        arbiter.select((b, c), now=5.0),
        arbiter.select((a, c), now=5.0),
    )
    assert all(selection is not None for selection in selections)
    assert [selection.canonical_root for selection in selections if selection] == [
        "a",
        "b",
        "c",
    ]
