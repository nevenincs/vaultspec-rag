"""Managed filesystem-watcher control and indexing execution.

Uses watchfiles.awatch() to monitor .vault/ for documentation changes
and the project root for source code changes. Triggers incremental
re-indexing when changes are detected.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

from anyio.to_thread import run_sync as _run_in_thread
from watchfiles import (
    Change,
    awatch,  # pyright: ignore[reportUnknownVariableType]  # watchfiles awatch return type is partially stubbed
)

from . import jobs as _jobs
from ._backoff import capped_exponential
from .indexer._content_policy import ContentKind
from .indexer._route_migration import prior_stored_owners
from .job_manager.models import JobAttemptContext, JobExecutionResult
from .job_models import (
    IndexResilienceSnapshot,
    JobInitiator,
    JobMode,
    JobOperation,
    JobOutcomeStatus,
    JobSnapshot,
    JobSource,
    JobSpec,
    JobState,
)
from .logging_config import log_event
from .registry import get_registry
from .watcher_policy import (
    _CONFIG_FILENAMES,
    _is_code_change,
    _is_document_change,
    _is_vault_change,
    _refresh_watcher_policy,
)
from .watcher_retry import (
    WatcherRetryDecision,
    WatcherRetryPolicy,
    WatcherRetryState,
    WatcherRetryStateError,
    WatcherRetryUnavailableError,
    WatcherSource,
)
from .watcher_retry_settlement import register_retry_settlement

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .graph_cache import GraphCache
    from .indexer import CodebaseIndexer, DocumentIndexer, VaultIndexer
    from .indexer._codebase_indexer import CodeExecutionPreflight
    from .indexer._document_indexer import DocumentExecutionPreflight
    from .indexer._resolved_policy import ResolvedIndexPolicy
    from .indexer._vault_prep import IndexResult
    from .service import ProjectSlot, ServiceRegistry

logger = logging.getLogger(__name__)
_CANCELLATION_DURABILITY_SECONDS = 3.0
_CANCELLATION_FALLBACK_SECONDS = 2.0
_STATE_TRANSACTION_WORKER_SLOTS = threading.BoundedSemaphore(4)
_CANCELLATION_FALLBACK_WORKER_SLOTS = threading.BoundedSemaphore(2)
# Idle re-entry interval for the watch loop, in milliseconds. The pending sets
# carry forward any change suppressed by the per-source cooldown, but they are
# only re-examined when the loop body runs, and the body runs only when awatch
# yields. Without an idle yield, a change that lands during a cooldown window on
# an otherwise quiet tree is never reconciled - the deletion-eviction failure
# mode. Asking awatch to yield an empty change set on this interval re-enters the
# loop so the cooldown is re-checked and the trailing batch is flushed. The Rust
# watcher already wakes on this cadence to honour the stop event, so yielding the
# timeout adds no extra wakeups.
_WATCH_IDLE_TICK_MS = 1000

# Operator cancellation deliberately leaves watcher convergence dirty. Retry
# delay grows only across consecutive cancellations and is capped so automatic
# freshness remains both non-thrashing and finite.
_WATCH_REPLACEMENT_BACKOFF_BASE_SECONDS = 1.0
_WATCH_REPLACEMENT_BACKOFF_MAX_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class _DurableTransactionRequest:
    """Durability identity and recovery behavior for one state operation."""

    source: WatcherSource
    root_dir: Path
    action: str
    cancellation_fallback: Callable[[], object] | None = None


@dataclass(frozen=True, slots=True)
class _ObservedSource:
    """One watcher domain's observed-event persistence request."""

    observed: bool
    source: WatcherSource
    retry_policy: WatcherRetryPolicy


@dataclass(frozen=True, slots=True)
class _WatcherChangeRouting:
    """Immutable routing dependencies for one watcher intake batch."""

    root_dir: Path
    vault_dir: Path
    policy: ResolvedIndexPolicy | None
    vault_slot: _WatcherConvergenceSlot
    code_slot: _WatcherConvergenceSlot
    document_slot: _WatcherConvergenceSlot | None


@dataclass(frozen=True, slots=True)
class _WatcherReconciliation:
    """Timing and cache dependencies shared by one convergence pass."""

    cooldown: float
    now: float
    graph_cache: GraphCache


@dataclass(frozen=True, slots=True)
class _UnstartedFailure:
    """The manager and durable-retry identity of one dispatch failure."""

    manager: _jobs.JobManager
    job_id: str
    attempt: int
    message: str
    action: str
    reason: str


@dataclass(frozen=True, slots=True)
class _TransitionLogContext:
    """State accumulated while releasing one observed watcher job."""

    watcher_owned: bool
    pending_count: int
    replacement_delay: float
    error: BaseException | None


@dataclass(frozen=True, slots=True)
class _ManagedAttemptInputs:
    """Admission proof and shared cache for one watcher manager dispatch."""

    initial_attempt: int
    initial_paths: frozenset[Path]
    code_preflight: CodeExecutionPreflight | None
    document_preflight: DocumentExecutionPreflight | None = None
    secondary_graph_cache: GraphCache | None = None


@dataclass(frozen=True, slots=True)
class _ManagedAttemptScope:
    """Resolved execution authority for one manager attempt number."""

    paths: frozenset[Path] | None
    captured_paths: frozenset[Path]
    requires_unscoped: bool
    code_preflight: CodeExecutionPreflight | None
    document_preflight: DocumentExecutionPreflight | None


@dataclass(slots=True)
class _WatcherConvergenceSlot:
    """Thread-safe ownership of one root/source convergence generation."""

    source: JobSource
    root: Path
    registry: ServiceRegistry
    retry_policy: WatcherRetryPolicy
    lock: RLock = field(default_factory=RLock)
    job_id: str | None = None
    watcher_owned: bool = False
    held_paths: set[Path] = field(default_factory=set)
    pending_paths: set[Path] = field(default_factory=set)
    attempt_paths: dict[int, frozenset[Path]] = field(default_factory=dict)
    last_success: float = 0.0
    replacement_not_before: float = 0.0
    replacement_streak: int = 0
    observed_state: JobState | None = None
    retry_attempt_generations: dict[int, int] = field(default_factory=dict)
    retry_unscoped_attempts: set[int] = field(default_factory=set)
    settlement_task: asyncio.Task[None] | None = None

    @property
    def command(self) -> str:
        return f"watcher_{self.source.value}_index"

    def add_dirty(self, path: Path) -> None:
        """Record a new generation without merging it into a running attempt."""
        with self.lock:
            self.pending_paths.add(path)

    def has_work(self) -> bool:
        with self.lock:
            return bool(self.held_paths or self.pending_paths)

    def pending_count(self) -> int:
        with self.lock:
            return len(self.held_paths | self.pending_paths)

    def defer_replacement(self, now: float) -> float:
        """Extend the replacement backoff after another failed attempt.

        Three callers scheduled this for themselves, each rewriting the same
        streak increment, capped exponential, and deadline assignment. Returns
        the delay so a caller can report what it scheduled without recomputing
        it from the streak - which is how the copies came about.
        """
        with self.lock:
            self.replacement_streak += 1
            delay = capped_exponential(
                self.replacement_streak - 1,
                base=_WATCH_REPLACEMENT_BACKOFF_BASE_SECONDS,
                cap=_WATCH_REPLACEMENT_BACKOFF_MAX_SECONDS,
            )
            self.replacement_not_before = now + delay
            return delay

    def dirty_paths(self) -> frozenset[Path]:
        """Snapshot the exact paths eligible for the next watcher attempt."""
        with self.lock:
            return frozenset(self.held_paths | self.pending_paths)

    def capture_prevalidated_attempt(
        self,
        attempt: int,
        paths: frozenset[Path],
    ) -> frozenset[Path]:
        """Bind only the prevalidated paths, leaving later events pending."""
        with self.lock:
            self.pending_paths.difference_update(paths)
            self.held_paths.update(paths)
            self.attempt_paths[attempt] = paths
            return paths

    def captured_attempt(self, attempt: int) -> frozenset[Path] | None:
        """Return the immutable path batch already bound to an attempt."""
        with self.lock:
            return self.attempt_paths.get(attempt)

    def capture_attempt(self, attempt: int) -> frozenset[Path]:
        """Move the current pending generation into one immutable attempt batch."""
        with self.lock:
            self.held_paths.update(self.pending_paths)
            self.pending_paths.clear()
            captured = frozenset(self.held_paths)
            self.attempt_paths[attempt] = captured
            return captured


