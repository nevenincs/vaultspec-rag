"""Pull requests from forks are refused, and never reach the hardware tiers.

A ``pull_request`` run from a fork executes the fork's own copy of each
workflow, so no assertion over these files can stop a fork that rewrites
them; Actions approval for external contributors is what does. This guard
keeps this repository's own copy honest: the required verdict refuses a fork,
and the hardware tiers, which hold secrets, cannot be started by a pull
request.
"""

from __future__ import annotations

from typing import cast

import pytest

from dev.guards import _workflows as workflows
from dev.guards._ci_names import GATE_JOB, Workflow

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: Events that run code a pull request's author controls.
PULL_REQUEST_EVENTS = frozenset({"pull_request", "pull_request_target"})

#: The pull request authors whose code may reach the fleet unreviewed. This is a
#: personal account, so there are no organisation members.
TRUSTED_AUTHOR = (
    "(github.event.pull_request.author_association == 'OWNER' || "
    "github.event.pull_request.author_association == 'COLLABORATOR')"
)

#: Applying a label takes triage rights; a bot applying `ci:full` does not count.
LABEL_BY_USER = "github.event.sender.type == 'User'"


def test_only_a_trusted_author_or_a_users_label_reaches_the_fleet() -> None:
    """A pull request runs fleet jobs only for a trusted author or a user's label.

    Dependabot and every other author who is neither the owner nor a
    collaborator push branches of this repository, so the fork refusal never
    stops them, and the approval requirement for outside contributors does not
    cover them. Every job a pull request can reach, except the gate that only
    reads results, carries the author clause, and any `ci:full` path in it
    counts only a user's label.

    Mutation proof: dropping the author clause from `lint-light`'s condition
    makes this fail naming ``merge-gate.yml:lint-light``; restoring it makes
    this pass.
    """
    untrusted: list[str] = []
    for job in workflows.load_jobs():
        if (job.workflow, job.job_id) == (Workflow.MERGE_GATE, GATE_JOB):
            continue
        events = PULL_REQUEST_EVENTS & set(workflows.workflow_events(job.workflow))
        if not any(job.reaches(event) for event in events):
            continue
        condition = job.condition or ""
        if TRUSTED_AUTHOR not in condition:
            untrusted.append(f"{job.workflow}:{job.job_id}")
        elif "ci:full" in condition and LABEL_BY_USER not in condition:
            untrusted.append(f"{job.workflow}:{job.job_id} (a bot's label)")
    assert not untrusted, (
        "these jobs run a pull request by any author on the self-hosted fleet, "
        f"Dependabot included: {untrusted}"
    )


def test_the_gate_refuses_an_untrusted_authors_commit_by_name() -> None:
    """An untrusted author's unproven commit is refused, not told to push again.

    The refusal follows the lookup of an earlier verdict on the same commit, so
    a commit a collaborator's ``ci:full`` already proved keeps it.

    Mutation proof: deleting the untrusted-author refusal from the gate's
    verdict step makes this fail on the missing refusal; restoring it makes
    this pass.
    """
    raw_gate = workflows.document(Workflow.MERGE_GATE)["jobs"][GATE_JOB]
    assert raw_gate["env"]["ASSOCIATION"] == (
        "${{ github.event.pull_request.author_association }}"
    ), "the gate no longer reads the pull request author's association"
    gate = next(
        job
        for job in workflows.load_jobs(Workflow.MERGE_GATE)
        if job.job_id == GATE_JOB
    )
    script = str(
        next(
            step
            for step in gate.steps
            if step.get("name") == "Every full check passed on this commit"
        )["run"]
    )
    marker = 'case "${ASSOCIATION}" in OWNER | COLLABORATOR) ;;'
    assert marker in script, (
        "the gate no longer refuses a commit by an author who is neither the "
        "owner nor a collaborator"
    )
    refusal = script.index(marker)
    assert script.index("head_sha=$HEAD_SHA") < refusal, (
        "an untrusted author's commit a collaborator's ci:full already proved "
        "must keep its verdict"
    )
    assert refusal < script.index("nothing has measured"), (
        "an untrusted author's commit must be refused by name, not told to push"
    )


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
    raw_gate = workflows.document(workflow)["jobs"][job_id]
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
    for name, loaded in workflows.documents():
        raw_jobs = loaded.get("jobs")
        if not isinstance(raw_jobs, dict):
            continue
        calling = {
            str(job_id)
            for job_id, body in cast("dict[object, object]", raw_jobs).items()
            if isinstance(body, dict)
            and cast("dict[object, object]", body).get("uses") == target
        }
        found.extend(
            (name, job) for job in workflows.load_jobs(name) if job.job_id in calling
        )
    return found


def test_the_hardware_tiers_are_unreachable_from_a_pull_request() -> None:
    """No pull request can start the MPS or CUDA tier.

    The tiers receive release secrets. They are reachable only through a
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
        f"a pull request can start {Workflow.HARDWARE} through {reachable}, "
        "handing a fork's code the tiers' secrets."
    )
