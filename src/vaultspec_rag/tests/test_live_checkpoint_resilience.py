"""CPU storage and durable attempt evidence at live checkpoint boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, cast

import pytest

from .._store_models import CodeChunk, DocumentChunk, DocumentPayload
from ..config._settings import get_config
from ..embeddings import EmbeddingModel
from ..index_profiles import IndexDomain, get_index_support_profile
from ..indexer import CodebaseIndexer, DocumentIndexer, VaultIndexer
from ..indexer._checkpoint_common import PublicationExecution
from ..indexer._content_policy import (
    ContentKind,
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._generation_lifecycle import CodeGenerationOpenRequest
from ..indexer._resolved_policy import (
    IndexPolicyResolutionOptions,
    resolve_index_policy,
)
from ..indexer._route_migration import reconcile_origin_after_destination
from ..indexer._run_checkpoint import CodeRunConfiguration
from ..indexer._run_ledger_models import RunAuthority, RunOperation, RunTerminalState
from ..indexer._run_policy import DurableProgressKind
from ..indexer._streaming import execute_store_mutation
from ..indexer._streaming_types import CodeFileSegment
from ..indexer._vault_checkpoint import VaultRunCheckpoint
from ..job_control import RunControlToken
from ..job_dispatch import _observe_index_resilience
from ..job_manager._control import AttemptTerminal
from ..job_manager.manager import JobManager
from ..job_manager.models import JobAttemptContext
from ..job_models import (
    IndexResilienceSnapshot,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ..job_persistence import load_persisted_state
from ..progress import NullProgressReporter
from ..service_quiesce import ServiceQuiesceController
from ..store_runtime import VaultStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..indexer._run_checkpoint import CodeRunCheckpoint
    from ..job_manager.state import AttemptExit

pytestmark = [pytest.mark.unit]


@pytest.fixture
def unloaded_model(clean_config: None) -> EmbeddingModel:
    """Construct the real encoder state without loading or forwarding a model."""
    del clean_config
    config = get_config(
        {"embedding_dimension": 2, "qdrant_url": None, "sparse_enabled": False}
    )
    model = EmbeddingModel.__new__(EmbeddingModel)
    model._init_encode_state(config, device="unloaded")
    return model


@contextmanager
def _running(
    root: Path, source: JobSource = JobSource.CODE
) -> Generator[JobAttemptContext]:
    manager = JobManager(
        state_path=root / "jobs.json",
        quiesce_controller=ServiceQuiesceController(),
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX, source, str(root), JobMode.REBUILD, RunAuthority.REBUILD
        ),
        JobInitiator("test", "live-checkpoint", str(root)),
    )
    assert created.job is not None
    task = asyncio.current_task()
    assert task is not None
    owner = cast("asyncio.Task[AttemptExit]", task)
    control = RunControlToken()
    started = manager.start_attempt(created.job.id, task=owner, control=control)
    assert started.job is not None and started.job.state is JobState.RUNNING
    context = JobAttemptContext(
        manager, created.job.id, 1, owner, control, RunAuthority.REBUILD
    )
    context.update_progress("CPU bounded ingestion", completed=0, total=1)
    context.set_resilience(IndexResilienceSnapshot())
    try:
        yield context
    finally:
        manager.finish_attempt(
            context.job_id,
            AttemptTerminal(1, owner, JobState.SUCCEEDED, "CPU observation complete"),
        )


def _open_code(
    indexer: CodebaseIndexer, context: JobAttemptContext
) -> CodeRunCheckpoint:
    return indexer._lifecycle.open_checkpoint(
        CodeGenerationOpenRequest(
            policy=resolve_index_policy(
                indexer.root_dir,
                IndexPolicyResolutionOptions(
                    content_policy=RootContentPolicy(
                        SourceProfileVersion.CONVENTIONAL_V1
                    )
                ),
            ),
            operation=RunOperation.FULL,
            clean=True,
            configuration=CodeRunConfiguration(
                1, 4096, 2, 8192, 2, 8192, False, 1, 2, 1
            ),
            dense_dimensions=2,
            sparse_enabled=False,
            run_control=context.control,
            authority=context.authority,
        )
    )


def _commit(
    indexer: CodebaseIndexer,
    checkpoint: CodeRunCheckpoint,
    ordinal: int,
    *,
    end: bool = False,
    vector: tuple[float, ...] = (1.0, 0.0),
) -> None:
    path = indexer.root_dir / "module.py"
    digest = hashlib.blake2b(path.read_bytes()).hexdigest()
    chunk = CodeChunk(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path}:{ordinal}")),
        path=path.name,
        language="python",
        content=f"def unit_{ordinal}():\n    return {ordinal}\n",
        line_start=ordinal * 2 + 1,
        line_end=ordinal * 2 + 2,
        vector=list(vector),
    )
    segment = CodeFileSegment(path.name, ordinal, (chunk,), 256, end)
    unit = checkpoint.unit_for(segment, digest)

    def acknowledge() -> None:
        checkpoint.record_confirmed_segments((segment,), {path.name: digest})

    execute_store_mutation(
        partial(
            indexer.store.upsert_code_chunks,
            [chunk],
            collection=indexer._lifecycle.active_build_target,
            write_policy=checkpoint.run_policy.store_write_policy,
        ),
        checkpoint.mutation_lifecycle_for_units((unit,)),
        after_acknowledgement=acknowledge,
    )


def _live(context: JobAttemptContext) -> IndexResilienceSnapshot:
    snapshot = context.manager.get(context.job_id)
    assert snapshot is not None and snapshot.state is JobState.RUNNING
    assert snapshot.progress is not None
    assert snapshot.progress.completed == 0, "durable telemetry changed file counters"
    assert snapshot.resilience is not None
    assert context.manager._state_path is not None
    assert (
        load_persisted_state(context.manager._state_path).jobs[0].resilience
        == snapshot.resilience
    )
    return snapshot.resilience


@pytest.mark.asyncio
async def test_nonfinal_units_publish_before_attempt_exit(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """Real store acknowledgements expose partial-file durability while RUNNING."""
    (tmp_path / "module.py").write_text("def alpha():\n    return 1\n")
    with VaultStore(tmp_path, embedding_dim=2) as store, _running(tmp_path) as context:
        indexer = CodebaseIndexer(tmp_path, unloaded_model, store)
        admitted = IndexResilienceSnapshot(
            rss_ceiling_mib=512.0, support_profile="small"
        )
        context.set_resilience(admitted)
        assert _live(context).generation_id is None
        with (
            indexer._writer_lock,
            _observe_index_resilience(context, indexer, admitted),
        ):
            checkpoint = _open_code(indexer, context)
            opened = _live(context)
            assert opened.generation_id == checkpoint.generation_id
            assert opened.checkpoint_compatible is True
            assert opened.committed_units == 0
            _commit(indexer, checkpoint, 0)
            first = _live(context)
            assert first.committed_units == 1, (
                "first durable unit was not published live"
            )
            assert first.last_durable_progress_at != opened.last_durable_progress_at
            await asyncio.sleep(1.05)
            _commit(indexer, checkpoint, 1)
            second = _live(context)
            assert second.committed_units == 2, (
                "subsequent durable unit was not published live"
            )
            assert second.last_durable_progress_at != first.last_durable_progress_at
            assert not checkpoint.ledger.file_complete(
                checkpoint.generation_id, "module.py"
            )
            assert second.rss_ceiling_mib == admitted.rss_ceiling_mib
            assert second.support_profile == admitted.support_profile


@pytest.mark.asyncio
async def test_burst_coalesces_publications_and_retains_final_facts(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """Rapid durable commits avoid per-unit job fsync and still settle exact facts."""
    (tmp_path / "module.py").write_text("def alpha():\n    return 1\n")
    with VaultStore(tmp_path, embedding_dim=2) as store, _running(tmp_path) as context:
        indexer = CodebaseIndexer(tmp_path, unloaded_model, store)
        with (
            indexer._writer_lock,
            _observe_index_resilience(context, indexer, IndexResilienceSnapshot()),
        ):
            checkpoint = _open_code(indexer, context)
            _commit(indexer, checkpoint, 0)
            published = _live(context)
            persisted = (tmp_path / "jobs.json").read_bytes()
            _commit(indexer, checkpoint, 1)
            assert checkpoint.ledger.committed_unit_count(checkpoint.generation_id) == 2
            assert _live(context) == published, (
                "burst performed another job publication"
            )
            assert (tmp_path / "jobs.json").read_bytes() == persisted
        assert _live(context).committed_units == 2, (
            "exit lost coalesced durable evidence"
        )
        settled = _live(context)
        await asyncio.sleep(1.05)
        _commit(indexer, checkpoint, 2)
        assert _live(context) == settled, "closed attempt observer still published"


@pytest.mark.asyncio
async def test_failed_store_and_ledger_do_not_publish_progress(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """Actual conformance and SQLite failures cannot be credited as durability."""
    (tmp_path / "module.py").write_text("def alpha():\n    return 1\n")
    with VaultStore(tmp_path, embedding_dim=2) as store, _running(tmp_path) as context:
        indexer = CodebaseIndexer(tmp_path, unloaded_model, store)
        with (
            indexer._writer_lock,
            _observe_index_resilience(context, indexer, IndexResilienceSnapshot()),
        ):
            checkpoint = _open_code(indexer, context)
            _commit(indexer, checkpoint, 0)
            baseline = _live(context)
            clock = checkpoint.run_policy.snapshot().last_durable_progress_at
            await asyncio.sleep(1.05)
            with pytest.raises(ValueError):
                _commit(indexer, checkpoint, 1, vector=(1.0, 0.0, 0.0))
            assert (
                checkpoint.ledger.committed_unit_count(checkpoint.generation_id) == 1
            ), "failed store gained a ledger unit"
            assert _live(context) == baseline, "failed store was published as progress"
            # Only isolated temporary ledger storage is removed. The next real
            # acknowledged Qdrant write encounters an actual SQLite open failure.
            checkpoint.ledger.path.unlink()
            checkpoint.ledger.path.mkdir()
            with pytest.raises(sqlite3.OperationalError):
                _commit(indexer, checkpoint, 1)
            assert checkpoint.run_policy.snapshot().last_durable_progress_at == clock, (
                "failed ledger renewed durable clock"
            )
            assert _live(context) == baseline, "failed ledger was published as progress"


@pytest.mark.asyncio
async def test_stale_task_cannot_publish_a_different_checkpoint(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """A real foreign task cannot replace the manager's exact attempt owner."""
    (tmp_path / "module.py").write_text("def alpha():\n    return 1\n")
    with VaultStore(tmp_path, embedding_dim=2) as store, _running(tmp_path) as context:
        indexer = CodebaseIndexer(tmp_path, unloaded_model, store)
        baseline = _live(context)

        async def foreign() -> None:
            task = asyncio.current_task()
            assert task is not None
            stale = replace(context, task=cast("asyncio.Task[AttemptExit]", task))
            with (
                indexer._writer_lock,
                _observe_index_resilience(stale, indexer, IndexResilienceSnapshot()),
            ):
                checkpoint = _open_code(indexer, stale)
                _commit(indexer, checkpoint, 0)
                assert (
                    checkpoint.ledger.committed_unit_count(checkpoint.generation_id)
                    == 1
                )

        await asyncio.create_task(foreign())
        assert _live(context) == baseline, (
            "stale task replaced current attempt evidence"
        )


