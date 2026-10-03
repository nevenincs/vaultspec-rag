"""Production indexing bindings for canonical manager-owned jobs."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Literal, assert_never

from ._units import bytes_to_mib
from .indexer._run_ledger_models import RunAuthority
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
    from collections.abc import Callable, Generator

    from .index_profiles import IndexDomain
    from .indexer import (
        CodebaseIndexer,
        DocumentIndexer,
        IndexResult,
        VaultIndexer,
    )
    from .indexer._checkpoint_common import RunCheckpointBase
    from .indexer._codebase_indexer import CodeIndexPreflight
    from .indexer._document_indexer import DocumentIndexPreflight
    from .indexer._run_policy import RunPolicySnapshot
    from .job_manager.manager import JobManager
    from .job_models import JobSnapshot
    from .progress import ProgressReporter
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
    """Stable persisted execution contract for one source-specific attempt."""

    source: JobSource
    job_id: str
    root: Path
    mode: JobMode
    authority: RunAuthority
    registry: ServiceRegistry


def _admit_attempt_mode(
    context: JobAttemptContext,
    dispatch: _AttemptDispatch,
) -> bool:
    """Return whether this exact persisted contract admits full execution."""
    if context.authority is not dispatch.authority:
        raise RuntimeError(
            "attempt authority does not match its persisted dispatch authority"
        )
    if dispatch.authority is RunAuthority.AUDIT_VERIFICATION:
        raise RuntimeError(
            "audit-verification authority cannot run a publication index attempt"
        )
    clean = dispatch.mode is JobMode.REBUILD
    if clean and dispatch.authority is not RunAuthority.REBUILD:
        raise RuntimeError("publication authority cannot run a full index attempt")
    return clean


def _bind_index_attempt(
    context: JobAttemptContext,
    dispatch: _AttemptDispatch,
    *,
    indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    reporter: ProgressReporter,
    preflight: CodeIndexPreflight | DocumentIndexPreflight | None = None,
) -> Callable[[], IndexResult]:
    """Bind source execution to persisted authority, independent of attempt lineage.

    A resumed rebuild retains replacement authority. Each source checkpoint
    decides whether its compatible generation can resume confirmed work.
    """
    from .indexer import CodebaseIndexer, DocumentIndexer
    from .indexer._codebase_indexer import CodeIndexPreflight
    from .indexer._document_indexer import DocumentIndexPreflight

    clean = _admit_attempt_mode(context, dispatch)
    if isinstance(indexer, CodebaseIndexer):
        if not isinstance(preflight, CodeIndexPreflight):
            raise RuntimeError("code attempt requires its admitted preflight")
        if clean:
            return partial(
                indexer.full_index,
                clean=clean,
                reporter=reporter,
                preflight=preflight,
                authority=dispatch.authority,
                run_control=context.control,
            )
        return partial(
            indexer.incremental_index,
            reporter=reporter,
            preflight=preflight,
            authority=dispatch.authority,
            run_control=context.control,
        )
    if isinstance(indexer, DocumentIndexer):
        if not isinstance(preflight, DocumentIndexPreflight):
            raise RuntimeError("document attempt requires its admitted preflight")
        if clean:
            return partial(
                indexer.full_index,
                clean=clean,
                reporter=reporter,
                preflight=preflight,
                authority=dispatch.authority,
                run_control=context.control,
            )
        return partial(
            indexer.incremental_index,
            reporter=reporter,
            preflight=preflight,
            authority=dispatch.authority,
            run_control=context.control,
        )
    if clean:
        return partial(
            indexer.full_index,
            clean=clean,
            reporter=reporter,
            authority=dispatch.authority,
            run_control=context.control,
        )
    return partial(
        indexer.incremental_index,
        reporter=reporter,
        authority=dispatch.authority,
        run_control=context.control,
    )


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
    if spec.source is JobSource.VAULT:
        runner = partial(
            _run_vault_attempt,
            dispatch=_AttemptDispatch(
                source=JobSource.VAULT,
                job_id=binding.job_id,
                root=root,
                mode=spec.mode,
                authority=spec.authority,
                registry=binding.registry,
            ),
        )
    else:
        runner = partial(
            _run_indexing_attempt,
            dispatch=_AttemptDispatch(
                source=spec.source,
                job_id=binding.job_id,
                root=root,
                mode=spec.mode,
                authority=spec.authority,
                registry=binding.registry,
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

    _admit_attempt_mode(context, dispatch)
    result: IndexResult | None = None
    try:
        with dispatch.registry.compute_lease(dispatch.root) as lease:
            runtime = lease.runtime
            context.set_resources(ResourceUpdate(project_lease_held=True))
            try:
                context.set_resources(ResourceUpdate(writer_lock_held=True))
                reporter = JobProgressReporter(dispatch.job_id, context=context)
                with _observe_index_resilience(
                    context, runtime.vault_indexer, IndexResilienceSnapshot()
                ):
                    result = _bind_index_attempt(
                        context,
                        dispatch,
                        indexer=runtime.vault_indexer,
                        reporter=reporter,
                    )()
            finally:
                context.set_resources(ResourceUpdate(writer_lock_held=False))
            dispatch.registry.peek_project(dispatch.root).graph_cache.invalidate()
    finally:
        context.set_resources(ResourceUpdate(project_lease_held=False))
    if result is None:
        raise RuntimeError("vault indexing attempt ended without a result")
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
    else - the lease, the resource bookkeeping, the admitted mode, the
    clean/incremental branch, the teardown ordering, and the whole result -
    was the same text twice.

    Merging them matters beyond the repetition. Every attempt resolves its
    runtime through a single ``compute_lease`` and does all of its work inside
    that scope, so the resource bookkeeping is paired with the lease's
    lifetime and the teardown order is fixed in one place. That pairing was
    spelled twice and could have drifted on either copy - a lease released
    while a resource still reads as held is invisible until an operator reads
    the job. One runner means one scope to guard.

    The vault runner is deliberately not folded in. It takes no admission
    preflight, holds no pipeline resource, invalidates the graph cache, and
    returns a result without preprocess fields - it is a different job, not
    this one with different nouns. It does publish resilience, but a different
    shape of it: observed memory peaks and actual checkpoint facts, with no
    admitted ceiling or support profile for the vault domain.
    """
    from ._job_admission import (
        validate_code_job_admission,
        validate_document_job_admission,
    )
    from .jobs import JobProgressReporter

    _admit_attempt_mode(context, dispatch)
    # Held as two narrowed locals rather than one union: each indexer accepts
    # only its own preflight type, and the type checker cannot see that the
    # source picks both together. Narrowing keeps the pairing checkable.
    code_preflight: CodeIndexPreflight | None = None
    document_preflight: DocumentIndexPreflight | None = None
    context.control.checkpoint()
    if dispatch.source is JobSource.CODE:
        code_preflight = validate_code_job_admission(dispatch.root)
    elif dispatch.source is JobSource.DOCUMENT:
        document_preflight = validate_document_job_admission(
            dispatch.root, run_control=context.control
        )
    else:
        # Naming the document arm rather than taking every non-code source
        # keeps the third branch a refusal instead of a silent enrolment: a
        # source with no admission preflight of its own would otherwise be
        # validated, admitted and reported as a document run.
        raise RuntimeError(
            f"indexing attempt cannot run source: {dispatch.source.value}"
        )
    admitted = _admitted_resilience(dispatch.source)
    context.set_resilience(admitted)
    context.control.checkpoint()
    result: IndexResult | None = None
    try:
        with dispatch.registry.compute_lease(dispatch.root) as lease:
            runtime = lease.runtime
            context.set_resources(ResourceUpdate(project_lease_held=True))
            try:
                context.set_resources(
                    ResourceUpdate(writer_lock_held=True, pipeline_active=True)
                )
                reporter = JobProgressReporter(dispatch.job_id, context=context)
                if code_preflight is not None:
                    code_indexer = runtime.code_indexer
                    with _observe_index_resilience(context, code_indexer, admitted):
                        result = _bind_index_attempt(
                            context,
                            dispatch,
                            indexer=code_indexer,
                            reporter=reporter,
                            preflight=code_preflight,
                        )()
                else:
                    document_indexer = runtime.document_indexer
                    with _observe_index_resilience(context, document_indexer, admitted):
                        result = _bind_index_attempt(
                            context,
                            dispatch,
                            indexer=document_indexer,
                            reporter=reporter,
                            preflight=document_preflight,
                        )()
            finally:
                context.set_resources(
                    ResourceUpdate(writer_lock_held=False, pipeline_active=False)
                )
    finally:
        context.set_resources(ResourceUpdate(project_lease_held=False))
    if result is None:
        raise RuntimeError("indexing attempt ended without a result")
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


