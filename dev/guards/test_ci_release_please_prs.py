"""Release-please PRs wait for the lock refresh before CI initializes them.

release-please writes the version bump first and regenerates ``uv.lock`` in a
follow-up commit on the same branch. The merge-box jobs all start with
``just init``, which runs ``uv sync --locked`` and will therefore fail on the
transient one-commit head for no code reason at all.
"""

from __future__ import annotations

import pytest

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

WORKFLOW = "ci.yml"
REQUIRED_GUARD = (
    "startsWith(github.head_ref, 'release-please--')",
    "github.event.pull_request.commits > 1",
)
REQUIRED_JOBS = ("lint", "tests", "tests-windows")


def _job_condition(job_id: str) -> str:
    """Return the named job's condition, or fail loudly when it vanishes."""
    for job in workflows.load_jobs(WORKFLOW):
        if job.job_id == job_id:
            assert job.condition is not None
            return job.condition
    pytest.fail(
        f"{WORKFLOW} has no job `{job_id}`. If it was renamed, repoint this "
        "guard; if it was deleted, the release-please race needs a new owner."
    )


def test_release_please_pull_requests_wait_for_the_lock_refresh_commit() -> None:
    """Merge-box jobs skip the transient one-commit release-please head.

    Mutation proof: removing the release-please clause from any guarded job
    makes this fail naming that job; restoring the clause makes it pass again.
    """
    expected = (
        "github.event_name != 'schedule' && "
        "(github.event_name != 'pull_request' || "
        f"!{REQUIRED_GUARD[0]} || {REQUIRED_GUARD[1]})"
    )
    offenders = {
        job_id: condition
        for job_id in REQUIRED_JOBS
        if (condition := " ".join(_job_condition(job_id).split())) != expected
    }
    assert not offenders, (
        "A release-please PR head runs merge-box jobs before the workflow's "
        "follow-up uv.lock refresh lands, so `just init` fails on stale lock "
        "metadata instead of on code.\n\n"
        f"missing guard: {offenders}"
    )