async def _run_bounded_transaction[T](
    operation: Callable[[], T],
    slots: threading.BoundedSemaphore,
    unavailable_message: str,
) -> T:
    """Run locking and durable I/O on a worker thread behind a capacity gate.

    ``slots`` bounds a dedicated worker pool so callers competing for one
    pool can never starve another; each caller passes its own pool.
    """

    def _guarded_operation() -> T:
        if not slots.acquire(blocking=False):
            raise WatcherRetryUnavailableError(unavailable_message)
        try:
            return operation()
        finally:
            slots.release()

    return await _run_in_thread(_guarded_operation, abandon_on_cancel=True)


async def _await_retry_transaction[T](
    transaction: asyncio.Task[T],
    cancellation_deadline: float | None,
) -> T:
    """Await one transaction, imposing a hard bound only after cancellation."""
    if cancellation_deadline is None:
        return await asyncio.shield(transaction)
    remaining = cancellation_deadline - time.monotonic()
    if remaining <= 0.0:
        raise TimeoutError
    return await asyncio.wait_for(asyncio.shield(transaction), timeout=remaining)


@dataclass
class _DurableRetryState:
    """Mutable bookkeeping shared across one durable-retry loop.

    Held as an object so the attempt helper can arm the cancellation
    deadline and throttle logging without threading four in/out values
    through its signature.
    """

    delay: float = 0.01
    next_log_at: float = 0.0
    cancellation_requested: bool = False
    cancellation_deadline: float | None = None

    def request_cancellation(self) -> None:
        """Record a cancellation and arm the durability deadline once.

        The first request starts the clock; later ones keep it, so
        repeated cancellation can never extend the window.
        """
        self.cancellation_requested = True
        if self.cancellation_deadline is None:
            self.cancellation_deadline = (
                time.monotonic() + _CANCELLATION_DURABILITY_SECONDS
            )

    def expired(self) -> bool:
        """Whether the durability window has closed."""
        return (
            self.cancellation_deadline is not None
            and time.monotonic() >= self.cancellation_deadline
        )

    def sleep_seconds(self) -> float:
        """Backoff delay, clamped to whatever durability budget remains."""
        if self.cancellation_deadline is None:
            return self.delay
        remaining = max(0.0, self.cancellation_deadline - time.monotonic())
        return min(self.delay, remaining)


async def _attempt_durable_transaction[T](
    operation: Callable[[], T],
    *,
    request: _DurableTransactionRequest,
    state: _DurableRetryState,
) -> tuple[T, bool] | None:
    """Drive one transaction to a durable outcome.

    Returns the result when it commits, or ``None`` when the caller
    should back off and start a fresh transaction. Raises
    ``CancelledError`` once the durability window closes.
    """
    transaction = asyncio.create_task(
        _run_bounded_transaction(
            operation,
            _STATE_TRANSACTION_WORKER_SLOTS,
            "watcher retry state worker capacity is unavailable",
        )
    )
    while True:
        try:
            result = await _await_retry_transaction(
                transaction,
                state.cancellation_deadline,
            )
        except asyncio.CancelledError:
            state.request_cancellation()
            continue
        except TimeoutError:
            transaction.cancel()
            transaction.add_done_callback(_consume_background_result)
            await _complete_cancellation_handoff(
                request.cancellation_fallback,
                source=request.source,
                root_dir=request.root_dir,
                action=request.action,
            )
            raise asyncio.CancelledError from None
        except WatcherRetryUnavailableError as exc:
            now = time.monotonic()
            if now >= state.next_log_at:
                log_event(
                    logger,
                    "service.watcher",
                    "state_transaction_retry",
                    severity=logging.WARNING,
                    root=request.root_dir,
                    source=request.source,
                    action=request.action,
                    retry_delay_seconds=f"{state.delay:.3f}",
                    error=exc,
                )
                state.next_log_at = now + 5.0
            return None
        else:
            return result, state.cancellation_requested


async def _run_durable_retry_transaction[T](
    operation: Callable[[], T],
    *,
    source: WatcherSource,
    root_dir: Path,
    action: str,
    cancellation_fallback: Callable[[], object] | None = None,
) -> tuple[T, bool]:
    """Retry transient state I/O and defer cancellation until it is durable."""
    state = _DurableRetryState()
    request = _DurableTransactionRequest(
        source=source,
        root_dir=root_dir,
        action=action,
        cancellation_fallback=cancellation_fallback,
    )
    while True:
        if state.expired():
            await _complete_cancellation_handoff(
                request.cancellation_fallback,
                source=source,
                root_dir=root_dir,
                action=action,
            )
            raise asyncio.CancelledError
        outcome = await _attempt_durable_transaction(
            operation,
            request=request,
            state=state,
        )
        if outcome is not None:
            return outcome
        try:
            await asyncio.sleep(state.sleep_seconds())
        except asyncio.CancelledError:
            state.request_cancellation()
        state.delay = min(1.0, state.delay * 2.0)


async def _complete_cancellation_handoff(
    fallback: Callable[[], object] | None,
    *,
    source: WatcherSource,
    root_dir: Path,
    action: str,
) -> None:
    """Attempt the lock-independent handoff within its separate hard bound."""
    if fallback is None:
        return
    if await _run_cancellation_fallback(fallback):
        return
    log_event(
        logger,
        "service.watcher",
        "state_handoff_timeout",
        severity=logging.ERROR,
        root=root_dir,
        source=source,
        action=action,
        timeout_seconds=f"{_CANCELLATION_FALLBACK_SECONDS:.0f}",
    )


def _consume_background_result[T](task: asyncio.Task[T]) -> None:
    """Observe a detached fallback result after its caller reached its deadline."""
    with suppress(asyncio.CancelledError, Exception):
        task.result()


def _abandon_fallback(task: asyncio.Task[object]) -> None:
    """Detach a fallback whose deadline passed, without losing its result."""
    task.cancel()
    task.add_done_callback(_consume_background_result)


async def _attempt_fallback_transaction(
    operation: Callable[[], object], *, deadline: float
) -> bool | None:
    """Drive one handoff attempt.

    Returns ``True`` on success, ``False`` when the deadline closed, or
    ``None`` when the caller should back off and try again.
    """
    remaining = deadline - time.monotonic()
    task = asyncio.create_task(
        _run_bounded_transaction(
            operation,
            _CANCELLATION_FALLBACK_WORKER_SLOTS,
            "watcher recovery handoff worker capacity is unavailable",
        )
    )
    while True:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                _abandon_fallback(task)
                return False
            continue
        except TimeoutError:
            _abandon_fallback(task)
            return False
        except WatcherRetryUnavailableError:
            return None
        else:
            return True


async def _run_cancellation_fallback(operation: Callable[[], object]) -> bool:
    """Retry transient handoff I/O within one cancellation-owned deadline."""
    deadline = time.monotonic() + _CANCELLATION_FALLBACK_SECONDS
    delay = 0.01
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return False
        outcome = await _attempt_fallback_transaction(operation, deadline=deadline)
        if outcome is not None:
            return outcome
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return False
        with suppress(asyncio.CancelledError):
            await asyncio.sleep(min(delay, remaining))
        delay = min(0.25, delay * 2.0)