def _resilience_domain(
    source: Literal[JobSource.CODE, JobSource.DOCUMENT],
) -> IndexDomain:
    """Resolve the domain whose admitted limits describe one source.

    Only code and document have an entry in the support profiles, so every
    other source has no limits to report at all. A two-way fallback would
    hand such a source the document domain's ceilings and profile name and
    say nothing, and the numbers are plausible enough that an operator
    reading them has no way to tell. Worse, code and document currently
    carry identical ceilings in every shipped profile, so a mis-mapping
    between those two is invisible in the snapshot as well - the mapping has
    to be right by construction, because nothing downstream can catch it.

    So the parameter admits only the two mapped sources, which makes the bad
    call a type error at every call site rather than a wrong number at
    runtime, and the residual arm is ``assert_never``, so widening the
    parameter to admit a third source fails the type check here until that
    source is mapped. It is a call, not a bare assertion, so the refusal
    also survives optimised bytecode for anyone who reaches it dynamically.
    """
    from .index_profiles import IndexDomain

    if source is JobSource.CODE:
        return IndexDomain.CODE
    if source is JobSource.DOCUMENT:
        return IndexDomain.DOCUMENT
    assert_never(source)


def _admitted_resilience(
    source: Literal[JobSource.CODE, JobSource.DOCUMENT],
) -> IndexResilienceSnapshot:
    """Freeze the selected profile and domain ceilings before model loading."""
    from .config._settings import get_config
    from .index_profiles import get_index_support_profile

    config = get_config()
    profile = get_index_support_profile(config.index_support_profile)
    limits = profile.limits_for(_resilience_domain(source))
    from .memory_probe import (
        resident_cuda_baseline_mib,
        resolve_index_cuda_ceiling_mib,
    )

    rss_ceiling_mib = bytes_to_mib(limits.rss_bytes)
    rss_ceiling_mib = min(rss_ceiling_mib, config.index_rss_ceiling_mib)
    # Point-in-time diagnostic only: this snapshot is reported and persisted,
    # never enforced, and may legitimately differ from the later per-job
    # enforcing derivation the budget builders compute post-flush.
    cuda_ceiling_mib = resolve_index_cuda_ceiling_mib(
        configured_mib=config.index_cuda_ceiling_mib,
        headroom_mib=config.index_cuda_headroom_mib,
        profile_cuda_mib=bytes_to_mib(limits.cuda_bytes),
        baseline_mib=resident_cuda_baseline_mib(),
    )
    return IndexResilienceSnapshot(
        rss_ceiling_mib=rss_ceiling_mib,
        cuda_ceiling_mib=cuda_ceiling_mib,
        support_profile=profile.name,
    )


