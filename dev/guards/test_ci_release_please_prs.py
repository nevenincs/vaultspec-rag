"""The release App writes the proposal, and merging starts the proven cut."""

from __future__ import annotations

import json
import re
import tomllib
from typing import Any, cast

import pytest

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

RELEASE_WORKFLOW = "release-please.yml"
GATE_WORKFLOW = "merge-gate.yml"
REF_EXPRESSION = "${{ inputs.ref || github.sha }}"
DEV_PROOF_STEP = "Require the dev server proof on this exact commit"

#: The release App token's exact inputs. The client id is a variable and the
#: key a secret; the token gets only the two grants a proposal writes with.
APP_TOKEN_INPUTS = {
    "client-id": "${{ vars.RELEASE_APP_CLIENT_ID }}",
    "private-key": "${{ secrets.RELEASE_APP_PRIVATE_KEY }}",
    "permission-contents": "write",
    "permission-pull-requests": "write",
}
APP_TOKEN = "${{ steps.proposal-token.outputs.token }}"

#: The ``extra-files`` entry that bumps the project's own version in uv.lock.
#: The ``.value`` segment is load-bearing: release-please's TOML reader wraps
#: each value, and the plain ``@.name`` filter matches nothing.
LOCK_ENTRY = {
    "type": "toml",
    "path": "uv.lock",
    "jsonpath": "$.package[?(@.name.value=='vaultspec-rag')].version",
}


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


def test_the_release_app_writes_the_proposal() -> None:
    """The proposal is opened with a token minted from the release App, only.

    A pull request the default token opens is authored by github-actions[bot],
    which the merge gate withholds, so the required check never reports.

    Mutation proof: replacing the proposal's token with
    ``${{ steps.proposal-token.outputs.token || secrets.GITHUB_TOKEN }}`` made
    this fail on the token assertion; pinning the token action to ``@v3`` failed
    the pin assertion; restoring each made this pass.
    """
    job = _job("release-please")
    permissions = job.get("permissions")
    assert isinstance(permissions, dict)
    assert "write" not in cast("dict[object, object]", permissions).values(), (
        "the proposal job's own token writes nothing; the App token does"
    )
    steps = cast("list[dict[str, Any]]", job["steps"])
    assert len(steps) == 2, [step.get("name") for step in steps]
    mint, proposal = steps
    assert mint.get("id") == "proposal-token"
    uses = str(mint.get("uses", ""))
    action, _, ref = uses.partition("@")
    assert action == "actions/create-github-app-token"
    assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{uses} is not pinned to a commit"
    assert mint.get("with") == APP_TOKEN_INPUTS
    assert str(proposal.get("uses", "")).startswith("googleapis/release-please-action@")
    options = cast("dict[str, object]", proposal["with"])
    assert options.get("token") == APP_TOKEN, (
        f"the proposal is written with {options.get('token')!r}, not the App token"
    )
    assert options.get("skip-github-release") is True


def test_nothing_else_writes_or_dispatches_for_the_proposal() -> None:
    """The proposal's own events prove it; nothing pushes to it or dispatches.

    A run another workflow dispatches is linked to no pull request, and a push
    with the default token raises no pull-request event, so either leaves the
    required check unreported on the proposal.

    Mutation proof: restoring the ``gh workflow run merge-gate.yml`` step in
    the proposal job made this fail naming it; restoring the default-token
    ``git push`` of the lock made this fail naming it; removing each made this
    pass.
    """
    findings: list[str] = []
    for job in workflows.load_jobs(RELEASE_WORKFLOW):
        for step in job.steps:
            script = str(step.get("run") or "")
            findings.extend(
                f"{job.job_id}: {step.get('name')!r} runs {banned}"
                for banned in (
                    "gh workflow run merge-gate.yml",
                    "gh workflow run devserver.yml",
                    "git push",
                    "github-actions[bot]",
                )
                if banned in script
            )
    assert not findings, "\n".join(findings)