@pytest.mark.asyncio
async def test_reconciliation_and_finalization_publish_actual_boundaries(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """Actual origin deletion and generation publication update a running job."""
    (tmp_path / "module.py").write_text("def alpha():\n    return 1\n")
    with VaultStore(tmp_path, embedding_dim=2) as store, _running(tmp_path) as context:
        store.upsert_document_content_chunks(
            [
                DocumentChunk(
                    str(uuid.uuid4()),
                    DocumentPayload("module.py", 0, "old", "prior document"),
                    vector=[1.0, 0.0],
                )
            ],
            write_policy=None,
        )
        indexer = CodebaseIndexer(tmp_path, unloaded_model, store)
        with (
            indexer._writer_lock,
            _observe_index_resilience(context, indexer, IndexResilienceSnapshot()),
        ):
            checkpoint = _open_code(indexer, context)
            _commit(indexer, checkpoint, 0, end=True)
            before = _live(context)
            # Reconciliation looks up the concrete destination collection.
            target = indexer._lifecycle.active_build_target
            assert target is not None
            store.CODE_TABLE_NAME = target
            await asyncio.sleep(1.05)
            assert (
                reconcile_origin_after_destination(
                    store, checkpoint, ContentKind.CODE, "module.py"
                )
                == 1
            )
            reconciled = _live(context)
            assert reconciled.committed_units == 1
            assert (
                reconciled.last_durable_progress_at != before.last_durable_progress_at
            )
            assert (
                checkpoint.run_policy.snapshot().last_progress_kind
                is DurableProgressKind.RECONCILIATION_BATCH_COMMITTED
            )
            indexer._lifecycle.publish(
                checkpoint,
                build_target=target,
                reporter=NullProgressReporter(),
                phase_label="CPU publication",
            )
            assert (
                checkpoint.ledger.generation(checkpoint.generation_id).terminal_state
                is RunTerminalState.SUCCEEDED
            )
            assert _live(context).terminal_outcome == "succeeded", (
                "finalization remained unpublished"
            )


@pytest.mark.parametrize(
    "source", [JobSource.CODE, JobSource.DOCUMENT, JobSource.VAULT]
)
@pytest.mark.asyncio
async def test_each_source_registers_its_actual_checkpoint(
    tmp_path: Path, unloaded_model: EmbeddingModel, source: JobSource
) -> None:
    """Vault exposes actual ledger facts without another domain's profile."""
    with (
        VaultStore(tmp_path, embedding_dim=2) as store,
        _running(tmp_path, source) as context,
    ):
        if source is JobSource.CODE:
            indexer = CodebaseIndexer(tmp_path, unloaded_model, store)
        elif source is JobSource.DOCUMENT:
            indexer = DocumentIndexer(tmp_path, unloaded_model, store)
        else:
            indexer = VaultIndexer(tmp_path, unloaded_model, store)
        with _observe_index_resilience(context, indexer, IndexResilienceSnapshot()):
            if isinstance(indexer, CodebaseIndexer):
                checkpoint = _open_code(indexer, context)
            elif isinstance(indexer, DocumentIndexer):
                checkpoint = indexer._open_checkpoint(
                    policy=resolve_index_policy(
                        tmp_path,
                        IndexPolicyResolutionOptions(
                            content_policy=RootContentPolicy(
                                SourceProfileVersion.CONVENTIONAL_V1
                            )
                        ),
                    ),
                    operation=RunOperation.FULL,
                    clean=True,
                    limits=get_index_support_profile(
                        get_config().index_support_profile
                    ).limits_for(IndexDomain.DOCUMENT),
                    execution=PublicationExecution(context.authority, context.control),
                )
            else:
                checkpoint = VaultRunCheckpoint.open(
                    tmp_path,
                    backend_identity=store.backend_identity,
                    authority=context.authority,
                    operation=RunOperation.FULL,
                    run_control=context.control,
                )
            live = _live(context)
            assert live.generation_id == checkpoint.generation_id, (
                "actual source checkpoint was omitted"
            )
            assert live.checkpoint_compatible is True
            assert live.committed_units == 0
            assert (
                live.no_progress_timeout_seconds
                == checkpoint.run_policy.snapshot().timeout_seconds
            )
            assert live.rss_ceiling_mib is None
            assert live.cuda_ceiling_mib is None
            assert live.support_profile is None


def test_durable_observer_can_read_policy_without_lock_reentry() -> None:
    """Observer execution follows unlocking so it can safely project the clock."""
    from ..indexer._run_policy import RunPolicy

    policy = RunPolicy(no_progress_timeout_seconds=30.0)
    observed: list[float] = []
    policy.set_durable_progress_observer(
        lambda _snapshot: observed.append(policy.snapshot().last_durable_progress_at)
    )
    thread = threading.Thread(
        target=partial(
            policy.record_durable_progress,
            kind=DurableProgressKind.LEDGER_UNIT_COMMITTED,
            label="policy observer unit",
        ),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=1.0)
    assert not thread.is_alive(), "observer held the run-policy lock"
    assert observed == [policy.snapshot().last_durable_progress_at]


def test_observer_failure_does_not_mask_durable_progress() -> None:
    """An observability failure cannot turn a confirmed boundary into failure."""
    from ..indexer._run_policy import RunPolicy

    policy = RunPolicy(no_progress_timeout_seconds=30.0)

    def fail(_snapshot: object) -> None:
        raise OSError("observer persistence unavailable")

    policy.set_durable_progress_observer(fail)
    before = policy.snapshot().last_durable_progress_at
    time.sleep(0.002)
    failure: OSError | None = None
    try:
        policy.record_durable_progress(
            kind=DurableProgressKind.LEDGER_UNIT_COMMITTED, label="policy observer unit"
        )
    except OSError as exc:
        failure = exc
    assert failure is None, "observer failure escaped a durable boundary"
    assert policy.snapshot().last_durable_progress_at > before
