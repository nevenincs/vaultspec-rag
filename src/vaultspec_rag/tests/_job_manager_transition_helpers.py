"""Concrete state-transition setup shared by transition behavior tests."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ..job_control import PauseRequested, RunControlToken
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)

_TEST_PROJECT_ROOT = os.path.abspath(os.path.join(os.sep, "project"))

if TYPE_CHECKING:
    import asyncio

    from ..job_manager.manager import JobManager


def create_paused_vault_job(manager: JobManager) -> str:
    spec = JobSpec(
        JobOperation.INDEX,
        JobSource.VAULT,
        _TEST_PROJECT_ROOT,
        JobMode.INCREMENTAL,
    )
    initiator = JobInitiator("cli", "server job create", _TEST_PROJECT_ROOT)
    created = manager.create(spec, initiator)
    assert created.job is not None
    job_id = created.job.id

    stale_change = manager.set_desired_state(
        job_id,
        DesiredJobState.PAUSED,
        expected_revision=0,
    )
    assert stale_change.code == "revision_conflict"

    paused = manager.set_desired_state(
        job_id,
        DesiredJobState.PAUSED,
        expected_revision=1,
    )
    assert paused.job is not None
    assert paused.job.state is JobState.PAUSED
    assert paused.job.revision == 2
    replay = manager.set_desired_state(
        job_id,
        DesiredJobState.PAUSED,
        expected_revision=1,
    )
    assert replay.code == "already_satisfied"
    conflict = manager.set_desired_state(
        job_id,
        DesiredJobState.RUNNING,
        expected_revision=1,
    )
    assert conflict.code == "revision_conflict"
    return job_id


def resume_paused_job(manager: JobManager, job_id: str) -> None:
    resumed = manager.set_desired_state(
        job_id,
        DesiredJobState.RUNNING,
        expected_revision=2,
    )
    assert resumed.job is not None
    assert resumed.job.attempt.number == 2
    assert resumed.job.state is JobState.QUEUED


def assert_delivered_pause_requeues_resume(
    manager: JobManager,
    job_id: str,
    task: asyncio.Task[object],
    control: RunControlToken,
) -> None:
    started = manager.start_attempt(job_id, task=task, control=control)
    assert started.job is not None
    assert started.job.state is JobState.RUNNING
    pause = manager.set_desired_state(job_id, DesiredJobState.PAUSED)
    assert pause.code == "pause_requested"
    with pytest.raises(PauseRequested):
        control.checkpoint()

    committed_resume = manager.set_desired_state(job_id, DesiredJobState.RUNNING)
    assert committed_resume.job is not None
    assert committed_resume.job.state is JobState.PAUSING
    assert committed_resume.job.desired_state is DesiredJobState.RUNNING

    acknowledged = manager.acknowledge_control(
        job_id,
        attempt=2,
        task=task,
    )
    assert acknowledged.code == "resume_requeued"
    assert acknowledged.job is not None
    assert acknowledged.job.state is JobState.QUEUED
    assert acknowledged.job.attempt.number == 3
    stale = manager.acknowledge_control(job_id, attempt=2, task=task)
    assert stale.code == "stale_attempt_ignored"
