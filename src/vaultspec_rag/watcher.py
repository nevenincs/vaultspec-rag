"""Filesystem watcher for automatic vault/codebase re-indexing.

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
from dataclasses import dataclass, field
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
from .indexer._content_policy import ContentKind
from .indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME
from .job_manager import JobAttemptContext, JobExecutionResult
from .job_models import (
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
from .watcher_retry import (
    WatcherRetryDecision,
    WatcherRetryPolicy,
    WatcherRetryState,
    WatcherRetryStateError,
    WatcherRetryUnavailableError,
    WatcherSource,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .graph_cache import GraphCache
    from .indexer import CodebaseIndexer, VaultIndexer
    from .indexer._resolved_policy import ResolvedIndexPolicy
    from .service import ServiceRegistry

logger = logging.getLogger(__name__)
_CANCELLATION_DURABILITY_SECONDS = 3.0
_CANCELLATION_FALLBACK_SECONDS = 2.0
_STATE_TRANSACTION_WORKER_SLOTS = threading.BoundedSemaphore(4)
_CANCELLATION_FALLBACK_WORKER_SLOTS = threading.BoundedSemaphore(2)
_RETRY_SETTLEMENTS_LOCK = RLock()
_RETRY_SETTLEMENTS: dict[Path, set[asyncio.Task[None]]] = {}

# Extensions recognized as vault documentation
_VAULT_EXTENSIONS = frozenset({".md"})

# Index-shaping control files. An edit to one of these changes index
# membership without changing any indexed file's bytes, so it must reach the
# indexer as an ordinary changed path: the config-epoch check inside the
# incremental entry detects the drift and self-escalates. The watcher does no
# drift classification of its own.
_CONFIG_FILENAMES = frozenset(
    {
        ".gitignore",
        ".vaultragignore",
        PREPROCESS_CONFIG_FILENAME,
    }
)

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

    def capture_attempt(self, attempt: int) -> frozenset[Path]:
        """Move the current pending generation into one immutable attempt batch."""
        with self.lock:
            self.held_paths.update(self.pending_paths)
            self.pending_paths.clear()
            captured = frozenset(self.held_paths)
            self.attempt_paths[attempt] = captured
            return captured


def _is_vault_change(path: Path, vault_dir: Path) -> bool:
    """Return True if path is a .md file inside the vault directory.

    Args:
        path: The changed file path.
        vault_dir: The vault directory to check against.

    Returns:
        True if path is a .md file inside vault_dir, False otherwise.
    """
    try:
        path.relative_to(vault_dir)
    except ValueError as exc:
        logger.debug("watcher: %s not under vault dir %s: %s", path, vault_dir, exc)
        return False
    return path.suffix.lower() in _VAULT_EXTENSIONS


def _is_code_change(
    path: Path,
    root_dir: Path,
    vault_dir: Path,
    policy: ResolvedIndexPolicy | None,
) -> bool:
    """Return whether one watcher path is code-owned in this snapshot.

    Control files always schedule reconciliation because they can change the
    next generation's policy. Ordinary paths use exactly the shared
    classifier; parser support and directory layout never establish ownership.

    Args:
        path: The changed file path.
        root_dir: Project root directory.
        vault_dir: Vault directory to exclude.
        policy: Immutable watcher-generation policy snapshot.

    Returns:
        True for a control file or admitted code-owned path outside the vault.
    """
    try:
        path.relative_to(vault_dir)
        return False  # Inside vault - not a code change
    except ValueError as exc:
        logger.debug(
            "watcher code-path: %s not under vault %s: %s", path, vault_dir, exc
        )
    try:
        rel = path.relative_to(root_dir)
    except ValueError as exc:
        logger.debug("watcher code-path: %s not under root %s: %s", path, root_dir, exc)
        return False
    if path.name in _CONFIG_FILENAMES:
        return True
    if policy is None:
        return False
    disposition = policy.classify(str(rel).replace("\\", "/")).disposition
    return disposition.admitted and disposition.kind is ContentKind.CODE


def _refresh_watcher_policy(
    code_indexer: CodebaseIndexer,
    root_dir: Path,
    previous: ResolvedIndexPolicy | None,
) -> ResolvedIndexPolicy | None:
    """Advance watcher classification authority or retain fail-closed state."""
    try:
        policy = code_indexer.resolve_policy_snapshot()
    except (OSError, ValueError) as exc:
        log_event(
            logger,
            "service.watcher",
            "policy_snapshot_rejected",
            severity=logging.ERROR,
            root=root_dir,
            error=exc,
        )
        return previous
    log_event(
        logger,
        "service.watcher",
        "policy_snapshot_advanced",
        root=root_dir,
        policy_fingerprint=policy.fingerprints.snapshot,
    )
    return policy


async def _run_retry_transaction[T](operation: Callable[[], T]) -> T:
    """Run retry-state locking and durable I/O outside the service event loop."""

    def _guarded_operation() -> T:
        if not _STATE_TRANSACTION_WORKER_SLOTS.acquire(blocking=False):
            raise WatcherRetryUnavailableError(
                "watcher retry state worker capacity is unavailable"
            )
        try:
            return operation()
        finally:
            _STATE_TRANSACTION_WORKER_SLOTS.release()

    return await _run_in_thread(_guarded_operation, abandon_on_cancel=True)


async def _run_fallback_transaction[T](operation: Callable[[], T]) -> T:
    """Run a recovery handoff without competing for state worker capacity."""

    def _guarded_operation() -> T:
        if not _CANCELLATION_FALLBACK_WORKER_SLOTS.acquire(blocking=False):
            raise WatcherRetryUnavailableError(
                "watcher recovery handoff worker capacity is unavailable"
            )
        try:
            return operation()
        finally:
            _CANCELLATION_FALLBACK_WORKER_SLOTS.release()

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
    source: WatcherSource,
    root_dir: Path,
    action: str,
    cancellation_fallback: Callable[[], object] | None,
    state: _DurableRetryState,
) -> tuple[T, bool] | None:
    """Drive one transaction to a durable outcome.

    Returns the result when it commits, or ``None`` when the caller
    should back off and start a fresh transaction. Raises
    ``CancelledError`` once the durability window closes.
    """
    transaction = asyncio.create_task(_run_retry_transaction(operation))
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
                cancellation_fallback,
                source=source,
                root_dir=root_dir,
                action=action,
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
                    root=root_dir,
                    source=source,
                    action=action,
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
    while True:
        if state.expired():
            await _complete_cancellation_handoff(
                cancellation_fallback,
                source=source,
                root_dir=root_dir,
                action=action,
            )
            raise asyncio.CancelledError
        outcome = await _attempt_durable_transaction(
            operation,
            source=source,
            root_dir=root_dir,
            action=action,
            cancellation_fallback=cancellation_fallback,
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
    task = asyncio.create_task(_run_fallback_transaction(operation))
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


async def _persist_observed_sources(
    *,
    vault_events_observed: bool,
    code_events_observed: bool,
    vault_retry: WatcherRetryPolicy,
    code_retry: WatcherRetryPolicy,
    root_dir: Path,
) -> bool:
    """Settle every source in one accepted batch before delivering cancellation."""
    cancellation_requested = False
    errors: list[Exception] = []
    operations = [
        (vault_events_observed, WatcherSource.VAULT, vault_retry),
        (code_events_observed, WatcherSource.CODE, code_retry),
    ]
    tasks = [
        asyncio.create_task(
            _persist_convergence_pending(
                policy,
                source=source,
                root_dir=root_dir,
            )
        )
        for observed, source, policy in operations
        if observed
    ]
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
            break
    for outcome in outcomes:
        if isinstance(outcome, asyncio.CancelledError):
            cancellation_requested = True
        elif isinstance(outcome, Exception):
            errors.append(outcome)
        elif isinstance(outcome, bool):
            cancellation_requested |= outcome
        else:
            raise outcome
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


async def watch_and_reindex(
    root_dir: Path,
    vault_dir: Path,
    vault_indexer: VaultIndexer,
    code_indexer: CodebaseIndexer,
    stop_event: asyncio.Event,
    graph_cache: GraphCache,
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
        This coroutine does not propagate exceptions from indexing.
        Indexing errors are caught and logged via ``logger.exception``.
    """
    try:
        vault_retry, vault_start_cancelled = await _run_durable_retry_transaction(
            lambda: WatcherRetryPolicy.for_root(root_dir, WatcherSource.VAULT),
            source=WatcherSource.VAULT,
            root_dir=root_dir,
            action="initialize",
        )
        code_retry, code_start_cancelled = await _run_durable_retry_transaction(
            lambda: WatcherRetryPolicy.for_root(root_dir, WatcherSource.CODE),
            source=WatcherSource.CODE,
            root_dir=root_dir,
            action="initialize",
        )
        _raise_if_cancellation_requested(vault_start_cancelled or code_start_cancelled)
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
        return

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
    )
    resolved_root = root_dir.resolve()
    if (
        vault_indexer.root_dir.resolve() != resolved_root
        or code_indexer.root_dir.resolve() != resolved_root
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
            ),
        ):
            # ``changes`` is empty on an idle tick (yield_on_timeout): the loop
            # body below still runs, re-checking the cooldown and flushing any
            # carried-forward pending set, so a change suppressed during a
            # cooldown window is reconciled even when no further change arrives.
            vault_events_observed = False
            code_events_observed = False
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
            for change_type, path_str in changes:
                path = Path(path_str)
                if change_type in (Change.added, Change.modified, Change.deleted):
                    if _is_vault_change(path, vault_dir):
                        vault_slot.add_dirty(path)
                        vault_events_observed = True
                    elif _is_code_change(
                        path,
                        root_dir,
                        vault_dir,
                        code_policy[0],
                    ):
                        code_slot.add_dirty(path)
                        code_events_observed = True

            cancellation_requested = await _persist_observed_sources(
                vault_events_observed=vault_events_observed,
                code_events_observed=code_events_observed,
                vault_retry=vault_retry,
                code_retry=code_retry,
                root_dir=root_dir,
            )
            _raise_if_cancellation_requested(cancellation_requested)
            if stop_event.is_set():
                break

            now = time.monotonic()

            await _reconcile_watcher_slot(
                vault_slot,
                cooldown=cooldown,
                now=now,
                secondary_graph_cache=graph_cache,
            )
            await _reconcile_watcher_slot(
                code_slot,
                cooldown=cooldown,
                now=now,
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
    if slot.source is JobSource.CODE:
        _jobs.validate_code_index_policy(slot.root)
    manager = _jobs.get_job_manager()
    generation = retry_decision.attempt_generation
    if generation is None:
        raise WatcherRetryStateError("admitted watcher attempt has no generation")
    with slot.lock:
        slot.retry_attempt_generations[1] = generation
        if retry_decision.requires_unscoped:
            slot.retry_unscoped_attempts.add(1)
    outcome = manager.create(
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
    _jobs.record_start(
        slot.source.value,
        "watcher",
        project_root=slot.root,
        command=slot.command,
        initiator_kind="watcher",
        _record_id=job_id,
    )

    def _run_attempt(context: JobAttemptContext) -> JobExecutionResult:
        return _run_managed_index_attempt(
            slot,
            context,
            secondary_graph_cache=secondary_graph_cache,
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
            manager=manager,
            job_id=job_id,
            attempt=snapshot.attempt.number,
            message=bound.message,
            action="record_dispatch_bind_failure",
            reason="dispatch_bind_failed",
        )
        return

    dispatched = manager.dispatch(job_id)
    if dispatched.status is JobOutcomeStatus.ERROR:
        await _finish_unstarted_watcher_failure(
            slot,
            manager=manager,
            job_id=job_id,
            attempt=snapshot.attempt.number,
            message=dispatched.message,
            action="record_dispatch_failure",
            reason="dispatch_failed",
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
    *,
    manager: _jobs.JobManager,
    job_id: str,
    attempt: int,
    message: str,
    action: str,
    reason: str,
) -> None:
    """Durably settle an orchestration failure before releasing its slot."""
    manager.fail_unstarted(job_id, result=message)
    failure = RuntimeError(message)
    await _settle_retry_failure(
        slot,
        failure,
        attempt=attempt,
        action=action,
    )
    failed = manager.get(job_id)
    observed_terminal = (
        failed is not None
        and failed.state.is_terminal
        and _observe_managed_job(
            slot,
            failed,
            now=time.monotonic(),
            error=failure,
        )
    )
    if observed_terminal:
        _jobs.record_finish(job_id, error=message)
        return
    _schedule_replacement(
        slot,
        now=time.monotonic(),
        reason=reason,
        error=message,
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
) -> None:
    """Make durable retry truth follow one terminal managed-job outcome."""
    generation, _requires_unscoped = _retry_generation_for_attempt(
        slot,
        snapshot.attempt.number,
    )
    retry_source = WatcherSource(slot.source.value)
    if snapshot.state is JobState.SUCCEEDED:
        _state, cancellation_requested = await _run_durable_retry_transaction(
            lambda: slot.retry_policy.record_success(generation),
            source=retry_source,
            root_dir=slot.root,
            action="record_success",
            cancellation_fallback=slot.retry_policy.write_recovery_marker,
        )
    elif snapshot.state is JobState.FAILED:
        failure = error or RuntimeError(snapshot.result or "watcher indexing failed")
        _state, cancellation_requested = await _run_durable_retry_transaction(
            partial(slot.retry_policy.record_failure, failure, generation),
            source=retry_source,
            root_dir=slot.root,
            action="record_failure",
            cancellation_fallback=slot.retry_policy.write_recovery_marker,
        )
    else:
        _state, cancellation_requested = await _run_durable_retry_transaction(
            lambda: slot.retry_policy.record_interrupted(generation),
            source=retry_source,
            root_dir=slot.root,
            action="record_interrupted",
            cancellation_fallback=slot.retry_policy.write_recovery_marker,
        )
    _clear_retry_generation(slot, generation)
    _raise_if_cancellation_requested(cancellation_requested)


async def _settle_and_observe_managed_job(
    slot: _WatcherConvergenceSlot,
    snapshot: JobSnapshot,
    *,
    result: JobExecutionResult | None,
    error: BaseException | None,
) -> None:
    """Settle durable retry truth before releasing the convergence slot."""
    await _settle_managed_retry(slot, snapshot, error=error)
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
    root = slot.root.resolve()
    with _RETRY_SETTLEMENTS_LOCK:
        _RETRY_SETTLEMENTS.setdefault(root, set()).add(task)
    task.add_done_callback(partial(_finish_retry_settlement, slot))


def _finish_retry_settlement(
    slot: _WatcherConvergenceSlot,
    task: asyncio.Task[None],
) -> None:
    """Release global ownership only after recording settlement diagnostics."""
    _log_retry_settlement_result(slot, task)
    root = slot.root.resolve()
    with _RETRY_SETTLEMENTS_LOCK:
        tasks = _RETRY_SETTLEMENTS.get(root)
        if tasks is None:
            return
        tasks.discard(task)
        if not tasks:
            _RETRY_SETTLEMENTS.pop(root, None)


async def wait_for_retry_settlements(root: Path, deadline: float) -> bool:
    """Join exact retry settlements under the caller's existing time bound."""
    resolved = root.resolve()
    while True:
        with _RETRY_SETTLEMENTS_LOCK:
            tasks = tuple(_RETRY_SETTLEMENTS.get(resolved, ()))
        if not tasks:
            return True
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        done, pending = await asyncio.wait(tasks, timeout=remaining)
        if pending:
            return False
        if any(task.cancelled() or task.exception() is not None for task in done):
            return False
        await asyncio.sleep(0)


def retry_settlements_released(root: Path) -> bool:
    """Return whether no durable retry transaction remains owned for a root."""
    with _RETRY_SETTLEMENTS_LOCK:
        return not _RETRY_SETTLEMENTS.get(root.resolve())


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


def _run_managed_index_attempt(
    slot: _WatcherConvergenceSlot,
    context: JobAttemptContext,
    *,
    secondary_graph_cache: GraphCache | None,
) -> JobExecutionResult:
    """Run one watcher generation under manager and registry ownership."""
    _generation, requires_unscoped = _retry_generation_for_attempt(
        slot,
        context.attempt,
    )
    captured_paths = slot.capture_attempt(context.attempt)
    paths = None if requires_unscoped else captured_paths
    pipeline_active = slot.source is JobSource.CODE
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
                reporter = _jobs.JobProgressReporter(
                    context.job_id,
                    context=context,
                )
                if slot.source is JobSource.VAULT:
                    result = project.vault_indexer.incremental_index(
                        reporter=reporter,
                        changed_paths=paths,
                        run_control=context.control,
                    )
                    project.graph_cache.invalidate()
                    if (
                        secondary_graph_cache is not None
                        and secondary_graph_cache is not project.graph_cache
                    ):
                        secondary_graph_cache.invalidate()
                else:
                    result = project.code_indexer.incremental_index(
                        reporter=reporter,
                        changed_paths=paths,
                        run_control=context.control,
                    )
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
    )


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
        slot.replacement_streak += 1
        delay = min(
            _WATCH_REPLACEMENT_BACKOFF_BASE_SECONDS
            * (2 ** (slot.replacement_streak - 1)),
            _WATCH_REPLACEMENT_BACKOFF_MAX_SECONDS,
        )
        slot.replacement_not_before = now + delay
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

            if snapshot.state in {
                JobState.CANCELLED,
                JobState.FAILED,
                JobState.INTERRUPTED,
            }:
                slot.replacement_streak += 1
                replacement_delay = min(
                    _WATCH_REPLACEMENT_BACKOFF_BASE_SECONDS
                    * (2 ** (slot.replacement_streak - 1)),
                    _WATCH_REPLACEMENT_BACKOFF_MAX_SECONDS,
                )
                slot.replacement_not_before = now + replacement_delay

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
        watcher_owned=watcher_owned,
        pending_count=pending_count,
        replacement_delay=replacement_delay,
        error=error,
    )
    return True


