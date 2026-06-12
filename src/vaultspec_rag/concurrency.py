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
    "get_index_limiter",
    "get_search_limiter",
    "limiter_stats",
    "reset_limiters",
]

_lock = threading.Lock()
_search_limiter: anyio.CapacityLimiter | None = None
_index_limiter: anyio.CapacityLimiter | None = None


def _make_limiter(tokens: int) -> anyio.CapacityLimiter:
    import anyio

    return anyio.CapacityLimiter(max(1, tokens))


def get_search_limiter() -> anyio.CapacityLimiter:
    """Return the shared limiter for interactive search dispatches."""
    global _search_limiter
    if _search_limiter is None:
        from .config import get_config

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
        from .config import get_config

        with _lock:
            if _index_limiter is None:
                _index_limiter = _make_limiter(
                    int(get_config().index_job_concurrency),
                )
    return _index_limiter


def _stats(limiter: anyio.CapacityLimiter | None) -> dict[str, Any]:
    if limiter is None:
        return {"total_tokens": None, "borrowed_tokens": 0, "waiting": 0}
    stats = limiter.statistics()
    return {
        "total_tokens": int(limiter.total_tokens),
        "borrowed_tokens": int(stats.borrowed_tokens),
        "waiting": int(stats.tasks_waiting),
    }


def limiter_stats() -> dict[str, dict[str, Any]]:
    """Return bounded queue-depth telemetry for both limiters.

    ``total_tokens`` is ``None`` for a limiter that has not been
    exercised yet this process.
    """
    return {
        "search": _stats(_search_limiter),
        "index": _stats(_index_limiter),
    }


def reset_limiters() -> None:
    """Drop both limiters so the next caller rebuilds them (tests only)."""
    global _search_limiter, _index_limiter
    with _lock:
        _search_limiter = None
        _index_limiter = None
