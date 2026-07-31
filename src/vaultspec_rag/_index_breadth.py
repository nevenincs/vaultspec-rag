"""How much breadth a published index claims, and where that claim lives.

A neutral leaf shared by the indexers that write the claims and the search
path that checks them. It exists as its own module so neither side has to
import the other: the writers live behind the tree-sitter-bearing indexer
package, while the reader sits on a search path that is deliberately
model-free and must stay importable on a host with no GPU.

A claim is a point count recorded when an index publishes, taken after storage
reconciliation so it is exactly the breadth the sidecar describes. Without it
a truncated collection is indistinguishable from a small one - the entries
name which paths or documents are indexed, but nothing says how many points
that should amount to, so a collection holding a fraction of its corpus reads
as intact and answers searches as though it were whole.

Two sidecars are covered, because both are flat key-to-hash maps whose
reserved keys begin with ``__``: the code sidecar keyed by relative file path,
and the vault sidecar keyed by document stem. They keep separate key names so
one domain's figure can never be read as the other's, and share one parser so
"cannot tell" means the same thing on both.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Literal, NamedTuple, cast

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Mapping

from ._operator_commands import IndexCommandOptions, index_command
from ._source_types import PublicSourceType
from ._store_writes import workspace_volume_path

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

#: Reserved sidecar key naming the generation whose publication wrote the
#: sidecar. Lives here rather than behind the indexer package because the
#: serve path reads it as evidence beside the published counts: a breadth
#: verdict that names the claiming generation lets an operator tie the figures
#: to one publication.
GENERATION_ID_KEY = "__code_generation_id__"

#: Reserved vault-sidecar key carrying the published point count. Named apart
#: from the code key so a sidecar of one domain can never be read as the
#: other's, and prefixed with ``__`` so it stays out of the document-id set
#: arithmetic the vault sidecar's other keys take part in.
VAULT_PUBLISHED_POINTS_KEY = "__vault_published_points__"

#: Reserved vault-sidecar key carrying the number of distinct documents the
#: collection held points for when the publication was written. Recorded
#: beside the point count for the same reason the code side records its file
#: figure: the two fail independently, and a plausible number of points spread
#: across a fraction of the documents the sidecar names is invisible to any
#: comparison of point counts.
VAULT_PUBLISHED_DOCUMENTS_KEY = "__vault_published_documents__"

__all__ = [
    "GENERATION_ID_KEY",
    "PUBLISHED_FILES_KEY",
    "PUBLISHED_POINTS_KEY",
    "SHORTFALL_CONSEQUENCE",
    "SHORTFALL_REMEDIATION",
    "VAULT_PUBLISHED_DOCUMENTS_KEY",
    "VAULT_PUBLISHED_POINTS_KEY",
    "BreadthShortfall",
    "CodeBreadthClaim",
    "FileBreadthShortfall",
    "ShortfallWarning",
    "VaultBreadthClaim",
    "code_breadth_shortfall",
    "code_file_breadth_shortfall",
    "index_meta_path",
    "parse_reserved_count",
    "read_code_breadth_claim",
    "read_reserved_count",
    "read_vault_breadth_claim",
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

    Both kinds are read here, in one pass, because that is the property worth
    holding: a surface that renders this list cannot report one kind and stay
    silent on the other. The two are independent - a publication covering a
    fraction of the files it names still stamps a self-consistent point count,
    so the file deficit fires exactly where the point deficit cannot - and a
    consumer that walked only the key it happened to know about would go quiet
    on the case the other key exists for.
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
    files = _shortfall_figures(index_state, "file_shortfall")
    if files is not None:
        warnings.append(
            ShortfallWarning(
                deficit=(
                    f"this index names {files.get('named_count')} files but "
                    f"holds content for only {files.get('covered_count')}"
                ),
                missing=f"{files.get('missing_count')} are missing",
                why="A file absent from the index cannot be found by any query",
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
        logger.debug("unusable %s %r in index sidecar", key, value)
        return None
    try:
        count = int(value)
    except ValueError:
        logger.debug("unusable %s %r in index sidecar", key, value)
        return None
    return count if count >= 0 else None


def _named_entry_count(raw: Mapping[str, object]) -> int:
    """Return how many corpus entries a sidecar mapping names.

    Reserved keys begin with ``__`` precisely so they can be excluded here:
    every remaining key is one relative file path or one document stem the
    publication declares indexed.
    """
    return sum(1 for key in raw if not key.startswith("__"))


def index_meta_path(
    root: pathlib.Path,
    source: Literal[PublicSourceType.CODE, PublicSourceType.VAULT],
) -> pathlib.Path:
    """Return the index metadata sidecar path *source* publishes under *root*.

    Both sidecars sit in the same data directory and differ only in which
    configured filename names them, so they resolve here rather than through a
    function each: two bodies differing by one constant is one rename away from
    a caller reading the wrong domain's claim as its own.

    The parameter is narrowed to the two sources this module covers. The wider
    source vocabulary includes selections with no sidecar of this shape, and
    accepting them would buy a runtime rejection where the type already says
    the call cannot be written.

    Only the filename is decided here. Which directory a root's own index
    bookkeeping lives in is one question with one answer, so it is asked of the
    volume resolver every other writer into that directory asks.
    """
    from .config._settings import get_config

    cfg = get_config()
    filename = (
        cfg.code_index_metadata_file
        if source is PublicSourceType.CODE
        else cfg.index_metadata_file
    )
    return workspace_volume_path(root) / filename


def _read_sidecar(path: pathlib.Path) -> dict[str, object] | None:
    """Return the parsed sidecar at *path*, or ``None`` when it cannot be read.

    One reader, so a caller needing both a reserved count and the corpus
    entries pays a single parse and cannot observe the two halves from
    different reads of a file another process is replacing.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("index sidecar %s unreadable: %s", path, exc)
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
    raw = _read_sidecar(index_meta_path(root, PublicSourceType.CODE))
    return None if raw is None else parse_reserved_count(raw, key)


