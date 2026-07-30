"""Managed filesystem-watcher control and indexing execution.

Uses watchfiles.awatch() to monitor .vault/ for documentation changes
and the project root for source code changes. Triggers incremental
re-indexing when changes are detected.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

from anyio.to_thread import run_sync as _run_in_thread

from . import jobs as _jobs
from .job_control import QuiesceRequested
from .job_manager.models import JobAttemptContext, JobExecutionResult, ResourceUpdate
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
from .service_quiesce import QuiesceAdmissionClosedError
from .watcher_durability import (
    raise_if_cancellation_requested,
    run_durable_retry_transaction,
)
from .watcher_retry import (
    WatcherRetryDecision,
    WatcherRetryState,
    WatcherRetryStateError,
    WatcherSource,
)
from .watcher_retry_settlement import register_retry_settlement
from .watcher_runtime import (
    ManagedAttemptInputs,
    ManagedAttemptScope,
    UnstartedFailure,
    WatcherConvergenceSlot,
    observe_managed_job,
    schedule_replacement,
    sync_legacy_snapshot,
)

if TYPE_CHECKING:
    from .graph_cache import GraphCache
    from .indexer._codebase_indexer import CodeExecutionPreflight
    from .indexer._document_indexer import DocumentExecutionPreflight
    from .indexer._vault_prep import IndexResult
    from .service import ProjectComputeRuntime

logger = logging.getLogger(__name__)


async def submit_watcher_job(
    slot: WatcherConvergenceSlot,
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
        schedule_replacement(
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

    await _dispatch_created_watcher_job(
        _CreatedWatcherJobRequest(
            slot=slot,
            manager=manager,
            snapshot=snapshot,
            candidate_paths=candidate_paths,
            code_preflight=code_preflight,
            document_preflight=document_preflight,
            secondary_graph_cache=secondary_graph_cache,
        )
    )


@dataclass(frozen=True, slots=True)
class _CreatedWatcherJobRequest:
    slot: WatcherConvergenceSlot
    manager: _jobs.JobManager
    snapshot: JobSnapshot
    candidate_paths: frozenset[Path]
    code_preflight: CodeExecutionPreflight | None
    document_preflight: DocumentExecutionPreflight | None
    secondary_graph_cache: GraphCache | None


async def _dispatch_created_watcher_job(request: _CreatedWatcherJobRequest) -> None:
    """Bind and dispatch one watcher job already admitted by the manager."""
    slot = request.slot
    manager = request.manager
    snapshot = request.snapshot
    job_id = snapshot.id
    captured_paths = slot.capture_prevalidated_attempt(
        snapshot.attempt.number,
        request.candidate_paths,
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
            ManagedAttemptInputs(
                initial_attempt=snapshot.attempt.number,
                initial_paths=captured_paths,
                code_preflight=request.code_preflight,
                document_preflight=request.document_preflight,
                secondary_graph_cache=request.secondary_graph_cache,
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
        elif observe_managed_job(
            slot,
            finished,
            now=time.monotonic(),
            error=error,
        ):
            sync_legacy_snapshot(
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
            UnstartedFailure(
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
        if dispatched.code == "quiesce_admission_closed":
            deferred = await _run_in_thread(
                partial(manager.defer_unstarted_for_quiesce, job_id),
            )
            if deferred.status is not JobOutcomeStatus.ERROR:
                log_event(
                    logger,
                    "service.watcher",
                    "quiesce_admission_deferred",
                    source=slot.source.value,
                    job_id=job_id,
                    pending_paths=slot.pending_count(),
                )
                return
        await _finish_unstarted_watcher_failure(
            slot,
            UnstartedFailure(
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
    slot: WatcherConvergenceSlot,
    failure: UnstartedFailure,
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
        and observe_managed_job(
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
    schedule_replacement(
        slot,
        now=time.monotonic(),
        reason=failure.reason,
        error=failure.message,
    )


def _retry_generation_for_attempt(
    slot: WatcherConvergenceSlot,
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


def _clear_retry_generation(slot: WatcherConvergenceSlot, generation: int) -> None:
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
    slot: WatcherConvergenceSlot,
    error: BaseException,
    *,
    attempt: int,
    action: str,
) -> WatcherRetryState:
    """Persist one managed orchestration or execution failure."""
    generation, _requires_unscoped = _retry_generation_for_attempt(slot, attempt)
    retry_source = WatcherSource(slot.source.value)
    state, cancellation_requested = await run_durable_retry_transaction(
        partial(slot.retry_policy.record_failure, error, generation),
        source=retry_source,
        root_dir=slot.root,
        action=action,
        cancellation_fallback=slot.retry_policy.write_recovery_marker,
    )
    _clear_retry_generation(slot, generation)
    raise_if_cancellation_requested(cancellation_requested)
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
    slot: WatcherConvergenceSlot,
    *,
    attempt: int,
    action: str,
) -> WatcherRetryState:
    """Release one managed claim while retaining durable dirty intent."""
    generation, _requires_unscoped = _retry_generation_for_attempt(slot, attempt)
    retry_source = WatcherSource(slot.source.value)
    state, cancellation_requested = await run_durable_retry_transaction(
        lambda: slot.retry_policy.record_interrupted(generation),
        source=retry_source,
        root_dir=slot.root,
        action=action,
        cancellation_fallback=slot.retry_policy.write_recovery_marker,
    )
    _clear_retry_generation(slot, generation)
    raise_if_cancellation_requested(cancellation_requested)
    return state


async def _settle_managed_retry(
    slot: WatcherConvergenceSlot,
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
        state, cancellation_requested = await run_durable_retry_transaction(
            lambda: slot.retry_policy.record_success(generation),
            source=retry_source,
            root_dir=slot.root,
            action="record_success",
            cancellation_fallback=slot.retry_policy.write_recovery_marker,
        )
    elif snapshot.state is JobState.FAILED:
        failure = error or RuntimeError(snapshot.result or "watcher indexing failed")
        state, cancellation_requested = await run_durable_retry_transaction(
            partial(slot.retry_policy.record_failure, failure, generation),
            source=retry_source,
            root_dir=slot.root,
            action="record_failure",
            cancellation_fallback=slot.retry_policy.write_recovery_marker,
        )
    else:
        state, cancellation_requested = await run_durable_retry_transaction(
            lambda: slot.retry_policy.record_interrupted(generation),
            source=retry_source,
            root_dir=slot.root,
            action="record_interrupted",
            cancellation_fallback=slot.retry_policy.write_recovery_marker,
        )
    _clear_retry_generation(slot, generation)
    raise_if_cancellation_requested(cancellation_requested)
    return state


async def _settle_and_observe_managed_job(
    slot: WatcherConvergenceSlot,
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
    if observe_managed_job(
        slot,
        snapshot,
        now=time.monotonic(),
        error=error,
    ):
        sync_legacy_snapshot(snapshot, result=result, error=error)


def _track_retry_settlement(
    slot: WatcherConvergenceSlot,
    task: asyncio.Task[None],
) -> None:
    """Keep one settlement strongly owned and visible to watcher drains."""
    register_retry_settlement(
        slot.root,
        task,
        partial(_log_retry_settlement_result, slot),
    )


def _log_retry_settlement_result(
    slot: WatcherConvergenceSlot,
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
    slot: WatcherConvergenceSlot,
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
    slot: WatcherConvergenceSlot,
    context: JobAttemptContext,
    scope: ManagedAttemptScope,
) -> ManagedAttemptScope:
    """Refresh admission authority for retries before model acquisition."""
    code_preflight = scope.code_preflight
    document_preflight = scope.document_preflight
    if slot.source is JobSource.CODE and code_preflight is None:
        context.control.checkpoint()
        code_preflight = (
            _jobs.validate_code_index_policy(slot.root)
            if scope.requires_unscoped
            else _jobs.validate_scoped_code_index_policy(
                slot.root, scope.captured_paths
            )
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
    runtime: ProjectComputeRuntime,
    slot: WatcherConvergenceSlot,
    context: JobAttemptContext,
    scope: ManagedAttemptScope,
    inputs: ManagedAttemptInputs,
) -> IndexResult:
    """Dispatch one exhaustively typed domain under an acquired project lease."""
    reporter = _jobs.JobProgressReporter(context.job_id, context=context)
    if slot.source is JobSource.VAULT:
        result = runtime.vault_indexer.incremental_index(
            reporter=reporter,
            changed_paths=scope.paths,
            run_control=context.control,
        )
        primary_graph_cache = slot.registry.peek_project(slot.root).graph_cache
        primary_graph_cache.invalidate()
        if (
            inputs.secondary_graph_cache is not None
            and inputs.secondary_graph_cache is not primary_graph_cache
        ):
            inputs.secondary_graph_cache.invalidate()
        return result
    if slot.source is JobSource.CODE:
        if scope.code_preflight is None:
            raise RuntimeError("code watcher attempt has no execution preflight")
        return runtime.code_indexer.incremental_index(
            reporter=reporter,
            changed_paths=scope.paths,
            preflight=scope.code_preflight,
            run_control=context.control,
        )
    if scope.document_preflight is None:
        raise RuntimeError("document watcher attempt has no execution preflight")
    return runtime.document_indexer.incremental_index(
        reporter=reporter,
        changed_paths=scope.paths,
        preflight=scope.document_preflight,
        run_control=context.control,
    )


def _run_managed_index_attempt(
    slot: WatcherConvergenceSlot,
    context: JobAttemptContext,
    inputs: ManagedAttemptInputs,
) -> JobExecutionResult:
    """Run one watcher generation under manager and registry ownership."""
    paths, captured_paths, requires_unscoped = _resolve_attempt_scope(
        slot,
        context,
        initial_attempt=inputs.initial_attempt,
        initial_paths=inputs.initial_paths,
    )
    scope = ManagedAttemptScope(
        paths=paths,
        captured_paths=captured_paths,
        requires_unscoped=requires_unscoped,
        code_preflight=(
            inputs.code_preflight if context.attempt == inputs.initial_attempt else None
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
    result: IndexResult | None = None
    try:
        with registry.compute_lease(slot.root) as lease:
            runtime = lease.runtime
            context.set_resources(ResourceUpdate(project_lease_held=True))
            try:
                context.set_resources(
                    ResourceUpdate(
                        writer_lock_held=True,
                        pipeline_active=pipeline_active,
                    )
                )
                try:
                    result = _execute_project_incremental(
                        runtime,
                        slot,
                        context,
                        scope,
                        inputs,
                    )
                finally:
                    _publish_watcher_index_resilience(slot, runtime, context)
            finally:
                context.set_resources(
                    ResourceUpdate(
                        writer_lock_held=False,
                        pipeline_active=False,
                    )
                )
    except QuiesceAdmissionClosedError as exc:
        # The controller may close between intake's admission observation and
        # this worker reaching compute.  Convert that race to the manager's
        # cooperative quiesce outcome so dirty paths are deferred rather than
        # charged to retry/circuit failure state.
        context.control.request_quiesce()
        raise QuiesceRequested() from exc
    finally:
        context.set_resources(ResourceUpdate(project_lease_held=False))
    if result is None:
        raise RuntimeError("watcher index attempt ended without a result")
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
    slot: WatcherConvergenceSlot,
) -> IndexResilienceSnapshot:
    """Project admission and retry truth before model acquisition."""
    if slot.source in {JobSource.CODE, JobSource.DOCUMENT}:
        # Package-internal resilience projectors, shared with the dispatcher.
        from .job_dispatch import (
            _admitted_resilience,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module: shared delegation seam
        )

        base = _admitted_resilience(slot.source)
    else:
        base = IndexResilienceSnapshot()
    return _retry_resilience(slot.retry_policy.state, base=base)


def _publish_watcher_index_resilience(
    slot: WatcherConvergenceSlot,
    runtime: ProjectComputeRuntime,
    context: JobAttemptContext,
) -> None:
    """Publish checkpoint evidence for watcher-owned code and document work."""
    # Package-internal resilience projectors, shared with the dispatcher.
    from .job_dispatch import (
        _code_resilience,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module: shared delegation seam
        _document_resilience,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module: shared delegation seam
        _publish_resilience,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module: shared delegation seam
    )

    if slot.source not in {JobSource.CODE, JobSource.DOCUMENT}:
        return

    def snapshot_factory() -> IndexResilienceSnapshot:
        base = (
            _code_resilience(runtime.code_indexer)
            if slot.source is JobSource.CODE
            else _document_resilience(runtime.document_indexer)
        )
        return _retry_resilience(slot.retry_policy.state, base=base)

    _publish_resilience(context, snapshot_factory)
