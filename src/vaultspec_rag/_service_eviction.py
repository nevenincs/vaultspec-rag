"""Choosing which project slot to give up, and tearing it down.

Idle expiry and least-recently-used replacement, plus the teardown every
eviction runs. A slot with a live lease is never a victim: eviction picks
only from what nothing is currently using.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from ._service_types import ProjectSlot, RegistryFullError

logger = logging.getLogger("vaultspec_rag.service")


if TYPE_CHECKING:
    import threading
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path


class ProjectEvictionMixin:
    """Selects and evicts project slots the registry no longer needs warm."""

    _idle_ttl_seconds: float
    _lock: threading.RLock
    _max_projects: int
    _on_close_project: Callable[[Path], object] | None
    _projects: dict[Path, ProjectSlot]

    if TYPE_CHECKING:
        # Provided by the registry this mixes into.
        def _admit_project_slot(self, resolved: Path, *, pin: bool) -> ProjectSlot: ...

        def _root_store_guard(self, resolved: Path) -> AbstractContextManager[None]: ...

        @property
        def max_projects(self) -> int: ...

        @property
        def idle_ttl_seconds(self) -> float: ...

    def _acquire(self, root: Path) -> ProjectSlot:
        """Admit or fetch *root*'s slot and increment its ``ref_count``.

        Must NOT be called outside :meth:`lease`.  The shared project-admission
        authority pins a newly published slot while it still holds the
        registry lock, closing the old gap where :meth:`peek_project` exposed
        an unpinned slot before this method could increment it.

        Args:
            root: Workspace root directory.

        Returns:
            The acquired ``ProjectSlot``, with its ``ref_count`` already
            incremented.

        Raises:
            RegistryFullError: When admission would exceed the LRU cap
                and no slot is evictable.
            RuntimeError: When the registry is shutting down.
        """
        acquired_slot = self._admit_project_slot(root.resolve(), pin=True)
        try:
            with self._lock:
                idle_roots = self._idle_victim_roots()
            self._evict_idle_roots(idle_roots)
            return acquired_slot
        except BaseException:
            # _admit_project_slot pinned before returning.  If a later idle
            # teardown fails, lease() never receives the slot to release it.
            # Roll it back before preserving that original teardown failure.
            self._release(acquired_slot)
            raise

    def _release(self, slot: ProjectSlot) -> None:
        """Decrement a slot's ``ref_count`` under ``_lock``."""
        with self._lock:
            if slot.ref_count > 0:
                slot.ref_count -= 1

    # -- eviction ---------------------------------------------------------

    def _is_idle(self, slot: ProjectSlot, now: float) -> bool:
        """Return whether *slot* is unleased and older than the idle TTL."""
        return (
            slot.ref_count == 0 and (now - slot.last_access) >= self._idle_ttl_seconds
        )

    def _idle_victim_roots(self) -> list[Path]:
        """Return the roots whose slot is idle-evictable right now.

        Caller MUST hold ``self._lock``.  Returns with the lock still held.
        Selection only: nothing is removed here, because removal has to
        happen under the victim's own store guard and that guard cannot be
        taken beneath ``self._lock`` without inverting the registry's lock
        order.  :meth:`_evict_idle_roots` re-tests this predicate under the
        guard, so a root leased in between is left alone.
        """
        if self._idle_ttl_seconds <= 0:
            return []
        now = time.monotonic()
        return [r for r, s in self._projects.items() if self._is_idle(s, now)]

    def _evict_idle_roots(self, roots: list[Path]) -> None:
        """Evict each root of *roots* that is still idle, under its own guard.

        Caller MUST NOT hold ``self._lock``.  A root's store guard is taken
        before its slot leaves ``_projects`` and released only once that
        slot's store has closed, so no arrival for that root is ever admitted
        into the window where the slot is invisible but its storage lock is
        still held.
        """
        for root in roots:
            with self._root_store_guard(root):
                with self._lock:
                    slot = self._projects.get(root)
                    if slot is None or not self._is_idle(slot, time.monotonic()):
                        continue
                    del self._projects[root]
                self._teardown_slot(root, slot, reason="idle")

    def _lru_victim_root(self) -> Path:
        """Return the root to evict to make room for one more slot.

        Caller MUST hold ``self._lock`` and have already established that no
        project-admission seat is free.  Selection only: the caller takes the
        selected root's guard before rechecking and replacing it atomically.

        Raises:
            RegistryFullError: When the registry is at capacity and every
                slot is leased.
        """
        candidates = [
            (slot.last_access, r)
            for r, slot in self._projects.items()
            if slot.ref_count == 0
        ]
        if not candidates:
            raise RegistryFullError(self._max_projects)
        candidates.sort()
        return candidates[0][1]

    def _teardown_slot(
        self,
        root: Path,
        slot: ProjectSlot,
        *,
        reason: str,
    ) -> None:
        """Run the watcher-stop + store-close teardown for an evicted slot.

        Caller MUST have already removed *slot* from ``self._projects``.
        Caller MUST NOT hold ``self._lock``, and MUST hold *root*'s
        :meth:`_root_store_guard` from before that removal until after this
        returns: the store keeps its exclusive storage lock until ``close()``
        completes, so a guard released any earlier readmits an opener into a
        window where the refusal blames a foreign process.  Mirrors the
        teardown order used by :meth:`close_project` (watcher first, then
        store) so that ``incremental_index()`` cannot fire against a closed
        store.
        """
        if self._on_close_project is not None:
            self._on_close_project(root)
        slot.graph_cache.invalidate()
        slot.store.close()
        logger.info("Evicted ProjectSlot %s (reason=%s)", root, reason)

    def try_evict(self, root: Path) -> tuple[bool, str]:
        """Manually evict *root* atomically.

        Used by the ``evict_project`` MCP admin tool and the
        ``vaultspec-rag server projects evict`` CLI command.  The existence
        and busy checks and the removal all happen under ``self._lock`` so a
        concurrent :meth:`lease` cannot race the evict, and the whole
        sequence runs under *root*'s store guard so a concurrent opener
        cannot race the close either.  Teardown runs outside ``self._lock``
        per the same protocol as :meth:`_evict_idle_roots` and
        :meth:`_make_room_for_admission`.

        Returns:
            ``(True, "forced")`` when the slot was evicted,
            ``(False, "busy")`` when ``ref_count > 0``,
            ``(False, "not_found")`` when no slot exists for *root*.
        """
        target = root.resolve()
        with self._root_store_guard(target):
            with self._lock:
                slot = self._projects.get(target)
                if slot is None:
                    return (False, "not_found")
                if slot.ref_count > 0:
                    return (False, "busy")
                del self._projects[target]
            self._teardown_slot(target, slot, reason="forced")
        return (True, "forced")

    def busy_roots(self) -> list[Path]:
        """Return a list of resolved roots with ``ref_count > 0``."""
        with self._lock:
            return [r for r, s in self._projects.items() if s.ref_count > 0]

    def projects_envelope(self, projects: list[dict[str, Any]]) -> dict[str, Any]:
        """Wrap an already-shaped project list in its published bounds.

        The per-project entries differ by surface - the route publishes the
        slots as they are, the consolidated state adds derived timings - but
        the bounds beside them are this registry's own and are read the same
        way by both. Written out at each surface they agree only until one
        gains a field, and nothing reports the disagreement because each
        surface still answers with a well-formed payload.
        """
        return {
            "projects": projects,
            "max_projects": self.max_projects,
            "idle_ttl_seconds": self.idle_ttl_seconds,
        }

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
