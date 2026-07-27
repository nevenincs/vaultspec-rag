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
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

from anyio.to_thread import run_sync as _run_in_thread

from .logging_config import log_event
from .watcher_retry import (
    WatcherRetryDecision,
    WatcherRetryPolicy,
    WatcherRetryUnavailableError,
    WatcherSource,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .watcher_runtime import ObservedSource


logger = logging.getLogger(__name__)
_CANCELLATION_DURABILITY_SECONDS = 3.0
_CANCELLATION_FALLBACK_SECONDS = 2.0
_STATE_TRANSACTION_WORKER_SLOTS = threading.BoundedSemaphore(4)
_CANCELLATION_FALLBACK_WORKER_SLOTS = threading.BoundedSemaphore(2)


@dataclass(frozen=True, slots=True)
class _DurableTransactionRequest:
    """Durability identity and recovery behavior for one state operation."""

    source: WatcherSource
    root_dir: Path
    action: str
    cancellation_fallback: Callable[[], object] | None = None


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


async def run_durable_retry_transaction[T](
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
    _state, cancellation_requested = await run_durable_retry_transaction(
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


async def persist_observed_sources(
    observed_sources: tuple[ObservedSource, ...],
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


async def admit_watcher_attempt(
    policy: WatcherRetryPolicy,
    *,
    source: WatcherSource,
    root_dir: Path,
) -> WatcherRetryDecision:
    """Admit atomically, settling a claim if cancellation raced its commit."""
    attempt_token = policy.reserve_admission()
    decision, cancellation_requested = await run_durable_retry_transaction(
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
        await run_durable_retry_transaction(
            lambda: policy.record_interrupted(attempt_generation),
            source=source,
            root_dir=root_dir,
            action="interrupt_cancelled_admission",
            cancellation_fallback=policy.write_recovery_marker,
        )
    raise asyncio.CancelledError


def raise_if_cancellation_requested(requested: bool) -> None:
    """Deliver cancellation only after the selected durable outcome exists."""
    if requested:
        raise asyncio.CancelledError


async def initialize_retry_policies(
    root_dir: Path,
    *,
    document_enabled: bool,
) -> tuple[WatcherRetryPolicy, WatcherRetryPolicy, WatcherRetryPolicy | None]:
    """Open one durable retry authority per enabled indexing domain."""
    initialized: list[tuple[WatcherRetryPolicy, bool]] = []
    for source in (WatcherSource.VAULT, WatcherSource.CODE):
        initialized.append(
            await run_durable_retry_transaction(
                lambda selected=source: WatcherRetryPolicy.for_root(root_dir, selected),
                source=source,
                root_dir=root_dir,
                action="initialize",
            )
        )
    document: tuple[WatcherRetryPolicy, bool] | None = None
    if document_enabled:
        document = await run_durable_retry_transaction(
            lambda: WatcherRetryPolicy.for_root(root_dir, WatcherSource.DOCUMENT),
            source=WatcherSource.DOCUMENT,
            root_dir=root_dir,
            action="initialize",
        )
    raise_if_cancellation_requested(
        any(cancelled for _policy, cancelled in initialized)
        or (document is not None and document[1])
    )
    return initialized[0][0], initialized[1][0], document[0] if document else None
