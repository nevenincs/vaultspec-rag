"""Retry lineage resolution and rejection observability for the job manager."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from ..job_control import RunControlToken
from ..job_manager._control import AttemptTerminal
from ..job_manager.manager import JobManager
from ..job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ..service_quiesce import ServiceQuiesceController
from ._job_manager_transition_helpers import pending_attempt
from ._job_roots import _TEST_PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_JOBS_LOGGER = "vaultspec_rag.jobs"


def _spec(source: JobSource = JobSource.CODE) -> JobSpec:
    return JobSpec(JobOperation.INDEX, source, _TEST_PROJECT_ROOT, JobMode.INCREMENTAL)


def _initiator(kind: str = "cli", command: str = "server job create") -> JobInitiator:
    return JobInitiator(kind, command, _TEST_PROJECT_ROOT)


def _create(manager: JobManager, source: JobSource = JobSource.CODE) -> str:
    created = manager.create(_spec(source), _initiator())
    assert created.code == "job_created"
    assert created.job is not None
    return created.job.id


async def _finish(
    manager: JobManager,
    job_id: str,
    state: JobState,
    *,
    result: str | None = None,
    error_kind: str | None = None,
) -> None:
    """Drive one queued job through a started attempt into a terminal state."""
    task = asyncio.create_task(pending_attempt())
    try:
        started = manager.start_attempt(job_id, task=task, control=RunControlToken())
        assert started.code == "attempt_started"
        finished = manager.finish_attempt(
            job_id,
            AttemptTerminal(
                attempt=1,
                task=task,
                state=state,
                result=result,
                error_kind=error_kind,
            ),
        )
        assert finished.code == "job_finished"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def _retry_child(manager: JobManager, parent_id: str) -> str:
    retried = manager.retry(parent_id)
    assert retried.code == "job_retry_created"
    assert retried.job is not None
    assert retried.job.attempt.parent_job_id == parent_id
    return retried.job.id


@pytest.mark.asyncio
async def test_successful_retry_supersedes_interrupted_parent() -> None:
    """A parent whose linked retry succeeded resolves to superseded.

    Guard proof: with the ancestry-resolution call in ``finish_attempt``
    disabled, this failed on the ``JobState.SUPERSEDED`` assertion (the parent
    stayed interrupted and retryable); with it restored the test passes.
    """
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=None,
    )
    parent_id = _create(manager)
    await _finish(
        manager,
        parent_id,
        JobState.INTERRUPTED,
        result="service died mid-run",
        error_kind="interrupted",
    )
    parent = manager.get(parent_id)
    assert parent is not None
    assert parent.capabilities.retryable is True
    parent_finished_at = parent.timestamps.finished_at

    child_id = _retry_child(manager, parent_id)
    await _finish(manager, child_id, JobState.SUCCEEDED, result="ok")

    resolved = manager.get(parent_id)
    assert resolved is not None
    assert resolved.state is JobState.SUPERSEDED
    assert resolved.capabilities.retryable is False
    assert resolved.capabilities.deletable is True
    # Resolution preserves history: the record keeps its original finish clock.
    assert resolved.timestamps.finished_at == parent_finished_at

    rejected = manager.retry(parent_id)
    assert rejected.code == "job_not_retryable"
    assert rejected.message.startswith("A linked retry already succeeded")

    assert manager.delete(parent_id).code == "job_deleted"


@pytest.mark.asyncio
async def test_failed_retry_leaves_parent_retryable() -> None:
    """A retry that fails resolves nothing, and the next retry is admitted.

    The second half is the outage guard: resolving parents must never make a
    legitimate follow-up retry read as duplicate active work.

    Guard proof: with the ``JobState.SUCCEEDED`` condition on ancestry
    resolution removed (resolving on any terminal child state), this failed on
    the ``JobState.INTERRUPTED`` assertion below; with the condition restored
    the test passes.
    """
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=None,
    )
    parent_id = _create(manager)
    await _finish(manager, parent_id, JobState.INTERRUPTED, error_kind="interrupted")

    child_id = _retry_child(manager, parent_id)
    await _finish(manager, child_id, JobState.FAILED, result="encode failed")

    parent = manager.get(parent_id)
    assert parent is not None
    assert parent.state is JobState.INTERRUPTED
    assert parent.capabilities.retryable is True

    second_child = manager.retry(parent_id)
    assert second_child.code == "job_retry_created"


@pytest.mark.asyncio
async def test_chained_retries_resolve_every_ancestor() -> None:
    """One eventual success settles the whole retry lineage."""
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=None,
    )
    parent_id = _create(manager)
    await _finish(manager, parent_id, JobState.INTERRUPTED, error_kind="interrupted")

    first_id = _retry_child(manager, parent_id)
    await _finish(manager, first_id, JobState.FAILED, result="encode failed")

    second_id = _retry_child(manager, first_id)
    await _finish(manager, second_id, JobState.SUCCEEDED, result="ok")

    for ancestor_id in (parent_id, first_id):
        ancestor = manager.get(ancestor_id)
        assert ancestor is not None
        assert ancestor.state is JobState.SUPERSEDED
        assert ancestor.capabilities.retryable is False
    settled = manager.get(second_id)
    assert settled is not None
    assert settled.state is JobState.SUCCEEDED


@pytest.mark.asyncio
async def test_retry_with_equivalent_active_child_logs_the_rejection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retrying while the linked retry is still active leaves a log trace.

    This is the operator-reported loop: the UI accepts the retry, the manager
    rejects it, and before this nothing recorded why.

    Guard proof: with the ``_log_rejection`` call on the ``active_job_exists``
    branch removed, this failed on the empty ``rejections`` assertion; with it
    restored the test passes.
    """
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=None,
    )
    parent_id = _create(manager)
    await _finish(manager, parent_id, JobState.INTERRUPTED, error_kind="interrupted")
    child_id = _retry_child(manager, parent_id)

    with caplog.at_level(logging.WARNING, logger=_JOBS_LOGGER):
        rejected = manager.retry(parent_id)
    assert rejected.code == "active_job_exists"
    rejections = [
        record.getMessage()
        for record in caplog.records
        if "event=rejected" in record.getMessage()
    ]
    assert len(rejections) == 1
    message = rejections[0]
    assert "command=retry" in message
    assert "code=active_job_exists" in message
    assert f"job_id={parent_id}" in message
    assert f"equivalent_job_id={child_id}" in message


