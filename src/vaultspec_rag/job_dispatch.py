"""Production indexing bindings for canonical manager-owned jobs."""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from .job_manager import JobAttemptContext, JobExecutionResult
from .job_models import (
    IndexResilienceSnapshot,
    JobMode,
    JobOperation,
    JobOutcome,
    JobSource,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .indexer import CodebaseIndexer, DocumentIndexer
    from .indexer._codebase_indexer import CodeIndexPreflight
    from .indexer._document_indexer import DocumentIndexPreflight
    from .job_manager import JobManager
    from .job_models import JobSnapshot
    from .service import ServiceRegistry


def bind_index_job(
    manager: JobManager,
    job_id: str,
    *,
    registry: ServiceRegistry,
    code_preflight: CodeIndexPreflight | None,
    document_preflight: DocumentIndexPreflight | None,
    on_started: Callable[[JobSnapshot], None] | None = None,
    on_finished: (
        Callable[
            [JobSnapshot, float, JobExecutionResult | None, BaseException | None],
            None,
        ]
        | None
    ) = None,
) -> JobOutcome:
    """Bind one restored or newly admitted indexing job to production services."""
    # Admission authority proves creation was validated; execution rediscovers
    # after queueing so paused, retried, and restored jobs cannot use stale scope.
    del code_preflight, document_preflight
    snapshot = manager.get(job_id)
    if snapshot is None:
        raise RuntimeError(f"Cannot bind unknown job: {job_id}")
    spec = snapshot.spec
    if (
        spec.operation is not JobOperation.INDEX
        or spec.source not in {JobSource.VAULT, JobSource.CODE, JobSource.DOCUMENT}
        or spec.project_root is None
        or spec.mode is None
    ):
        raise RuntimeError(f"Cannot bind unsupported durable job: {job_id}")
    root = Path(spec.project_root).resolve()
    clean = spec.mode is JobMode.REBUILD
    if spec.source is JobSource.VAULT:
        runner = partial(
            _run_vault_attempt,
            manager=manager,
            job_id=job_id,
            root=root,
            clean=clean,
            registry=registry,
        )
    elif spec.source is JobSource.CODE:
        runner = partial(
            _run_code_attempt,
            manager=manager,
            job_id=job_id,
            root=root,
            clean=clean,
            registry=registry,
        )
    else:
        runner = partial(
            _run_document_attempt,
            manager=manager,
            job_id=job_id,
            root=root,
            clean=clean,
            registry=registry,
        )
    return manager.bind_dispatch(
        job_id,
        runner,
        on_started=on_started,
        on_finished=on_finished,
    )


def _run_vault_attempt(
    context: JobAttemptContext,
    *,
    manager: JobManager,
    job_id: str,
    root: Path,
    clean: bool,
    registry: ServiceRegistry,
) -> JobExecutionResult:
    """Run one vault attempt through the exact service registry."""
    from .jobs import JobProgressReporter

    registry.load_model()
    try:
        with registry.lease(root) as slot:
            context.set_resources(project_lease_held=True)
            try:
                context.set_resources(writer_lock_held=True)
                reporter = JobProgressReporter(job_id, context=context)
                snapshot = manager.get(job_id)
                resumed = (
                    snapshot is not None
                    and snapshot.attempt.resumed_from_attempt is not None
                )
                if clean:
                    result = slot.vault_indexer.full_index(
                        clean=not resumed,
                        reporter=reporter,
                        run_control=context.control,
                    )
                else:
                    result = slot.vault_indexer.incremental_index(
                        reporter=reporter,
                        run_control=context.control,
                    )
            finally:
                context.set_resources(writer_lock_held=False)
            slot.graph_cache.invalidate()
    finally:
        context.set_resources(project_lease_held=False)
    return JobExecutionResult(
        summary=(
            f"+{result.added} /{result.updated} "
            f"-{result.removed} ({result.duration_ms}ms)"
        ),
        reuse=result.reuse,
    )


def _run_code_attempt(
    context: JobAttemptContext,
    *,
    manager: JobManager,
    job_id: str,
    root: Path,
    clean: bool,
    registry: ServiceRegistry,
) -> JobExecutionResult:
    """Run one code attempt through fresh execution authority."""
    from .jobs import JobProgressReporter, validate_code_job_admission

    context.control.checkpoint()
    preflight = validate_code_job_admission(root)
    context.set_resilience(_admitted_resilience(JobSource.CODE))
    context.control.checkpoint()
    registry.load_model()
    try:
        with registry.lease(root) as slot:
            context.set_resources(project_lease_held=True)
            try:
                context.set_resources(
                    writer_lock_held=True,
                    pipeline_active=True,
                )
                reporter = JobProgressReporter(job_id, context=context)
                snapshot = manager.get(job_id)
                resumed = (
                    snapshot is not None
                    and snapshot.attempt.resumed_from_attempt is not None
                )
                try:
                    if clean:
                        result = slot.code_indexer.full_index(
                            clean=not resumed,
                            reporter=reporter,
                            preflight=preflight,
                            run_control=context.control,
                        )
                    else:
                        result = slot.code_indexer.incremental_index(
                            reporter=reporter,
                            preflight=preflight,
                            run_control=context.control,
                        )
                finally:
                    _publish_resilience(
                        context,
                        lambda: _code_resilience(slot.code_indexer),
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
        reuse=result.reuse,
    )


def _run_document_attempt(
    context: JobAttemptContext,
    *,
    manager: JobManager,
    job_id: str,
    root: Path,
    clean: bool,
    registry: ServiceRegistry,
) -> JobExecutionResult:
    """Run one document attempt with independent policy and storage state."""
    from .jobs import JobProgressReporter, validate_document_job_admission

    context.control.checkpoint()
    preflight = validate_document_job_admission(
        root,
        run_control=context.control,
    )
    context.set_resilience(_admitted_resilience(JobSource.DOCUMENT))
    context.control.checkpoint()
    registry.load_model()
    try:
        with registry.lease(root) as slot:
            context.set_resources(project_lease_held=True)
            try:
                context.set_resources(writer_lock_held=True, pipeline_active=True)
                reporter = JobProgressReporter(job_id, context=context)
                snapshot = manager.get(job_id)
                resumed = (
                    snapshot is not None
                    and snapshot.attempt.resumed_from_attempt is not None
                )
                try:
                    if clean:
                        result = slot.document_indexer.full_index(
                            clean=not resumed,
                            reporter=reporter,
                            preflight=preflight,
                            run_control=context.control,
                        )
                    else:
                        result = slot.document_indexer.incremental_index(
                            reporter=reporter,
                            preflight=preflight,
                            run_control=context.control,
                        )
                finally:
                    _publish_resilience(
                        context,
                        lambda: _document_resilience(slot.document_indexer),
                    )
            finally:
                context.set_resources(writer_lock_held=False, pipeline_active=False)
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
        reuse=result.reuse,
    )


