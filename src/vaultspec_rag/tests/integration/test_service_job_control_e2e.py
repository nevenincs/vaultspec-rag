"""Cross-boundary service job-control scenarios over production components."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import pytest
import uvicorn
from typer.testing import CliRunner

from ... import jobs, server
from ..._index_breadth import index_meta_path
from ..._source_types import PublicSourceType
from ...cli import app
from ...concurrency import limiter_stats, reset_limiters
from ...config._settings import get_config, reset_config
from ...config._types import EnvVar
from ...indexer._vault_prep import prepare_document
from ...job_manager.manager import JobManager
from ...job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobOutcomeStatus,
    JobSource,
    JobSpec,
    JobState,
)
from ...registry import get_registry, reset_registry
from ...server import ServerRouteRuntime, WatcherStartOutcome, create_http_app
from ...server import _lifespan as server_lifespan
from ...service_quiesce import ServiceQuiesceController
from ...serviceclient._transport import (
    _try_http_create_job,
    _try_http_delete_job,
    _try_http_get_job,
    _try_http_set_job_desired_state,
)
from .._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator
    from pathlib import Path

    from ...embeddings import EmbeddingModel
    from ...job_models import JobOutcome, JobSnapshot
    from ...service import ProjectSlot, ServiceRegistry

pytestmark = pytest.mark.integration

_E2E_TIMEOUT_SECONDS = 180.0
_E2E_POLL_SECONDS = 0.01
_CLI_RUNNER = CliRunner()


@contextmanager
def _real_job_control_server(tmp_path: Path) -> Generator[int]:
    """Serve the production route table over a real loopback socket."""
    status_dir = tmp_path / "http-status"
    port = free_loopback_port()
    token = "service-job-control-e2e-token"
    prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
    prior_watch_enabled = os.environ.get(EnvVar.WATCH_ENABLED)
    live_server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    stopped = True
    try:
        status_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        os.environ[EnvVar.WATCH_ENABLED] = "false"
        reset_config()
        jobs.reset()
        (status_dir / "service.json").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "port": port,
                    "service_token": token,
                }
            ),
            encoding="utf-8",
        )
        live_server = uvicorn.Server(
            uvicorn.Config(
                create_http_app(
                    ServerRouteRuntime(
                        token=token,
                        registry=get_registry(),
                        port=port,
                    ),
                    lifespan=None,
                ),
                host="127.0.0.1",
                port=port,
                log_config=None,
                access_log=False,
                lifespan="off",
            )
        )
        thread = threading.Thread(target=live_server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5.0
        while not live_server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert live_server.started
        yield port
    finally:
        if live_server is not None:
            live_server.should_exit = True
        if thread is not None:
            thread.join(timeout=5.0)
            stopped = not thread.is_alive()
        jobs.reset()
        if prior_status_dir is None:
            os.environ.pop(EnvVar.STATUS_DIR, None)
        else:
            os.environ[EnvVar.STATUS_DIR] = prior_status_dir
        if prior_watch_enabled is None:
            os.environ.pop(EnvVar.WATCH_ENABLED, None)
        else:
            os.environ[EnvVar.WATCH_ENABLED] = prior_watch_enabled
        reset_config()
        assert stopped


def _invoke_job_json(*args: str) -> tuple[int, dict[str, object]]:
    result = _CLI_RUNNER.invoke(app, ["server", "job", *args, "--json"])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, result.stdout
    payload = json.loads(lines[0])
    assert isinstance(payload, dict)
    return result.exit_code, cast("dict[str, object]", payload)


@pytest.fixture
async def _e2e_runtime(  # pyright: ignore[reportUnusedFunction]
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    clean_config: None,
) -> AsyncGenerator[tuple[ServiceRegistry, JobManager]]:
    """Provide one real model, registry, manager, and bounded teardown."""
    del clean_config
    jobs.reset()
    reset_limiters()
    get_config(
        {
            "data_dir": ".service-job-control-e2e",
            "status_dir": str(tmp_path / "status"),
            "qdrant_url": None,
            "qdrant_server": False,
            "local_only": True,
            "index_support_profile": "embedded-local",
            "sparse_enabled": False,
            "reranker_enabled": False,
            "embedding_dimension": embedding_model.dimension,
            "embedding_batch_size": 8,
            "embedding_encode_batch_size": 1,
            "index_segment_max_chunks": 8,
            "index_queue_max_chunks": 16,
            "index_job_concurrency": 1,
            "job_shutdown_timeout_seconds": _E2E_TIMEOUT_SECONDS,
            "watch_enabled": True,
            "watch_retry_base_seconds": 1.0,
            "watch_retry_max_seconds": 1.0,
            "watch_retry_jitter_fraction": 0.0,
        }
    )
    # ``get_registry()`` is a process-wide singleton, so a module whose
    # teardown was cut short hands this one its still-open project slots.
    # Claim a fresh registry instead of inheriting whatever the run left
    # behind: closing an ownerless registry is the cleanup its owner skipped,
    # and it makes this fixture's starting state a product of its own action
    # rather than a bet on every earlier module having tidied up.
    reset_registry()
    # ``get_registry()`` rebinds the server package's cached ``_registry``
    # alias as it rebuilds, so the test, the watcher, and the job dispatcher
    # all drive one registry rather than double-opening the same
    # non-parallel-safe local store from two.
    registry = get_registry()
    registry._model = embedding_model
    manager = jobs.get_job_manager()
    try:
        yield registry, manager
    finally:
        try:
            watcher_cleanup = server._stop_all_watchers()
            if watcher_cleanup:
                assert all(await asyncio.gather(*watcher_cleanup))
            assert await server._wait_for_watcher_cleanup(
                timeout_seconds=_E2E_TIMEOUT_SECONDS
            )
            owned_managers = {manager, jobs.get_job_manager()}
            for owned_manager in owned_managers:
                for snapshot in owned_manager.active():
                    outcome = owned_manager.set_desired_state(
                        snapshot.id,
                        DesiredJobState.CANCELLED,
                    )
                    assert outcome.status is not JobOutcomeStatus.ERROR
                for snapshot in owned_manager.active():
                    if snapshot.runtime.task_active:
                        joined = await owned_manager.wait_for_attempt(
                            snapshot.id,
                            timeout_seconds=_E2E_TIMEOUT_SECONDS,
                        )
                        assert joined.code == "attempt_released"
                assert owned_manager.active() == []
        finally:
            # Release the process-global singletons even when a drain
            # assertion above fails. These assertions report on the test that
            # just ran; letting one of them skip the release turns a single
            # failure into a setup error for every test that follows it.
            #
            # Drop the singleton rather than closing it in place: ``close_all``
            # latches ``_shutting_down`` and only ``prepare_startup`` clears it,
            # so a closed-but-retained registry makes every later
            # ``get_registry()`` hand back an instance that raises on the first
            # slot it is asked for. ``reset_registry`` closes this one and clears
            # the reference, so the next caller builds a live registry.
            reset_registry()
            jobs.reset()
            reset_limiters()


def _write_vault_corpus(root: Path, *, start: int, count: int) -> None:
    adr_dir = root / ".vault" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    for ordinal in range(start, start + count):
        (adr_dir / f"job-control-{ordinal:04d}.md").write_text(
            "---\n"
            "tags: ['#adr', '#service-job-control']\n"
            "---\n"
            f"# Job control document {ordinal}\n\n"
            f"pause resume cancel convergence marker {ordinal}\n",
            encoding="utf-8",
        )


def _vault_job_spec(root: Path) -> JobSpec:
    return JobSpec(
        operation=JobOperation.INDEX,
        source=JobSource.VAULT,
        project_root=str(root.resolve()),
        mode=JobMode.INCREMENTAL,
    )


def _integration_initiator(root: Path, command: str) -> JobInitiator:
    return JobInitiator(
        kind="integration",
        command=command,
        project_root=str(root.resolve()),
    )


def _write_watched_document(path: Path, root: Path, marker: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "tags: ['#adr', '#service-job-control']\n"
        "---\n"
        f"# {marker}\n\n"
        f"watcher lifecycle convergence marker {marker}\n",
        encoding="utf-8",
    )
    document = prepare_document(path, root)
    assert document is not None
    return document.id


async def _wait_for_job(
    manager: JobManager,
    job_id: str,
    predicate: Callable[[JobSnapshot], bool],
    description: str,
) -> JobSnapshot:
    deadline = asyncio.get_running_loop().time() + _E2E_TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        snapshot = manager.get(job_id)
        if snapshot is not None and predicate(snapshot):
            return snapshot
        await asyncio.sleep(_E2E_POLL_SECONDS)
    raise AssertionError(f"{description}; last snapshot={manager.get(job_id)!r}")


async def _request_control_on_moving_job(
    manager: JobManager,
    observed: JobSnapshot,
    desired_state: DesiredJobState,
) -> JobOutcome:
    """Land one compare-and-set against a job that is still publishing.

    A running job bumps its revision on every progress publication, so the
    revision read to seed ``expected_revision`` can go stale before the
    compare-and-set consumes it and the request loses the race. Re-read and
    retry the way a real client does, rather than dropping the revision guard
    and giving up the optimistic-concurrency coverage along with the flake.
    """
    deadline = asyncio.get_running_loop().time() + _E2E_TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        outcome = manager.set_desired_state(
            observed.id,
            desired_state,
            expected_revision=observed.revision,
        )
        if outcome.code != "revision_conflict":
            return outcome
        await asyncio.sleep(_E2E_POLL_SECONDS)
        refreshed = manager.get(observed.id)
        assert refreshed is not None
        observed = refreshed
    raise AssertionError(
        f"{desired_state} never won the revision race for {observed.id}; "
        f"last snapshot={manager.get(observed.id)!r}"
    )


def _watcher_jobs(manager: JobManager, root: Path) -> list[JobSnapshot]:
    resolved = str(root.resolve())
    return [
        snapshot
        for snapshot in manager.list_jobs()
        if snapshot.initiator.kind == "watcher"
        and snapshot.spec.project_root == resolved
    ]


async def _wait_for_watcher_job(
    manager: JobManager,
    root: Path,
    predicate: Callable[[JobSnapshot], bool],
    description: str,
) -> JobSnapshot:
    deadline = asyncio.get_running_loop().time() + _E2E_TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        for snapshot in _watcher_jobs(manager, root):
            if predicate(snapshot):
                return snapshot
        await asyncio.sleep(_E2E_POLL_SECONDS)
    raise AssertionError(
        f"{description}; last snapshots={_watcher_jobs(manager, root)!r}"
    )


def _watcher_attempt_owns_runtime(snapshot: JobSnapshot) -> bool:
    return all(
        (
            snapshot.state is JobState.RUNNING,
            snapshot.runtime.task_active,
            snapshot.runtime.worker_active,
            snapshot.resources.index_capacity_held,
            snapshot.resources.project_lease_held,
            snapshot.resources.writer_lock_held,
        )
    )


async def _start_real_watcher(root: Path) -> None:
    resolved = root.resolve()
    assert (
        server._ensure_watcher(resolved, debounce_ms=50, cooldown_s=0.0)
        is WatcherStartOutcome.STARTED
    )
    assert resolved in server._watcher_tasks
    await asyncio.sleep(0.3)


async def _stop_real_watcher(root: Path) -> None:
    resolved = root.resolve()
    cleanup = server._stop_watcher(resolved)
    assert resolved not in server._watcher_tasks
    assert resolved not in server._watcher_stops
    if cleanup is not None:
        assert await asyncio.wait_for(
            asyncio.shield(cleanup),
            timeout=_E2E_TIMEOUT_SECONDS,
        )
    assert await server._wait_for_watcher_cleanup(
        resolved,
        timeout_seconds=_E2E_TIMEOUT_SECONDS,
    )
    assert resolved not in server._watcher_tasks
    assert resolved not in server._watcher_stops


def _assert_released(snapshot: JobSnapshot, slot: ProjectSlot) -> None:
    assert snapshot.runtime.task_active is False
    assert snapshot.runtime.worker_active is False
    assert snapshot.resources.index_capacity_held is False
    assert snapshot.resources.project_lease_held is False
    assert snapshot.resources.writer_lock_held is False
    assert snapshot.resources.pipeline_active is False
    assert slot.ref_count == 0
    # Encode-bearing jobs borrow the machine-wide encode admission slot;
    # the index partition must stay unborrowed either way.
    assert limiter_stats()["encode"] == {
        "total_tokens": 1,
        "borrowed_tokens": 0,
        "waiting": 0,
    }
    index_stats = limiter_stats()["index"]
    assert index_stats["borrowed_tokens"] == 0
    assert index_stats["waiting"] == 0


def _assert_restored_restart_state(
    manager: JobManager,
    *,
    queued_id: str,
    paused_id: str,
    interrupted_id: str,
) -> tuple[JobSnapshot, JobSnapshot, JobSnapshot]:
    queued = manager.get(queued_id)
    paused = manager.get(paused_id)
    interrupted = manager.get(interrupted_id)
    assert queued is not None
    assert queued.state in {JobState.RUNNING, JobState.SUCCEEDED}
    assert queued.desired_state is DesiredJobState.RUNNING
    assert queued.attempt.number == 1
    assert queued.id == queued_id
    assert paused is not None
    assert paused.state is JobState.PAUSED
    assert paused.desired_state is DesiredJobState.PAUSED
    assert paused.runtime.task_active is False
    assert paused.id == paused_id
    assert interrupted is not None
    assert interrupted.state is JobState.INTERRUPTED
    assert interrupted.runtime.task_active is False
    assert interrupted.runtime.worker_active is False
    return queued, paused, interrupted


async def _capture_running_restart_generation(
    manager: JobManager,
    registry: ServiceRegistry,
    interrupted: JobOutcome,
    root: Path,
    crash_state_path: Path,
) -> Path:
    """Persist one real blocked attempt, then safely release the old generation."""
    assert interrupted.job is not None
    state_path = manager.state_path
    assert state_path is not None
    slot = registry.peek_project(root)
    with registry.compute_lease(root) as lease:
        writer_lock = lease.runtime.vault_indexer._writer_lock
        assert writer_lock.acquire(blocking=False)
        cleanup_outcomes: list[JobOutcome] = []
        try:
            activated = await jobs.activate_index_job(
                interrupted,
                code_preflight=None,
                registry=registry,
            )
            assert activated.status is not JobOutcomeStatus.ERROR
            await _wait_for_job(
                manager,
                interrupted.job.id,
                lambda snapshot: (
                    snapshot.state is JobState.RUNNING
                    and snapshot.runtime.worker_active
                    and snapshot.resources.project_lease_held
                    and snapshot.resources.writer_lock_held
                ),
                "production attempt never reached the persisted writer boundary",
            )
            shutil.copyfile(state_path, crash_state_path)
        finally:
            try:
                for snapshot in manager.active():
                    cleanup_outcomes.append(
                        manager.set_desired_state(
                            snapshot.id,
                            DesiredJobState.CANCELLED,
                        )
                    )
            finally:
                writer_lock.release()
        for snapshot in manager.active():
            if snapshot.runtime.task_active:
                joined = await manager.wait_for_attempt(
                    snapshot.id,
                    timeout_seconds=_E2E_TIMEOUT_SECONDS,
                )
                assert joined.code == "attempt_released"
        assert all(
            outcome.status is not JobOutcomeStatus.ERROR for outcome in cleanup_outcomes
        )
    assert manager.active() == []
    released = manager.get(interrupted.job.id)
    assert released is not None
    _assert_released(released, slot)
    return state_path


async def _exercise_watcher_pause_coalescing(
    manager: JobManager,
    registry: ServiceRegistry,
    root: Path,
    slot: ProjectSlot,
) -> JobSnapshot:
    first_path = root / ".vault" / "adr" / "paused-first.md"
    second_path = root / ".vault" / "adr" / "paused-second.md"
    first_id: str | None = None
    running: JobSnapshot | None = None
    with registry.compute_lease(root) as lease:
        writer_lock = lease.runtime.vault_indexer._writer_lock
        assert writer_lock.acquire(blocking=False)
        try:
            first_id = _write_watched_document(first_path, root, "paused first")
            running = await _wait_for_watcher_job(
                manager,
                root,
                _watcher_attempt_owns_runtime,
                "watcher pause attempt never acquired production resources",
            )
            pause = manager.set_desired_state(running.id, DesiredJobState.PAUSED)
            assert pause.code == "pause_requested"
        finally:
            writer_lock.release()
    assert running is not None
    assert first_id is not None
    assert (
        await manager.wait_for_attempt(
            running.id,
            timeout_seconds=_E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    paused = manager.get(running.id)
    assert paused is not None
    assert paused.state is JobState.PAUSED
    _assert_released(paused, slot)
    assert slot.store.get_by_id(first_id) is None

    second_id = _write_watched_document(second_path, root, "paused second")
    await asyncio.sleep(0.5)
    nonterminal = [
        job for job in _watcher_jobs(manager, root) if not job.state.is_terminal
    ]
    assert [(job.id, job.state) for job in nonterminal] == [
        (paused.id, JobState.PAUSED)
    ]
    resume = manager.set_desired_state(paused.id, DesiredJobState.RUNNING)
    assert resume.code == "resume_requested"
    assert (
        await manager.wait_for_attempt(
            paused.id,
            timeout_seconds=_E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    succeeded = manager.get(paused.id)
    assert succeeded is not None
    assert succeeded.state is JobState.SUCCEEDED
    assert succeeded.attempt.number == 2
    _assert_released(succeeded, slot)
    assert slot.store.get_by_id(first_id) is not None
    assert slot.store.get_by_id(second_id) is not None
    return succeeded


async def _exercise_watcher_cancel_replacement(
    manager: JobManager,
    registry: ServiceRegistry,
    root: Path,
    slot: ProjectSlot,
    prior_job_id: str,
) -> JobSnapshot:
    third_path = root / ".vault" / "adr" / "cancelled-third.md"
    fourth_path = root / ".vault" / "adr" / "replacement-fourth.md"
    third_id: str | None = None
    running: JobSnapshot | None = None
    with registry.compute_lease(root) as lease:
        writer_lock = lease.runtime.vault_indexer._writer_lock
        assert writer_lock.acquire(blocking=False)
        try:
            third_id = _write_watched_document(third_path, root, "cancelled third")
            running = await _wait_for_watcher_job(
                manager,
                root,
                lambda snapshot: (
                    snapshot.id != prior_job_id
                    and _watcher_attempt_owns_runtime(snapshot)
                ),
                "watcher cancellation attempt never reached the writer boundary",
            )
            cancel = manager.set_desired_state(running.id, DesiredJobState.CANCELLED)
            assert cancel.code == "cancellation_requested"
        finally:
            writer_lock.release()
    assert running is not None
    assert third_id is not None
    assert (
        await manager.wait_for_attempt(
            running.id,
            timeout_seconds=_E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    cancelled = manager.get(running.id)
    assert cancelled is not None
    assert cancelled.state is JobState.CANCELLED
    assert cancelled.timestamps.finished_at is not None
    _assert_released(cancelled, slot)
    assert slot.store.get_by_id(third_id) is None

    fourth_id = _write_watched_document(fourth_path, root, "replacement fourth")
    replacement = await _wait_for_watcher_job(
        manager,
        root,
        lambda snapshot: (
            snapshot.id not in {cancelled.id, prior_job_id}
            and snapshot.state is JobState.SUCCEEDED
        ),
        "watcher did not schedule and finish replacement convergence",
    )
    assert replacement.timestamps.created_at >= cancelled.timestamps.finished_at + 0.8
    _assert_released(replacement, slot)
    assert slot.store.get_by_id(third_id) is not None
    assert slot.store.get_by_id(fourth_id) is not None
    return replacement


async def _pause_and_resume_large_job(
    manager: JobManager,
    slot: ProjectSlot,
    root: Path,
) -> None:
    """Pause and resume one publishing job through a released attempt."""
    job_id = jobs.start_reindex_vault(root, clean=False)
    live = await _wait_for_job(
        manager,
        job_id,
        lambda snapshot: (
            snapshot.state is JobState.RUNNING
            and snapshot.runtime.worker_active
            and snapshot.resources.writer_lock_held
            and slot.store.count() > 0
        ),
        "large vault job never published a durable slice",
    )
    pause = await _request_control_on_moving_job(
        manager,
        live,
        DesiredJobState.PAUSED,
    )
    assert pause.code == "pause_requested"
    assert (
        await manager.wait_for_attempt(
            job_id,
            timeout_seconds=_E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    paused = manager.get(job_id)
    assert paused is not None
    assert paused.state is JobState.PAUSED
    _assert_released(paused, slot)

    resume = manager.set_desired_state(
        job_id,
        DesiredJobState.RUNNING,
        expected_revision=paused.revision,
    )
    assert resume.code == "resume_requested"
    assert (
        await manager.wait_for_attempt(
            job_id,
            timeout_seconds=_E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    succeeded = manager.get(job_id)
    assert succeeded is not None
    assert succeeded.state is JobState.SUCCEEDED
    assert succeeded.attempt.number == 2
    assert succeeded.attempt.resumed_from_attempt == 1
    assert slot.store.count() >= 384
    _assert_released(succeeded, slot)


async def _cancel_large_job(
    manager: JobManager,
    registry: ServiceRegistry,
    slot: ProjectSlot,
    root: Path,
) -> None:
    """Cancel a writer-blocked job and assert its published state is absorbing."""
    _write_vault_corpus(root, start=384, count=192)
    before_ids = slot.store.get_all_ids()
    metadata_path = index_meta_path(root, PublicSourceType.VAULT)
    before_metadata = metadata_path.read_bytes()
    cancelled_id: str | None = None
    with registry.compute_lease(root) as lease:
        writer_lock = lease.runtime.vault_indexer._writer_lock
        writer_lock.acquire()
        try:
            cancelled_id = jobs.start_reindex_vault(root, clean=False)
            blocked = await _wait_for_job(
                manager,
                cancelled_id,
                lambda snapshot: (
                    snapshot.state is JobState.RUNNING
                    and snapshot.runtime.worker_active
                    and snapshot.resources.writer_lock_held
                ),
                "cancellation probe never reached the real writer boundary",
            )
            cancel = manager.set_desired_state(
                cancelled_id,
                DesiredJobState.CANCELLED,
                expected_revision=blocked.revision,
            )
            assert cancel.code == "cancellation_requested"
        finally:
            writer_lock.release()

    assert cancelled_id is not None
    assert (
        await manager.wait_for_attempt(
            cancelled_id,
            timeout_seconds=_E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    cancelled = manager.get(cancelled_id)
    assert cancelled is not None
    assert cancelled.state is JobState.CANCELLED
    _assert_released(cancelled, slot)
    after_ids = slot.store.get_all_ids()
    after_metadata = metadata_path.read_bytes()
    await asyncio.sleep(0.25)
    assert after_ids == before_ids
    assert after_metadata == before_metadata
    assert slot.store.get_all_ids() == after_ids
    assert metadata_path.read_bytes() == after_metadata
    replay = manager.set_desired_state(cancelled_id, DesiredJobState.CANCELLED)
    assert replay.code == "already_satisfied"


@pytest.mark.timeout(300)
async def test_large_corpus_pause_resume_cancel_releases_and_converges(
    tmp_path: Path,
    _e2e_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """Pause and resume one large job, then prove cancellation is absorbing."""
    registry, manager = _e2e_runtime
    root = tmp_path / "large-vault"
    _write_vault_corpus(root, start=0, count=384)
    slot = registry.peek_project(root)
    await _pause_and_resume_large_job(manager, slot, root)
    await _cancel_large_job(manager, registry, slot, root)


def _seed_restart_jobs(
    manager: JobManager,
    queued_root: Path,
    paused_root: Path,
    interrupted_root: Path,
) -> tuple[JobSnapshot, JobSnapshot, JobOutcome]:
    """Create queued, paused, and soon-interrupted durable restart intents."""
    queued = manager.create(
        _vault_job_spec(queued_root),
        _integration_initiator(queued_root, "restart queued probe"),
    )
    paused = manager.create(
        _vault_job_spec(paused_root),
        _integration_initiator(paused_root, "restart paused probe"),
        start_paused=True,
    )
    interrupted = manager.create(
        _vault_job_spec(interrupted_root),
        _integration_initiator(interrupted_root, "restart interrupted probe"),
    )
    assert queued.job is not None
    assert paused.job is not None
    assert interrupted.job is not None
    return queued.job, paused.job, interrupted


async def _complete_restored_queued_job(
    manager: JobManager,
    registry: ServiceRegistry,
    restored: JobSnapshot,
    root: Path,
) -> None:
    """Wait for restored queued work and assert released success."""
    assert (
        await manager.wait_for_attempt(
            restored.id,
            timeout_seconds=_E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    completed = manager.get(restored.id)
    assert completed is not None
    assert completed.state is JobState.SUCCEEDED
    _assert_released(completed, registry.peek_project(root))


async def _retry_restored_interruption(
    manager: JobManager,
    registry: ServiceRegistry,
    restored: JobSnapshot,
    root: Path,
) -> None:
    """Retry restored interrupted work and assert its durable parent link."""
    retry = manager.retry(
        restored.id,
        initiator=_integration_initiator(root, "restart retry probe"),
    )
    assert retry.code == "job_retry_created"
    assert retry.job is not None
    assert retry.job.attempt.parent_job_id == restored.id
    activated = await jobs.activate_index_job(
        retry,
        code_preflight=None,
        registry=registry,
    )
    assert activated.status is not JobOutcomeStatus.ERROR
    assert (
        await manager.wait_for_attempt(
            retry.job.id,
            timeout_seconds=_E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    completed = manager.get(retry.job.id)
    assert completed is not None
    assert completed.state is JobState.SUCCEEDED
    assert completed.attempt.parent_job_id == restored.id
    _assert_released(completed, registry.peek_project(root))


def _assert_restart_delete_and_pause(
    manager: JobManager,
    state_path: Path,
    restored_interrupted: JobSnapshot,
    restored_paused: JobSnapshot,
) -> None:
    """Assert deletion persistence and retained pause intent after restart."""
    deleted = manager.delete(restored_interrupted.id)
    assert deleted.code == "job_deleted"
    assert manager.get(restored_interrupted.id) is None
    still_paused = manager.get(restored_paused.id)
    assert still_paused is not None
    assert still_paused.state is JobState.PAUSED
    assert still_paused.desired_state is DesiredJobState.PAUSED
    observed_after_delete = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=3,
        state_path=state_path,
    )
    assert observed_after_delete.restore_persisted().code == "job_state_restored"
    assert observed_after_delete.get(restored_interrupted.id) is None
    durable_pause = observed_after_delete.get(restored_paused.id)
    assert durable_pause is not None
    assert durable_pause.state is JobState.PAUSED
    assert durable_pause.desired_state is DesiredJobState.PAUSED
    cancelled_pause = manager.set_desired_state(
        restored_paused.id,
        DesiredJobState.CANCELLED,
        expected_revision=still_paused.revision,
    )
    assert cancelled_pause.code == "job_cancelled"
    assert manager.active() == []


@pytest.mark.timeout(300)
async def test_restart_dispatches_queued_preserves_pause_and_links_retry(
    tmp_path: Path,
    _e2e_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """Restore durable intent, reconcile interruption, retry, and delete."""
    registry, seed_manager = _e2e_runtime
    queued_root = tmp_path / "restart-queued"
    paused_root = tmp_path / "restart-paused"
    interrupted_root = tmp_path / "restart-interrupted"
    for root, marker in (
        (queued_root, 1000),
        (paused_root, 2000),
        (interrupted_root, 3000),
    ):
        _write_vault_corpus(root, start=marker, count=8)

    crash_state_path = tmp_path / "running-generation.json"
    queued, paused, interrupted = _seed_restart_jobs(
        seed_manager,
        queued_root,
        paused_root,
        interrupted_root,
    )
    interrupted_job = interrupted.job
    assert interrupted_job is not None

    state_path = await _capture_running_restart_generation(
        seed_manager,
        registry,
        interrupted,
        interrupted_root,
        crash_state_path,
    )
    shutil.copyfile(crash_state_path, state_path)

    jobs.reset()
    restarted = jobs.get_job_manager()
    await server_lifespan._start_job_manager(restarted, registry)

    restored_queued, restored_paused, restored_interrupted = (
        _assert_restored_restart_state(
            restarted,
            queued_id=queued.id,
            paused_id=paused.id,
            interrupted_id=interrupted_job.id,
        )
    )
    await _complete_restored_queued_job(
        restarted,
        registry,
        restored_queued,
        queued_root,
    )
    await _retry_restored_interruption(
        restarted,
        registry,
        restored_interrupted,
        interrupted_root,
    )
    _assert_restart_delete_and_pause(
        restarted,
        state_path,
        restored_interrupted,
        restored_paused,
    )


@pytest.mark.timeout(300)
async def test_paused_code_job_rediscovers_current_corpus_before_resume(
    tmp_path: Path,
    _e2e_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """A paused admission must not freeze its code-discovery authority."""
    registry, manager = _e2e_runtime
    root = tmp_path / "paused-code-refresh"
    source_dir = root / "src"
    (root / ".vault").mkdir(parents=True)
    source_dir.mkdir()
    removed = source_dir / "removed_before_resume.py"
    added = source_dir / "added_before_resume.py"
    removed.write_text(
        "def removed_before_resume() -> str:\n    return 'stale'\n",
        encoding="utf-8",
    )

    preflight = jobs.validate_code_index_policy(root)
    created = manager.create(
        JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.CODE,
            project_root=str(root.resolve()),
            mode=JobMode.INCREMENTAL,
        ),
        _integration_initiator(root, "paused code discovery refresh"),
        start_paused=True,
    )
    assert created.job is not None
    activated = await jobs.activate_index_job(
        created,
        code_preflight=preflight,
        registry=registry,
    )
    assert activated.status is not JobOutcomeStatus.ERROR

    removed.unlink()
    added.write_text(
        "def added_before_resume() -> str:\n    return 'current'\n",
        encoding="utf-8",
    )
    paused = manager.get(created.job.id)
    assert paused is not None
    resumed = manager.set_desired_state(
        paused.id,
        DesiredJobState.RUNNING,
        expected_revision=paused.revision,
    )
    assert resumed.code == "resume_requested"
    assert (
        await manager.wait_for_attempt(
            paused.id,
            timeout_seconds=_E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"

    completed = manager.get(paused.id)
    assert completed is not None
    assert completed.state is JobState.SUCCEEDED
    assert completed.attempt.number == 2
    assert completed.attempt.resumed_from_attempt == 1
    slot = registry.peek_project(root)
    added_rel = str(added.relative_to(root)).replace("\\", "/")
    removed_rel = str(removed.relative_to(root)).replace("\\", "/")
    with registry.compute_lease(root) as lease:
        assert lease.runtime.code_indexer._get_chunk_ids_for_files({added_rel})
        assert not lease.runtime.code_indexer._get_chunk_ids_for_files({removed_rel})
    _assert_released(completed, slot)


@pytest.mark.timeout(300)
async def test_watcher_coalesces_replaces_stops_and_closes_store_safely(
    tmp_path: Path,
    _e2e_runtime: tuple[ServiceRegistry, JobManager],
) -> None:
    """Drive pause, replacement, explicit stop, and safe store closure."""
    registry, manager = _e2e_runtime
    root = (tmp_path / "watcher-shutdown").resolve()
    (root / ".vault").mkdir(parents=True)
    slot = registry.peek_project(root)

    await _start_real_watcher(root)
    paused_generation = await _exercise_watcher_pause_coalescing(
        manager,
        registry,
        root,
        slot,
    )
    replacement = await _exercise_watcher_cancel_replacement(
        manager,
        registry,
        root,
        slot,
        paused_generation.id,
    )
    assert replacement.id != paused_generation.id
    assert root in server._watcher_tasks

    await _stop_real_watcher(root)
    assert manager.active() == []
    assert slot.ref_count == 0
    registry.close_project(root)
    health = registry.health()
    assert health["project_count"] == 0
    assert str(root) not in health["projects"]


def _create_operator_matrix_job(port: int, project_root: Path) -> tuple[str, int]:
    """Create one paused job for the cross-surface operator matrix."""
    created = _try_http_create_job(
        JobSource.VAULT,
        str(project_root),
        port,
        start_paused=True,
        idempotency_key="e2e-operator-matrix",
        timeout=5.0,
    )
    assert created is not None
    assert created["code"] == "job_created"
    created_job = cast("dict[str, object]", created["job"])
    return cast("str", created_job["id"]), cast("int", created_job["revision"])


def _assert_operator_matrix_lookup(port: int, job_id: str) -> None:
    """Assert typed and CLI lookup agree on exact-ID semantics."""
    detail = _try_http_get_job(job_id, port, timeout=5.0)
    assert detail is not None
    assert detail["ok"] is True
    detail_job = cast("dict[str, object]", detail["job"])
    assert detail_job["id"] == job_id
    exit_code, shown = _invoke_job_json("show", job_id, "--port", str(port))
    assert exit_code == 0
    assert shown["ok"] is True
    exit_code, prefix_rejected = _invoke_job_json(
        "show", job_id[:8], "--port", str(port)
    )
    assert exit_code == 1
    assert prefix_rejected["error"] == "job_not_found"


def _assert_operator_matrix_conflicts(port: int, job_id: str, revision: int) -> None:
    """Assert revision replay, active-delete, and force-stop outcomes."""
    stale = _try_http_set_job_desired_state(
        job_id,
        DesiredJobState.RUNNING,
        port,
        expected_revision=revision + 100,
        timeout=5.0,
    )
    assert stale is not None
    assert stale["ok"] is False
    assert stale["error"] == "revision_conflict"
    replay = _try_http_set_job_desired_state(
        job_id,
        DesiredJobState.PAUSED,
        port,
        expected_revision=revision + 100,
        timeout=5.0,
    )
    assert replay is not None
    assert replay["ok"] is True
    assert replay["code"] == "already_satisfied"
    active_delete = _try_http_delete_job(job_id, port, timeout=5.0)
    assert active_delete is not None
    assert active_delete["ok"] is False
    assert active_delete["error"] == "job_not_terminal"
    exit_code, force_rejected = _invoke_job_json(
        "stop", job_id, "--port", str(port), "--force"
    )
    assert exit_code == 1
    assert force_rejected["error"] == "force_termination_unavailable"


def _complete_operator_matrix(port: int, job_id: str) -> None:
    """Cancel through the CLI and delete through typed transport."""
    exit_code, stopped = _invoke_job_json("stop", job_id, "--port", str(port))
    assert exit_code == 0
    assert stopped["ok"] is True
    stopped_data = cast("dict[str, object]", stopped["data"])
    assert stopped_data["status"] == "job_cancelled"
    deleted = _try_http_delete_job(job_id, port, timeout=5.0)
    assert deleted is not None
    assert deleted["ok"] is True
    assert deleted["code"] == "job_deleted"


def test_http_transport_and_cli_outcome_matrix_uses_exact_job_ids(
    tmp_path: Path,
) -> None:
    """Cross HTTP, typed transport, and CLI with one exact job resource."""
    project_root = tmp_path / "operator-matrix"
    (project_root / ".vault").mkdir(parents=True)
    with _real_job_control_server(tmp_path) as port:
        job_id, revision = _create_operator_matrix_job(port, project_root)
        _assert_operator_matrix_lookup(port, job_id)
        _assert_operator_matrix_conflicts(port, job_id, revision)
        _complete_operator_matrix(port, job_id)
