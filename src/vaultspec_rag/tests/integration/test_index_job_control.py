"""Real-behavior integration coverage for cooperative indexing control.

The tests use the production streaming and indexing paths with local Qdrant,
real vault and code files, and a CPU-backed SentenceTransformer model. Keeping
the model tiny makes the control races deterministic without substituting test
implementations for any production indexing behavior.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sentence_transformers.sentence_transformer import SentenceTransformer
from sentence_transformers.sentence_transformer.modules import BoW

from ... import jobs
from ...concurrency import limiter_stats, reset_limiters
from ...config import get_config, reset_config
from ...embeddings import EmbeddingModel, QueryEmbeddingCache
from ...indexer import CodebaseIndexer, VaultIndexer
from ...indexer._streaming import _stream_encode_and_upsert_vault
from ...indexer._vault_prep import prepare_document
from ...job_control import (
    CancelRequested,
    ControlRequest,
    PauseRequested,
    RunControlSignal,
    RunControlToken,
)
from ...job_models import (
    DesiredJobState,
    JobOutcomeStatus,
    JobSnapshot,
    JobState,
    ResumeStrategy,
)
from ...progress import NullProgressReporter
from ...registry import get_registry, reset_registry
from ...store import VaultStore

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator

    from _pytest.tmpdir import TempPathFactory

    from ...job_manager import JobManager
    from ...service import ProjectSlot, ServiceRegistry
    from ...store import VaultDocument

pytestmark = pytest.mark.integration

_CONTROL_WAIT_SECONDS = 20.0
_MANAGED_WAIT_SECONDS = 60.0
_CONTROL_POLL_SECONDS = 0.001


def _managed_test_config(*, status_dir: Path | None = None) -> dict[str, object]:
    overrides: dict[str, object] = {
        "data_dir": ".managed-index-control",
        "qdrant_url": None,
        "qdrant_server": False,
        "local_only": True,
        "index_support_profile": "embedded-local",
        "sparse_enabled": False,
        "reranker_enabled": False,
        "embedding_batch_size": 8,
        "embedding_encode_batch_size": 1,
        "embedding_code_encode_batch_size": 1,
        "index_chunk_workers": 2,
        "index_parallel_min_bytes": 1,
        "index_job_concurrency": 1,
        "job_shutdown_timeout_seconds": _MANAGED_WAIT_SECONDS,
    }
    if status_dir is not None:
        overrides["status_dir"] = str(status_dir)
    return overrides


@pytest.fixture
def cpu_embedding_model(clean_config: None) -> EmbeddingModel:
    """Build a real production embedding path around a tiny CPU BoW model."""
    del clean_config
    vocabulary = [
        "alpha",
        "beta",
        "gamma",
        "delta",
        "index",
        "control",
        "document",
        "content",
    ]
    backend = SentenceTransformer(modules=[BoW(vocabulary)], device="cpu")
    dimension = backend.get_embedding_dimension()
    assert dimension is not None
    get_config(
        {
            "data_dir": ".index-control",
            "embedding_batch_size": 1,
            "embedding_dimension": dimension,
            "embedding_encode_batch_size": 1,
            "index_chunk_workers": 2,
            # Force more than one durable weighted slice so pause/cancel can
            # be observed between production publication checkpoints. The
            # batch-size setting intentionally does not cap segment capacity.
            "index_segment_max_chunks": 8,
            "index_queue_max_chunks": 16,
            "qdrant_url": None,
            "sparse_enabled": False,
            "vault_chunk_chars": 10_000,
        }
    )

    model = EmbeddingModel.__new__(EmbeddingModel)
    model._dense_model = backend
    model._device = "cpu"
    model.dimension = dimension
    model.query_cache = QueryEmbeddingCache()
    return model


def _write_vault_documents(root: Path, count: int) -> list[VaultDocument]:
    """Create and parse a small real vault corpus through production code."""
    adr_dir = root / ".vault" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    documents: list[VaultDocument] = []
    for ordinal in range(count):
        path = adr_dir / f"control-{ordinal:03d}.md"
        path.write_text(
            "---\n"
            "tags: ['#adr', '#index-control']\n"
            "---\n"
            f"# Control document {ordinal}\n\n"
            f"alpha beta gamma index control document content {ordinal}\n",
            encoding="utf-8",
        )
        document = prepare_document(path, root)
        assert document is not None
        documents.append(document)
    return documents


def _request_after_first_upsert(
    store: VaultStore,
    token: RunControlToken,
    control_request: ControlRequest,
) -> None:
    """Request control only after production storage publishes one slice."""
    deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
    while time.monotonic() < deadline:
        if store.count() > 0:
            if control_request is ControlRequest.PAUSE:
                assert token.request_pause()
            else:
                assert token.request_cancel()
            return
        time.sleep(_CONTROL_POLL_SECONDS)
    raise AssertionError("streaming never published a slice before the deadline")


def _write_code_files(root: Path, count: int, revision: str) -> list[Path]:
    """Create a real Python corpus with unique content markers."""
    source_dir = root / "src"
    source_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for ordinal in range(count):
        path = source_dir / f"control_{ordinal:03d}.py"
        path.write_text(
            f"def control_{ordinal:03d}() -> str:\n"
            f'    """alpha beta index control {revision}-{ordinal:03d}."""\n'
            f'    return "{revision}-{ordinal:03d}"\n',
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def _request_after_first_code_upsert(
    store: VaultStore,
    token: RunControlToken,
    control_request: ControlRequest,
) -> None:
    """Request control after the real code consumer publishes its first slice."""
    deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
    while time.monotonic() < deadline:
        if store.count_code() > 0:
            accepted = (
                token.request_pause()
                if control_request is ControlRequest.PAUSE
                else token.request_cancel()
            )
            assert accepted
            return
        time.sleep(_CONTROL_POLL_SECONDS)
    raise AssertionError("code pipeline never published a slice before the deadline")


def _code_consumer_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "codebase-indexer-consumer"
    ]


def _assert_code_resources_released() -> None:
    """Require all process-pool and sole-consumer resources to be gone."""
    deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
    while time.monotonic() < deadline:
        if not _code_consumer_threads() and not multiprocessing.active_children():
            return
        time.sleep(_CONTROL_POLL_SECONDS)
    assert not _code_consumer_threads()
    assert not multiprocessing.active_children()


async def _wait_for_managed_job(
    manager: JobManager,
    job_id: str,
    predicate: Callable[[JobSnapshot], bool],
    description: str,
) -> JobSnapshot:
    """Poll one exact production job until an observable condition holds."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _MANAGED_WAIT_SECONDS
    while loop.time() < deadline:
        snapshot = manager.get(job_id)
        if snapshot is not None and predicate(snapshot):
            return snapshot
        await asyncio.sleep(_CONTROL_POLL_SECONDS)
    snapshot = manager.get(job_id)
    raise AssertionError(f"{description} before deadline; last snapshot={snapshot!r}")


