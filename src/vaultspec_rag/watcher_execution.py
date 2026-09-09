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

from . import _job_admission, _job_progress
from . import jobs as _jobs
from .indexer._run_ledger_models import RunAuthority
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
from .watcher_controller import (
    ControllerReason,
    ControllerScope,
    ControllerState,
    ScopeObservation,
    WatcherController,
)
from .watcher_durability import (
    WatcherAttemptOutcome,
    WatcherSettlement,
    admit_scoped_watcher_attempt,
    raise_if_cancellation_requested,
    run_durable_retry_transaction,
    settle_watcher_attempt,
)
from .watcher_retry import (
    WatcherPathEvent,
    WatcherPathObservation,
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
_REBUILD_REMEDIATION = "Run an explicit full reindex before resuming automatic updates."


def controller_scope_from_retry_state(
    state: WatcherRetryState,
    *,
    monotonic_now: float | None = None,
    wall_now: float | None = None,
) -> ControllerScope:
    """Translate one durable exact-scope snapshot onto the process clock."""
    process_now = time.monotonic() if monotonic_now is None else monotonic_now
    persisted_now = time.time() if wall_now is None else wall_now

    def translate(item: WatcherPathObservation) -> ScopeObservation:
        first_age = max(0.0, persisted_now - item.first_observed_at)
        latest_age = max(0.0, persisted_now - item.latest_observed_at)
        return ScopeObservation(
            relative_path=item.relative_path,
            source=item.source,
            first_observed_at=max(0.0, process_now - first_age),
            latest_observed_at=max(0.0, process_now - latest_age),
            event_kinds=frozenset(
                WatcherPathEvent(event) for event in item.event_kinds
            ),
            generation=item.generation,
        )

    return ControllerScope(
        generation=state.convergence_generation,
        pending=tuple(translate(item) for item in state.pending_paths),
        captured_generation=(
            state.attempt_generation if state.captured_paths else None
        ),
        captured=tuple(translate(item) for item in state.captured_paths),
    )


@dataclass(frozen=True, slots=True)
class _ScopedAdmission:
    generation: int
    candidate_paths: frozenset[Path]


def _refuse_unscoped(controller: WatcherController) -> None:
    controller.refuse(
        ControllerReason.FULL_REINDEX_REQUIRED,
        remediation=_REBUILD_REMEDIATION,
    )


async def _capture_scoped_admission(
    slot: WatcherConvergenceSlot,
    controller: WatcherController,
    proposed_job_id: str,
) -> _ScopedAdmission | None:
    retry_source = WatcherSource(slot.source.value)
    retry_state, refresh_cancelled = await run_durable_retry_transaction(
        slot.retry_policy.refresh,
        source=retry_source,
        root_dir=slot.root,
        action="refresh_scoped_admission",
    )
    raise_if_cancellation_requested(refresh_cancelled)
    if retry_state.scope_refusal is not None or retry_state.unscoped_required:
        _refuse_unscoped(controller)
        return None
    if not retry_state.pending_paths:
        return None
    decision = await admit_scoped_watcher_attempt(
        slot.retry_policy,
        proposed_job_id,
        source=retry_source,
        root_dir=slot.root,
    )
    generation = decision.attempt_generation
    if not decision.admitted or generation is None:
        return None
    candidate_paths = frozenset(
        slot.root / item.relative_path
        for item in slot.retry_policy.state.captured_paths
    )
    if candidate_paths and not decision.requires_unscoped:
        return _ScopedAdmission(generation, candidate_paths)
    await settle_watcher_attempt(
        slot.retry_policy,
        generation,
        WatcherSettlement(WatcherAttemptOutcome.INTERRUPTED),
        source=retry_source,
        root_dir=slot.root,
    )
    _refuse_unscoped(controller)
    return None


async def _preflight_scoped_paths(
    slot: WatcherConvergenceSlot,
    candidate_paths: frozenset[Path],
) -> tuple[CodeExecutionPreflight | None, DocumentExecutionPreflight | None]:
    code_preflight = None
    document_preflight = None
    if slot.source is JobSource.CODE:
        code_preflight = await _run_in_thread(
            partial(
                _job_admission.validate_scoped_code_index_policy,
                changed_paths=candidate_paths,
            ),
            slot.root,
        )
    elif slot.source is JobSource.DOCUMENT:
        document_preflight = await _run_in_thread(
            partial(
                _job_admission.validate_scoped_document_index_policy,
                changed_paths=candidate_paths,
            ),
            slot.root,
        )
        await _run_in_thread(
            _job_admission.validate_document_support_profile,
            slot.root,
            document_preflight,
        )
    return code_preflight, document_preflight


async def _restore_uncreated_admission(
    slot: WatcherConvergenceSlot,
    controller: WatcherController,
    admission: _ScopedAdmission,
) -> None:
    """Restore an exact fence when orchestration failed before job creation."""
    retry_state = await settle_watcher_attempt(
        slot.retry_policy,
        admission.generation,
        WatcherSettlement(WatcherAttemptOutcome.INTERRUPTED),
        source=WatcherSource(slot.source.value),
        root_dir=slot.root,
    )
    controller.observe(controller_scope_from_retry_state(retry_state))
    from .server._watcher import _wake_watcher_scheduler

    _wake_watcher_scheduler()


async def submit_watcher_job(
    slot: WatcherConvergenceSlot,
    *,
    controller: WatcherController,
    now: float,
    secondary_graph_cache: GraphCache | None,
) -> None:
    """Fence exact controller scope to one canonical manager job and dispatch."""
    manager = _jobs.get_job_manager()
    with slot.lock:
        existing_job_id = slot.job_id
        settlement = slot.settlement_task
    if settlement is not None:
        if not settlement.done():
            return
        await settlement
        with slot.lock:
            if slot.settlement_task is settlement:
                slot.settlement_task = None
    if existing_job_id is not None:
        existing = manager.get(existing_job_id)
        if existing is not None:
            if observe_managed_job(slot, existing, now=now):
                sync_legacy_snapshot(existing, result=None, error=None)
            return

    proposed_job_id = uuid.uuid4().hex
    admission = await _capture_scoped_admission(slot, controller, proposed_job_id)
    if admission is None:
        return
    with slot.lock:
        slot.retry_attempt_generations[1] = admission.generation
    try:
        code_preflight, document_preflight = await _preflight_scoped_paths(
            slot, admission.candidate_paths
        )
        outcome = await _run_in_thread(
            partial(
                manager.create,
                JobSpec(
                    operation=JobOperation.INDEX,
                    source=slot.source,
                    project_root=str(slot.root),
                    mode=JobMode.INCREMENTAL,
                    authority=RunAuthority.PUBLICATION,
                ),
                JobInitiator(
                    kind="watcher",
                    command=slot.command,
                    project_root=str(slot.root),
                ),
                job_id=proposed_job_id,
            )
        )
    except BaseException:
        if manager.get(proposed_job_id) is None:
            await _restore_uncreated_admission(slot, controller, admission)
        raise
    if outcome.status is JobOutcomeStatus.ERROR or outcome.job is None:
        await _settle_retry_failure(
            slot,
            RuntimeError(outcome.message),
            attempt=1,
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
        slot.retry_attempt_generations[snapshot.attempt.number] = admission.generation

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
        )
        controller.observe(controller_scope_from_retry_state(slot.retry_policy.state))
        return

    controller.admit(snapshot.id)

    await _dispatch_created_watcher_job(
        _CreatedWatcherJobRequest(
            controller=controller,
            slot=slot,
            manager=manager,
            snapshot=snapshot,
            candidate_paths=admission.candidate_paths,
            code_preflight=code_preflight,
            document_preflight=document_preflight,
            secondary_graph_cache=secondary_graph_cache,
        )
    )


@dataclass(frozen=True, slots=True)
class _CreatedWatcherJobRequest:
    controller: WatcherController
    slot: WatcherConvergenceSlot
    manager: _jobs.JobManager
    snapshot: JobSnapshot
    candidate_paths: frozenset[Path]
    code_preflight: CodeExecutionPreflight | None
    document_preflight: DocumentExecutionPreflight | None
    secondary_graph_cache: GraphCache | None


@dataclass(frozen=True, slots=True)
class _ManagedSettlement:
    slot: WatcherConvergenceSlot
    controller: WatcherController
    snapshot: JobSnapshot
    duration_seconds: float
    result: JobExecutionResult | None
    error: BaseException | None


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
        if request.controller.snapshot.state is ControllerState.ADMITTED:
            request.controller.advance(ControllerReason.JOB_STARTED)
        _job_progress.record_progress(started.id, "queued")

    def _on_finished(
        finished: JobSnapshot,
        duration_seconds: float,
        result: JobExecutionResult | None,
        error: BaseException | None,
    ) -> None:
        if finished.state.is_terminal:
            settlement = asyncio.create_task(
                _settle_and_observe_managed_job(
                    _ManagedSettlement(
                        slot,
                        request.controller,
                        finished,
                        duration_seconds,
                        result,
                        error,
                    )
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
            request.controller,
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
            request.controller,
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
    controller: WatcherController,
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
    )
    if controller.snapshot.state in {
        ControllerState.ADMITTED,
        ControllerState.RUNNING,
    }:
        controller.release(controller_scope_from_retry_state(retry_state))
        from .server._watcher import _wake_watcher_scheduler

        _wake_watcher_scheduler()
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
) -> WatcherRetryState:
    """Persist one managed orchestration or execution failure."""
    generation, _requires_unscoped = _retry_generation_for_attempt(slot, attempt)
    retry_source = WatcherSource(slot.source.value)
    state = await settle_watcher_attempt(
        slot.retry_policy,
        generation,
        WatcherSettlement(WatcherAttemptOutcome.FAILED, error),
        source=retry_source,
        root_dir=slot.root,
    )
    _clear_retry_generation(slot, generation)
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
) -> WatcherRetryState:
    """Release one managed claim while retaining durable dirty intent."""
    generation, _requires_unscoped = _retry_generation_for_attempt(slot, attempt)
    retry_source = WatcherSource(slot.source.value)
    state = await settle_watcher_attempt(
        slot.retry_policy,
        generation,
        WatcherSettlement(WatcherAttemptOutcome.INTERRUPTED),
        source=retry_source,
        root_dir=slot.root,
    )
    _clear_retry_generation(slot, generation)
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
        settlement = WatcherSettlement(WatcherAttemptOutcome.SUCCEEDED)
    elif snapshot.state is JobState.FAILED:
        settlement = WatcherSettlement(
            WatcherAttemptOutcome.FAILED,
            error or RuntimeError(snapshot.result or "watcher indexing failed"),
        )
    else:
        settlement = WatcherSettlement(WatcherAttemptOutcome.INTERRUPTED)
    state = await settle_watcher_attempt(
        slot.retry_policy,
        generation,
        settlement,
        source=retry_source,
        root_dir=slot.root,
    )
    _clear_retry_generation(slot, generation)
    return state