async def _persist_convergence_pending(
    policy: WatcherRetryPolicy,
    *,
    source: WatcherSource,
    root_dir: Path,
) -> bool:
    """Persist one accepted event batch even when shutdown races it."""
    _state, cancellation_requested = await _run_durable_retry_transaction(
        policy.mark_convergence_pending,
        source=source,
        root_dir=root_dir,
        action="mark_convergence_pending",
        cancellation_fallback=policy.write_recovery_marker,
    )
    return cancellation_requested


async def _await_shielded_persist_outcomes(
    tasks: list[asyncio.Task[bool]],
) -> tuple[list[bool | BaseException], bool]:
    """Await every persist task under shield, absorbing outer cancellation.

    Cancelling the awaiting coroutine must not cancel the shielded gather: it
    cancels the still-unsettled member tasks instead, then re-awaits until
    every task actually settles, so no accepted event batch is left
    un-persisted by a cancellation that raced its commit.
    """
    cancellation_requested = False
    grouped = asyncio.gather(*tasks, return_exceptions=True)
    while True:
        try:
            outcomes = await asyncio.shield(grouped)
        except asyncio.CancelledError:
            cancellation_requested = True
            for unsettled in tasks:
                if not unsettled.done():
                    unsettled.cancel()
        else:
            return outcomes, cancellation_requested


def _collect_persist_outcomes(
    outcomes: list[bool | BaseException],
) -> tuple[bool, list[Exception]]:
    """Fold gathered per-source outcomes into a cancellation flag and errors."""
    cancellation_requested = False
    errors: list[Exception] = []
    for outcome in outcomes:
        if isinstance(outcome, asyncio.CancelledError):
            cancellation_requested = True
        elif isinstance(outcome, Exception):
            errors.append(outcome)
        elif isinstance(outcome, bool):
            cancellation_requested |= outcome
        else:
            raise outcome
    return cancellation_requested, errors


async def _persist_observed_sources(
    observed_sources: tuple[_ObservedSource, ...],
    *,
    root_dir: Path,
) -> bool:
    """Settle every source in one accepted batch before delivering cancellation."""
    tasks = [
        asyncio.create_task(
            _persist_convergence_pending(
                observed.retry_policy,
                source=observed.source,
                root_dir=root_dir,
            )
        )
        for observed in observed_sources
        if observed.observed
    ]
    outcomes, shield_cancellation = await _await_shielded_persist_outcomes(tasks)
    collected_cancellation, errors = _collect_persist_outcomes(outcomes)
    cancellation_requested = shield_cancellation or collected_cancellation
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise ExceptionGroup("watcher intent persistence failed", errors)
    return cancellation_requested


async def _admit_watcher_attempt(
    policy: WatcherRetryPolicy,
    *,
    source: WatcherSource,
    root_dir: Path,
) -> WatcherRetryDecision:
    """Admit atomically, settling a claim if cancellation raced its commit."""
    attempt_token = policy.reserve_admission()
    decision, cancellation_requested = await _run_durable_retry_transaction(
        lambda: policy.admit_reserved(attempt_token, now=time.time()),
        source=source,
        root_dir=root_dir,
        action="admit",
        cancellation_fallback=policy.write_recovery_marker,
    )
    if not cancellation_requested:
        return decision
    attempt_generation = decision.attempt_generation
    if decision.admitted and attempt_generation is not None:
        await _run_durable_retry_transaction(
            lambda: policy.record_interrupted(attempt_generation),
            source=source,
            root_dir=root_dir,
            action="interrupt_cancelled_admission",
            cancellation_fallback=policy.write_recovery_marker,
        )
    raise asyncio.CancelledError


def _raise_if_cancellation_requested(requested: bool) -> None:
    """Deliver cancellation only after the selected durable outcome exists."""
    if requested:
        raise asyncio.CancelledError


async def _initialize_retry_policies(
    root_dir: Path,
    *,
    document_enabled: bool,
) -> tuple[WatcherRetryPolicy, WatcherRetryPolicy, WatcherRetryPolicy | None]:
    """Open one durable retry authority per enabled indexing domain."""
    initialized: list[tuple[WatcherRetryPolicy, bool]] = []
    for source in (WatcherSource.VAULT, WatcherSource.CODE):
        initialized.append(
            await _run_durable_retry_transaction(
                lambda selected=source: WatcherRetryPolicy.for_root(root_dir, selected),
                source=source,
                root_dir=root_dir,
                action="initialize",
            )
        )
    document: tuple[WatcherRetryPolicy, bool] | None = None
    if document_enabled:
        document = await _run_durable_retry_transaction(
            lambda: WatcherRetryPolicy.for_root(root_dir, WatcherSource.DOCUMENT),
            source=WatcherSource.DOCUMENT,
            root_dir=root_dir,
            action="initialize",
        )
    _raise_if_cancellation_requested(
        any(cancelled for _policy, cancelled in initialized)
        or (document is not None and document[1])
    )
    return initialized[0][0], initialized[1][0], document[0] if document else None


def _record_watcher_changes(
    changes: Iterable[tuple[Change, str]],
    *,
    routing: _WatcherChangeRouting,
) -> tuple[bool, bool, bool]:
    """Classify one intake batch once and record each domain's dirty paths."""
    observed = [False, False, False]
    accepted_changes = {Change.added, Change.modified, Change.deleted}
    for change_type, path_str in changes:
        if change_type not in accepted_changes:
            continue
        path = Path(path_str)
        if _is_vault_change(path, routing.vault_dir):
            routing.vault_slot.add_dirty(path)
            observed[0] = True
            continue
        if change_type is Change.deleted:
            prior_code, prior_document = _record_deleted_prior_owners(
                path,
                root_dir=routing.root_dir,
                code_slot=routing.code_slot,
                document_slot=routing.document_slot,
            )
            observed[1] = observed[1] or prior_code
            observed[2] = observed[2] or prior_document
            if prior_code or prior_document:
                continue
        if _is_code_change(path, routing.root_dir, routing.vault_dir, routing.policy):
            routing.code_slot.add_dirty(path)
            observed[1] = True
        if routing.document_slot is not None and _is_document_change(
            path, routing.root_dir, routing.vault_dir, routing.policy
        ):
            routing.document_slot.add_dirty(path)
            observed[2] = True
    return observed[0], observed[1], observed[2]


def _record_deleted_prior_owners(
    path: Path,
    *,
    root_dir: Path,
    code_slot: _WatcherConvergenceSlot,
    document_slot: _WatcherConvergenceSlot | None,
) -> tuple[bool, bool]:
    """Schedule a missing path from its last durable per-kind ownership."""
    try:
        rel_path = path.relative_to(root_dir).as_posix()
        prior_owners = prior_stored_owners(root_dir, rel_path)
    except (OSError, RuntimeError, ValueError):
        logger.warning(
            "watcher could not resolve prior ownership for deleted path %s",
            path,
            exc_info=True,
        )
        return False, False
    code_owned = ContentKind.CODE in prior_owners
    document_owned = document_slot is not None and ContentKind.DOCUMENT in prior_owners
    if code_owned:
        code_slot.add_dirty(path)
    if document_owned:
        assert document_slot is not None
        document_slot.add_dirty(path)
    return code_owned, document_owned


async def _reconcile_watcher_slots(
    vault_slot: _WatcherConvergenceSlot,
    code_slot: _WatcherConvergenceSlot,
    document_slot: _WatcherConvergenceSlot | None,
    *,
    reconciliation: _WatcherReconciliation,
) -> None:
    """Give each domain an independent convergence opportunity."""
    await _reconcile_watcher_slot(
        vault_slot,
        cooldown=reconciliation.cooldown,
        now=reconciliation.now,
        secondary_graph_cache=reconciliation.graph_cache,
    )
    await _reconcile_watcher_slot(
        code_slot,
        cooldown=reconciliation.cooldown,
        now=reconciliation.now,
    )
    if document_slot is not None:
        await _reconcile_watcher_slot(
            document_slot,
            cooldown=reconciliation.cooldown,
            now=reconciliation.now,
        )


