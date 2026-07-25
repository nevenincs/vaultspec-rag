"""Which code collections a root serves, and which it has left behind.

A rebuild publishes into a generation-scoped collection and moves a per-root
pointer, so a root's namespace can hold the collection currently answering
searches alongside earlier generations nothing points at any more. This reports
that split. It does not act on it.

Detection is separated from removal deliberately. The namespace survey the
maintenance verbs consume is per-prefix - one status for a whole root - and the
prefix-scoped delete takes every collection under it, served included. Dropping
a superseded generation therefore needs a finer granularity than those verbs
have, plus a definition of when no reader still holds the collection, which
nothing currently tracks. Until both exist an operator can at least see what
has accumulated, which is what this provides.

A root whose pointer cannot be read is omitted rather than reported. An
unreadable pointer is not evidence that nothing points anywhere, and a listing
that implied otherwise would be the first step toward deleting a live index.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple

from ._store_models import read_served_pointer

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "GenerationReclaim",
    "RootGenerations",
    "advance_generation_stamps",
    "decide_generation_reclaim",
    "survey_generations",
]


class RootGenerations(NamedTuple):
    """One root's served code collection and the generations it has outgrown.

    ``served`` is what the pointer names, or the derived name when no
    replacement was ever published. ``unreferenced`` names generations that
    exist in storage and are no longer served - what a future reclamation would
    consider, once it can also establish that no reader holds them.
    """

    root: str
    served: str
    unreferenced: tuple[str, ...]

    @property
    def has_debt(self) -> bool:
        """Whether this root is carrying generations nothing points at."""
        return bool(self.unreferenced)


def survey_generations(
    roots: Mapping[str, str],
    existing: Iterable[str],
) -> tuple[RootGenerations, ...]:
    """Report per-root served and unreferenced code collections.

    Args:
        roots: Root path to that root's derived code collection name. The
            derived name is what the root would serve had it never published a
            replacement.
        existing: Every collection name currently in storage.

    Returns:
        One entry per root whose pointer could be read, in input order. A root
        whose pointer is unreadable is omitted entirely: absence of a legible
        pointer is not an observation that its generations are unreferenced,
        and reporting them as such invites exactly the deletion the separation
        of detection from removal exists to prevent.
    """
    from ._store_models import reclaimable_generation_collections

    names = tuple(existing)
    reports: list[RootGenerations] = []
    for root, derived in roots.items():
        pointer = read_served_pointer(root)
        if not pointer.verifiable:
            continue
        served = pointer.collection or derived
        # Scoped to this root, then handed to the function that owns what
        # "reclaimable" means. Restating that rule here would be a second
        # definition of the one question a drop depends on, and the two would
        # answer differently the first time either moved.
        unreferenced = reclaimable_generation_collections(
            existing=(name for name in names if name.startswith(derived)),
            served=(served,),
        )
        reports.append(
            RootGenerations(root=str(root), served=served, unreferenced=unreferenced)
        )
    return tuple(reports)


@dataclass(frozen=True, slots=True)
class GenerationReclaim:
    """What may happen to one superseded generation, and why.

    ``action`` is ``reclaim`` (droppable now), ``pending`` (grace window still
    running), or ``held`` (something observed that forbids acting at all).
    ``reason`` names the gate, so an operator reading a deferral learns which
    one it was rather than only that nothing happened.
    """

    collection: str
    action: str
    reason: str

    @property
    def droppable(self) -> bool:
        """Whether every gate passed and this collection may be dropped now."""
        return self.action == "reclaim"


def decide_generation_reclaim(
    collection: str,
    *,
    stamps: Mapping[str, str],
    now: datetime,
    grace_hours: float,
    reader_present: bool,
    pointer_verifiable: bool,
) -> GenerationReclaim:
    """Decide whether one superseded generation may be dropped now.

    Three gates, and every one of them fails closed. An unreadable pointer is
    not evidence that nothing points at this collection, so it holds. A live
    lease means a reader in this process may still be resolving the old name,
    because a store binds its collection once at construction and keeps it for
    its whole life. Neither can be waited out, so both reset the clock rather
    than merely pausing it - the window measures continuous unreferenced-ness,
    and a single contrary observation means it has not been continuous.

    Only when nothing contradicts it does time substitute for evidence about
    other processes, which cannot be observed at all.

    The caller must resolve the pointer at the moment it decides, not from a
    survey gathered earlier in the cycle: a collection can become the served
    one between gather and drop, and a stale snapshot would step past every
    gate here while naming a live index.
    """
    if not pointer_verifiable:
        return GenerationReclaim(collection, "held", "pointer_unverifiable")
    if reader_present:
        return GenerationReclaim(collection, "held", "reader_lease_held")
    first_seen = stamps.get(collection)
    if not first_seen:
        return GenerationReclaim(collection, "pending", "grace_started")
    try:
        seen_at = datetime.fromisoformat(first_seen)
    except ValueError:
        return GenerationReclaim(collection, "pending", "grace_restarted")
    if seen_at.tzinfo is None:
        seen_at = seen_at.replace(tzinfo=UTC)
    age_hours = (now - seen_at).total_seconds() / 3600.0
    if age_hours < grace_hours:
        remaining = grace_hours - age_hours
        return GenerationReclaim(
            collection, "pending", f"grace_remaining_h={remaining:.1f}"
        )
    return GenerationReclaim(collection, "reclaim", "grace_elapsed")


def advance_generation_stamps(
    stamps: Mapping[str, str],
    *,
    unreferenced: Iterable[str],
    held: Iterable[str],
    now_iso: str,
) -> dict[str, str]:
    """Advance the per-collection grace clocks from one observation.

    A collection observed unreferenced keeps an existing stamp, because the
    window measures CONTINUOUS unreferenced-ness and a daemon restart must not
    reset it. Anything in ``held`` - served again, a live reader, an unreadable
    pointer - has its stamp cleared, so a contrary observation restarts the
    window from zero rather than letting it accumulate across a gap.
    """
    advanced = dict(stamps)
    for collection in held:
        advanced.pop(collection, None)
    for collection in unreferenced:
        advanced.setdefault(collection, now_iso)
    return advanced