def _checkpoint_resilience(
    checkpoint: RunCheckpointBase | None,
    admitted: IndexResilienceSnapshot,
    *,
    peak_rss_mib: float | None,
    peak_cuda_allocated_mib: float | None,
    peak_cuda_reserved_mib: float | None,
) -> IndexResilienceSnapshot:
    """Project one concrete checkpoint without adapter policy recomputation."""
    if checkpoint is None:
        return replace(
            admitted,
            peak_rss_mib=peak_rss_mib,
            peak_cuda_allocated_mib=peak_cuda_allocated_mib,
            peak_cuda_reserved_mib=peak_cuda_reserved_mib,
        )
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
        peak_rss_mib=peak_rss_mib,
        rss_ceiling_mib=admitted.rss_ceiling_mib,
        peak_cuda_allocated_mib=peak_cuda_allocated_mib,
        peak_cuda_reserved_mib=peak_cuda_reserved_mib,
        cuda_ceiling_mib=admitted.cuda_ceiling_mib,
        support_profile=admitted.support_profile,
        terminal_outcome=generation.terminal_state.value,
    )


def _indexer_resilience(
    indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    checkpoint: RunCheckpointBase | None,
    admitted: IndexResilienceSnapshot,
) -> IndexResilienceSnapshot:
    """Project the attempt's exact checkpoint and observed resource peaks."""
    budget = indexer.memory_budget_snapshot
    peak_rss_mib = budget.peak_rss_mib if budget is not None else None
    peak_cuda_reserved_mib = (
        budget.peak_cuda_reserved_mib if budget is not None else None
    )
    return _checkpoint_resilience(
        checkpoint,
        admitted,
        peak_rss_mib=peak_rss_mib,
        peak_cuda_allocated_mib=(
            budget.peak_cuda_allocated_mib if budget is not None else None
        ),
        peak_cuda_reserved_mib=peak_cuda_reserved_mib,
    )


