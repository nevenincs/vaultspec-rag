"""Serve-time reconciliation of a collection's breadth against its published claim.

A collection can silently lose most of its points and keep answering queries
as though it were whole: every remaining point is valid, so searches succeed,
health stays green, and the only symptom is results that quietly stopped
covering the corpus. This module is the invariant that stands between that
state and a confident response: at serve time the collection's actual breadth
must be reconcilable with what its publication claimed, and unexplained
shrinkage degrades loudly - the search still serves, but the response says the
index is short and an operator-facing ERROR names the figures.

One implementation, service-domain: the daemon route and the command line both
call :func:`evaluate_index_integrity` and render whatever it returns, so no
entry point can classify the same collection differently. The verdict is a
tri-state, and the third state is the honest one: ``unverifiable`` says "there
is no claim to check against", never "fine" and never "shrunken", so a root
written by a build that recorded no breadth is neither escalated nor quietly
promoted to healthy.

Cheapness is a contract: the live count is the one the search path already
took for its empty-index short-circuit, so the check adds no store round trip.
The claim is a small local sidecar parse, cached per root and domain for a
short TTL so bursty search traffic pays one parse per window rather than one
per query. A claim that cannot be read is ``unverifiable``, not an error - the
check must never make a search fail or wait.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Literal, NamedTuple

from ._source_types import PublicSourceType

if TYPE_CHECKING:
    import pathlib

logger = logging.getLogger(__name__)

__all__ = [
    "MANIFEST_CLAIM_TTL_SECONDS",
    "REASON_COUNT_UNAVAILABLE",
    "REASON_FILE_COVERAGE_SHORTFALL",
    "REASON_MANIFEST_INCOMPLETE",
    "REASON_NO_CLAIM",
    "REASON_NO_MANIFEST",
    "REASON_ZERO_CLAIM_OVER_NAMED_FILES",
    "SHRUNKEN_LOG_INTERVAL_SECONDS",
    "VERDICT_CONSISTENT",
    "VERDICT_SHRUNKEN",
    "VERDICT_UNVERIFIABLE",
    "IndexIntegrity",
    "evaluate_index_integrity",
]

IntegrityVerdict = Literal["consistent", "shrunken", "unverifiable"]

VERDICT_CONSISTENT: IntegrityVerdict = "consistent"
VERDICT_SHRUNKEN: IntegrityVerdict = "shrunken"
VERDICT_UNVERIFIABLE: IntegrityVerdict = "unverifiable"

#: No sidecar for the domain, or one that could not be read or parsed. Says
#: nothing about the collection: an unreadable manifest is ignorance, not loss.
REASON_NO_MANIFEST = "no_manifest"

#: A manifest exists but records no breadth figure - a sidecar written by an
#: older build, or a domain whose publication has never carried one (the vault
#: sidecar records document hashes and layout epochs, no point figure).
REASON_NO_CLAIM = "no_claim"

#: The caller had no live count to compare - the count call failed or the
#: figure never reached the envelope site. Degraded, never fatal: a count that
#: could not be taken proves nothing about the collection either way.
REASON_COUNT_UNAVAILABLE = "count_unavailable"

#: The manifest says of itself that it does not describe a complete
#: publication, so its point figure is not a breadth claim to hold the
#: collection to.
REASON_MANIFEST_INCOMPLETE = "manifest_incomplete"

#: The manifest names indexed files but claims zero points for them. Not
#: ignorance - a publication counts the collection after storage
#: reconciliation, so a complete one over N named files cannot record zero.
#: The manifest is contradicting itself, and the collection it describes
#: cannot be serving those files however many points it currently holds.
REASON_ZERO_CLAIM_OVER_NAMED_FILES = "zero_claim_over_named_files"

#: The manifest records covering fewer files than it names. Two figures from
#: one publication disagreeing, which no comparison of point counts can see:
#: a publication covering a fraction of its named files still stamps a
#: self-consistent point total, because the total it stamps is the fragment's.
#: An ABSENT coverage figure is not this case and never reaches here - that is
#: an older build having recorded nothing, and ignorance never escalates.
REASON_FILE_COVERAGE_SHORTFALL = "file_coverage_shortfall"

#: How long one parsed claim answers for its root and domain before the
#: sidecar is read again. Five seconds bounds the added cost to one small
#: local-file parse per domain per window under bursty search traffic, while a
#: republication (which changes the claim) is honoured within seconds.
#: Correctness never rests on this cache: the live count is fresh on every
#: search, so a real shrink is visible immediately against the cached claim -
#: only the claim itself can be this stale, and a stale claim can only ever be
#: the previous publication's.
MANIFEST_CLAIM_TTL_SECONDS = 5.0

#: Minimum spacing between ERROR lines for one root and domain. The response
#: envelope carries the verdict on every single search, so the log line exists
#: for an operator tailing logs, not as the transport: one line per minute per
#: domain keeps the signal without letting a busy agent loop write one line
#: per query.
SHRUNKEN_LOG_INTERVAL_SECONDS = 60.0

#: Hard ceiling on remembered roots. A daemon serves a bounded registry of
#: roots, so this is never reached in practice; it exists so a pathological
#: caller cycling through roots cannot grow the two dicts without bound.
_CACHE_MAX_ENTRIES = 512

_STATE_LOCK = threading.Lock()
_CLAIM_CACHE: dict[tuple[str, str], tuple[float, _BreadthClaim]] = {}
_ERROR_LAST_EMIT: dict[tuple[str, str], float] = {}


class _BreadthClaim(NamedTuple):
    """What one domain's publication claims, or why it claims nothing."""

    claimed: int | None
    generation_id: str | None
    reason: str | None
    """Why ``claimed`` is ``None``; ``None`` itself when a claim is present."""

    named_files: int = 0
    """How many indexed files the same manifest names, ``0`` when unknown."""

    covered_files: int | None = None
    """How many the publication recorded covering; ``None`` when unrecorded."""

    def self_contradiction(self) -> str | None:
        """Return why this manifest disagrees with itself, or ``None``.

        Both readings are about one publication's own figures, so neither
        needs a live count and neither can be satisfied by one. They are
        checked here rather than at the comparison so a manifest that already
        admits it describes an incomplete index is never handed to a test that
        an empty collection would pass.
        """
        if not self.named_files:
            return None
        if self.claimed == 0:
            return REASON_ZERO_CLAIM_OVER_NAMED_FILES
        if self.covered_files is not None and self.covered_files < self.named_files:
            return REASON_FILE_COVERAGE_SHORTFALL
        return None


