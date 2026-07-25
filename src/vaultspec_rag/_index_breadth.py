"""How much breadth a published code index claims, and where that claim lives.

A neutral leaf shared by the indexer that writes the claim and the search path
that checks it. It exists as its own module so neither side has to import the
other: the writer lives behind the tree-sitter-bearing indexer package, while
the reader sits on a search path that is deliberately model-free and must stay
importable on a host with no GPU.

The claim is a point count recorded when a code index publishes, taken after
storage reconciliation so it is exactly the breadth the sidecar describes.
Without it a truncated collection is indistinguishable from a small one - the
file entries name which paths are indexed, but nothing says how many points
that should amount to, so a collection holding a fraction of its corpus reads
as intact and answers searches as though it were whole.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, NamedTuple, cast

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

#: Reserved sidecar key carrying the published point count. Reserved keys begin
#: with ``__`` so they can never collide with a relative file path or be counted
#: as one during set arithmetic over the sidecar's file entries.
PUBLISHED_POINTS_KEY = "__code_published_points__"

#: Reserved sidecar key marking that the collection still holds points encoded
#: under a regime the current configuration no longer produces. Set when a gate
#: reconciles rather than rebuilding destructively, and cleared only by a
#: rebuild an operator asked for, which is the one thing that removes them.
SUPERSEDED_REGIME_KEY = "__code_superseded_regime__"

__all__ = [
    "PUBLISHED_POINTS_KEY",
    "SUPERSEDED_REGIME_KEY",
    "BreadthShortfall",
    "code_breadth_shortfall",
    "code_meta_path",
    "code_regime_superseded",
    "parse_published_points",
    "parse_superseded_regime",
    "read_published_points",
]


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


def parse_published_points(raw: Mapping[str, object]) -> int | None:
    """Return the point count a sidecar mapping claims, or ``None`` for no claim.

    ``None`` means the sidecar predates the key or carries an unusable value.
    That is a "cannot tell" and must never be read as a shortfall: treating
    ignorance as loss would escalate every root written by an older build.

    The values are typed as ``object`` because they arrive from parsed JSON: the
    writer stamps a string, but a sidecar this build did not write can carry
    anything, and that is exactly the case the unusable-value branch exists for.
    """
    value = raw.get(PUBLISHED_POINTS_KEY)
    if value is None:
        return None
    if not isinstance(value, (str, int)):
        logger.debug("unusable published point count %r in code sidecar", value)
        return None
    try:
        count = int(value)
    except ValueError:
        logger.debug("unusable published point count %r in code sidecar", value)
        return None
    return count if count >= 0 else None


def parse_superseded_regime(raw: Mapping[str, object]) -> bool:
    """Return whether a sidecar mapping marks the collection's regime superseded.

    Absence is "no", not "cannot tell": a sidecar written before the key
    existed describes an index no gate has reconciled in place, and warning
    over every such root would train the reader to skip the warning.
    """
    return raw.get(SUPERSEDED_REGIME_KEY) == "1"


def code_regime_superseded(root: pathlib.Path) -> bool:
    """Return whether *root*'s code collection still holds superseded points."""
    path = code_meta_path(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("code sidecar %s unreadable: %s", path, exc)
        return False
    if not isinstance(raw, dict):
        return False
    return parse_superseded_regime(cast("dict[str, object]", raw))


def code_meta_path(root: pathlib.Path) -> pathlib.Path:
    """Return the code index metadata sidecar path for *root*."""
    from .config import get_config

    cfg = get_config()
    return root / cfg.data_dir / cfg.code_index_metadata_file


def read_published_points(root: pathlib.Path) -> int | None:
    """Return the point count *root*'s published code index claims.

    ``None`` when the sidecar is absent, unreadable, or silent on breadth. Every
    such case is a "cannot tell" rather than a claim of zero, so a caller cannot
    mistake an unreadable sidecar for a destroyed index.
    """
    path = code_meta_path(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("code sidecar %s unreadable: %s", path, exc)
        return None
    if not isinstance(raw, dict):
        return None
    return parse_published_points(cast("dict[str, object]", raw))


def code_breadth_shortfall(
    root: pathlib.Path,
    live_count: int,
) -> BreadthShortfall | None:
    """Return the shortfall *root*'s code collection is in, or ``None``.

    ``None`` covers both "complete" and "cannot tell": a sidecar silent on
    breadth yields no shortfall, because a root written by an older build has
    nothing to compare against and must not be reported as incomplete on that
    account. A caller therefore reads a returned value as demonstrated
    incompleteness and nothing else.

    ``live_count`` is supplied by the caller rather than counted here, so a
    search path that has already counted the collection pays no second round
    trip - which is the only reason this check is affordable on every query.
    """
    published = read_published_points(root)
    if published is None or live_count >= published:
        return None
    return BreadthShortfall(published=published, live=live_count)
