"""A degraded verdict must describe now, not the worst thing that ever happened.

The jobs rollup folds job history per project root and source. A key is
failing when the newest record that proves anything about it - a success or a
real failure - is a failure. A failing key degrades health only while its
failure is inside the running generation and inside the degradation window;
past either bound it stays listed without degrading. Observed on a live
service before this fold: sixteen hours of ``degraded`` over one failure while
other jobs ran clean, because only the single newest failure was ever examined
and nothing aged it out.

These bind the verdict to current state. They use real job records through the
production recording API rather than hand-built dicts, because the defect was
in which records the fold consults - a hand-built list would encode the
author's assumption about that instead of testing it. The assertions read the
typed reason, not the detail text.

MUTATION PROOF, each run in one uninterrupted sequence against
``_lifespan._failing_project_indexes`` and ``_lifespan._decisive_outcome``:

- Treating ``cancelled`` as decisive fails
  ``test_a_later_cancelled_run_does_not_clear_the_failure`` on its
  ``_job_failed`` assertion.
- Reducing the fold to the single newest failure fails
  ``test_an_older_failure_stays_degrading_when_a_newer_one_is_resolved`` on its
  ``_job_failed`` assertion.
- Dropping the window from ``degrading`` fails
  ``test_a_failure_older_than_the_window_is_listed_without_degrading`` on its
  ``degrading is False`` assertion.
- Removing the full-reindex exclusion fails the rebuild-refusal cases on the
  empty degradation and empty ``failing`` assertions.

Restoring each mutation returns the module to green.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

import pytest

from .._job_errors import JobError, JobErrorKind
from ..job_models import JobSource
from ..jobs import record_finish, record_start, reset, snapshot
from ..operator_state._service import DegradationReason
from ..server._lifespan import (
    _FAILING_NAMED,
    _FAILURE_DEGRADES_FOR_SECONDS,
    _jobs_health,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ..operator_state._models import Degradation

pytestmark = [pytest.mark.unit]


def _degrade_reasons() -> list[Degradation]:
    _health, reasons = _jobs_health(now=time.time())
    return reasons


def _job_failed(reasons: list[Degradation]) -> bool:
    """Whether the failed-job branch, and no other, degraded the verdict."""
    return any(reason.reason is DegradationReason.JOB_FAILED for reason in reasons)


def _failing(jobs_health: dict[str, object]) -> dict[str, object]:
    return cast("dict[str, object]", jobs_health["failing"])


def _entries(jobs_health: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", _failing(jobs_health)["entries"])


def _failed(source: JobSource) -> str:
    job_id = record_start(source, "watcher")
    record_finish(job_id, error="cuda_memory_ceiling: ceiling exceeded")
    return job_id


def _succeeded(source: JobSource) -> str:
    job_id = record_start(source, "watcher")
    record_finish(job_id, result="+1 /0 -0 (100ms)")
    return job_id


class TestDegradedVerdictTracksCurrentState:
    """One failure must not outlive the runs that followed it."""

    @pytest.mark.parametrize(
        "source", [JobSource.CODE, JobSource.VAULT, JobSource.DOCUMENT]
    )
    def test_rebuild_refusal_is_repository_readiness(
        self, isolated_status_dir: Path, tmp_path: Path, source: JobSource
    ) -> None:
        """A refused incremental stays visible without degrading the service."""
        del isolated_status_dir
        reset()
        try:
            job_id = record_start(
                source, "watcher", project_root=tmp_path / "unindexed"
            )
            record_finish(
                job_id,
                error=str(
                    JobError(JobErrorKind.FULL_REINDEX_REQUIRED, "no committed index")
                ),
            )
            jobs_health, reasons = _jobs_health(now=time.time())
            records = {str(record["id"]): record for record in snapshot()}
        finally:
            reset()
        assert records[job_id]["error_kind"] == JobErrorKind.FULL_REINDEX_REQUIRED
        assert records[job_id]["phase"] == "error"
        assert reasons == []
        assert _failing(jobs_health) == {"total": 0, "degrading": 0, "entries": []}

    def test_rebuild_refusal_does_not_hide_a_real_failure(
        self, isolated_status_dir: Path
    ) -> None:
        """A newer refusal must not hide a real failure on another source."""
        del isolated_status_dir
        reset()
        try:
            failed_id = _failed(JobSource.CODE)
            refused_id = record_start(JobSource.VAULT, "watcher")
            record_finish(
                refused_id,
                error=str(
                    JobError(JobErrorKind.FULL_REINDEX_REQUIRED, "no committed index")
                ),
            )
            jobs_health, reasons = _jobs_health(now=time.time())
        finally:
            reset()
        assert _job_failed(reasons)
        assert [entry["id"] for entry in _entries(jobs_health)] == [failed_id]

    def test_a_failure_with_nothing_after_it_still_degrades(
        self,
        isolated_status_dir: Path,
    ) -> None:
        """The verdict must still fire, or the clearing test proves nothing."""
        del isolated_status_dir
        reset()
        try:
            _failed(JobSource.CODE)
            reasons = _degrade_reasons()
        finally:
            reset()
        assert _job_failed(reasons), (
            f"an unanswered failure must degrade health, got {reasons}"
        )

    def test_a_later_success_on_the_same_source_clears_the_verdict(
        self,
        isolated_status_dir: Path,
    ) -> None:
        """This is the defect: the failure is answered, so it is history."""
        del isolated_status_dir
        reset()
        try:
            failed_id = _failed(JobSource.CODE)
            _succeeded(JobSource.CODE)
            records = {str(record["id"]): record for record in snapshot()}
            # Assert the failure actually reached the rollup first. Without
            # this the empty reason list below could equally mean "no failed
            # record was ever recorded", which is not the property defended.
            assert records[failed_id]["phase"] == "error", (
                "the failed record must be present for this to prove anything"
            )
            reasons = _degrade_reasons()
        finally:
            reset()
        assert not _job_failed(reasons), (
            f"a later success answered the failure, got {reasons}"
        )

    def test_a_success_on_a_different_source_does_not_clear_it(
        self,
        isolated_status_dir: Path,
    ) -> None:
        """A vault run says nothing about whether the code index is current."""
        del isolated_status_dir
        reset()
        try:
            _failed(JobSource.CODE)
            _succeeded(JobSource.VAULT)
            reasons = _degrade_reasons()
        finally:
            reset()
        assert _job_failed(reasons), (
            f"another source's success must not answer this failure, got {reasons}"
        )

    def test_a_success_in_another_project_does_not_clear_it(
        self,
        isolated_status_dir: Path,
        tmp_path: Path,
    ) -> None:
        """The service serves many projects; one's success says nothing of another."""
        del isolated_status_dir
        reset()
        try:
            failed = record_start(
                JobSource.CODE, "watcher", project_root=tmp_path / "first"
            )
            record_finish(failed, error="cuda_memory_ceiling: ceiling exceeded")
            succeeded = record_start(
                JobSource.CODE, "watcher", project_root=tmp_path / "second"
            )
            record_finish(succeeded, result="+1 /0 -0 (100ms)")
            reasons = _degrade_reasons()
        finally:
            reset()
        assert _job_failed(reasons), (
            f"another project's success must not answer this failure, got {reasons}"
        )

    def test_a_later_success_in_the_same_project_clears_it(
        self,
        isolated_status_dir: Path,
        tmp_path: Path,
    ) -> None:
        """The same project, spelled another way, is still the same project.

        Mutation: comparing the recorded roots as raw strings. The success
        then reads as another project's and the verdict stays degraded.
        """
        del isolated_status_dir
        project = tmp_path / "project"
        reset()
        try:
            failed = record_start(JobSource.CODE, "watcher", project_root=project)
            record_finish(failed, error="cuda_memory_ceiling: ceiling exceeded")
            succeeded = record_start(
                JobSource.CODE, "watcher", project_root=project / "nested" / ".."
            )
            record_finish(succeeded, result="+1 /0 -0 (100ms)")
            reasons = _degrade_reasons()
        finally:
            reset()
        assert not _job_failed(reasons), (
            f"a success in the same project answered the failure, got {reasons}"
        )

    def test_a_failure_after_a_success_degrades_again(
        self,
        isolated_status_dir: Path,
    ) -> None:
        """Order matters: the newest outcome is the one that counts."""
        del isolated_status_dir
        reset()
        try:
            _succeeded(JobSource.CODE)
            _failed(JobSource.CODE)
            reasons = _degrade_reasons()
        finally:
            reset()
        assert _job_failed(reasons), f"the newest outcome is a failure, got {reasons}"

    def test_a_resolved_failure_leaves_the_failing_list(
        self,
        isolated_status_dir: Path,
        tmp_path: Path,
    ) -> None:
        """A success answers the failure; the history stays in the state counts.

        An operator still sees that a run failed through the job states; the
        failing list names only keys whose newest decisive outcome failed.
        """
        del isolated_status_dir
        project = tmp_path / "project"
        reset()
        try:
            failed = record_start(JobSource.CODE, "watcher", project_root=project)
            record_finish(failed, error="cuda_memory_ceiling: ceiling exceeded")
            succeeded = record_start(JobSource.CODE, "watcher", project_root=project)
            record_finish(succeeded, result="+1 /0 -0 (100ms)")
            jobs_health, reasons = _jobs_health(now=time.time())
        finally:
            reset()
        assert not _job_failed(reasons)
        assert _failing(jobs_health)["total"] == 0
        states = cast("dict[str, int]", jobs_health["states"])
        assert states.get("failed") == 1, "the failure must stay in job history"

    def test_a_later_cancelled_run_does_not_clear_the_failure(
        self,
        isolated_status_dir: Path,
        tmp_path: Path,
    ) -> None:
        """A cancellation is a decision, not evidence the index can be built.

        Mutation: counting ``cancelled`` as a decisive outcome. The cancelled
        run then becomes the key's newest outcome and the verdict clears.
        """
        del isolated_status_dir
        project = tmp_path / "project"
        reset()
        try:
            failed = record_start(JobSource.CODE, "watcher", project_root=project)
            record_finish(failed, error="cuda_memory_ceiling: ceiling exceeded")
            cancelled = record_start(JobSource.CODE, "watcher", project_root=project)
            record_finish(cancelled, phase="cancelled")
            jobs_health, reasons = _jobs_health(now=time.time())
        finally:
            reset()
        assert _job_failed(reasons), (
            f"a cancelled run proves nothing about the failure, got {reasons}"
        )
        assert [entry["id"] for entry in _entries(jobs_health)] == [failed]

    def test_an_older_failure_stays_degrading_when_a_newer_one_is_resolved(
        self,
        isolated_status_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Every project is folded, so a resolved newest failure hides nothing.

        Mutation: examining only the newest failure across all projects. That
        is project B's, which a success resolved, so project A's unresolved
        failure never degrades.
        """
        del isolated_status_dir
        first = tmp_path / "first"
        second = tmp_path / "second"
        reset()
        try:
            older = record_start(JobSource.CODE, "watcher", project_root=first)
            record_finish(older, error="cuda_memory_ceiling: ceiling exceeded")
            newer = record_start(JobSource.CODE, "watcher", project_root=second)
            record_finish(newer, error="cuda_memory_ceiling: ceiling exceeded")
            resolved = record_start(JobSource.CODE, "watcher", project_root=second)
            record_finish(resolved, result="+1 /0 -0 (100ms)")
            jobs_health, reasons = _jobs_health(now=time.time())
        finally:
            reset()
        assert _job_failed(reasons), (
            f"project A's failure is unresolved and recent, got {reasons}"
        )
        entries = _entries(jobs_health)
        assert [entry["id"] for entry in entries] == [older]
        assert entries[0]["project_root"] == str(first)
        assert entries[0]["degrading"] is True

    def test_a_failure_older_than_the_window_is_listed_without_degrading(
        self,
        isolated_status_dir: Path,
        tmp_path: Path,
    ) -> None:
        """The window bounds how long one failure holds the verdict.

        Mutation: dropping the age bound from ``degrading``. The stale failure
        then degrades for as long as the generation lives, which is the
        sixteen-hour symptom.
        """
        del isolated_status_dir
        project = tmp_path / "project"
        reset()
        try:
            failed = record_start(JobSource.CODE, "watcher", project_root=project)
            record_finish(failed, error="cuda_memory_ceiling: ceiling exceeded")
            later = time.time() + _FAILURE_DEGRADES_FOR_SECONDS + 60.0
            jobs_health, reasons = _jobs_health(now=later)
        finally:
            reset()
        entries = _entries(jobs_health)
        assert [entry["id"] for entry in entries] == [failed]
        assert entries[0]["degrading"] is False
        assert not _job_failed(reasons)
        assert _failing(jobs_health)["degrading"] == 0

    def test_the_failing_list_is_bounded_and_newest_first(
        self,
        isolated_status_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Five entries are named, newest first, and every failure is counted."""
        del isolated_status_dir
        reset()
        try:
            for index in range(_FAILING_NAMED + 2):
                job = record_start(
                    JobSource.CODE, "watcher", project_root=tmp_path / f"p{index}"
                )
                record_finish(job, error="cuda_memory_ceiling: ceiling exceeded")
            jobs_health, reasons = _jobs_health(now=time.time())
        finally:
            reset()
        failing = _failing(jobs_health)
        assert failing["total"] == _FAILING_NAMED + 2
        assert failing["degrading"] == _FAILING_NAMED + 2
        entries = _entries(jobs_health)
        assert len(entries) == _FAILING_NAMED
        assert entries[0]["project_root"] == str(tmp_path / f"p{_FAILING_NAMED + 1}")
        detail = next(
            reason.detail
            for reason in reasons
            if reason.reason is DegradationReason.JOB_FAILED
        )
        assert detail.startswith(f"{_FAILING_NAMED + 2} project index runs failed: ")
        assert detail.endswith(f" and {_FAILING_NAMED + 1} more")