class IndexIntegrity(NamedTuple):
    """One serve-time breadth verdict, with the evidence that produced it.

    Constructed only by :func:`evaluate_index_integrity`, so a consumer never
    compares figures for itself - the verdict is the conclusion.
    """

    verdict: IntegrityVerdict
    source: str
    claimed_count: int | None
    live_count: int | None
    generation_id: str | None
    reason: str | None
    named_files: int | None = None
    """Indexed files the manifest names, ``None`` where the domain has none."""
    covered_files: int | None = None
    """Files the publication recorded covering, ``None`` when unrecorded."""

    def as_block(self) -> dict[str, object]:
        """Return the canonical ``index_integrity`` envelope block.

        One projection for every surface. The block is emitted whenever the
        serving path evaluated the check - ``consistent`` included - so a
        consumer can tell "checked and fine" from "surface predates the
        check", where the block is absent entirely. Unknown figures are
        ``null``, never invented; ``missing_count`` appears only over a
        demonstrated point deficit, mirroring how the shortfall block never
        renders a zero deficit - a manifest judged shrunken for contradicting
        itself has no point deficit to name, and subtracting its figures would
        print a zero or a negative one. ``named_files`` appears only where the
        manifest names any, so a domain that records no file list renders no
        figure for one.
        """
        block: dict[str, object] = {
            "verdict": self.verdict,
            "source": self.source,
            "claimed_count": self.claimed_count,
            "live_count": self.live_count,
            "generation_id": self.generation_id,
            "reason": self.reason,
        }
        if self.named_files:
            block["named_files"] = self.named_files
            block["covered_files"] = self.covered_files
        if (
            self.verdict == VERDICT_SHRUNKEN
            and self.claimed_count is not None
            and self.live_count is not None
            and self.claimed_count > self.live_count
        ):
            block["missing_count"] = self.claimed_count - self.live_count
        return block