class CodeBreadthClaim(NamedTuple):
    """What one code publication claims, read from the sidecar in one parse.

    ``published_points`` is ``None`` when the sidecar predates the key or
    carries an unusable value; ``generation_id`` is ``None`` on the same
    terms. Both are "cannot tell", never a claim of zero.

    ``named_files`` is how many indexed paths the same sidecar lists. It is
    carried alongside the point figure because the two together say something
    neither says alone: a publication counts the collection after storage
    reconciliation, so a point claim of zero over a non-zero number of named
    files is a manifest contradicting itself rather than a manifest that
    happens to describe an empty index.

    ``published_files`` is how many distinct files that publication found the
    collection holding content for. ``None`` means the key is absent - an
    older build that never recorded coverage - which is ignorance and must
    never be read as a claim of zero. A recorded zero is the opposite: a
    publication actively stating it covered nothing.
    """

    published_points: int | None
    generation_id: str | None
    named_files: int = 0
    published_files: int | None = None


def read_code_breadth_claim(root: pathlib.Path) -> CodeBreadthClaim | None:
    """Return *root*'s published code breadth claim, or ``None`` for no sidecar.

    One parse for every figure, so a caller can never observe the count, the
    named files, and the generation from different reads of a file another
    process is replacing - they always describe a single publication.
    """
    raw = _read_sidecar(index_meta_path(root, PublicSourceType.CODE))
    if raw is None:
        return None
    generation = raw.get(GENERATION_ID_KEY)
    return CodeBreadthClaim(
        published_points=parse_reserved_count(raw, PUBLISHED_POINTS_KEY),
        generation_id=(
            generation if isinstance(generation, str) and generation else None
        ),
        named_files=sum(1 for key in raw if not key.startswith("__")),
        published_files=parse_reserved_count(raw, PUBLISHED_FILES_KEY),
    )


class VaultBreadthClaim(NamedTuple):
    """What one vault publication claims, read from the sidecar in one parse.

    ``published_points`` and ``published_documents`` are ``None`` when the
    sidecar predates the key or carries an unusable value - "cannot tell",
    never a claim of zero, so a root written by an older build is neither
    escalated nor quietly promoted to healthy. ``named_documents`` is the
    count of document entries the same sidecar carries, and is a plain figure
    rather than an optional: an entry is either there or it is not.

    All three come from one parse, so a caller can never observe them from
    different reads of a file another process is replacing - they always
    describe a single publication.

    The vault publication carries no generation identity: it replaces its
    collection in place rather than building a generation beside the served
    one, so there is no second name a claim could be tied to.
    """

    published_points: int | None
    published_documents: int | None
    named_documents: int


def read_vault_breadth_claim(root: pathlib.Path) -> VaultBreadthClaim | None:
    """Return *root*'s published vault breadth claim, or ``None`` for no sidecar.

    The two published figures fail independently, which is why both are read
    here rather than one standing in for the other: a collection can hold a
    plausible number of points spread across a fraction of the documents the
    same sidecar names, and only the document figures disagree in that case.
    """
    raw = _read_sidecar(index_meta_path(root, PublicSourceType.VAULT))
    if raw is None:
        return None
    return VaultBreadthClaim(
        published_points=parse_reserved_count(raw, VAULT_PUBLISHED_POINTS_KEY),
        published_documents=parse_reserved_count(raw, VAULT_PUBLISHED_DOCUMENTS_KEY),
        named_documents=_named_entry_count(raw),
    )


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
    raw = _read_sidecar(index_meta_path(root, PublicSourceType.CODE))
    if raw is None:
        return None
    covered = parse_reserved_count(raw, PUBLISHED_FILES_KEY)
    if covered is None:
        return None
    named = _named_entry_count(raw)
    if covered >= named:
        return None
    return FileBreadthShortfall(named=named, covered=covered)
