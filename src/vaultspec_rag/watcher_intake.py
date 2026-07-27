"""Managed filesystem-watcher control and indexing execution.

Uses watchfiles.awatch() to monitor .vault/ for documentation changes
and the project root for source code changes. Triggers incremental
re-indexing when changes are detected.
"""

from __future__ import annotations

import asyncio  # noqa: TC003
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

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
from .watcher_durability import (
    admit_watcher_attempt,
    initialize_retry_policies,
    persist_observed_sources,
    raise_if_cancellation_requested,
    run_durable_retry_transaction,
)
from .watcher_execution import _submit_watcher_job
from .watcher_policy import (
    CONFIG_FILENAMES,
    is_code_change,
    is_document_change,
    is_vault_change,
    refresh_watcher_policy,
)
from .watcher_retry import (
    WatcherRetryStateError,
    WatcherSource,
)
from .watcher_runtime import (
    WatcherConfiguration,
    _observe_managed_job,
    _ObservedSource,
    _release_missing_job,
    _sync_legacy_snapshot,
    _WatcherChangeRouting,
    _WatcherConvergenceSlot,
    _WatcherReconciliation,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .graph_cache import GraphCache
    from .indexer._resolved_policy import ResolvedIndexPolicy

logger = logging.getLogger(__name__)
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
        if is_vault_change(path, routing.vault_dir):
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
        if is_code_change(path, routing.root_dir, routing.vault_dir, routing.policy):
            routing.code_slot.add_dirty(path)
            observed[1] = True
        if routing.document_slot is not None and is_document_change(
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


async def watch_and_reindex(configuration: WatcherConfiguration) -> None:
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
    # Only the two the ``watch_filter`` closure reads on every path event are
    # bound locally; every other input is read off the configuration where it
    # is used.
    root_dir = configuration.root_dir
    vault_dir = configuration.vault_dir
    try:
        vault_retry, code_retry, document_retry = await initialize_retry_policies(
            root_dir,
            document_enabled=configuration.document_indexer is not None,
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
    if (
        configuration.vault_indexer.root_dir.resolve() != resolved_root
        or configuration.code_indexer.root_dir.resolve() != resolved_root
        or (
            configuration.document_indexer is not None
            and configuration.document_indexer.root_dir.resolve() != resolved_root
        )
    ):
        raise ValueError("watcher indexers must belong to the watched project root")

    # Each source owns one convergence slot. Manager callbacks and attempt
    # runners cross the event-loop/worker-thread boundary, so generation
    # transfer is protected by the slot's real thread lock.
    owner_registry = (
        configuration.registry if configuration.registry is not None else get_registry()
    )
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
        refresh_watcher_policy(configuration.code_indexer, root_dir, None)
    ]

    try:
        async for changes in awatch(
            root_dir,
            debounce=configuration.debounce,
            rust_timeout=_WATCH_IDLE_TICK_MS,
            yield_on_timeout=True,
            stop_event=configuration.stop_event,
            watch_filter=lambda _change, path: (
                is_vault_change(Path(path), vault_dir)
                or is_code_change(Path(path), root_dir, vault_dir, code_policy[0])
                or is_document_change(Path(path), root_dir, vault_dir, code_policy[0])
            ),
        ):
            # ``changes`` is empty on an idle tick (yield_on_timeout): the loop
            # body below still runs, re-checking the cooldown and flushing any
            # carried-forward pending set, so a change suppressed during a
            # cooldown window is reconciled even when no further change arrives.
            policy_changed = any(
                Path(path_str).name in CONFIG_FILENAMES
                for _change_type, path_str in changes
            )
            if policy_changed:
                code_policy[0] = refresh_watcher_policy(
                    configuration.code_indexer,
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

            cancellation_requested = await persist_observed_sources(
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
            raise_if_cancellation_requested(cancellation_requested)
            if configuration.stop_event.is_set():
                break

            now = time.monotonic()

            await _reconcile_watcher_slots(
                vault_slot,
                code_slot,
                document_slot,
                reconciliation=_WatcherReconciliation(
                    cooldown=configuration.cooldown,
                    now=now,
                    graph_cache=configuration.graph_cache,
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
    retry_state, refresh_cancelled = await run_durable_retry_transaction(
        slot.retry_policy.refresh,
        source=retry_source,
        root_dir=slot.root,
        action="refresh",
    )
    raise_if_cancellation_requested(refresh_cancelled)

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

    decision = await admit_watcher_attempt(
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
