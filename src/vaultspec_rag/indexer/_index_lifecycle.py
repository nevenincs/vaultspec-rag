"""The one index-run lifecycle every indexer's run entry points share.

Each indexer owns its own discovery, chunking, and storage pipeline, but
every full or incremental run is wrapped by identical cross-cutting
behaviour: refresh the persisted activity clock so a long run is never
mistaken for an idle root, and emit the ``service.index``
started/failed/completed events the operator log surface reads.

That behaviour lives here exactly once. An indexer supplies its locked
implementation as the ``body`` callable and the labels its events carry;
it never stamps the clock or emits an index event itself. Adding a new
content domain therefore inherits both by construction rather than by
remembering to copy them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from ..logging_config import log_event

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Mapping

    from ..job_control import RunControl
    from ..store_runtime import VaultStore
    from ._vault_prep import IndexResult

#: Namespace every index-run lifecycle event is emitted under.
INDEX_EVENT_NAMESPACE = "service.index"


@dataclass(frozen=True, slots=True)
class IndexLifecycleRequest:
    event_logger: logging.Logger
    store: VaultStore
    source: str
    mode: str
    clean: bool
    root: pathlib.Path
    run_control: RunControl
    completion_fields: Callable[[IndexResult], Mapping[str, object]] | None = None


def preprocess_completion_fields(result: IndexResult) -> dict[str, object]:
    """Completion extras every domain that runs a preprocess pipeline reports.

    Coverage gaps in rule-fed content are only visible when the counts
    ride the ``completed`` event, so the domains sharing that pipeline
    share these fields rather than each choosing a subset.
    """
    return {
        "files": result.files,
        "preprocess_ok": result.preprocess_ok,
        "preprocess_skipped": result.preprocess_skipped,
    }


def run_index_lifecycle(
    body: Callable[[], IndexResult],
    request: IndexLifecycleRequest | None = None,
    **legacy: object,
) -> IndexResult:
    """Run ``body`` as an observable, activity-stamped index run.

    The caller holds its writer lock and has already resolved whatever
    per-run state its pipeline needs; this wrapper adds only the
    behaviour that is identical across every content domain.

    Args:
        body: The indexer's locked implementation, called once.
        event_logger: Logger the events are attributed to, so records keep
            naming the indexer module that produced them.
        store: Store whose persisted activity clock this run refreshes.
        source: Content-domain label carried by every event of this run.
        mode: Run-shape label (``full``, ``incremental``,
            ``scoped_incremental``).
        clean: Whether this run rebuilds from empty.
        root: Workspace root being indexed.
        run_control: Cooperative attempt control, checked around the
            stamps so a cancelled attempt stops before and after the body
            rather than only inside it.
        completion_fields: Optional per-domain extras for the
            ``completed`` event, derived from the run's result.

    Returns:
        Whatever ``body`` returned.

    Raises:
        Exception: Re-raises anything ``body`` raises, after emitting the
            ``failed`` event.
    """
    if request is None:
        request = IndexLifecycleRequest(**cast("dict[str, Any]", legacy))
    elif legacy:
        raise TypeError("use either IndexLifecycleRequest or named inputs")
    run_fields: dict[str, object] = {
        "source": request.source,
        "mode": request.mode,
        "clean": request.clean,
        "root": request.root,
    }
    request.run_control.checkpoint()
    log_event(request.event_logger, INDEX_EVENT_NAMESPACE, "started", fields=run_fields)
    try:
        # Stamp the activity clock at run START as well as at completion:
        # a long run spanning a maintenance tick must advance the ephemeral
        # idle clock before any reclaim evaluation can see a stale stamp
        # mid-write.
        request.run_control.checkpoint()
        request.store.touch_manifest_last_indexed()
        request.run_control.checkpoint()
        result = body()
        request.run_control.checkpoint()
        request.store.touch_manifest_last_indexed()
        request.run_control.checkpoint()
    except Exception as exc:
        log_event(
            request.event_logger,
            INDEX_EVENT_NAMESPACE,
            "failed",
            severity=logging.ERROR,
            exc_info=True,
            fields=run_fields,
            error=exc,
        )
        raise
    completed_fields = dict(run_fields)
    completed_fields.update(
        total=result.total,
        added=result.added,
        updated=result.updated,
        removed=result.removed,
        duration_ms=result.duration_ms,
    )
    if request.completion_fields is not None:
        completed_fields.update(request.completion_fields(result))
    log_event(
        request.event_logger,
        INDEX_EVENT_NAMESPACE,
        "completed",
        fields=completed_fields,
    )
    return result
