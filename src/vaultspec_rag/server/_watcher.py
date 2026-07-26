"""Filesystem-watcher lifecycle for resident projects.

Split out of the original ``server.py`` monolith. The watcher bookkeeping dicts and lock
are mutated in place; the registry is read through the package alias so
a test rebind of ``_registry`` is observed. ``_ensure_watcher`` keeps
its literal ``_registry.peek_project`` call - a source-inspection
regression test asserts that string is present.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

__all__ = [
    "WatcherStartOutcome",
    "_ensure_watcher",
    "_ensure_watcher_soon",
    "_stop_all_watchers",
    "_stop_watcher",
    "_wait_for_watcher_cleanup",
]

import vaultspec_rag.server as _m

from ..logging_config import log_event

if TYPE_CHECKING:
    from ..config import VaultSpecConfigWrapper
    from ..job_models import JobSnapshot
    from ..service import ProjectSlot, ServiceRegistry

logger = logging.getLogger("vaultspec_rag.server")


class WatcherStartOutcome(StrEnum):
    """What a start request achieved for one root, at the moment it returned.

    A start request is answered without waiting: an owner that has not yet
    released (a draining stop, an in-flight warm) can hold the real start for
    as long as the shutdown bound allows, and holding the caller for that
    window would outlive its own request deadline. The outcome therefore
    separates "a watcher is running" from "a start is owed", so an operator is
    never told automatic indexing is back when it is not yet.
    """

    #: A watcher was already running for the root when the request arrived.
    ALREADY_RUNNING = "already_running"
    #: This request published the watcher; it is running on return.
    STARTED = "started"
    #: Another start for the root is mid-flight; this request's overrides were
    #: recorded and that start will publish them.
    PENDING = "pending"
    #: A stop is still draining; the start is queued behind it and publishes
    #: once the old generation releases.
    QUEUED_BEHIND_DRAIN = "queued_behind_drain"
    #: Watching is switched off for the service; no watcher will start.
    DISABLED = "disabled"
    #: No watcher, and none owed: a stop superseded the request, the owning
    #: registry was replaced, or the service is shutting down.
    UNAVAILABLE = "unavailable"

    @property
    def running(self) -> bool:
        """Whether a watcher is running for the root on return."""
        return self in (
            WatcherStartOutcome.ALREADY_RUNNING,
            WatcherStartOutcome.STARTED,
        )

    @property
    def pending(self) -> bool:
        """Whether a start is still owed to the root by another owner."""
        return self in (
            WatcherStartOutcome.PENDING,
            WatcherStartOutcome.QUEUED_BEHIND_DRAIN,
        )


#: Strong references to in-flight deferred watcher starts so the event
#: loop cannot garbage-collect them mid-flight.
_deferred_watcher_tasks: set[asyncio.Task[None]] = set()
_deferred_watcher_roots: dict[Path, asyncio.Task[None]] = {}
_suppressed_deferred_watcher_roots: dict[Path, asyncio.Task[None]] = {}
_deferred_watcher_restarts: dict[Path, tuple[int | None, float | None]] = {}
_watcher_stop_generations: dict[Path, int] = {}
_watcher_starting_generations: dict[Path, int] = {}
_watcher_starting_restarts: dict[Path, tuple[int | None, float | None]] = {}


def _forget_stop_generation_if_idle(root: Path) -> None:
    """Drop an epoch once no old or future watcher generation can observe it."""
    if (
        root not in _m._watcher_tasks
        and root not in _deferred_watcher_roots
        and root not in _suppressed_deferred_watcher_roots
        and root not in _watcher_drains
        and root not in _watcher_restarts
        and root not in _deferred_watcher_restarts
        and root not in _watcher_starting_generations
        and root not in _watcher_starting_restarts
    ):
        _watcher_stop_generations.pop(root, None)


@dataclass(slots=True)
class _WatcherDrain:
    """Private ownership retained after watcher intake is disabled."""

    intake_task: asyncio.Task[None]
    stop_event: asyncio.Event
    cleanup_task: asyncio.Task[bool] | None = None
    last_error: str | None = None


# Public watcher state represents enabled intake only. A stopped watcher moves
# here until its old intake task and every exact manager-owned attempt release.
_watcher_drains: dict[Path, _WatcherDrain] = {}

# Reconfigure is a synchronous stop-then-start adapter. If the old owner is
# still draining, retain the requested overrides and start exactly once after
# release instead of overlapping two watcher generations.
_watcher_restarts: dict[Path, tuple[int | None, float | None]] = {}


def _watcher_task_done(root: Path, task: asyncio.Task[None]) -> None:
    """Turn a natural intake exit into the normal drain/restart lifecycle."""
    from ..watcher import WatcherInitializationError

    error = None if task.cancelled() else task.exception()
    init_failed = isinstance(error, WatcherInitializationError)
    drain: _WatcherDrain | None = None
    with _m._watcher_lock:
        if _m._watcher_tasks.get(root) is not task:
            return
        _m._watcher_tasks.pop(root, None)
        stop_event = _m._watcher_stops.pop(root, None)
        if stop_event is None:
            stop_event = asyncio.Event()
        stop_event.set()
        drain = _WatcherDrain(task, stop_event)
        _watcher_drains[root] = drain
        # A watcher is expected to remain enabled until an explicit stop. A
        # natural return or runtime failure therefore converges through the
        # same bounded drain before publishing one replacement generation. A
        # failed initialization is not recoverable by restarting into the same
        # unreadable state, so it terminally removes the watcher (no re-arm)
        # rather than looping a doomed replacement generation.
        if not init_failed:
            _watcher_restarts[root] = (None, None)
    log_event(
        logger,
        "service.watcher",
        "task_exited",
        severity=logging.ERROR if error is not None else logging.WARNING,
        root=root,
        error=error,
    )
    _schedule_watcher_drain(root, drain)


def _ensure_watcher_soon(root: Path) -> None:
    """Ensure a watcher for *root* without blocking the event loop.

    Per-request callers (the search and reindex routes) must not pay
    the cold project-slot open (50-200ms of store I/O) on the loop
    thread. When the watcher already exists this is a dict probe; when
    it does not, the slot is warmed on a worker thread and the watcher
    registered afterwards.
    """
    from ..config import get_config

    if not get_config().watch_enabled:
        return
    root = root.resolve()
    task: asyncio.Task[None] | None = None
    drain: _WatcherDrain | None = None
    with _m._watcher_lock:
        if root in _m._watcher_tasks or root in _deferred_watcher_roots:
            return
        if root in _suppressed_deferred_watcher_roots:
            # This explicit new request revives the already-running warm only
            # after its registry I/O finishes; it never overlaps that I/O.
            _deferred_watcher_restarts[root] = (None, None)
            return
        if root in _watcher_drains:
            _watcher_restarts[root] = (None, None)
            drain = _watcher_drains[root]
        elif root in _watcher_starting_generations:
            _watcher_starting_restarts[root] = (None, None)
        else:
            generation = _watcher_stop_generations.get(root, 0)
            owner_registry = _m._registry
            # Register under the same lock as the probes. A cross-thread stop
            # can therefore suppress this exact task or advance its epoch.
            task = asyncio.create_task(
                _run_deferred_watcher_start(root, generation, owner_registry)
            )
            _deferred_watcher_roots[root] = task
            _deferred_watcher_tasks.add(task)
    if drain is not None:
        _schedule_watcher_drain(root, drain)
    elif task is not None:
        task.add_done_callback(partial(_forget_deferred_watcher, root))


async def _run_deferred_watcher_start(
    root: Path,
    generation: int,
    owner_registry: ServiceRegistry,
) -> None:
    """Warm one exact registry owner and publish only a valid generation."""
    import anyio.to_thread

    from ..config import get_config

    try:
        slot = await anyio.to_thread.run_sync(lambda: owner_registry.peek_project(root))
    except Exception:
        logger.exception("Deferred watcher start failed for %s", root)
        return
    current = asyncio.current_task()
    if current is None:
        return
    with _m._watcher_lock:
        active = _deferred_watcher_roots.get(root) is current
        suppressed = _suppressed_deferred_watcher_roots.get(root) is current
        restart = _deferred_watcher_restarts.pop(root, None)
        generation_current = _watcher_stop_generations.get(root, 0) == generation
        should_start = (active and generation_current) or (
            (active or suppressed) and restart is not None
        )
        if active:
            _deferred_watcher_roots.pop(root, None)
        elif suppressed:
            _suppressed_deferred_watcher_roots.pop(root, None)
        if not should_start:
            _forget_stop_generation_if_idle(root)
        else:
            debounce_ms, cooldown_s = restart or (None, None)
            _start_watcher_locked(
                root,
                slot=slot,
                registry=owner_registry,
                cfg=get_config(),
                debounce_ms=debounce_ms,
                cooldown_s=cooldown_s,
                expected_generation=_watcher_stop_generations.get(root, 0),
            )


def _forget_deferred_watcher(root: Path, done: asyncio.Task[None]) -> None:
    """Release the strong warm-task reference and its exact root identity."""
    _deferred_watcher_tasks.discard(done)
    with _m._watcher_lock:
        if _deferred_watcher_roots.get(root) is done:
            _deferred_watcher_roots.pop(root, None)
        if _suppressed_deferred_watcher_roots.get(root) is done:
            _suppressed_deferred_watcher_roots.pop(root, None)
        _forget_stop_generation_if_idle(root)


def _ensure_watcher(
    root: Path,
    *,
    debounce_ms: int | None = None,
    cooldown_s: float | None = None,
) -> WatcherStartOutcome:
    """Launch a filesystem watcher for *root* as a background asyncio task.

    Safe to call repeatedly - starts at most one watcher per root.
    Uses a double-check lock pattern to prevent duplicate watcher
    creation when multiple tool handlers finish near-simultaneously.

    Must be called from the async event loop thread (not from a
    worker thread).

    The call never waits for another owner to release, so a request that
    arrives while a stop drains, or while another start warms, records its
    overrides and returns a pending outcome rather than a running one.

    Args:
        root: Project root directory to watch.
        debounce_ms: Optional debounce override (ms); falls back to
            ``cfg.watch_debounce_ms`` when ``None``.
        cooldown_s: Optional cooldown override (s); falls back to
            ``cfg.watch_cooldown_s`` when ``None``.

    Returns:
        The :class:`WatcherStartOutcome` describing the root's real state on
        return. Only ``running`` outcomes mean a watcher is watching.
    """
    from ..config import get_config

    cfg = get_config()
    # watch_enabled is the sole opt-out: when disabled the service is
    # pull-only and no watcher is ever started - including explicit
    # start/reconfigure requests.
    if not cfg.watch_enabled:
        return WatcherStartOutcome.DISABLED
    root = root.resolve()
    drain: _WatcherDrain | None = None
    generation: int | None = None
    owner_registry: ServiceRegistry | None = None
    with _m._watcher_lock:
        if root in _m._watcher_tasks:
            return WatcherStartOutcome.ALREADY_RUNNING
        if (
            root in _deferred_watcher_roots
            or root in _suppressed_deferred_watcher_roots
        ):
            _deferred_watcher_restarts[root] = (debounce_ms, cooldown_s)
            return WatcherStartOutcome.PENDING
        if root in _watcher_drains:
            _watcher_restarts[root] = (debounce_ms, cooldown_s)
            drain = _watcher_drains[root]
        elif root in _watcher_starting_generations:
            _watcher_starting_restarts[root] = (debounce_ms, cooldown_s)
            return WatcherStartOutcome.PENDING
        else:
            generation = _watcher_stop_generations.get(root, 0)
            _watcher_starting_generations[root] = generation
            owner_registry = _m._registry
    if drain is not None:
        _schedule_watcher_drain(root, drain)
        return WatcherStartOutcome.QUEUED_BEHIND_DRAIN
    assert generation is not None and owner_registry is not None
    # Preserve the package's rebindable ``_registry.peek_project`` ownership
    # seam while the private helper performs the potentially cold open.
    return _warm_and_publish_watcher(
        root,
        registry=owner_registry,
        cfg=cfg,
        debounce_ms=debounce_ms,
        cooldown_s=cooldown_s,
        expected_generation=generation,
    )


def _warm_and_publish_watcher(
    root: Path,
    *,
    registry: ServiceRegistry,
    cfg: VaultSpecConfigWrapper,
    debounce_ms: int | None,
    cooldown_s: float | None,
    expected_generation: int,
) -> WatcherStartOutcome:
    """Cold-open a slot, then atomically publish only the valid generation."""
    # Resolve the project slot OUTSIDE the lock - peek_project() has its own
    # per-root locking and can take 50-200ms on cold start.
    try:
        slot = registry.peek_project(root)
    except BaseException:
        with _m._watcher_lock:
            if _watcher_starting_generations.get(root) == expected_generation:
                _watcher_starting_generations.pop(root, None)
                _watcher_starting_restarts.pop(root, None)
        raise
    with _m._watcher_lock:
        if _watcher_starting_generations.get(root) == expected_generation:
            _watcher_starting_generations.pop(root, None)
        restart = _watcher_starting_restarts.pop(root, None)
        if (
            _watcher_stop_generations.get(root, 0) != expected_generation
            and restart is None
        ):
            _forget_stop_generation_if_idle(root)
            return WatcherStartOutcome.UNAVAILABLE
        requested_debounce, requested_cooldown = restart or (
            debounce_ms,
            cooldown_s,
        )
        outcome = _start_watcher_locked(
            root,
            slot=slot,
            registry=registry,
            cfg=cfg,
            debounce_ms=requested_debounce,
            cooldown_s=requested_cooldown,
            expected_generation=_watcher_stop_generations.get(root, 0),
        )
        if not (outcome.running or outcome.pending):
            _forget_stop_generation_if_idle(root)
        return outcome


def _start_watcher_locked(
    root: Path,
    *,
    slot: ProjectSlot,
    registry: ServiceRegistry,
    cfg: VaultSpecConfigWrapper,
    debounce_ms: int | None,
    cooldown_s: float | None,
    expected_generation: int,
) -> WatcherStartOutcome:
    """Publish a warmed watcher while ``_watcher_lock`` still owns its epoch."""
    if _watcher_stop_generations.get(root, 0) != expected_generation:
        return WatcherStartOutcome.UNAVAILABLE
    if root in _m._watcher_tasks:
        return WatcherStartOutcome.ALREADY_RUNNING
    if root in _watcher_drains:
        _watcher_restarts[root] = (debounce_ms, cooldown_s)
        return WatcherStartOutcome.QUEUED_BEHIND_DRAIN
    if registry is not _m._registry or getattr(registry, "_shutting_down", False):
        return WatcherStartOutcome.UNAVAILABLE
    if not bool(cfg.watch_enabled):
        return WatcherStartOutcome.DISABLED

    from ..watcher import watch_and_reindex

    debounce = (
        int(debounce_ms) if debounce_ms is not None else int(cfg.watch_debounce_ms)
    )
    cooldown = (
        float(cooldown_s) if cooldown_s is not None else float(cfg.watch_cooldown_s)
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        watch_and_reindex(
            root_dir=root,
            vault_dir=root / ".vault",
            vault_indexer=slot.vault_indexer,
            code_indexer=slot.code_indexer,
            document_indexer=slot.document_indexer,
            stop_event=stop_event,
            graph_cache=slot.graph_cache,
            debounce=debounce,
            cooldown=cooldown,
            registry=registry,
        ),
    )
    _m._watcher_tasks[root] = task
    _m._watcher_stops[root] = stop_event
    task.add_done_callback(partial(_watcher_task_done, root))
    log_event(logger, "service.watcher", "task_started", root=root)
    return WatcherStartOutcome.STARTED


def _stop_watcher(root: Path) -> asyncio.Task[bool] | None:
    """Disable watcher intake and start non-blocking owner cleanup.

    Public watcher bookkeeping represents intake enablement, so it is removed
    immediately. The old task remains strongly owned by ``_watcher_drains``
    until it exits and every exact watcher-origin manager attempt releases.
    Stopping a watcher never requests pause or cancellation of a canonical job.

    Args:
        root: Project root directory.

    Returns:
        The owner-loop cleanup task when it can be returned synchronously,
        otherwise ``None`` after thread-safely scheduling cleanup.
    """
    root = root.resolve()
    with _m._watcher_lock:
        has_start_or_owner = (
            root in _m._watcher_tasks
            or root in _deferred_watcher_roots
            or root in _suppressed_deferred_watcher_roots
            or root in _watcher_drains
            or root in _watcher_starting_generations
        )
        if has_start_or_owner:
            _watcher_stop_generations[root] = _watcher_stop_generations.get(root, 0) + 1
        # A later explicit stop wins over a reconfigure/start that was waiting
        # for an earlier generation to drain.
        _watcher_restarts.pop(root, None)
        _deferred_watcher_restarts.pop(root, None)
        _watcher_starting_restarts.pop(root, None)
        deferred = _deferred_watcher_roots.pop(root, None)
        if deferred is not None:
            _suppressed_deferred_watcher_roots[root] = deferred
        drain = _watcher_drains.get(root)
        if drain is None:
            stop_event = _m._watcher_stops.pop(root, None)
            intake_task = _m._watcher_tasks.pop(root, None)
            if intake_task is not None and stop_event is not None:
                drain = _WatcherDrain(intake_task, stop_event)
                _watcher_drains[root] = drain

    # Invalidating the identity is sufficient to suppress a cold start. Its
    # to-thread warm may already be executing and cannot be stopped safely.
    if deferred is not None:
        log_event(logger, "service.watcher", "deferred_start_suppressed", root=root)
    if drain is None:
        return None
    return _schedule_watcher_drain(root, drain)


def _schedule_watcher_drain(
    root: Path,
    drain: _WatcherDrain,
) -> asyncio.Task[bool] | None:
    """Start or reuse one drain on the intake task's owning event loop."""
    owner_loop = drain.intake_task.get_loop()

    def _start_on_owner() -> asyncio.Task[bool] | None:
        with _m._watcher_lock:
            if _watcher_drains.get(root) is not drain:
                return None
            cleanup = drain.cleanup_task
            if cleanup is not None and not cleanup.done():
                return cleanup
            drain.stop_event.set()
            cleanup = owner_loop.create_task(
                _drain_watcher(root, drain),
                name=f"vaultspec-watcher-drain-{root.name}",
            )
            drain.cleanup_task = cleanup
            return cleanup

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    if running_loop is owner_loop:
        return _start_on_owner()
    if owner_loop.is_closed():
        if drain.intake_task.done() and _managed_watcher_resources_released(root):
            with _m._watcher_lock:
                if _watcher_drains.get(root) is drain:
                    _watcher_drains.pop(root, None)
                    _watcher_restarts.pop(root, None)
                    _forget_stop_generation_if_idle(root)
            log_event(logger, "service.watcher", "task_stopped", root=root)
            return None
        drain.last_error = "watcher owner event loop is closed"
        log_event(
            logger,
            "service.watcher",
            "cleanup_unavailable",
            severity=logging.ERROR,
            root=root,
            reason=drain.last_error,
        )
        return None
    owner_loop.call_soon_threadsafe(_start_on_owner)
    return None