def _attempt_task(job_id: str, attempt: int) -> asyncio.Task[object] | None:
    """Return the live manager-owned task for one exact attempt name."""
    expected_name = f"vaultspec-job-{job_id}-attempt-{attempt}"
    for task in asyncio.all_tasks():
        if task.get_name() == expected_name:
            return task
    return None


def _assert_manager_resources_released(
    snapshot: JobSnapshot,
    slot: ProjectSlot,
    *,
    code: bool,
) -> None:
    """Combine canonical ownership fields with physical release evidence."""
    assert snapshot.runtime.task_active is False
    assert snapshot.runtime.worker_active is False
    assert snapshot.resources.started is not None
    assert snapshot.resources.finished is not None
    assert snapshot.resources.index_capacity_held is False
    assert snapshot.resources.project_lease_held is False
    assert snapshot.resources.writer_lock_held is False
    assert snapshot.resources.pipeline_active is False
    for pool in ("index", "encode"):
        capacity = limiter_stats()[pool]
        assert capacity["borrowed_tokens"] == 0
        assert capacity["waiting"] == 0
    assert slot.ref_count == 0
    indexer = slot.code_indexer if code else slot.vault_indexer
    assert indexer._writer_lock.acquire(blocking=False)  # pyright: ignore[reportPrivateUsage]
    indexer._writer_lock.release()  # pyright: ignore[reportPrivateUsage]
    if code:
        _assert_code_resources_released()


def _vault_attempt_published(snapshot: JobSnapshot, *, slot: ProjectSlot) -> bool:
    return (
        snapshot.state is JobState.RUNNING
        and snapshot.runtime.task_active
        and snapshot.runtime.worker_active
        and snapshot.resources.index_capacity_held
        and snapshot.resources.project_lease_held
        and snapshot.resources.writer_lock_held
        and slot.store.count() > 0
    )


def _code_pipeline_published(snapshot: JobSnapshot, *, slot: ProjectSlot) -> bool:
    return (
        snapshot.state is JobState.RUNNING
        and snapshot.resources.pipeline_active
        and slot.store.count_code() > 0
    )


def _attempt_is_active(snapshot: JobSnapshot, *, attempt: int) -> bool:
    return snapshot.attempt.number == attempt and snapshot.runtime.task_active


def _code_attempt_reached_embedding_boundary(snapshot: JobSnapshot) -> bool:
    progress = snapshot.progress
    return (
        progress is not None
        and progress.step == "chunk + embed"
        and snapshot.resources.pipeline_active
    )


def _assert_reconciliation_lineage(snapshot: JobSnapshot, job_id: str) -> None:
    assert snapshot.id == job_id
    assert snapshot.attempt.number == 2
    assert snapshot.attempt.resumed_from_attempt == 1
    assert snapshot.attempt.resume_strategy is ResumeStrategy.RECONCILE


