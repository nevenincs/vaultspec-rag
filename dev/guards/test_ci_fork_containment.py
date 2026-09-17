"""What a fork's pull request may and may not reach.

No self-hosted job may run for a fork's pull request, because the workflow it
would run is the fork's own, and admitting one hands a stranger execution on
this hardware. The jobs a pull request does reach must still report their
required context for a fork, on GitHub-hosted isolation.

THE ACCELERATOR TIERS NEED NO SAME-REPO CLAUSE OF THEIR OWN. They run on a
workstation carrying a live service and the only card in the fleet, and on a
laptop, and no pull request can start them at all.
"""

from __future__ import annotations

import re
from typing import cast

import pytest
import yaml

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: The one definition of the accelerator tiers.
HARDWARE_WORKFLOW = "hardware.yml"

#: Events that run code a pull request's author controls.
PULL_REQUEST_EVENTS = frozenset({"pull_request", "pull_request_target"})

#: The clause that excludes a fork's pull request specifically. A self-hosted
#: job reachable by `pull_request` at all must carry this in its `if:`; one
#: that does not runs a fork's own workflow on this hardware.
SAME_REPO_CLAUSE = "head.repo.full_name == github.repository"

#: Every job a pull request reaches that lands on the fleet otherwise, by
#: workflow, with the hosted image a fork runs it on instead.
PULL_REQUEST_JOBS = {
    "ci.yml": {"lint": "ubuntu-24.04"},
    "merge-gate.yml": {
        "lint": "ubuntu-24.04",
        "tests": "ubuntu-24.04",
        "tests-windows": "windows-2025",
        "dependency-audit": "ubuntu-24.04",
    },
}


def test_no_self_hosted_job_is_reachable_from_a_forks_pull_request() -> None:
    """A fork's pull request never reaches the self-hosted fleet.

    Guard assertion: every self-hosted job either skips `pull_request`
    entirely or carries :data:`SAME_REPO_CLAUSE` in its `if:`.
    A self-hosted job with neither runs a fork's own workflow on this
    hardware, which is the exposure the trust boundary exists to close.
    """
    offenders = {
        f"{job.workflow}:{job.job_id}": job.condition
        for workflow in workflows.MERGE_BOX
        for job in workflows.load_jobs(workflow)
        if job.self_hosted
        and job.reaches("pull_request")
        and (job.condition is None or SAME_REPO_CLAUSE not in job.condition)
    }
    assert not offenders, f"self-hosted jobs reachable from a fork PR: {offenders}"


@pytest.mark.parametrize("workflow", sorted(PULL_REQUEST_JOBS))
def test_forks_emit_every_check_on_hosted_isolation(workflow: str) -> None:
    """Fork PRs keep their checks without reaching persistent runners.

    Mutation proof: replacing ``"windows-2025"`` in the gate's Windows job
    with a self-hosted label makes this fail naming that job; restoring it
    makes this pass.
    """
    source = (
        workflows.repository_root() / ".github" / "workflows" / workflow
    ).read_text(encoding="utf-8")
    for job_id, hosted in PULL_REQUEST_JOBS[workflow].items():
        match = re.search(
            rf"(?ms)^  {re.escape(job_id)}:\n(?P<body>.*?)(?=^  [a-z][\w-]*:|\Z)",
            source,
        )
        assert match is not None, f"{workflow} has no job `{job_id}`"
        runs_on = re.search(r"(?m)^    runs-on: (?P<value>.*)$", match.group("body"))
        assert runs_on is not None, f"{workflow}:{job_id} declares no runs-on"
        value = runs_on.group("value")
        where = f"{workflow}:{job_id}"
        assert "head.repo.full_name != github.repository" in value, where
        assert "fromJSON(" in value, where
        assert "self-hosted" in value, where
        assert f'"{hosted}"' in value, f"{where} does not run a fork on {hosted}"


def _callers(workflow: str) -> list[tuple[str, workflows.Job]]:
    """Return ``(caller workflow, job)`` for every job that calls *workflow*."""
    target = f"./.github/workflows/{workflow}"
    found: list[tuple[str, workflows.Job]] = []
    directory = workflows.repository_root() / ".github" / "workflows"
    for path in sorted(directory.glob("*.yml")):
        loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            continue
        raw_jobs = cast("dict[object, object]", loaded).get("jobs")
        if not isinstance(raw_jobs, dict):
            continue
        calling = {
            str(job_id)
            for job_id, body in cast("dict[object, object]", raw_jobs).items()
            if isinstance(body, dict)
            and cast("dict[object, object]", body).get("uses") == target
        }
        found.extend(
            (path.name, job)
            for job in workflows.load_jobs(path.name)
            if job.job_id in calling
        )
    return found


def test_the_hardware_tiers_are_unreachable_from_a_pull_request() -> None:
    """No pull request can start the MPS or CUDA tier.

    Those tiers run on a workstation with a live service and the fleet's only
    CUDA device, and on a personal laptop. They are reachable only through a
    workflow call, and every caller is started by a tag, a schedule or a
    dispatch, all of which require write access.

    Mutation proof: deleting the ``if:`` of the hardware caller in ``ci.yml``
    makes this fail naming ``ci.yml:hardware``; restoring it makes this pass.
    """
    assert workflows.workflow_events(HARDWARE_WORKFLOW) == ("workflow_call",), (
        f"{HARDWARE_WORKFLOW} must only be callable from another workflow, "
        f"but it triggers on {workflows.workflow_events(HARDWARE_WORKFLOW)}"
    )
    callers = _callers(HARDWARE_WORKFLOW)
    assert callers, f"nothing calls {HARDWARE_WORKFLOW}"
    reachable = [
        f"{workflow}:{job.job_id} (condition {job.condition!r})"
        for workflow, job in callers
        if PULL_REQUEST_EVENTS & set(workflows.workflow_events(workflow))
        and any(job.reaches(event) for event in PULL_REQUEST_EVENTS)
    ]
    assert not reachable, (
        f"a pull request can start {HARDWARE_WORKFLOW} through {reachable}. "
        "It would run a fork's code next to a live service and the only CUDA "
        "device."
    )
