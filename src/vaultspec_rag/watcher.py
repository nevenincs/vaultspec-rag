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
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from anyio.to_thread import run_sync as _run_in_thread
from watchfiles import (
    Change,
    awatch,  # pyright: ignore[reportUnknownVariableType]  # watchfiles awatch return type is partially stubbed
)

from . import jobs as _jobs
from .concurrency import get_index_limiter
from .indexer._chunking import SUPPORTED_EXTENSIONS
from .indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME
from .logging_config import log_event
from .watcher_retry import (
    WatcherRetryDecision,
    WatcherRetryPolicy,
    WatcherRetryState,
    WatcherRetryStateError,
    WatcherRetryUnavailableError,
    WatcherSource,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .graph_cache import GraphCache
    from .indexer import CodebaseIndexer, VaultIndexer
    from .indexer._preprocess_config import PreprocessConfig

logger = logging.getLogger(__name__)
_CANCELLATION_DURABILITY_SECONDS = 3.0
_CANCELLATION_FALLBACK_SECONDS = 2.0
_STATE_TRANSACTION_WORKER_SLOTS = threading.BoundedSemaphore(4)
_CANCELLATION_FALLBACK_WORKER_SLOTS = threading.BoundedSemaphore(2)

# Extensions recognized as vault documentation
_VAULT_EXTENSIONS = frozenset({".md"})

# One CPU-only source of truth with CodebaseIndexer. Non-vault markdown remains
# code-indexable because vault classification wins before this predicate.
_CODE_EXTENSIONS = frozenset(SUPPORTED_EXTENSIONS)

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
    preprocess_config: PreprocessConfig | None = None,
) -> bool:
    """Return True if path is a source file outside the vault directory.

    A file whose extension is in ``_CODE_EXTENSIONS`` qualifies, and so does a
    file matched by a preprocess rule even when its extension is unsupported
    (#185, D8) - otherwise a watched ``.pdf`` change would never trigger a
    reindex. Ignore filtering still happens downstream in the indexer scan.

    Args:
        path: The changed file path.
        root_dir: Project root directory.
        vault_dir: Vault directory to exclude.
        preprocess_config: Resolved preprocess rules for the root, if any.

    Returns:
        True if path is an indexable source or preprocessable file outside
        vault_dir and inside root_dir, False otherwise.
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
    if path.suffix.lower() in _CODE_EXTENSIONS:
        return True
    if preprocess_config is not None:
        rel_posix = str(rel).replace("\\", "/")
        return preprocess_config.match(rel_posix) is not None
    return False


def _record_changes(
    changes: Iterable[tuple[Change, str]],
    *,
    root_dir: Path,
    vault_dir: Path,
    code_indexer: CodebaseIndexer,
    prep_config: list[PreprocessConfig],
    pending_vault: set[Path],
    pending_code: set[Path],
) -> tuple[bool, bool]:
    """Classify one watcher batch and retain its exact convergence scope."""
    vault_events_observed = False
    code_events_observed = False
    for change_type, path_str in changes:
        path = Path(path_str)
        if change_type not in (Change.added, Change.modified, Change.deleted):
            continue
        if path.name == PREPROCESS_CONFIG_FILENAME and path.parent == root_dir:
            prep_config[0] = code_indexer.preprocess_config()
            log_event(
                logger,
                "service.watcher",
                "preprocess_config_reloaded",
                root=root_dir,
                rules=len(prep_config[0].rules),
            )
        if _is_vault_change(path, vault_dir):
            pending_vault.add(path)
            vault_events_observed = True
        elif _is_code_change(path, root_dir, vault_dir, prep_config[0]):
            pending_code.add(path)
            code_events_observed = True
    return vault_events_observed, code_events_observed


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


async def _collect_watcher_events(
    *,
    root_dir: Path,
    vault_dir: Path,
    code_indexer: CodebaseIndexer,
    stop_event: asyncio.Event,
    debounce: int,
    prep_config: list[PreprocessConfig],
    pending_vault: set[Path],
    pending_code: set[Path],
    vault_retry: WatcherRetryPolicy,
    code_retry: WatcherRetryPolicy,
    dispatch_wakeup: asyncio.Queue[None],
) -> None:
    """Persist incoming intent while indexing runs in the dispatcher task."""
    try:
        async for changes in awatch(
            root_dir,
            debounce=debounce,
            rust_timeout=_WATCH_IDLE_TICK_MS,
            yield_on_timeout=True,
            stop_event=stop_event,
            watch_filter=lambda _change, path: (
                _is_vault_change(Path(path), vault_dir)
                or _is_code_change(Path(path), root_dir, vault_dir, prep_config[0])
            ),
        ):
            vault_events_observed, code_events_observed = _record_changes(
                changes,
                root_dir=root_dir,
                vault_dir=vault_dir,
                code_indexer=code_indexer,
                prep_config=prep_config,
                pending_vault=pending_vault,
                pending_code=pending_code,
            )
            cancellation_requested = await _persist_observed_sources(
                vault_events_observed=vault_events_observed,
                code_events_observed=code_events_observed,
                vault_retry=vault_retry,
                code_retry=code_retry,
                root_dir=root_dir,
            )
            if dispatch_wakeup.empty():
                dispatch_wakeup.put_nowait(None)
            if cancellation_requested:
                raise asyncio.CancelledError
    finally:
        if dispatch_wakeup.empty():
            dispatch_wakeup.put_nowait(None)


async def watch_and_reindex(
    root_dir: Path,
    vault_dir: Path,
    vault_indexer: VaultIndexer,
    code_indexer: CodebaseIndexer,
    stop_event: asyncio.Event,
    graph_cache: GraphCache,
    debounce: int = 2000,
    cooldown: float = 30.0,
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

    # Track last index times per source to enforce the cooldown window.
    _last_vault_index: float = 0.0
    _last_code_index: float = 0.0

    # Paths observed but not yet reindexed (suppressed by cooldown, or
    # dropped by a failed run). A scoped reindex only processes the paths it
    # is handed, so - unlike the former full rescan, which re-discovered
    # everything each run - these must be carried forward and merged into the
    # next run or the edits would be lost (#151).
    active_vault_job: str | None = None
    active_code_job: str | None = None

    pending_vault: set[Path] = set()
    pending_code: set[Path] = set()
    # Resolved at watcher start so a watched change to a preprocessable file
    # (e.g. a .pdf) routes through the same debounce/cooldown machinery, and
    # re-resolved whenever the root preprocess config itself changes so a rule
    # added mid-session admits its target files without a restart. Held in a
    # single-slot list because the change filter closes over it and must see
    # the refreshed config after a reload.
    prep_config: list[PreprocessConfig] = [code_indexer.preprocess_config()]
    dispatch_wakeup: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
    collector = asyncio.create_task(
        _collect_watcher_events(
            root_dir=root_dir,
            vault_dir=vault_dir,
            code_indexer=code_indexer,
            stop_event=stop_event,
            debounce=debounce,
            prep_config=prep_config,
            pending_vault=pending_vault,
            pending_code=pending_code,
            vault_retry=vault_retry,
            code_retry=code_retry,
            dispatch_wakeup=dispatch_wakeup,
        )
    )
    # Evaluate restored durable intent immediately instead of waiting for the
    # first filesystem event or idle tick.
    dispatch_wakeup.put_nowait(None)

    try:
        while True:
            await dispatch_wakeup.get()
            if collector.done():
                await collector
                break
            if stop_event.is_set():
                break

            now = time.monotonic()
            vault_state, vault_refresh_cancelled = await _run_durable_retry_transaction(
                vault_retry.refresh,
                source=WatcherSource.VAULT,
                root_dir=root_dir,
                action="refresh",
            )
            code_state, code_refresh_cancelled = await _run_durable_retry_transaction(
                code_retry.refresh,
                source=WatcherSource.CODE,
                root_dir=root_dir,
                action="refresh",
            )
            _raise_if_cancellation_requested(
                vault_refresh_cancelled or code_refresh_cancelled
            )

            if pending_vault or vault_state.convergence_pending:
                (
                    _last_vault_index,
                    pending_vault,
                    active_vault_job,
                ) = await _process_vault_changes(
                    pending_vault,
                    _last_vault_index,
                    cooldown,
                    now,
                    vault_indexer,
                    graph_cache,
                    active_vault_job,
                    vault_retry,
                )

            if pending_code or code_state.convergence_pending:
                (
                    _last_code_index,
                    pending_code,
                    active_code_job,
                ) = await _process_code_changes(
                    pending_code,
                    _last_code_index,
                    cooldown,
                    now,
                    code_indexer,
                    active_code_job,
                    code_retry,
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
        stop_event.set()
        if not collector.done():
            collector.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await collector
        if active_vault_job is not None:
            _jobs.record_finish(
                active_vault_job, phase="cancelled", error="watcher task stopped"
            )
        if active_code_job is not None:
            _jobs.record_finish(
                active_code_job, phase="cancelled", error="watcher task stopped"
            )
        log_event(logger, "service.watcher", "stopped", root=root_dir)


def _finish_watcher_job(
    job_id: str | None,
    *,
    error: str,
    phase: _jobs.Phase | None = None,
) -> None:
    """Finish a watcher job only when admission created one."""
    if job_id is None:
        return
    if phase is None:
        _jobs.record_finish(job_id, error=error)
    else:
        _jobs.record_finish(job_id, phase=phase, error=error)


async def _interrupt_watcher_attempt(
    policy: WatcherRetryPolicy,
    generation: int,
    *,
    source: WatcherSource,
    root_dir: Path,
    job_id: str | None,
) -> None:
    try:
        await _run_durable_retry_transaction(
            lambda: policy.record_interrupted(generation),
            source=source,
            root_dir=root_dir,
            action="record_interrupted",
            cancellation_fallback=policy.write_recovery_marker,
        )
    finally:
        _finish_watcher_job(
            job_id,
            phase="cancelled",
            error="watcher task cancelled",
        )


async def _record_watcher_failure(
    policy: WatcherRetryPolicy,
    error: Exception,
    generation: int,
    *,
    source: WatcherSource,
    root_dir: Path,
    job_id: str | None,
) -> tuple[WatcherRetryState, bool]:
    try:
        return await _run_durable_retry_transaction(
            partial(policy.record_failure, error, generation),
            source=source,
            root_dir=root_dir,
            action="record_failure",
            cancellation_fallback=policy.write_recovery_marker,
        )
    except asyncio.CancelledError:
        _finish_watcher_job(
            job_id,
            phase="cancelled",
            error="watcher task cancelled during failure settlement",
        )
        raise
    except Exception:
        _finish_watcher_job(job_id, error=str(error))
        raise


async def _record_watcher_success(
    policy: WatcherRetryPolicy,
    generation: int,
    *,
    source: WatcherSource,
    root_dir: Path,
    job_id: str | None,
) -> bool:
    try:
        _state, cancellation_requested = await _run_durable_retry_transaction(
            lambda: policy.record_success(generation),
            source=source,
            root_dir=root_dir,
            action="record_success",
            cancellation_fallback=policy.write_recovery_marker,
        )
    except asyncio.CancelledError:
        _finish_watcher_job(
            job_id,
            phase="cancelled",
            error="watcher task cancelled during success settlement",
        )
        raise
    except Exception as exc:
        if job_id is not None:
            _jobs.record_finish(job_id, error=str(exc))
        raise
    return cancellation_requested


async def _process_vault_changes(
    pending_vault: set[Path],
    _last_vault_index: float,
    cooldown: float,
    now: float,
    vault_indexer: VaultIndexer,
    graph_cache: GraphCache,
    active_vault_job: str | None,
    retry_policy: WatcherRetryPolicy,
) -> tuple[float, set[Path], str | None]:
    import time

    if now - _last_vault_index < cooldown:
        log_event(
            logger,
            "service.watcher",
            "reindex_suppressed",
            severity=logging.DEBUG,
            source="vault",
            cooldown_remaining_seconds=f"{cooldown - (now - _last_vault_index):.0f}",
            pending_paths=len(pending_vault),
        )
        return _last_vault_index, pending_vault, active_vault_job

    decision = await _admit_watcher_attempt(
        retry_policy,
        source=WatcherSource.VAULT,
        root_dir=vault_indexer.root_dir,
    )
    if not decision.admitted:
        if decision.reason != "retry delay active":
            log_event(
                logger,
                "service.watcher",
                "reindex_suppressed",
                severity=logging.DEBUG,
                source="vault",
                reason=decision.reason,
                circuit_state=decision.circuit_state,
                retry_at=f"{decision.retry_at:.3f}",
                retry_in_seconds=f"{decision.retry_in_seconds:.3f}",
                consecutive_failures=retry_policy.state.consecutive_failures,
                pending_paths=len(pending_vault),
            )
        return _last_vault_index, pending_vault, active_vault_job
    attempt_generation = decision.attempt_generation
    if attempt_generation is None:
        raise WatcherRetryStateError("admitted vault attempt has no generation")

    try:
        attempted_paths = frozenset(pending_vault)
        batch = None if decision.requires_unscoped else attempted_paths
        if batch is not None and not batch:
            raise WatcherRetryStateError("scoped vault attempt has no changed paths")
        active_vault_job = _jobs.record_start(
            "vault",
            "watcher",
            project_root=vault_indexer.root_dir,
        )
        log_event(
            logger,
            "service.watcher",
            "reindex_started",
            source="vault",
            job_id=active_vault_job,
            pending_paths=len(attempted_paths),
            scope="scoped" if batch is not None else "unscoped",
            circuit_state=decision.circuit_state,
            attempt_generation=attempt_generation,
        )
        _jobs.record_progress(active_vault_job, "queued")
        result = await _run_in_thread(
            lambda paths=batch, job_id=active_vault_job: (
                vault_indexer.incremental_index(
                    reporter=_jobs.JobProgressReporter(job_id),
                    changed_paths=paths,
                )
            ),
            limiter=get_index_limiter(),
        )
        graph_cache.invalidate()
    except asyncio.CancelledError:
        await _interrupt_watcher_attempt(
            retry_policy,
            attempt_generation,
            source=WatcherSource.VAULT,
            root_dir=vault_indexer.root_dir,
            job_id=active_vault_job,
        )
        raise
    except Exception as exc:
        retry_state, settlement_cancelled = await _record_watcher_failure(
            retry_policy,
            exc,
            attempt_generation,
            source=WatcherSource.VAULT,
            root_dir=vault_indexer.root_dir,
            job_id=active_vault_job,
        )
        _finish_watcher_job(active_vault_job, error=str(exc))
        log_event(
            logger,
            "service.watcher",
            "reindex_failed",
            severity=logging.ERROR,
            exc_info=True,
            source="vault",
            job_id=active_vault_job,
            error=exc,
            error_kind=retry_state.last_error_kind,
            consecutive_failures=retry_state.consecutive_failures,
            circuit_state=retry_state.circuit_state,
            next_retry_at=f"{retry_state.next_retry_at:.3f}",
        )
        _raise_if_cancellation_requested(settlement_cancelled)
    else:
        settlement_cancelled = await _record_watcher_success(
            retry_policy,
            attempt_generation,
            source=WatcherSource.VAULT,
            root_dir=vault_indexer.root_dir,
            job_id=active_vault_job,
        )
        _last_vault_index = time.monotonic()
        pending_vault.difference_update(attempted_paths)
        _jobs.record_finish(
            active_vault_job,
            result=(
                f"+{result.added} /{result.updated} "
                f"-{result.removed} ({result.duration_ms}ms)"
            ),
        )
        log_event(
            logger,
            "service.watcher",
            "reindex_completed",
            source="vault",
            job_id=active_vault_job,
            added=result.added,
            updated=result.updated,
            removed=result.removed,
            duration_ms=result.duration_ms,
        )
        _raise_if_cancellation_requested(settlement_cancelled)
    finally:
        active_vault_job = None
    return _last_vault_index, pending_vault, active_vault_job


async def _process_code_changes(
    pending_code: set[Path],
    _last_code_index: float,
    cooldown: float,
    now: float,
    code_indexer: CodebaseIndexer,
    active_code_job: str | None,
    retry_policy: WatcherRetryPolicy,
) -> tuple[float, set[Path], str | None]:
    import time

    if now - _last_code_index < cooldown:
        log_event(
            logger,
            "service.watcher",
            "reindex_suppressed",
            severity=logging.DEBUG,
            source="code",
            cooldown_remaining_seconds=f"{cooldown - (now - _last_code_index):.0f}",
            pending_paths=len(pending_code),
        )
        return _last_code_index, pending_code, active_code_job

    decision = await _admit_watcher_attempt(
        retry_policy,
        source=WatcherSource.CODE,
        root_dir=code_indexer.root_dir,
    )
    if not decision.admitted:
        if decision.reason != "retry delay active":
            log_event(
                logger,
                "service.watcher",
                "reindex_suppressed",
                severity=logging.DEBUG,
                source="code",
                reason=decision.reason,
                circuit_state=decision.circuit_state,
                retry_at=f"{decision.retry_at:.3f}",
                retry_in_seconds=f"{decision.retry_in_seconds:.3f}",
                consecutive_failures=retry_policy.state.consecutive_failures,
                pending_paths=len(pending_code),
            )
        return _last_code_index, pending_code, active_code_job
    attempt_generation = decision.attempt_generation
    if attempt_generation is None:
        raise WatcherRetryStateError("admitted code attempt has no generation")

    try:
        attempted_paths = frozenset(pending_code)
        batch = None if decision.requires_unscoped else attempted_paths
        if batch is not None and not batch:
            raise WatcherRetryStateError("scoped code attempt has no changed paths")
        active_code_job = _jobs.record_start(
            "code",
            "watcher",
            project_root=code_indexer.root_dir,
        )
        log_event(
            logger,
            "service.watcher",
            "reindex_started",
            source="code",
            job_id=active_code_job,
            pending_paths=len(attempted_paths),
            scope="scoped" if batch is not None else "unscoped",
            circuit_state=decision.circuit_state,
            attempt_generation=attempt_generation,
        )
        _jobs.record_progress(active_code_job, "queued")
        result = await _run_in_thread(
            lambda paths=batch, job_id=active_code_job: code_indexer.incremental_index(
                reporter=_jobs.JobProgressReporter(job_id),
                changed_paths=paths,
            ),
            limiter=get_index_limiter(),
        )
    except asyncio.CancelledError:
        await _interrupt_watcher_attempt(
            retry_policy,
            attempt_generation,
            source=WatcherSource.CODE,
            root_dir=code_indexer.root_dir,
            job_id=active_code_job,
        )
        raise
    except Exception as exc:
        retry_state, settlement_cancelled = await _record_watcher_failure(
            retry_policy,
            exc,
            attempt_generation,
            source=WatcherSource.CODE,
            root_dir=code_indexer.root_dir,
            job_id=active_code_job,
        )
        _finish_watcher_job(active_code_job, error=str(exc))
        log_event(
            logger,
            "service.watcher",
            "reindex_failed",
            severity=logging.ERROR,
            exc_info=True,
            source="code",
            job_id=active_code_job,
            error=exc,
            error_kind=retry_state.last_error_kind,
            consecutive_failures=retry_state.consecutive_failures,
            circuit_state=retry_state.circuit_state,
            next_retry_at=f"{retry_state.next_retry_at:.3f}",
        )
        _raise_if_cancellation_requested(settlement_cancelled)
    else:
        settlement_cancelled = await _record_watcher_success(
            retry_policy,
            attempt_generation,
            source=WatcherSource.CODE,
            root_dir=code_indexer.root_dir,
            job_id=active_code_job,
        )
        _last_code_index = time.monotonic()
        pending_code.difference_update(attempted_paths)
        skipped_suffix = (
            f" ~{result.preprocess_skipped}" if result.preprocess_skipped else ""
        )
        _jobs.record_finish(
            active_code_job,
            result=(
                f"+{result.added} /{result.updated} "
                f"-{result.removed} ({result.duration_ms}ms){skipped_suffix}"
            ),
            preprocess_ok=result.preprocess_ok,
            preprocess_skipped=result.preprocess_skipped,
            preprocess_failures=result.preprocess_failures,
        )
        log_event(
            logger,
            "service.watcher",
            "reindex_completed",
            source="code",
            job_id=active_code_job,
            added=result.added,
            updated=result.updated,
            removed=result.removed,
            duration_ms=result.duration_ms,
        )
        _raise_if_cancellation_requested(settlement_cancelled)
    finally:
        active_code_job = None
    return _last_code_index, pending_code, active_code_job
