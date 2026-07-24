"""Encode-seam donor vector reuse: adopt stored vectors instead of re-encoding.

One indexing run resolves at most one :class:`DonorReuseContext` (donor
discovery and eligibility are per-run decisions, never per-slice), and the
encode seam consults it before every slice encode: the slice's string point
ids are looked up in the eligible donor collections in rank order, each
fetched point's stored payload content is compared byte-for-byte against the
chunk content this run would store, and only verified hits adopt the donor's
dense and sparse vectors. Everything else - misses, verify failures, donor
read errors - degrades to the ordinary GPU encode. Payloads are always
rebuilt locally; vectors are the only thing reused.

Threading and GPU discipline: every donor call runs on the calling consumer
thread, strictly outside ``gpu_lock``; this module never imports torch and
never spawns a thread.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .._store_models import CodeChunk, DocumentChunk, VaultChunk
from ._donor_candidates import (
    CollectionKind,
    discover_donor_candidates,
    evaluate_donor_eligibility,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ..store import DonorPoint, VaultStore

logger = logging.getLogger(__name__)

__all__ = [
    "FALLBACK_ENCODE_SECONDS_PER_CHUNK",
    "DonorReuseContext",
    "ReuseStats",
    "resolve_donor_reuse",
]

#: Per-chunk encode-cost estimate used for the saved-GPU-seconds telemetry
#: when a run adopted every point and therefore produced no same-job encode
#: timing to derive the real rate from. Deliberately conservative (measured
#: rebuild-class jobs on the reference GPU average several times this per
#: chunk), and telemetry-only: no correctness decision reads it.
FALLBACK_ENCODE_SECONDS_PER_CHUNK = 0.02


@dataclass(slots=True)
class ReuseStats:
    """Mutable per-job reuse accounting, snapshotted into the job record.

    ``encode_seconds``/``encoded_chunks`` accumulate the run's own miss-encode
    timing so ``gpu_seconds_saved`` is derived from this job's measured
    per-chunk cost whenever at least one miss was encoded.
    """

    reuse_hits: int = 0
    reuse_misses: int = 0
    donor_absent: bool = False
    donor_collections: tuple[str, ...] = ()
    encode_seconds: float = 0.0
    encoded_chunks: int = 0

    def record_encode(self, seconds: float, chunks: int) -> None:
        """Accumulate one measured miss-encode span."""
        if chunks > 0 and seconds >= 0.0:
            self.encode_seconds += seconds
            self.encoded_chunks += chunks

    @property
    def hit_rate(self) -> float:
        """Fraction of consulted points served from a donor (0.0 when none)."""
        consulted = self.reuse_hits + self.reuse_misses
        return self.reuse_hits / consulted if consulted else 0.0

    @property
    def gpu_seconds_saved(self) -> float:
        """Estimated encode time the adopted vectors avoided."""
        if self.encoded_chunks > 0:
            per_chunk = self.encode_seconds / self.encoded_chunks
        else:
            per_chunk = FALLBACK_ENCODE_SECONDS_PER_CHUNK
        return self.reuse_hits * per_chunk

    def snapshot(self) -> dict[str, object]:
        """Return the JSON-ready per-job telemetry block."""
        return {
            "reuse_hits": self.reuse_hits,
            "reuse_misses": self.reuse_misses,
            "hit_rate": round(self.hit_rate, 4),
            "gpu_seconds_saved": round(self.gpu_seconds_saved, 3),
            "donor_absent": self.donor_absent,
            "donor_collections": list(self.donor_collections),
        }


def _chunk_point_identity(
    chunk: CodeChunk | DocumentChunk | VaultChunk,
) -> tuple[str, str]:
    """Return one chunk's (string point id, expected stored content) pair.

    Must mirror the store's upsert identity and payload exactly: code chunks
    key on ``chunk.id`` and store ``chunk.content``; vault chunks key on
    ``chunk.point_key`` and store ``chunk.text`` as the payload ``content``
    field; document chunks key on ``chunk.id`` and store
    ``chunk.payload.content``. Any drift here makes reuse verification fail
    (a hit-rate regression), never adopt a wrong vector - adoption still
    requires the stored content to equal this expected string.
    """
    if isinstance(chunk, CodeChunk):
        return chunk.id, chunk.content
    if isinstance(chunk, VaultChunk):
        return chunk.point_key, chunk.text
    return chunk.id, chunk.payload.content


def _verify_and_adopt(
    chunk: CodeChunk | DocumentChunk | VaultChunk,
    point: DonorPoint,
    expected_content: str,
    *,
    sparse_required: bool,
) -> bool:
    """Verify one donor point against a chunk and adopt its vectors on a hit.

    A hit requires the stored payload ``content`` to equal *expected_content*
    byte-for-byte AND (when the run writes sparse vectors) the donor point to
    carry a sparse vector. On a hit the chunk's dense and sparse vector fields
    are overwritten and ``True`` is returned; otherwise the chunk is left
    untouched and ``False`` is returned.
    """
    payload_content = point.payload.get("content")
    if not isinstance(payload_content, str) or payload_content != expected_content:
        # Same point id, different stored bytes: the id scheme's residual
        # collision/staleness risk lands here and MUST read as a miss, never
        # an adoption.
        return False
    if sparse_required and (
        point.sparse_indices is None or point.sparse_values is None
    ):
        return False
    chunk.vector = list(point.dense)
    if sparse_required and point.sparse_indices is not None:
        chunk.sparse_indices = list(point.sparse_indices)
        chunk.sparse_values = list(point.sparse_values or [])
    else:
        chunk.sparse_indices = []
        chunk.sparse_values = []
    return True


@dataclass(slots=True)
class DonorReuseContext:
    """One run's resolved donor set plus its accounting.

    ``donor_collections`` is the consultation order (first verified hit
    wins per point). The context performs read-only store calls and chunk
    vector-field writes; it never encodes, upserts, or touches the GPU.
    """

    store: VaultStore
    donor_collections: tuple[str, ...]
    stats: ReuseStats = field(default_factory=ReuseStats)

    def adopt_verified_vectors(
        self,
        chunks: Sequence[CodeChunk | DocumentChunk | VaultChunk],
        *,
        sparse_required: bool,
    ) -> list[bool]:
        """Adopt donor vectors onto verified hits; return the per-chunk mask.

        A point is a hit only when a donor stores it under the identical
        string id AND its stored payload ``content`` equals the chunk's
        expected content byte-for-byte AND (when this run writes sparse
        vectors) the donor point carries a sparse vector. Everything else,
        including a donor read failure, stays a miss for the caller to
        encode. The returned mask is index-aligned with ``chunks``.
        """
        identities = [_chunk_point_identity(chunk) for chunk in chunks]
        adopted = [False] * len(chunks)
        remaining: dict[str, int] = {}
        for index, (chunk_id, _content) in enumerate(identities):
            remaining.setdefault(chunk_id, index)
        for collection in self.donor_collections:
            if not remaining:
                break
            self._adopt_from_collection(
                collection,
                chunks,
                identities,
                remaining,
                adopted,
                sparse_required=sparse_required,
            )
        hits = sum(adopted)
        self.stats.reuse_hits += hits
        self.stats.reuse_misses += len(chunks) - hits
        return adopted

    def _adopt_from_collection(
        self,
        collection: str,
        chunks: Sequence[CodeChunk | DocumentChunk | VaultChunk],
        identities: Sequence[tuple[str, str]],
        remaining: dict[str, int],
        adopted: list[bool],
        *,
        sparse_required: bool,
    ) -> None:
        """Consult one donor collection, adopting each verified hit in place.

        Reads the still-outstanding ids from *collection* in a single batch;
        a read failure is logged and degrades every outstanding id to a miss
        (the caller encodes them). Each verified hit clears its id from
        *remaining* and flips its index in *adopted*.
        """
        try:
            found = self.store.retrieve_donor_points(collection, list(remaining))
        except Exception:
            logger.warning(
                "Donor read against %s failed; encoding its misses instead",
                collection,
                exc_info=True,
            )
            return
        for chunk_id, point in found.items():
            index = remaining.get(chunk_id)
            if index is None:
                continue
            if _verify_and_adopt(
                chunks[index],
                point,
                identities[index][1],
                sparse_required=sparse_required,
            ):
                adopted[index] = True
                del remaining[chunk_id]


def resolve_donor_reuse(
    root: Path,
    kind: CollectionKind,
    store: VaultStore,
    *,
    expected_content_epoch: str,
) -> tuple[ReuseStats | None, DonorReuseContext | None]:
    """Resolve one run's donor context, exactly once per index run.

    Returns ``(None, None)`` when the reuse knob is off - the baseline path,
    with no donor consultation and no telemetry block on the job record.
    When the knob is on, the stats object is always returned so the job
    records reuse accounting even when no eligible donor exists
    (``donor_absent``); the context is ``None`` in that case.

    Discovery and every eligibility gate fail closed: any error here
    degrades to "no donors" and can never fail the indexing job.
    """
    from ..config import get_config

    if not bool(get_config().index_reuse_enabled):
        return None, None
    stats = ReuseStats()
    backend = "server" if get_config().effective_server_mode() else "local"
    try:
        candidates = discover_donor_candidates(root, kind, backend=backend)
    except Exception:
        logger.warning("Donor discovery failed; indexing without reuse", exc_info=True)
        stats.donor_absent = True
        return stats, None
    eligible: list[str] = []
    for candidate in candidates:
        try:
            verdict = evaluate_donor_eligibility(
                candidate,
                kind=kind,
                expected_content_epoch=expected_content_epoch,
            )
        except Exception:
            logger.warning(
                "Donor eligibility check failed for %s; skipping it",
                candidate.collection,
                exc_info=True,
            )
            continue
        if not verdict.eligible:
            logger.debug(
                "Donor %s ineligible: %s",
                candidate.collection,
                ",".join(reason.value for reason in verdict.reasons),
            )
            continue
        if not store.supports_donor_reads(candidate.collection):
            continue
        eligible.append(candidate.collection)
    if not eligible:
        stats.donor_absent = True
        return stats, None
    stats.donor_collections = tuple(eligible)
    return stats, DonorReuseContext(
        store=store,
        donor_collections=tuple(eligible),
        stats=stats,
    )
