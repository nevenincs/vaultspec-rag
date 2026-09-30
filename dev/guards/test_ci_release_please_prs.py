"""Release Please proposes on every green main and releases only when asked.

The proposal path dispatches the required gate on its final branch head and
never creates a release. The cut path, started by a dispatch alone, proves the
head with the full gate and both accelerator tiers before it merges and tags.
"""

from __future__ import annotations

from typing import cast

import pytest

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

RELEASE_WORKFLOW = "release-please.yml"
GATE_WORKFLOW = "merge-gate.yml"
DISPATCH_STEP = "Dispatch the merge gate for the release pull request"
REF_EXPRESSION = "${{ inputs.ref || github.sha }}"


def _triggers(workflow: str) -> dict[object, object]:
    """Return one workflow's trigger mapping."""
    triggers = workflows.triggers(workflows.document(workflow))
    assert isinstance(triggers, dict), f"{workflow} has no `on:` mapping"
    return cast("dict[object, object]", triggers)


def _job(job_id: str) -> dict[object, object]:
    """Return one raw job of the release workflow."""
    jobs = workflows.document(RELEASE_WORKFLOW).get("jobs")
    assert isinstance(jobs, dict)
    job = cast("dict[object, object]", jobs).get(job_id)
    assert isinstance(job, dict), f"{RELEASE_WORKFLOW} has no job `{job_id}`"
    return cast("dict[object, object]", job)


def _release_please_steps(job_id: str) -> list[dict[object, object]]:
    """Return the Release Please action steps of one job."""
    steps = _job(job_id).get("steps")
    assert isinstance(steps, list)
    return [
        cast("dict[object, object]", step)
        for step in steps
        if isinstance(step, dict)
        and str(step.get("uses", "")).startswith("googleapis/release-please-action@")
    ]


def test_release_please_dispatches_the_gate_after_its_last_branch_write() -> None:
    """The bot proves the lock-refreshed head without a label or operator.

    Mutation proof: deleting ``--field ref=`` makes this fail on the dispatch
    contract, and deleting ``--field scope=light`` fails on the scope;
    restoring each makes this pass.
    """
    jobs = workflows.document(RELEASE_WORKFLOW).get("jobs")
    assert isinstance(jobs, dict)
    release = cast("dict[object, object]", jobs).get("release-please")
    assert isinstance(release, dict)
    raw = cast("dict[object, object]", release)
    permissions = raw.get("permissions")
    assert isinstance(permissions, dict)
    assert cast("dict[object, object]", permissions).get("actions") == "write"
    steps = raw.get("steps")
    assert isinstance(steps, list)
    named = {
        str(step.get("name")): (index, step)
        for index, step in enumerate(steps)
        if isinstance(step, dict)
    }
    assert DISPATCH_STEP in named
    dispatch_index, dispatch = named[DISPATCH_STEP]
    lock_index, _ = named["Regenerate and push uv.lock"]
    assert dispatch_index > lock_index
    run = str(dispatch.get("run", ""))
    assert "gh workflow run merge-gate.yml" in run
    assert '--ref "${HEAD_BRANCH}"' in run
    assert '--field ref="${HEAD_BRANCH}"' in run
    assert "--field scope=light" in run


def test_the_proposal_never_releases_and_follows_a_green_main() -> None:
    """Merging changes accumulates a proposal; nothing is released unasked.

    Mutation proof: deleting ``skip-github-release: true`` fails the proposal
    assertion; dropping the ``conclusion == 'success'`` clause fails the
    trigger assertion; restoring each makes this pass.
    """
    triggers = _triggers(RELEASE_WORKFLOW)
    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    run = triggers["workflow_run"]
    assert isinstance(run, dict)
    assert cast("dict[object, object]", run).get("workflows") == ["RAG Merge Gate"]
    condition = " ".join(str(_job("release-please").get("if") or "").split())
    for clause in (
        "github.event_name == 'workflow_run'",
        "github.event.workflow_run.event == 'push'",
        "github.event.workflow_run.conclusion == 'success'",
    ):
        assert clause in condition, f"the proposal runs without {clause!r}"
    proposals = _release_please_steps("release-please")
    assert len(proposals) == 1
    options = proposals[0].get("with")
    assert isinstance(options, dict)
    assert cast("dict[object, object]", options).get("skip-github-release") is True


def test_the_cut_proves_the_head_before_it_releases() -> None:
    """Only a dispatch releases, and only after the gate and both tiers pass.

    Mutation proof: removing ``prove-hardware`` from the cut's ``needs`` fails
    naming it; calling the gate with the light scope fails the call check;
    restoring each makes this pass.
    """
    candidate = _job("candidate")
    assert candidate.get("if") == "github.event_name == 'workflow_dispatch'"
    gate = _job("prove-gate")
    assert gate.get("uses") == f"./.github/workflows/{GATE_WORKFLOW}"
    options = gate.get("with")
    assert isinstance(options, dict)
    assert "scope" not in cast("dict[object, object]", options), (
        "the cut must run the gate in full"
    )
    assert _job("prove-hardware").get("uses") == "./.github/workflows/hardware.yml"
    needs = _job("cut").get("needs")
    needed = set(cast("list[str]", needs)) if isinstance(needs, list) else set()
    missing = {"candidate", "prove-gate", "prove-hardware"} - needed
    assert not missing, f"the cut releases without {sorted(missing)}"
    releases = _release_please_steps("cut")
    assert len(releases) == 1
    options = releases[0].get("with")
    assert isinstance(options, dict)
    assert cast("dict[object, object]", options).get("skip-github-pull-request") is True


def test_every_gate_checkout_uses_the_requested_ref() -> None:
    """A release dispatch measures its branch rather than the default branch."""
    triggers = _triggers(GATE_WORKFLOW)
    for event in ("workflow_call", "workflow_dispatch"):
        body = triggers.get(event)
        assert isinstance(body, dict)
        inputs = cast("dict[object, object]", body).get("inputs")
        assert isinstance(inputs, dict) and "ref" in inputs

    findings: list[str] = []
    checkouts = 0
    for job in workflows.load_jobs(GATE_WORKFLOW):
        if job.job_id == "gate":
            continue
        for step in job.steps:
            if not str(step.get("uses", "")).startswith("actions/checkout@"):
                continue
            checkouts += 1
            options = step.get("with")
            ref = (
                cast("dict[object, object]", options).get("ref")
                if isinstance(options, dict)
                else None
            )
            if ref != REF_EXPRESSION:
                findings.append(f"{job.job_id}: ref={ref!r}")
    assert checkouts, f"{GATE_WORKFLOW} has no measuring checkouts"
    assert not findings, (
        "Gate jobs do not all validate the dispatched ref:\n\n" + "\n".join(findings)
    )
