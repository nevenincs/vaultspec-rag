"""The registry's vocabulary: its slots, leases, evidence, and refusals.

Everything the registry and its mixins both name lives here - the project
slot, the compute and search leases taken against it, the evidence a GPU
release or rebuild produces, and the errors that describe a refusal. It sits
below all of them so the pieces that mutate a registry can share a vocabulary
without importing the registry itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from math import isfinite
from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    import contextlib
    from collections.abc import Callable
    from pathlib import Path
    from types import TracebackType

    from .embeddings import EmbeddingModel
    from .graph_cache import GraphCache
    from .indexer import CodebaseIndexer, DocumentIndexer, VaultIndexer
    from .search import VaultSearcher
    from .service_quiesce import ComputeTicket, QuiesceTransition
    from .store_runtime import VaultStore

logger = logging.getLogger(__name__)

# Bound the per-store collection-lock acquisition during shutdown teardown.
# close_all() reaches store.close() only after its 5s busy drain, so a lock
# still held here belongs to a wedged consumer that the graceful drain could
# not release; a short bound then force-closes the client rather than blocking
# the daemon's bounded shutdown on the writer lock indefinitely.
STORE_FORCE_CLOSE_SECONDS = 5.0


def validate_resource_transition_timeout(timeout_seconds: float) -> None:
    """Reject invalid waits before they can close compute admission."""
    if not isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError(
            "timeout_seconds must be a finite value greater than or equal to zero"
        )


def require_present[T](value: T | None, unavailable: str) -> T:
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
class GPUResidencyRecipe:
    """Object-free recipe retained across GPU residency transitions."""

    model_name: str | None
    restore_model: bool
    restore_reranker: bool


@dataclass(slots=True)
class ResourceTransitionOperation:
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
        return require_present(self._runtime, "compute lease is not active")


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
