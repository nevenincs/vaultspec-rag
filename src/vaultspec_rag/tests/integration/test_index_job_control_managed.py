# ruff: noqa: E402
"""Real-behavior integration coverage for cooperative indexing control.

The tests use the production streaming and indexing paths with local Qdrant,
real vault and code files, and a CPU-backed SentenceTransformer model. Keeping
the model tiny makes the control races deterministic without substituting test
implementations for any production indexing behavior.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

import pytest

from ... import jobs
from ...concurrency import limiter_stats
from ...embeddings import EmbeddingModel  # noqa: TC001
from ...indexer import CodebaseIndexer
from ...job_control import (
    CancelRequested,
    ControlRequest,
    PauseRequested,
    RunControlSignal,
    RunControlToken,
)
from ...job_models import (
    JobState,
)
from ...progress import NullProgressReporter
from ...store_runtime import VaultStore

if TYPE_CHECKING:
    from ...job_manager.manager import JobManager
    from ...service import ServiceRegistry

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

from ._index_job_control_support import (
    _assert_code_resources_released,
    _assert_manager_resources_released,
    _code_consumer_threads,
    _wait_for_managed_job,
    _write_code_files,
    assert_cancel_wins_at_the_write_gate,
    assert_cancelled_job_is_absorbing,
    assert_cancelled_vault_stops_writes,
    assert_current_code_state,
    cancel_managed_attempt,
    code_pipeline_published,
    pause_managed_attempt,
    prepare_empty_code_collection,
    request_after_first_code_upsert,
    request_cancel_at_the_write_gate,
    resume_managed_attempt,
    vault_attempt_published,
    write_vault_documents,
)


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
                request_after_first_code_upsert,
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
        assert_current_code_state(indexer, store, paths, "initial")

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
            options=CodebaseIndexer.Options(gpu_lock=gpu_lock),
        )
        indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert_current_code_state(indexer, store, paths, "seed")
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
                served_before_rebuild = store.count_code()
                deadline = time.monotonic() + _CONTROL_WAIT_SECONDS
                while time.monotonic() < deadline:
                    state = token.snapshot()
                    if state.protected_depth == 1:
                        break
                    time.sleep(_CONTROL_POLL_SECONDS)
                else:
                    raise AssertionError(
                        "clean code rebuild never entered its protected span"
                    )

                # The wait used to key on the collection reading zero, because a
                # clean rebuild dropped before repopulating and the empty window
                # was a convenient marker for "inside the protected span". A
                # rebuild now builds beside the served collection, so that window
                # does not exist and waiting for it would hang forever. The
                # protected depth is the property this test was always about.
                #
                # The absent window is worth asserting rather than merely no
                # longer waiting on: a rebuild that emptied what it serves is the
                # defect the generation build removes.
                assert store.count_code() == served_before_rebuild

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

        assert_current_code_state(indexer, store, paths, "clean-current")
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
            options=CodebaseIndexer.Options(gpu_lock=gpu_lock),
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
        assert_current_code_state(indexer, store, paths, "scoped-current")
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
    documents = write_vault_documents(root, 128)
    expected_ids = {document.id for document in documents}
    slot = managed_facade_registry.peek_project(root)

    job_id = jobs.start_reindex_vault(root, clean=False)
    live = await _wait_for_managed_job(
        managed_job_manager,
        job_id,
        partial(vault_attempt_published, slot=slot),
        "vault attempt did not publish while owning its execution resources",
    )
    assert live.attempt.number == 1
    assert slot.ref_count == 1
    # Encode-bearing jobs borrow the machine-wide encode admission
    # slot rather than the wider index partition.
    assert limiter_stats()["encode"]["borrowed_tokens"] == 1
    first_task, paused = await pause_managed_attempt(managed_job_manager, job_id)
    _assert_manager_resources_released(
        paused, managed_facade_registry, root, code=False
    )

    succeeded = await resume_managed_attempt(
        managed_job_manager,
        job_id,
        first_task,
        "fresh reconciliation attempt did not start",
    )
    assert slot.store.get_all_ids() == expected_ids
    with managed_facade_registry.compute_lease(root) as lease:
        assert set(lease.runtime.vault_indexer._load_meta()) == expected_ids
    _assert_manager_resources_released(
        succeeded, managed_facade_registry, root, code=False
    )


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
        partial(code_pipeline_published, slot=slot),
        "code pipeline did not publish before pause",
    )
    assert live.attempt.number == 1
    assert slot.ref_count == 1
    # Encode-bearing jobs borrow the machine-wide encode admission
    # slot rather than the wider index partition.
    assert limiter_stats()["encode"]["borrowed_tokens"] == 1

    first_task, paused = await pause_managed_attempt(managed_job_manager, job_id)
    _assert_manager_resources_released(paused, managed_facade_registry, root, code=True)
    with managed_facade_registry.compute_lease(root) as lease:
        assert_current_code_state(
            lease.runtime.code_indexer, slot.store, paths, "initial"
        )

    succeeded = await resume_managed_attempt(
        managed_job_manager,
        job_id,
        first_task,
        "fresh code reconciliation attempt did not start",
    )
    _assert_manager_resources_released(
        succeeded, managed_facade_registry, root, code=True
    )
    with managed_facade_registry.compute_lease(root) as lease:
        assert_current_code_state(
            lease.runtime.code_indexer, slot.store, paths, "initial"
        )


@pytest.mark.timeout(300)
async def test_managed_vault_cancel_is_absorbing_and_stops_all_writes(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """A public vault cancellation acknowledges after every writer exits."""
    root = tmp_path / "managed-vault-cancel"
    write_vault_documents(root, 128)
    slot = managed_facade_registry.peek_project(root)

    job_id = jobs.start_reindex_vault(root, clean=False)
    live = await _wait_for_managed_job(
        managed_job_manager,
        job_id,
        partial(vault_attempt_published, slot=slot),
        "vault attempt did not publish before cancellation",
    )
    assert live.attempt.number == 1
    cancelled = await cancel_managed_attempt(managed_job_manager, job_id)
    _assert_manager_resources_released(
        cancelled, managed_facade_registry, root, code=False
    )
    await assert_cancelled_vault_stops_writes(
        managed_job_manager,
        job_id,
        cancelled,
        slot,
        root,
    )
    assert_cancelled_job_is_absorbing(managed_job_manager, job_id)
    assert managed_job_manager.get(job_id) == cancelled


@pytest.mark.timeout(300)
async def test_managed_cancel_at_write_gate_wins_without_spurious_failure(
    tmp_path: Path,
    managed_facade_registry: ServiceRegistry,
    managed_job_manager: JobManager,
) -> None:
    """A cancel at the pre-mutation write gate wins before a valid upsert.

    Here the operator cancels while the sole consumer is still parked at the
    managed write-lock acquisition gate - before any mutation - so the pending
    valid upsert never executes. The attempt must acknowledge the cancel, persist
    nothing, and never record a spurious failure. The separate store-retry
    failure-precedence proof lives in
    ``test_store_writes.py::TestFailureOutranksPendingControl``.
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

    slot = prepare_empty_code_collection(
        managed_facade_registry,
        root,
        file_count=len(paths),
    )
    cancelled_id = await request_cancel_at_the_write_gate(
        managed_job_manager,
        managed_facade_registry,
        root,
        slot,
    )
    await assert_cancel_wins_at_the_write_gate(
        managed_job_manager,
        cancelled_id,
        managed_facade_registry,
        root,
    )
