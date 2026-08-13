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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from sentence_transformers import CrossEncoder

    from .embeddings import EmbeddingModel
    from .job_manager.manager import JobManager
    from .store_runtime import VaultStore

from ._service_borrower import BorrowerLeaseMixin
from ._service_eviction import ProjectEvictionMixin
from ._service_residency import GPUResidencyMixin
from ._service_types import (
    STORE_FORCE_CLOSE_SECONDS,
    ComputeLease,
    GPUResidencyRecipe,
    GPUResidencyTransitionError,
    ProjectBusyError,
    ProjectComputeRuntime,
    ProjectSlot,
    RegistryFullError,
    ResourceTransitionOperation,
    SearchLease,
    ServiceHealth,
    require_present,
)
from .graph_cache import GraphCache
from .service_quiesce import (
    ComputeTicket,
    ServiceQuiesceController,
)

logger = logging.getLogger(__name__)

__all__ = ["ServiceRegistry"]


class ServiceRegistry(
    GPUResidencyMixin,
    BorrowerLeaseMixin,
    ProjectEvictionMixin,
):
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
        from .config._settings import get_config

        cfg = get_config()
        self._model: EmbeddingModel | None = None
        self._projects: dict[Path, ProjectSlot] = {}
        # A reservation owns one bounded project seat while its root's store
        # is being constructed.  It is deliberately separate from
        # ``_projects``: putting a half-built slot in the public map lets a
        # concurrent lease observe storage before its construction either
        # completed or failed.  The condition shares ``_lock`` so same-root
        # callers join the in-flight admission without reserving a second
        # seat, while unrelated roots continue their own construction.
        self._project_admissions: set[Path] = set()
        # Cold model-free store leases are not project slots, but they still
        # own Qdrant clients and filesystem locks. Track both construction and
        # active use so close_all() can drain or force-close every store the
        # registry admitted, including a constructor racing shutdown.
        self._transient_stores: set[VaultStore] = set()
        self._transient_store_constructions = 0
        # Reentrant so eviction can call close_project() while still
        # holding the lock that selected the victim - closing without
        # releasing the lock first eliminates a TOCTOU window where a
        # concurrent lease() could resurrect the victim.
        self._lock = threading.RLock()
        self._project_admission_condition = threading.Condition(self._lock)
        # One store guard per resolved root, minted on first use and then kept
        # for the registry's life. Entries are deliberately NOT removed when a
        # root's slot is evicted, and removing one is a race, not a cleanup: a
        # per-root mutex only serializes threads that resolve to the *same*
        # object, so dropping the entry while the outgoing store is still
        # closing guarantees the next arrival mints a different lock, takes it
        # uninhibited, and opens a second store against storage this process
        # has not released yet - the exact refusal the guard exists to
        # prevent. Growth is bounded by the number of distinct roots the
        # process ever served, one bare lock each, and close_all() clears it.
        self._root_locks: dict[Path, threading.Lock] = {}
        self._gpu_lock = threading.Lock()
        self._quiesce_controller = ServiceQuiesceController()
        # This is deliberately the capability alone, never a PID or a lease
        # record.  It stays private to the registry and is cleared only after
        # the matching borrower resume has actually succeeded.
        self._borrower_capability: str | None = None
        # One registry has one controller and therefore one durable job
        # coordinator.  Keeping the manager here makes every lifecycle owner
        # consult the controller that actually owns its admission epoch.
        self._job_manager: JobManager | None = None
        # This condition owns only the right to perform a registry-level
        # resource transition.  It is never held while the owner drains jobs,
        # waits for tickets, or takes GPU/registry locks.
        self._resource_transition_condition = threading.Condition(threading.Lock())
        self._resource_transition: ResourceTransitionOperation | None = None
        self._reranker: CrossEncoder | None = None
        self._gpu_residency_recipe: GPUResidencyRecipe | None = None
        self._reranker_lock = threading.Lock()
        self._on_close_project: Callable[[Path], object] | None = None
        self._shutting_down = False
        self._shutdown_complete = False
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

    def prepare_startup(self) -> bool:
        """Reopen this exact registry after one fully completed shutdown.

        Returns:
            ``True`` when a closed registry was reopened; ``False`` for its
            initial service life.

        Raises:
            RuntimeError: If teardown is incomplete or retained state makes
                reopening unsafe.
        """
        with self._lock:
            if not self._shutting_down:
                return False
            if not self._shutdown_complete:
                raise RuntimeError(
                    "ServiceRegistry cannot reopen before shutdown completes"
                )
            if (
                self._projects
                or self._project_admissions
                or self._transient_stores
                or self._transient_store_constructions
                or self._root_locks
                or self._model is not None
                or self._reranker is not None
            ):
                raise RuntimeError(
                    "ServiceRegistry cannot reopen while owned state remains"
                )
            self._shutting_down = False
            self._shutdown_complete = False
            return True

    def load_model(self, model_name: str | None = None) -> None:
        """Eagerly load GPU models into ``_model``.

        Args:
            model_name: Optional override for the dense embedding
                model name.  When ``None``, uses the config default.
        """
        ticket = self._quiesce_controller.acquire_ticket()
        try:
            self._load_model(model_name)
        finally:
            ticket.release()

    def _load_model(self, model_name: str | None = None) -> None:
        """Load the shared embedding model after admission is already held."""
        from .config._types import hf_cache_only
        from .embeddings import EmbeddingModel
        from .memory_probe import sample_resident_cuda_baseline

        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            local_files_only = hf_cache_only()
            self._model = EmbeddingModel(
                model_name=model_name,
                local_files_only=local_files_only,
            )
            reranker_loaded = (
                self._gpu_residency_recipe.restore_reranker
                if self._gpu_residency_recipe is not None
                else self._reranker is not None
            )
            self._gpu_residency_recipe = GPUResidencyRecipe(
                model_name=model_name,
                restore_model=True,
                restore_reranker=reranker_loaded,
            )
            logger.info("EmbeddingModel cache-only mode: %s", local_files_only)
            logger.info("EmbeddingModel loaded")
            # The indexing budget subtracts the resident-model baseline;
            # record it while the freshly-loaded stack is idle so ceilings
            # describe indexing headroom rather than pre-consumed capacity.
            sample_resident_cuda_baseline()

    @property
    def model(self) -> EmbeddingModel:
        """Return the shared embedding model.

        Raises:
            RuntimeError: If ``load_model()`` has not been called.
        """
        return require_present(
            self._model,
            "EmbeddingModel not loaded - call load_model() first",
        )

    @property
    def gpu_lock(self) -> threading.Lock:
        """Return the shared GPU serialization lock."""
        return self._gpu_lock

    def acquire_compute_ticket(self) -> ComputeTicket:
        """Admit route-owned compute without constructing project runtime state.

        Public search routes acquire this before selecting a corpus so each
        source shares the controller's one admission decision.  Project,
        model, and GPU construction remain with the selected operation.
        """
        return self._quiesce_controller.acquire_ticket()

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
        ticket = self._quiesce_controller.acquire_ticket()
        try:
            return self._get_reranker()
        finally:
            ticket.release()

    def _get_reranker(self) -> CrossEncoder:
        """Load the shared reranker after compute admission is already held."""
        if self._reranker is not None:
            return self._reranker
        with self._reranker_lock:
            if self._reranker is not None:
                return self._reranker
            from sentence_transformers import CrossEncoder

            from ._gpu import load_torch
            from .config._settings import get_config
            from .config._types import hf_cache_only

            torch = load_torch()
            cfg = get_config()
            local_files_only = hf_cache_only()
            self._reranker = CrossEncoder(
                cfg.reranker_model,
                device="cuda",
                activation_fn=torch.nn.Sigmoid(),
                max_length=int(cfg.reranker_max_length),
                local_files_only=local_files_only,
            )
            with self._lock:
                model_name = (
                    self._gpu_residency_recipe.model_name
                    if self._gpu_residency_recipe is not None
                    else None
                )
                self._gpu_residency_recipe = GPUResidencyRecipe(
                    model_name=model_name,
                    restore_model=True,
                    restore_reranker=True,
                )
            logger.info(
                "Shared CrossEncoder loaded on %s: %s (cache-only=%s)",
                torch.cuda.get_device_name(0),
                cfg.reranker_model,
                local_files_only,
            )
            # The reranker loads lazily and outside the GPU lock; re-sample
            # the resident baseline so a late load raises it rather than
            # leaving indexing budgets constructed against an understated
            # figure.
            from .memory_probe import sample_resident_cuda_baseline

            sample_resident_cuda_baseline()
            return self._reranker

    @contextlib.contextmanager
    def _root_store_guard(self, resolved: Path) -> Generator[None]:
        """Own one resolved root's open store, and only that root's.

        A local-file store takes an exclusive OS lock on its own storage
        directory and keeps it for as long as it is open.  That lock is per
        open handle, so a second store opened on a root this process already
        has open is refused exactly as a foreign holder's would be.  Every
        path that opens one - slot creation, a cold store lease - and every
        path that closes one - idle sweep, LRU admission, forced eviction -
        runs under this guard, and holds it for as long as that store is open
        rather than merely across construction, which would leave the two
        overlapping in lifetime and racing again.

        Eviction therefore takes the guard *before* the slot leaves
        ``_projects``, never after: the window between the removal and the
        close is precisely when the slot is invisible and its storage lock is
        still held, and an arrival admitted into it is refused by this
        process' own handle.

        The guard is per root, so unrelated roots still open and close in
        parallel and no store-wide mutex is introduced.  It is registry-level
        and always acquired before ``self._lock``, therefore above every
        store's own lifecycle and collection locks and never beneath one.
        Acquiring it while ``self._lock`` is held would invert that order and
        deadlock, which is why victim selection and victim removal are two
        steps rather than one.
        """
        with self._lock:
            root_lock = self._root_locks.get(resolved)
            if root_lock is None and not self._shutting_down:
                root_lock = threading.Lock()
                self._root_locks[resolved] = root_lock
        if root_lock is None:
            # Only close_all() ever removes an entry, and only after the
            # shutdown flag is set - from which point admission refuses every
            # open, so nothing can be racing this root. Minting one here would
            # leave owned state behind that prepare_startup() reads as an
            # incomplete shutdown, and a late teardown must never be skipped.
            yield
            return
        with root_lock:
            yield

    @contextlib.contextmanager
    def _root_store_admission(self, resolved: Path) -> Generator[None]:
        """Admit one opener of *resolved*'s store, refusing a shutting-down registry.

        The guard held is :meth:`_root_store_guard`; opening additionally
        refuses outright once shutdown has begun, so a late arrival never
        starts building storage the drain has already accounted for.

        Raises:
            RuntimeError: If the registry is shutting down.
        """
        with self._root_store_guard(resolved):
            with self._lock:
                if self._shutting_down:
                    msg = "ServiceRegistry is shutting down"
                    raise RuntimeError(msg)
            yield

    def _pin_warm_slot(self, resolved: Path) -> ProjectSlot | None:
        """Bump and return *resolved*'s warm slot, or ``None`` when it has none.

        Raises:
            RuntimeError: If the registry is shutting down.
        """
        with self._lock:
            if self._shutting_down:
                msg = "ServiceRegistry is shutting down"
                raise RuntimeError(msg)
            slot = self._projects.get(resolved)
            if slot is None:
                return None
            slot.last_access = time.monotonic()
            slot.ref_count += 1
            return slot

    def _has_project_admission_capacity_locked(self) -> bool:
        """Return whether another cold project reservation fits the configured cap.

        Caller MUST hold ``_lock``.  A reservation occupies a project seat
        before its store exists, which makes a concurrent multi-root cold
        start obey the same cap as warm slots.
        """
        return self._max_projects <= 0 or (
            len(self._projects) + len(self._project_admissions) < self._max_projects
        )

    def _release_project_admission_locked(self, root: Path) -> None:
        """Release *root*'s construction seat and wake same-root joiners.

        Caller MUST hold ``_lock``.  The notify happens on successful
        publication and on every failure path, so a waiter never inherits an
        abandoned reservation.
        """
        if root in self._project_admissions:
            self._project_admissions.remove(root)
            self._project_admission_condition.notify_all()
        self._complete_shutdown_if_drained_locked()

    def _release_project_admission(self, root: Path) -> None:
        """Release *root*'s construction seat outside an existing lock scope."""
        with self._project_admission_condition:
            self._release_project_admission_locked(root)

    def _complete_shutdown_if_drained_locked(self) -> None:
        """Finalize a shutdown only after every registry-owned store is gone.

        Caller MUST hold ``_lock``.  A bounded close can return while a store
        constructor is still unwinding; retaining the shutdown state and root
        guard identities until that owner releases prevents a subsequent
        startup from opening the same root through a freshly minted guard.
        """
        if (
            self._shutting_down
            and not self._projects
            and not self._project_admissions
            and not self._transient_stores
            and self._transient_store_constructions == 0
        ):
            self._root_locks.clear()
            self._shutdown_complete = True

    def _pin_slot_locked(self, slot: ProjectSlot) -> None:
        """Record one lease before returning a warm or newly published slot."""
        slot.last_access = time.monotonic()
        slot.ref_count += 1

    def _warm_slot_locked(self, resolved: Path, *, pin: bool) -> ProjectSlot | None:
        """Return the published slot, pinning it when a lease is acquiring it.

        Caller MUST hold ``_lock``.
        """
        slot = self._projects.get(resolved)
        if slot is not None and pin:
            self._pin_slot_locked(slot)
        return slot

    def _reserve_after_root_guard(
        self,
        resolved: Path,
        *,
        pin: bool,
    ) -> tuple[ProjectSlot | None, bool]:
        """Resolve a capped no-victim gap beneath *resolved*'s root guard.

        A just-removed LRU victim is invisible to ``_projects`` until its
        guarded teardown finishes.  Joining that guard closes the gap without
        allowing a second root guard or an unaccounted extra project seat.
        """
        with self._root_store_guard(resolved), self._project_admission_condition:
            if self._shutting_down:
                msg = "ServiceRegistry is shutting down"
                raise RuntimeError(msg)
            slot = self._warm_slot_locked(resolved, pin=pin)
            if slot is not None:
                return (slot, False)
            if resolved in self._project_admissions:
                return (None, False)
            if self._has_project_admission_capacity_locked():
                self._project_admissions.add(resolved)
                return (None, True)
            if self._project_admissions:
                self._project_admission_condition.wait()
                return (None, False)
            self._lru_victim_root()
            return (None, False)

    def _replace_lru_with_project_admission(
        self,
        resolved: Path,
        victim_root: Path,
        *,
        pin: bool,
    ) -> tuple[ProjectSlot | None, bool]:
        """Atomically replace *victim_root* with *resolved*'s reservation.

        The root guard is acquired before the registry lock.  Under that lock
        the outgoing warm slot is removed and the incoming reservation is
        recorded together, preserving the bounded-cap invariant throughout
        the later, potentially slow teardown.
        """
        with self._root_store_guard(victim_root):
            victim_slot: ProjectSlot | None = None
            with self._project_admission_condition:
                if self._shutting_down:
                    msg = "ServiceRegistry is shutting down"
                    raise RuntimeError(msg)
                slot = self._warm_slot_locked(resolved, pin=pin)
                if slot is not None:
                    return (slot, False)
                if resolved in self._project_admissions:
                    return (None, False)
                if self._has_project_admission_capacity_locked():
                    self._project_admissions.add(resolved)
                    return (None, True)
                if self._lru_victim_root() != victim_root:
                    return (None, False)
                victim_slot = self._projects.get(victim_root)
                if victim_slot is None or victim_slot.ref_count > 0:
                    return (None, False)
                del self._projects[victim_root]
                self._project_admissions.add(resolved)
            try:
                self._teardown_slot(victim_root, victim_slot, reason="lru")
            except BaseException:
                self._release_project_admission(resolved)
                raise
        return (None, True)

    def _reserve_project_admission(
        self,
        resolved: Path,
        *,
        pin: bool,
    ) -> tuple[ProjectSlot | None, bool]:
        """Return a warm slot or reserve the sole construction seat for *root*."""
        while True:
            with self._project_admission_condition:
                if self._shutting_down:
                    msg = "ServiceRegistry is shutting down"
                    raise RuntimeError(msg)
                slot = self._warm_slot_locked(resolved, pin=pin)
                if slot is not None:
                    return (slot, False)
                if resolved in self._project_admissions:
                    self._project_admission_condition.wait()
                    continue
                if self._has_project_admission_capacity_locked():
                    self._project_admissions.add(resolved)
                    return (None, True)
                try:
                    victim_root = self._lru_victim_root()
                except RegistryFullError:
                    victim_root = None

            if victim_root is None:
                slot, reserved = self._reserve_after_root_guard(resolved, pin=pin)
            else:
                slot, reserved = self._replace_lru_with_project_admission(
                    resolved,
                    victim_root,
                    pin=pin,
                )
            if slot is not None or reserved:
                return (slot, reserved)

    def _refuse_when_shutting_down(self) -> None:
        """Refuse to begin construction once shutdown has been declared."""
        with self._project_admission_condition:
            if self._shutting_down:
                msg = "ServiceRegistry is shutting down"
                raise RuntimeError(msg)

    def _publish_slot_locked(
        self,
        resolved: Path,
        slot: ProjectSlot,
        *,
        pin: bool,
    ) -> bool:
        """Publish *slot* and release its seat, unless shutdown got there first.

        Publication and the seat release happen under one hold, so no caller
        can observe the slot listed while its seat is still reserved. Reports
        whether it published: a shutdown that landed during construction
        leaves the slot for its builder to discard.
        """
        with self._project_admission_condition:
            if self._shutting_down:
                return False
            if pin:
                self._pin_slot_locked(slot)
            self._projects[resolved] = slot
            self._release_project_admission_locked(resolved)
            return True

    def _discard_unpublished_slot(
        self,
        resolved: Path,
        slot: ProjectSlot | None,
        *,
        store_closed: bool,
    ) -> None:
        """Close a slot that never got published and give its seat back.

        The seat is released even when the close raises, because a seat held
        for a slot no caller can reach is a permanent loss of capacity.
        """
        try:
            if slot is not None and not store_closed:
                slot.store.close()
        finally:
            self._release_project_admission(resolved)

    def _construct_admitted_project_slot(
        self,
        resolved: Path,
        *,
        pin: bool,
    ) -> ProjectSlot:
        """Construct and publish a slot after its bounded seat was reserved."""
        released = False
        try:
            with self._root_store_admission(resolved):
                created_slot: ProjectSlot | None = None
                published = False
                store_closed = False
                try:
                    self._refuse_when_shutting_down()
                    created_slot = self._create_slot(resolved)
                    published = self._publish_slot_locked(
                        resolved,
                        created_slot,
                        pin=pin,
                    )
                    if published:
                        released = True
                        return created_slot
                    created_slot.store.close()
                    store_closed = True
                    msg = "ServiceRegistry shut down during project construction"
                    raise RuntimeError(msg)
                finally:
                    if not published:
                        self._discard_unpublished_slot(
                            resolved,
                            created_slot,
                            store_closed=store_closed,
                        )
                        released = True
        except BaseException:
            if not released:
                self._release_project_admission(resolved)
            raise

    def _admit_project_slot(self, resolved: Path, *, pin: bool) -> ProjectSlot:
        """Return or build *resolved*'s slot under one bounded registry seat."""
        slot, reserved = self._reserve_project_admission(resolved, pin=pin)
        if slot is not None:
            return slot
        if not reserved:
            msg = "Project admission did not return a slot or a reservation"
            raise RuntimeError(msg)
        return self._construct_admitted_project_slot(resolved, pin=pin)

    def peek_project(self, root: Path) -> ProjectSlot:
        """Return (or lazily create) *root*'s unpinned registry-owned slot.

        Reserved for watcher wiring, lifespan preload, and tests.  Request
        paths use :meth:`lease`, whose shared admission authority publishes a
        new slot already pinned so it cannot be evicted between creation and
        the caller receiving it.
        """
        return self._admit_project_slot(root.resolve(), pin=False)

    def _store_count(self, root: Path, *, domain: str) -> int:
        """Count points in one collection without loading the GPU model.

        Counting only touches the vector store, so it never loads the
        embedding model. A warm slot's store is reused; otherwise a
        transient store is opened and closed (no slot is cached, and only
        the requested collection is touched). Used to short-circuit a
        search of an empty or unbuilt index to an actionable empty result
        without paying the model-load cost - and, on a CPU-only host,
        without requiring a GPU at all.
        """
        with self.lease_store(root) as store:
            if domain == "code":
                return store.count_code()
            if domain == "document":
                return store.count_document()
            return store.count()

    def vault_doc_count(self, root: Path) -> int:
        """Indexed vault-doc count for *root*, model-free (see _store_count)."""
        return self._store_count(root, domain="vault")

    def code_chunk_count(self, root: Path) -> int:
        """Indexed code-chunk count for *root*, model-free (see _store_count)."""
        return self._store_count(root, domain="code")

    def document_chunk_count(self, root: Path) -> int:
        """Indexed document-chunk count for *root*, without loading a model."""
        return self._store_count(root, domain="document")

    @contextlib.contextmanager
    def _lease_registered_transient_store(
        self,
        resolved: Path,
    ) -> Generator[VaultStore]:
        """Construct and account for one registry-owned non-slot store.

        The caller owns ``resolved``'s root guard for the full context.  Both
        cold read leases and exclusive maintenance leases use this single
        accounting path, so shutdown sees a store before construction begins
        and keeps seeing it until its close completes.
        """
        with self._lock:
            if self._shutting_down:
                msg = "ServiceRegistry is shutting down"
                raise RuntimeError(msg)
            self._transient_store_constructions += 1

        from .store_runtime import VaultStore

        try:
            store = VaultStore(resolved)
        except BaseException:
            with self._lock:
                self._transient_store_constructions -= 1
                self._complete_shutdown_if_drained_locked()
            raise

        with self._lock:
            shutdown_won = self._shutting_down
            if not shutdown_won:
                self._transient_stores.add(store)
                self._transient_store_constructions -= 1

        if shutdown_won:
            # Keep the pending-construction count live until close completes,
            # so close_all() cannot observe a false zero while this late store
            # still owns a client or the local storage lock.
            try:
                store.close()
            finally:
                with self._lock:
                    self._transient_store_constructions -= 1
                    self._complete_shutdown_if_drained_locked()
            msg = "ServiceRegistry shut down during store construction"
            raise RuntimeError(msg)

        try:
            yield store
        finally:
            try:
                store.close()
            finally:
                # Keep the lease visible to close_all() until resource
                # release completes; removing it first would let shutdown
                # return while the Qdrant client or local storage lock was
                # still closing.
                with self._lock:
                    self._transient_stores.discard(store)
                    self._complete_shutdown_if_drained_locked()

    @contextlib.contextmanager
    def lease_store(self, root: Path) -> Generator[VaultStore]:
        """Lease only *root*'s store without loading or admitting GPU models.

        A warm project slot is pinned through the registry's existing
        ``ref_count`` so idle, LRU, forced, and shutdown teardown cannot close
        its store while the caller is using it. A cold root uses one transient
        store that is always closed on exit and is never added to the project
        registry, preserving model-free empty-index probes and status reads.

        A cold lease holds the root's store admission for its whole life, so a
        concurrent slot creation for the same root waits for it rather than
        opening a second store against storage this process has already locked.
        A warm lease takes no such guard: the slot's store is shared, and
        serializing on it would queue every reader of that root behind another.

        Args:
            root: Workspace root directory.

        Yields:
            A live ``VaultStore`` for the resolved root.

        Raises:
            RuntimeError: If the registry is shutting down.
        """
        resolved = root.resolve()
        with contextlib.ExitStack() as stack:
            slot = self._pin_warm_slot(resolved)
            if slot is None:
                stack.enter_context(self._root_store_admission(resolved))
                # A slot may have been published while this waited for
                # admission; adopt it rather than opening a second store.
                slot = self._pin_warm_slot(resolved)
            if slot is not None:
                stack.callback(self._release, slot)
                yield slot.store
                return
            with self._lease_registered_transient_store(resolved) as store:
                yield store

    @contextlib.contextmanager
    def lease_maintenance_store(self, root: Path) -> Generator[VaultStore]:
        """Lease one root exclusively for registry-owned store maintenance.

        Maintenance can mutate or remove collection state, so it never shares
        a warm slot.  It first takes the root guard, then rejects an active
        slot before any watcher or registry mutation; an unleased warm slot is
        removed and closed under that same guard.  The replacement store uses
        the normal transient accounting path, letting shutdown drain or force
        close maintenance exactly as it does a cold reader.

        Raises:
            ProjectBusyError: If an active lease pins the warm project slot.
            RuntimeError: If the registry is shutting down.
        """
        resolved = root.resolve()
        with self._root_store_admission(resolved):
            with self._lock:
                slot = self._projects.get(resolved)
                if slot is not None and slot.ref_count > 0:
                    raise ProjectBusyError(resolved)
                if slot is not None:
                    del self._projects[resolved]
            if slot is not None:
                self._teardown_slot(resolved, slot, reason="maintenance")
            with self._lease_registered_transient_store(resolved) as store:
                yield store

    # -- lease API ---------------------------------------------------------

    @contextlib.contextmanager
    def lease(self, root: Path) -> Generator[ProjectSlot]:
        """Acquire a refcounted lease against the slot for *root*.

        Use as ``with registry.lease(root) as slot: ...``.  On enter,
        the slot is created if necessary (honoring the LRU cap and
        triggering an idle sweep), its ``last_access`` is updated, and
        its ``ref_count`` is incremented.  Any victim the admission or the
        sweep selects is fully evicted before this yields, so the caller
        never observes more than ``max_projects`` slots and never begins
        work while an evicted slot still owns its files and sockets.
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
        slot = self._acquire(root)
        try:
            yield slot
        finally:
            self._release(slot)

    def compute_lease(
        self,
        root: Path,
        *,
        model_name: str | None = None,
    ) -> ComputeLease:
        """Return a ticketed lease for one project's compute operation.

        Compute admission is acquired before the project slot, model, or
        runtime can be reached. A quiescing registry therefore refuses a new
        operation before it can retain GPU-resident dependencies.
        """
        return ComputeLease(
            root,
            model_name,
            self._quiesce_controller.acquire_ticket,
            self.lease,
            self._runtime_for,
        )

    def search_lease(self, root: Path) -> SearchLease:
        """Return a ticketed lease for one project's search component."""
        return SearchLease(self.compute_lease(root))

    def create_job_manager(self) -> JobManager:
        """Return the sole manager with this registry's controller authority."""
        from .job_manager.manager import JobManager

        with self._lock:
            manager = self._job_manager
            if manager is None:
                manager = JobManager(quiesce_controller=self._quiesce_controller)
                self._job_manager = manager
            return manager

    def discard_job_manager(self) -> None:
        """Drop the cached manager so the next build reads config afresh.

        The manager caches its non-terminal ceiling at construction and owns
        every active and terminal record, so a caller that clears job state
        without dropping it keeps both the old ceiling and the old records.
        """
        with self._lock:
            self._job_manager = None

    def _create_slot(self, root: Path) -> ProjectSlot:
        """Build one storage-only project slot for *root*.

        The slot retains its store, graph cache, and project identity through
        resource quiescence. Its GPU-dependent runtime is built only through
        :meth:`compute_lease` after compute admission succeeds.

        Args:
            root: Resolved workspace root directory.

        Returns:
            A storage-only ``ProjectSlot``.
        """
        from .config._settings import get_config
        from .store_runtime import VaultStore

        cfg = get_config()

        store = VaultStore(root)
        try:
            graph_cache = GraphCache(ttl_seconds=cfg.graph_ttl_seconds)
        except BaseException:
            store.close()
            raise

        logger.info("ProjectSlot created for %s", root)
        return ProjectSlot(
            store=store,
            graph_cache=graph_cache,
        )

    def _runtime_for(
        self,
        root: Path,
        slot: ProjectSlot,
        model_name: str | None,
    ) -> ProjectComputeRuntime:
        """Return a ticket-protected runtime, creating it once per slot.

        Construction runs outside ``_lock`` and the lock is taken only to
        publish the result, exactly as slot creation and the GPU residency
        rebuild already do.  ``_lock`` covers the whole registry - leasing,
        refcounting, health, eviction, every root - while building a runtime
        reaches the shared model and reranker loads, the longest step the
        registry has.  Holding it across that turns one root's first request
        into a stall on every other root's bookkeeping, and on ``/health``,
        which is the window a supervisor is watching.

        The re-check under the lock adopts a concurrent builder's runtime
        rather than clobbering it.  Losing that race costs only a few cheap
        objects: the model and reranker are shared and internally
        double-checked, so the duplicate build never loads either twice.
        """
        runtime = slot.compute_runtime
        if runtime is not None:
            return runtime
        built = self._create_compute_runtime(root, slot, model_name)
        with self._lock:
            published = slot.compute_runtime
            if published is not None:
                return published
            slot.compute_runtime = built
            return built

    def _create_compute_runtime(
        self,
        root: Path,
        slot: ProjectSlot,
        model_name: str | None,
    ) -> ProjectComputeRuntime:
        """Build the model-dependent components for one already-admitted slot."""
        from .config._settings import get_config
        from .indexer import CodebaseIndexer, DocumentIndexer, VaultIndexer
        from .search import VaultSearcher

        self._load_model(model_name)
        model = self.model
        cfg = get_config()
        reranker = self._get_reranker() if cfg.reranker_enabled else None
        searcher = VaultSearcher(
            root,
            model,
            slot.store,
            graph_provider=lambda gc=slot.graph_cache, r=root: gc.get(r),
            gpu_lock=self._gpu_lock,
            reranker=reranker,
        )
        vault_indexer = VaultIndexer(
            root,
            model,
            slot.store,
            gpu_lock=self._gpu_lock,
        )
        code_indexer = CodebaseIndexer(
            root,
            model,
            slot.store,
            options=CodebaseIndexer.Options(gpu_lock=self._gpu_lock),
        )
        document_indexer = DocumentIndexer(
            root,
            model,
            slot.store,
            gpu_lock=self._gpu_lock,
        )
        return ProjectComputeRuntime(
            model=model,
            searcher=searcher,
            vault_indexer=vault_indexer,
            code_indexer=code_indexer,
            document_indexer=document_indexer,
        )

    def has_live_lease(self, root: Path) -> bool:
        """Return whether any worker currently holds *root*'s project slot.

        A store binds its collection name once at construction and keeps it for
        its whole life, so a lease taken before a publication swap is still
        resolving the collection that swap superseded. Maintenance asks this
        before dropping one: a live lease means a reader in this process may
        still be reading it, and no amount of waiting makes that observation
        safe to ignore.

        Answers only for this process. Readers elsewhere are unobservable,
        which is why the caller pairs this with a persisted grace window rather
        than treating a false here as proof that nothing holds the collection.
        """
        resolved = root.resolve()
        with self._lock:
            slot = self._projects.get(resolved)
            return slot is not None and slot.ref_count > 0

    def close_project(self, root: Path) -> None:
        """Close and remove the project slot for *root*.

        Signals the watcher-stop callback, then uses the same atomic busy check
        as explicit eviction before closing the unleased store. A live lease
        fails closed instead of invalidating storage beneath its worker.

        Args:
            root: Workspace root directory.

        Raises:
            ProjectBusyError: If the project has one or more active leases.
        """
        root = root.resolve()
        # Signal intake even when the slot is not present yet: a deferred cold
        # watcher warm may be between registration and peek_project(), and a
        # not-found eviction must not let that stale watcher generation publish
        # later. Successful try_evict teardown repeats the safe stop signal
        # after atomically removing the unleased slot.
        if self._on_close_project is not None:
            self._on_close_project(root)
        _evicted, reason = self.try_evict(root)
        if reason == "busy":
            raise ProjectBusyError(root)

    def close_all(self) -> None:
        """Shut down the registry with a bounded 5-second busy drain.

        Implements a "graceful drain": sets ``_shutting_down``
        first so new :meth:`lease` calls raise, polls every 100ms for
        busy slots and transient model-free stores to drain, and force-closes
        any still-busy stores after a 5-second deadline (logging a warning for
        each). A transient constructor racing shutdown closes its store before
        unregistering its pending construction.

        The 5.0s constant is intentionally NOT configurable - long
        enough for worst-case search latency, short enough that
        uvicorn lifespan shutdown never looks hung.
        """
        with self._lock:
            self._shutting_down = True
            self._shutdown_complete = False
            # Wake same-root admission joiners so they observe shutdown rather
            # than waiting for a constructor that is about to be drained.
            self._project_admission_condition.notify_all()

        # Bounded drain: 5.0 seconds is intentionally hardcoded.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            with self._lock:
                busy = (
                    any(s.ref_count > 0 for s in self._projects.values())
                    or bool(self._transient_stores)
                    or self._transient_store_constructions > 0
                    or bool(self._project_admissions)
                )
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
                slot.store.close(force_after_seconds=STORE_FORCE_CLOSE_SECONDS)
                logger.info("ProjectSlot closed for %s", root)
            for store in tuple(self._transient_stores):
                logger.warning(
                    "Force-closing busy transient store %s",
                    store.root_dir,
                )
                store.close(force_after_seconds=STORE_FORCE_CLOSE_SECONDS)
            # Active context managers retain their registration until their
            # own finally block completes.  Clearing here would claim that a
            # force-closed maintenance or cold lease had finished releasing
            # its root guard when its owner is still unwinding.
            if self._transient_store_constructions:
                logger.warning(
                    "ServiceRegistry shutdown deadline reached with %d store "
                    "construction(s) still pending; each late constructor will "
                    "close before returning",
                    self._transient_store_constructions,
                )
            self._projects.clear()
            self._model = None
            self._reranker = None
            self._complete_shutdown_if_drained_locked()

        # Dropping the references is not enough: both stacks are reachable only
        # through reference cycles, so their device memory survives until a
        # collection runs, and the blocks a collection frees stay checked out
        # of the device until the allocator cache is flushed. One release
        # sequence owns all three steps; a shortened copy here once skipped the
        # cache flush, leaving the freed stacks invisible to the device-wide
        # free reading a later in-process load is admitted against. A failure
        # has nowhere to go at shutdown, but it must not pass silently either.
        try:
            self._release_gpu_residency()
        except GPUResidencyTransitionError:
            logger.warning(
                "GPU residency release failed during shutdown; the device may "
                "hold memory this process no longer references",
                exc_info=True,
            )
        logger.info("ServiceRegistry shut down")

    # -- introspection -----------------------------------------------------

    def health(self) -> ServiceHealth:
        """Return a status dict for diagnostics.

        Returns:
            A dict with ``model_loaded``, ``project_count``, and
            ``projects`` (list of resolved root path strings).
        """
        from . import store_schema

        with self._lock:
            project_list = [str(r) for r in self._projects]
            count = len(self._projects)
            # Read the verdicts the ensure path already recorded. No backend
            # call happens here: a health poll must stay cheap, and a store
            # nobody has opened has nothing to report either way.
            nonconforming = sorted(
                f"{root}:{collection}"
                for root, slot in self._projects.items()
                for collection, verdict in slot.store.conformance_verdicts().items()
                if verdict.verdict == store_schema.NONCONFORMING
            )
        return {
            "model_loaded": self._model is not None,
            "reranker_loaded": self._reranker is not None,
            "cuda": (
                self._model is not None
                and getattr(self._model, "device", None) == "cuda"
            ),
            "project_count": count,
            "projects": project_list,
            "nonconforming": nonconforming,
        }