class WatcherInitializationError(RuntimeError):
    """A watcher could not initialize its durable retry state.

    Raised when retry-policy setup fails deterministically (an unreadable or
    unwritable retry ledger). It is distinct from an indexing error taken
    during the watch loop, which is caught and logged rather than propagated:
    a failed initialization cannot be recovered by restarting into the same
    unreadable state, so the owner terminally removes the watcher instead of
    re-arming it.
    """


async def watch_and_reindex(
    root_dir: Path,
    vault_dir: Path,
    vault_indexer: VaultIndexer,
    code_indexer: CodebaseIndexer,
    stop_event: asyncio.Event,
    graph_cache: GraphCache,
    document_indexer: DocumentIndexer | None = None,
    debounce: int = 2000,
    cooldown: float = 30.0,
    registry: ServiceRegistry | None = None,
) -> None:
    """Watch for file changes and trigger incremental re-indexing.

    Runs until stop_event is set. GPU serialization is handled
    internally by the indexers' ``gpu_lock``. Applies an
    application-level cooldown between index runs to prevent
    thrashing. Cooldown is tracked independently per source: vault
    and code each have separate 30-second windows so a vault reindex
    does not suppress a subsequent code reindex (or vice versa).

    Args:
        root_dir: Project root directory to watch.
        vault_dir: Path to the .vault/ documentation directory.
        vault_indexer: Initialized VaultIndexer for doc re-indexing.
        code_indexer: Initialized CodebaseIndexer for source
            re-indexing.
        document_indexer: Managed document indexer bound to the same project.
            Document job dispatch is introduced independently; carrying it here
            prevents watcher construction from inventing a second lifecycle.
        stop_event: Set this event to stop the watcher gracefully.
        debounce: Milliseconds to wait for additional changes
            before processing.
        cooldown: Seconds to suppress re-index triggers after a
            completed run.
        graph_cache: GraphCache to invalidate after a successful vault
            reindex.
        registry: Service registry that owns the watched project's stores.
            Standalone callers default to the process singleton; the resident
            server passes its rebindable registry explicitly.

    Raises:
        WatcherInitializationError: Retry-state initialization failed
            deterministically; the owner terminally removes the watcher.
        This coroutine does not propagate exceptions from indexing.
        Indexing errors are caught and logged via ``logger.exception``.
    """
    try:
        vault_retry, code_retry, document_retry = await _initialize_retry_policies(
            root_dir,
            document_enabled=document_indexer is not None,
        )
    except Exception as exc:
        log_event(
            logger,
            "service.watcher",
            "retry_state_failed",
            severity=logging.ERROR,
            exc_info=True,
            root=root_dir,
            error=exc,
        )
        raise WatcherInitializationError(str(exc)) from exc

    log_event(
        logger,
        "service.watcher",
        "started",
        root=root_dir,
        vault=vault_dir,
        debounce_ms=debounce,
        cooldown_seconds=f"{cooldown:.0f}",
        vault_circuit_state=vault_retry.state.circuit_state,
        vault_next_retry_at=f"{vault_retry.state.next_retry_at:.3f}",
        code_circuit_state=code_retry.state.circuit_state,
        code_next_retry_at=f"{code_retry.state.next_retry_at:.3f}",
        document_circuit_state=(
            document_retry.state.circuit_state if document_retry is not None else None
        ),
        document_next_retry_at=(
            f"{document_retry.state.next_retry_at:.3f}"
            if document_retry is not None
            else None
        ),
    )
    resolved_root = root_dir.resolve()
    if (
        vault_indexer.root_dir.resolve() != resolved_root
        or code_indexer.root_dir.resolve() != resolved_root
        or (
            document_indexer is not None
            and document_indexer.root_dir.resolve() != resolved_root
        )
    ):
        raise ValueError("watcher indexers must belong to the watched project root")

    # Each source owns one convergence slot. Manager callbacks and attempt
    # runners cross the event-loop/worker-thread boundary, so generation
    # transfer is protected by the slot's real thread lock.
    owner_registry = registry if registry is not None else get_registry()
    vault_slot = _WatcherConvergenceSlot(
        JobSource.VAULT,
        resolved_root,
        owner_registry,
        vault_retry,
    )
    code_slot = _WatcherConvergenceSlot(
        JobSource.CODE,
        resolved_root,
        owner_registry,
        code_retry,
    )
    document_slot = (
        _WatcherConvergenceSlot(
            JobSource.DOCUMENT,
            resolved_root,
            owner_registry,
            document_retry,
        )
        if document_retry is not None
        else None
    )
    # One immutable snapshot governs ordinary watcher intake until an
    # index-shaping control event advances the watcher generation. The list is
    # a closure cell shared with ``watch_filter``; invalid policy edits retain
    # the prior intake snapshot while the unconditional control-file event is
    # still sent to the indexer, whose entry gate then fails closed.
    code_policy: list[ResolvedIndexPolicy | None] = [
        _refresh_watcher_policy(code_indexer, root_dir, None)
    ]

    try:
        async for changes in awatch(
            root_dir,
            debounce=debounce,
            rust_timeout=_WATCH_IDLE_TICK_MS,
            yield_on_timeout=True,
            stop_event=stop_event,
            watch_filter=lambda _change, path: (
                _is_vault_change(Path(path), vault_dir)
                or _is_code_change(Path(path), root_dir, vault_dir, code_policy[0])
                or _is_document_change(Path(path), root_dir, vault_dir, code_policy[0])
            ),
        ):
            # ``changes`` is empty on an idle tick (yield_on_timeout): the loop
            # body below still runs, re-checking the cooldown and flushing any
            # carried-forward pending set, so a change suppressed during a
            # cooldown window is reconciled even when no further change arrives.
            policy_changed = any(
                Path(path_str).name in _CONFIG_FILENAMES
                for _change_type, path_str in changes
            )
            if policy_changed:
                code_policy[0] = _refresh_watcher_policy(
                    code_indexer,
                    root_dir,
                    code_policy[0],
                )
            (
                vault_events_observed,
                code_events_observed,
                document_events_observed,
            ) = _record_watcher_changes(
                changes,
                routing=_WatcherChangeRouting(
                    root_dir=root_dir,
                    vault_dir=vault_dir,
                    policy=code_policy[0],
                    vault_slot=vault_slot,
                    code_slot=code_slot,
                    document_slot=document_slot,
                ),
            )

            cancellation_requested = await _persist_observed_sources(
                (
                    _ObservedSource(
                        vault_events_observed, WatcherSource.VAULT, vault_retry
                    ),
                    _ObservedSource(
                        code_events_observed, WatcherSource.CODE, code_retry
                    ),
                    *(
                        (
                            _ObservedSource(
                                document_events_observed,
                                WatcherSource.DOCUMENT,
                                document_retry,
                            ),
                        )
                        if document_retry is not None
                        else ()
                    ),
                ),
                root_dir=root_dir,
            )
            _raise_if_cancellation_requested(cancellation_requested)
            if stop_event.is_set():
                break

            now = time.monotonic()

            await _reconcile_watcher_slots(
                vault_slot,
                code_slot,
                document_slot,
                reconciliation=_WatcherReconciliation(
                    cooldown=cooldown,
                    now=now,
                    graph_cache=graph_cache,
                ),
            )
    except Exception as exc:
        log_event(
            logger,
            "service.watcher",
            "failed",
            severity=logging.ERROR,
            exc_info=True,
            root=root_dir,
            error=exc,
        )
    finally:
        # The manager, not this intake task, owns any admitted attempt. Watcher
        # shutdown must not publish a false cancellation while a worker can
        # still mutate storage; the service lifecycle joins that owner.
        log_event(logger, "service.watcher", "stopped", root=root_dir)


async def _await_slot_settlement(
    slot: _WatcherConvergenceSlot,
    settlement: asyncio.Task[None] | None,
) -> bool:
    """Wait out a pending settlement, reporting whether to continue.

    A manager terminal transition is not yet a watcher convergence
    outcome: the durable retry authority must settle the exact policy
    generation before the slot may clear its path set or admit a
    replacement. Returns ``False`` while a settlement is still running.
    """
    if settlement is None:
        return True
    if not settlement.done():
        return False
    await settlement
    with slot.lock:
        if slot.settlement_task is settlement:
            slot.settlement_task = None
    return True


