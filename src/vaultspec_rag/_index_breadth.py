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

#: Reserved sidecar key carrying the number of distinct files the collection
#: held points for when the publication was written. Recorded beside the point
#: count because the two fail independently: a collection can hold a plausible
#: number of points spread across a fraction of the files the same sidecar
#: names, and no comparison of point counts can see that.
PUBLISHED_FILES_KEY = "__code_published_files__"

__all__ = [
    "PUBLISHED_FILES_KEY",
    "PUBLISHED_POINTS_KEY",
    "BreadthShortfall",
    "FileBreadthShortfall",
    "code_breadth_shortfall",
    "code_file_breadth_shortfall",
    "code_meta_path",
    "parse_reserved_count",
    "read_reserved_count",
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


class FileBreadthShortfall(NamedTuple):
    """A code publication covering fewer files than the same sidecar names.

    Distinct from :class:`BreadthShortfall`, which compares point counts across
    time. This compares two figures written by one publication, so it holds
    whether or not the collection has lost anything since.
    """

    named: int
    covered: int

    @property
    def missing(self) -> int:
        """Files the sidecar names that the publication did not cover."""
        return self.named - self.covered

    def as_index_state_block(self) -> dict[str, int]:
        """Return the canonical ``index_state["file_shortfall"]`` block."""
        return {
            "named_count": self.named,
            "covered_count": self.covered,
            "missing_count": self.missing,
        }


def parse_reserved_count(raw: Mapping[str, object], key: str) -> int | None:
    """Return the count *key* claims in a sidecar mapping, or ``None`` for none.

    ``None`` means the sidecar predates the key or carries an unusable value.
    That is a "cannot tell" and must never be read as a shortfall: treating
    ignorance as loss would escalate every root written by an older build.

    The values are typed as ``object`` because they arrive from parsed JSON: the
    writer stamps a string, but a sidecar this build did not write can carry
    anything, and that is exactly the case the unusable-value branch exists for.
    """
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, (str, int)):
        logger.debug("unusable %s %r in code sidecar", key, value)
        return None
    try:
        count = int(value)
    except ValueError:
        logger.debug("unusable %s %r in code sidecar", key, value)
        return None
    return count if count >= 0 else None


def code_meta_path(root: pathlib.Path) -> pathlib.Path:
    """Return the code index metadata sidecar path for *root*."""
    from .config import get_config

    cfg = get_config()
    return root / cfg.data_dir / cfg.code_index_metadata_file


def _read_meta(root: pathlib.Path) -> dict[str, object] | None:
    """Return *root*'s parsed code sidecar, or ``None`` when it cannot be read.

    One reader, so a caller needing both a reserved count and the file entries
    pays a single parse and cannot observe the two halves from different reads
    of a file another process is replacing.
    """
    path = code_meta_path(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("code sidecar %s unreadable: %s", path, exc)
        return None
    if not isinstance(raw, dict):
        return None
    return cast("dict[str, object]", raw)


def read_reserved_count(root: pathlib.Path, key: str) -> int | None:
    """Return the count *key* claims in *root*'s published code sidecar.

    ``None`` when the sidecar is absent, unreadable, or silent on that key.
    Every such case is a "cannot tell" rather than a claim of zero, so a caller
    cannot mistake an unreadable sidecar for a destroyed index.
    """
    raw = _read_meta(root)
    return None if raw is None else parse_reserved_count(raw, key)


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
    published = read_reserved_count(root, PUBLISHED_POINTS_KEY)
    if published is None or live_count >= published:
        return None
    return BreadthShortfall(published=published, live=live_count)


def code_file_breadth_shortfall(
    root: pathlib.Path,
) -> FileBreadthShortfall | None:
    """Return the file-breadth shortfall *root*'s sidecar admits to, or ``None``.

    Compares two figures the sidecar already carries: how many files it names as
    indexed, and how many distinct files the collection actually held points for
    when that publication was written. Both come from one read, so this costs a
    single file parse and no query - which is why it is affordable on a search
    path where counting distinct paths in the collection would not be.

    This is the comparison a point count cannot express. A publication that
    covers a fraction of the files it names still writes a self-consistent point
    count, because the count it stamps is the fragment's own. Only the file
    figures disagree.

    ``None`` covers "complete" and "cannot tell" alike: a sidecar written before
    this key existed has nothing to compare against and must not be reported as
    incomplete for that reason.
    """
    raw = _read_meta(root)
    if raw is None:
        return None
    covered = parse_reserved_count(raw, PUBLISHED_FILES_KEY)
    if covered is None:
        return None
    named = sum(1 for key in raw if not key.startswith("__"))
    if covered >= named:
        return None
    return FileBreadthShortfall(named=named, covered=covered)
