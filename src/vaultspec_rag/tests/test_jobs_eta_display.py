"""The jobs feed and detail views say how much longer, or say they cannot.

The enriched jobs projection publishes ``estimated_remaining_seconds`` with
three distinct answers: a value (a countdown the operator can plan around), a
null (the service measured and declines to estimate this job), and an absent
key (a daemon that predates the field and says nothing about estimates at
all). Each must read differently, because collapsing any two of them either
promises a finish nobody computed or tells an operator their work is
unmeasurable when only their daemon is old.

No mocks, patches, or fakes: the real renderers write to the real console and
the assertions read what they printed.
"""

from __future__ import annotations

import pytest

from ..cli._service_jobs_presentation import (
    _render_jobs_feed,
    remaining_estimate_label,
    render_job_detail,
)

pytestmark = [pytest.mark.unit]


def _running_job(
    job_id: str,
    **overrides: object,
) -> dict[str, object]:
    """One admitted, progressing job in the shape the service publishes."""
    record: dict[str, object] = {
        "id": job_id,
        "source": "code",
        "phase": "running",
        "started_at": 1_000.0,
        "runtime_seconds": 75.0,
        "admission_acquired_at": 1_001.0,
        "last_progress_age_seconds": 1.0,
        "stalled": False,
        "progress_rate_per_second": 5.0,
        "estimated_remaining_seconds": 250.0,
        "progress": {"step": "embed", "completed": 40, "total": 100},
        "initiator": {"command": "reindex_codebase", "project_root": "/w/demo"},
    }
    return record | overrides


def _feed(jobs: list[dict[str, object]]) -> None:
    _render_jobs_feed(
        {"total": len(jobs), "returned": len(jobs)},
        list(jobs),
        port=8766,
    )


class TestFeedRemainingTime:
    """One line per job, and the estimate rides on it when there is one."""

    def test_a_published_estimate_renders_as_a_coarse_countdown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _feed([_running_job("aaaaaaaa")])
        out = capsys.readouterr().out

        assert "~4m10s remaining" in out

    def test_a_published_null_reads_as_an_explicit_unknown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Mutation check: making ``remaining_estimate_label`` return the
        # empty string for a published null - collapsing decline into
        # absence - fails on the assertion below, not on an import.
        _feed(
            [
                _running_job(
                    "aaaaaaaa",
                    estimated_remaining_seconds=None,
                    progress_rate_per_second=None,
                )
            ]
        )
        out = capsys.readouterr().out

        assert "ETA unknown" in out
        assert "remaining" not in out

    def test_an_absent_field_says_nothing_at_all(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Mutation check: dropping the key-presence guard in
        # ``remaining_estimate_label`` renders every pre-field daemon's job
        # as "ETA unknown" and fails on the not-printed assertion below.
        job = _running_job("aaaaaaaa")
        del job["estimated_remaining_seconds"]
        del job["progress_rate_per_second"]
        _feed([job])
        out = capsys.readouterr().out

        assert "ETA unknown" not in out
        assert "remaining" not in out

    def test_a_stalled_job_shows_the_stall_not_a_countdown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The estimate is measured over a window whose newest samples
        # predate the stall; a countdown beside "no progress for ..." is
        # two contradictory claims. Mutation check: dropping the
        # stale-progress gate in ``_running_job_detail`` prints both and
        # fails on the no-countdown assertion below.
        _feed(
            [
                _running_job(
                    "aaaaaaaa",
                    stalled=True,
                    last_progress_age_seconds=900.0,
                )
            ]
        )
        out = capsys.readouterr().out

        assert "no progress for" in out
        assert "~4m10s remaining" not in out

    def test_a_queued_job_carries_no_unknown_marker(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A job parked on the GPU slot is inert by design; its null estimate
        # is not a measurement the operator needs announced.
        _feed(
            [
                _running_job(
                    "aaaaaaaa",
                    admission_acquired_at=None,
                    estimated_remaining_seconds=None,
                    progress_rate_per_second=None,
                    progress=None,
                )
            ]
        )
        out = capsys.readouterr().out

        assert "for the GPU slot" in out
        assert "ETA unknown" not in out


class TestDetailRemainingTime:
    """The single-job view carries the same estimate line, same vocabulary."""

    def test_a_published_estimate_is_a_line_of_its_own(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_job_detail(_running_job("aaaaaaaa"))
        out = capsys.readouterr().out

        assert "~4m10s remaining" in out

    def test_a_published_null_is_said_plainly(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_job_detail(
            _running_job(
                "aaaaaaaa",
                estimated_remaining_seconds=None,
                progress_rate_per_second=None,
            )
        )
        out = capsys.readouterr().out

        assert "ETA unknown" in out

    def test_an_absent_field_prints_no_estimate_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        job = _running_job("aaaaaaaa")
        del job["estimated_remaining_seconds"]
        del job["progress_rate_per_second"]
        render_job_detail(job)
        out = capsys.readouterr().out

        assert "ETA unknown" not in out
        assert "remaining" not in out

    def test_a_finished_job_prints_no_estimate_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_job_detail(
            _running_job(
                "aaaaaaaa",
                phase="done",
                finished_at=2_000.0,
                estimated_remaining_seconds=None,
                progress_rate_per_second=None,
                result="+3 /1 -0 (900ms)",
            )
        )
        out = capsys.readouterr().out

        assert "ETA unknown" not in out


class TestLabelShape:
    """The one label both views share, pinned at its edges."""

    def test_the_countdown_never_reads_below_the_service_value(self) -> None:
        # Ceiling, not truncation: 249.7 must not read as 4m09s the instant
        # the service said "about 250". Mutation check: replacing the
        # ``math.ceil`` with ``int`` truncates and fails on this assertion.
        label = remaining_estimate_label(
            {"estimated_remaining_seconds": 249.7},
        )
        assert label == "~4m10s remaining"

    def test_a_negative_value_clamps_to_zero(self) -> None:
        # A skewed clock or a rounded-down remainder must not render a
        # negative countdown.
        label = remaining_estimate_label(
            {"estimated_remaining_seconds": -3.0},
        )
        assert label == "~0s remaining"
