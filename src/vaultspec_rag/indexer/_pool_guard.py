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

The pool constructor here also keeps the working directory off a worker's
import path while it starts; :class:`_WorkerImportPath` says why that has to
be done at this one place and by this one means.
"""

from __future__ import annotations

import contextlib
import multiprocessing
import os
import sys
import threading
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator
    from multiprocessing.context import BaseContext

__all__ = ["die_with_parent", "spawn_pool"]

# Distinct from a task failure: the worker was healthy and simply outlived the
# run that owned it.
_ORPHANED_EXIT_CODE = 3

#: The interpreter's own switch for safe-path mode, read once at startup.
_SAFE_PATH_VARIABLE = "PYTHONSAFEPATH"


class _WorkerImportPath:
    """Start pool workers with the working directory off their import path.

    The standard library starts a spawn worker on an inline program, and an
    interpreter started that way puts the working directory first on its
    import path. The worker replaces that path with its parent's a moment
    later, but it has imported the bootstrap by then, so a file in the
    working directory named after anything the bootstrap imports has already
    run. Indexing is done from inside the project being indexed; that
    directory is not this package's to trust.

    Every other child this package starts is given the interpreter's
    safe-path flag on its command line. A pool worker's command line is built
    inside the standard library, which passes on the flags the parent was
    itself started with and offers no way to add one. So a parent that was
    started with the flag needs nothing here, and for any other parent the
    environment variable is the only thing that reaches the worker. That is
    why this one site uses the variable; it is not a second convention to
    converge on.

    The variable is set only while a pool is open and is put back exactly as
    it was, absent included. Pools overlap and are opened from several
    threads, so the first one in sets it and the last one out restores it.
    Other children started in that window inherit it too. None of this
    package's depends on being without it: project hooks are given an
    allow-listed environment that does not carry it, and the rest are
    started in safe-path mode already.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open_pools = 0
        self._previous: str | None = None

    @contextlib.contextmanager
    def held(self) -> Generator[None]:
        """Keep workers started inside the block in safe-path mode."""
        if sys.flags.safe_path:
            yield
            return
        if sys.flags.ignore_environment:
            # The standard library hands that flag to the worker as well, and
            # a worker told to ignore its environment never reads the variable.
            msg = (
                "A worker pool cannot be started safely from this interpreter: "
                "it ignores its environment (-E) and is not in safe-path mode, "
                "so its workers would import from the working directory. "
                "Start it with -P or -I."
            )
            raise RuntimeError(msg)
        with self._lock:
            if self._open_pools == 0:
                self._previous = os.environ.get(_SAFE_PATH_VARIABLE)
                os.environ[_SAFE_PATH_VARIABLE] = "1"
            self._open_pools += 1
        try:
            yield
        finally:
            with self._lock:
                self._open_pools -= 1
                if self._open_pools == 0:
                    if self._previous is None:
                        os.environ.pop(_SAFE_PATH_VARIABLE, None)
                    else:
                        os.environ[_SAFE_PATH_VARIABLE] = self._previous
                    self._previous = None


_worker_import_path = _WorkerImportPath()


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


@contextlib.contextmanager
def spawn_pool(
    *, max_workers: int, mp_context: BaseContext
) -> Generator[ProcessPoolExecutor]:
    """Open a worker pool whose workers cannot outlive this process.

    The single home for indexer pool construction. Every spawn pool in the
    indexer is built here so none of them can be created without its guards -
    a pool assembled directly from :class:`ProcessPoolExecutor` looks correct,
    leaks a full worker cohort the first time its owner is killed hard, and
    starts each worker with the working directory on its import path.

    A pool starts its workers as work is submitted, not when it is built, so
    it is handed out for the length of a block rather than returned: the
    import-path guard has to hold for as long as a worker can still be
    started.
    """
    with (
        _worker_import_path.held(),
        ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=mp_context,
            initializer=die_with_parent,
        ) as pool,
    ):
        yield pool