def _log_managed_transition(
    slot: _WatcherConvergenceSlot,
    snapshot: JobSnapshot,
    *,
    watcher_owned: bool,
    pending_count: int,
    replacement_delay: float,
    error: BaseException | None,
) -> None:
    if snapshot.state is JobState.PAUSED:
        log_event(
            logger,
            "service.watcher",
            "reindex_paused",
            source=slot.source.value,
            job_id=snapshot.id,
            pending_paths=pending_count,
        )
    elif snapshot.state is JobState.SUCCEEDED and watcher_owned:
        log_event(
            logger,
            "service.watcher",
            "reindex_completed",
            source=slot.source.value,
            job_id=snapshot.id,
            result=snapshot.result,
            pending_paths=pending_count,
        )
    elif snapshot.state is JobState.CANCELLED:
        log_event(
            logger,
            "service.watcher",
            "replacement_scheduled",
            source=slot.source.value,
            job_id=snapshot.id,
            replacement_backoff_seconds=f"{replacement_delay:.0f}",
            pending_paths=pending_count,
        )
    elif snapshot.state is JobState.SUCCEEDED:
        log_event(
            logger,
            "service.watcher",
            "coalesced_job_completed",
            source=slot.source.value,
            job_id=snapshot.id,
            pending_paths=pending_count,
        )
    else:
        log_event(
            logger,
            "service.watcher",
            "reindex_failed",
            severity=logging.ERROR,
            exc_info=error is not None,
            source=slot.source.value,
            job_id=snapshot.id,
            state=snapshot.state.value,
            error=error or snapshot.result,
            pending_paths=pending_count,
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
        slot.replacement_streak += 1
        delay = min(
            _WATCH_REPLACEMENT_BACKOFF_BASE_SECONDS
            * (2 ** (slot.replacement_streak - 1)),
            _WATCH_REPLACEMENT_BACKOFF_MAX_SECONDS,
        )
        slot.replacement_not_before = now + delay
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