async def _pause_managed_attempt(
    manager: JobManager,
    job_id: str,
) -> tuple[asyncio.Task[object], JobSnapshot]:
    first_task = _attempt_task(job_id, 1)
    assert first_task is not None
    pause = manager.set_desired_state(job_id, DesiredJobState.PAUSED)
    assert pause.status is JobOutcomeStatus.ACCEPTED
    assert pause.job is not None
    assert pause.job.state is JobState.PAUSING
    joined = await manager.wait_for_attempt(
        job_id,
        timeout_seconds=_MANAGED_WAIT_SECONDS,
    )
    assert joined.code == "attempt_released"
    paused = manager.get(job_id)
    assert paused is not None
    assert paused.id == job_id
    assert paused.state is JobState.PAUSED
    assert paused.attempt.number == 1
    assert paused.timestamps.control_requested_at is not None
    assert paused.timestamps.control_acknowledged_at is not None
    assert (
        paused.timestamps.control_acknowledged_at
        >= paused.timestamps.control_requested_at
    )
    assert first_task.done()
    assert _attempt_task(job_id, 1) is None
    return first_task, paused


async def _resume_managed_attempt(
    manager: JobManager,
    job_id: str,
    first_task: asyncio.Task[object],
    description: str,
) -> JobSnapshot:
    resume = manager.set_desired_state(job_id, DesiredJobState.RUNNING)
    assert resume.status is JobOutcomeStatus.ACCEPTED
    resumed = await _wait_for_managed_job(
        manager,
        job_id,
        partial(_attempt_is_active, attempt=2),
        description,
    )
    second_task = _attempt_task(job_id, 2)
    assert second_task is not None
    assert second_task is not first_task
    _assert_reconciliation_lineage(resumed, job_id)

    completed = await manager.wait_for_attempt(
        job_id,
        timeout_seconds=_MANAGED_WAIT_SECONDS,
    )
    assert completed.code == "attempt_released"
    succeeded = manager.get(job_id)
    assert succeeded is not None
    assert succeeded.state is JobState.SUCCEEDED
    _assert_reconciliation_lineage(succeeded, job_id)
    return succeeded


async def _cancel_managed_attempt(
    manager: JobManager,
    job_id: str,
) -> JobSnapshot:
    cancel = manager.set_desired_state(job_id, DesiredJobState.CANCELLED)
    assert cancel.status is JobOutcomeStatus.ACCEPTED
    assert cancel.job is not None
    assert cancel.job.state is JobState.CANCELLING
    joined = await manager.wait_for_attempt(
        job_id,
        timeout_seconds=_MANAGED_WAIT_SECONDS,
    )
    assert joined.code == "attempt_released"
    cancelled = manager.get(job_id)
    assert cancelled is not None
    assert cancelled.state is JobState.CANCELLED
    assert cancelled.timestamps.control_requested_at is not None
    assert cancelled.timestamps.control_acknowledged_at is not None
    return cancelled


async def _assert_cancelled_vault_stops_writes(
    manager: JobManager,
    job_id: str,
    cancelled: JobSnapshot,
    slot: ProjectSlot,
    root: Path,
) -> None:
    metadata_path = root / get_config().data_dir / get_config().index_metadata_file
    metadata = metadata_path.read_bytes() if metadata_path.exists() else None
    metadata_mtime = (
        metadata_path.stat().st_mtime_ns if metadata_path.exists() else None
    )
    point_ids = slot.store.get_all_ids()
    point_count = slot.store.count()
    payloads = {point_id: slot.store.get_by_id(point_id) for point_id in point_ids}
    await asyncio.sleep(0.25)

    assert manager.get(job_id) == cancelled
    assert slot.store.get_all_ids() == point_ids
    assert slot.store.count() == point_count
    current_payloads = {
        point_id: slot.store.get_by_id(point_id) for point_id in point_ids
    }
    assert current_payloads == payloads
    current_metadata = metadata_path.read_bytes() if metadata_path.exists() else None
    assert current_metadata == metadata
    current_mtime = metadata_path.stat().st_mtime_ns if metadata_path.exists() else None
    assert current_mtime == metadata_mtime


def _assert_cancelled_job_is_absorbing(manager: JobManager, job_id: str) -> None:
    replay = manager.set_desired_state(job_id, DesiredJobState.CANCELLED)
    assert replay.status is JobOutcomeStatus.OK
    assert replay.code == "already_satisfied"
    rejected = manager.set_desired_state(job_id, DesiredJobState.RUNNING)
    assert rejected.status is JobOutcomeStatus.ERROR
    assert rejected.code == "invalid_transition"