async def _watcher_release_error(
    root: Path,
    drain: _WatcherDrain,
    *,
    deadline: float,
    timeout: float,
) -> str | None:
    """Return the first ownership layer that misses the shared deadline."""
    if not await _wait_for_intake_release(root, drain.intake_task, deadline):
        return f"watcher intake did not stop within {timeout:g} seconds"
    if not await _wait_for_managed_watcher_attempts(root, deadline):
        return f"watcher-owned job resources did not release within {timeout:g} seconds"
    from ..watcher import wait_for_retry_settlements

    if not await wait_for_retry_settlements(root, deadline):
        return (
            "watcher durable retry settlement did not complete within "
            f"{timeout:g} seconds"
        )
    return None


async def _drain_watcher(root: Path, drain: _WatcherDrain) -> bool:
    """Boundedly join intake and exact manager resources for one root."""
    from ..config import get_config

    timeout = float(get_config().job_shutdown_timeout_seconds)
    deadline = asyncio.get_running_loop().time() + timeout
    succeeded = False
    try:
        drain.last_error = await _watcher_release_error(
            root,
            drain,
            deadline=deadline,
            timeout=timeout,
        )
        if drain.last_error is not None:
            _log_cleanup_timeout(root, drain.last_error)
            return False

        with _m._watcher_lock:
            if _watcher_drains.get(root) is not drain:
                return True
            _watcher_drains.pop(root, None)
            restart = _watcher_restarts.pop(root, None)
            if restart is None:
                _forget_stop_generation_if_idle(root)
                restart_generation = None
                restart_registry = None
            else:
                restart_generation = _watcher_stop_generations.get(root, 0)
                _watcher_starting_generations[root] = restart_generation
                restart_registry = _m._registry
        drain.last_error = None
        succeeded = True
        log_event(logger, "service.watcher", "task_stopped", root=root)
        if (
            restart is not None
            and restart_generation is not None
            and restart_registry is not None
        ):
            debounce_ms, cooldown_s = restart
            try:
                _warm_and_publish_watcher(
                    root,
                    registry=restart_registry,
                    cfg=get_config(),
                    debounce_ms=debounce_ms,
                    cooldown_s=cooldown_s,
                    expected_generation=restart_generation,
                )
            except Exception:
                logger.exception("Deferred watcher restart failed for %s", root)
        return True
    except asyncio.CancelledError:
        drain.last_error = "watcher cleanup task was interrupted"
        raise
    except Exception as exc:
        drain.last_error = str(exc)
        log_event(
            logger,
            "service.watcher",
            "cleanup_failed",
            severity=logging.ERROR,
            root=root,
            error=str(exc),
            exc_info=True,
        )
        return False
    finally:
        if not succeeded:
            current = asyncio.current_task()
            with _m._watcher_lock:
                if _watcher_drains.get(root) is drain and drain.cleanup_task is current:
                    # Retain the drain's intake/resource ownership for a later
                    # bounded retry, but do not retain a completed Task as if
                    # cleanup were still in progress.
                    drain.cleanup_task = None


