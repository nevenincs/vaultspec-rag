"""Fair admission selection for automatic watcher convergence."""

from __future__ import annotations

from dataclasses import dataclass

from .watcher_controller import (
    ControllerReason,
    ControllerSnapshot,
    ControllerState,
)
from .watcher_retry import WatcherSource

ControllerKey = tuple[str, WatcherSource]


@dataclass(frozen=True, slots=True)
class AdmissionSelection:
    """Stable evidence for one fair automatic-work selection."""

    canonical_root: str
    source: WatcherSource
    deadline: float
    reason: ControllerReason
    tied_candidates: tuple[ControllerKey, ...]


class WatcherAdmissionArbiter:
    """Select earliest eligible deadlines with rotation across exact ties."""

    __slots__ = ("_last_selected",)

    def __init__(self) -> None:
        self._last_selected: ControllerKey | None = None

    def select(
        self,
        snapshots: tuple[ControllerSnapshot, ...],
        *,
        now: float,
    ) -> AdmissionSelection | None:
        """Return one admission claim without acquiring an execution lock."""
        eligible = [snapshot for snapshot in snapshots if _eligible(snapshot, now)]
        if not eligible:
            return None
        earliest = min(_deadline(snapshot) for snapshot in eligible)
        tied = sorted(
            (snapshot for snapshot in eligible if _deadline(snapshot) == earliest),
            key=_key,
        )
        selected = _rotate_after(tied, self._last_selected)
        self._last_selected = _key(selected)
        return AdmissionSelection(
            canonical_root=selected.canonical_root,
            source=selected.source,
            deadline=earliest,
            reason=ControllerReason.FAIR_TURN_SELECTED,
            tied_candidates=tuple(_key(snapshot) for snapshot in tied),
        )


def _eligible(snapshot: ControllerSnapshot, now: float) -> bool:
    if snapshot.state is not ControllerState.READY:
        return False
    decision = snapshot.next_decision_at
    return decision is None or decision <= now


def _deadline(snapshot: ControllerSnapshot) -> float:
    freshness = snapshot.freshness_deadline
    if freshness is not None:
        return freshness
    decision = snapshot.next_decision_at
    return decision if decision is not None else snapshot.observed_at


def _key(snapshot: ControllerSnapshot) -> ControllerKey:
    return snapshot.canonical_root, snapshot.source


def _rotate_after(
    tied: list[ControllerSnapshot],
    previous: ControllerKey | None,
) -> ControllerSnapshot:
    if previous is None:
        return tied[0]
    for snapshot in tied:
        if _key(snapshot) > previous:
            return snapshot
    return tied[0]
