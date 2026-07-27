"""Ownership and bounded draining of watcher retry-settlement tasks."""

from __future__ import annotations

import asyncio
from threading import RLock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_LOCK = RLock()
_SETTLEMENTS: dict[Path, set[asyncio.Task[None]]] = {}


def register_retry_settlement(
    root: Path,
    task: asyncio.Task[None],
    observe: Callable[[asyncio.Task[None]], None],
) -> None:
    """Keep a settlement owned until its result has been observed."""
    resolved = root.resolve()
    with _LOCK:
        _SETTLEMENTS.setdefault(resolved, set()).add(task)

    def finish(completed: asyncio.Task[None]) -> None:
        observe(completed)
        with _LOCK:
            tasks = _SETTLEMENTS.get(resolved)
            if tasks is None:
                return
            tasks.discard(completed)
            if not tasks:
                _SETTLEMENTS.pop(resolved, None)

    task.add_done_callback(finish)


async def wait_for_retry_settlements(root: Path, deadline: float) -> bool:
    """Join exact retry settlements under the caller's existing time bound."""
    resolved = root.resolve()
    while True:
        with _LOCK:
            tasks = tuple(_SETTLEMENTS.get(resolved, ()))
        if not tasks:
            return True
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        done, pending = await asyncio.wait(tasks, timeout=remaining)
        failed = any(task.cancelled() or task.exception() is not None for task in done)
        if pending or failed:
            return False
        await asyncio.sleep(0)


def retry_settlements_released(root: Path) -> bool:
    """Return whether no retry settlement remains owned for a root."""
    with _LOCK:
        return not _SETTLEMENTS.get(root.resolve())
