"""THIS REPOSITORY'S copy of every workflow refuses a fork's pull request.

WHAT THIS GUARD DOES NOT PROVE, FIRST, BECAUSE IT READS AS THOUGH IT DID. A
``pull_request`` run from a fork executes the FORK's copy of the workflow
file. Every clause asserted below therefore lives in a file the fork rewrites
before its run starts: it can delete the same-repo clause, point ``runs-on``
at the fleet, and name a job whatever the merge box requires. No assertion
over the files in this repository can contain that, and reading one as though
it could is how a public repository ends up trusting a check a stranger wrote.

What contains a fork is a repository setting rather than a file: Actions
requires approval for workflow runs from ALL external contributors, so nothing
starts until a maintainer approves it. Approving a fork's run to be helpful
about its CI is therefore the whole boundary being lowered, once, by hand.

WHAT THIS GUARD DOES PROVE, AND WHY IT IS WORTH HAVING. That this repository's
own copy never drifts into running a pull request's head on the fleet, and
never reroutes a fork somewhere else instead of refusing it. That drift is the
likely failure - a clause dropped while moving a job, a hosted fallback added
to be accommodating - and it is the one a file can be read for. The clauses
are depth behind the setting, and this guard is what keeps the depth.

THE ACCELERATOR TIERS NEED NO SAME-REPO CLAUSE OF THEIR OWN. They run on a
workstation carrying a live service and the only card in the fleet, and on a
laptop, and no pull request can start them at all.
"""

from __future__ import annotations

import re
from typing import cast

import pytest
import yaml

from dev.ci_names import GATE_JOB, MERGE_BOX, SAME_REPO_CLAUSE, Workflow
from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: Events that run code a pull request's author controls.
PULL_REQUEST_EVENTS = frozenset({"pull_request", "pull_request_target"})

#: A runs-on expression that picks a different runner for a fork.
_FORK_RUNNER_SWITCH = re.compile(r"head\.repo\.full_name\s*!=")


def test_no_self_hosted_job_is_reachable_from_a_forks_pull_request() -> None:
    """A fork's pull request never reaches the self-hosted fleet.

    Guard assertion: every self-hosted job either skips `pull_request`
    entirely or carries :data:`SAME_REPO_CLAUSE` in its `if:`.
    A self-hosted job with neither runs a fork's own workflow on this
    hardware, which is the exposure the trust boundary exists to close.
    """
    offenders = {
        f"{job.workflow}:{job.job_id}": job.condition
        for workflow in MERGE_BOX
        for job in workflows.load_jobs(workflow)
        if job.self_hosted
        and job.reaches("pull_request")
        and (job.condition is None or SAME_REPO_CLAUSE not in job.condition)
    }
    assert not offenders, f"self-hosted jobs reachable from a fork PR: {offenders}"


def _runner_switches(documents: dict[str, str]) -> list[str]:
    """Name every job whose runs-on sends a fork somewhere else to run."""
    return [
        f"{name}:{line.strip()}"
        for name, text in documents.items()
        for line in text.splitlines()
        if line.lstrip().startswith("runs-on:") and _FORK_RUNNER_SWITCH.search(line)
    ]


def test_no_job_offers_a_fork_another_runner() -> None:
    """A fork is refused, never rerouted to hosted isolation."""
    directory = workflows.repository_root() / ".github" / "workflows"
    documents = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(directory.glob("*.yml"))
    }
    assert _runner_switches(documents) == []


def test_a_fork_runner_switch_is_named() -> None:
    """Mutation proof: the hosted fallback forks used to get is caught.

    Restoring ``runs-on: ${{ fromJSON(... head.repo.full_name !=
    github.repository && '["ubuntu-24.04"]' || ...) }}`` on the merge gate's
    lint job made ``test_no_job_offers_a_fork_another_runner`` fail naming
    that line; restoring the fixed fleet labels made it pass.
    """
    switch = (
        "    runs-on: ${{ fromJSON(github.event.pull_request.head.repo.full_name"
        " != github.repository && '[\"ubuntu-24.04\"]' || '[\"self-hosted\"]') }}"
    )
    documents = {"w.yml": f"jobs:\n  lint:\n{switch}\n    steps: []\n"}
    assert _runner_switches(documents) == [f"w.yml:{switch.strip()}"]


def test_the_gate_refuses_a_forks_pull_request() -> None:
    """The one required verdict fails a fork before it reads any result.

    Mutation proof: deleting the ``HEAD_REPO`` refusal from the gate's verdict step
    made this fail on the missing refusal; restoring it made this pass.
    """
    workflow, job_id = Workflow.MERGE_GATE, GATE_JOB
    gate = next(job for job in workflows.load_jobs(workflow) if job.job_id == job_id)
    verdict = next(
        step
        for step in gate.steps
        if step.get("name") == "Every full check passed on this commit"
    )
    document = yaml.safe_load(
        (workflows.repository_root() / ".github" / "workflows" / workflow).read_text(
            encoding="utf-8"
        )
    )
    assert isinstance(document, dict)
    raw_gate = document["jobs"][job_id]
    assert raw_gate["env"]["HEAD_REPO"] == (
        "${{ github.event.pull_request.head.repo.full_name }}"
    )
    script = str(verdict["run"])
    opening = (
        'if [ "${EVENT}" = "pull_request" ] && '
        '[ "${HEAD_REPO}" != "${GITHUB_REPOSITORY}" ]; then'
    )
    assert opening in script, "the verdict no longer refuses a fork"
    refusal = script.index(opening)
    assert "exit 1" in script[refusal : script.index("fi", refusal)]
    assert refusal < script.index('echo "lint=${LINT}')


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
    assert workflows.workflow_events(Workflow.HARDWARE) == ("workflow_call",), (
        f"{Workflow.HARDWARE} must only be callable from another workflow, "
        f"but it triggers on {workflows.workflow_events(Workflow.HARDWARE)}"
    )
    callers = _callers(Workflow.HARDWARE)
    assert callers, f"nothing calls {Workflow.HARDWARE}"
    reachable = [
        f"{workflow}:{job.job_id} (condition {job.condition!r})"
        for workflow, job in callers
        if PULL_REQUEST_EVENTS & set(workflows.workflow_events(workflow))
        and any(job.reaches(event) for event in PULL_REQUEST_EVENTS)
    ]
    assert not reachable, (
        f"a pull request can start {Workflow.HARDWARE} through {reachable}. "
        "It would run a fork's code next to a live service and the only CUDA "
        "device."
    )
