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

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._source_types import PublicSourceType, parse_source_type

if TYPE_CHECKING:
    from ._index_breadth import BreadthShortfall, FileBreadthShortfall
    from ._index_integrity import IndexIntegrity

__all__ = ["BreadthFindings", "search_index_state"]


@dataclass(frozen=True, slots=True)
class BreadthFindings:
    """Completeness conclusions one search settled, attached to its block.

    ``shortfall`` and ``file_shortfall`` are present only over a demonstrated
    deficit and carry the figures, so a renderer names them without comparing
    counts for itself. Absence means complete or unknowable; a consumer must
    not read it as either one alone.

    ``integrity`` follows the opposite discipline: emitted whenever the
    serve-time check ran, ``consistent`` included, so an absent block means
    only that the surface predates the check - never that the collection was
    checked and found fine.
    """

    shortfall: BreadthShortfall | None = None
    file_shortfall: FileBreadthShortfall | None = None
    integrity: IndexIntegrity | None = None
    #: Id of the automatic repair job in flight for a shrunken verdict, set by
    #: the service path that queued it. Rendered as an additive key inside the
    #: integrity block, so surfaces that never queue repairs simply omit it.
    integrity_repair_job_id: str | None = None


def search_index_state(
    *,
    indexed_count: int | float,
    requested_root: object,
    search_type: PublicSourceType | str,
    findings: BreadthFindings | None = None,
) -> dict[str, object]:
    """Return the canonical ``index_state`` block for one search response.

    ``findings`` carries the completeness conclusions the search settled; see
    :class:`BreadthFindings` for the presence discipline of each field.
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
    found = findings or BreadthFindings()
    if found.shortfall is not None:
        state["shortfall"] = found.shortfall.as_index_state_block()
    # Independent of the point comparison: a republished fragment stamps a
    # point count that agrees with itself, so only the file figures disagree.
    if found.file_shortfall is not None:
        state["file_shortfall"] = found.file_shortfall.as_index_state_block()
    if found.integrity is not None:
        block = found.integrity.as_block()
        if found.integrity_repair_job_id is not None:
            block["repair_job_id"] = found.integrity_repair_job_id
        state["index_integrity"] = block
    return state
