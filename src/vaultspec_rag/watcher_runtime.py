"""Managed filesystem-watcher control and indexing execution.

Uses watchfiles.awatch() to monitor .vault/ for documentation changes
and the project root for source code changes. Triggers incremental
re-indexing when changes are detected.
"""

from __future__ import annotations

import asyncio  # noqa: TC003
import logging
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003
from threading import RLock
from typing import TYPE_CHECKING

from . import jobs as _jobs
from ._backoff import capped_exponential
from .job_manager.models import JobExecutionResult  # noqa: TC001
from .job_models import (
    JobSnapshot,
    JobSource,
    JobState,
)
from .logging_config import log_event
from .watcher_retry import (
    WatcherRetryPolicy,  # noqa: TC001
    WatcherSource,  # noqa: TC001
)

if TYPE_CHECKING:
    from .graph_cache import GraphCache
    from .indexer import CodebaseIndexer, DocumentIndexer, VaultIndexer
    from .indexer._codebase_indexer import CodeExecutionPreflight
    from .indexer._document_indexer import DocumentExecutionPreflight
    from .indexer._resolved_policy import ResolvedIndexPolicy
    from .service import ServiceRegistry

logger = logging.getLogger(__name__)
# Operator cancellation deliberately leaves watcher convergence dirty. Retry
# delay grows only across consecutive cancellations and is capped so automatic
# freshness remains both non-thrashing and finite.
_WATCH_REPLACEMENT_BACKOFF_BASE_SECONDS = 1.0
_WATCH_REPLACEMENT_BACKOFF_MAX_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class ObservedSource:
    """One watcher domain's observed-event persistence request."""

    observed: bool
    source: WatcherSource
    retry_policy: WatcherRetryPolicy


@dataclass(frozen=True, slots=True)
class WatcherChangeRouting:
    """Immutable routing dependencies for one watcher intake batch."""

    root_dir: Path
    vault_dir: Path
    policy: ResolvedIndexPolicy | None
    vault_slot: WatcherConvergenceSlot
    code_slot: WatcherConvergenceSlot
    document_slot: WatcherConvergenceSlot | None


@dataclass(frozen=True, slots=True)
class WatcherReconciliation:
    """Timing and cache dependencies shared by one convergence pass."""

    cooldown: float
    now: float
    graph_cache: GraphCache


@dataclass(frozen=True, slots=True)
class UnstartedFailure:
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
class ManagedAttemptInputs:
    """Admission proof and shared cache for one watcher manager dispatch."""

    initial_attempt: int
    initial_paths: frozenset[Path]
    code_preflight: CodeExecutionPreflight | None
    document_preflight: DocumentExecutionPreflight | None = None
    secondary_graph_cache: GraphCache | None = None


@dataclass(frozen=True, slots=True)
class ManagedAttemptScope:
    """Resolved execution authority for one manager attempt number."""

    paths: frozenset[Path] | None
    captured_paths: frozenset[Path]
    requires_unscoped: bool
    code_preflight: CodeExecutionPreflight | None
    document_preflight: DocumentExecutionPreflight | None


@dataclass(frozen=True, slots=True)
class WatcherConfiguration:
    """All immutable dependencies and controls for one watcher lifetime."""

    root_dir: Path
    vault_dir: Path
    vault_indexer: VaultIndexer
    code_indexer: CodebaseIndexer
    stop_event: asyncio.Event
    graph_cache: GraphCache
    document_indexer: DocumentIndexer | None = None
    debounce: int = 2000
    cooldown: float = 30.0
    registry: ServiceRegistry | None = None


@dataclass(slots=True)
class WatcherConvergenceSlot:
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


def sync_legacy_snapshot(
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
            details=_jobs.FinishDetails(
                preprocess_ok=result.preprocess_ok if result is not None else 0,
                preprocess_skipped=(
                    result.preprocess_skipped if result is not None else 0
                ),
                preprocess_failures=(
                    list(result.preprocess_failures) if result is not None else None
                ),
                reuse=result.reuse if result is not None else None,
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


def schedule_replacement(
    slot: WatcherConvergenceSlot,
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


def observe_managed_job(
    slot: WatcherConvergenceSlot,
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
    slot: WatcherConvergenceSlot,
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


def release_missing_job(
    slot: WatcherConvergenceSlot,
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
