"""The jobs feed says out loud that a retry belongs to the job it retried.

The service publishes the relationship as ``parent_job_id`` on the retry,
and the feed used to render both rows as unrelated entries. The operator
experience that produced: hit retry, watch a child run briefly, finish, and
vanish, while the interrupted row sits there apparently untouched - which
reads as "the retry was cancelled instantly". A child row must name the job
it retries, and a parent row must report its newest retry and that retry's
state, so an interrupted row whose retry succeeded says so.

No mocks, patches, or fakes: the real renderer writes to the real console
and the assertions read what it printed.
"""

from __future__ import annotations

import pytest

from ..cli._service_jobs_presentation import _render_jobs_feed, render_job_detail

pytestmark = [pytest.mark.unit]


def _job(
    job_id: str,
    *,
    phase: str,
    at: float,
    parent: str | None = None,
    result: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "id": job_id,
        "source": "code",
        "phase": phase,
        "started_at": at,
        "finished_at": at + 10.0 if phase != "running" else None,
        "runtime_seconds": 10.0,
        "result": result
        if result is not None
        else ("+106 /0 -0 (27900ms)" if phase == "done" else None),
        "initiator": {"command": "reindex_codebase", "project_root": "/w/demo"},
    }
    if parent is not None:
        record["parent_job_id"] = parent
    return record


def _render(jobs: list[dict[str, object]]) -> None:
    _render_jobs_feed(
        {"total": len(jobs), "returned": len(jobs)},
        list(jobs),
        port=8766,
    )


class TestRetryLineageInTheFeed:
    def test_parent_and_child_rows_name_each_other(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The live incident's shape: interrupted parent, succeeded retry.

        Mutation check: dropping the lineage notes from the feed loop makes
        this fail on both phrase assertions below - the rows render exactly
        as the unrelated entries the defect produced - and restoring the
        notes returns it to green.
        """
        _render(
            [
                _job("fe101858", phase="interrupted", at=1_000.0),
                _job("de428ff2", phase="done", at=2_000.0, parent="fe101858"),
            ]
        )
        out = capsys.readouterr().out
        parent_line = next(
            line for line in out.splitlines() if "(job fe101858)" in line
        )
        assert "retried as job de428ff2 (finished)" in parent_line
        child_line = next(line for line in out.splitlines() if "(job de428ff2)" in line)
        assert "retry of job fe101858" in child_line

    def test_a_child_whose_parent_left_the_page_still_names_it(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _render(
            [
                _job(
                    "de428ff2",
                    phase="done",
                    at=2_000.0,
                    parent="fe101858aaaa4bd0be7cf6f1b64d2f00",
                )
            ]
        )
        out = capsys.readouterr().out
        assert "retry of job fe101858" in out

    def test_the_parent_reports_its_newest_retry(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _render(
            [
                _job("fe101858", phase="interrupted", at=1_000.0),
                _job("aaaa1111", phase="error", at=1_500.0, parent="fe101858"),
                _job("bbbb2222", phase="done", at=2_000.0, parent="fe101858"),
            ]
        )
        out = capsys.readouterr().out
        parent_line = next(
            line for line in out.splitlines() if "(job fe101858)" in line
        )
        assert "retried as job bbbb2222 (finished)" in parent_line

    def test_unrelated_rows_carry_no_lineage_phrase(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Mutation check: annotating every row unconditionally (e.g. keying
        # the notes wrongly) makes this fail on the absence assertions below.
        _render(
            [
                _job("fe101858", phase="interrupted", at=1_000.0),
                _job("de428ff2", phase="done", at=2_000.0),
            ]
        )
        out = capsys.readouterr().out
        assert "retry of job" not in out
        assert "retried as job" not in out


class TestSupersededRendering:
    """A resolved parent reads as history, not as a failure or as the worker.

    The service marks a parent whose linked retry succeeded with the
    terminal state string "superseded" while preserving the parent's
    pre-resolution result text. Rendered defensively from the payload's
    state string alone, so the rows read correctly whether or not this
    build's own models know the state.
    """

    def test_a_superseded_parent_reads_as_resolved_history(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _render(
            [
                _job(
                    "fe101858",
                    phase="superseded",
                    at=1_000.0,
                    result="daemon terminated while this job was running",
                ),
                _job("de428ff2", phase="done", at=2_000.0, parent="fe101858"),
            ]
        )
        out = capsys.readouterr().out
        parent_line = next(
            line for line in out.splitlines() if "(job fe101858)" in line
        )
        assert "superseded" in parent_line
        assert "resolved: a linked retry succeeded" in parent_line
        assert "retried as job de428ff2 (finished)" in parent_line
        # The pre-resolution interruption text must not resurface as a
        # current finding on a resolved row.
        assert "daemon terminated" not in parent_line
        # Resolved history counts beside finished work, never as a failure.
        assert "2 finished, 0 failed" in out

    def test_a_superseded_detail_replaces_the_stale_result(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Mutation check: removing the superseded branch from the result
        renderer prints the preserved interruption text instead of the
        resolution line, and this fails on the "Resolution:" assertion
        below (the stale-text absence assertion backs it); restoring the
        branch returns it to green.
        """
        render_job_detail(
            _job(
                "fe101858",
                phase="superseded",
                at=1_000.0,
                result="daemon terminated while this job was running",
            )
        )
        out = capsys.readouterr().out
        assert "Status: superseded" in out
        assert "Resolution: a linked retry succeeded" in out
        assert "daemon terminated" not in out


class TestRetryLineageInTheDetailView:
    def test_a_retry_detail_names_its_parent(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        render_job_detail(
            _job(
                "de428ff2",
                phase="done",
                at=2_000.0,
                parent="fe101858aaaa4bd0be7cf6f1b64d2f00",
            )
        )
        out = capsys.readouterr().out
        assert "Retry of job: fe101858aaaa4bd0be7cf6f1b64d2f00" in out

    def test_a_job_without_a_parent_shows_no_lineage_line(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        render_job_detail(_job("fe101858", phase="done", at=1_000.0))
        out = capsys.readouterr().out
        assert "Retry of job:" not in out