@pytest.mark.asyncio
async def test_rejected_retry_of_succeeded_job_logs_code_target_and_initiator(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every retry rejection logs its exact code, target, and requester.

    Guard proof: with the ``_log_rejection`` call inside ``_error`` removed,
    this failed on the empty ``rejections`` assertion; with it restored the
    test passes.
    """
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=None,
    )
    job_id = _create(manager)
    await _finish(manager, job_id, JobState.SUCCEEDED, result="ok")

    requester = JobInitiator("mcp", "retry_job", _TEST_PROJECT_ROOT)
    with caplog.at_level(logging.WARNING, logger=_JOBS_LOGGER):
        rejected = manager.retry(job_id, initiator=requester)
    assert rejected.code == "job_not_retryable"
    assert rejected.message.startswith("Succeeded jobs are recreated")
    rejections = [
        record for record in caplog.records if "event=rejected" in record.getMessage()
    ]
    assert len(rejections) == 1
    assert rejections[0].levelno == logging.WARNING
    message = rejections[0].getMessage()
    assert "command=retry" in message
    assert "code=job_not_retryable" in message
    assert f"job_id={job_id}" in message
    assert "initiator_kind=mcp" in message
    assert "initiator_command=retry_job" in message


@pytest.mark.asyncio
async def test_rejected_retry_of_unknown_job_logs_the_requested_target(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A rejection with no job resource still names the id the caller sent.

    Guard proof: with the ``job_id`` attribution dropped from the missing
    retry-target branch, this failed on the ``job_id=`` assertion; with it
    restored the test passes.
    """
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=None,
    )
    with caplog.at_level(logging.WARNING, logger=_JOBS_LOGGER):
        rejected = manager.retry("no-such-job")
    assert rejected.code == "job_not_found"
    rejections = [
        record.getMessage()
        for record in caplog.records
        if "event=rejected" in record.getMessage()
    ]
    assert len(rejections) == 1
    assert "command=retry" in rejections[0]
    assert "code=job_not_found" in rejections[0]
    assert "job_id=no-such-job" in rejections[0]


@pytest.mark.asyncio
async def test_resolution_logs_a_superseded_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Resolving a parent is a lifecycle fact and shows up in the service log."""
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=None,
    )
    parent_id = _create(manager)
    await _finish(manager, parent_id, JobState.INTERRUPTED, error_kind="interrupted")
    child_id = _retry_child(manager, parent_id)
    with caplog.at_level(logging.INFO, logger=_JOBS_LOGGER):
        await _finish(manager, child_id, JobState.SUCCEEDED, result="ok")
    superseded = [
        record.getMessage()
        for record in caplog.records
        if "event=superseded" in record.getMessage()
    ]
    assert len(superseded) == 1
    assert f"job_id={parent_id}" in superseded[0]
    assert f"resolved_by={child_id}" in superseded[0]


@pytest.mark.asyncio
async def test_superseded_parent_round_trips_persistence(tmp_path: Path) -> None:
    """A resolved parent restores as superseded, still not retryable.

    This also proves the resolution transition keeps the persisted clock
    contract (the finish stamp is the final state change): a violated
    invariant fails restore validation, not this assertion set.
    """
    state_path = tmp_path / "jobs-state.json"
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=state_path,
    )
    parent_id = _create(manager)
    await _finish(manager, parent_id, JobState.INTERRUPTED, error_kind="interrupted")
    child_id = _retry_child(manager, parent_id)
    await _finish(manager, child_id, JobState.SUCCEEDED, result="ok")

    restored = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=state_path,
    )
    outcome = restored.restore_persisted()
    assert outcome.code == "job_state_restored"
    parent = restored.get(parent_id)
    assert parent is not None
    assert parent.state is JobState.SUPERSEDED
    assert parent.capabilities.retryable is False