def _prepare_dimension_failure(
    registry: ServiceRegistry,
    root: Path,
    *,
    file_count: int,
) -> ProjectSlot:
    registry.close_project(root)
    with VaultStore(
        root, embedding_dim=registry.model.dimension + 1
    ) as mismatched_store:
        mismatched_store.drop_code_table()
        mismatched_store.ensure_code_table()
    _write_code_files(root, file_count, "dimension-failure")
    return registry.peek_project(root)


async def _request_cancel_at_the_write_gate(
    manager: JobManager,
    registry: ServiceRegistry,
    root: Path,
    slot: ProjectSlot,
) -> str:
    point_lock = slot.store._collection_locks[slot.store.CODE_TABLE_NAME]  # pyright: ignore[reportPrivateUsage]
    gpu_lock = registry.gpu_lock
    gpu_lock.acquire()
    try:
        cancelled_id = jobs.start_reindex_codebase(root, clean=False)
        embedding = await _wait_for_managed_job(
            manager,
            cancelled_id,
            _code_attempt_reached_embedding_boundary,
            "incremental job did not enter the real embedding pipeline",
        )
        assert embedding.state is JobState.RUNNING
        point_lock.acquire()
    finally:
        gpu_lock.release()

    try:
        # Holding the collection lock parks the sole consumer at the managed
        # write-lock acquisition gate, after the post-GPU checkpoint but before
        # any store mutation. That gate polls cooperative control, so a cancel
        # requested here is delivered before the (doomed) upsert can run: no
        # encoded chunk is ever persisted.
        await asyncio.sleep(2.0)
        blocked = manager.get(cancelled_id)
        assert blocked is not None
        assert blocked.state is JobState.RUNNING
        assert blocked.progress is not None
        assert blocked.progress.step == "chunk + embed"
        assert blocked.progress.completed == blocked.progress.total == 4
        assert registry.gpu_lock.locked() is False
        cancel = manager.set_desired_state(cancelled_id, DesiredJobState.CANCELLED)
        assert cancel.status is JobOutcomeStatus.ACCEPTED
        assert cancel.job is not None
        assert cancel.job.state is JobState.CANCELLING
    finally:
        point_lock.release()
    return cancelled_id


async def _assert_cancel_wins_at_the_write_gate(
    manager: JobManager,
    cancelled_id: str,
    slot: ProjectSlot,
) -> None:
    joined = await manager.wait_for_attempt(
        cancelled_id,
        timeout_seconds=_MANAGED_WAIT_SECONDS,
    )
    assert joined.code == "attempt_released"
    cancelled = manager.get(cancelled_id)
    assert cancelled is not None
    assert cancelled.state is JobState.CANCELLED
    assert cancelled.desired_state is DesiredJobState.CANCELLED
    assert cancelled.timestamps.control_requested_at is not None
    assert cancelled.timestamps.control_acknowledged_at is not None
    # The pending write never executed: a cancel delivered at the pre-mutation
    # write gate wins cleanly and cannot surface the doomed dimension-mismatch
    # write as a spurious failure. Nothing was persisted.
    assert cancelled.error_kind is None
    assert cancelled.result is None
    assert slot.store.count_code() == 0
    _assert_manager_resources_released(cancelled, slot, code=True)


@pytest.fixture(scope="module")
def managed_facade_registry(
    tmp_path_factory: TempPathFactory,
) -> Generator[ServiceRegistry]:
    """Load one cached production model through the public registry API."""
    runtime_root = tmp_path_factory.mktemp("managed-job-facade")
    reset_registry()
    jobs.reset()
    reset_limiters()
    reset_config()
    get_config(_managed_test_config(status_dir=runtime_root / "status"))
    registry = get_registry()
    registry.load_model()
    yield registry
    survivors = jobs.get_job_manager().active()
    if survivors:
        survivor_ids = ", ".join(snapshot.id for snapshot in survivors)
        raise AssertionError(
            "refusing to close the production registry while managed attempts "
            f"remain active: {survivor_ids}"
        )
    reset_registry()
    jobs.reset()
    reset_limiters()
    reset_config()


@pytest.fixture
async def managed_job_manager(
    managed_facade_registry: ServiceRegistry,
) -> AsyncGenerator[JobManager]:
    """Isolate manager state and boundedly drain production work on teardown."""
    get_config(_managed_test_config())
    jobs.reset()
    reset_limiters()
    manager = jobs.get_job_manager()
    yield manager

    for snapshot in manager.active():
        manager.set_desired_state(snapshot.id, DesiredJobState.CANCELLED)
    join_failures: list[str] = []
    for snapshot in manager.active():
        joined = await manager.wait_for_attempt(
            snapshot.id,
            timeout_seconds=_MANAGED_WAIT_SECONDS,
        )
        if joined.code != "attempt_released":
            join_failures.append(f"{snapshot.id}: {joined.code}")
    survivors = manager.active()
    if join_failures or survivors:
        survivor_ids = ", ".join(snapshot.id for snapshot in survivors)
        details = "; ".join(join_failures)
        raise AssertionError(
            "refusing to close stores or reset runtime ownership after failed "
            f"manager drain: joins=[{details}], active=[{survivor_ids}]"
        )
    for root in managed_facade_registry.health()["projects"]:
        managed_facade_registry.close_project(Path(root))
    jobs.reset()
    reset_limiters()