def _admitted_resilience(source: JobSource) -> IndexResilienceSnapshot:
    """Freeze the selected profile and domain ceilings before model loading."""
    from .config import get_config
    from .index_profiles import IndexDomain, get_index_support_profile

    config = get_config()
    profile = get_index_support_profile(config.index_support_profile)
    domain = IndexDomain.CODE if source is JobSource.CODE else IndexDomain.DOCUMENT
    limits = profile.limits_for(domain)
    from .memory_probe import resolve_index_cuda_ceiling_mb

    mib = 1024**2
    rss_ceiling_mb = limits.rss_bytes / mib
    rss_ceiling_mb = min(rss_ceiling_mb, config.index_rss_ceiling_mb)
    cuda_ceiling_mb = resolve_index_cuda_ceiling_mb(
        configured_mb=config.index_cuda_ceiling_mb,
        headroom_mb=config.index_cuda_headroom_mb,
        profile_cuda_mb=limits.cuda_bytes / mib,
    )
    return IndexResilienceSnapshot(
        rss_ceiling_mb=rss_ceiling_mb,
        cuda_ceiling_mb=cuda_ceiling_mb,
        support_profile=profile.name,
    )


def _checkpoint_resilience(
    checkpoint: object,
    admitted: IndexResilienceSnapshot,
    *,
    peak_rss_mb: float | None,
    peak_cuda_allocated_mb: float | None,
    peak_cuda_reserved_mb: float | None,
) -> IndexResilienceSnapshot:
    """Project one concrete checkpoint without adapter policy recomputation."""
    from .indexer._document_checkpoint import DocumentRunCheckpoint
    from .indexer._run_checkpoint import CodeRunCheckpoint

    if not isinstance(checkpoint, (CodeRunCheckpoint, DocumentRunCheckpoint)):
        return admitted
    generation = checkpoint.ledger.generation(checkpoint.generation_id)
    run = checkpoint.run_policy.snapshot()
    committed_units = checkpoint.ledger.committed_unit_count(checkpoint.generation_id)
    return IndexResilienceSnapshot(
        generation_id=checkpoint.generation_id,
        committed_units=committed_units,
        replayed_units=checkpoint.resumed_units,
        checkpoint_compatible=True,
        last_durable_progress_at=run.last_durable_progress_at,
        no_progress_timeout_seconds=run.timeout_seconds,
        no_progress_remaining_seconds=run.remaining_seconds,
        peak_rss_mb=peak_rss_mb,
        rss_ceiling_mb=admitted.rss_ceiling_mb,
        peak_cuda_allocated_mb=peak_cuda_allocated_mb,
        peak_cuda_reserved_mb=peak_cuda_reserved_mb,
        cuda_ceiling_mb=admitted.cuda_ceiling_mb,
        support_profile=admitted.support_profile,
        terminal_outcome=generation.terminal_state.value,
    )


