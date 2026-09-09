"""Proof-fenced code breadth checks shared by search entry points."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NamedTuple, cast

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Mapping

    from ._publication_state import PublicationSnapshot

from ._operator_commands import IndexCommandOptions, index_command
from ._source_types import PublicSourceType

logger = logging.getLogger(__name__)

__all__ = [
    "SHORTFALL_CONSEQUENCE",
    "SHORTFALL_REMEDIATION",
    "BreadthShortfall",
    "CodeBreadthSnapshot",
    "ShortfallWarning",
    "acquire_code_breadth_snapshot",
    "shortfall_warnings",
]
#: What an incomplete index means for the reader, in one wording for every
#: surface. The noun is ``code`` because breadth is published for the code
#: index alone, so a warning that fires is always about missing code even on a
#: combined search - and it agrees with the remediation below, which reindexes
#: exactly that.
SHORTFALL_CONSEQUENCE = "an absent result is not evidence that no such code exists"

#: The one command that repairs any shortfall. A remediation an operator is
#: told to run has to be the command that still exists; a second copy is one
#: rename away from sending them to a flag that was removed.
SHORTFALL_REMEDIATION = index_command("code", IndexCommandOptions(full=True))


class BreadthShortfall(NamedTuple):
    """A code collection holding fewer points than its publication claimed.

    Carries the figures rather than a bare flag so a renderer can name the
    deficit without re-deriving it. Only ever constructed for a real shortfall,
    so its existence is the conclusion and no consumer compares counts again.
    """

    published: int
    live: int

    @property
    def missing(self) -> int:
        """Points the publication claimed that the collection no longer holds."""
        return self.published - self.live

    def as_index_state_block(self) -> dict[str, int]:
        """Return the canonical ``index_state["shortfall"]`` block.

        One projection, so the in-process search path and the daemon hand a
        renderer the same keys. A second construction site would let the two
        drift, and a renderer reading a key only one of them emits would go
        quiet on exactly the surface that lacked it.
        """
        return {
            "published_count": self.published,
            "live_count": self.live,
            "missing_count": self.missing,
        }


class CodeBreadthSnapshot(NamedTuple):
    """Canonical proof held across one cheap backend count."""

    published: int
    publication: PublicationSnapshot

    def finish(self, live_count: int) -> BreadthShortfall | None:
        """Fence the completed count and return its demonstrated deficit."""
        self.publication.validate()
        if live_count >= self.published:
            return None
        return BreadthShortfall(published=self.published, live=live_count)


class ShortfallWarning(NamedTuple):
    """One demonstrated deficit, in the words every surface reports it with.

    Split into three parts because the surfaces differ in how much room they
    have, not in what they say. The command line prints all three across a
    warning block; the service summary has one sentence and carries the
    deficit alone. Both draw on this, so neither can describe the same figures
    differently.
    """

    deficit: str
    """The figures, as a clause: what the index holds against what it claimed."""

    missing: str
    """The count that is gone, as its own clause for a surface with room."""

    why: str
    """Why that deficit reaches the reader's results."""


def _shortfall_figures(
    index_state: Mapping[str, object], key: str
) -> Mapping[str, object] | None:
    """Return ``index_state[key]`` when it is a figures dict, else ``None``.

    A missing field means complete or unknowable, and warning on either would
    train the reader to ignore the warning.
    """
    figures = index_state.get(key)
    if not isinstance(figures, dict):
        return None
    return cast("Mapping[str, object]", figures)


def shortfall_warnings(index_state: Mapping[str, object]) -> list[ShortfallWarning]:
    """Return every deficit *index_state* demonstrates, in reporting order.

    The service settles whether a shortfall exists and carries the figures, so
    this describes what it was given and compares nothing.

    Point loss and result collapse are independent signals and are rendered
    from conclusions already carried by the service.
    """
    warnings: list[ShortfallWarning] = []
    points = _shortfall_figures(index_state, "shortfall")
    if points is not None:
        warnings.append(
            ShortfallWarning(
                deficit=(
                    f"this index holds {points.get('live_count')} of the "
                    f"{points.get('published_count')} sections it published"
                ),
                missing=f"{points.get('missing_count')} are missing",
                why="These results are drawn from an incomplete index",
            )
        )
    # Third kind, and the only one derived from the answer rather than from a
    # claim. It fires exactly where the other two cannot: a fragment that
    # republished its own figures is self-consistent, so every count agrees
    # and nothing above this line has anything to compare.
    collapse = _shortfall_figures(index_state, "result_collapse")
    if collapse is not None:
        warnings.append(
            ShortfallWarning(
                deficit=(
                    f"all {collapse.get('result_count')} results resolve to a "
                    f"single file, {collapse.get('path')}"
                ),
                missing="no other file matched",
                why=(
                    "An index serving one file answers every query from it, "
                    "and the answer looks like a real absence"
                ),
            )
        )
    return warnings


def acquire_code_breadth_snapshot(root: pathlib.Path) -> CodeBreadthSnapshot:
    """Acquire canonical code breadth immediately before a backend count.

    Missing, obsolete, or incompatible proof is an explicit rebuild boundary;
    it is never treated as an unknown-but-acceptable publication state.
    """
    from ._publication_state import acquire_publication_snapshot

    publication = acquire_publication_snapshot(root, PublicSourceType.CODE)
    return CodeBreadthSnapshot(
        published=publication.proof.aggregate.retained_points,
        publication=publication,
    )
