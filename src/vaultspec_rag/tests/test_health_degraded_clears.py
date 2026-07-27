"""A degraded verdict must describe now, not the worst thing that ever happened.

The jobs rollup degrades health when the latest failed job belongs to the
running generation. That guard rules out failures from a previous daemon, but
it never asked whether a *later* run had since succeeded. One transient
failure - a momentary memory ceiling, a file that vanished mid-scan - therefore
degraded the service for the whole remaining life of the process, while newer
runs of the same source were visibly finishing clean. Observed on a live
service: fourteen hours of uptime reporting "the latest indexing job failed"
with twelve successful runs of that source after the named failure.

These bind the verdict to current state. They use real job records through the
production recording API rather than hand-built dicts, because the defect was
in which records the selector consults - a hand-built list would encode the
author's assumption about that instead of testing it.

MUTATION PROOF, run in one uninterrupted sequence: removing the supersession
check from the degradation condition in ``_lifespan._jobs_health`` fails
``test_a_later_success_on_the_same_source_clears_the_verdict`` on its own
empty-reasons assertion, and fails nothing else here. Restoring it returns the
file to green.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ..job_models import JobSource
from ..jobs import record_finish, record_start, reset, snapshot
from ..server._lifespan import _jobs_health

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _degrade_reasons() -> list[str]:
    _health, reasons = _jobs_health()
    return reasons


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
        assert any("latest indexing job failed" in reason for reason in reasons), (
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
        assert not any("latest indexing job failed" in r for r in reasons), (
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
        assert any("latest indexing job failed" in reason for reason in reasons), (
            f"another source's success must not answer this failure, got {reasons}"
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
        assert any("latest indexing job failed" in reason for reason in reasons), (
            f"the newest outcome is a failure, got {reasons}"
        )

    def test_the_failure_stays_visible_in_the_rollup_after_clearing(
        self,
        isolated_status_dir: Path,
    ) -> None:
        """Clearing the verdict must not hide the history behind it.

        An operator still needs to see that a run failed; what changes is
        whether the service calls itself degraded over it.
        """
        del isolated_status_dir
        reset()
        try:
            _failed(JobSource.CODE)
            _succeeded(JobSource.CODE)
            jobs_health, reasons = _jobs_health()
        finally:
            reset()
        assert not any("latest indexing job failed" in r for r in reasons)
        last_failed = cast("dict[str, object] | None", jobs_health["last_failed"])
        assert last_failed is not None, (
            "the failure must remain reported in the rollup, only not degrading"
        )
