"""Production indexing bindings for canonical manager-owned jobs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from ._units import bytes_to_mib
from .job_manager.models import JobAttemptContext, JobExecutionResult, ResourceUpdate
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
    from .job_manager.manager import JobManager
    from .job_models import JobSnapshot
    from .service import ServiceRegistry


@dataclass(frozen=True, slots=True)
class IndexJobBinding:
    """Dependencies and callbacks bound to one durable indexing job."""

    manager: JobManager
    job_id: str
    registry: ServiceRegistry
    code_preflight: CodeIndexPreflight | None
    document_preflight: DocumentIndexPreflight | None
    on_started: Callable[[JobSnapshot], None] | None = None
    on_finished: (
        Callable[
            [JobSnapshot, float, JobExecutionResult | None, BaseException | None],
            None,
        ]
        | None
    ) = None


@dataclass(frozen=True, slots=True)
class _AttemptDispatch:
    """Stable execution authority for one source-specific index attempt."""

    source: JobSource
    manager: JobManager
    job_id: str
    root: Path
    clean: bool
    registry: ServiceRegistry


def bind_index_job(binding: IndexJobBinding) -> JobOutcome:
    """Bind one restored or newly admitted indexing job to production services."""
    # Admission authority proves creation was validated; execution rediscovers
    # after queueing so paused, retried, and restored jobs cannot use stale scope.
    _ = (binding.code_preflight, binding.document_preflight)
    snapshot = binding.manager.get(binding.job_id)
    if snapshot is None:
        raise RuntimeError(f"Cannot bind unknown job: {binding.job_id}")
    spec = snapshot.spec
    if (
        spec.operation is not JobOperation.INDEX
        or not spec.source.is_corpus
        or spec.project_root is None
        or spec.mode is None
    ):
        raise RuntimeError(f"Cannot bind unsupported durable job: {binding.job_id}")
    root = Path(spec.project_root).resolve()
    clean = spec.mode is JobMode.REBUILD
    if spec.source is JobSource.VAULT:
        runner = partial(
            _run_vault_attempt,
            dispatch=_AttemptDispatch(
                JobSource.VAULT,
                binding.manager,
                binding.job_id,
                root,
                clean,
                binding.registry,
            ),
        )
    else:
        runner = partial(
            _run_indexing_attempt,
            dispatch=_AttemptDispatch(
                spec.source,
                binding.manager,
                binding.job_id,
                root,
                clean,
                binding.registry,
            ),
        )
    return binding.manager.bind_dispatch(
        binding.job_id,
        runner,
        on_started=binding.on_started,
        on_finished=binding.on_finished,
    )


def _run_vault_attempt(
    context: JobAttemptContext,
    *,
    dispatch: _AttemptDispatch,
) -> JobExecutionResult:
    """Run one vault attempt through the exact service registry."""
    from .jobs import JobProgressReporter

    dispatch.registry.load_model()
    try:
        with dispatch.registry.lease(dispatch.root) as slot:
            context.set_resources(ResourceUpdate(project_lease_held=True))
            try:
                context.set_resources(ResourceUpdate(writer_lock_held=True))
                reporter = JobProgressReporter(dispatch.job_id, context=context)
                snapshot = dispatch.manager.get(dispatch.job_id)
                resumed = (
                    snapshot is not None
                    and snapshot.attempt.resumed_from_attempt is not None
                )
                if dispatch.clean:
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
                context.set_resources(ResourceUpdate(writer_lock_held=False))
            slot.graph_cache.invalidate()
    finally:
        context.set_resources(ResourceUpdate(project_lease_held=False))
    return JobExecutionResult(
        summary=(
            f"+{result.added} /{result.updated} "
            f"-{result.removed} ({result.duration_ms}ms)"
        ),
        reuse=result.reuse,
        drift=result.drift,
    )


def _run_indexing_attempt(
    context: JobAttemptContext,
    *,
    dispatch: _AttemptDispatch,
) -> JobExecutionResult:
    """Run one code or document attempt through fresh execution authority.

    The two were separate functions with identical bodies apart from four
    things: which admission call validates the root, which ``JobSource`` the
    resilience snapshot is taken for, which indexer the leased slot exposes,
    and which reader turns that indexer into resilience evidence. Everything
    else - the lease, the resource bookkeeping, the resumed check, the
    clean/incremental branch, the teardown ordering, and the whole result -
    was the same text twice.

    Merging them matters beyond the repetition. ``load_model`` must be called
    before ``lease``: the model load is the long, GPU-touching step, and doing
    it while holding a project lease blocks every other root for its duration.
    That ordering was guarded on the vault and code runners and NOT on the
    document one, so a third of the paths could have reordered silently. One
    runner means one ordering to guard.

    The vault runner is deliberately not folded in. It takes no admission
    preflight, publishes no resilience, holds no pipeline resource, invalidates
    the graph cache, and returns a result without preprocess fields - it is a
    different job, not this one with different nouns.
    """
    from .jobs import (
        JobProgressReporter,
        validate_code_job_admission,
        validate_document_job_admission,
    )

    # Held as two narrowed locals rather than one union: each indexer accepts
    # only its own preflight type, and the type checker cannot see that the
    # source picks both together. Narrowing keeps the pairing checkable.
    code_preflight: CodeIndexPreflight | None = None
    document_preflight: DocumentIndexPreflight | None = None
    context.control.checkpoint()
    if dispatch.source is JobSource.CODE:
        code_preflight = validate_code_job_admission(dispatch.root)
    else:
        document_preflight = validate_document_job_admission(
            dispatch.root, run_control=context.control
        )
    context.set_resilience(_admitted_resilience(dispatch.source))
    context.control.checkpoint()
    dispatch.registry.load_model()
    try:
        with dispatch.registry.lease(dispatch.root) as slot:
            context.set_resources(ResourceUpdate(project_lease_held=True))
            try:
                context.set_resources(
                    ResourceUpdate(writer_lock_held=True, pipeline_active=True)
                )
                reporter = JobProgressReporter(dispatch.job_id, context=context)
                snapshot = dispatch.manager.get(dispatch.job_id)
                resumed = (
                    snapshot is not None
                    and snapshot.attempt.resumed_from_attempt is not None
                )
                try:
                    if code_preflight is not None:
                        code_indexer = slot.code_indexer
                        result = (
                            code_indexer.full_index(
                                clean=not resumed,
                                reporter=reporter,
                                preflight=code_preflight,
                                run_control=context.control,
                            )
                            if dispatch.clean
                            else code_indexer.incremental_index(
                                reporter=reporter,
                                preflight=code_preflight,
                                run_control=context.control,
                            )
                        )
                    else:
                        document_indexer = slot.document_indexer
                        result = (
                            document_indexer.full_index(
                                clean=not resumed,
                                reporter=reporter,
                                preflight=document_preflight,
                                run_control=context.control,
                            )
                            if dispatch.clean
                            else document_indexer.incremental_index(
                                reporter=reporter,
                                preflight=document_preflight,
                                run_control=context.control,
                            )
                        )
                finally:
                    _publish_resilience(
                        context,
                        (
                            (lambda: _code_resilience(slot.code_indexer))
                            if code_preflight is not None
                            else (lambda: _document_resilience(slot.document_indexer))
                        ),
                    )
            finally:
                context.set_resources(
                    ResourceUpdate(writer_lock_held=False, pipeline_active=False)
                )
    finally:
        context.set_resources(ResourceUpdate(project_lease_held=False))
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
        drift=result.drift,
    )


def _admitted_resilience(source: JobSource) -> IndexResilienceSnapshot:
    """Freeze the selected profile and domain ceilings before model loading."""
    from .config._settings import get_config
    from .index_profiles import IndexDomain, get_index_support_profile

    config = get_config()
    profile = get_index_support_profile(config.index_support_profile)
    domain = IndexDomain.CODE if source is JobSource.CODE else IndexDomain.DOCUMENT
    limits = profile.limits_for(domain)
    from .memory_probe import (
        resident_cuda_baseline_mb,
        resolve_index_cuda_ceiling_mb,
    )

    rss_ceiling_mb = bytes_to_mib(limits.rss_bytes)
    rss_ceiling_mb = min(rss_ceiling_mb, config.index_rss_ceiling_mb)
    # Point-in-time diagnostic only: this snapshot is reported and persisted,
    # never enforced, and may legitimately differ from the later per-job
    # enforcing derivation the budget builders compute post-flush.
    cuda_ceiling_mb = resolve_index_cuda_ceiling_mb(
        configured_mb=config.index_cuda_ceiling_mb,
        headroom_mb=config.index_cuda_headroom_mb,
        profile_cuda_mb=bytes_to_mib(limits.cuda_bytes),
        baseline_mb=resident_cuda_baseline_mb(),
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
    return _checkpoint_resilience(
        indexer.last_checkpoint,
        admitted,
        peak_rss_mb=(
            budget.peak_rss_mb
            if budget is not None
            else bytes_to_mib(measurement.rss_bytes)
        ),
        peak_cuda_allocated_mb=(
            budget.peak_cuda_allocated_mb if budget is not None else None
        ),
        peak_cuda_reserved_mb=(
            budget.peak_cuda_reserved_mb
            if budget is not None
            else bytes_to_mib(measurement.cuda_bytes)
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
