"""In-flight activity registry for index/reindex jobs (#142, plan P01).

A small, thread-safe, bounded record of every index/reindex activity the
service performs. Written inline by the reindex MCP tools
(``trigger="tool"``) and the watcher reindex loop (``trigger="watcher"``);
read by the jobs/state observability surface (later phases). There is **no**
background thread or reaper — entries are appended/finished synchronously by
the hot path and the buffer is bounded so it can never grow unbounded
(honours the standing rejection of background sweepers per the
``service-observability`` ADR).

All access is guarded by a module-level :class:`threading.Lock`. The buffer is
a :class:`collections.deque` with ``maxlen`` so the oldest record is evicted
once the cap is reached. Records are mutated in place on finish (looked up by
their stable ``id``); :func:`snapshot` returns deep-copied dicts newest-first
so callers cannot observe or mutate live state.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Literal

__all__ = [
    "MAX_RECORDS",
    "record_finish",
    "record_start",
    "reset",
    "snapshot",
]

# Source of an activity: the documentation vault or the source codebase.
Source = Literal["vault", "code"]
# What initiated the activity: a reindex tool call or the filesystem watcher.
Trigger = Literal["tool", "watcher"]
# Lifecycle phase of a record.
Phase = Literal["running", "done", "error"]

# Bounded ring buffer cap. Generous enough to retain a meaningful recent
# history without unbounded growth; the oldest record is evicted past this.
MAX_RECORDS = 256

_lock = threading.Lock()
_records: deque[dict[str, object]] = deque(maxlen=MAX_RECORDS)


def record_start(source: Source, trigger: Trigger) -> str:
    """Append a new ``running`` activity record and return its stable id.

    Args:
        source: ``"vault"`` or ``"code"`` — the corpus being (re)indexed.
        trigger: ``"tool"`` (a reindex MCP tool call) or ``"watcher"``
            (the filesystem watcher reindex loop).

    Returns:
        The record's stable ``id`` (a uuid4 hex string) to pass to
        :func:`record_finish`.
    """
    record_id = uuid.uuid4().hex
    record: dict[str, object] = {
        "id": record_id,
        "source": source,
        "trigger": trigger,
        "phase": "running",
        "started_at": time.time(),
        "finished_at": None,
        "result": None,
    }
    with _lock:
        _records.append(record)
    return record_id


def record_finish(
    record_id: str,
    *,
    result: str | None = None,
    error: str | None = None,
) -> None:
    """Mark the record with *record_id* finished, in place.

    Sets ``finished_at`` and transitions ``phase`` to ``"error"`` when
    *error* is given, otherwise ``"done"``. The ``result`` field holds a
    short human-readable summary (the *error* string when erroring, else
    *result*). A no-op if the id is unknown (e.g. evicted past the bound).

    Args:
        record_id: The id returned by :func:`record_start`.
        result: Optional success summary (ignored when *error* is set).
        error: Optional error summary; its presence flips the phase to
            ``"error"``.
    """
    finished_at = time.time()
    phase: Phase = "error" if error is not None else "done"
    summary = error if error is not None else result
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                record["phase"] = phase
                record["finished_at"] = finished_at
                record["result"] = summary
                return


def snapshot() -> list[dict[str, object]]:
    """Return a newest-first list of copied activity records.

    Each entry is a shallow copy of the stored record (all values are
    immutable scalars or ``None``), so callers cannot mutate live state.

    Returns:
        Newest-first list of record dicts.
    """
    with _lock:
        return [dict(record) for record in reversed(_records)]


def reset() -> None:
    """Clear all recorded activity (test-only)."""
    with _lock:
        _records.clear()
