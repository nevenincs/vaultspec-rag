"""Centralized service registry for vaultspec-rag.

Provides a ``ServiceRegistry`` that holds a shared ``EmbeddingModel``
and per-project ``ProjectSlot`` instances, each containing a
``VaultStore``, ``VaultSearcher``, ``VaultIndexer``, ``CodebaseIndexer``,
and ``GraphCache``.  Designed to replace the scattered component
initialization in ``api.py`` and the RAG daemon (``server/_main.py``).
"""

from __future__ import annotations

import contextlib
import gc
import logging
import threading
import time
from dataclasses import dataclass, field
from math import isfinite
from typing import TYPE_CHECKING, Any, Literal, TypedDict

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path
    from types import TracebackType

    from sentence_transformers import CrossEncoder

    from .embeddings import EmbeddingModel
    from .indexer import CodebaseIndexer, DocumentIndexer, VaultIndexer
    from .job_manager.manager import JobManager
    from .search import VaultSearcher
    from .store_runtime import VaultStore

from .graph_cache import GraphCache
from .service_quiesce import (
    ComputeTicket,
    QuiesceSnapshot,
    QuiesceState,
    QuiesceTransition,
    QuiesceTransitionCode,
    ServiceQuiesceController,
    ServiceQuiesceTransitionConflictError,
    ServiceQuiesceTransitionWaitTimeoutError,
)

logger = logging.getLogger(__name__)

# Bound the per-store collection-lock acquisition during shutdown teardown.
# close_all() reaches store.close() only after its 5s busy drain, so a lock
# still held here belongs to a wedged consumer that the graceful drain could
# not release; a short bound then force-closes the client rather than blocking
# the daemon's bounded shutdown on the writer lock indefinitely.
_STORE_FORCE_CLOSE_SECONDS = 5.0


def _validate_resource_transition_timeout(timeout_seconds: float) -> None:
    """Reject invalid waits before they can close compute admission."""
    if not isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError(
            "timeout_seconds must be a finite value greater than or equal to zero"
        )


def _require_present[T](value: T | None, unavailable: str) -> T:
    """Return a lifecycle-owned reference, or name the step that never ran.

    Reaching one of these accessors with its reference unset means a caller
    skipped the lifecycle step that establishes it.  That is a wiring bug, and
    it should name itself rather than surface as an attribute error on ``None``
    several frames deeper.
    """
    if value is None:
        raise RuntimeError(unavailable)
    return value


__all__ = [
    "ComputeLease",
    "GPURebuildEvidence",
    "GPUReleaseEvidence",
    "GPUResidencyTransitionError",
    "ProjectBusyError",
    "ProjectComputeRuntime",
    "ProjectSlot",
    "QuiesceInvariantError",
    "RegistryFullError",
    "SearchLease",
    "ServiceHealth",
    "ServiceRegistry",
]


class ServiceHealth(TypedDict):
    """Diagnostic status returned by :meth:`ServiceRegistry.health`.

    ``nonconforming`` names each warm collection whose stored vectors were not
    produced by the models this process is configured with. It reports only
    what the ensure path already judged, so a health poll never probes the
    backend; collections nobody has opened, and those judged unverifiable, are
    absent rather than listed as problems.
    """

    model_loaded: bool
    reranker_loaded: bool
    cuda: bool
    project_count: int
    projects: list[str]
    nonconforming: list[str]


class RegistryFullError(Exception):
    """Raised by :meth:`ServiceRegistry._lru_victim_root` when no slot is evictable.

    Attributes:
        max_projects: The registry's configured ``max_projects`` cap.
    """

    def __init__(self, max_projects: int) -> None:
        super().__init__(
            f"ServiceRegistry is full ({max_projects} slots, all busy)",
        )
        self.max_projects = max_projects


class ProjectBusyError(RuntimeError):
    """Raised when explicit project closure would invalidate a live lease."""

    def __init__(self, root: Path) -> None:
        super().__init__(f"Project is busy and cannot be closed: {root}")
        self.root = root


class QuiesceInvariantError(RuntimeError):
    """Raised when a GPU residency transition lacks controller evidence."""


class GPUResidencyTransitionError(RuntimeError):
    """Raised when registry-owned GPU residency teardown or rebuild fails."""


