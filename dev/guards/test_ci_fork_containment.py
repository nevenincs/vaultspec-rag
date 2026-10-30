"""Pull requests from forks are refused, and never reach the hardware tiers.

A ``pull_request`` run from a fork executes the fork's own copy of each
workflow, so no assertion over these files can stop a fork that rewrites
them; Actions approval for external contributors is what does. This guard
keeps this repository's own copy honest: the required verdict refuses a fork,
and the hardware tiers, which hold secrets, cannot be started by a pull
request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from dev.guards import _workflows as workflows
from dev.guards._ci_names import (
    GATE_JOB,
    SAME_REPO_CLAUSE,
    TRUSTED_AUTHOR_CLAUSE,
    Workflow,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: Events that run code a pull request's author controls.
PULL_REQUEST_EVENTS = frozenset({"pull_request", "pull_request_target"})

#: Applying a label takes triage rights; a bot applying `ci:full` does not count.
LABEL_BY_USER = "github.event.sender.type == 'User'"


def _containment_findings(jobs: Sequence[workflows.Job]) -> list[str]:
    """Return every pull-request-reachable job in *jobs* lacking containment.

    A job a pull request can reach must name the same-repository clause and
    the fleet's trusted-author clause, the latter spelled exactly; a
    ``ci:full`` path in it must count only a user's label. A folded YAML
    condition is compared with its line breaks collapsed.
    """
    findings: list[str] = []
    for job in jobs:
        events = PULL_REQUEST_EVENTS & set(workflows.workflow_events(job.workflow))
        if not any(job.reaches(event) for event in events):
            continue
        condition = " ".join((job.condition or "").split())
        if SAME_REPO_CLAUSE not in condition:
            findings.append(f"{job.workflow}:{job.job_id} (a fork's branch)")
        if TRUSTED_AUTHOR_CLAUSE not in condition:
            findings.append(f"{job.workflow}:{job.job_id}")
        elif "ci:full" in condition and LABEL_BY_USER not in condition:
            findings.append(f"{job.workflow}:{job.job_id} (a bot's label)")
    return findings


def test_only_a_trusted_author_or_a_users_label_reaches_the_fleet() -> None:
    """A pull request runs fleet jobs only for a trusted author or a user's label.

    Dependabot and every other author who is neither the owner, a
    collaborator nor the release App push branches of this repository, so the
    fork refusal never stops them, and the approval requirement for outside
    contributors does not cover them. Every job a pull request can reach, the
    gate included, carries the same-repository and author clauses, and any
    `ci:full` path in it counts only a user's label.

    Mutation proof: dropping the release App's term from the shared
    ``full_gate`` condition in ``merge-gate.yml`` made this fail naming
    ``merge-gate.yml:lint``, ``merge-gate.yml:tests``,
    ``merge-gate.yml:tests-windows`` and ``merge-gate.yml:code-scanning``;
    dropping the sender check from the gate's ``ci:full`` draft exemption made
    it fail naming ``merge-gate.yml:gate (a bot's label)``; restoring each made
    this pass.
    """
    untrusted = _containment_findings(workflows.load_jobs())
    assert not untrusted, (
        "these jobs run a pull request by any author on the self-hosted fleet, "
        f"Dependabot included: {untrusted}"
    )


def test_a_job_without_the_exact_clause_is_named() -> None:
    """The containment reader names each kind of uncontained job.

    A condition that admits the owner and collaborators but spells the
    author clause any other way is reported, as is one that drops the
    same-repository clause or counts a bot's label.

    Mutation proof: disabling the reader's same-repository check made this
    fail without the ``forked`` finding; restoring it made this pass.
    """
    jobs = [
        workflows.Job(
            workflow=Workflow.MERGE_GATE,
            job_id=job_id,
            name=job_id,
            runners=(("self-hosted",),),
            timeout=None,
            condition=condition,
            concurrency=None,
            steps=(),
        )
        for job_id, condition in (
            (
                "contained",
                f"{SAME_REPO_CLAUSE} && {TRUSTED_AUTHOR_CLAUSE} && "
                f"github.event.label.name == 'ci:full' && {LABEL_BY_USER}",
            ),
            (
                "respelled",
                f"{SAME_REPO_CLAUSE} && "
                "(github.event.pull_request.author_association == 'OWNER' || "
                "github.event.pull_request.author_association == 'COLLABORATOR')",
            ),
            ("forked", TRUSTED_AUTHOR_CLAUSE),
            (
                "bot-label",
                f"{SAME_REPO_CLAUSE} && {TRUSTED_AUTHOR_CLAUSE} && "
                "github.event.label.name == 'ci:full'",
            ),
        )
    ]
    assert _containment_findings(jobs) == [
        "merge-gate.yml:respelled",
        "merge-gate.yml:forked (a fork's branch)",
        "merge-gate.yml:bot-label (a bot's label)",
    ]


def test_no_workflow_runs_on_pull_request_target() -> None:
    """``pull_request_target`` runs with this repository's secrets and token.

    Mutation proof: adding ``pull_request_target:`` to ``merge-gate.yml``'s
    triggers made this fail naming ``merge-gate.yml``; removing it made this
    pass.
    """
    offending = [
        name
        for name, _ in workflows.documents()
        if "pull_request_target" in workflows.workflow_events(name)
    ]
    assert not offending, f"these workflows run on pull_request_target: {offending}"


def test_the_gate_refuses_an_untrusted_authors_commit_by_name() -> None:
    """An untrusted author's unproven commit is refused, not told to push again.

    The refusal follows the lookup of an earlier verdict on the same commit, so
    a commit a collaborator's ``ci:full`` already proved keeps it.

    Mutation proof: deleting the untrusted-author refusal from the gate's
    verdict step makes this fail on the missing refusal; restoring it makes
    this pass.
    """
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
    assert "applies $FULL_RUN_LABEL" not in script
    context = {
        "github.repository": "owner/repo",
        "github.event.pull_request.head.repo.full_name": "owner/repo",
        "github.event.pull_request.author_association": "CONTRIBUTOR",
        "github.event.pull_request.user.login": "dependabot[bot]",
        "github.event.pull_request.draft": False,
        "github.event.action": "labeled",
        "github.event.label.name": "ci:full",
    }
    assert (
        workflows.evaluate(gate.condition or "true", "pull_request", context)
        is workflows.FALSE
    ), "an untrusted author must never reach the gate"


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
    workflow call, and every caller is started by a tag or a dispatch, both of
    which require write access.

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
