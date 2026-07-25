"""The index-state block a search response carries, and who decides it.

Every search surface has to tell a caller what the index behind an answer was
holding: which source it read, how many items that source had, whether the root
it searched is the root the caller asked for, and whether the collection is
demonstrably short of what it published. That is one fact about the service,
not a rendering concern, so it is settled here once and rendered by whoever
asked.

The module is a neutral leaf - stdlib plus the source-type vocabulary, no
server, no command-line, no store - so the in-process search path and the
daemon route can both reach it without importing each other. Two builders would
let the surfaces disagree about the shape a renderer looks up, and a renderer
reading a key only one of them emitted goes quiet on exactly the surface that
lacked it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._source_types import PublicSourceType, parse_source_type

if TYPE_CHECKING:
    from ._index_breadth import BreadthShortfall

__all__ = ["search_index_state"]


def search_index_state(
    *,
    indexed_count: int | float,
    requested_root: object,
    search_type: PublicSourceType | str,
    shortfall: BreadthShortfall | None = None,
) -> dict[str, object]:
    """Return the canonical ``index_state`` block for one search response.

    ``shortfall`` is present only over a demonstrated deficit and carries the
    figures, so a renderer names it without comparing counts for itself.
    Absence means complete or unknowable; a consumer must not read it as
    either one alone.
    """
    requested_target = str(requested_root)
    source = parse_source_type(search_type, allow_aliases=True).value
    count = int(indexed_count)
    state: dict[str, object] = {
        "source": source,
        "indexed_count": count,
        "indexed_target_root": requested_target,
        "requested_target_root": requested_target,
        "target_matches": True,
        "status": "missing" if count == 0 else "available",
    }
    if shortfall is not None:
        state["shortfall"] = shortfall.as_index_state_block()
    return state
