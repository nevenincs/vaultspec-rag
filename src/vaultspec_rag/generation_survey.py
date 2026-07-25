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

from typing import TYPE_CHECKING, NamedTuple

from ._store_models import read_served_pointer, reclaimable_generation_collections

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ["RootGenerations", "survey_generations"]


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
    names = tuple(existing)
    reports: list[RootGenerations] = []
    for root, derived in roots.items():
        pointer = read_served_pointer(root)
        if not pointer.verifiable:
            continue
        served = pointer.collection or derived
        # Which of this root's names have lost their last reference is decided
        # by the store's own predicate, not restated here. Scoping the input to
        # the root's derived prefix is this function's only addition: the
        # predicate is deliberately agnostic about which root a name belongs to.
        unreferenced = reclaimable_generation_collections(
            existing=(name for name in names if name.startswith(derived)),
            served=(served,),
        )
        reports.append(
            RootGenerations(root=str(root), served=served, unreferenced=unreferenced)
        )
    return tuple(reports)
