"""Filesystem-watcher lifecycle for resident projects.

Split out of the original ``server.py`` monolith per the
``2026-06-01-module-split-adr``. The watcher bookkeeping dicts and lock
are mutated in place; the registry is read through the package alias so
a test rebind of ``_registry`` is observed. ``_ensure_watcher`` keeps
its literal ``_registry.peek_project`` call - a source-inspection
regression test asserts that string is present.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

__all__ = [
    "_ensure_watcher",
    "_ensure_watcher_soon",
    "_stop_all_watchers",
    "_stop_watcher",
]

import vaultspec_rag.server as _m

from ..logging_config import log_event

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("vaultspec_rag.server")

#: Strong references to in-flight deferred watcher starts so the event
#: loop cannot garbage-collect them mid-flight.
_deferred_watcher_tasks: set[asyncio.Task[None]] = set()


def _ensure_watcher_soon(root: Path) -> None:
    """Ensure a watcher for *root* without blocking the event loop.

    Per-request callers (the search and reindex routes) must not pay
    the cold project-slot open (50-200ms of store I/O) on the loop
    thread. When the watcher already exists this is a dict probe; when
    it does not, the slot is warmed on a worker thread and the watcher
    registered afterwards.
    """
    root = root.resolve()
    if root in _m._watcher_tasks:
        return

    async def _warm_and_start() -> None:
        import anyio.to_thread

        try:
            await anyio.to_thread.run_sync(lambda: _m._registry.peek_project(root))
        except Exception:
            logger.exception("Deferred watcher start failed for %s", root)
            return
        _m._ensure_watcher(root)

    task = asyncio.create_task(_warm_and_start())
    _deferred_watcher_tasks.add(task)
    task.add_done_callback(_deferred_watcher_tasks.discard)


def _ensure_watcher(
    root: Path,
    *,
    debounce_ms: int | None = None,
    cooldown_s: float | None = None,
) -> bool:
    """Launch a filesystem watcher for *root* as a background asyncio task.

    Safe to call repeatedly - starts at most one watcher per root.
    Uses a double-check lock pattern to prevent duplicate watcher
    creation when multiple tool handlers finish near-simultaneously.

    Must be called from the async event loop thread (not from a
    worker thread).

    Args:
        root: Project root directory to watch.
        debounce_ms: Optional debounce override (ms); falls back to
            ``cfg.watch_debounce_ms`` when ``None``.
        cooldown_s: Optional cooldown override (s); falls back to
            ``cfg.watch_cooldown_s`` when ``None``.

    Returns:
        ``True`` if a watcher is running for *root* on return (newly
        started or already present); ``False`` if watching is disabled
        or the service is shutting down.
    """
    from ..config import get_config

    cfg = get_config()
    # watch_enabled is the sole opt-out: when disabled the service is
    # pull-only and no watcher is ever started - including explicit
    # start/reconfigure requests.
    if not cfg.watch_enabled:
        return False
    root = root.resolve()
    if root in _m._watcher_tasks:
        return True
    # Resolve the project slot OUTSIDE the lock - peek_project() has
    # its own per-root locking and can take 50-200ms on cold start.
    # Holding _watcher_lock during that would block the event loop.
    slot = _m._registry.peek_project(root)
    with _m._watcher_lock:
        if root in _m._watcher_tasks:
            return True
        if getattr(_m._registry, "_shutting_down", False):
            return False

        from ..watcher import watch_and_reindex

        debounce = (
            int(debounce_ms)
            if debounce_ms is not None
            else int(
                cfg.watch_debounce_ms,
            )
        )
        cooldown = (
            float(cooldown_s)
            if cooldown_s is not None
            else float(
                cfg.watch_cooldown_s,
            )
        )
        stop_event = asyncio.Event()
        vault_dir = root / ".vault"
        task = asyncio.create_task(
            watch_and_reindex(
                root_dir=root,
                vault_dir=vault_dir,
                vault_indexer=slot.vault_indexer,
                code_indexer=slot.code_indexer,
                stop_event=stop_event,
                graph_cache=slot.graph_cache,
                debounce=debounce,
                cooldown=cooldown,
            ),
        )
        _m._watcher_tasks[root] = task
        _m._watcher_stops[root] = stop_event
        log_event(logger, "service.watcher", "task_started", root=root)
    return True


def _stop_watcher(root: Path) -> None:
    """Stop and remove the watcher for *root*.

    Args:
        root: Project root directory (must be resolved).
    """
    root = root.resolve()
    with _m._watcher_lock:
        stop_event = _m._watcher_stops.pop(root, None)
        task = _m._watcher_tasks.pop(root, None)
    if stop_event is not None:
        stop_event.set()
    if task is not None and not task.done():
        task.cancel()
    if task is not None:
        log_event(logger, "service.watcher", "task_stopped", root=root)


def _stop_all_watchers() -> None:
    """Stop all running watchers."""
    with _m._watcher_lock:
        roots = list(_m._watcher_tasks.keys())
    for root in roots:
        _m._stop_watcher(root)