async def _wait_for_intake_release(
    root: Path,
    intake_task: asyncio.Task[None],
    deadline: float,
) -> bool:
    """Wait for one intake coroutine without propagating cancellation to it."""
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        return False
    try:
        await asyncio.wait_for(asyncio.shield(intake_task), timeout=remaining)
    except TimeoutError:
        return False
    except asyncio.CancelledError:
        if not intake_task.cancelled():
            raise
        logger.warning("Watcher intake task for %s was cancelled externally", root)
    except Exception:
        logger.exception("Watcher intake task failed while stopping %s", root)
    return True


async def _wait_for_managed_watcher_attempts(root: Path, deadline: float) -> bool:
    """Join natural release of exact watcher-origin attempts under one bound."""
    from .. import jobs as _jobs

    manager = _jobs.get_job_manager()
    released_generations: set[tuple[str, int]] = set()
    while True:
        candidates = [
            snapshot
            for snapshot in _active_watcher_jobs(root)
            if (snapshot.id, snapshot.attempt.number) not in released_generations
        ]
        if not candidates:
            return True
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        outcomes = await asyncio.gather(
            *(
                manager.wait_for_attempt(
                    snapshot.id,
                    timeout_seconds=remaining,
                )
                for snapshot in candidates
            )
        )
        if any(outcome.code == "attempt_join_timeout" for outcome in outcomes):
            return False
        released_generations.update(
            (snapshot.id, snapshot.attempt.number) for snapshot in candidates
        )
        # Let synchronous completion callbacks publish any resume generation
        # before the next exact scan.
        await asyncio.sleep(0)