def _stored_code_content(store: VaultStore) -> dict[str, str]:
    """Read the real Qdrant payloads and combine content by source path."""
    content_by_path: dict[str, list[str]] = {}
    offset: object | None = None
    while True:
        records, next_offset = store.client.scroll(
            collection_name=store.CODE_TABLE_NAME,
            limit=64,
            offset=offset,
            with_payload=["path", "content"],
            with_vectors=False,
        )
        for record in records:
            payload = record.payload
            assert payload is not None
            path = str(payload["path"])
            content_by_path.setdefault(path, []).append(str(payload["content"]))
        if next_offset is None:
            break
        offset = next_offset
    return {path: "\n".join(parts) for path, parts in content_by_path.items()}


def _assert_current_code_state(
    indexer: CodebaseIndexer,
    store: VaultStore,
    paths: list[Path],
    revision: str,
) -> None:
    """Verify complete metadata and current source text through production output."""
    expected_paths = {
        str(path.relative_to(indexer.root_dir)).replace("\\", "/") for path in paths
    }
    assert set(indexer._load_meta()) == expected_paths
    stored = _stored_code_content(store)
    assert set(stored) == expected_paths
    for ordinal, path in enumerate(paths):
        rel_path = str(path.relative_to(indexer.root_dir)).replace("\\", "/")
        assert f"{revision}-{ordinal:03d}" in stored[rel_path]


@pytest.mark.parametrize(
    ("control_request", "signal_type"),
    [
        pytest.param(ControlRequest.PAUSE, PauseRequested, id="pause"),
        pytest.param(ControlRequest.CANCEL, CancelRequested, id="cancel"),
    ],
)
def test_vault_stream_observes_control_between_published_slices(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
    control_request: ControlRequest,
    signal_type: type[RunControlSignal],
) -> None:
    """Pause and cancel stop real streaming only at a safe slice boundary."""
    documents = _write_vault_documents(tmp_path, 128)
    token = RunControlToken()

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        store.ensure_table()
        with ThreadPoolExecutor(max_workers=1) as executor:
            requester = executor.submit(
                _request_after_first_upsert,
                store,
                token,
                control_request,
            )
            with pytest.raises(signal_type):
                _stream_encode_and_upsert_vault(
                    docs=documents,
                    slice_size=1,
                    model=cpu_embedding_model,
                    store=store,
                    gpu_lock=None,
                    reporter=NullProgressReporter(),
                    run_control=token,
                )
            requester.result(timeout=_CONTROL_WAIT_SECONDS)

        published = store.count()
        assert 0 < published < len(documents)
        assert token.snapshot().delivered is control_request


def test_clean_rebuild_defers_pause_until_complete_publication(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """A clean rebuild publishes all points and metadata before pausing."""
    documents = _write_vault_documents(tmp_path, 16)
    expected_ids = {document.id for document in documents}
    token = RunControlToken()
    gpu_lock = threading.Lock()

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = VaultIndexer(
            tmp_path,
            cpu_embedding_model,
            store,
            gpu_lock=gpu_lock,
        )
        seeded = indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
        )
        assert seeded.added == len(documents)
        assert store.get_all_ids() == expected_ids
        metadata_before = indexer._load_meta()
        revised_document = documents[0]
        revised_path = tmp_path / ".vault" / revised_document.path
        revised_marker = "delta content published by the protected rebuild"
        revised_path.write_text(
            f"{revised_path.read_text(encoding='utf-8')}\n{revised_marker}\n",
            encoding="utf-8",
        )

        with ThreadPoolExecutor(max_workers=1) as executor:
            gpu_lock.acquire()
            try:
                rebuild = executor.submit(
                    indexer.full_index,
                    True,
                    reporter=NullProgressReporter(),
                    run_control=token,
                )

                deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
                publication_started = False
                while time.monotonic() < deadline:
                    state = token.snapshot()
                    if state.protected_depth == 1 and store.count() == 0:
                        publication_started = True
                        break
                    time.sleep(_CONTROL_POLL_SECONDS)
                assert publication_started, (
                    "clean rebuild did not reach its protected empty-collection span"
                )

                assert token.request_pause()
                pending = token.snapshot()
                assert pending.desired is ControlRequest.PAUSE
                assert pending.delivered is None
                assert pending.protected_depth == 1

                gpu_lock.release()
                with pytest.raises(PauseRequested):
                    rebuild.result(timeout=_CONTROL_WAIT_SECONDS)
            finally:
                if gpu_lock.locked():
                    gpu_lock.release()

        assert store.get_all_ids() == expected_ids
        metadata_after = indexer._load_meta()
        assert set(metadata_after) == expected_ids
        assert (
            metadata_after[revised_document.id] != metadata_before[revised_document.id]
        )
        stored_document = store.get_by_id(revised_document.id)
        assert stored_document is not None
        assert revised_marker in stored_document["content"]
        final = token.snapshot()
        assert final.delivered is ControlRequest.PAUSE
        assert final.protected_depth == 0


