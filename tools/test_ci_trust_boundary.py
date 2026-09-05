"""The pull-request lane's shape is a decision, not an accident.

Two properties hold this workflow together and neither is visible from reading
one job. Every job reachable from a fork's pull request must run on hosted
infrastructure, because a fork's code runs there. And the provisioning proofs
must be among what a pull request runs, because the failure they exist to catch
is a Windows file-locking behaviour that skips silently everywhere else - a
regression in it would otherwise reach the default branch unseen.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit]

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def _jobs() -> dict[str, dict[str, object]]:
    return dict(yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"])


def _runs_on_a_fork_pull_request(condition: str) -> bool:
    """Whether a job with this condition can run for a pull request."""
    if not condition:
        return True
    if "!= 'pull_request'" in condition:
        return False
    return "pull_request" in condition


def test_every_pull_request_job_runs_on_hosted_infrastructure() -> None:
    """A fork's pull request never reaches the self-hosted fleet.

    Guard assertion: this is the containment the workflow header describes.
    Adding a self-hosted job to the pull-request lane would hand an arbitrary
    fork execution on a workstation.
    """
    offenders = {
        name: job.get("runs-on")
        for name, job in _jobs().items()
        if _runs_on_a_fork_pull_request(str(job.get("if", "")))
        and "self-hosted" in str(job.get("runs-on", ""))
    }

    assert not offenders, f"self-hosted jobs reachable from a fork PR: {offenders}"


def test_the_pull_request_lane_runs_the_provisioning_proofs_on_windows() -> None:
    """The Windows-only proofs gate a merge rather than skipping quietly.

    Guard assertion: those tests carry `skipif(sys.platform != "win32")`, so on
    the Linux gate they report as skipped and prove nothing. Without a Windows
    leg in this lane, the environment-destruction proof cannot fail a pull
    request at all.
    """
    windows_pr_jobs = {
        name: job
        for name, job in _jobs().items()
        if _runs_on_a_fork_pull_request(str(job.get("if", "")))
        and "windows" in str(job.get("runs-on", "")).lower()
    }

    assert windows_pr_jobs, "no Windows job runs on a pull request"
    commands = []
    for job in windows_pr_jobs.values():
        steps = job.get("steps", [])
        assert isinstance(steps, list)
        for step in steps:
            assert isinstance(step, dict)
            commands.append(str(step.get("run", "")))
    assert any("just test provisioning" in command for command in commands), commands
