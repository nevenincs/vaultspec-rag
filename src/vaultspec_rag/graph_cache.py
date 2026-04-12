"""Thread-safe cached ``VaultGraph`` wrapper.

Extracted from ``api.py`` so that the registry collapse in the
store-eviction phase can rewire facade functions without also moving
graph-cache code in the same commit.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib

    from vaultspec_core.graph import VaultGraph

logger = logging.getLogger(__name__)

__all__ = ["GraphCache"]


class GraphCache:
    """Thread-safe cached VaultGraph with lock, TTL, and explicit invalidation.

    Uses a ``threading.Lock`` with a double-check pattern so that
    concurrent callers never build duplicate graphs.  The TTL ensures
    the graph is periodically refreshed without requiring explicit
    invalidation after every change.
    """

    def __init__(self, *, ttl_seconds: float | None = None) -> None:
        """Initialise the graph cache.

        Args:
            ttl_seconds: Seconds before a cached graph expires.
                Defaults to ``graph_ttl_seconds`` from project
                config (300s).
        """
        if ttl_seconds is None:
            from .config import get_config

            ttl_seconds = get_config().graph_ttl_seconds
        self._ttl_seconds = ttl_seconds
        self._graph: VaultGraph | None = None
        self._root: pathlib.Path | None = None
        self._built_at: float = 0.0
        self._lock = threading.Lock()

    def _is_stale(self, root_dir: pathlib.Path) -> bool:
        """Return ``True`` when the cache needs a rebuild.

        Args:
            root_dir: Workspace root directory to check against the
                cached root.

        Returns:
            ``True`` if the graph has not been built yet, targets a
            different *root_dir*, or the TTL has expired.
        """
        if self._graph is None or self._root != root_dir:
            return True
        return (time.monotonic() - self._built_at) >= self._ttl_seconds

    def get(self, root_dir: pathlib.Path) -> VaultGraph | None:
        """Return cached graph, building it if necessary or stale.

        Args:
            root_dir: Workspace root directory.

        Returns:
            The ``VaultGraph`` for *root_dir*, or ``None`` if the
            graph could not be built (e.g. missing vault directory).
        """
        if not self._is_stale(root_dir):
            return self._graph
        with self._lock:
            if not self._is_stale(root_dir):
                return self._graph
            from vaultspec_core.graph import VaultGraph

            try:
                self._graph = VaultGraph(root_dir)
                self._root = root_dir
                self._built_at = time.monotonic()
            except Exception:
                logger.warning("Failed to build vault graph", exc_info=True)
                self._graph = None
                self._root = None
                # Retry sooner on failure (5s vs normal TTL)
                self._built_at = time.monotonic() - self._ttl_seconds + 5.0
                return None
        return self._graph

    def invalidate(self) -> None:
        """Clear the cached graph.

        Call after vault reindex so that the next ``get()`` rebuilds
        the graph from updated documents.  Thread-safe.
        """
        with self._lock:
            self._graph = None
            self._root = None
            self._built_at = 0.0
