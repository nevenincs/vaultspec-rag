"""Filesystem watcher for automatic vault/codebase re-indexing.

Uses watchfiles.awatch() to monitor .vault/ for documentation changes
and the project root for source code changes. Triggers incremental
re-indexing when changes are detected.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

from watchfiles import (
    Change,
    awatch,  # pyright: ignore[reportUnknownVariableType]  # watchfiles awatch return type is partially stubbed
)

from . import jobs as _jobs
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

if TYPE_CHECKING:
    import asyncio

    from .graph_cache import GraphCache
    from .indexer import CodebaseIndexer, VaultIndexer
    from .indexer._preprocess_config import PreprocessConfig

logger = logging.getLogger(__name__)

# Extensions recognized as vault documentation
_VAULT_EXTENSIONS = frozenset({".md"})

# Extensions recognized as indexable source code (mirrors CodebaseIndexer)
_CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".rs",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".rb",
        ".swift",
        ".kt",
        ".lua",
        ".zig",
        # Plain-text/markup tails added to LANGUAGE_MAP (#185 adjacent ask) so a
        # watched edit to one triggers a reindex like any other source file.
        ".txt",
        ".xml",
        ".xsd",
        ".properties",
        # Non-vault markdown is indexed as code (LANGUAGE_MAP has .md); vault
        # classification wins first in the change filter, so only markdown
        # outside .vault/ arrives here.
        ".md",
    }
)

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
    return path.suffix in _VAULT_EXTENSIONS


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
    if path.suffix in _CODE_EXTENSIONS:
        return True
    if preprocess_config is not None:
        rel_posix = str(rel).replace("\\", "/")
        return preprocess_config.match(rel_posix) is not None
    return False


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
    log_event(
        logger,
        "service.watcher",
        "started",
        root=root_dir,
        vault=vault_dir,
        debounce_ms=debounce,
        cooldown_seconds=f"{cooldown:.0f}",
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
    vault_slot = _WatcherConvergenceSlot(JobSource.VAULT, resolved_root)
    code_slot = _WatcherConvergenceSlot(JobSource.CODE, resolved_root)
    # Resolved at watcher start so a watched change to a preprocessable file
    # (e.g. a .pdf) routes through the same debounce/cooldown machinery, and
    # re-resolved whenever the root preprocess config itself changes so a rule
    # added mid-session admits its target files without a restart. Held in a
    # single-slot list because the change filter closes over it and must see
    # the refreshed config after a reload.
    prep_config: list[PreprocessConfig] = [code_indexer.preprocess_config()]

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
            # ``changes`` is empty on an idle tick (yield_on_timeout): the loop
            # body below still runs, re-checking the cooldown and flushing any
            # carried-forward pending set, so a change suppressed during a
            # cooldown window is reconciled even when no further change arrives.
            for change_type, path_str in changes:
                path = Path(path_str)
                if change_type in (Change.added, Change.modified, Change.deleted):
                    if (
                        path.name == PREPROCESS_CONFIG_FILENAME
                        and path.parent == root_dir
                    ):
                        prep_config[0] = code_indexer.preprocess_config()
                        log_event(
                            logger,
                            "service.watcher",
                            "preprocess_config_reloaded",
                            root=root_dir,
                            rules=len(prep_config[0].rules),
                        )
                    if _is_vault_change(path, vault_dir):
                        vault_slot.add_dirty(path)
                    elif _is_code_change(path, root_dir, vault_dir, prep_config[0]):
                        code_slot.add_dirty(path)

            now = time.monotonic()

            _reconcile_watcher_slot(
                vault_slot,
                cooldown=cooldown,
                now=now,
                secondary_graph_cache=graph_cache,
            )
            _reconcile_watcher_slot(
                code_slot,
                cooldown=cooldown,
                now=now,
            )
    finally:
        # The manager, not this intake task, owns any admitted attempt. Watcher
        # shutdown must not publish a false cancellation while a worker can
        # still mutate storage; the service lifecycle joins that owner.
        log_event(logger, "service.watcher", "stopped", root=root_dir)


def _reconcile_watcher_slot(
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

    if job_id is not None:
        snapshot = manager.get(job_id)
        if snapshot is None:
            _release_missing_job(slot, job_id, now=now)
        else:
            with slot.lock:
                watcher_owned = slot.watcher_owned
            if _observe_managed_job(slot, snapshot, now=now) and watcher_owned:
                _sync_legacy_snapshot(snapshot, result=None, error=None)

    with slot.lock:
        if slot.job_id is not None or not (slot.held_paths or slot.pending_paths):
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

    _submit_watcher_job(
        slot,
        now=now,
        secondary_graph_cache=secondary_graph_cache,
    )


def _submit_watcher_job(
    slot: _WatcherConvergenceSlot,
    *,
    now: float,
    secondary_graph_cache: GraphCache | None,
) -> None:
    """Admit and bind one manager-owned watcher attempt, or coalesce on dedupe."""
    manager = _jobs.get_job_manager()
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
        if _observe_managed_job(
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
        manager.fail_unstarted(job_id, result=bound.message)
        failed = manager.get(job_id)
        observed_terminal = (
            failed is not None
            and failed.state.is_terminal
            and (
                _observe_managed_job(
                    slot,
                    failed,
                    now=time.monotonic(),
                    error=RuntimeError(bound.message),
                )
            )
        )
        if observed_terminal:
            _jobs.record_finish(job_id, error=bound.message)
        else:
            _schedule_replacement(
                slot,
                now=time.monotonic(),
                reason="dispatch_bind_failed",
                error=bound.message,
            )
        return

    dispatched = manager.dispatch(job_id)
    if dispatched.status is JobOutcomeStatus.ERROR:
        manager.fail_unstarted(job_id, result=dispatched.message)
        failed = manager.get(job_id)
        observed_terminal = (
            failed is not None
            and failed.state.is_terminal
            and (
                _observe_managed_job(
                    slot,
                    failed,
                    now=time.monotonic(),
                    error=RuntimeError(dispatched.message),
                )
            )
        )
        if observed_terminal:
            _jobs.record_finish(job_id, error=dispatched.message)
        else:
            _schedule_replacement(
                slot,
                now=time.monotonic(),
                reason="dispatch_failed",
                error=dispatched.message,
            )
        return

    log_event(
        logger,
        "service.watcher",
        "reindex_started",
        source=slot.source.value,
        job_id=job_id,
        pending_paths=slot.pending_count(),
    )


def _run_managed_index_attempt(
    slot: _WatcherConvergenceSlot,
    context: JobAttemptContext,
    *,
    secondary_graph_cache: GraphCache | None,
) -> JobExecutionResult:
    """Run one watcher generation under manager and registry ownership."""
    paths = slot.capture_attempt(context.attempt)
    pipeline_active = slot.source is JobSource.CODE
    registry = get_registry()
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
