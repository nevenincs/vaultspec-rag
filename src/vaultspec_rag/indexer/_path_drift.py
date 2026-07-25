"""Own detection and remedy for code paths whose source moves mid-run."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from ..store import VaultStore
    from ._run_checkpoint import CodeRunCheckpoint
    from ._streaming import CodeFileSegment

__all__ = [
    "DEFAULT_SUPERSEDE_BUDGET",
    "CodePathDriftOwner",
    "PathDriftTally",
]

logger = logging.getLogger(__name__)

DEFAULT_SUPERSEDE_BUDGET = 3
"""How many times one path may be superseded before the run defers it.

A path that keeps drifting is being rewritten faster than it can be encoded.
Retrying it without limit spends the whole run on one file, so the budget
converts an unbounded loop into a bounded one with a visible outcome.
"""


@dataclass(frozen=True, slots=True)
class PathDriftTally:
    """Immutable drift volume for one attempt, separate from fault counts."""

    superseded_paths: int
    supersede_operations: int
    deferred_paths: int

    @property
    def observed(self) -> bool:
        """Whether this attempt saw any drift at all."""
        return bool(self.supersede_operations or self.deferred_paths)


class CodePathDriftOwner:
    """Single owner of the drift lifecycle for one code generation.

    Deciding a path has drifted, dropping its published points, and removing
    the units that claimed them is one operation with one order, not three
    independent steps. Holding all three here makes the order a property of
    the type: no caller can drop points without removing the units, and no
    caller can remove the units first.

    The order matters because chunk identity embeds a content digest. Content
    ingested again mints new identities rather than overwriting the old ones,
    so points left behind become silent duplicates rather than a visible
    failure. Removing storage first also means an interruption between the two
    replays cleanly: the path is still recorded indexed under the old digest,
    is re-opened again, and finds no points left to drop.

    The owner also carries the per-path retry budget, because deciding a path
    has drifted too often to be worth another attempt is the same decision as
    deciding it drifted at all.
    """

    __slots__ = (
        "_budget",
        "_checkpoint",
        "_deferred",
        "_store",
        "_supersede_counts",
    )

    def __init__(
        self,
        store: VaultStore,
        checkpoint: CodeRunCheckpoint,
        *,
        supersede_budget: int = DEFAULT_SUPERSEDE_BUDGET,
    ) -> None:
        """Bind one owner to the store and generation it repairs."""
        if isinstance(supersede_budget, bool) or supersede_budget < 1:
            raise ValueError("supersede_budget must be a positive integer")
        self._store = store
        self._checkpoint = checkpoint
        self._budget = supersede_budget
        self._supersede_counts: dict[str, int] = {}
        self._deferred: set[str] = set()

    @property
    def checkpoint(self) -> CodeRunCheckpoint:
        """Return the generation authority this owner repairs."""
        return self._checkpoint

    @property
    def deferred_paths(self) -> frozenset[str]:
        """Return the paths this attempt gave up on and left to the next one."""
        return frozenset(self._deferred)

    def tally(self) -> PathDriftTally:
        """Return drift volume for reporting alongside job state."""
        return PathDriftTally(
            superseded_paths=len(self._supersede_counts),
            supersede_operations=sum(self._supersede_counts.values()),
            deferred_paths=len(self._deferred),
        )

    def reopen_drifted(self, current_digests: Mapping[str, str]) -> int:
        """Supersede every resumed indexed path whose source has since changed.

        A resumed generation carries the indexed paths of the attempt that
        failed. Any of those whose source changed in the meantime can neither
        be recognised as already committed - commit-unit identity binds the
        source digest - nor written over an indexed path. Superseding them
        before dispatch is what turns a resumed attempt over a moving tree
        into an ordinary one, for every path that had already moved by then.

        Returns:
            The number of paths re-opened.
        """
        drifted = self._checkpoint.drifted_indexed_paths(current_digests)
        for rel_path, superseded_digest in sorted(drifted.items()):
            self.supersede(rel_path, superseded_digest)
        if drifted:
            logger.info(
                "Re-opened %d resumed code path(s) whose source changed since "
                "the interrupted attempt indexed them",
                len(drifted),
            )
        return len(drifted)

    def settle_pending(
        self,
        segments: tuple[CodeFileSegment, ...],
        source_digests: Mapping[str, str],
    ) -> frozenset[str]:
        """Settle any path in this mutation that drifted since dispatch.

        Checked immediately before the units are recorded rather than once
        per run, so a path that moved after the pre-dispatch sweep is repaired
        without the ledger ever having to refuse the write. It cannot replace
        the refusal - a path can still move between this check and the insert -
        but it keeps that far narrower window off the exception path.

        The budget applies here exactly as it does to a refused write. A path
        caught cheaply has still drifted, and letting the cheap route retry
        without limit would leave the bound in place only for the rarer one.

        Returns:
            The paths given up on, whose segments must not be recorded.
        """
        incoming = {segment.path: source_digests[segment.path] for segment in segments}
        drifted = self._checkpoint.drifted_indexed_paths(incoming)
        deferred: set[str] = set()
        for rel_path, superseded_digest in sorted(drifted.items()):
            protected = _point_ids_for_path(segments, rel_path)
            if self.budget_exhausted(rel_path):
                self.defer(rel_path, protected)
                deferred.add(rel_path)
                continue
            self.supersede(
                rel_path,
                superseded_digest,
                protected_ids=protected,
            )
        return frozenset(deferred)

    def supersede(
        self,
        rel_path: str,
        superseded_digest: str,
        *,
        protected_ids: frozenset[str] = frozenset(),
    ) -> int:
        """Drop one path's published points, then the units that claimed them.

        Args:
            rel_path: The project-relative path to re-open.
            superseded_digest: The digest recorded when the path was indexed.
            protected_ids: Identities already written for the incoming content.
                They live in storage before the ledger accepts them, so a
                remedy that dropped everything the store holds for this path
                would delete the very content it is making room for.

        Returns:
            The number of stale upsert units removed.
        """
        stale_ids = sorted(
            set(self._store.get_code_ids_by_paths({rel_path})) - protected_ids
        )
        if stale_ids:
            self._store.delete_code_chunks(stale_ids)
        removed = self._checkpoint.reopen_drifted_path(rel_path, superseded_digest)
        self._supersede_counts[rel_path] = self._supersede_counts.get(rel_path, 0) + 1
        return removed

    def budget_exhausted(self, rel_path: str) -> bool:
        """Return whether this path has used every supersede it is allowed."""
        return self._supersede_counts.get(rel_path, 0) >= self._budget

    def defer(self, rel_path: str, point_ids: Iterable[str]) -> None:
        """Leave one path to the next generation rather than failing the run.

        The identities just written are dropped, so the path keeps exactly the
        content its surviving evidence claims and the next run sees an ordinary
        changed file. Deferral is never silent: a path that stays stale because
        it is being rewritten faster than it can be indexed is an operational
        condition, not an implementation detail.
        """
        stale_ids = sorted(set(point_ids))
        if stale_ids:
            self._store.delete_code_chunks(stale_ids)
        self._deferred.add(rel_path)
        logger.warning(
            "Deferring code path %r to the next index run: its source changed "
            "%d time(s) during this run, exhausting the per-path budget of %d",
            rel_path,
            self._supersede_counts.get(rel_path, 0),
            self._budget,
        )


def _point_ids_for_path(
    segments: tuple[CodeFileSegment, ...],
    rel_path: str,
) -> frozenset[str]:
    """Return every identity one pending mutation carries for a single path."""
    return frozenset(
        chunk.id
        for segment in segments
        if segment.path == rel_path
        for chunk in segment.chunks
    )
