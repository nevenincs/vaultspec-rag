"""Centralized service registry for vaultspec-rag.

Provides a ``ServiceRegistry`` that holds a shared ``EmbeddingModel``
and per-project ``ProjectSlot`` instances, each containing a
``VaultStore``, ``VaultSearcher``, ``VaultIndexer``, ``CodebaseIndexer``,
and ``GraphCache``.  Designed to replace the scattered component
initialization in ``api.py`` and ``mcp_server.py``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sentence_transformers import CrossEncoder

    from .embeddings import EmbeddingModel
    from .indexer import CodebaseIndexer, VaultIndexer
    from .search import VaultSearcher
    from .store import VaultStore

from .api import GraphCache

logger = logging.getLogger(__name__)

__all__ = ["ProjectSlot", "ServiceRegistry"]


@dataclass
class ProjectSlot:
    """Per-project component bundle managed by ``ServiceRegistry``.

    Attributes:
        store: Qdrant-backed vector store for this project.
        searcher: Hybrid search engine wired to the project's
            graph cache via ``graph_provider``.
        vault_indexer: Incremental indexer for ``.vault/`` documents.
        code_indexer: Incremental indexer for source code files.
        graph_cache: Thread-safe TTL graph cache for this project.
    """

    store: VaultStore
    searcher: VaultSearcher
    vault_indexer: VaultIndexer
    code_indexer: CodebaseIndexer
    graph_cache: GraphCache


class ServiceRegistry:
    """Shared GPU models + per-project isolated components.

    The registry owns a single ``EmbeddingModel`` instance shared
    across all projects, and a ``dict[Path, ProjectSlot]`` for
    per-project isolation.  Thread-safe: mutations to ``_projects``
    are guarded by ``_lock``.

    A shared ``gpu_lock`` serializes GPU-bound operations (query
    encoding + reranker predict) so that Qdrant I/O and graph
    reranking can overlap across concurrent requests.

    A shared ``CrossEncoder`` reranker avoids loading ~560 MB VRAM
    per project.  Lazily loaded on first use, thread-safe.
    """

    def __init__(self) -> None:
        """Initialize the registry with empty model and project state."""
        self._model: EmbeddingModel | None = None
        self._projects: dict[Path, ProjectSlot] = {}
        self._lock = threading.Lock()
        self._root_locks: dict[Path, threading.Lock] = {}
        self._gpu_lock = threading.Lock()
        self._reranker: CrossEncoder | None = None
        self._reranker_lock = threading.Lock()
        self._on_close_project: Callable[[Path], None] | None = None
        self._shutting_down = False

    # -- model lifecycle ---------------------------------------------------

    def load_model(self, model_name: str | None = None) -> None:
        """Eagerly load GPU models into ``_model``.

        Args:
            model_name: Optional override for the dense embedding
                model name.  When ``None``, uses the config default.
        """
        from .embeddings import EmbeddingModel

        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            self._model = EmbeddingModel(model_name=model_name)
            logger.info("EmbeddingModel loaded")

    @property
    def model(self) -> EmbeddingModel:
        """Return the shared embedding model.

        Raises:
            RuntimeError: If ``load_model()`` has not been called.
        """
        if self._model is None:
            raise RuntimeError(
                "EmbeddingModel not loaded — call load_model() first",
            )
        return self._model

    @property
    def gpu_lock(self) -> threading.Lock:
        """Return the shared GPU serialization lock."""
        return self._gpu_lock

    def get_reranker(self) -> CrossEncoder:
        """Return the shared CrossEncoder, loading it lazily.

        Thread-safe via double-check lock pattern.  The reranker
        is project-independent (scores text pairs regardless of
        which vault they came from).

        Returns:
            Shared ``CrossEncoder`` instance.

        Raises:
            RuntimeError: If no CUDA GPU is available.
        """
        if self._reranker is not None:
            return self._reranker
        with self._reranker_lock:
            if self._reranker is not None:
                return self._reranker
            import torch
            from sentence_transformers import CrossEncoder

            from .config import get_config

            cfg = get_config()
            if not torch.cuda.is_available():
                msg = (
                    "CUDA GPU required for CrossEncoder reranker. No CUDA device found."
                )
                raise RuntimeError(msg)
            self._reranker = CrossEncoder(
                cfg.reranker_model,
                device="cuda",
                activation_fn=torch.nn.Sigmoid(),
            )
            logger.info(
                "Shared CrossEncoder loaded on %s: %s",
                torch.cuda.get_device_name(0),
                cfg.reranker_model,
            )
            return self._reranker

    # -- per-project slots -------------------------------------------------

    def get_project(self, root: Path) -> ProjectSlot:
        """Return (or lazily create) the component slot for *root*.

        Thread-safe: uses a per-root lock so that concurrent callers
        for *different* roots proceed in parallel, while concurrent
        callers for the *same* root are serialized.

        Args:
            root: Workspace root directory (resolved internally).

        Returns:
            The ``ProjectSlot`` for *root*.

        Raises:
            RuntimeError: If ``load_model()`` has not been called
                or the registry is shutting down.
        """
        # NOTE: The 3-level lock dance (global → per-root → global) exists
        # to satisfy PERF-002 (parallel init of different roots).  In alpha
        # this is unlikely to matter — _create_slot takes ~50-200ms and
        # contention only happens on cold first-request.  If this ever
        # causes trouble, reverting to the original single global-lock
        # double-check pattern is a safe simplification.  The _shutting_down
        # guard was added to prevent a race where close_all() runs while
        # _create_slot() is in-flight (Codex review, 2026-04-04).
        root = root.resolve()
        slot = self._projects.get(root)
        if slot is not None:
            return slot
        # Get or create a per-root lock (global lock held briefly)
        with self._lock:
            slot = self._projects.get(root)
            if slot is not None:
                return slot
            root_lock = self._root_locks.get(root)
            if root_lock is None:
                root_lock = threading.Lock()
                self._root_locks[root] = root_lock
        # Per-root lock: only blocks concurrent callers for the same root
        with root_lock:
            slot = self._projects.get(root)
            if slot is not None:
                return slot
            slot = self._create_slot(root)
            with self._lock:
                if self._shutting_down:
                    # close_all() ran while we were creating the slot.
                    # Don't publish — close the orphaned store.
                    slot.store.close()
                    msg = "ServiceRegistry is shutting down"
                    raise RuntimeError(msg)
                self._projects[root] = slot
        return slot

    def _create_slot(self, root: Path) -> ProjectSlot:
        """Build all per-project components for *root*.

        Wires the ``GraphCache`` into ``VaultSearcher`` via a
        ``graph_provider`` closure so the searcher always gets the
        current cached graph.

        Args:
            root: Resolved workspace root directory.

        Returns:
            A fully wired ``ProjectSlot``.
        """
        from .config import get_config
        from .indexer import CodebaseIndexer, VaultIndexer
        from .search import VaultSearcher
        from .store import VaultStore

        model = self.model  # raises if not loaded
        cfg = get_config()

        store = VaultStore(root)
        try:
            graph_cache = GraphCache(ttl_seconds=cfg.graph_ttl_seconds)
            reranker = self.get_reranker() if cfg.reranker_enabled else None
            searcher = VaultSearcher(
                root,
                model,
                store,
                graph_provider=lambda gc=graph_cache, r=root: gc.get(r),
                gpu_lock=self._gpu_lock,
                reranker=reranker,
            )
            vault_indexer = VaultIndexer(
                root,
                model,
                store,
                gpu_lock=self._gpu_lock,
            )
            code_indexer = CodebaseIndexer(
                root,
                model,
                store,
                gpu_lock=self._gpu_lock,
            )
        except Exception:
            store.close()
            raise

        logger.info("ProjectSlot created for %s", root)
        return ProjectSlot(
            store=store,
            searcher=searcher,
            vault_indexer=vault_indexer,
            code_indexer=code_indexer,
            graph_cache=graph_cache,
        )

    def close_project(self, root: Path) -> None:
        """Close and remove the project slot for *root*.

        Invokes ``_on_close_project`` callback (if set) to stop the
        project's filesystem watcher before closing the store.

        Args:
            root: Workspace root directory.
        """
        root = root.resolve()
        # Stop the watcher BEFORE closing the store to prevent
        # incremental_index() running against a closed store.
        if self._on_close_project is not None:
            self._on_close_project(root)
        with self._lock:
            slot = self._projects.pop(root, None)
            self._root_locks.pop(root, None)
        if slot is not None:
            slot.graph_cache.invalidate()
            slot.store.close()
            logger.info("ProjectSlot closed for %s", root)

    def close_all(self) -> None:
        """Close all project stores and release the model.

        Invokes ``_on_close_project`` for each project to stop
        watchers before closing stores.  Sets ``_shutting_down``
        so any in-flight ``get_project()`` calls don't publish
        new slots after close.
        """
        with self._lock:
            self._shutting_down = True
            roots = list(self._projects.keys())
        # Stop watchers first (outside _lock to avoid deadlock
        # with watcher callbacks that may call get_project)
        if self._on_close_project is not None:
            for root in roots:
                self._on_close_project(root)
        with self._lock:
            for root, slot in self._projects.items():
                slot.store.close()
                logger.info("ProjectSlot closed for %s", root)
            self._projects.clear()
            self._root_locks.clear()
            self._model = None
            self._reranker = None
        logger.info("ServiceRegistry shut down")

    # -- introspection -----------------------------------------------------

    def health(self) -> dict:
        """Return a status dict for diagnostics.

        Returns:
            A dict with ``model_loaded``, ``project_count``, and
            ``projects`` (list of resolved root path strings).
        """
        with self._lock:
            project_list = [str(r) for r in self._projects]
            count = len(self._projects)
        return {
            "model_loaded": self._model is not None,
            "project_count": count,
            "projects": project_list,
        }