def _read_code_claim(root: pathlib.Path) -> _BreadthClaim:
    """Return the code publication's breadth claim for *root*."""
    from ._index_breadth import read_code_breadth_claim

    claim = read_code_breadth_claim(root)
    if claim is None:
        return _BreadthClaim(None, None, REASON_NO_MANIFEST)
    if claim.published_points is None:
        return _BreadthClaim(
            None,
            claim.generation_id,
            REASON_NO_CLAIM,
            claim.named_files,
            claim.published_files,
        )
    return _BreadthClaim(
        claim.published_points,
        claim.generation_id,
        None,
        claim.named_files,
        claim.published_files,
    )


def _read_document_claim(root: pathlib.Path) -> _BreadthClaim:
    """Return the document publication's breadth claim for *root*.

    The document sidecar names every published point id per file, so the claim
    is the sum of those - exact for the generation that published it, because
    the manifest is written atomically from ledger evidence after storage
    reconciliation. A manifest that declares itself incomplete is not held
    against the collection: it says so precisely because its figures do not
    describe a whole publication.
    """
    from .indexer._document_meta import (
        DocumentMetadataError,
        document_metadata_path,
        read_document_meta,
    )

    try:
        meta = read_document_meta(document_metadata_path(root))
    except DocumentMetadataError:
        return _BreadthClaim(None, None, REASON_NO_MANIFEST)
    if meta is None:
        return _BreadthClaim(None, None, REASON_NO_MANIFEST)
    if not meta.complete:
        return _BreadthClaim(None, meta.generation_id, REASON_MANIFEST_INCOMPLETE)
    return _BreadthClaim(meta.claimed_points, meta.generation_id, None)


def _read_vault_claim(root: pathlib.Path) -> _BreadthClaim:
    """Return the vault domain's breadth claim: honestly, there is none.

    The vault sidecar records per-document content hashes and layout epochs
    but no point figure, so there is no claim to reconcile a live count
    against. Reporting ``unverifiable`` here is the point of the tri-state:
    inventing a claim from the document-hash entries would count documents
    against a collection that stores one point per chunk, and a fabricated
    comparison is worse than an honest "cannot tell".
    """
    del root
    return _BreadthClaim(None, None, REASON_NO_CLAIM)


_CLAIM_READERS = {
    PublicSourceType.CODE: _read_code_claim,
    PublicSourceType.DOCUMENT: _read_document_claim,
    PublicSourceType.VAULT: _read_vault_claim,
}


def _cached_claim(
    root: pathlib.Path,
    source: PublicSourceType,
    ttl_seconds: float,
) -> _BreadthClaim:
    """Return the claim for one root and domain, re-reading at most per TTL.

    The cache records when each claim was read and the caller's TTL decides
    staleness at lookup, so a caller passing a tighter TTL forces a fresh
    parse rather than inheriting the freshness a previous caller chose.
    """
    key = (str(root), source.value)
    now = time.monotonic()
    with _STATE_LOCK:
        cached = _CLAIM_CACHE.get(key)
        if cached is not None and now - cached[0] < ttl_seconds:
            return cached[1]
    claim = _CLAIM_READERS[source](root)
    with _STATE_LOCK:
        if len(_CLAIM_CACHE) >= _CACHE_MAX_ENTRIES:
            _CLAIM_CACHE.clear()
        _CLAIM_CACHE[key] = (now, claim)
    return claim


def _log_shrunken(root: pathlib.Path, integrity: IndexIntegrity) -> None:
    """Emit the operator-facing ERROR for a demonstrated shrink, rate-limited."""
    key = (str(root), integrity.source)
    now = time.monotonic()
    with _STATE_LOCK:
        last = _ERROR_LAST_EMIT.get(key)
        if last is not None and now - last < SHRUNKEN_LOG_INTERVAL_SECONDS:
            return
        if len(_ERROR_LAST_EMIT) >= _CACHE_MAX_ENTRIES:
            _ERROR_LAST_EMIT.clear()
        _ERROR_LAST_EMIT[key] = now
    if integrity.reason in (
        REASON_ZERO_CLAIM_OVER_NAMED_FILES,
        REASON_FILE_COVERAGE_SHORTFALL,
    ):
        # A points-held-of-points-claimed line would read "0 of 0" here and
        # send an operator looking for a deficit that is not what went wrong.
        logger.error(
            "%s publication (generation %s) for %s names %s indexed file(s) "
            "but records covering only %s of them; searches still serve but "
            "no result can be drawn from the rest",
            integrity.source,
            integrity.generation_id,
            root,
            integrity.named_files,
            integrity.covered_files,
        )
        return
    logger.error(
        "%s collection for %s holds %s of the %s points its publication "
        "(generation %s) claims; searches still serve but results are drawn "
        "from an incomplete index",
        integrity.source,
        root,
        integrity.live_count,
        integrity.claimed_count,
        integrity.generation_id,
    )