def _observe_slot_owner(
    slot: _WatcherConvergenceSlot,
    manager: _jobs.JobManager,
    job_id: str,
    *,
    now: float,
) -> None:
    """Fold the canonical job's current state back into the slot."""
    snapshot = manager.get(job_id)
    if snapshot is None:
        _release_missing_job(slot, job_id, now=now)
        return
    with slot.lock:
        watcher_owned = slot.watcher_owned
    if _observe_managed_job(slot, snapshot, now=now) and watcher_owned:
        _sync_legacy_snapshot(snapshot, result=None, error=None)


async def _reconcile_watcher_slot(
    slot: _WatcherConvergenceSlot,
    *,
    cooldown: float,
    now: float,
    secondary_graph_cache: GraphCache | None = None,
) -> None:
    """Observe the canonical owner, then admit one eligible convergence job."""
    manager = _jobs.get_job_manager()
    with slot.lock:
        job_id = slot.job_id
        settlement = slot.settlement_task

    if not await _await_slot_settlement(slot, settlement):
        return
    if job_id is not None:
        _observe_slot_owner(slot, manager, job_id, now=now)

    retry_source = WatcherSource(slot.source.value)
    retry_state, refresh_cancelled = await _run_durable_retry_transaction(
        slot.retry_policy.refresh,
        source=retry_source,
        root_dir=slot.root,
        action="refresh",
    )
    _raise_if_cancellation_requested(refresh_cancelled)

    with slot.lock:
        if slot.job_id is not None or not (
            slot.held_paths or slot.pending_paths or retry_state.convergence_pending
        ):
            return
        eligible_at = max(
            slot.last_success + cooldown,
            slot.replacement_not_before,
        )
        pending_count = len(slot.held_paths | slot.pending_paths)

    if now < eligible_at:
        log_event(
            logger,
            "service.watcher",
            "reindex_suppressed",
            severity=logging.DEBUG,
            source=slot.source.value,
            cooldown_remaining_seconds=f"{eligible_at - now:.0f}",
            pending_paths=pending_count,
        )
        return

    decision = await _admit_watcher_attempt(
        slot.retry_policy,
        source=retry_source,
        root_dir=slot.root,
    )
    if not decision.admitted:
        if decision.reason != "retry delay active":
            log_event(
                logger,
                "service.watcher",
                "reindex_suppressed",
                severity=logging.DEBUG,
                source=slot.source.value,
                reason=decision.reason,
                circuit_state=decision.circuit_state,
                retry_at=f"{decision.retry_at:.3f}",
                retry_in_seconds=f"{decision.retry_in_seconds:.3f}",
                consecutive_failures=slot.retry_policy.state.consecutive_failures,
                pending_paths=pending_count,
            )
        return
    if decision.attempt_generation is None:
        raise WatcherRetryStateError("admitted watcher attempt has no generation")
    await _submit_watcher_job(
        slot,
        now=now,
        retry_decision=decision,
        secondary_graph_cache=secondary_graph_cache,
    )


async def _submit_watcher_job(
    slot: _WatcherConvergenceSlot,
    *,
    now: float,
    retry_decision: WatcherRetryDecision,
    secondary_graph_cache: GraphCache | None,
) -> None:
    """Admit and bind one manager-owned watcher attempt, or coalesce on dedupe."""
    candidate_paths = slot.dirty_paths()
    code_preflight = None
    document_preflight = None
    if slot.source is JobSource.CODE:
        policy_resolver = (
            _jobs.validate_code_index_policy
            if retry_decision.requires_unscoped
            else partial(
                _jobs.validate_scoped_code_index_policy,
                changed_paths=candidate_paths,
            )
        )
        code_preflight = await _run_in_thread(
            policy_resolver,
            slot.root,
        )
    elif slot.source is JobSource.DOCUMENT:
        policy_resolver = (
            _jobs.validate_document_index_policy
            if retry_decision.requires_unscoped
            else partial(
                _jobs.validate_scoped_document_index_policy,
                changed_paths=candidate_paths,
            )
        )
        document_preflight = await _run_in_thread(policy_resolver, slot.root)
        await _run_in_thread(
            _jobs.validate_document_support_profile,
            slot.root,
            document_preflight,
        )
    manager = _jobs.get_job_manager()
    generation = retry_decision.attempt_generation
    if generation is None:
        raise WatcherRetryStateError("admitted watcher attempt has no generation")
    with slot.lock:
        slot.retry_attempt_generations[1] = generation
        if retry_decision.requires_unscoped:
            slot.retry_unscoped_attempts.add(1)
    outcome = await _run_in_thread(
        partial(
            manager.create,
            JobSpec(
                operation=JobOperation.INDEX,
                source=slot.source,
                project_root=str(slot.root),
                mode=JobMode.INCREMENTAL,
            ),
            JobInitiator(
                kind="watcher",
                command=slot.command,
                project_root=str(slot.root),
            ),
            job_id=uuid.uuid4().hex,
        )
    )
    if outcome.status is JobOutcomeStatus.ERROR or outcome.job is None:
        await _settle_retry_failure(
            slot,
            RuntimeError(outcome.message),
            attempt=1,
            action="record_admission_failure",
        )
        _schedule_replacement(
            slot,
            now=now,
            reason="admission_failed",
            error=outcome.message,
        )
        return

    snapshot = outcome.job
    created = outcome.code == "job_created"
    with slot.lock:
        slot.job_id = snapshot.id
        slot.watcher_owned = created
        slot.observed_state = snapshot.state
        slot.retry_attempt_generations[snapshot.attempt.number] = generation
        if retry_decision.requires_unscoped:
            slot.retry_unscoped_attempts.add(snapshot.attempt.number)

    if not created:
        # The equivalent job may have captured the filesystem before this
        # watcher event. Let it retain the root/source slot, but keep every
        # watcher path dirty for a conservative follow-up convergence.
        log_event(
            logger,
            "service.watcher",
            "reindex_coalesced",
            source=slot.source.value,
            job_id=snapshot.id,
            state=snapshot.state.value,
            pending_paths=slot.pending_count(),
        )
        await _settle_retry_interrupted(
            slot,
            attempt=snapshot.attempt.number,
            action="record_coalesced_admission",
        )
        return

    job_id = snapshot.id
    captured_paths = slot.capture_prevalidated_attempt(
        snapshot.attempt.number,
        candidate_paths,
    )
    await _run_in_thread(
        partial(
            _jobs.record_start,
            slot.source,
            "watcher",
            project_root=slot.root,
            command=slot.command,
            initiator_kind="watcher",
            _record_id=job_id,
        )
    )

    def _run_attempt(context: JobAttemptContext) -> JobExecutionResult:
        return _run_managed_index_attempt(
            slot,
            context,
            _ManagedAttemptInputs(
                initial_attempt=snapshot.attempt.number,
                initial_paths=captured_paths,
                code_preflight=code_preflight,
                document_preflight=document_preflight,
                secondary_graph_cache=secondary_graph_cache,
            ),
        )

    def _on_started(started: JobSnapshot) -> None:
        _jobs.record_progress(started.id, "queued")

    def _on_finished(
        finished: JobSnapshot,
        _duration_seconds: float,
        result: JobExecutionResult | None,
        error: BaseException | None,
    ) -> None:
        if finished.state.is_terminal:
            settlement = asyncio.create_task(
                _settle_and_observe_managed_job(
                    slot,
                    finished,
                    result=result,
                    error=error,
                ),
                name=f"vaultspec-watcher-retry-{finished.id}",
            )
            with slot.lock:
                slot.settlement_task = settlement
            _track_retry_settlement(slot, settlement)
        elif _observe_managed_job(
            slot,
            finished,
            now=time.monotonic(),
            error=error,
        ):
            _sync_legacy_snapshot(
                finished,
                result=result,
                error=error,
            )

    bound = manager.bind_dispatch(
        job_id,
        _run_attempt,
        on_started=_on_started,
        on_finished=_on_finished,
    )
    if bound.status is JobOutcomeStatus.ERROR:
        await _finish_unstarted_watcher_failure(
            slot,
            _UnstartedFailure(
                manager=manager,
                job_id=job_id,
                attempt=snapshot.attempt.number,
                message=bound.message,
                action="record_dispatch_bind_failure",
                reason="dispatch_bind_failed",
            ),
        )
        return

    dispatched = await manager.dispatch_async(job_id)
    if dispatched.status is JobOutcomeStatus.ERROR:
        await _finish_unstarted_watcher_failure(
            slot,
            _UnstartedFailure(
                manager=manager,
                job_id=job_id,
                attempt=snapshot.attempt.number,
                message=dispatched.message,
                action="record_dispatch_failure",
                reason="dispatch_failed",
            ),
        )
        return

    log_event(
        logger,
        "service.watcher",
        "reindex_started",
        source=slot.source.value,
        job_id=job_id,
        pending_paths=slot.pending_count(),
        scope=(
            "unscoped"
            if snapshot.attempt.number in slot.retry_unscoped_attempts
            else "scoped"
        ),
        circuit_state=slot.retry_policy.state.circuit_state,
        attempt_generation=slot.retry_attempt_generations[snapshot.attempt.number],
    )


