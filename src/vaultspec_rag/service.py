"""Centralized service registry for vaultspec-rag.

Provides a ``ServiceRegistry`` that holds a shared ``EmbeddingModel``
and per-project ``ProjectSlot`` instances, each containing a
``VaultStore``, ``VaultSearcher``, ``VaultIndexer``, ``CodebaseIndexer``,
and ``GraphCache``.  Designed to replace the scattered component
initialization in ``api.py`` and the RAG daemon (``server/_main.py``).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from sentence_transformers import CrossEncoder

    from .embeddings import EmbeddingModel
    from .indexer import CodebaseIndexer, VaultIndexer
    from .search import VaultSearcher
    from .store import VaultStore

from .graph_cache import GraphCache

logger = logging.getLogger(__name__)

__all__ = ["ProjectSlot", "RegistryFullError", "ServiceRegistry"]


class RegistryFullError(Exception):
    """Raised by :meth:`ServiceRegistry._collect_lru_victim` when no slot is evictable.

    Attributes:
        max_projects: The registry's configured ``max_projects`` cap.
    """

    def __init__(self, max_projects: int) -> None:
        super().__init__(
            f"ServiceRegistry is full ({max_projects} slots, all busy)",
        )
        self.max_projects = max_projects


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
        last_access: Monotonic seconds of the most recent successful
            :meth:`ServiceRegistry.lease` acquire.  Never mutated or
            read outside the registry's ``_lock``.
        ref_count: Number of currently held leases against this slot.
            Incremented on lease acquire and decremented on release;
            only the sweeper looks at slots with ``ref_count == 0``.
    """

    store: VaultStore
    searcher: VaultSearcher
    vault_indexer: VaultIndexer
    code_indexer: CodebaseIndexer
    graph_cache: GraphCache
    last_access: float = field(default=0.0)
    ref_count: int = field(default=0)


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
        from .config import get_config

        cfg = get_config()
        self._model: EmbeddingModel | None = None
        self._projects: dict[Path, ProjectSlot] = {}
        # Reentrant so eviction can call close_project() while still
        # holding the lock that selected the victim - closing without
        # releasing the lock first eliminates a TOCTOU window where a
        # concurrent lease() could resurrect the victim.
        self._lock = threading.RLock()
        self._root_locks: dict[Path, threading.Lock] = {}
        self._gpu_lock = threading.Lock()
        self._reranker: CrossEncoder | None = None
        self._reranker_lock = threading.Lock()
        self._on_close_project: Callable[[Path], None] | None = None
        self._shutting_down = False
        self._idle_ttl_seconds: float = float(cfg.service_idle_ttl_seconds)
        self._max_projects: int = int(cfg.service_max_projects)

    # -- eviction config --------------------------------------------------

    @property
    def max_projects(self) -> int:
        """Return the configured LRU cap (``0`` disables the cap)."""
        return self._max_projects

    @property
    def idle_ttl_seconds(self) -> float:
        """Return the idle-sweep TTL (``0`` disables idle eviction)."""
        return self._idle_ttl_seconds

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
                "EmbeddingModel not loaded - call load_model() first",
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

    def peek_project(self, root: Path) -> ProjectSlot:
        """Return (or lazily create) the slot for *root* without bumping refcount.

        Reserved for non-request-path callers (watcher wiring, lifespan
        preload, tests).  Request-path callers MUST use :meth:`lease`
        instead so eviction refcount accounting is honored.

        Thread-safe: uses the same three-level lock dance as the
        service-graph ADR so that concurrent callers for *different*
        roots proceed in parallel, while concurrent callers for the
        *same* root are serialized.

        Args:
            root: Workspace root directory (resolved internally).

        Returns:
            The ``ProjectSlot`` for *root*.

        Raises:
            RuntimeError: If ``load_model()`` has not been called or
                the registry is shutting down.
        """
        root = root.resolve()
        slot = self._projects.get(root)
        if slot is not None:
            return slot
        with self._lock:
            if self._shutting_down:
                msg = "ServiceRegistry is shutting down"
                raise RuntimeError(msg)
            slot = self._projects.get(root)
            if slot is not None:
                return slot
            root_lock = self._root_locks.get(root)
            if root_lock is None:
                root_lock = threading.Lock()
                self._root_locks[root] = root_lock
        with root_lock:
            slot = self._projects.get(root)
            if slot is not None:
                return slot
            slot = self._create_slot(root)
            with self._lock:
                if self._shutting_down:
                    slot.store.close()
                    msg = "ServiceRegistry is shutting down"
                    raise RuntimeError(msg)
                self._projects[root] = slot
        return slot

    # -- lease API ---------------------------------------------------------

    @contextlib.contextmanager
    def lease(self, root: Path) -> Iterator[ProjectSlot]:
        """Acquire a refcounted lease against the slot for *root*.

        Use as ``with registry.lease(root) as slot: ...``.  On enter,
        the slot is created if necessary (honoring the LRU cap and
        triggering an idle sweep), its ``last_access`` is updated, and
        its ``ref_count`` is incremented.  Any victim slots that the
        admission/sweep selected are popped from the registry while
        the lock is held and then torn down *after* the lock has been
        fully released, never via manual ``release()`` on an ``RLock``.
        On exit, the refcount is decremented.  Eviction never touches a
        slot with ``ref_count > 0``.

        Args:
            root: Workspace root directory.

        Yields:
            The leased ``ProjectSlot``.

        Raises:
            RegistryFullError: When admission would exceed
                ``max_projects`` and every existing slot is busy.
            RuntimeError: If ``load_model()`` has not been called or
                the registry is shutting down.
        """
        slot, victims = self._acquire(root)
        # Run teardown OUTSIDE the lock and BEFORE yielding so the
        # caller never observes more than ``max_projects`` slots and
        # so the file/socket resources held by victims are released
        # before any caller-side work begins.
        for v_root, v_slot, reason in victims:
            self._teardown_slot(v_root, v_slot, reason=reason)
        try:
            yield slot
        finally:
            self._release(slot)

    def _acquire(
        self,
        root: Path,
    ) -> tuple[ProjectSlot, list[tuple[Path, ProjectSlot, str]]]:
        """Admit or fetch *root*'s slot and increment its ``ref_count``.

        Must NOT be called outside :meth:`lease`.  Holds ``_lock`` for
        the slot lookup / admission / refcount mutation / opportunistic
        idle sweep.  Slot creation itself runs outside ``_lock`` via
        :meth:`peek_project` to preserve the service-graph ADR's
        parallel cold-start guarantee.  Returns the acquired slot
        plus a (possibly empty) list of victims that the caller MUST
        tear down after the lock is fully released.

        Args:
            root: Workspace root directory.

        Returns:
            ``(slot, victims)`` - *slot* is the acquired
            ``ProjectSlot`` (already bumped); *victims* is a list of
            ``(root, slot, reason)`` triples that were popped from the
            registry under the lock and need teardown.

        Raises:
            RegistryFullError: When admission would exceed the LRU cap
                and no slot is evictable.
            RuntimeError: When the registry is shutting down.
        """
        resolved = root.resolve()
        victims: list[tuple[Path, ProjectSlot, str]] = []
        # Track the slot whose ref_count we have already incremented
        # so we can roll the increment back on the failure path.
        # Without this, an exception raised AFTER ``ref_count += 1`` but
        # BEFORE the value is returned would leak the increment forever:
        # ``lease`` never sees the slot, never calls ``_release``, and
        # the slot becomes ineligible for eviction (ref_count > 0
        # disqualifies it from both the idle sweep and LRU admission).
        acquired_slot: ProjectSlot | None = None

        try:
            # Fast path: slot already exists. Still take _lock to
            # mutate ref_count and last_access atomically.
            with self._lock:
                if self._shutting_down:
                    msg = "ServiceRegistry is shutting down"
                    raise RuntimeError(msg)
                slot = self._projects.get(resolved)
                if slot is not None:
                    slot.last_access = time.monotonic()
                    slot.ref_count += 1
                    acquired_slot = slot
                    victims.extend(self._collect_idle_victims())
                    return slot, victims
                # LRU admission may collect a victim under the lock.
                victims.extend(self._collect_lru_victim())

            # Create (outside _lock so GPU parallel init is preserved).
            slot = self.peek_project(resolved)
            with self._lock:
                if self._shutting_down:
                    msg = "ServiceRegistry is shutting down"
                    raise RuntimeError(msg)
                slot.last_access = time.monotonic()
                slot.ref_count += 1
                acquired_slot = slot
                victims.extend(self._collect_idle_victims())
            return slot, victims
        except BaseException:
            # Rollback BEFORE re-raising:
            # 1. Decrement ref_count on the target slot if we already
            #    bumped it - otherwise the slot is stuck busy forever
            #    and the caller never sees it via lease().
            # 2. Tear down popped victims so their Qdrant handles and
            #    watchers do not leak.
            # Both rollback steps swallow their own errors so a cleanup
            # failure cannot mask the original exception.
            if acquired_slot is not None:
                try:
                    self._release(acquired_slot)
                except Exception:
                    logger.exception(
                        "Failed to roll back ref_count during _acquire rollback",
                    )
            for v_root, v_slot, v_reason in victims:
                try:
                    self._teardown_slot(v_root, v_slot, reason=v_reason)
                except Exception:
                    logger.exception(
                        "Failed to tear down victim %s during _acquire rollback",
                        v_root,
                    )
            raise

    def _release(self, slot: ProjectSlot) -> None:
        """Decrement a slot's ``ref_count`` under ``_lock``."""
        with self._lock:
            if slot.ref_count > 0:
                slot.ref_count -= 1

    # -- eviction ---------------------------------------------------------

    def _collect_idle_victims(self) -> list[tuple[Path, ProjectSlot, str]]:
        """Pop and return slots whose ``last_access`` is older than the idle TTL.

        Caller MUST hold ``self._lock``.  Returns with the lock still
        held.  Victims are popped from ``_projects`` while the lock is
        held so a concurrent :meth:`lease` cannot observe them and
        resurrect them once teardown begins.  Teardown itself (watcher
        stop → graph invalidate → store close) is the *caller's*
        responsibility once the lock has been fully released - the
        manual ``RLock.release()/acquire()`` dance is fragile because
        a single ``release()`` on a recursively-held ``RLock`` only
        decrements the recursion counter and does not actually let
        other threads in.
        """
        if self._idle_ttl_seconds <= 0:
            return []
        now = time.monotonic()
        victims: list[tuple[Path, ProjectSlot, str]] = []
        for r, s in list(self._projects.items()):
            if s.ref_count == 0 and (now - s.last_access) >= self._idle_ttl_seconds:
                self._projects.pop(r, None)
                self._root_locks.pop(r, None)
                victims.append((r, s, "idle"))
        return victims

    def _collect_lru_victim(self) -> list[tuple[Path, ProjectSlot, str]]:
        """Pop and return the LRU victim if the registry is at capacity.

        Caller MUST hold ``self._lock``.  Returns with the lock still
        held.  If the registry is below ``max_projects`` returns an
        empty list.  Otherwise selects the slot with the smallest
        ``last_access`` among ``ref_count == 0`` candidates, pops it
        from ``_projects``, and returns it as a single-element list.
        Raises :class:`RegistryFullError` when every slot is busy.
        """
        if self._max_projects <= 0:
            return []
        if len(self._projects) < self._max_projects:
            return []
        candidates = [
            (slot.last_access, r)
            for r, slot in self._projects.items()
            if slot.ref_count == 0
        ]
        if not candidates:
            raise RegistryFullError(self._max_projects)
        candidates.sort()
        victim_root = candidates[0][1]
        victim_slot = self._projects.pop(victim_root, None)
        self._root_locks.pop(victim_root, None)
        if victim_slot is None:
            return []
        return [(victim_root, victim_slot, "lru")]

    def _teardown_slot(
        self,
        root: Path,
        slot: ProjectSlot,
        *,
        reason: str,
    ) -> None:
        """Run the watcher-stop + store-close teardown for an evicted slot.

        Caller MUST have already removed *slot* from ``self._projects``.
        Caller MUST NOT hold ``self._lock``.  Mirrors the teardown order
        used by :meth:`close_project` (watcher first, then store) so that
        ``incremental_index()`` cannot fire against a closed store.
        """
        if self._on_close_project is not None:
            self._on_close_project(root)
        slot.graph_cache.invalidate()
        slot.store.close()
        logger.info("Evicted ProjectSlot %s (reason=%s)", root, reason)

    def try_evict(self, root: Path) -> tuple[bool, str]:
        """Manually evict *root* atomically.

        Used by the ``evict_project`` MCP admin tool and the
        ``vaultspec-rag server service projects evict`` CLI command.  All
        decisions (existence + busy check + pop) happen under
        ``self._lock`` so a concurrent :meth:`lease` cannot race the
        evict.  Teardown runs outside the lock per the same protocol
        as :meth:`_collect_idle_victims` and :meth:`_collect_lru_victim`.

        Returns:
            ``(True, "forced")`` when the slot was evicted,
            ``(False, "busy")`` when ``ref_count > 0``,
            ``(False, "not_found")`` when no slot exists for *root*.
        """
        target = root.resolve()
        with self._lock:
            slot = self._projects.get(target)
            if slot is None:
                return (False, "not_found")
            if slot.ref_count > 0:
                return (False, "busy")
            self._projects.pop(target, None)
            self._root_locks.pop(target, None)
        self._teardown_slot(target, slot, reason="forced")
        return (True, "forced")

    def busy_roots(self) -> list[Path]:
        """Return a list of resolved roots with ``ref_count > 0``."""
        with self._lock:
            return [r for r, s in self._projects.items() if s.ref_count > 0]

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a list of per-slot diagnostic dicts (for ``list_projects``).

        Each dict contains ``root`` (resolved Path), ``last_access``
        (monotonic float), ``ref_count`` (int), and ``idle_seconds``
        (float, derived from ``time.monotonic() - last_access``).
        """
        now = time.monotonic()
        with self._lock:
            return [
                {
                    "root": r,
                    "last_access": slot.last_access,
                    "ref_count": slot.ref_count,
                    "idle_seconds": max(0.0, now - slot.last_access),
                }
                for r, slot in self._projects.items()
            ]

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
        """Shut down the registry with a bounded 5-second busy drain.

        Implements ADR D6 "graceful drain": sets ``_shutting_down``
        first so new :meth:`lease` calls raise, polls every 100ms for
        busy slots to drain, and force-closes any still-busy slots
        after a 5-second deadline (logging a warning for each).

        The 5.0s constant is intentionally NOT configurable per
        ADR D6 - long enough for worst-case search latency, short
        enough that uvicorn lifespan shutdown never looks hung.
        """
        with self._lock:
            self._shutting_down = True

        # ADR D6: bounded drain.  5.0 seconds is intentionally hardcoded.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            with self._lock:
                busy = any(s.ref_count > 0 for s in self._projects.values())
            if not busy:
                break
            time.sleep(0.1)

        with self._lock:
            roots = list(self._projects.keys())

        # Stop watchers first (outside _lock to avoid deadlock with
        # watcher callbacks that may call back into the registry).
        if self._on_close_project is not None:
            for root in roots:
                self._on_close_project(root)

        with self._lock:
            for root, slot in list(self._projects.items()):
                if slot.ref_count > 0:
                    logger.warning(
                        "Force-closing busy slot %s (ref_count=%d)",
                        root,
                        slot.ref_count,
                    )
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
