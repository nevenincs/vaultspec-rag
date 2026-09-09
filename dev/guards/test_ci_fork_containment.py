"""What a fork's pull request may and may not reach, and what it must run.

THIS REPLACED A GUARD THAT ASSERTED THE OPPOSITE OF THE DECISION. Its
predecessor held that no job reachable from a fork pull request may run on the
self-hosted fleet. That was true once; the workflow header then recorded the
reversal - the fleet runs pull requests like everything else, and the
containment comes from the repository's fork-approval setting for workflow
runs rather than from where the job lands. The guard was never updated, so it
had been failing continuously against a workflow that was doing exactly what
it had been changed to do. A red guard nobody can act on is worse than no
guard: it trains people to read the failure list and skip a line.

WHAT IS STILL WORTH ASSERTING. The reversal did not extend to the GPU tier.
That job runs on a workstation carrying a live service and the only card in
the fleet, and it stays dispatch-only precisely so a pull request can never
start it - which is a containment a workflow edit could remove in one line and
nothing else would notice.

AND WHAT A PULL REQUEST MUST NOT SKIP. The provisioning proofs carry
``skipif(sys.platform != "win32")``: on a Linux runner they report as skipped
and prove nothing. Without a Windows leg in the pull-request lane, the
environment-destruction proof cannot fail a pull request at all, and a
Windows-only regression reaches the default branch unseen. This is the reason
the Windows job runs on every event rather than on pushes only.
"""

from __future__ import annotations

import pytest

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

WORKFLOW = "ci.yml"

#: The job whose runner is a workstation with a live service and the one card.
GPU_JOB = "gpu-tests"

#: The lane that can only fail on Windows, and so must run there.
WINDOWS_ONLY_LANE = "test-provisioning"


def _job(job_id: str) -> workflows.Job:
    """Return the named merge-box job, failing loudly when it is gone."""
    for job in workflows.load_jobs(WORKFLOW):
        if job.job_id == job_id:
            return job
    pytest.fail(
        f"{WORKFLOW} has no job `{job_id}`. If it was renamed, repoint this "
        "guard; if it was deleted, the property it holds went with it and "
        "that is a decision to make deliberately."
    )


def test_the_gpu_tier_is_unreachable_from_a_pull_request() -> None:
    """No pull request can start the GPU tier.

    Guard assertion: deleting the dispatch condition on that job hands a fork
    arbitrary execution on a workstation, next to a running service and the
    only CUDA device in the fleet. Nothing else in the repository would report
    that change.
    """
    job = _job(GPU_JOB)
    assert not job.reaches("pull_request"), (
        f"`{GPU_JOB}` is reachable from a pull request under its condition "
        f"{job.condition!r}. It runs on a workstation with a live service and "
        "the fleet's only CUDA device; it stays dispatch-only, which requires "
        "write access, so a fork can never start it."
    )


def test_the_pull_request_lane_runs_the_windows_only_proofs() -> None:
    """A pull request runs the proofs that can only fail on Windows.

    Guard assertion: those tests skip silently on Linux, so a lane without a
    Windows leg reports the same green whether the behaviour they cover works
    or was deleted.
    """
    covering = {
        job.job_id: job.recipes_on("pull_request")
        for job in workflows.load_jobs(WORKFLOW)
        if "windows" in job.platforms
    }
    running = {job_id: recipes for job_id, recipes in covering.items() if recipes}
    assert running, (
        "no Windows job runs on a pull request, so the provisioning proofs "
        "skip in the only lane that gates a merge."
    )
    from dev.guards.test_ci_no_repeated_work import SUBSET_LANES

    cover = SUBSET_LANES[WINDOWS_ONLY_LANE][0]
    assert any(
        WINDOWS_ONLY_LANE in recipes or cover in recipes for recipes in running.values()
    ), (
        f"a pull request's Windows job runs {running}, which includes neither "
        f"`{WINDOWS_ONLY_LANE}` nor the lane that contains it, `{cover}`."
    )