def evaluate_index_integrity(
    root: pathlib.Path,
    source: PublicSourceType,
    live_count: int | None,
    *,
    claim_ttl_seconds: float = MANIFEST_CLAIM_TTL_SECONDS,
) -> IndexIntegrity:
    """Reconcile *source*'s live breadth for *root* against its published claim.

    ``live_count`` is the count the search path already took for its
    empty-index short-circuit - supplied, never re-counted, which is what
    keeps this affordable on every query. ``None`` means the caller had no
    count, and that is ``unverifiable``: degraded, never fatal.

    The comparison is exact and one-sided, no tolerance. Every publication
    counts the store immediately after storage reconciliation and writes the
    figure atomically with the generation it describes - for a rebuilt
    generation the sidecar lands before the served pointer moves, and an
    in-place incremental republishes the figure at the same protected commit
    edge that performs its deletions - so a complete served collection always
    reads back at least its claim. A count above the claim is the legitimate
    motion of an in-flight incremental whose upserts land ahead of its
    republication; a count below it is either demonstrated loss or a
    publication torn mid-replacement, and both deserve the loud verdict. Any
    tolerance wider than zero would mask exactly a loss of that size.

    Some manifests are judged without comparing counts at all, because they
    already disagree with themselves: zero points, or a recorded file
    coverage below the file count, over a manifest that names indexed files.
    Neither pair can be produced by a complete publication, which counts the
    collection after storage reconciliation and records what it found, so
    neither is the "no information" case ``unverifiable`` exists for - the
    manifest is stating a figure and contradicting it in the same breath. A
    zero point claim left to the count comparison would read ``consistent``
    against any live count at all, most perversely against an empty
    collection, and latch there: a claim of zero is satisfied forever, so
    nothing would ever escalate and nothing would ever repair. ``shrunken``
    is both the honest reading and the one the self-heal path acts on.

    An ABSENT figure is the opposite and stays ``unverifiable``: a build that
    never recorded coverage has told us nothing, and escalating on that would
    rebuild every root written before the key existed.

    A ``shrunken`` verdict never blocks the search - partial results beat no
    results - but it is attached to the response and logged at ERROR with the
    figures and the claiming generation, rate-limited per root and domain.
    """
    if source not in _CLAIM_READERS:
        raise ValueError(f"no per-domain breadth claim exists for {source!r}")
    claim = _cached_claim(root, source, claim_ttl_seconds)
    if live_count is None:
        integrity = IndexIntegrity(
            verdict=VERDICT_UNVERIFIABLE,
            source=source.value,
            claimed_count=claim.claimed,
            live_count=None,
            generation_id=claim.generation_id,
            reason=REASON_COUNT_UNAVAILABLE,
            named_files=claim.named_files or None,
        )
    elif claim.claimed is None:
        integrity = IndexIntegrity(
            verdict=VERDICT_UNVERIFIABLE,
            source=source.value,
            claimed_count=None,
            live_count=live_count,
            generation_id=claim.generation_id,
            reason=claim.reason,
            named_files=claim.named_files or None,
        )
    elif (contradiction := claim.self_contradiction()) is not None:
        integrity = IndexIntegrity(
            verdict=VERDICT_SHRUNKEN,
            source=source.value,
            claimed_count=claim.claimed,
            live_count=live_count,
            generation_id=claim.generation_id,
            reason=contradiction,
            named_files=claim.named_files,
            covered_files=claim.covered_files,
        )
        _log_shrunken(root, integrity)
    elif live_count >= claim.claimed:
        integrity = IndexIntegrity(
            verdict=VERDICT_CONSISTENT,
            source=source.value,
            claimed_count=claim.claimed,
            live_count=live_count,
            generation_id=claim.generation_id,
            reason=None,
            named_files=claim.named_files or None,
        )
    else:
        integrity = IndexIntegrity(
            verdict=VERDICT_SHRUNKEN,
            source=source.value,
            claimed_count=claim.claimed,
            live_count=live_count,
            generation_id=claim.generation_id,
            reason=None,
            named_files=claim.named_files or None,
        )
        _log_shrunken(root, integrity)
    return integrity
