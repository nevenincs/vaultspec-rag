"""Cohesive unit coverage for job-management behavior."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest

from ..job_control import RunControlToken
from ..job_manager.manager import JobManager
from ..job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)

if TYPE_CHECKING:
    from pathlib import Path
from ..jobs import (
    index_job_status,
    reset,
    snapshot,
)
from ._jobs_restore_helpers import job_recorded_by_a_now_dead_process

pytestmark = [pytest.mark.unit]


class TestInterruptedJobDegradationSplit:
    """An interrupted run degrades the project index view, never health.

    The two surfaces answer different questions and their degrading state sets
    differ because of it. Nothing else pins that difference, so a change to
    either selector would otherwise pass silently as a tidy-up; both directions
    are asserted here so the split reads as a decision rather than an oversight.
    """

    @pytest.mark.asyncio
    async def test_an_interrupted_run_degrades_the_project_index_status(
        self,
        tmp_path: Path,
    ) -> None:
        """The index that run was building is incomplete, so it must be flagged.

        The interruption is produced the way a daemon death produces it: a
        started attempt is persisted, and a fresh manager restores that state
        and finds an attempt no live worker owns. No state is hand-written.
        """
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(max_nonterminal=2, state_path=state_path)
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                str(tmp_path),
                JobMode.INCREMENTAL,
            ),
            JobInitiator("service", "degradation split coverage", str(tmp_path)),
        )
        assert created.job is not None
        task = asyncio.create_task(asyncio.Event().wait())
        try:
            started = manager.start_attempt(
                created.job.id,
                task=task,
                control=RunControlToken(),
            )
            assert started.job is not None
            assert started.job.state is JobState.RUNNING

            restarted = JobManager(max_nonterminal=2, state_path=state_path)
            assert restarted.restore_persisted().code == "job_state_restored"
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        interrupted = restarted.get(created.job.id)
        assert interrupted is not None
        assert interrupted.state is JobState.INTERRUPTED

        status = index_job_status(tmp_path, manager=restarted, now=1_000_000.0)
        # The reason token is asserted, not merely the presence of an entry:
        # a "stalled" or "failed" entry here would mean the interrupted state
        # reached the check under some other branch and proves nothing.
        assert status["degraded_reasons"] == [
            {
                "source": "code",
                "job_id": created.job.id,
                "reason": "interrupted",
                "error_kind": "interrupted",
            }
        ]

    def test_an_interrupted_run_leaves_service_health_undegraded(
        self,
        isolated_status_dir: Path,
    ) -> None:
        """Serving is unimpaired by an interruption, so health must stay clean.

        The record is asserted present in the rollup before the empty reason
        list is asserted. Without that, the test could not tell "the health
        selector considered an interrupted job and declined it" from "no
        interrupted job ever reached the selector", and only the first is the
        property being defended.
        """
        del isolated_status_dir
        from ..jobs import restore_interrupted
        from ..server._lifespan import _jobs_health

        reset()
        try:
            # An empty in-memory ring beside a surviving snapshot written by a
            # process that is gone is exactly what a killed daemon leaves.
            job_id = job_recorded_by_a_now_dead_process()
            assert restore_interrupted() == 1
            records = {record["id"]: record for record in snapshot()}
            assert records[job_id]["phase"] == "interrupted"

            jobs_health, degraded_reasons = _jobs_health()
        finally:
            reset()

        states = cast("dict[str, int]", jobs_health["states"])
        assert states.get("interrupted") == 1, (
            "the interrupted record must reach the health rollup, or the "
            "empty reason list below would prove nothing"
        )
        # The empty reason list is asserted before the corroborating detail
        # below, so widening the health selector breaks the property this test
        # defends rather than an incidental consequence of it.
        assert degraded_reasons == []
        assert jobs_health["last_failed"] is None


class TestPersistenceFailureClassification:
    """A failed replace must never be reported as already published.

    ``PersistenceWriteError.published`` is what tells the manager whether to
    roll its in-memory mutation back. Reporting a failed replace as published
    suppresses that rollback on every reversible path at once, leaving memory
    claiming a transition no reader can see.
    """

    def test_failed_replace_is_not_published(self, tmp_path: Path) -> None:
        """A destination that cannot be replaced fails as unpublished."""
        from ..job_persistence import (
            PersistedManagerState,
            PersistenceWriteError,
            save_persisted_state,
        )

        state_path = tmp_path / "managed-jobs.json"
        # A directory at the destination makes the real replace fail: Windows
        # raises ACCESS_DENIED, POSIX raises EISDIR. Neither one publishes, so
        # a platform-conditional classification breaks this assertion.
        state_path.mkdir()

        with pytest.raises(PersistenceWriteError) as caught:
            save_persisted_state(
                state_path,
                PersistedManagerState(jobs=(), bindings=()),
            )

        assert caught.value.published is False
        assert list(tmp_path.glob(".managed-jobs.json.*.tmp")) == []