async def _finish_unstarted_watcher_failure(
    slot: _WatcherConvergenceSlot,
    failure: _UnstartedFailure,
) -> None:
    """Durably settle an orchestration failure before releasing its slot."""
    await _run_in_thread(
        partial(failure.manager.fail_unstarted, failure.job_id, result=failure.message),
    )
    error = RuntimeError(failure.message)
    retry_state = await _settle_retry_failure(
        slot,
        error,
        attempt=failure.attempt,
        action=failure.action,
    )
    failed = await _run_in_thread(failure.manager.get, failure.job_id)
    await _run_in_thread(
        partial(
            failure.manager.update_terminal_resilience,
            failure.job_id,
            attempt=failure.attempt,
            resilience=_retry_resilience(
                retry_state,
                base=failed.resilience if failed is not None else None,
            ),
        )
    )
    failed = await _run_in_thread(failure.manager.get, failure.job_id)
    observed_terminal = (
        failed is not None
        and failed.state.is_terminal
        and _observe_managed_job(
            slot,
            failed,
            now=time.monotonic(),
            error=error,
        )
    )
    if observed_terminal:
        await _run_in_thread(
            partial(_jobs.record_finish, failure.job_id, error=failure.message),
        )
        return
    _schedule_replacement(
        slot,
        now=time.monotonic(),
        reason=failure.reason,
        error=failure.message,
    )


def _retry_generation_for_attempt(
    slot: _WatcherConvergenceSlot,
    attempt: int,
) -> tuple[int, bool]:
    """Map a manager resume attempt to the slot's one durable policy claim."""
    with slot.lock:
        generation = slot.retry_attempt_generations.get(attempt)
        if generation is not None:
            return generation, attempt in slot.retry_unscoped_attempts
        generations = set(slot.retry_attempt_generations.values())
        if len(generations) != 1:
            raise WatcherRetryStateError(
                "managed watcher attempt has no unique durable retry generation"
            )
        generation = generations.pop()
        requires_unscoped = bool(slot.retry_unscoped_attempts)
        slot.retry_attempt_generations[attempt] = generation
        if requires_unscoped:
            slot.retry_unscoped_attempts.add(attempt)
        return generation, requires_unscoped


def _clear_retry_generation(slot: _WatcherConvergenceSlot, generation: int) -> None:
    """Release every manager-attempt alias for one settled policy generation."""
    with slot.lock:
        attempts = {
            attempt
            for attempt, mapped in slot.retry_attempt_generations.items()
            if mapped == generation
        }
        for attempt in attempts:
            slot.retry_attempt_generations.pop(attempt, None)
        slot.retry_unscoped_attempts.difference_update(attempts)


async def _settle_retry_failure(
    slot: _WatcherConvergenceSlot,
    error: BaseException,
    *,
    attempt: int,
    action: str,
) -> WatcherRetryState:
    """Persist one managed orchestration or execution failure."""
    generation, _requires_unscoped = _retry_generation_for_attempt(slot, attempt)
    retry_source = WatcherSource(slot.source.value)
    state, cancellation_requested = await _run_durable_retry_transaction(
        partial(slot.retry_policy.record_failure, error, generation),
        source=retry_source,
        root_dir=slot.root,
        action=action,
        cancellation_fallback=slot.retry_policy.write_recovery_marker,
    )
    _clear_retry_generation(slot, generation)
    _raise_if_cancellation_requested(cancellation_requested)
    log_event(
        logger,
        "service.watcher",
        "retry_recorded",
        severity=logging.WARNING,
        source=slot.source.value,
        error_kind=state.last_error_kind,
        consecutive_failures=state.consecutive_failures,
        circuit_state=state.circuit_state,
        next_retry_at=f"{state.next_retry_at:.3f}",
    )
    return state


async def _settle_retry_interrupted(
    slot: _WatcherConvergenceSlot,
    *,
    attempt: int,
    action: str,
) -> WatcherRetryState:
    """Release one managed claim while retaining durable dirty intent."""
    generation, _requires_unscoped = _retry_generation_for_attempt(slot, attempt)
    retry_source = WatcherSource(slot.source.value)
    state, cancellation_requested = await _run_durable_retry_transaction(
        lambda: slot.retry_policy.record_interrupted(generation),
        source=retry_source,
        root_dir=slot.root,
        action=action,
        cancellation_fallback=slot.retry_policy.write_recovery_marker,
    )
    _clear_retry_generation(slot, generation)
    _raise_if_cancellation_requested(cancellation_requested)
    return state


async def _settle_managed_retry(
    slot: _WatcherConvergenceSlot,
    snapshot: JobSnapshot,
    *,
    error: BaseException | None,
) -> WatcherRetryState:
    """Make durable retry truth follow one terminal managed-job outcome."""
    generation, _requires_unscoped = _retry_generation_for_attempt(
        slot,
        snapshot.attempt.number,
    )
    retry_source = WatcherSource(slot.source.value)
    if snapshot.state is JobState.SUCCEEDED:
        state, cancellation_requested = await _run_durable_retry_transaction(
            lambda: slot.retry_policy.record_success(generation),
            source=retry_source,
            root_dir=slot.root,
            action="record_success",
            cancellation_fallback=slot.retry_policy.write_recovery_marker,
        )
    elif snapshot.state is JobState.FAILED:
        failure = error or RuntimeError(snapshot.result or "watcher indexing failed")
        state, cancellation_requested = await _run_durable_retry_transaction(
            partial(slot.retry_policy.record_failure, failure, generation),
            source=retry_source,
            root_dir=slot.root,
            action="record_failure",
            cancellation_fallback=slot.retry_policy.write_recovery_marker,
        )
    else:
        state, cancellation_requested = await _run_durable_retry_transaction(
            lambda: slot.retry_policy.record_interrupted(generation),
            source=retry_source,
            root_dir=slot.root,
            action="record_interrupted",
            cancellation_fallback=slot.retry_policy.write_recovery_marker,
        )
    _clear_retry_generation(slot, generation)
    _raise_if_cancellation_requested(cancellation_requested)
    return state