@dataclass(frozen=True, slots=True)
class GPUReleaseEvidence:
    """Immutable evidence from one completed GPU dependency detachment."""

    admission_epoch: int
    detached_slot_count: int
    model_detached: bool
    reranker_detached: bool


@dataclass(frozen=True, slots=True)
class GPURebuildEvidence:
    """Immutable evidence from one completed shared GPU dependency rebuild."""

    admission_epoch: int
    model_rebuilt: bool
    reranker_rebuilt: bool
    lazy_slot_count: int


@dataclass(frozen=True, slots=True)
class _GPUResidencyRecipe:
    """Object-free recipe retained across GPU residency transitions."""

    model_name: str | None
    restore_model: bool
    restore_reranker: bool


@dataclass(slots=True)
class _ResourceTransitionOperation:
    """One registry-owned side-effect transition shared by concurrent callers."""

    direction: Literal["pause", "resume"]
    completed: bool = False
    outcome: QuiesceTransition | None = None
    failure: BaseException | None = None


@dataclass(slots=True)
class ProjectComputeRuntime:
    """GPU-dependent components attached to one retained project slot."""

    model: EmbeddingModel
    searcher: VaultSearcher
    vault_indexer: VaultIndexer
    code_indexer: CodebaseIndexer
    document_indexer: DocumentIndexer


@dataclass
class ProjectSlot:
    """Per-project storage identity managed by ``ServiceRegistry``.

    Attributes:
        store: Qdrant-backed vector store for this project.
        graph_cache: Thread-safe TTL graph cache for this project. It remains
            resident through GPU quiescence.
        compute_runtime: The sole slot-reachable owner of GPU-dependent
            model, search, and index components. The registry detaches it
            before it releases resident GPU dependencies.
        last_access: Monotonic seconds of the most recent successful
            :meth:`ServiceRegistry.lease` acquire.  Never mutated or
            read outside the registry's ``_lock``.
        ref_count: Number of currently held leases against this slot.
            Incremented on lease acquire and decremented on release;
            only the sweeper looks at slots with ``ref_count == 0``.
    """

    store: VaultStore
    graph_cache: GraphCache
    compute_runtime: ProjectComputeRuntime | None = None
    last_access: float = field(default=0.0)
    ref_count: int = field(default=0)