def test_the_lock_bump_rides_in_release_pleases_commit() -> None:
    """release-please bumps uv.lock in its own commit, and the entry matches.

    The jsonpath must address exactly one locked package, the project itself,
    at the version pyproject.toml declares; otherwise the bump silently writes
    nothing and the proposal's lock is stale.

    Mutation proof: deleting the ``uv.lock`` entry from
    ``release-please-config.json`` made this fail on the entry assertion;
    restoring it made this pass.
    """
    root = workflows.repository_root()
    config = json.loads((root / "release-please-config.json").read_text("utf-8"))
    extra = config["packages"]["."]["extra-files"]
    assert LOCK_ENTRY in extra, f"release-please does not bump uv.lock: {extra}"
    project = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]
    lock = tomllib.loads((root / "uv.lock").read_text("utf-8"))
    locked = [
        package["version"]
        for package in lock["package"]
        if package["name"] == project["name"]
    ]
    assert locked == [project["version"]], (
        f"uv.lock locks {project['name']} at {locked}, pyproject.toml at "
        f"{project['version']}"
    )


def test_releases_stay_on_the_default_token() -> None:
    """The cut's tag and release raise no workflow event of their own.

    Mutation proof: passing the App token to the cut's release-please step made
    this fail on the token assertion; removing it made this pass.
    """
    releases = _release_please_steps("cut")
    assert len(releases) == 1
    options = releases[0].get("with")
    assert isinstance(options, dict)
    assert "token" not in cast("dict[object, object]", options), (
        "a tag or release created with any token but the default one starts "
        "the tag-triggered workflows a second time"
    )


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
    assert len(_release_please_steps("release-please")) == 1


def test_the_cut_proves_the_head_before_it_releases() -> None:
    """Automatic cuts require a proven parent, the audit and both accelerator tiers.

    The release head differs from its parent only by version files, so the
    gate proves that, requires the parent's merge-gate verdict, and audits the
    lock again instead of re-running the suites.

    Mutation proof: removing ``prove-hardware`` from the cut's ``needs`` fails
    naming it; dropping the version-only diff, the parent verdict or the audit
    fails naming it; restoring each makes this pass.
    """
    candidate = _job("candidate")
    assert "if" not in candidate
    gate = _job("prove-gate")
    assert "uses" not in gate, "the cut re-runs the suites its parent already passed"
    assert gate["permissions"].get("actions") == "read"
    steps = cast("list[dict[str, object]]", gate["steps"])
    scripts = "\n".join(str(step.get("run", "")) for step in steps)
    assert 'git diff --name-only "${parent}" "${SHA}"' in scripts, (
        "the cut does not prove the release head changes only version files"
    )
    proof_env = [
        cast("dict[str, object]", step.get("env", {})).get("GATE_WORKFLOW")
        for step in steps
    ]
    assert GATE_WORKFLOW in proof_env, (
        "the cut does not require its parent's merge-gate verdict"
    )
    # The weekly schedule audits alone under the same aggregate check name, so
    # only the parent's push run proves the suites.
    assert "event=push" in scripts, "the cut accepts a partial scheduled verdict"
    assert "just audit-deps" in scripts, "the cut releases an unaudited lock"
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


def test_readiness_requires_the_dev_server_on_the_exact_commit() -> None:
    """The required aggregate includes the canonical exact-SHA dev proof.

    A release call or dispatch carries no Dev Server run of its own, so the
    proof reads the newest run on the commit whatever event started it.

    Mutation proof: dropping the dev proof's SHA filter failed proof admission
    (exit 1); restoring an ``event=`` filter failed the any-event assertion;
    exact restoration passed (exit 0).
    """
    raw = workflows.document(GATE_WORKFLOW)["jobs"]["gate"]
    assert raw["permissions"]["actions"] == "write"
    steps = {step.get("name"): step for step in raw["steps"]}
    proof = str(steps[DEV_PROOF_STEP]["run"])
    assert "head_sha=$PROOF_SHA" in proof
    assert "event=" not in proof, "a dispatch or a call would wait on no run"
    assert '"completed success") exit 0' in proof
    assert "completed*)" in proof and "exit 1" in proof
    assert "github.event_name == 'pull_request'" in str(steps[DEV_PROOF_STEP]["if"])
    verdict = str(steps["Every full check passed on this commit"]["run"])
    assert 'if ($4 != "success") failed=1' in verdict
    assert "exit(failed || count != 8)" in verdict


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