def _active_watcher_jobs(root: Path) -> list[JobSnapshot]:
    """Return exact active indexing jobs originated by this watcher root."""
    from .. import jobs as _jobs
    from ..job_models import JobOperation, JobSource

    return [
        snapshot
        for snapshot in _jobs.get_job_manager().active()
        if snapshot.spec.operation is JobOperation.INDEX
        and snapshot.spec.source
        in {JobSource.VAULT, JobSource.CODE, JobSource.DOCUMENT}
        and snapshot.initiator.kind == "watcher"
        and snapshot.spec.project_root is not None
        and Path(snapshot.spec.project_root).resolve() == root
    ]


def _managed_watcher_resources_released(root: Path) -> bool:
    """Return whether snapshots prove no watcher attempt owns live resources."""
    from ..watcher import retry_settlements_released

    return retry_settlements_released(root) and all(
        not snapshot.runtime.task_active
        and not snapshot.runtime.worker_active
        and not snapshot.resources.index_capacity_held
        and not snapshot.resources.project_lease_held
        and not snapshot.resources.writer_lock_held
        and not snapshot.resources.pipeline_active
        for snapshot in _active_watcher_jobs(root)
    )


def _log_cleanup_timeout(root: Path, reason: str) -> None:
    log_event(
        logger,
        "service.watcher",
        "cleanup_timeout",
        severity=logging.ERROR,
        root=root,
        reason=reason,
    )


