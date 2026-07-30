"""CPU-only evidence for registry-owned durable quiesce recovery."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import pytest

from ..job_manager.manager import JobManager
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ..job_persistence import load_persisted_state
from ..service import ServiceRegistry
from ..service_quiesce import QuiesceState, QuiesceTransition, QuiesceTransitionCode
from ._job_roots import _TEST_PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _registry_with_quiesced_job(
    state_path: Path,
) -> tuple[ServiceRegistry, JobManager, str]:
    registry = ServiceRegistry()
    manager = JobManager(
        max_nonterminal=1,
        state_path=state_path,
        quiesce_controller=registry._quiesce_controller,
    )
    registry._job_manager = manager
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        ),
        JobInitiator("test", "registry-durable-recovery", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    job_id = created.job.id
    assert (
        manager.defer_unstarted_for_quiesce(job_id).code
        == "quiesce_deferred_before_start"
    )
    assert registry.quiesce_resources(timeout_seconds=0).achieved
    return registry, manager, job_id


def test_registry_persists_same_id_recovery_before_reopening_admission(
    tmp_path: Path,
) -> None:
    """A running registry is backed by the durable queued recovery record."""
    state_path = tmp_path / "managed" / "jobs.json"
    registry, manager, job_id = _registry_with_quiesced_job(state_path)

    resumed = registry.resume_resources(timeout_seconds=0)

    assert resumed.code is QuiesceTransitionCode.RUNNING
    assert resumed.snapshot.state is QuiesceState.RUNNING
    persisted = load_persisted_state(state_path)
    assert len(persisted.jobs) == 1
    recovered = persisted.jobs[0]
    assert recovered.id == job_id
    assert recovered.state is JobState.QUEUED
    assert recovered.desired_state is DesiredJobState.RUNNING
    assert recovered.attempt.number == 2
    in_memory = manager.get(job_id)
    assert in_memory is not None
    assert in_memory == recovered


def test_registry_reports_unpublished_recovery_without_reopening_admission(
    tmp_path: Path,
) -> None:
    """A real state-path failure is explicit and leaves warming closed."""
    state_path = tmp_path / "managed" / "jobs.json"
    registry, manager, job_id = _registry_with_quiesced_job(state_path)
    state_path.unlink()
    state_path.parent.rmdir()
    state_path.parent.write_text("not a directory", encoding="utf-8")

    failed = registry.resume_resources(timeout_seconds=0)

    assert failed.code is QuiesceTransitionCode.RESUME_RECOVERY_FAILED
    assert not failed.achieved
    assert failed.snapshot.state is QuiesceState.WARMING
    assert not failed.snapshot.admissions_open
    assert not failed.snapshot.vram_released
    assert not failed.snapshot.safe_to_borrow_gpu
    assert failed.snapshot.failure_reason == "job_resume_persistence_unpublished"
    retained = manager.get(job_id)
    assert retained is not None
    assert retained.state is JobState.PAUSED
    assert retained.desired_state is DesiredJobState.RUNNING


def test_registry_concurrent_resume_coalesces_one_recovery_preparation(
    tmp_path: Path,
) -> None:
    """Two callers share one durable same-ID recovery transition."""
    state_path = tmp_path / "managed" / "jobs.json"
    registry, manager, job_id = _registry_with_quiesced_job(state_path)
    launch = threading.Barrier(3)
    outcomes: list[QuiesceTransition] = []

    def resume() -> None:
        launch.wait(timeout=5.0)
        outcomes.append(registry.resume_resources(timeout_seconds=5))

    assert registry.gpu_lock.acquire(timeout=5.0)
    first = threading.Thread(target=resume, name="registry-recovery-1")
    second = threading.Thread(target=resume, name="registry-recovery-2")
    first.start()
    second.start()
    launch.wait(timeout=5.0)
    deadline = time.monotonic() + 5.0
    try:
        while registry._quiesce_controller.snapshot().state is not QuiesceState.WARMING:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        registry.gpu_lock.release()
        for worker in (first, second):
            worker.join(timeout=5.0)
    finally:
        if registry.gpu_lock.locked():
            registry.gpu_lock.release()
        for worker in (first, second):
            worker.join(timeout=5.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(outcomes) == 2
    assert outcomes[0] is outcomes[1]
    assert outcomes[0].code is QuiesceTransitionCode.RUNNING
    persisted = load_persisted_state(state_path)
    assert len(persisted.jobs) == 1
    assert persisted.jobs[0].id == job_id
    assert persisted.jobs[0].state is JobState.QUEUED
    assert persisted.jobs[0].attempt.number == 2
    retained = manager.get(job_id)
    assert retained is not None
    assert retained == persisted.jobs[0]
