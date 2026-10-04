"""Managed watcher completion with real CPU checkpoints and registry leases."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from .. import job_dispatch
from ..config._settings import get_config
from ..embeddings import EmbeddingModel
from ..indexer import CodebaseIndexer, DocumentIndexer
from ..indexer._content_policy import (
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._run_ledger_models import RunAuthority
from ..job_control import CancelRequested, RunControlToken
from ..job_manager._control import AttemptTerminal
from ..job_manager.models import JobAttemptContext
from ..job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ..progress import NullProgressReporter
from ..service import ServiceRegistry
from ..watcher_execution import _run_managed_index_attempt
from ..watcher_retry import (
    WatcherPathEvent,
    WatcherPathObservation,
    WatcherSource,
)
from ..watcher_retry_policy import WatcherRetryPolicy
from ..watcher_runtime import ManagedAttemptInputs, WatcherConvergenceSlot

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from .._service_types import ProjectComputeRuntime
    from ..job_manager.state import AttemptExit

pytestmark = [pytest.mark.unit]


@dataclass(frozen=True)
class _Project:
    root: Path
    registry: ServiceRegistry
    runtime: ProjectComputeRuntime


@pytest.fixture
def project(
    tmp_path: Path, clean_config: None, monkeypatch: pytest.MonkeyPatch
) -> Generator[_Project]:
    """Keep real model state; substitute only the external encoder forward."""
    del clean_config
    cfg = get_config(
        {
            "embedding_dimension": 2,
            "qdrant_url": None,
            "sparse_enabled": False,
            "reranker_enabled": False,
            # A few-file corpus on a local store: the service profile's RAM
            # floor would refuse it on any host smaller than a workstation.
            "index_support_profile": "embedded-local",
        }
    )
    model = EmbeddingModel.__new__(EmbeddingModel)
    # No weights are loaded here, so there is no device to name.
    model._device = "unloaded"
    model._init_encode_state(cfg)

    def encode(texts: list[str], **_options: object) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(model, "encode_documents_on_device", encode)
    registry = ServiceRegistry()
    registry._model = model
    policy = RootContentPolicy(
        SourceProfileVersion.CONVENTIONAL_V1,
        (ContentRoute("guide.txt", ContentKind.DOCUMENT),),
    )
    (tmp_path / "module.py").write_text("def alpha():\n    return 1\n")
    (tmp_path / "guide.txt").write_text("First CPU document content.\n")
    vault = tmp_path / ".vault" / "adr"
    vault.mkdir(parents=True)
    (vault / "notes.md").write_text(
        "---\ntype: adr\nfeature: watcher\ndate: 2026-10-03\n"
        "tags: []\nrelated: []\n---\n# CPU notes\nFirst durable vault content.\n"
    )
    with registry.compute_lease(tmp_path) as lease:
        runtime = lease.runtime
        runtime.code_indexer = CodebaseIndexer(
            tmp_path,
            model,
            runtime.code_indexer.store,
            options=CodebaseIndexer.Options(content_policy=policy),
        )
        runtime.document_indexer = DocumentIndexer(
            tmp_path, model, runtime.code_indexer.store, content_policy=policy
        )
        yield _Project(tmp_path, registry, runtime)
    registry.close_project(tmp_path)


def _seed(project: _Project, source: JobSource) -> Path:
    reporter = NullProgressReporter()
    runtime = project.runtime
    if source is JobSource.CODE:
        runtime.code_indexer.full_index(
            clean=True,
            reporter=reporter,
            preflight=runtime.code_indexer.preflight_content(),
        )
        path = project.root / "module.py"
        path.write_text("def alpha():\n    return 2\n")
    elif source is JobSource.DOCUMENT:
        runtime.document_indexer.full_index(clean=True, reporter=reporter)
        path = project.root / "guide.txt"
        path.write_text("Changed CPU document content.\n")
    else:
        runtime.vault_indexer.full_index(clean=True, reporter=reporter)
        path = project.root / ".vault" / "adr" / "notes.md"
        path.write_text(path.read_text().replace("First durable", "Changed durable"))
    return path


@contextmanager
def _attempt(
    project: _Project, source: JobSource, path: Path
) -> Generator[tuple[WatcherConvergenceSlot, JobAttemptContext]]:
    manager = project.registry.create_job_manager()
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            source,
            str(project.root),
            JobMode.INCREMENTAL,
            RunAuthority.PUBLICATION,
        ),
        JobInitiator("watcher", "CPU watcher", str(project.root)),
    )
    assert created.job is not None
    task = asyncio.current_task()
    assert task is not None
    owner = cast("asyncio.Task[AttemptExit]", task)
    control = RunControlToken()
    assert manager.start_attempt(created.job.id, task=owner, control=control).job
    context = JobAttemptContext(
        manager, created.job.id, 1, owner, control, RunAuthority.PUBLICATION
    )
    retry = WatcherRetryPolicy.for_root(project.root, WatcherSource(source.value))
    retry.mark_scope_pending(
        (
            WatcherPathObservation(
                path.relative_to(project.root).as_posix(),
                WatcherSource(source.value),
                1.0,
                1.0,
                frozenset({WatcherPathEvent.MODIFIED}),
                1,
            ),
        ),
        now=1.0,
    )
    # A real prior failure leaves backoff evidence to merge with the checkpoint.
    first = retry.admit(now=1.0)
    assert first.admitted and first.attempt_generation is not None
    retry.record_failure(OSError("CPU transient"), first.attempt_generation, now=2.0)
    admitted = retry.admit(now=retry.state.next_retry_at)
    assert admitted.admitted and admitted.attempt_generation is not None
    slot = WatcherConvergenceSlot(source, project.root, project.registry, retry)
    slot.capture_prevalidated_attempt(1, frozenset({path}))
    slot.retry_attempt_generations[1] = admitted.attempt_generation
    completed = False
    try:
        yield slot, context
        completed = True
    finally:
        retry.record_interrupted(admitted.attempt_generation)
        manager.finish_attempt(
            context.job_id,
            AttemptTerminal(
                1,
                owner,
                JobState.SUCCEEDED if completed else JobState.FAILED,
                "CPU watcher completed" if completed else "CPU watcher failed",
            ),
        )


def _inputs(project: _Project, source: JobSource, path: Path) -> ManagedAttemptInputs:
    paths = frozenset({path})
    return ManagedAttemptInputs(
        initial_attempt=1,
        initial_paths=paths,
        code_preflight=(
            project.runtime.code_indexer.preflight_changed_paths(paths)
            if source is JobSource.CODE
            else None
        ),
        document_preflight=(
            project.runtime.document_indexer.preflight_changed_paths(paths)
            if source is JobSource.DOCUMENT
            else None
        ),
    )


@pytest.mark.parametrize("source", [JobSource.CODE, JobSource.DOCUMENT])
async def test_managed_watcher_completes_with_actual_checkpoint(
    project: _Project, source: JobSource
) -> None:
    path = _seed(project, source)
    with _attempt(project, source, path) as (slot, context):
        try:
            result = _run_managed_index_attempt(
                slot, context, _inputs(project, source, path)
            )
        except ImportError as exc:
            raise AssertionError(
                f"managed watcher completion imported a removed projector: {exc}"
            ) from exc
        removed = 1 if source is JobSource.DOCUMENT else 0
        assert result.summary.startswith(f"+0 /1 -{removed}"), (
            "watcher indexing outcome changed"
        )
        indexer = (
            project.runtime.code_indexer
            if source is JobSource.CODE
            else project.runtime.document_indexer
        )
        checkpoint = indexer.last_checkpoint
        assert checkpoint is not None
        snapshot = context.manager.get(context.job_id)
        assert snapshot is not None and snapshot.resilience is not None
        fact = snapshot.resilience
        assert fact.generation_id == checkpoint.generation_id, (
            "actual checkpoint missing"
        )
        assert fact.committed_units == checkpoint.ledger.committed_unit_count(
            checkpoint.generation_id
        )
        assert fact.committed_units > 0, "real durable units missing"
        assert fact.terminal_outcome == "succeeded", "successful checkpoint missing"
        assert fact.peak_rss_mib is not None and fact.peak_rss_mib > 0
        assert fact.circuit_state == slot.retry_policy.state.circuit_state.value
        assert fact.next_retry_at == slot.retry_policy.state.next_retry_at, (
            "retry backoff lost"
        )
        assert not snapshot.resources.writer_lock_held
        assert not snapshot.resources.pipeline_active
        assert not snapshot.resources.project_lease_held
    finished = context.manager.get(context.job_id)
    assert finished is not None and finished.state is JobState.SUCCEEDED
    assert finished.resilience == fact


async def test_vault_watcher_does_not_import_code_document_projectors(
    project: _Project,
) -> None:
    path = _seed(project, JobSource.VAULT)
    with _attempt(project, JobSource.VAULT, path) as (slot, context):
        try:
            result = _run_managed_index_attempt(
                slot, context, _inputs(project, JobSource.VAULT, path)
            )
        except ImportError as exc:
            raise AssertionError(
                f"VAULT completion imported a removed projector: {exc}"
            ) from exc
        assert result.summary.startswith("+0 /1 -0"), "VAULT watcher outcome changed"
        snapshot = context.manager.get(context.job_id)
        assert snapshot is not None and snapshot.resilience is not None
        assert snapshot.resilience.generation_id is None
        assert (
            snapshot.resilience.next_retry_at == slot.retry_policy.state.next_retry_at
        )


@pytest.mark.parametrize("source", [JobSource.CODE, JobSource.DOCUMENT])
async def test_checkpoint_projection_failure_preserves_watcher_outcome(
    project: _Project, source: JobSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _seed(project, source)

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("CPU projection unavailable")

    monkeypatch.setattr(job_dispatch, "_indexer_resilience", unavailable)
    with _attempt(project, source, path) as (slot, context):
        try:
            result = _run_managed_index_attempt(
                slot, context, _inputs(project, source, path)
            )
        except RuntimeError as exc:
            raise AssertionError(
                f"checkpoint telemetry changed successful watcher outcome: {exc}"
            ) from exc
        removed = 1 if source is JobSource.DOCUMENT else 0
        assert result.summary.startswith(f"+0 /1 -{removed}")
        snapshot = context.manager.get(context.job_id)
        assert snapshot is not None and snapshot.resilience is not None
        assert snapshot.resilience.generation_id is None


async def test_unchanged_watcher_does_not_inherit_previous_checkpoint(
    project: _Project,
) -> None:
    path = _seed(project, JobSource.CODE)
    path.write_text("def alpha():\n    return 1\n")
    previous = project.runtime.code_indexer.last_checkpoint
    assert (
        previous is not None
        and previous.ledger.committed_unit_count(previous.generation_id) > 0
    )
    with _attempt(project, JobSource.CODE, path) as (slot, context):
        result = _run_managed_index_attempt(
            slot, context, _inputs(project, JobSource.CODE, path)
        )
        assert result.summary.startswith("+0 /0 -0")
        assert project.runtime.code_indexer.last_checkpoint is previous
        snapshot = context.manager.get(context.job_id)
        assert snapshot is not None and snapshot.resilience is not None
        fact = snapshot.resilience
        assert fact.generation_id is None, "unchanged attempt inherited old checkpoint"
        assert fact.committed_units == 0
        assert fact.terminal_outcome is None
        assert fact.peak_rss_mib is None
        assert fact.support_profile is not None and fact.rss_ceiling_mib is not None
        assert fact.next_retry_at == slot.retry_policy.state.next_retry_at


async def test_pre_checkpoint_cancellation_keeps_original_outcome(
    project: _Project,
) -> None:
    path = _seed(project, JobSource.CODE)
    previous = project.runtime.code_indexer.last_checkpoint
    assert previous is not None
    with _attempt(project, JobSource.CODE, path) as (slot, context):
        context.control.request_cancel()
        with pytest.raises(CancelRequested):
            _run_managed_index_attempt(
                slot, context, _inputs(project, JobSource.CODE, path)
            )
        assert project.runtime.code_indexer.last_checkpoint is previous
        snapshot = context.manager.get(context.job_id)
        assert snapshot is not None and snapshot.resilience is not None
        assert snapshot.resilience.generation_id is None, (
            "pre-checkpoint failure inherited old checkpoint"
        )
        assert snapshot.resilience.committed_units == 0
        assert snapshot.resilience.terminal_outcome is None
        assert snapshot.resilience.peak_rss_mib is None
        assert (
            snapshot.resilience.next_retry_at == slot.retry_policy.state.next_retry_at
        )
        assert not snapshot.resources.writer_lock_held
        assert not snapshot.resources.pipeline_active
        assert not snapshot.resources.project_lease_held