@dataclass(slots=True)
class ComputeLease:
    """Ticketed, refcounted access to one project's compute runtime."""

    _root: Path
    _model_name: str | None
    _acquire_ticket: Callable[[], ComputeTicket]
    _acquire_slot: Callable[[Path], contextlib.AbstractContextManager[ProjectSlot]]
    _create_runtime: Callable[[Path, ProjectSlot, str | None], ProjectComputeRuntime]
    _ticket: ComputeTicket | None = field(default=None, init=False)
    _slot_lease: contextlib.AbstractContextManager[ProjectSlot] | None = field(
        default=None,
        init=False,
    )
    _runtime: ProjectComputeRuntime | None = field(default=None, init=False)

    def __enter__(self) -> ComputeLease:
        """Acquire controller admission before the project runtime."""
        self._ticket = self._acquire_ticket()
        try:
            slot_lease = self._acquire_slot(self._root)
            slot = slot_lease.__enter__()
        except BaseException:
            self._ticket.release()
            self._ticket = None
            raise
        self._slot_lease = slot_lease
        try:
            self._runtime = self._create_runtime(
                self._root.resolve(),
                slot,
                self._model_name,
            )
        except BaseException:
            self._slot_lease.__exit__(None, None, None)
            self._slot_lease = None
            self._ticket.release()
            self._ticket = None
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Release slot ownership before making the ticket drainable."""
        self._runtime = None
        try:
            if self._slot_lease is not None:
                self._slot_lease.__exit__(exc_type, exc_val, exc_tb)
        finally:
            self._slot_lease = None
            if self._ticket is not None:
                self._ticket.release()
                self._ticket = None
        return False

    @property
    def runtime(self) -> ProjectComputeRuntime:
        """Return the runtime only while this lease is entered."""
        return _require_present(self._runtime, "compute lease is not active")


@dataclass(slots=True)
class SearchLease:
    """Ticketed, refcounted access to one project's search component."""

    _compute_lease: ComputeLease

    def __enter__(self) -> SearchLease:
        """Acquire the underlying compute lease."""
        self._compute_lease.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Release the underlying compute lease."""
        return self._compute_lease.__exit__(exc_type, exc_val, exc_tb)

    @property
    def searcher(self) -> VaultSearcher:
        """Return the searcher only while this lease is entered."""
        return self._compute_lease.runtime.searcher


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
        # One registry has one controller and therefore one durable job
        # coordinator.  Keeping the manager here makes every lifecycle owner
        # consult the controller that actually owns its admission epoch.
        self._job_manager: JobManager | None = None
        # This condition owns only the right to perform a registry-level
        # resource transition.  It is never held while the owner drains jobs,
        # waits for tickets, or takes GPU/registry locks.
        self._resource_transition_condition = threading.Condition(threading.Lock())
        self._resource_transition: _ResourceTransitionOperation | None = None
        self._reranker: CrossEncoder | None = None
        self._gpu_residency_recipe: _GPUResidencyRecipe | None = None
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
            self._gpu_residency_recipe = _GPUResidencyRecipe(
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
        return _require_present(
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
                self._gpu_residency_recipe = _GPUResidencyRecipe(
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

    def quiesce_resources(self, *, timeout_seconds: float) -> QuiesceTransition:
        """Drain and detach GPU residency through the registry's one façade."""
        return self._run_resource_transition(
            direction="pause",
            timeout_seconds=timeout_seconds,
            run=lambda: self._quiesce_resources_once(timeout_seconds),
        )

    def _quiesce_resources_once(self, timeout_seconds: float) -> QuiesceTransition:
        """Perform the one pause owner's drain and residency-release effects."""
        started = self._quiesce_controller.begin_pause()
        if started.snapshot.state is QuiesceState.QUIESCED:
            return started
        if started.snapshot.state is not QuiesceState.PAUSING:
            return started
        self.create_job_manager().request_quiesce_attempts()
        drained = self._quiesce_controller.wait_for_drain(timeout_seconds)
        if not drained.achieved:
            return drained
        try:
            self._detach_gpu_dependencies(
                admission_epoch=drained.snapshot.admission_epoch,
            )
        except (GPUResidencyTransitionError, QuiesceInvariantError):
            return self._quiesce_controller.fail_transition(
                code=QuiesceTransitionCode.QUIESCE_FAILED,
                reason="gpu_dependency_release_failed",
            )
        return self._quiesce_controller.acknowledge_vram_released()

    def resume_resources(self, *, timeout_seconds: float = 5.0) -> QuiesceTransition:
        """Rebuild shared GPU residency before reopening compute admission.

        Resume is the single operator-facing way back to ``running``, from a
        completed quiesce and from a pause that failed alike.  An operator
        whose pause was stranded has no way to know which of the two they are
        looking at, so the verb - not the operator - picks the recovery.
        """
        return self._run_resource_transition(
            direction="resume",
            timeout_seconds=timeout_seconds,
            run=self._resume_resources_once,
        )

    def _resume_resources_once(self) -> QuiesceTransition:
        """Recover a failed pause or rebuild, prepare recovery, and reopen admission."""
        observed = self._quiesce_controller.snapshot()
        if observed.state is QuiesceState.PAUSING:
            return self._abort_pause_once(observed.admission_epoch)
        warming = self._quiesce_controller.begin_warming()
        if warming.snapshot.state is not QuiesceState.WARMING:
            return warming
        try:
            self._rebuild_gpu_dependencies(
                admission_epoch=warming.snapshot.admission_epoch,
            )
        except (GPUResidencyTransitionError, QuiesceInvariantError):
            return self._quiesce_controller.fail_transition(
                code=QuiesceTransitionCode.WARMUP_FAILED,
                reason="gpu_dependency_rebuild_failed",
            )
        from .job_manager.models import QuiescedResumeStatus

        manager = self.create_job_manager()
        prepared = manager.prepare_quiesced_resume()
        match prepared.status:
            case QuiescedResumeStatus.PREPARED | QuiescedResumeStatus.NO_WORK:
                pass
            case QuiescedResumeStatus.PERSISTENCE_UNPUBLISHED:
                return self._quiesce_controller.fail_transition(
                    code=QuiesceTransitionCode.RESUME_RECOVERY_FAILED,
                    reason="job_resume_persistence_unpublished",
                )
            case QuiescedResumeStatus.PERSISTENCE_PUBLISHED_NOT_DURABLE:
                return self._quiesce_controller.fail_transition(
                    code=QuiesceTransitionCode.RESUME_RECOVERY_FAILED,
                    reason="job_resume_persistence_published_not_durable",
                )
        completed = self._quiesce_controller.complete_warming()
        if completed.achieved and completed.snapshot.state is QuiesceState.RUNNING:
            manager.dispatch_prepared_quiesced_resume(prepared)
        return completed

    def _recover_already_running_resources(
        self,
        snapshot: QuiesceSnapshot,
    ) -> QuiesceTransition:
        """Reconcile retained durable work before reporting an idempotent resume."""
        self.create_job_manager().recover_running_quiesced_resume()
        return QuiesceTransition(
            code=QuiesceTransitionCode.RUNNING,
            achieved=True,
            snapshot=snapshot,
        )

    def _abort_pause_once(self, admission_epoch: int) -> QuiesceTransition:
        """Return a failed pause to running, rebuilding what it already released.

        A resume aimed at ``pausing`` is aimed at a pause that stopped without
        quiescing, so there is no ``warming`` to enter and no quiesced
        evidence to rebuild against.  Restoring residency first is what makes
        the reopening honest: the residency-release failure path detaches the
        shared model and reranker before it reports, so flipping admission
        open without rebuilding them would readmit compute against a stack
        that is no longer there.
        """
        try:
            self._restore_paused_gpu_dependencies(admission_epoch=admission_epoch)
        except (GPUResidencyTransitionError, QuiesceInvariantError):
            return self._quiesce_controller.fail_transition(
                code=QuiesceTransitionCode.QUIESCE_FAILED,
                reason="gpu_dependency_rebuild_failed",
            )
        aborted = self._quiesce_controller.abort_pause()
        if aborted.achieved and aborted.snapshot.state is QuiesceState.RUNNING:
            self.create_job_manager().recover_running_quiesced_resume()
        return aborted

    def _run_resource_transition(
        self,
        *,
        direction: Literal["pause", "resume"],
        timeout_seconds: float,
        run: Callable[[], QuiesceTransition],
    ) -> QuiesceTransition:
        """Claim or join one registry side-effect transition without lock nesting."""
        _validate_resource_transition_timeout(timeout_seconds)
        conflict_direction: Literal["pause", "resume"] | None = None
        operation: _ResourceTransitionOperation | None = None
        owner = False
        with self._resource_transition_condition:
            active = self._resource_transition
            if active is not None:
                if active.direction != direction:
                    conflict_direction = active.direction
                else:
                    operation = active
                    owner = False
            else:
                operation = _ResourceTransitionOperation(direction=direction)
                self._resource_transition = operation
                owner = True
        if conflict_direction is not None:
            raise ServiceQuiesceTransitionConflictError(
                requested_direction=direction,
                active_direction=conflict_direction,
                snapshot=self._quiesce_controller.snapshot(),
            )
        if operation is None:
            raise RuntimeError("resource transition claim did not select an operation")
        if not owner:
            return self._wait_for_resource_transition(
                operation,
                direction=direction,
                timeout_seconds=timeout_seconds,
            )
        observed = self._quiesce_controller.snapshot()
        if direction == "pause" and observed.state is QuiesceState.QUIESCED:
            return self._complete_owned_resource_transition(
                operation,
                lambda: QuiesceTransition(
                    code=QuiesceTransitionCode.ALREADY_QUIESCED,
                    achieved=True,
                    snapshot=observed,
                ),
            )
        if direction == "resume" and observed.state is QuiesceState.RUNNING:
            return self._complete_owned_resource_transition(
                operation,
                lambda: self._recover_already_running_resources(observed),
            )
        return self._complete_owned_resource_transition(operation, run)

    def _wait_for_resource_transition(
        self,
        operation: _ResourceTransitionOperation,
        *,
        direction: Literal["pause", "resume"],
        timeout_seconds: float,
    ) -> QuiesceTransition:
        """Wait boundedly for the owner without taking registry or GPU locks."""
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        with self._resource_transition_condition:
            while not operation.completed:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._resource_transition_condition.wait(
                    timeout=remaining
                ):
                    timed_out = not operation.completed
                    break
            if operation.completed:
                if operation.failure is not None:
                    raise operation.failure
                if operation.outcome is None:
                    raise RuntimeError("completed resource transition has no outcome")
                return operation.outcome
        if timed_out:
            raise ServiceQuiesceTransitionWaitTimeoutError(
                direction=direction,
                snapshot=self._quiesce_controller.snapshot(),
            )
        raise RuntimeError("resource transition waiter left without an outcome")

    def _complete_owned_resource_transition(
        self,
        operation: _ResourceTransitionOperation,
        run: Callable[[], QuiesceTransition],
    ) -> QuiesceTransition:
        """Run owner effects once, then publish their exact terminal truth."""
        outcome: QuiesceTransition | None = None
        failure: BaseException | None = None
        try:
            outcome = run()
            return outcome
        except BaseException as exc:
            failure = exc
            raise
        finally:
            with self._resource_transition_condition:
                operation.outcome = outcome
                operation.failure = failure
                operation.completed = True
                if self._resource_transition is operation:
                    self._resource_transition = None
                self._resource_transition_condition.notify_all()

    def _detach_gpu_dependencies(
        self,
        *,
        admission_epoch: int,
    ) -> GPUReleaseEvidence:
        """Detach GPU objects only after the current epoch has fully drained."""
        snapshot = self._quiesce_controller.snapshot()
        self._require_drained_closed_epoch(
            snapshot,
            admission_epoch,
            expected_state=QuiesceState.PAUSING,
            operation="detach",
        )
        with self._gpu_lock, self._lock:
            detached_slot_count = len(self._projects)
            model_detached = self._model is not None
            reranker_detached = self._reranker is not None
            recipe = self._gpu_residency_recipe
            self._gpu_residency_recipe = _GPUResidencyRecipe(
                model_name=recipe.model_name if recipe is not None else None,
                restore_model=model_detached,
                restore_reranker=reranker_detached,
            )
            for slot in self._projects.values():
                slot.compute_runtime = None
            self._model = None
            self._reranker = None
        self._release_gpu_residency()
        return GPUReleaseEvidence(
            admission_epoch=admission_epoch,
            detached_slot_count=detached_slot_count,
            model_detached=model_detached,
            reranker_detached=reranker_detached,
        )

    def _rebuild_gpu_dependencies(
        self,
        *,
        admission_epoch: int,
    ) -> GPURebuildEvidence:
        """Rebuild shared dependencies while the controller keeps admission closed."""
        snapshot = self._quiesce_controller.snapshot()
        self._require_drained_closed_epoch(
            snapshot,
            admission_epoch,
            expected_state=QuiesceState.WARMING,
            operation="rebuild",
        )
        return self._restore_gpu_residency(admission_epoch=admission_epoch)

    def _restore_paused_gpu_dependencies(self, *, admission_epoch: int) -> None:
        """Rebuild the residency a failed pause released, before it reopens.

        A pause that never got past its drain released nothing, so this must
        not reach for the GPU lock the unfinished slice is still holding -
        doing so would make the way out of a stranded pause wait on exactly
        the work that stranded it.  Only a pause that already detached
        residency has anything to rebuild, and detaching is reachable only
        from a drained closed epoch, so every restore that actually allocates
        is still guarded by the full drained-epoch invariant.
        """
        snapshot = self._quiesce_controller.snapshot()
        if (
            snapshot.state is not QuiesceState.PAUSING
            or snapshot.admission_epoch != admission_epoch
            or snapshot.admissions_open
        ):
            raise QuiesceInvariantError(
                "GPU restore requires the closed epoch its failed pause left behind"
            )
        if not self._gpu_residency_detached():
            return
        self._require_drained_closed_epoch(
            snapshot,
            admission_epoch,
            expected_state=QuiesceState.PAUSING,
            operation="restore",
        )
        self._restore_gpu_residency(admission_epoch=admission_epoch)

    def _gpu_residency_detached(self) -> bool:
        """Report whether the recipe names residency the registry no longer holds."""
        with self._lock:
            recipe = self._gpu_residency_recipe
            if recipe is None:
                return False
            return (recipe.restore_model and self._model is None) or (
                recipe.restore_reranker and self._reranker is None
            )

    def _restore_gpu_residency(self, *, admission_epoch: int) -> GPURebuildEvidence:
        """Reconstruct the recipe's shared GPU stack, failing closed on any error."""
        recipe = self._gpu_residency_recipe
        try:
            with self._gpu_lock:
                if recipe is not None and recipe.restore_model:
                    self._load_model(recipe.model_name)
                    if recipe.restore_reranker:
                        self._get_reranker()
            with self._lock:
                lazy_slot_count = len(self._projects)
                model_rebuilt = self._model is not None
                reranker_rebuilt = self._reranker is not None
        except Exception as exc:
            self._clear_partial_gpu_dependencies()
            raise GPUResidencyTransitionError("GPU dependency rebuild failed") from exc
        return GPURebuildEvidence(
            admission_epoch=admission_epoch,
            model_rebuilt=model_rebuilt,
            reranker_rebuilt=reranker_rebuilt,
            lazy_slot_count=lazy_slot_count,
        )

    def _require_drained_closed_epoch(
        self,
        snapshot: QuiesceSnapshot,
        admission_epoch: int,
        *,
        expected_state: QuiesceState,
        operation: str,
    ) -> None:
        """Reject ``operation`` unless its own closed epoch has drained."""
        if (
            snapshot.state is not expected_state
            or snapshot.admission_epoch != admission_epoch
            or snapshot.admissions_open
            or snapshot.active_compute_tickets != 0
            or not snapshot.drain_complete
            or snapshot.drain_acknowledged_at is None
        ):
            raise QuiesceInvariantError(
                f"GPU {operation} requires a drained closed epoch"
            )

    def _release_gpu_residency(self) -> None:
        """Collect detached references and release allocator cache outside locks."""
        from .memory_probe import (
            rebase_resident_cuda_baseline,
            reset_cuda_peak_memory_stats,
        )

        try:
            gc.collect()
            reset_cuda_peak_memory_stats()
            rebase_resident_cuda_baseline()
        except Exception as exc:
            raise GPUResidencyTransitionError(
                "GPU dependency release cleanup failed"
            ) from exc

    def _clear_partial_gpu_dependencies(self) -> None:
        """Fail closed after rebuild failure while retaining the object-free recipe."""
        with self._gpu_lock, self._lock:
            for slot in self._projects.values():
                slot.compute_runtime = None
            self._model = None
            self._reranker = None
        self._release_gpu_residency()

    # -- per-project slots -------------------------------------------------

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
                    with self._project_admission_condition:
                        if self._shutting_down:
                            msg = "ServiceRegistry is shutting down"
                            raise RuntimeError(msg)
                    created_slot = self._create_slot(resolved)
                    with self._project_admission_condition:
                        if not self._shutting_down:
                            if pin:
                                self._pin_slot_locked(created_slot)
                            self._projects[resolved] = created_slot
                            self._release_project_admission_locked(resolved)
                            released = True
                            published = True
                    if published:
                        return created_slot
                    created_slot.store.close()
                    store_closed = True
                    msg = "ServiceRegistry shut down during project construction"
                    raise RuntimeError(msg)
                finally:
                    if not published:
                        try:
                            if created_slot is not None and not store_closed:
                                created_slot.store.close()
                        finally:
                            self._release_project_admission(resolved)
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

    def quiesce_snapshot(self) -> QuiesceSnapshot:
        """Return the registry-owned controller's read-only lifecycle truth."""
        return self._quiesce_controller.snapshot()

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
                slot.store.close(force_after_seconds=_STORE_FORCE_CLOSE_SECONDS)
                logger.info("ProjectSlot closed for %s", root)
            for store in tuple(self._transient_stores):
                logger.warning(
                    "Force-closing busy transient store %s",
                    store.root_dir,
                )
                store.close(force_after_seconds=_STORE_FORCE_CLOSE_SECONDS)
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