async def _settle_and_observe_managed_job(
    slot: _WatcherConvergenceSlot,
    snapshot: JobSnapshot,
    *,
    result: JobExecutionResult | None,
    error: BaseException | None,
) -> None:
    """Settle durable retry truth before releasing the convergence slot."""
    retry_state = await _settle_managed_retry(slot, snapshot, error=error)
    manager = _jobs.get_job_manager()
    settled = manager.get(snapshot.id)
    base = settled.resilience if settled is not None else snapshot.resilience
    await _run_in_thread(
        partial(
            manager.update_terminal_resilience,
            snapshot.id,
            attempt=snapshot.attempt.number,
            resilience=_retry_resilience(retry_state, base=base),
        )
    )
    if _observe_managed_job(
        slot,
        snapshot,
        now=time.monotonic(),
        error=error,
    ):
        _sync_legacy_snapshot(snapshot, result=result, error=error)


def _track_retry_settlement(
    slot: _WatcherConvergenceSlot,
    task: asyncio.Task[None],
) -> None:
    """Keep one settlement strongly owned and visible to watcher drains."""
    register_retry_settlement(
        slot.root,
        task,
        partial(_log_retry_settlement_result, slot),
    )


def _log_retry_settlement_result(
    slot: _WatcherConvergenceSlot,
    task: asyncio.Task[None],
) -> None:
    """Observe detached settlement failures without losing their diagnostics."""
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        log_event(
            logger,
            "service.watcher",
            "retry_state_failed",
            severity=logging.ERROR,
            exc_info=(type(error), error, error.__traceback__),
            root=slot.root,
            source=slot.source.value,
            error=error,
        )


def _resolve_attempt_scope(
    slot: _WatcherConvergenceSlot,
    context: JobAttemptContext,
    *,
    initial_attempt: int,
    initial_paths: frozenset[Path],
) -> tuple[frozenset[Path] | None, frozenset[Path], bool]:
    """Resolve and verify the exact watcher scope owned by this attempt."""
    _generation, requires_unscoped = _retry_generation_for_attempt(
        slot, context.attempt
    )
    captured = slot.captured_attempt(context.attempt)
    if captured is None:
        captured = slot.capture_attempt(context.attempt)
    if context.attempt == initial_attempt and captured != initial_paths:
        raise WatcherRetryStateError(
            "managed watcher scope differs from its validated admission"
        )
    return (None if requires_unscoped else captured), captured, requires_unscoped


def _resolve_attempt_preflights(
    slot: _WatcherConvergenceSlot,
    context: JobAttemptContext,
    scope: _ManagedAttemptScope,
) -> _ManagedAttemptScope:
    """Refresh admission authority for retries before model acquisition."""
    code_preflight = scope.code_preflight
    document_preflight = scope.document_preflight
    if slot.source is JobSource.CODE and code_preflight is None:
        context.control.checkpoint()
        code_preflight = (
            _jobs.validate_code_index_policy(slot.root)
            if scope.requires_unscoped
            else _jobs.validate_scoped_code_index_policy(slot.root, scope.captured_paths)
        )
        context.control.checkpoint()
    if slot.source is JobSource.DOCUMENT and document_preflight is None:
        context.control.checkpoint()
        document_preflight = (
            _jobs.validate_document_index_policy(slot.root)
            if scope.requires_unscoped
            else _jobs.validate_scoped_document_index_policy(
                slot.root, scope.captured_paths
            )
        )
        context.control.checkpoint()
    if slot.source is JobSource.DOCUMENT:
        if document_preflight is None:
            raise RuntimeError("document watcher attempt has no admission preflight")
        _jobs.validate_document_support_profile(slot.root, document_preflight)
        context.control.checkpoint()
    return replace(
        scope,
        code_preflight=code_preflight,
        document_preflight=document_preflight,
    )


def _execute_project_incremental(
    project: ProjectSlot,
    slot: _WatcherConvergenceSlot,
    context: JobAttemptContext,
    scope: _ManagedAttemptScope,
    inputs: _ManagedAttemptInputs,
) -> IndexResult:
    """Dispatch one exhaustively typed domain under an acquired project lease."""
    reporter = _jobs.JobProgressReporter(context.job_id, context=context)
    if slot.source is JobSource.VAULT:
        result = project.vault_indexer.incremental_index(
            reporter=reporter,
            changed_paths=scope.paths,
            run_control=context.control,
        )
        project.graph_cache.invalidate()
        if (
            inputs.secondary_graph_cache is not None
            and inputs.secondary_graph_cache is not project.graph_cache
        ):
            inputs.secondary_graph_cache.invalidate()
        return result
    if slot.source is JobSource.CODE:
        if scope.code_preflight is None:
            raise RuntimeError("code watcher attempt has no execution preflight")
        return project.code_indexer.incremental_index(
            reporter=reporter,
            changed_paths=scope.paths,
            preflight=scope.code_preflight,
            run_control=context.control,
        )
    if scope.document_preflight is None:
        raise RuntimeError("document watcher attempt has no execution preflight")
    return project.document_indexer.incremental_index(
        reporter=reporter,
        changed_paths=scope.paths,
        preflight=scope.document_preflight,
        run_control=context.control,
    )


def _run_managed_index_attempt(
    slot: _WatcherConvergenceSlot,
    context: JobAttemptContext,
    inputs: _ManagedAttemptInputs,
) -> JobExecutionResult:
    """Run one watcher generation under manager and registry ownership."""
    paths, captured_paths, requires_unscoped = _resolve_attempt_scope(
        slot,
        context,
        initial_attempt=inputs.initial_attempt,
        initial_paths=inputs.initial_paths,
    )
    scope = _ManagedAttemptScope(
        paths=paths,
        captured_paths=captured_paths,
        requires_unscoped=requires_unscoped,
        code_preflight=(
            inputs.code_preflight
            if context.attempt == inputs.initial_attempt
            else None
        ),
        document_preflight=(
            inputs.document_preflight
            if context.attempt == inputs.initial_attempt
            else None
        ),
    )
    scope = _resolve_attempt_preflights(slot, context, scope)
    context.set_resilience(_watcher_attempt_resilience(slot))
    pipeline_active = slot.source in {JobSource.CODE, JobSource.DOCUMENT}
    registry = slot.registry
    registry.load_model()
    try:
        with registry.lease(slot.root) as project:
            context.set_resources(project_lease_held=True)
            try:
                context.set_resources(
                    writer_lock_held=True,
                    pipeline_active=pipeline_active,
                )
                try:
                    result = _execute_project_incremental(
                        project,
                        slot,
                        context,
                        scope,
                        inputs,
                    )
                finally:
                    _publish_watcher_index_resilience(slot, project, context)
            finally:
                context.set_resources(
                    writer_lock_held=False,
                    pipeline_active=False,
                )
    finally:
        context.set_resources(project_lease_held=False)
    skipped_suffix = (
        f" ~{result.preprocess_skipped}" if result.preprocess_skipped else ""
    )
    return JobExecutionResult(
        summary=(
            f"+{result.added} /{result.updated} "
            f"-{result.removed} ({result.duration_ms}ms){skipped_suffix}"
        ),
        preprocess_ok=result.preprocess_ok,
        preprocess_skipped=result.preprocess_skipped,
        preprocess_failures=tuple(result.preprocess_failures),
        reuse=result.reuse,
    )


def _retry_resilience(
    state: WatcherRetryState,
    *,
    base: IndexResilienceSnapshot | None = None,
) -> IndexResilienceSnapshot:
    """Merge durable watcher retry truth into the canonical index account."""
    current = base or IndexResilienceSnapshot()
    return replace(
        current,
        circuit_state=state.circuit_state.value,
        next_retry_at=state.next_retry_at if state.next_retry_at > 0.0 else None,
        last_durable_progress_at=(
            current.last_durable_progress_at or state.last_durable_progress_at
        ),
    )


def _watcher_attempt_resilience(
    slot: _WatcherConvergenceSlot,
) -> IndexResilienceSnapshot:
    """Project admission and retry truth before model acquisition."""
    if slot.source in {JobSource.CODE, JobSource.DOCUMENT}:
        # Package-internal resilience projectors, shared with the dispatcher.
        from .job_dispatch import (
            _admitted_resilience,  # pyright: ignore[reportPrivateUsage]
        )

        base = _admitted_resilience(slot.source)
    else:
        base = IndexResilienceSnapshot()
    return _retry_resilience(slot.retry_policy.state, base=base)