@pytest.mark.parametrize(
    ("control_request", "signal_type"),
    [
        pytest.param(ControlRequest.PAUSE, PauseRequested, id="pause"),
        pytest.param(ControlRequest.CANCEL, CancelRequested, id="cancel"),
    ],
)
def test_code_pipeline_control_unwinds_and_reconciliation_converges(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
    control_request: ControlRequest,
    signal_type: type[RunControlSignal],
) -> None:
    """Pause/cancel unwind producers and consumer before a fresh attempt converges."""
    paths = _write_code_files(tmp_path, 192, "initial")
    token = RunControlToken()

    assert not _code_consumer_threads()
    assert not multiprocessing.active_children()
    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = CodebaseIndexer(tmp_path, cpu_embedding_model, store)
        with ThreadPoolExecutor(max_workers=1) as executor:
            requester = executor.submit(
                _request_after_first_code_upsert,
                store,
                token,
                control_request,
            )
            with pytest.raises(signal_type):
                indexer.full_index(
                    reporter=NullProgressReporter(),
                    preflight=indexer.preflight_content(),
                    run_control=token,
                )
            requester.result(timeout=_CONTROL_WAIT_SECONDS)

        assert token.snapshot().delivered is control_request
        _assert_code_resources_released()
        published_count = store.count_code()
        published_ids = store.get_all_code_ids()
        assert 0 < published_count < len(paths)
        assert len(published_ids) == published_count

        time.sleep(0.25)
        assert store.count_code() == published_count
        assert store.get_all_code_ids() == published_ids

        reconciled = indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
            run_control=RunControlToken(),
        )
        assert reconciled.files == len(paths)
        _assert_current_code_state(indexer, store, paths, "initial")

    _assert_code_resources_released()