_RESILIENCE_PUBLICATION_SECONDS = 1.0


class _LiveResiliencePublication:
    """Serialize bounded checkpoint reads and publication for one attempt."""

    def __init__(
        self,
        context: JobAttemptContext,
        indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
        admitted: IndexResilienceSnapshot,
    ) -> None:
        self._context: JobAttemptContext | None = context
        self._indexer = indexer
        self._admitted = admitted
        self._checkpoint: RunCheckpointBase | None = None
        self._next_publication_at = 0.0
        self._durable_progress_published = False
        self._lock = threading.Lock()

    def __call__(
        self, checkpoint: RunCheckpointBase, snapshot: RunPolicySnapshot | None
    ) -> None:
        from .indexer._run_policy import DurableProgressKind

        with self._lock:
            context = self._context
            if context is None:
                return
            opened = snapshot is None
            if opened:
                self._checkpoint = checkpoint
                self._durable_progress_published = False
            elif checkpoint is not self._checkpoint:
                return
            now = time.monotonic()
            finalization = (
                snapshot is not None
                and snapshot.last_progress_kind
                is DurableProgressKind.FINALIZATION_PHASE_COMMITTED
            )
            if (
                not opened
                and self._durable_progress_published
                and not finalization
                and now < self._next_publication_at
            ):
                return
            if not opened:
                self._durable_progress_published = True
            self._next_publication_at = now + _RESILIENCE_PUBLICATION_SECONDS
            _publish_resilience(
                context,
                lambda: _indexer_resilience(self._indexer, checkpoint, self._admitted),
            )

    def finish(self) -> None:
        """Retain final projection and detach observation when execution exits."""
        with self._lock:
            context = self._context
            if context is None:
                return
            _publish_resilience(
                context,
                lambda: _indexer_resilience(
                    self._indexer, self._checkpoint, self._admitted
                ),
            )
            if self._checkpoint is not None:
                self._checkpoint.run_policy.set_durable_progress_observer(None)
            self._context = None


@contextmanager
def _observe_index_resilience(
    context: JobAttemptContext,
    indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    admitted: IndexResilienceSnapshot,
) -> Generator[None]:
    """Bind real checkpoint notifications and final facts to this attempt."""
    from .indexer import CodebaseIndexer, DocumentIndexer
    from .indexer._checkpoint_common import observe_checkpoint_progress

    if isinstance(indexer, (CodebaseIndexer, DocumentIndexer)):
        indexer.reset_memory_telemetry()
    publication = _LiveResiliencePublication(context, indexer, admitted)
    with observe_checkpoint_progress(publication):
        try:
            yield
        finally:
            publication.finish()


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
