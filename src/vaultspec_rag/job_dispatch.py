"""Production indexing bindings for canonical manager-owned jobs."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from .job_manager import JobAttemptContext, JobExecutionResult
from .job_models import JobMode, JobOperation, JobOutcome, JobSource

if TYPE_CHECKING:
    from collections.abc import Callable

    from .indexer._codebase_indexer import CodeIndexPreflight
    from .job_manager import JobManager
    from .job_models import JobSnapshot
    from .service import ServiceRegistry


def bind_index_job(
    manager: JobManager,
    job_id: str,
    *,
    registry: ServiceRegistry,
    code_preflight: CodeIndexPreflight | None,
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
    del code_preflight  # Admission authority must never survive until execution.
    snapshot = manager.get(job_id)
    if snapshot is None:
        raise RuntimeError(f"Cannot bind unknown job: {job_id}")
    spec = snapshot.spec
    if (
        spec.operation is not JobOperation.INDEX
        or spec.source not in {JobSource.VAULT, JobSource.CODE}
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
    else:
        runner = partial(
            _run_code_attempt,
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
        )
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
    from .jobs import JobProgressReporter, validate_code_index_policy

    context.control.checkpoint()
    preflight = validate_code_index_policy(root)
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