def _code_resilience(indexer: CodebaseIndexer) -> IndexResilienceSnapshot:
    admitted = _admitted_resilience(JobSource.CODE)
    measurement = indexer.support_measurement
    budget = indexer.memory_budget_snapshot
    mib = 1024**2
    return _checkpoint_resilience(
        indexer.last_checkpoint,
        admitted,
        peak_rss_mb=(
            budget.peak_rss_mb if budget is not None else measurement.rss_bytes / mib
        ),
        peak_cuda_allocated_mb=(
            budget.peak_cuda_allocated_mb if budget is not None else None
        ),
        peak_cuda_reserved_mb=(
            budget.peak_cuda_reserved_mb
            if budget is not None
            else measurement.cuda_bytes / mib
        ),
    )


def _document_resilience(indexer: DocumentIndexer) -> IndexResilienceSnapshot:
    admitted = _admitted_resilience(JobSource.DOCUMENT)
    budget = indexer.memory_budget_snapshot
    return _checkpoint_resilience(
        indexer.last_checkpoint,
        admitted,
        peak_rss_mb=budget.peak_rss_mb if budget is not None else None,
        peak_cuda_allocated_mb=(
            budget.peak_cuda_allocated_mb if budget is not None else None
        ),
        peak_cuda_reserved_mb=(
            budget.peak_cuda_reserved_mb if budget is not None else None
        ),
    )


def _publish_resilience(
    context: JobAttemptContext,
    snapshot_factory: Callable[[], IndexResilienceSnapshot],
) -> None:
    """Publish operability evidence without masking the indexing outcome."""
    try:
        resilience = snapshot_factory()
        if not context.set_resilience(resilience):
            logger.warning("job resilience snapshot was not persisted")
    except Exception:
        logger.warning("job resilience snapshot failed", exc_info=True)
