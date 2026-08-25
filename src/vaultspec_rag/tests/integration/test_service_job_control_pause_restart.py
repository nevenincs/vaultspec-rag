"""Pause, cancellation, and restart scenarios over production components.

Every scenario here drives one real job manager against a real store and
a real writer lock. The control requests are the ones an operator makes -
pause a publishing job, cancel a blocked one, restart the service and
reconcile what survived - and each closes by asserting the attempt let go
of everything it borrowed.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import TYPE_CHECKING

import pytest

from ... import _job_admission, jobs
from ..._index_breadth import index_meta_path
from ..._source_types import PublicSourceType
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
from ...server import _lifespan as server_lifespan
from ...service_quiesce import ServiceQuiesceController
from ._service_job_control_e2e_support import (
    E2E_POLL_SECONDS,
    E2E_TIMEOUT_SECONDS,
    assert_released,
)
from ._service_job_control_e2e_support import _e2e_runtime as _e2e_runtime_fixture

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ...job_models import JobOutcome, JobSnapshot
    from ...service import ProjectSlot, ServiceRegistry

pytestmark = pytest.mark.integration

__all__ = ["_e2e_runtime_fixture"]


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


async def _wait_for_job(
    manager: JobManager,
    job_id: str,
    predicate: Callable[[JobSnapshot], bool],
    description: str,
) -> JobSnapshot:
    deadline = asyncio.get_running_loop().time() + E2E_TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        snapshot = manager.get(job_id)
        if snapshot is not None and predicate(snapshot):
            return snapshot
        await asyncio.sleep(E2E_POLL_SECONDS)
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
    deadline = asyncio.get_running_loop().time() + E2E_TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        outcome = manager.set_desired_state(
            observed.id,
            desired_state,
            expected_revision=observed.revision,
        )
        if outcome.code != "revision_conflict":
            return outcome
        await asyncio.sleep(E2E_POLL_SECONDS)
        refreshed = manager.get(observed.id)
        assert refreshed is not None
        observed = refreshed
    raise AssertionError(
        f"{desired_state} never won the revision race for {observed.id}; "
        f"last snapshot={manager.get(observed.id)!r}"
    )


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
            timeout_seconds=E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    paused = manager.get(job_id)
    assert paused is not None
    assert paused.state is JobState.PAUSED
    assert_released(paused, slot)

    resume = manager.set_desired_state(
        job_id,
        DesiredJobState.RUNNING,
        expected_revision=paused.revision,
    )
    assert resume.code == "resume_requested"
    assert (
        await manager.wait_for_attempt(
            job_id,
            timeout_seconds=E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    succeeded = manager.get(job_id)
    assert succeeded is not None
    assert succeeded.state is JobState.SUCCEEDED
    assert succeeded.attempt.number == 2
    assert succeeded.attempt.resumed_from_attempt == 1
    assert slot.store.count() >= 384
    assert_released(succeeded, slot)


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
            timeout_seconds=E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    cancelled = manager.get(cancelled_id)
    assert cancelled is not None
    assert cancelled.state is JobState.CANCELLED
    assert_released(cancelled, slot)
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
                    timeout_seconds=E2E_TIMEOUT_SECONDS,
                )
                assert joined.code == "attempt_released"
        assert all(
            outcome.status is not JobOutcomeStatus.ERROR for outcome in cleanup_outcomes
        )
    assert manager.active() == []
    released = manager.get(interrupted.job.id)
    assert released is not None
    assert_released(released, slot)
    return state_path


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
            timeout_seconds=E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    completed = manager.get(restored.id)
    assert completed is not None
    assert completed.state is JobState.SUCCEEDED
    assert_released(completed, registry.peek_project(root))


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
            timeout_seconds=E2E_TIMEOUT_SECONDS,
        )
    ).code == "attempt_released"
    completed = manager.get(retry.job.id)
    assert completed is not None
    assert completed.state is JobState.SUCCEEDED
    assert completed.attempt.parent_job_id == restored.id
    assert_released(completed, registry.peek_project(root))


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

    preflight = _job_admission.validate_code_index_policy(root)
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
            timeout_seconds=E2E_TIMEOUT_SECONDS,
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
    assert_released(completed, slot)
