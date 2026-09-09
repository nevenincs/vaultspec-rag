"""Managed filesystem-watcher control and indexing execution.

Uses watchfiles.awatch() to monitor .vault/ for documentation changes
and the project root for source code changes. Triggers incremental
re-indexing when changes are detected.
"""

from __future__ import annotations

import logging
import time
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
from .indexer._content_policy import ContentKind
from .indexer._route_migration import prior_stored_owners
from .job_models import (
    JobSource,
)
from .logging_config import log_event
from .registry import get_registry
from .watcher_controller import (
    ControllerLimits,
    ControllerReason,
    ControllerSnapshot,
    ControllerState,
    WatcherController,
)
from .watcher_durability import (
    initialize_retry_policies,
    persist_watcher_observations,
    raise_if_cancellation_requested,
)
from .watcher_execution import controller_scope_from_retry_state, submit_watcher_job
from .watcher_policy import (
    CONFIG_FILENAMES,
    is_code_change,
    is_document_change,
    is_vault_change,
    refresh_watcher_policy,
)
from .watcher_retry import (
    WatcherPathEvent,
    WatcherPathObservation,
    WatcherRetryPolicy,
    WatcherSource,
)
from .watcher_runtime import (
    WatcherChangeRouting,
    WatcherConfiguration,
    WatcherConvergenceSlot,
    reconcile_restarted_slot,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .graph_cache import GraphCache
    from .indexer._resolved_policy import ResolvedIndexPolicy

logger = logging.getLogger(__name__)
# The native watcher uses this bound only to observe shutdown. Controller
# deadlines wake the service scheduler and never re-enter intake as empty polls.
_WATCH_STOP_CHECK_MS = 1000


@dataclass(frozen=True, slots=True)
class _ClassifiedWatcherChange:
    source: WatcherSource
    path: Path
    event: WatcherPathEvent


@dataclass(frozen=True, slots=True)
class _WatcherEventBatch:
    changes: tuple[_ClassifiedWatcherChange, ...]

    def for_source(self, source: WatcherSource) -> tuple[_ClassifiedWatcherChange, ...]:
        return tuple(change for change in self.changes if change.source is source)


#: The change kinds intake acts on. Everything else the platform reports is a
#: notification about a path this watcher does not index.
_ACCEPTED_CHANGES = frozenset({Change.added, Change.modified, Change.deleted})


def _stored_owner_sources(
    owners: frozenset[ContentKind],
    routing: WatcherChangeRouting,
) -> tuple[WatcherSource, ...]:
    """Map recorded per-kind ownership onto the sources that must react.

    Document ownership is dropped when this watcher runs no document slot: the
    record says an index holds the path, but not one this watcher can drive.
    """
    sources: list[WatcherSource] = []
    if ContentKind.CODE in owners:
        sources.append(WatcherSource.CODE)
    if routing.document_slot is not None and ContentKind.DOCUMENT in owners:
        sources.append(WatcherSource.DOCUMENT)
    return tuple(sources)


def _present_path_sources(
    path: Path,
    routing: WatcherChangeRouting,
) -> tuple[WatcherSource, ...]:
    """Classify a path that is still on disk against the intake policy."""
    sources: list[WatcherSource] = []
    if is_code_change(path, routing.root_dir, routing.vault_dir, routing.policy):
        sources.append(WatcherSource.CODE)
    if routing.document_slot is not None and is_document_change(
        path, routing.root_dir, routing.vault_dir, routing.policy
    ):
        sources.append(WatcherSource.DOCUMENT)
    return tuple(sources)


def _change_sources(
    path: Path,
    change_type: Change,
    routing: WatcherChangeRouting,
) -> tuple[WatcherSource, ...]:
    """Name every source one changed path belongs to.

    A deleted path cannot be classified by inspecting it, so its last recorded
    ownership is the evidence of which index still holds it and takes
    precedence. Only when nothing was ever stored does the path fall back to
    the policy classification, which is what admits a file the watcher was
    asked to index but never got to.
    """
    if is_vault_change(path, routing.vault_dir):
        return (WatcherSource.VAULT,)
    if change_type is Change.deleted:
        prior_owners = _deleted_prior_owners(path, root_dir=routing.root_dir)
        if prior_owners:
            return _stored_owner_sources(prior_owners, routing)
    return _present_path_sources(path, routing)


def _classify_watcher_changes(
    changes: Iterable[tuple[Change, str]],
    *,
    routing: WatcherChangeRouting,
) -> _WatcherEventBatch:
    """Classify one intake batch into immutable source-qualified facts."""
    classified: list[_ClassifiedWatcherChange] = []
    for change_type, path_str in changes:
        if change_type not in _ACCEPTED_CHANGES:
            continue
        path = Path(path_str)
        event = WatcherPathEvent(change_type.name)
        classified.extend(
            _ClassifiedWatcherChange(source, path, event)
            for source in _change_sources(path, change_type, routing)
        )
    return _WatcherEventBatch(tuple(classified))


def _deleted_prior_owners(
    path: Path,
    *,
    root_dir: Path,
) -> frozenset[ContentKind]:
    """Return a missing path's last durable per-kind ownership."""
    try:
        rel_path = path.relative_to(root_dir).as_posix()
        prior_owners = prior_stored_owners(root_dir, rel_path)
    except (OSError, RuntimeError, ValueError):
        logger.warning(
            "watcher could not resolve prior ownership for deleted path %s",
            path,
            exc_info=True,
        )
        return frozenset()
    return prior_owners


def _refresh_policy_snapshot(
    root_dir: Path,
    previous: ResolvedIndexPolicy | None,
) -> ResolvedIndexPolicy | None:
    """Resolve intake policy without retaining a compute runtime in the watcher."""
    from .indexer._content_discovery import CodeContentDiscovery

    discovery = CodeContentDiscovery(root_dir)
    return refresh_watcher_policy(discovery.resolve_policy, root_dir, previous)


@dataclass(frozen=True, slots=True)
class _ControllerBinding:
    controller: WatcherController
    slot: WatcherConvergenceSlot
    retry_policy: WatcherRetryPolicy
    secondary_graph_cache: GraphCache | None = None


def _controller_limits() -> ControllerLimits:
    from .config._settings import get_config

    cfg = get_config()
    return ControllerLimits(
        coalesce_min_seconds=float(cfg.watch_coalesce_min_seconds),
        coalesce_max_seconds=float(cfg.watch_coalesce_max_seconds),
        cooling_max_seconds=float(cfg.watch_cooling_max_seconds),
        maximum_freshness_seconds=float(cfg.watch_maximum_freshness_seconds),
        measurement_reevaluation_seconds=float(
            cfg.watch_measurement_reevaluation_seconds
        ),
        batch_path_limit=int(cfg.watch_batch_path_limit),
    )


def _new_controller(retry_policy: WatcherRetryPolicy) -> WatcherController:
    monotonic_now = time.monotonic()
    wall_now = time.time()
    scope = controller_scope_from_retry_state(
        retry_policy.state,
        monotonic_now=monotonic_now,
        wall_now=wall_now,
    )
    state = retry_policy.state
    controller = WatcherController(
        ControllerSnapshot(
            canonical_root=state.canonical_root,
            source=state.source,
            state=ControllerState.IDLE,
            reason=ControllerReason.CONVERGED,
            scope=scope,
            observed_at=wall_now,
            monotonic_at=monotonic_now,
        ),
        monotonic=time.monotonic,
        wall_clock=time.time,
        limits=_controller_limits(),
    )
    if state.scope_refusal is not None:
        controller.refuse(
            ControllerReason(state.scope_refusal.value),
            remediation=(
                "Run an explicit full reindex before resuming automatic updates."
            ),
        )
    elif scope.pending or scope.captured:
        controller.observe(scope)
    return controller


def _register_controller_binding(binding: _ControllerBinding) -> None:
    from .server._watcher import _register_watcher_controller
    from .server._watcher_measurements import capture_watcher_measurement

    measurement_generation = 0

    async def reevaluate() -> None:
        nonlocal measurement_generation
        state = binding.retry_policy.state
        measurement_generation += 1
        observed_at = time.monotonic()
        measurement = await _run_in_thread(
            partial(
                capture_watcher_measurement,
                binding.slot.registry,
                key=(str(binding.slot.root), state.source),
                retry_state=state,
                generation=measurement_generation,
                observed_at=observed_at,
            )
        )
        retry_at = (
            observed_at + max(0.0, state.next_retry_at - time.time())
            if state.next_retry_at
            else None
        )
        binding.controller.evaluate(
            measurement.controller,
            retry_at=retry_at,
            circuit_state=state.circuit_state,
        )

    async def admit(_selection: object) -> None:
        binding.controller.advance(ControllerReason.FAIR_TURN_SELECTED)
        await submit_watcher_job(
            binding.slot,
            controller=binding.controller,
            now=time.monotonic(),
            secondary_graph_cache=binding.secondary_graph_cache,
        )

    _register_watcher_controller(
        binding.controller,
        reevaluate=reevaluate,
        admit=admit,
    )


def _observation_batch(
    changes: tuple[_ClassifiedWatcherChange, ...],
    *,
    root_dir: Path,
    generation: int,
    observed_at: float,
) -> tuple[WatcherPathObservation, ...]:
    merged: dict[str, tuple[Path, set[WatcherPathEvent]]] = {}
    for change in changes:
        relative = change.path.relative_to(root_dir).as_posix()
        _path, events = merged.setdefault(relative, (change.path, set()))
        events.add(change.event)
    return tuple(
        WatcherPathObservation(
            relative_path=relative,
            source=changes[0].source,
            first_observed_at=observed_at,
            latest_observed_at=observed_at,
            event_kinds=frozenset(events),
            generation=generation,
        )
        for relative, (_path, events) in sorted(merged.items())
    )


async def _persist_and_observe_batch(
    batch: _WatcherEventBatch,
    bindings: tuple[_ControllerBinding, ...],
    *,
    root_dir: Path,
) -> bool:
    """Persist every classified source before exposing the batch to execution."""
    cancellation_requested = False
    observed_at = time.time()
    for binding in bindings:
        source_changes = batch.for_source(binding.retry_policy.state.source)
        if not source_changes:
            continue
        observations = _observation_batch(
            source_changes,
            root_dir=root_dir,
            generation=binding.retry_policy.state.convergence_generation + 1,
            observed_at=observed_at,
        )
        cancellation_requested |= await persist_watcher_observations(
            binding.retry_policy,
            observations,
            source=binding.retry_policy.state.source,
            root_dir=root_dir,
        )
        for change in source_changes:
            binding.slot.add_dirty(change.path)
        state = binding.retry_policy.state
        if state.scope_refusal is not None:
            binding.controller.refuse(
                ControllerReason(state.scope_refusal.value),
                remediation=(
                    "Run an explicit full reindex before resuming automatic updates."
                ),
            )
        else:
            binding.controller.observe(
                controller_scope_from_retry_state(
                    binding.retry_policy.state,
                    monotonic_now=time.monotonic(),
                    wall_now=time.time(),
                )
            )
    return cancellation_requested


class WatcherInitializationError(RuntimeError):
    """A watcher could not initialize its durable retry state.

    Raised when retry-policy setup fails deterministically (an unreadable or
    unwritable retry ledger). It is distinct from an indexing error taken
    during the watch loop, which is caught and logged rather than propagated:
    a failed initialization cannot be recovered by restarting into the same
    unreadable state, so the owner terminally removes the watcher instead of
    re-arming it.
    """


async def watch_and_reindex(configuration: WatcherConfiguration) -> None:
    """Watch for file changes and trigger incremental re-indexing.

    Runs until stop_event is set. Accepted path evidence is durable before it
    reaches the legacy execution slot. Each source controller owns adaptive
    collection deadlines, while the service scheduler owns fair admission.

    Args:
        root_dir: Project root directory to watch.
        vault_dir: Path to the .vault/ documentation directory.
        stop_event: Set this event to stop the watcher gracefully.
        debounce: Milliseconds to wait for additional changes
            before processing.
        cooldown: Compatibility input retained by the watcher configuration;
            adaptive policy bounds govern scheduling.
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
    # Only the two the ``watch_filter`` closure reads on every path event are
    # bound locally; every other input is read off the configuration where it
    # is used.
    root_dir = configuration.root_dir
    vault_dir = configuration.vault_dir
    try:
        vault_retry, code_retry, document_retry = await initialize_retry_policies(
            root_dir,
            document_enabled=True,
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
        debounce_ms=configuration.debounce,
        cooldown_seconds=f"{configuration.cooldown:.0f}",
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

    # Each source owns one convergence slot. Manager callbacks and attempt
    # runners cross the event-loop/worker-thread boundary, so generation
    # transfer is protected by the slot's real thread lock.
    owner_registry = (
        configuration.registry if configuration.registry is not None else get_registry()
    )
    vault_slot = WatcherConvergenceSlot(
        JobSource.VAULT,
        resolved_root,
        owner_registry,
        vault_retry,
    )
    code_slot = WatcherConvergenceSlot(
        JobSource.CODE,
        resolved_root,
        owner_registry,
        code_retry,
    )
    document_slot = (
        WatcherConvergenceSlot(
            JobSource.DOCUMENT,
            resolved_root,
            owner_registry,
            document_retry,
        )
        if document_retry is not None
        else None
    )
    manager = _jobs.get_job_manager()
    for slot in (vault_slot, code_slot, document_slot):
        if slot is not None:
            await reconcile_restarted_slot(slot, manager)
    bindings = (
        _ControllerBinding(
            _new_controller(vault_retry),
            vault_slot,
            vault_retry,
            configuration.graph_cache,
        ),
        _ControllerBinding(_new_controller(code_retry), code_slot, code_retry),
        *(
            (
                _ControllerBinding(
                    _new_controller(document_retry),
                    document_slot,
                    document_retry,
                ),
            )
            if document_retry is not None and document_slot is not None
            else ()
        ),
    )
    for binding in bindings:
        _register_controller_binding(binding)
    # One immutable snapshot governs ordinary watcher intake until an
    # index-shaping control event advances the watcher generation. The list is
    # a closure cell shared with ``watch_filter``; invalid policy edits retain
    # the prior intake snapshot while the unconditional control-file event is
    # still sent to the indexer, whose entry gate then fails closed.
    code_policy: list[ResolvedIndexPolicy | None] = [
        _refresh_policy_snapshot(root_dir, None)
    ]

    try:
        async for changes in awatch(
            root_dir,
            debounce=configuration.debounce,
            rust_timeout=_WATCH_STOP_CHECK_MS,
            stop_event=configuration.stop_event,
            watch_filter=lambda _change, path: (
                is_vault_change(Path(path), vault_dir)
                or is_code_change(Path(path), root_dir, vault_dir, code_policy[0])
                or is_document_change(Path(path), root_dir, vault_dir, code_policy[0])
            ),
        ):
            policy_changed = any(
                Path(path_str).name in CONFIG_FILENAMES
                for _change_type, path_str in changes
            )
            if policy_changed:
                code_policy[0] = _refresh_policy_snapshot(root_dir, code_policy[0])
            batch = _classify_watcher_changes(
                changes,
                routing=WatcherChangeRouting(
                    root_dir=resolved_root,
                    vault_dir=vault_dir,
                    policy=code_policy[0],
                    vault_slot=vault_slot,
                    code_slot=code_slot,
                    document_slot=document_slot,
                ),
            )

            cancellation_requested = await _persist_and_observe_batch(
                batch,
                bindings,
                root_dir=resolved_root,
            )
            raise_if_cancellation_requested(cancellation_requested)
            if configuration.stop_event.is_set():
                break
            if batch.changes:
                from .server._watcher import _wake_watcher_scheduler

                _wake_watcher_scheduler()
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
        from .server._watcher import _unregister_watcher_controllers

        _unregister_watcher_controllers(resolved_root)
        # The manager, not this intake task, owns any admitted attempt. Watcher
        # shutdown must not publish a false cancellation while a worker can
        # still mutate storage; the service lifecycle joins that owner.
        log_event(logger, "service.watcher", "stopped", root=root_dir)
