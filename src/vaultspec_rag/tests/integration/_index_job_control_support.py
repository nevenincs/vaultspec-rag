"""Real-behavior integration coverage for cooperative indexing control.

The tests use the production streaming and indexing paths with local Qdrant,
real vault and code files, and a CPU-backed SentenceTransformer model. Keeping
the model tiny makes the control races deterministic without substituting test
implementations for any production indexing behavior.
"""

from __future__ import annotations

import asyncio
import contextlib
import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest

from ... import jobs
from ..._index_breadth import index_meta_path
from ..._source_types import PublicSourceType
from ...concurrency import limiter_stats, reset_limiters
from ...config._settings import get_config, reset_config
from ...embeddings import EmbeddingModel  # noqa: TC001
from ...indexer import CodebaseIndexer, VaultIndexer  # noqa: TC001
from ...indexer._vault_prep import prepare_document
from ...job_control import (
    CancelRequested,
    ControlRequest,
    PauseRequested,
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
from ...store_runtime import VaultStore
from ._helpers import cpu_backed_embedding_model

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator

    from _pytest.tmpdir import TempPathFactory

    from ..._store_models import VaultDocument
    from ...job_manager.manager import JobManager
    from ...service import ProjectSlot, ServiceRegistry

pytestmark = pytest.mark.integration

_CONTROL_WAIT_SECONDS = 20.0
# Generous on purpose. These waits bound a real job - process-pool chunking, a
# real encode of the whole corpus, then publication - on whatever machine the
# suite happens to run on. A bound tuned to an idle machine turns ordinary load
# into a failure, and a suite that fails under load cannot be used to judge
# whether a change regressed anything: the A/B it is asked for returns noise.
# Sixty seconds was such a bound; a passing run of the managed rebuild took
# 68.8s wall-clock on a host also running the resident daemon. The only thing
# these should catch is a job that has genuinely stopped making progress.
_MANAGED_WAIT_SECONDS = 240.0
_CONTROL_POLL_SECONDS = 0.001


class _RevisedVaultPublication(NamedTuple):
    """The real rebuild state that must be visible before pause delivery."""

    expected_ids: set[str]
    document_id: str
    metadata_before: dict[str, str]
    marker: str


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

    def configure(dimension: int) -> None:
        get_config(
            {
                "data_dir": ".index-control",
                "embedding_batch_size": 1,
                "embedding_dimension": dimension,
                "embedding_encode_batch_size": 1,
                "index_chunk_workers": 2,
                # Force more than one durable weighted slice so pause/cancel
                # can be observed between production publication checkpoints.
                # The batch-size setting intentionally does not cap segment
                # capacity.
                "index_segment_max_chunks": 8,
                "index_queue_max_chunks": 16,
                "qdrant_url": None,
                "sparse_enabled": False,
                "vault_chunk_chars": 10_000,
            }
        )

    return cpu_backed_embedding_model(vocabulary, configure)


def write_vault_documents(root: Path, count: int) -> list[VaultDocument]:
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


def request_after_first_upsert(
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


def request_after_first_code_upsert(
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
    registry: ServiceRegistry,
    root: Path,
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
    slot = registry.peek_project(root)
    assert slot.ref_count == 0
    with registry.compute_lease(root) as lease:
        indexer = lease.runtime.code_indexer if code else lease.runtime.vault_indexer
        assert indexer._writer_lock.acquire(blocking=False)
        indexer._writer_lock.release()
    if code:
        _assert_code_resources_released()


def vault_attempt_published(snapshot: JobSnapshot, *, slot: ProjectSlot) -> bool:
    return (
        snapshot.state is JobState.RUNNING
        and snapshot.runtime.task_active
        and snapshot.runtime.worker_active
        and snapshot.resources.index_capacity_held
        and snapshot.resources.project_lease_held
        and snapshot.resources.writer_lock_held
        and slot.store.count() > 0
    )


def code_pipeline_published(snapshot: JobSnapshot, *, slot: ProjectSlot) -> bool:
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


async def pause_managed_attempt(
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


async def resume_managed_attempt(
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


async def cancel_managed_attempt(
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


async def assert_cancelled_vault_stops_writes(
    manager: JobManager,
    job_id: str,
    cancelled: JobSnapshot,
    slot: ProjectSlot,
    root: Path,
) -> None:
    # Resolve through production rather than deriving the path here: every
    # assertion below tolerates the sidecar being absent, so a path that did
    # not name the file the indexer writes would compare None against None and
    # report a pass without ever observing the writes it exists to forbid.
    metadata_path = index_meta_path(root, PublicSourceType.VAULT)
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


def assert_cancelled_job_is_absorbing(manager: JobManager, job_id: str) -> None:
    replay = manager.set_desired_state(job_id, DesiredJobState.CANCELLED)
    assert replay.status is JobOutcomeStatus.OK
    assert replay.code == "already_satisfied"
    rejected = manager.set_desired_state(job_id, DesiredJobState.RUNNING)
    assert rejected.status is JobOutcomeStatus.ERROR
    assert rejected.code == "invalid_transition"


def prepare_empty_code_collection(
    registry: ServiceRegistry,
    root: Path,
    *,
    file_count: int,
) -> ProjectSlot:
    registry.close_project(root)
    with VaultStore(root, embedding_dim=registry.model.dimension) as empty_store:
        empty_store.drop_code_table()
        empty_store.ensure_code_table()
    _write_code_files(root, file_count, "empty-collection")
    return registry.peek_project(root)


async def request_cancel_at_the_write_gate(
    manager: JobManager,
    registry: ServiceRegistry,
    root: Path,
    slot: ProjectSlot,
) -> str:
    point_lock = slot.store._collection_locks[slot.store.CODE_TABLE_NAME]
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
        # requested here is delivered before the pending upsert can run: no
        # encoded chunk is ever persisted.
        await asyncio.sleep(2.0)
        blocked = manager.get(cancelled_id)
        assert blocked is not None
        assert blocked.state is JobState.RUNNING
        assert blocked.progress is not None
        assert blocked.progress.step == "chunk + embed"
        # The counter measures consumer-confirmed files, and the parked
        # consumer has confirmed nothing: everything is produced, nothing
        # is counted done. Progress at the total here would mean the count
        # regressed to measuring queue handoff again.
        assert blocked.progress.total == 4
        assert blocked.progress.completed == 0
        assert registry.gpu_lock.locked() is False
        cancel = manager.set_desired_state(cancelled_id, DesiredJobState.CANCELLED)
        assert cancel.status is JobOutcomeStatus.ACCEPTED
        assert cancel.job is not None
        assert cancel.job.state is JobState.CANCELLING
    finally:
        point_lock.release()
    return cancelled_id


async def assert_cancel_wins_at_the_write_gate(
    manager: JobManager,
    cancelled_id: str,
    registry: ServiceRegistry,
    root: Path,
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
    # write gate wins cleanly without recording a spurious failure. Nothing was
    # persisted.
    assert cancelled.error_kind is None
    assert cancelled.result is None
    slot = registry.peek_project(root)
    assert slot.store.count_code() == 0
    _assert_manager_resources_released(cancelled, registry, root, code=True)


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


def assert_current_code_state(
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


def _wait_for_clean_vault_publication(
    token: RunControlToken, store: VaultStore, served_count: int
) -> None:
    """Wait for the protected span, with every served point still readable.

    A clean rebuild replaces in place: it upserts over the live points and
    purges what the new corpus no longer holds only once the stream has
    proved the replacement whole. So the collection is never emptied, and
    waiting for an empty one waits forever. Requiring the served count
    instead binds that promise - reinstating an up-front drop takes the
    count to zero here and this never returns.
    """
    deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
    while time.monotonic() < deadline:
        state = token.snapshot()
        if state.protected_depth == 1 and store.count() == served_count:
            return
        time.sleep(_CONTROL_POLL_SECONDS)
    raise AssertionError(
        "clean rebuild did not reach its protected span with the served "
        f"points intact: count={store.count()}, expected {served_count}"
    )


def pause_clean_vault_rebuild(
    indexer: VaultIndexer,
    store: VaultStore,
    token: RunControlToken,
    gpu_lock: threading.Lock,
    served_count: int,
) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        gpu_lock.acquire()
        try:
            rebuild = executor.submit(
                indexer.full_index,
                True,
                reporter=NullProgressReporter(),
                run_control=token,
            )
            _wait_for_clean_vault_publication(token, store, served_count)
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


def assert_revised_vault_publication(
    indexer: VaultIndexer,
    store: VaultStore,
    publication: _RevisedVaultPublication,
    token: RunControlToken,
) -> None:
    assert store.get_all_ids() == publication.expected_ids
    metadata_after = indexer._load_meta()
    assert set(metadata_after) == publication.expected_ids
    assert (
        metadata_after[publication.document_id]
        != publication.metadata_before[publication.document_id]
    )
    stored_document = store.get_by_id(publication.document_id)
    assert stored_document is not None
    assert publication.marker in str(stored_document["content"])
    final = token.snapshot()
    assert final.delivered is ControlRequest.PAUSE
    assert final.protected_depth == 0


class AbortAfterFirstCommitReporter(NullProgressReporter):
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


class CancelAfterCheckpoints:
    """Trip cooperative cancellation after a fixed number of safe checkpoints.

    Implements the production ``RunControl`` protocol rather than standing in
    for anything: this is the same surface a job's control token presents, and
    the signal it raises is the one the indexer already handles.
    """

    def __init__(self, after: int) -> None:
        self._remaining = after

    def checkpoint(self) -> None:
        if self._remaining <= 0:
            raise CancelRequested
        self._remaining -= 1

    def protected(self) -> contextlib.AbstractContextManager[None]:
        return contextlib.nullcontext()