async def _settle_and_observe_managed_job(
    request: _ManagedSettlement,
) -> None:
    """Settle durable retry truth before releasing the convergence slot."""
    slot = request.slot
    controller = request.controller
    snapshot = request.snapshot
    retry_state = await _settle_managed_retry(slot, snapshot, error=request.error)
    scope = controller_scope_from_retry_state(retry_state)
    if snapshot.state is JobState.SUCCEEDED:
        if controller.snapshot.state is ControllerState.RUNNING:
            controller.complete(
                scope,
                run_duration=max(0.0, request.duration_seconds),
                publication_duration=0.0,
            )
    elif controller.snapshot.state in {
        ControllerState.ADMITTED,
        ControllerState.RUNNING,
    }:
        controller.release(
            scope,
            superseded=snapshot.state is JobState.SUPERSEDED,
        )
    from .server._watcher import _wake_watcher_scheduler

    _wake_watcher_scheduler()
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
        error=request.error,
    ):
        sync_legacy_snapshot(
            snapshot,
            result=request.result,
            error=request.error,
        )


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
            _job_admission.validate_code_index_policy(slot.root)
            if scope.requires_unscoped
            else _job_admission.validate_scoped_code_index_policy(
                slot.root, scope.captured_paths
            )
        )
        context.control.checkpoint()
    if slot.source is JobSource.DOCUMENT and document_preflight is None:
        context.control.checkpoint()
        document_preflight = (
            _job_admission.validate_document_index_policy(slot.root)
            if scope.requires_unscoped
            else _job_admission.validate_scoped_document_index_policy(
                slot.root, scope.captured_paths
            )
        )
        context.control.checkpoint()
    if slot.source is JobSource.DOCUMENT:
        if document_preflight is None:
            raise RuntimeError("document watcher attempt has no admission preflight")
        _job_admission.validate_document_support_profile(slot.root, document_preflight)
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
            authority=context.authority,
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
            authority=context.authority,
            run_control=context.control,
        )
    if scope.document_preflight is None:
        raise RuntimeError("document watcher attempt has no execution preflight")
    return runtime.document_indexer.incremental_index(
        reporter=reporter,
        changed_paths=scope.paths,
        preflight=scope.document_preflight,
        authority=context.authority,
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
    # Spelled as a tuple, not a set: only the two mapped sources have admitted
    # limits, and the tuple form is the one both type checkers narrow, so the
    # guard is what proves the delegation below is a legal call.
    if slot.source in (JobSource.CODE, JobSource.DOCUMENT):
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
