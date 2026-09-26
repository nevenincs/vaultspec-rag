"""Queued work that nothing will ever start must degrade service health.

Queued work is dispatched the moment it is queued, and no attempt owns a job
until that dispatch moves it to running, so a queued job is normally a
sub-second state. When a dispatch fails without failing or deferring the job,
nothing is left to start it: every later request for the same scope can join
it, and the source is never indexed again. Health reported ready through
exactly that for 45 hours, because queued work was treated as intentionally
inert.

The manager answers which queued work nothing is holding for a reopening
dispatch; health counts what has waited past the stall threshold. Both are
driven for real: a real manager, opened through its startup verbs, holding a
job created by the production ``create`` and never dispatched.

MUTATION PROOF, each run alone in one uninterrupted sequence and restored
before the next:

- dropping the queued-state condition from ``JobManager.undispatched`` fails
  ``test_an_attempt_that_owns_the_job_clears_it`` on its empty-listing
  assertion;
- dropping the lifecycle check fails
  ``test_nothing_is_listed_once_shutdown_begins`` on its empty-listing
  assertion;
- dropping the admission check fails
  ``test_nothing_is_listed_while_quiesce_holds_admission`` on its empty-listing
  assertion;
- dropping the startup-restore check fails
  ``test_nothing_is_listed_before_startup_restore_completes`` on its second
  empty-listing assertion;
- dropping the ``JOBS_UNDISPATCHED`` degradation from ``_jobs_health`` fails
  ``test_queued_work_past_the_threshold_degrades_health`` on its reason
  assertion;
- replacing the age comparison with ``True`` fails
  ``test_queued_work_inside_the_threshold_leaves_health_clean`` on its
  rollup-count assertion.

Each restored file passes.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from .._job_errors import STALL_THRESHOLD_SECONDS
from ..indexer._run_ledger_models import RunAuthority
from ..job_control import RunControlToken
from ..job_manager.manager import JobManager
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSnapshot,
    JobSource,
    JobSpec,
    JobState,
)
from ..jobs import get_job_manager, reset
from ..operator_state._service import DegradationReason
from ..server._lifespan import _jobs_health
from ..service_quiesce import ServiceQuiesceController
from ._job_manager_transition_helpers import pending_attempt
from ._job_roots import _TEST_PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..operator_state._models import Degradation

pytestmark = [pytest.mark.unit]


def _in_memory(controller: ServiceQuiesceController | None = None) -> JobManager:
    """A manager that persists nothing, so no test touches a real status dir."""
    return JobManager(
        quiesce_controller=controller or ServiceQuiesceController(),
        state_path=None,
    )


def _open(manager: JobManager) -> JobManager:
    """Bring a manager through the startup verbs a service life runs."""
    manager.prepare_startup()
    manager.complete_startup()
    return manager


def _queue(manager: JobManager) -> JobSnapshot:
    """Create one queued job and dispatch nothing for it."""
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            _TEST_PROJECT_ROOT,
            JobMode.INCREMENTAL,
            RunAuthority.PUBLICATION,
        ),
        JobInitiator("cli", "undispatched coverage", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    assert created.job.state is JobState.QUEUED
    return created.job


def _listed(manager: JobManager) -> list[str]:
    return [snapshot.id for snapshot in manager.undispatched()]


def _undispatched_reasons(reasons: list[Degradation]) -> list[Degradation]:
    return [
        reason
        for reason in reasons
        if reason.reason is DegradationReason.JOBS_UNDISPATCHED
    ]


class TestManagerListsQueuedWorkNothingOwns:
    """Only queued work that should run and that nothing will start is listed."""

    def test_queued_work_nothing_dispatched_is_listed(self) -> None:
        manager = _open(_in_memory())
        queued = _queue(manager)

        assert _listed(manager) == [queued.id]

    @pytest.mark.asyncio
    async def test_an_attempt_that_owns_the_job_clears_it(self) -> None:
        manager = _open(_in_memory())
        queued = _queue(manager)
        assert _listed(manager) == [queued.id]

        task = asyncio.create_task(pending_attempt())
        try:
            started = manager.start_attempt(
                queued.id,
                task=task,
                control=RunControlToken(),
            )
            assert started.code == "attempt_started"

            assert _listed(manager) == []
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    def test_paused_work_is_not_listed(self) -> None:
        manager = _open(_in_memory())
        queued = _queue(manager)
        paused = manager.set_desired_state(queued.id, DesiredJobState.PAUSED)
        assert paused.job is not None
        assert paused.job.state is JobState.PAUSED

        assert _listed(manager) == []

    def test_nothing_is_listed_while_quiesce_holds_admission(self) -> None:
        controller = ServiceQuiesceController()
        manager = _open(_in_memory(controller))
        queued = _queue(manager)
        assert _listed(manager) == [queued.id]

        controller.begin_pause()

        # The quiesce resume dispatches held work when admission reopens, so
        # the job has an owner in waiting and is not stranded.
        assert _listed(manager) == []

    def test_nothing_is_listed_before_startup_restore_completes(self) -> None:
        manager = _in_memory()
        _queue(manager)
        assert _listed(manager) == []

        manager.prepare_startup()
        # Startup restore dispatches every durably queued job once it
        # completes, so until then queued work is still owned by startup.
        assert _listed(manager) == []

        manager.complete_startup()
        assert len(_listed(manager)) == 1

    def test_nothing_is_listed_once_shutdown_begins(self) -> None:
        manager = _open(_in_memory())
        queued = _queue(manager)
        assert _listed(manager) == [queued.id]

        manager.begin_shutdown()

        assert _listed(manager) == []


@pytest.fixture
def queued_process_job(isolated_status_dir: Path) -> Generator[JobSnapshot]:
    """Queue one undispatched job on the process manager health reads."""
    del isolated_status_dir
    reset()
    try:
        yield _queue(_open(get_job_manager()))
    finally:
        reset()


class TestHealthFlagsQueuedWorkNothingStarts:
    """Health degrades once undispatched work outlives the stall threshold."""

    def test_queued_work_past_the_threshold_degrades_health(
        self,
        queued_process_job: JobSnapshot,
    ) -> None:
        queued_at = queued_process_job.timestamps.state_changed_at

        jobs_health, reasons = _jobs_health(now=queued_at + STALL_THRESHOLD_SECONDS)

        assert jobs_health["undispatched"] == 1
        flagged = _undispatched_reasons(reasons)
        assert [reason.detail for reason in flagged] == [
            "1 queued indexing job(s) have nothing to start them"
        ]

    def test_queued_work_inside_the_threshold_leaves_health_clean(
        self,
        queued_process_job: JobSnapshot,
    ) -> None:
        queued_at = queued_process_job.timestamps.state_changed_at

        jobs_health, reasons = _jobs_health(
            now=queued_at + STALL_THRESHOLD_SECONDS - 1.0
        )

        # The job must reach the rollup, or the clean verdict below could mean
        # no queued work was ever considered.
        assert jobs_health["queued"] == 1
        assert jobs_health["undispatched"] == 0
        assert _undispatched_reasons(reasons) == []
