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
    """Raised by :meth:`ServiceRegistry._collect_lru_victim` when no slot is evictable.

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

    def peek_project(self, root: Path) -> ProjectSlot:
        """Return (or lazily create) the slot for *root* without bumping refcount.

        Reserved for non-request-path callers (watcher wiring, lifespan
        preload, tests).  Request-path callers MUST use :meth:`lease`
        instead so eviction refcount accounting is honored.

        Thread-safe: uses a three-level lock dance so that concurrent
        callers for *different* roots proceed in parallel, while
        concurrent callers for the *same* root are serialized.

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
    def lease_store(self, root: Path) -> Generator[VaultStore]:
        """Lease only *root*'s store without loading or admitting GPU models.

        A warm project slot is pinned through the registry's existing
        ``ref_count`` so idle, LRU, forced, and shutdown teardown cannot close
        its store while the caller is using it. A cold root uses one transient
        store that is always closed on exit and is never added to the project
        registry, preserving model-free empty-index probes and status reads.

        Args:
            root: Workspace root directory.

        Yields:
            A live ``VaultStore`` for the resolved root.

        Raises:
            RuntimeError: If the registry is shutting down.
        """
        resolved = root.resolve()
        with self._lock:
            if self._shutting_down:
                msg = "ServiceRegistry is shutting down"
                raise RuntimeError(msg)
            slot = self._projects.get(resolved)
            if slot is not None:
                slot.last_access = time.monotonic()
                slot.ref_count += 1
            else:
                # Register ownership before VaultStore performs any filesystem
                # or Qdrant effect. close_all() observes this pending admission
                # even if shutdown begins while construction is outside _lock.
                self._transient_store_constructions += 1

        if slot is not None:
            try:
                yield slot.store
            finally:
                self._release(slot)
            return

        from .store_runtime import VaultStore

        try:
            store = VaultStore(resolved)
        except BaseException:
            with self._lock:
                self._transient_store_constructions -= 1
            raise

        with self._lock:
            shutdown_won = self._shutting_down
            if not shutdown_won:
                self._transient_stores.add(store)
                self._transient_store_constructions -= 1

        if shutdown_won:
            # Keep the pending-construction count live until close completes,
            # so close_all() cannot observe a false zero and return while this
            # late store still owns a client or local storage lock.
            try:
                store.close()
            finally:
                with self._lock:
                    self._transient_store_constructions -= 1
            msg = "ServiceRegistry shut down during store construction"
            raise RuntimeError(msg)

        try:
            yield store
        finally:
            try:
                store.close()
            finally:
                # Keep the lease visible to close_all() until resource release
                # completes; removing it first would let shutdown return while
                # the Qdrant client or local storage lock was still closing.
                with self._lock:
                    self._transient_stores.discard(store)

    # -- lease API ---------------------------------------------------------

    @contextlib.contextmanager
    def lease(self, root: Path) -> Generator[ProjectSlot]:
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

    def quiesce_snapshot(self) -> QuiesceSnapshot:
        """Return the registry-owned controller's read-only lifecycle truth."""
        return self._quiesce_controller.snapshot()

    def _acquire(
        self,
        root: Path,
    ) -> tuple[ProjectSlot, list[tuple[Path, ProjectSlot, str]]]:
        """Admit or fetch *root*'s slot and increment its ``ref_count``.

        Must NOT be called outside :meth:`lease`.  Holds ``_lock`` for
        the slot lookup / admission / refcount mutation / opportunistic
        idle sweep.  Slot creation itself runs outside ``_lock`` via
        :meth:`peek_project` to preserve the parallel cold-start
        guarantee.  Returns the acquired slot
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
        ``vaultspec-rag server projects evict`` CLI command.  All
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
        graph_cache = GraphCache(ttl_seconds=cfg.graph_ttl_seconds)

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

        # Bounded drain: 5.0 seconds is intentionally hardcoded.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            with self._lock:
                busy = (
                    any(s.ref_count > 0 for s in self._projects.values())
                    or bool(self._transient_stores)
                    or self._transient_store_constructions > 0
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
            self._transient_stores.clear()
            if self._transient_store_constructions:
                logger.warning(
                    "ServiceRegistry shutdown deadline reached with %d store "
                    "construction(s) still pending; each late constructor will "
                    "close before returning",
                    self._transient_store_constructions,
                )
            self._projects.clear()
            self._root_locks.clear()
            self._model = None
            self._reranker = None
            self._shutdown_complete = True

        # Dropping the references is not enough: both stacks are reachable only
        # through reference cycles, so their device memory survives until a
        # collection runs. Until it does the process holds gigabytes it no
        # longer has a handle on, and the recorded resident baseline keeps
        # describing them - which would put every later index ceiling out of
        # reach, since enforcement clamps a job's peak net of that figure at
        # zero. Collect, then re-establish the baseline from what is genuinely
        # left resident.
        from .memory_probe import rebase_resident_cuda_baseline

        gc.collect()
        rebase_resident_cuda_baseline()
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
