"""The one run lifecycle every index entry point shares.

Accepting a run, stamping the persisted activity clock, and emitting the
``service.index`` started / failed / completed triple is a single decision,
not a per-indexer detail. Every public ``full_index`` and
``incremental_index`` on every content kind routes through
:func:`run_index_lifecycle` so the decision has exactly one home: a new
indexer, or a new entry point on an existing one, cannot silently ship
without the stamp or without operator-visible events, which is precisely
what a copied-out wrapper allowed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from ..logging_config import log_event

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Mapping

    from ..job_control import RunControl
    from ._vault_prep import IndexResult

__all__ = ["ActivityClock", "incremental_mode", "run_index_lifecycle"]

#: Namespace every index run event is emitted under. Operator log surfaces
#: filter on it, so it is a contract rather than a formatting choice.
INDEX_EVENT_NAMESPACE = "service.index"


def incremental_mode(changed_paths: object | None) -> str:
    """Return the event mode an incremental run reports.

    A caller-supplied path set means the run reconciled only that scope; an
    absent one means it rescanned everything incrementally. Deriving the
    label once keeps the two spellings from drifting apart per content kind.
    """
    return "scoped_incremental" if changed_paths is not None else "incremental"


class ActivityClock(Protocol):
    """The persisted activity stamp this lifecycle refreshes.

    Narrow on purpose: the lifecycle needs nothing else from the store, and
    a narrow surface keeps the wrapper testable against the real stamp
    rather than against an indexer.
    """

    def touch_manifest_last_indexed(self) -> None:
        """Refresh this root's persisted ``last_indexed`` stamp."""
        ...


def run_index_lifecycle(
    *,
    clock: ActivityClock,
    event_logger: logging.Logger,
    source: str,
    mode: str,
    clean: bool,
    root: pathlib.Path,
    run_control: RunControl,
    body: Callable[[], IndexResult],
    completion_fields: Callable[[IndexResult], Mapping[str, object]] | None = None,
) -> IndexResult:
    """Run one indexing pass inside the shared observability lifecycle.

    Args:
        clock: The store whose persisted activity stamp this run refreshes.
        event_logger: The calling module's logger, so an event keeps the
            record name of the indexer that produced it.
        source: Content kind emitted on every event of this run.
        mode: ``"full"``, ``"incremental"``, or ``"scoped_incremental"``.
        clean: Whether this run was asked to rebuild destructively.
        root: The workspace root being indexed.
        run_control: Cooperative attempt control, checked at each edge of
            the lifecycle so a cancelled run stops between the stamp and
            the work rather than only inside it.
        body: The actual indexing pass. Called exactly once.
        completion_fields: Extra fields for the completion event, derived
            from the result. Content kinds that carry file and preprocess
            counters supply them here.

    Returns:
        Whatever ``body`` returned, unmodified.

    Raises:
        Exception: Whatever ``body`` raised, after emitting the failure
            event. The exception is never swallowed or translated.
    """
    run_control.checkpoint()
    log_event(
        event_logger,
        INDEX_EVENT_NAMESPACE,
        "started",
        source=source,
        mode=mode,
        clean=clean,
        root=root,
    )
    try:
        # Stamp the activity clock at run START as well as at completion: a
        # long run spanning a maintenance tick must advance the ephemeral
        # idle clock before any reclaim evaluation can see a stale stamp
        # mid-write.
        run_control.checkpoint()
        clock.touch_manifest_last_indexed()
        run_control.checkpoint()
        result = body()
        run_control.checkpoint()
        clock.touch_manifest_last_indexed()
        run_control.checkpoint()
    except Exception as exc:
        log_event(
            event_logger,
            INDEX_EVENT_NAMESPACE,
            "failed",
            severity=logging.ERROR,
            exc_info=True,
            source=source,
            mode=mode,
            clean=clean,
            root=root,
            error=exc,
        )
        raise
    # Built as one ordered mapping rather than keyword arguments so the
    # per-kind extras land after the shared counters in the emitted line.
    completed: dict[str, object] = {
        "source": source,
        "mode": mode,
        "clean": clean,
        "root": root,
        "total": result.total,
        "added": result.added,
        "updated": result.updated,
        "removed": result.removed,
        "duration_ms": result.duration_ms,
    }
    if completion_fields is not None:
        completed.update(completion_fields(result))
    log_event(event_logger, INDEX_EVENT_NAMESPACE, "completed", fields=completed)
    return result