def _stop_all_watchers() -> tuple[asyncio.Task[bool], ...]:
    """Disable every watcher and expose owner-loop drains to async callers."""
    with _m._watcher_lock:
        roots = set(_m._watcher_tasks) | set(_watcher_drains)
        roots.update(_deferred_watcher_roots)
        roots.update(_suppressed_deferred_watcher_roots)
        roots.update(_watcher_starting_generations)
    cleanup_tasks: list[asyncio.Task[bool]] = []
    for root in roots:
        cleanup = _m._stop_watcher(root)
        if cleanup is not None:
            cleanup_tasks.append(cleanup)
    return tuple(cleanup_tasks)


async def _wait_for_watcher_cleanup(
    root: Path | None = None,
    *,
    timeout_seconds: float | None = None,
) -> bool:
    """Boundedly await current watcher drains without cancelling them.

    This is the bounded lifecycle hand-off for a watcher drain. A failed or
    timed-out private drain remains retryable and never changes the
    corresponding canonical job state.
    """
    from ..config import get_config

    timeout = (
        float(get_config().job_shutdown_timeout_seconds)
        if timeout_seconds is None
        else float(timeout_seconds)
    )
    if timeout <= 0:
        raise ValueError("timeout_seconds must be positive")
    target = root.resolve() if root is not None else None
    starting, drains, deferred = _watcher_cleanup_snapshot(target)
    cleanup_tasks = _schedule_watcher_drains(drains)
    awaited: set[asyncio.Task[bool] | asyncio.Task[None]] = set(cleanup_tasks)
    awaited.update(deferred)
    if not awaited:
        return not starting and not drains and not deferred
    _done, pending = await asyncio.wait(awaited, timeout=timeout)
    if pending or _watcher_start_in_progress(target):
        return False
    return _watcher_cleanup_results_ok(cleanup_tasks, deferred)


