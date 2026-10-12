"""One graph cache with coalesced refresh and nonblocking search reads."""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib

    from vaultspec_core.graph import VaultGraph

logger = logging.getLogger(__name__)


class GraphCache:
    """Build outside the state lock; never publish an invalidated build."""

    def __init__(self, *, ttl_seconds: float | None = None) -> None:
        if ttl_seconds is None:
            from .config._settings import get_config

            ttl_seconds = float(get_config().graph_ttl_seconds)
        self._ttl_seconds = ttl_seconds
        self._graph: VaultGraph | None = None
        self._root: pathlib.Path | None = None
        self._built_at = 0.0
        self._retry_at = 0.0
        self._epoch = 0
        self._closed = False
        self._worker: threading.Thread | None = None
        self._condition = threading.Condition()

    def get(self, root_dir: pathlib.Path, *, wait: bool = True) -> VaultGraph | None:
        """Return a current graph, or None while refreshing a nonblocking read.

        Explicit relationship queries may wait. Search requests use ``wait=False``
        and retain their semantic ranking until graph nudges become available.
        """
        with self._condition:
            if self._closed:
                return None
            if self._root != root_dir:
                self._discard()
                self._root = root_dir
            if self._graph is not None:
                if time.monotonic() - self._built_at < self._ttl_seconds:
                    return self._graph
                self._graph = None
            self._start_refresh()
            if wait:
                self._condition.wait_for(lambda: self._worker is None or self._closed)
            return self._graph if self._root == root_dir else None

    def _start_refresh(self) -> None:
        """Start at most one builder; caller holds the condition lock."""
        if (
            self._worker is not None
            or self._root is None
            or self._closed
            or time.monotonic() < self._retry_at
        ):
            return
        context = contextvars.copy_context()
        worker = threading.Thread(
            target=context.run,
            args=(self._build, self._root, self._epoch),
            name="vault-graph-refresh",
            daemon=True,
        )
        self._worker = worker
        try:
            worker.start()
        except RuntimeError:
            self._worker = None
            self._retry_at = time.monotonic() + 5.0
            logger.warning("Failed to start vault graph refresh", exc_info=True)

    def _build(self, root_dir: pathlib.Path, epoch: int) -> None:
        graph = None
        try:
            from vaultspec_core.graph import VaultGraph

            graph = VaultGraph(root_dir)
        except Exception:
            logger.warning("Failed to build vault graph", exc_info=True)
        finally:
            with self._condition:
                self._worker = None
                if not self._closed and epoch == self._epoch:
                    self._graph = graph
                    self._built_at = time.monotonic()
                    self._retry_at = self._built_at + 5.0 if graph is None else 0.0
                elif not self._closed:
                    # Changes during construction coalesce into one fresh build.
                    self._start_refresh()
                self._condition.notify_all()

    def _discard(self) -> None:
        self._epoch += 1
        self._graph = None
        self._built_at = 0.0
        self._retry_at = 0.0

    def invalidate(self) -> None:
        """Retire stale data immediately and refresh without blocking indexing."""
        with self._condition:
            self._discard()
            self._start_refresh()

    def close(self) -> None:
        """Retire this cache without waiting for filesystem work to finish."""
        with self._condition:
            self._closed = True
            self._discard()
            self._condition.notify_all()
