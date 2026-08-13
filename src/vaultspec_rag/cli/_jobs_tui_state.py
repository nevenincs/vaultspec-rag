"""Per-lane state the server watch holds between refreshes.

The watch app drives several independent lanes - jobs, served searches,
managed logs - each with its own fetch worker, its own error, its own refresh
clock and its own issue-ordered stamps. Held as loose attributes they read as
one flat pile in which nothing says which lane a given field belongs to, and
the app accumulated forty of them.

Grouping them by lane is what the code already means: every field here is
touched by exactly one lane's refresh path, so a lane's whole state moves,
resets, and is reasoned about as one object.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "LaneStamps",
    "LayoutMetrics",
    "MachineSignals",
    "ManagedLogState",
    "SearchActivityState",
    "ServiceVersion",
]


class LaneStamps:
    """Issue-ordered stamps for one lane's snapshots.

    Cancelling a thread worker does not stop the OS thread it is running on,
    so a fetch the next one superseded still delivers its answer - and with a
    short poll interval against a long transport timeout, several can be
    outstanding at once. Applying them in completion order lets a payload
    fetched before a mutation land after one fetched afterwards and silently
    revert the lane. Every lane therefore stamps what it issues and refuses
    what it has already overtaken, and the rule lives here rather than once
    per lane.
    """

    def __init__(self) -> None:
        self.issued = 0
        self._applied = 0

    def issue(self) -> int:
        """Stamp the next fetch and return the stamp to carry with it."""
        self.issued += 1
        return self.issued

    def accept(self, generation: int) -> bool:
        """Report whether *generation* is newer than what is already applied."""
        if generation <= self._applied:
            return False
        self._applied = generation
        return True


@dataclass(slots=True)
class SearchActivityState:
    """The served-search lane: its page, its tallies, and its own clock."""

    records: list[dict[str, object]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    returned: int = 0
    last_refresh: float | None = None
    error: str | None = None
    stamps: LaneStamps = field(default_factory=LaneStamps)
    column_cells: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class ManagedLogState:
    """The managed-log lane, independent of jobs and stamped on its own.

    ``show`` is ``None`` until the operator chooses; the width decides
    until then.
    """

    show: bool | None = None
    last_refresh: float | None = None
    error: str | None = None
    stamps: LaneStamps = field(default_factory=LaneStamps)


@dataclass(slots=True)
class ServiceVersion:
    """The release the connected daemon reports, never the local package's own.

    The two differ exactly when the difference matters. ``checked`` separates
    "no daemon has answered yet" from "the daemon answered and predates
    version reporting".
    """

    value: str | None = None
    checked: bool = False


@dataclass(slots=True)
class MachineSignals:
    """The machine-wide blocks riding the jobs payload.

    Absent-versus-null matters for each: a daemon older than a field never
    sends it, while a daemon on a host that cannot measure sends null
    measurements. The ``reported`` flags carry that distinction, so a value
    never computed is not rendered as one that was.
    """

    gpu: dict[str, object] | None = None
    gpu_reported: bool = False
    pressure: dict[str, object] | None = None
    quiesce: object | None = None
    quiesce_reported: bool = False


@dataclass(slots=True)
class LayoutMetrics:
    """The cell widths the current table width was divided into."""

    bar_cells: int = 0
    column_cells: dict[str, int] = field(default_factory=dict)
    divided_width: int = 0
