"""In-flight activity registry and background task worker for index/reindex jobs.

A thread-safe, bounded record of every index/reindex activity the service performs,
along with async task execution helpers for background reindexing.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import deque
from typing import TYPE_CHECKING, Any, Literal

from anyio.to_thread import run_sync as _run_in_thread

from .registry import get_registry

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_RECORDS",
    "JobProgressReporter",
    "record_finish",
    "record_progress",
    "record_start",
    "register_on_job_complete",
    "reset",
    "snapshot",
    "start_reindex_codebase",
    "start_reindex_vault",
]

# Source of an activity: the documentation vault or the source codebase.
Source = Literal["vault", "code"]
# What initiated the activity: a reindex tool call or the filesystem watcher.
Trigger = Literal["tool", "watcher"]
# Lifecycle phase of a record.
Phase = Literal[
    "running", "done", "error", "failed", "cancelled", "superseded", "skipped"
]

# Bounded ring buffer cap. Generous enough to retain a meaningful recent
# history without unbounded growth; the oldest record is evicted past this.
MAX_RECORDS = 256

_lock = threading.Lock()
_records: deque[dict[str, object]] = deque(maxlen=MAX_RECORDS)
_background_tasks: set[asyncio.Task[Any]] = set()
_on_job_complete_callbacks: list[Callable[[float], None]] = []


def register_on_job_complete(callback: Callable[[float], None]) -> None:
    """Register a callback to be run when a background job completes.

    The callback receives the duration of the job in seconds.
    """
    _on_job_complete_callbacks.append(callback)


def record_start(source: Source, trigger: Trigger) -> str:
    """Append a new ``running`` activity record and return its stable id.

    Args:
        source: ``"vault"`` or ``"code"`` - the corpus being (re)indexed.
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
        "progress": None,
    }
    with _lock:
        _records.append(record)
    return record_id


def record_progress(
    record_id: str,
    step: str,
    completed: int = 0,
    total: int | None = None,
) -> None:
    """Update progress for an active running job.

    Args:
        record_id: The id returned by :func:`record_start`.
        step: Name of the current phase/step (e.g. "queued", "discover", "embed").
        completed: Count of items processed so far in this step.
        total: Total number of items to process, if known.
    """
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                record["progress"] = {
                    "step": step,
                    "completed": completed,
                    "total": total,
                    "last_updated": time.time(),
                }
                return


def record_finish(
    record_id: str,
    *,
    result: str | None = None,
    error: str | None = None,
    phase: Phase | None = None,
) -> None:
    """Mark the record with *record_id* finished, in place.

    Sets ``finished_at`` and transitions ``phase`` to the given *phase*, or
    to ``"error"`` when *error* is given, otherwise ``"done"``. The ``result``
    field holds a short human-readable summary (the *error* string when erroring,
    else *result*). A no-op if the id is unknown (e.g. evicted past the bound).

    Args:
        record_id: The id returned by :func:`record_start`.
        result: Optional success summary (ignored when *error* is set).
        error: Optional error summary; its presence flips the phase to
            ``"error"`` if *phase* is not explicitly provided.
        phase: Optional explicit target phase (e.g. ``"cancelled"``).
    """
    finished_at = time.time()
    if phase is not None:
        target_phase = phase
    else:
        target_phase = "error" if error is not None else "done"
    summary = error if error is not None else result
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                record["phase"] = target_phase
                record["finished_at"] = finished_at
                record["result"] = summary
                return


def snapshot() -> list[dict[str, object]]:
    """Return a newest-first list of copied activity records.

    Each entry is a shallow copy of the stored record, and any progress
    nested dictionary is also copied, so callers cannot mutate live state.

    Returns:
        Newest-first list of record dicts.
    """
    with _lock:
        copied: list[dict[str, object]] = []
        for record in reversed(_records):
            item = dict(record)
            prog = record.get("progress")
            if isinstance(prog, dict):
                item["progress"] = dict(prog)
            copied.append(item)
        return copied


def reset() -> None:
    """Clear all recorded activity (test-only)."""
    with _lock:
        _records.clear()


class JobProgressReporter:
    """ProgressReporter that updates a specific in-flight job's progress."""

    def __init__(self, record_id: str) -> None:
        self.record_id = record_id
        self._step_name: str | None = None
        self._completed: int = 0
        self._total: int | None = None

    def phase_start(self, name: str, total: int | None) -> None:
        self._step_name = name
        self._total = total
        self._completed = 0
        record_progress(self.record_id, step=name, completed=0, total=total)

    def advance(self, n: int = 1) -> None:
        self._completed += n
        if self._step_name:
            record_progress(
                self.record_id,
                step=self._step_name,
                completed=self._completed,
                total=self._total,
            )

    def phase_end(self) -> None:
        pass

    def log(self, message: str) -> None:
        pass


def start_reindex_vault(root: Path, clean: bool) -> str:
    """Start a background vault reindexing task and return the job_id."""
    job_id = record_start("vault", "tool")
    record_progress(job_id, "queued")

    async def run_indexing_bg() -> None:
        try:
            started = time.perf_counter()

            def _bg_run() -> None:
                try:
                    with get_registry().lease(root) as slot:
                        if clean:
                            result = slot.vault_indexer.full_index(
                                clean=True,
                                reporter=JobProgressReporter(job_id),
                            )
                        else:
                            result = slot.vault_indexer.incremental_index(
                                reporter=JobProgressReporter(job_id)
                            )
                        record_finish(
                            job_id,
                            result=(
                                f"+{result.added} /{result.updated} "
                                f"-{result.removed} ({result.duration_ms}ms)"
                            ),
                        )
                        slot.graph_cache.invalidate()
                except Exception as exc:
                    record_finish(job_id, error=str(exc))
                    logger.exception("Background vault re-indexing failed")

            await _run_in_thread(_bg_run)
            duration = time.perf_counter() - started
            for cb in _on_job_complete_callbacks:
                try:
                    cb(duration)
                except Exception as e:
                    logger.exception("Error in job complete callback: %s", e)
        except Exception:
            logger.exception("Failed to launch background vault re-indexing task")

    task = asyncio.create_task(run_indexing_bg())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return job_id


def start_reindex_codebase(root: Path, clean: bool) -> str:
    """Start a background codebase reindexing task and return the job_id."""
    job_id = record_start("code", "tool")
    record_progress(job_id, "queued")

    async def run_indexing_bg() -> None:
        try:
            started = time.perf_counter()

            def _bg_run() -> None:
                try:
                    with get_registry().lease(root) as slot:
                        if clean:
                            result = slot.code_indexer.full_index(
                                clean=True,
                                reporter=JobProgressReporter(job_id),
                            )
                        else:
                            result = slot.code_indexer.incremental_index(
                                reporter=JobProgressReporter(job_id)
                            )
                        record_finish(
                            job_id,
                            result=(
                                f"+{result.added} /{result.updated} "
                                f"-{result.removed} ({result.duration_ms}ms)"
                            ),
                        )
                except Exception as exc:
                    record_finish(job_id, error=str(exc))
                    logger.exception("Background codebase re-indexing failed")

            await _run_in_thread(_bg_run)
            duration = time.perf_counter() - started
            for cb in _on_job_complete_callbacks:
                try:
                    cb(duration)
                except Exception as e:
                    logger.exception("Error in job complete callback: %s", e)
        except Exception:
            logger.exception("Failed to launch background codebase re-indexing task")

    task = asyncio.create_task(run_indexing_bg())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return job_id