def test_code_clean_rebuild_defers_pause_until_publication_is_current(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """Clean code publication cannot expose an empty or stale collection."""
    paths = _write_code_files(tmp_path, 24, "seed")
    token = RunControlToken()
    gpu_lock = threading.Lock()

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = CodebaseIndexer(
            tmp_path,
            cpu_embedding_model,
            store,
            gpu_lock=gpu_lock,
        )
        indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        _assert_current_code_state(indexer, store, paths, "seed")
        metadata_before = indexer._load_meta()
        paths = _write_code_files(tmp_path, len(paths), "clean-current")

        with ThreadPoolExecutor(max_workers=1) as executor:
            gpu_lock.acquire()
            try:
                rebuild = executor.submit(
                    indexer.full_index,
                    True,
                    reporter=NullProgressReporter(),
                    preflight=indexer.preflight_content(),
                    run_control=token,
                )
                deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
                while time.monotonic() < deadline:
                    state = token.snapshot()
                    if state.protected_depth == 1 and store.count_code() == 0:
                        break
                    time.sleep(_CONTROL_POLL_SECONDS)
                else:
                    raise AssertionError(
                        "clean code rebuild never exposed its protected empty span"
                    )

                assert token.request_pause()
                pending = token.snapshot()
                assert pending.desired is ControlRequest.PAUSE
                assert pending.delivered is None
                assert pending.protected_depth == 1
                assert not rebuild.done()

                gpu_lock.release()
                with pytest.raises(PauseRequested):
                    rebuild.result(timeout=_CONTROL_WAIT_SECONDS)
            finally:
                if gpu_lock.locked():
                    gpu_lock.release()

        _assert_current_code_state(indexer, store, paths, "clean-current")
        metadata_after = indexer._load_meta()
        assert metadata_after.keys() == metadata_before.keys()
        assert all(
            metadata_after[path] != old_hash
            for path, old_hash in metadata_before.items()
        )
        final = token.snapshot()
        assert final.delivered is ControlRequest.PAUSE
        assert final.protected_depth == 0

    _assert_code_resources_released()


def test_code_scoped_replacement_defers_pause_until_data_and_metadata_are_current(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """A scoped replacement delivers pause only after new chunks and metadata."""
    paths = _write_code_files(tmp_path, 4, "seed")
    token = RunControlToken()
    gpu_lock = threading.Lock()

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = CodebaseIndexer(
            tmp_path,
            cpu_embedding_model,
            store,
            gpu_lock=gpu_lock,
        )
        indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        changed_path = paths[0]
        rel_path = str(changed_path.relative_to(tmp_path)).replace("\\", "/")
        old_ids = set(store.get_code_ids_by_paths({rel_path}))
        assert old_ids
        metadata_before = indexer._load_meta()
        paths = _write_code_files(tmp_path, len(paths), "scoped-current")

        with ThreadPoolExecutor(max_workers=1) as executor:
            replacement = executor.submit(
                indexer.incremental_index,
                reporter=NullProgressReporter(),
                changed_paths=paths,
                preflight=indexer.preflight_changed_paths(paths),
                run_control=token,
            )
            deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
            while time.monotonic() < deadline:
                state = token.snapshot()
                if state.protected_depth == 1:
                    break
                time.sleep(_CONTROL_POLL_SECONDS)
            else:
                raise AssertionError(
                    "scoped replacement never exposed its protected commit span"
                )

            assert token.request_pause()
            pending = token.snapshot()
            assert pending.desired is ControlRequest.PAUSE
            assert pending.delivered is None
            assert pending.protected_depth == 1
            assert not replacement.done()

            with pytest.raises(PauseRequested):
                replacement.result(timeout=_CONTROL_WAIT_SECONDS)

        new_ids = set(store.get_code_ids_by_paths({rel_path}))
        assert new_ids
        assert new_ids.isdisjoint(old_ids)
        _assert_current_code_state(indexer, store, paths, "scoped-current")
        metadata_after = indexer._load_meta()
        assert metadata_after.keys() == metadata_before.keys()
        assert all(
            metadata_after[path] != old_hash
            for path, old_hash in metadata_before.items()
        )
        final = token.snapshot()
        assert final.delivered is ControlRequest.PAUSE
        assert final.protected_depth == 0

    _assert_code_resources_released()


@pytest.mark.timeout(300)
async def test_managed_vault_pause_releases_resources_and_resume_reconciles(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """The public facade pauses only after release, then resumes the same ID."""
    root = tmp_path / "managed-vault"
    documents = _write_vault_documents(root, 128)
    expected_ids = {document.id for document in documents}
    slot = managed_facade_registry.peek_project(root)

    job_id = jobs.start_reindex_vault(root, clean=False)
    live = await _wait_for_managed_job(
        managed_job_manager,
        job_id,
        partial(_vault_attempt_published, slot=slot),
        "vault attempt did not publish while owning its execution resources",
    )
    assert live.attempt.number == 1
    assert slot.ref_count == 1
    # Encode-bearing jobs borrow the machine-wide encode admission
    # slot rather than the wider index partition.
    assert limiter_stats()["encode"]["borrowed_tokens"] == 1
    first_task, paused = await _pause_managed_attempt(managed_job_manager, job_id)
    _assert_manager_resources_released(paused, slot, code=False)

    succeeded = await _resume_managed_attempt(
        managed_job_manager,
        job_id,
        first_task,
        "fresh reconciliation attempt did not start",
    )
    assert slot.store.get_all_ids() == expected_ids
    assert set(slot.vault_indexer._load_meta()) == expected_ids
    _assert_manager_resources_released(succeeded, slot, code=False)


@pytest.mark.timeout(300)
async def test_managed_code_pause_releases_pipeline_and_resume_reconciles(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """A public code pause releases its real pipeline before reconciliation."""
    root = tmp_path / "managed-code-pause"
    paths = _write_code_files(root, 192, "initial")
    slot = managed_facade_registry.peek_project(root)

    job_id = jobs.start_reindex_codebase(root, clean=True)
    live = await _wait_for_managed_job(
        managed_job_manager,
        job_id,
        partial(_code_pipeline_published, slot=slot),
        "code pipeline did not publish before pause",
    )
    assert live.attempt.number == 1
    assert slot.ref_count == 1
    # Encode-bearing jobs borrow the machine-wide encode admission
    # slot rather than the wider index partition.
    assert limiter_stats()["encode"]["borrowed_tokens"] == 1

    first_task, paused = await _pause_managed_attempt(managed_job_manager, job_id)
    _assert_manager_resources_released(paused, slot, code=True)
    _assert_current_code_state(slot.code_indexer, slot.store, paths, "initial")

    succeeded = await _resume_managed_attempt(
        managed_job_manager,
        job_id,
        first_task,
        "fresh code reconciliation attempt did not start",
    )
    _assert_manager_resources_released(succeeded, slot, code=True)
    _assert_current_code_state(slot.code_indexer, slot.store, paths, "initial")


@pytest.mark.timeout(300)
async def test_managed_vault_cancel_is_absorbing_and_stops_all_writes(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """A public vault cancellation acknowledges after every writer exits."""
    root = tmp_path / "managed-vault-cancel"
    _write_vault_documents(root, 128)
    slot = managed_facade_registry.peek_project(root)

    job_id = jobs.start_reindex_vault(root, clean=False)
    live = await _wait_for_managed_job(
        managed_job_manager,
        job_id,
        partial(_vault_attempt_published, slot=slot),
        "vault attempt did not publish before cancellation",
    )
    assert live.attempt.number == 1
    cancelled = await _cancel_managed_attempt(managed_job_manager, job_id)
    _assert_manager_resources_released(cancelled, slot, code=False)
    await _assert_cancelled_vault_stops_writes(
        managed_job_manager,
        job_id,
        cancelled,
        slot,
        root,
    )
    _assert_cancelled_job_is_absorbing(managed_job_manager, job_id)
    assert managed_job_manager.get(job_id) == cancelled


@pytest.mark.timeout(300)
async def test_managed_cancel_at_write_gate_wins_without_spurious_failure(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """A cancel at the pre-mutation write gate wins cleanly for a doomed write.

    The store-retry contract that a genuine store failure outranks a cancel
    delivered during backoff is enforced and guard-tested at its own layer.
    Here the operator cancels while the sole consumer is still parked at the
    managed write-lock acquisition gate - before any mutation - so the pending
    dimension-mismatch write never executes. The attempt must acknowledge the
    cancel, persist nothing, and never record a spurious failure.
    """
    root = tmp_path / "managed-code-cancel-gate"
    paths = _write_code_files(root, 4, "seed")
    initial_id = jobs.start_reindex_codebase(root, clean=True)
    initial_join = await managed_job_manager.wait_for_attempt(
        initial_id,
        timeout_seconds=_MANAGED_WAIT_SECONDS,
    )
    assert initial_join.code == "attempt_released"
    initial = managed_job_manager.get(initial_id)
    assert initial is not None
    assert initial.state is JobState.SUCCEEDED

    slot = _prepare_dimension_failure(
        managed_facade_registry,
        root,
        file_count=len(paths),
    )
    cancelled_id = await _request_cancel_at_the_write_gate(
        managed_job_manager,
        managed_facade_registry,
        root,
        slot,
    )
    await _assert_cancel_wins_at_the_write_gate(
        managed_job_manager, cancelled_id, slot
    )


class _AbortAfterFirstCommitReporter(NullProgressReporter):
    """Real reporter that crashes the run after durable indexing progress.

    Raising at the production progress boundary once the run ledger has
    storage-confirmed at least one unit leaves exactly the state an
    interrupted clean rebuild leaves behind: a resumable generation whose
    committed units a later attempt would skip instead of re-encoding.
    """

    def __init__(self, indexer: CodebaseIndexer) -> None:
        self._indexer = indexer
        self._phase = ""

    def phase_start(self, name: str, total: int | None) -> None:
        del total
        self._phase = name

    def advance(self, n: int = 1) -> None:
        del n
        if self._phase != "chunk + embed":
            return
        checkpoint = self._indexer.last_checkpoint
        if (
            checkpoint is not None
            and checkpoint.ledger.committed_unit_count(checkpoint.generation_id) > 0
        ):
            raise RuntimeError("injected mid-rebuild crash after first commit")


def test_clean_rebuild_reencodes_when_collection_vanished_under_the_ledger(
    tmp_path: Path,
    cpu_embedding_model: EmbeddingModel,
) -> None:
    """A rebuild must not trust ledger evidence for a destroyed collection.

    External storage destruction (the storage delete verb) drops the code
    collection but leaves the per-root run ledger behind. Resuming the
    interrupted generation would skip its storage-confirmed units with zero
    encoding, publishing a "successful" index whose committed portion no
    longer exists anywhere. The rebuild must retire that generation and
    re-encode from scratch.
    """
    paths = _write_code_files(tmp_path, 128, "ledger-stale")

    with VaultStore(tmp_path, embedding_dim=cpu_embedding_model.dimension) as store:
        indexer = CodebaseIndexer(
            tmp_path,
            cpu_embedding_model,
            store,
            gpu_lock=threading.Lock(),
        )
        with pytest.raises(RuntimeError, match="injected mid-rebuild crash"):
            indexer.full_index(
                clean=True,
                reporter=_AbortAfterFirstCommitReporter(indexer),
                preflight=indexer.preflight_content(),
            )
        interrupted = indexer.last_checkpoint
        assert interrupted is not None
        committed = interrupted.ledger.committed_unit_count(interrupted.generation_id)
        assert committed > 0, "the crash must land after storage-confirmed progress"

        # The storage-delete equivalent: the collection vanishes out-of-band
        # while the per-root run ledger (index_runs.sqlite3) stays behind.
        store.drop_code_table()

        result = indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        # Binds the staleness guard: without it the resumed generation skips
        # its committed units (resumed_units > 0, zero re-encode) and the
        # store is missing exactly those files' chunks while the run still
        # reports success.
        _assert_current_code_state(indexer, store, paths, "ledger-stale")
        fresh = indexer.last_checkpoint
        assert fresh is not None
        assert fresh.resumed_units == 0
        assert store.count_code() == result.added
    _assert_code_resources_released()
