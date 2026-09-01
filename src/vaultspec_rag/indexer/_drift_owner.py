"""Sole ownership of code paths whose source moves during a run.

A resumed generation carries the indexed paths of the attempt that failed.
Any of those whose source has changed since cannot be recognised as already
committed, because commit-unit identity binds the source digest, and cannot be
written over an indexed path either. Something has to notice and repair that,
and this module is the only thing that does.

Two instants need the repair, and they differ only in which points are stale:

- Before dispatch, over a digest snapshot. Nothing fresh has been written yet,
  so every point storage holds for the path belongs to the superseded content.
- At record time, after the fresh content is already in storage. Here only the
  points the superseded units still claim may be dropped; the replacement
  points are already present and must survive.

Both converge on one private supersede, which is where the ordering that makes
either safe is enforced.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._run_ledger_models import RunLedgerIndexedPathCollisionError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..store_runtime import VaultStore
    from ._run_checkpoint import CodeRunCheckpoint
    from ._streaming_types import CodeFileSegment

__all__ = [
    "DEFAULT_DRIFT_RETRY_BUDGET",
    "CodeDriftOwner",
]

logger = logging.getLogger(__name__)

#: How many times one path may be superseded while its units are being
#: recorded, within a single run, before it is left to the next generation. A
#: path needs one supersede to absorb an ordinary resumed edit; needing several
#: means it is being rewritten faster than the run can record it, and retrying
#: without a bound would trade a stale path for a run that never terminates.
DEFAULT_DRIFT_RETRY_BUDGET = 3


class CodeDriftOwner:
    """Decides, supersedes, and re-records one code generation's drift.

    Holds the drop-points-then-remove-units ordering as a property of the type
    rather than a convention: every route into a supersede goes through
    :meth:`_supersede`, so no caller is in a position to get the order wrong.
    """

    def __init__(
        self,
        checkpoint: CodeRunCheckpoint,
        store: VaultStore,
        *,
        collection: str | None,
        retry_budget: int = DEFAULT_DRIFT_RETRY_BUDGET,
    ) -> None:
        """Bind one generation's authority to the storage it publishes into.

        Args:
            checkpoint: The generation whose evidence may be superseded.
            store: Storage the superseded points are dropped from.
            collection: Code collection the generation writes into, or ``None``
                when it writes in place to the served collection.
            retry_budget: How many supersedes one path may consume before it is
                deferred to the next generation.

        Raises:
            ValueError: If ``retry_budget`` is not positive.
        """
        if retry_budget < 1:
            raise ValueError("retry_budget must be a positive integer")
        self._checkpoint = checkpoint
        self._store = store
        self._collection = collection
        self._retry_budget = retry_budget
        self._attempts: dict[str, int] = {}
        self._superseded: set[str] = set()
        self._superseded_ids: set[str] = set()
        self._deferred: set[str] = set()
        self._collisions = 0

    @property
    def superseded_paths(self) -> tuple[str, ...]:
        """Return every path this run superseded, in deterministic order."""
        return tuple(sorted(self._superseded))

    @property
    def superseded_point_ids(self) -> frozenset[str]:
        """Return every point identity this run dropped as superseded.

        A run's caller cannot derive this from a pre-run id snapshot: chunk
        identity embeds a content digest, so a drifted path's replacement
        points carry new identities and the superseded ones are simply gone.
        Anything reconciling the snapshot against live storage has to be told
        which identities this run retired, or it counts them as still present.

        Deduplicated by construction: a path may be superseded several times
        within its retry budget, and dropping the same identity twice retires
        it once.
        """
        return frozenset(self._superseded_ids)

    @property
    def collisions_observed(self) -> int:
        """Return how many times the ledger had to signal a racing path.

        Distinct from the number of superseded paths: drift the pre-record
        check catches is repaired without the ledger ever refusing a write, so
        a non-zero count here means the source moved inside the window the
        check cannot cover.
        """
        return self._collisions

    @property
    def deferred_paths(self) -> tuple[str, ...]:
        """Return every path left stale for the next generation."""
        return tuple(sorted(self._deferred))

    @property
    def remediated(self) -> bool:
        """Return whether this run repaired drift rather than only faulting."""
        return bool(self._superseded or self._deferred)

    def snapshot(self) -> dict[str, object]:
        """Return this run's drift telemetry for the job and status surfaces.

        A remediated run succeeds, so the circuit breaker never hears about it
        - which is the point, since a busy tree is not a fault. That makes this
        the only channel on which drift volume is visible, so it carries the
        deferred paths by name rather than only counting them: a path that
        stays deferred is stale index content an operator has to be able to
        find.
        """
        return {
            "superseded_paths": len(self._superseded),
            "deferred_paths": list(self.deferred_paths),
            "collisions_observed": self._collisions,
            "retry_budget": self._retry_budget,
        }

    def supersede_snapshot(self, current_digests: Mapping[str, str]) -> int:
        """Supersede resumed evidence for paths a digest snapshot says moved.

        Runs before any segment is dispatched, so nothing has been written for
        these paths yet and every point storage holds for one of them is
        superseded content.

        Not charged against the per-path budget: this sweep happens once per
        run and cannot recur, so it needs no bound, and spending the budget
        here would leave the ordinary resumed edit competing with the race the
        budget is reserved for.

        Returns:
            The number of paths re-opened.
        """
        drifted = self._checkpoint.drifted_indexed_paths(current_digests)
        for rel_path, superseded_digest in sorted(drifted.items()):
            self._supersede(
                rel_path,
                superseded_digest,
                tuple(
                    self._store.get_code_ids_by_paths(
                        {rel_path}, collection=self._collection
                    )
                ),
            )
        if drifted:
            logger.info(
                "Re-opened %d resumed code path(s) whose source changed since "
                "the interrupted attempt indexed them",
                len(drifted),
            )
        return len(drifted)

    def record_segments(
        self,
        segments: tuple[CodeFileSegment, ...],
        source_digests: dict[str, str],
    ) -> int:
        """Record one confirmed store mutation, repairing drift in place.

        The storage write has already been confirmed by the time this is
        called, so a collision cannot be allowed to propagate: the fresh points
        are in the store, and the only outstanding work is making the ledger
        say so. A path is superseded and the record retried until its budget is
        spent, after which it is dropped from the mutation and deferred.

        Returns:
            The number of newly inserted ledger units.
        """
        pending = self._absorb_known_drift(segments, source_digests)
        while pending:
            try:
                return self._checkpoint.record_confirmed_segments(
                    pending,
                    source_digests,
                )
            except RunLedgerIndexedPathCollisionError as collision:
                self._collisions += 1
                if not collision.is_drift:
                    # Equal digests: the caller re-submitted content this
                    # generation already committed under different point
                    # identities. Superseding would drop published content to
                    # hide a real defect in the caller, so this stays fatal.
                    raise
                if self._charge(collision.rel_path):
                    self._supersede_recorded(
                        collision.rel_path,
                        collision.indexed_digest,
                    )
                    continue
                pending = self._defer(pending, collision.rel_path)
        return 0

    def _absorb_known_drift(
        self,
        segments: tuple[CodeFileSegment, ...],
        source_digests: dict[str, str],
    ) -> tuple[CodeFileSegment, ...]:
        """Clear already-visible drift before the record is even attempted.

        One indexed-state lookup over the paths in this mutation. It cannot
        close the race - the source may move again between this read and the
        transaction - but it keeps every drift the ledger can already see off
        the collision path, leaving the exception to handle the genuine race
        only.

        Charged against the same per-path budget as a collision repair,
        because both spend a supersede: a storage delete plus a ledger write.
        A path arriving drifted in slice after slice is the hot path the
        budget exists to stop chasing, and it is reached through here rather
        than through the signal.
        """
        observed = {segment.path: source_digests[segment.path] for segment in segments}
        pending = segments
        for rel_path, superseded_digest in sorted(
            self._checkpoint.drifted_indexed_paths(observed).items()
        ):
            if self._charge(rel_path):
                self._supersede_recorded(rel_path, superseded_digest)
            else:
                pending = self._defer(pending, rel_path)
        return pending

    def _supersede_recorded(
        self,
        rel_path: str,
        superseded_digest: str | None,
    ) -> None:
        """Supersede a path whose replacement points are already stored."""
        if superseded_digest is None:
            raise ValueError(
                f"cannot supersede {rel_path!r} without the digest it indexed"
            )
        self._supersede(
            rel_path,
            superseded_digest,
            self._checkpoint.superseded_point_ids(rel_path, superseded_digest),
        )

    def _supersede(
        self,
        rel_path: str,
        superseded_digest: str,
        stale_ids: tuple[str, ...],
    ) -> None:
        """Drop the superseded points, then stop claiming them, in that order.

        The order is the whole invariant. Chunk identity embeds a content
        digest, so replacement points never overwrite superseded ones. Removing
        the units first would leave storage holding points no unit claims,
        which no later reconciliation attributes to this path - the content
        would simply be published twice. Dropping first means an interruption
        between the two steps replays cleanly: the path is still recorded
        indexed under the old digest, is superseded again, and finds no points
        left to drop.
        """
        if stale_ids:
            self._store.delete_code_chunks(list(stale_ids), collection=self._collection)
            self._superseded_ids.update(stale_ids)
        self._checkpoint.reopen_drifted_path(rel_path, superseded_digest)
        self._superseded.add(rel_path)

    def _charge(self, rel_path: str) -> bool:
        """Consume one of a path's supersedes, reporting whether any remained."""
        spent = self._attempts.get(rel_path, 0)
        if spent >= self._retry_budget:
            return False
        self._attempts[rel_path] = spent + 1
        return True

    def _defer(
        self,
        pending: tuple[CodeFileSegment, ...],
        rel_path: str,
    ) -> tuple[CodeFileSegment, ...]:
        """Drop one exhausted path from the mutation and say so out loud."""
        self._deferred.add(rel_path)
        logger.warning(
            "Deferring code path %s to the next generation: its source changed "
            "again after each of %d supersede(s), exhausting the per-path drift "
            "retry budget of %d. The path stays indexed at its previous content "
            "until a later run catches it at rest",
            rel_path,
            self._attempts.get(rel_path, 0),
            self._retry_budget,
        )
        return tuple(segment for segment in pending if segment.path != rel_path)
