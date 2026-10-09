"""Release proposals require full proof, and merging starts the release cut."""

from __future__ import annotations

from typing import Any, cast

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


def _job(job_id: str) -> dict[str, Any]:
    """Return one raw job of the release workflow."""
    jobs = workflows.document(RELEASE_WORKFLOW).get("jobs")
    assert isinstance(jobs, dict)
    job = cast("dict[object, object]", jobs).get(job_id)
    assert isinstance(job, dict), f"{RELEASE_WORKFLOW} has no job `{job_id}`"
    return cast("dict[str, Any]", job)


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
    contract, and deleting ``--field scope=full`` fails on the scope;
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
    assert "--field scope=full" in run


def test_main_push_selects_either_a_proposal_or_an_automatic_cut() -> None:
    """A merged release starts proof without an operator dispatch.

    Mutation proof: removing the push trigger failed trigger admission
    (exit 1); exact restoration passed (exit 0).
    """
    triggers = _triggers(RELEASE_WORKFLOW)
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"branches": ["main"]}
    candidate = _job("candidate")
    assert "if" not in candidate, "automatic pushes must select a release candidate"
    script = str(candidate["steps"][0]["run"])
    assert 'elif [ "${EVENT_NAME}" = "push" ]; then' in script
    assert script.index("--state merged") < script.index("--state open")
    proposal = _job("release-please")
    assert proposal["needs"] == "candidate"
    assert (
        proposal["if"] == "github.event_name == 'push' && !needs.candidate.outputs.sha"
    )
    proposals = _release_please_steps("release-please")
    assert len(proposals) == 1
    assert (
        cast("dict[str, object]", proposals[0]["with"])["skip-github-release"] is True
    )


def test_the_cut_proves_the_head_before_it_releases() -> None:
    """Automatic cuts require the full gate and both accelerator tiers.

    Mutation proof: removing ``prove-hardware`` from the cut's ``needs`` fails
    naming it; calling the gate with the light scope fails the call check;
    restoring each makes this pass.
    """
    candidate = _job("candidate")
    assert "if" not in candidate
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


def test_release_readiness_requires_dev_server_and_releases_held_checks() -> None:
    """The required aggregate includes the canonical exact-SHA dev proof.

    Mutation proof: dropping the dev proof's SHA filter failed proof admission
    (exit 1); exact restoration passed (exit 0).
    """
    proposal = _job("release-please")["steps"]
    scripts = [str(step.get("run", "")) for step in proposal]
    dev = next(
        i
        for i, script in enumerate(scripts)
        if "gh workflow run devserver.yml" in script
    )
    gate = next(
        i
        for i, script in enumerate(scripts)
        if "gh workflow run merge-gate.yml" in script
    )
    lock = next(
        i
        for i, step in enumerate(proposal)
        if step.get("name") == "Regenerate and push uv.lock"
    )
    assert lock < dev < gate
    assert '--ref "$HEAD_BRANCH"' in scripts[dev]
    raw = workflows.document(GATE_WORKFLOW)["jobs"]["gate"]
    assert raw["permissions"]["actions"] == "write"
    steps = {step.get("name"): step for step in raw["steps"]}
    proof = str(
        steps["Require the release dev server proof on this exact commit"]["run"]
    )
    assert "head_sha=$PROOF_SHA" in proof
    assert '"completed success") exit 0' in proof
    assert "completed*)" in proof and "exit 1" in proof
    approve = str(steps["Approve the proven release proposal checks"]["run"])
    assert '.author.is_bot and .author.login == "app/github-actions"' in approve
    assert '[ "$head" = "$SHA" ]' in approve
    assert "head_sha=$SHA&status=action_required" in approve
    assert "actions/runs/$run/approve" in approve
    verdict = str(steps["Every full check passed on this commit"]["run"])
    assert "event=workflow_dispatch&head_sha=$HEAD_SHA" in verdict
    assert 'length == 5 and all(.[]; .conclusion == "success")' in verdict


def test_release_result_refuses_a_skipped_selected_path() -> None:
    """The orchestrator reports failure when any mandatory stage did not pass.

    Mutation proof: removing hardware from the final comparison failed this
    contract (exit 1); exact restoration passed (exit 0).
    """
    result = _job("result")
    assert result["if"] == "always()"
    assert set(result["needs"]) == {
        "candidate",
        "release-please",
        "prove-gate",
        "prove-hardware",
        "cut",
    }
    script = str(result["steps"][0]["run"])
    assert '"$CANDIDATE_RESULT" != success' in script
    assert (
        '"$GATE_RESULT $HARDWARE_RESULT $CUT_RESULT" != "success success success"'
        in script
    )
    assert '"$PROPOSAL_RESULT" != success' in script