def _publish_watcher_index_resilience(
    slot: _WatcherConvergenceSlot,
    project: ProjectSlot,
    context: JobAttemptContext,
) -> None:
    """Publish checkpoint evidence for watcher-owned code and document work."""
    # Package-internal resilience projectors, shared with the dispatcher.
    from .job_dispatch import (
        _code_resilience,  # pyright: ignore[reportPrivateUsage]
        _document_resilience,  # pyright: ignore[reportPrivateUsage]
        _publish_resilience,  # pyright: ignore[reportPrivateUsage]
    )

    if slot.source not in {JobSource.CODE, JobSource.DOCUMENT}:
        return

    def snapshot_factory() -> IndexResilienceSnapshot:
        base = (
            _code_resilience(project.code_indexer)
            if slot.source is JobSource.CODE
            else _document_resilience(project.document_indexer)
        )
        return _retry_resilience(slot.retry_policy.state, base=base)

    _publish_resilience(context, snapshot_factory)


def _sync_legacy_snapshot(
    snapshot: JobSnapshot,
    *,
    result: JobExecutionResult | None,
    error: BaseException | None,
) -> None:
    """Project manager truth through the public bounded compatibility registry."""
    if snapshot.state is JobState.SUCCEEDED:
        _jobs.record_finish(
            snapshot.id,
            result=snapshot.result,
            preprocess_ok=result.preprocess_ok if result is not None else 0,
            preprocess_skipped=result.preprocess_skipped if result is not None else 0,
            preprocess_failures=(
                list(result.preprocess_failures) if result is not None else None
            ),
            reuse=result.reuse if result is not None else None,
        )
    elif snapshot.state is JobState.FAILED:
        _jobs.record_finish(
            snapshot.id,
            error=snapshot.result or str(error or "job failed"),
        )
    elif snapshot.state is JobState.INTERRUPTED:
        _jobs.record_finish(
            snapshot.id,
            result=snapshot.result,
            phase="interrupted",
        )
    elif snapshot.state is JobState.CANCELLED:
        _jobs.record_finish(
            snapshot.id,
            result=snapshot.result,
            phase="cancelled",
        )
    elif snapshot.state in {JobState.PAUSED, JobState.QUEUED}:
        _jobs.record_progress(snapshot.id, snapshot.state.value)


def _schedule_replacement(
    slot: _WatcherConvergenceSlot,
    *,
    now: float,
    reason: str,
    error: str | None = None,
) -> None:
    """Delay repeated orchestration failures with a finite exponential bound."""
    with slot.lock:
        delay = slot.defer_replacement(now)
        pending_count = len(slot.held_paths | slot.pending_paths)
    log_event(
        logger,
        "service.watcher",
        "replacement_scheduled",
        severity=logging.WARNING if error is None else logging.ERROR,
        source=slot.source.value,
        reason=reason,
        error=error,
        replacement_backoff_seconds=f"{delay:.0f}",
        pending_paths=pending_count,
    )


def _observe_managed_job(
    slot: _WatcherConvergenceSlot,
    snapshot: JobSnapshot,
    *,
    now: float,
    error: BaseException | None = None,
) -> bool:
    """Apply one exact manager snapshot once; return whether it changed the slot."""
    terminal = snapshot.state.is_terminal
    replacement_delay = 0.0
    with slot.lock:
        if slot.job_id != snapshot.id:
            return False
        previous_state = slot.observed_state
        if not terminal:
            slot.observed_state = snapshot.state
            if snapshot.state is JobState.PAUSED:
                slot.attempt_paths.pop(snapshot.attempt.number, None)
            elif snapshot.state is JobState.QUEUED:
                for attempt in tuple(slot.attempt_paths):
                    if attempt < snapshot.attempt.number:
                        slot.attempt_paths.pop(attempt, None)
            changed = previous_state is not snapshot.state
            pending_count = len(slot.held_paths | slot.pending_paths)
            watcher_owned = slot.watcher_owned
        else:
            watcher_owned = slot.watcher_owned
            captured = slot.attempt_paths.pop(snapshot.attempt.number, frozenset())
            slot.attempt_paths.clear()
            if watcher_owned and snapshot.state is JobState.SUCCEEDED:
                slot.held_paths.difference_update(captured)
                slot.last_success = now
                slot.replacement_not_before = 0.0
                slot.replacement_streak = 0
            else:
                slot.pending_paths.update(slot.held_paths)
                slot.held_paths.clear()

            if snapshot.state.is_retryable:
                replacement_delay = slot.defer_replacement(now)

            slot.job_id = None
            slot.watcher_owned = False
            slot.observed_state = snapshot.state
            pending_count = len(slot.held_paths | slot.pending_paths)
            changed = True

    if not changed:
        return False

    _log_managed_transition(
        slot,
        snapshot,
        _TransitionLogContext(
            watcher_owned=watcher_owned,
            pending_count=pending_count,
            replacement_delay=replacement_delay,
            error=error,
        ),
    )
    return True


def _log_managed_transition(
    slot: _WatcherConvergenceSlot,
    snapshot: JobSnapshot,
    context: _TransitionLogContext,
) -> None:
    if snapshot.state is JobState.PAUSED:
        log_event(
            logger,
            "service.watcher",
            "reindex_paused",
            source=slot.source.value,
            job_id=snapshot.id,
            pending_paths=context.pending_count,
        )
    elif snapshot.state is JobState.SUCCEEDED and context.watcher_owned:
        log_event(
            logger,
            "service.watcher",
            "reindex_completed",
            source=slot.source.value,
            job_id=snapshot.id,
            result=snapshot.result,
            pending_paths=context.pending_count,
        )
    elif snapshot.state is JobState.CANCELLED:
        log_event(
            logger,
            "service.watcher",
            "replacement_scheduled",
            source=slot.source.value,
            job_id=snapshot.id,
            replacement_backoff_seconds=f"{context.replacement_delay:.0f}",
            pending_paths=context.pending_count,
        )
    elif snapshot.state is JobState.SUCCEEDED:
        log_event(
            logger,
            "service.watcher",
            "coalesced_job_completed",
            source=slot.source.value,
            job_id=snapshot.id,
            pending_paths=context.pending_count,
        )
    elif not snapshot.state.is_terminal:
        # Queued, running, pausing and cancelling are progress, not outcomes.
        # They reached the failure branch below only because it was the
        # fallthrough, so every healthy run logged an error a second after it
        # started - which buries the failures that are real.
        log_event(
            logger,
            "service.watcher",
            "reindex_state_changed",
            source=slot.source.value,
            job_id=snapshot.id,
            state=snapshot.state.value,
            pending_paths=context.pending_count,
        )
    else:
        log_event(
            logger,
            "service.watcher",
            "reindex_failed",
            severity=logging.ERROR,
            exc_info=context.error is not None,
            source=slot.source.value,
            job_id=snapshot.id,
            state=snapshot.state.value,
            error=context.error or snapshot.result,
            pending_paths=context.pending_count,
        )


def _release_missing_job(
    slot: _WatcherConvergenceSlot,
    job_id: str,
    *,
    now: float,
) -> None:
    """Recover conservatively when bounded terminal history lost an exact ID."""
    with slot.lock:
        if slot.job_id != job_id:
            return
        slot.pending_paths.update(slot.held_paths)
        slot.held_paths.clear()
        slot.job_id = None
        slot.watcher_owned = False
        slot.observed_state = None
        delay = slot.defer_replacement(now)
        pending_count = len(slot.pending_paths)
    log_event(
        logger,
        "service.watcher",
        "replacement_scheduled",
        severity=logging.WARNING,
        source=slot.source.value,
        job_id=job_id,
        reason="job_snapshot_missing",
        replacement_backoff_seconds=f"{delay:.0f}",
        pending_paths=pending_count,
    )
