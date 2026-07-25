"""Parent-death guard for the spawn-started chunk worker pools.

``ProcessPoolExecutor`` workers are blind to their parent's death. They park in
``call_queue.get(block=True)``, and the call queue's write handle is inherited
by every worker, so the read end never reaches EOF while a single sibling is
still alive - the pool keeps itself blocked indefinitely. Nothing in the worker
loop waits on the parent sentinel.

That costs nothing while the parent unwinds its ``with`` block, because
``shutdown()`` hands every worker the ``None`` wake-up item. It is not free when
the parent dies without reaching that path. On Windows the service stop verb
escalates to ``TerminateProcess`` by design - a detached daemon shares no
console, so the graceful console signal cannot reach it - which skips
``atexit`` and the lifespan ``finally`` alike; a crash or an external hard kill
lands the same way. The pool is then stranded, and Windows neither reaps
orphans nor tears down a process group on parent death, so the workers survive
until an operator finds them: one full ``os.process_cpu_count()`` cohort per
killed run, each holding its own interpreter's worth of memory.

Waiting on the parent sentinel is the only signal that survives a death the
parent never got to handle, so each worker watches it directly and leaves when
it fires. The sibling qdrant child is guarded by a Windows job object instead
(see :mod:`vaultspec_rag.qdrant_runtime._supervise`); that mechanism needs a
handle to a child the parent spawned itself, which is not how a pool worker
comes into being, hence the in-worker watch here.
"""

from __future__ import annotations

import multiprocessing
import os
import threading
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocessing.context import BaseContext

__all__ = ["die_with_parent", "spawn_pool"]

# Distinct from a task failure: the worker was healthy and simply outlived the
# run that owned it.
_ORPHANED_EXIT_CODE = 3


def die_with_parent() -> None:
    """Exit this worker as soon as its parent process goes away.

    Installed as the ``initializer`` of every spawn-started pool, so it runs
    once inside each worker before it accepts work.
    """
    parent = multiprocessing.parent_process()
    if parent is None:
        # Not a spawned child - nothing owns this process, so nothing to watch.
        return

    def _watch() -> None:
        parent.join()
        # The parent is gone, so there is no result queue anyone will drain and
        # no cleanup worth running - an orderly interpreter shutdown would only
        # block on the very queues whose reader just died. Leave immediately.
        os._exit(_ORPHANED_EXIT_CODE)

    threading.Thread(
        target=_watch,
        name="vaultspec-rag-parent-death-watch",
        daemon=True,
    ).start()


def spawn_pool(*, max_workers: int, mp_context: BaseContext) -> ProcessPoolExecutor:
    """Build a worker pool whose workers cannot outlive this process.

    The single home for indexer pool construction. Every spawn pool in the
    indexer is built here so none of them can be created without the guard -
    a pool assembled directly from :class:`ProcessPoolExecutor` looks correct
    and leaks a full worker cohort the first time its owner is killed hard.
    """
    return ProcessPoolExecutor(
        max_workers=max_workers,
        mp_context=mp_context,
        initializer=die_with_parent,
    )