def _watcher_cleanup_snapshot(
    target: Path | None,
) -> tuple[
    bool,
    list[tuple[Path, _WatcherDrain]],
    list[asyncio.Task[None]],
]:
    """Take one lock-consistent view of pending watcher ownership."""
    with _m._watcher_lock:
        starting = any(
            target is None or candidate == target
            for candidate in _watcher_starting_generations
        )
        drains = [
            (candidate, drain)
            for candidate, drain in _watcher_drains.items()
            if target is None or candidate == target
        ]
        deferred = [
            task
            for candidate, task in (
                *_deferred_watcher_roots.items(),
                *_suppressed_deferred_watcher_roots.items(),
            )
            if target is None or candidate == target
        ]
    return starting, drains, deferred


def _schedule_watcher_drains(
    drains: list[tuple[Path, _WatcherDrain]],
) -> list[asyncio.Task[bool]]:
    """Start every retryable drain and return its owner-loop tasks."""
    return [
        cleanup
        for candidate, drain in drains
        if (cleanup := _schedule_watcher_drain(candidate, drain)) is not None
    ]


def _watcher_start_in_progress(target: Path | None) -> bool:
    """Recheck direct cold-start ownership after an async cleanup wait."""
    with _m._watcher_lock:
        return any(
            target is None or candidate == target
            for candidate in _watcher_starting_generations
        )


def _watcher_cleanup_results_ok(
    cleanup_tasks: list[asyncio.Task[bool]],
    deferred: list[asyncio.Task[None]],
) -> bool:
    """Accept only completed, successful drains and warm-task releases."""
    for cleanup in cleanup_tasks:
        if cleanup.cancelled() or cleanup.exception() is not None:
            return False
        if not cleanup.result():
            return False
    for warm in deferred:
        if warm.cancelled() or warm.exception() is not None:
            return False
    return True
