"""What a fork's pull request may and may not reach, and what it must run.

Two properties hold the pull-request lane's shape together and neither is
visible from reading one job. No self-hosted job may run for a fork's pull
request, because the workflow it would run is the fork's own, and admitting
one hands a stranger execution on this hardware. And the provisioning proofs
must be among what a pull request runs, because the failure they exist to
catch is a Windows file-locking behaviour that skips silently everywhere else
- a regression in it would otherwise reach the default branch unseen.

THE GPU TIER NEEDS NO SAME-REPO CLAUSE OF ITS OWN. That job runs on a
workstation carrying a live service and the only card in the fleet, and it
stays dispatch-only, which requires write access, so a fork's pull request can
never start it regardless of the guard every other self-hosted job carries.
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

#: The clause that excludes a fork's pull request specifically. A self-hosted
#: job reachable by `pull_request` at all must carry this in its `if:`; one
#: that does not runs a fork's own workflow on this hardware.
SAME_REPO_CLAUSE = "head.repo.full_name == github.repository"


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


def test_no_self_hosted_job_is_reachable_from_a_forks_pull_request() -> None:
    """A fork's pull request never reaches the self-hosted fleet.

    Guard assertion: every self-hosted job either skips `pull_request`
    entirely (the GPU tier) or carries :data:`SAME_REPO_CLAUSE` in its `if:`.
    A self-hosted job with neither runs a fork's own workflow on this
    hardware, which is the exposure the trust boundary exists to close.
    """
    offenders = {
        job.job_id: job.condition
        for job in workflows.load_jobs(WORKFLOW)
        if job.self_hosted
        and job.reaches("pull_request")
        and (job.condition is None or SAME_REPO_CLAUSE not in job.condition)
    }
    assert not offenders, f"self-hosted jobs reachable from a fork PR: {offenders}"


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
