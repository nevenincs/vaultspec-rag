"""Capacity limiters partitioning the service's worker-thread pool.

Searches and index jobs used to share anyio's default thread limiter
(40 process-wide tokens), so a handful of minutes-long reindex jobs
could permanently exhaust the pool that serves interactive searches.
Two dedicated limiters partition the pool: saturation beyond a
limiter's capacity queues callers instead of piling threads, and index
jobs can never starve searches of threads.

Limiters are created lazily on the event loop (anyio requires a
running async backend) and are process-wide singletons.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import anyio

__all__ = [
    "LIMITER_STAT_FIELDS",
    "get_encode_limiter",
    "get_index_limiter",
    "get_search_limiter",
    "limiter_stats",
    "reset_limiters",
]

_lock = threading.Lock()
_search_limiter: anyio.CapacityLimiter | None = None
_index_limiter: anyio.CapacityLimiter | None = None
_encode_limiter: anyio.CapacityLimiter | None = None

#: Exactly one encode-bearing index job may run at a time. A single GPU
#: gains nothing from job-level concurrency: concurrent encode jobs only
#: serialize on the process-wide GPU lock and inflate every job's wall
#: clock, so the machine-wide admission slot is fixed rather than tunable.
_ENCODE_ADMISSION_SLOTS = 1


def _make_limiter(tokens: int) -> anyio.CapacityLimiter:
    import anyio

    return anyio.CapacityLimiter(max(1, tokens))


def get_search_limiter() -> anyio.CapacityLimiter:
    """Return the shared limiter for interactive search dispatches."""
    global _search_limiter
    if _search_limiter is None:
        from .config._settings import get_config

        with _lock:
            if _search_limiter is None:
                _search_limiter = _make_limiter(
                    int(get_config().search_concurrency),
                )
    return _search_limiter


def get_index_limiter() -> anyio.CapacityLimiter:
    """Return the shared limiter for long-running index-job dispatches."""
    global _index_limiter
    if _index_limiter is None:
        from .config._settings import get_config

        with _lock:
            if _index_limiter is None:
                _index_limiter = _make_limiter(
                    int(get_config().index_job_concurrency),
                )
    return _index_limiter


def get_encode_limiter() -> anyio.CapacityLimiter:
    """Return the single-slot admission gate for encode-bearing index jobs.

    The daemon is the machine singleton, so this in-process limiter is the
    machine-wide encode-job admission slot. Jobs that will run GPU encoding
    acquire it before their worker thread starts; everyone else - searches,
    the storage-maintenance tick, and non-encode reads - never touches it,
    so nothing lifecycle-inert can starve or deadlock behind an encode job.
    """
    global _encode_limiter
    if _encode_limiter is None:
        with _lock:
            if _encode_limiter is None:
                _encode_limiter = _make_limiter(_ENCODE_ADMISSION_SLOTS)
    return _encode_limiter


def _stats(limiter: anyio.CapacityLimiter | None) -> dict[str, Any]:
    if limiter is None:
        return {"total_tokens": None, "borrowed_tokens": 0, "waiting": 0}
    stats = limiter.statistics()
    return {
        "total_tokens": int(limiter.total_tokens),
        "borrowed_tokens": int(stats.borrowed_tokens),
        "waiting": int(stats.tasks_waiting),
    }


#: The fields a limiter reports, taken from the reporter rather than written
#: out again: the metrics exporter names a gauge after each, and the status
#: header parses those gauge names back, so a field renamed here has to reach
#: both sides at once or the header silently stops reading what is emitted.
LIMITER_STAT_FIELDS: tuple[str, ...] = tuple(_stats(None))


def limiter_stats() -> dict[str, dict[str, Any]]:
    """Return bounded queue-depth telemetry for both limiters.

    ``total_tokens`` is ``None`` for a limiter that has not been
    exercised yet this process.
    """
    return {
        "search": _stats(_search_limiter),
        "index": _stats(_index_limiter),
        "encode": _stats(_encode_limiter),
    }


def reset_limiters() -> None:
    """Drop every limiter so the next caller rebuilds them (tests only)."""
    global _search_limiter, _index_limiter, _encode_limiter
    with _lock:
        _search_limiter = None
        _index_limiter = None
        _encode_limiter = None
