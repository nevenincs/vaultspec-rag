"""Release-please writes its pull request as an App and its releases as the token.

The two identities are load-bearing in opposite directions. A pull request the
default token opens or pushes to starts its workflows only after a maintainer
approves them in the Actions tab, so the release pull request must be written
by the release App for the merge gate to run on it at all. A tag or release the
default token creates raises no workflow event, so releases must stay on that
token or Publish would start twice: once from the explicit dispatch and once
from its tag trigger.
"""

from __future__ import annotations

import json
import tomllib
from typing import TYPE_CHECKING, Any, cast

import pytest

from dev.guards import _workflows as workflows

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = [pytest.mark.unit, pytest.mark.repo]

RELEASE_WORKFLOW = "release-please.yml"
GATE_WORKFLOW = "merge-gate.yml"
RELEASE_ACTION = "googleapis/release-please-action@"
APP_TOKEN_ACTION = "actions/create-github-app-token@"
RELEASE_STEP = "Create releases for merged release pull requests"
MINT_STEP = "Mint the release pull request token"
PROPOSAL_STEP = "Open or update the release pull request"
REF_EXPRESSION = "${{ inputs.ref || github.sha }}"


def _triggers(workflow: str) -> dict[object, object]:
    """Return one workflow's trigger mapping."""
    triggers = workflows.triggers(workflows.document(workflow))
    assert isinstance(triggers, dict), f"{workflow} has no `on:` mapping"
    return cast("dict[object, object]", triggers)


def _release_steps() -> list[dict[object, object]]:
    """Return the release-please job's steps, in order."""
    jobs = workflows.document(RELEASE_WORKFLOW).get("jobs")
    assert isinstance(jobs, dict)
    release = cast("dict[object, object]", jobs).get("release-please")
    assert isinstance(release, dict)
    steps = cast("dict[object, object]", release).get("steps")
    assert isinstance(steps, list)
    return [cast("dict[object, object]", step) for step in steps]


def _inputs(step: Mapping[Any, Any]) -> dict[object, object]:
    """Return one step's ``with:`` mapping, empty when it has none."""
    options = step.get("with")
    return cast("dict[object, object]", options) if isinstance(options, dict) else {}


def _named(
    steps: list[dict[object, object]], name: str
) -> tuple[int, dict[object, object]]:
    """Return the index and body of the step called *name*."""
    for index, step in enumerate(steps):
        if step.get("name") == name:
            return index, step
    raise AssertionError(f"{RELEASE_WORKFLOW} has no step named {name!r}")


def test_releases_use_the_default_token_and_run_before_the_proposal() -> None:
    """The tag stays eventless, and a merged proposal is tagged first.

    Mutation proof: passing ``token: ${{ steps.proposal-token.outputs.token }}``
    to the release step made this fail on the default-token assertion, and
    moving the release step below the proposal step made it fail on the
    ordering assertion; restoring each made it pass.
    """
    steps = _release_steps()
    release_index, release = _named(steps, RELEASE_STEP)
    proposal_index, _ = _named(steps, PROPOSAL_STEP)
    assert str(release.get("uses", "")).startswith(RELEASE_ACTION)
    assert release.get("id") == "release"
    options = _inputs(release)
    assert options.get("skip-github-pull-request") is True
    assert "token" not in options, (
        "the release step must create tags and releases with the default "
        "token, which raises no workflow event; any other token starts "
        "Publish a second time from its tag trigger"
    )
    assert release_index < proposal_index


def test_the_proposal_is_written_by_the_release_app_with_no_fallback() -> None:
    """Only the App's writes start the merge gate without an approval.

    Mutation proof: appending ``|| github.token`` to the proposal step's token
    made this fail on the exact-token assertion; restoring it made it pass.
    """
    steps = _release_steps()
    mint_index, mint = _named(steps, MINT_STEP)
    proposal_index, proposal = _named(steps, PROPOSAL_STEP)
    assert str(mint.get("uses", "")).startswith(APP_TOKEN_ACTION)
    assert mint_index < proposal_index
    mint_inputs = _inputs(mint)
    assert mint_inputs.get("client-id") == "${{ vars.RELEASE_APP_CLIENT_ID }}"
    assert mint_inputs.get("private-key") == "${{ secrets.RELEASE_APP_PRIVATE_KEY }}"
    assert mint_inputs.get("permission-contents") == "write"
    assert mint_inputs.get("permission-pull-requests") == "write"

    assert str(proposal.get("uses", "")).startswith(RELEASE_ACTION)
    options = _inputs(proposal)
    assert options.get("skip-github-release") is True
    assert options.get("token") == f"${{{{ steps.{mint.get('id')}.outputs.token }}}}"


def test_nothing_but_release_please_writes_the_release_branch() -> None:
    """One commit per proposal head, measured once by the pull-request gate.

    A second push to the release branch restarts the gate on a new head, and a
    dispatched gate is a second verdict racing the pull request's own for the
    same required check.

    Mutation proof: adding a step running ``git push`` made this fail naming
    that step; adding one running ``gh workflow run merge-gate.yml`` made it
    fail naming that step; removing each made it pass.
    """
    findings: list[str] = []
    for step in _release_steps():
        run = str(step.get("run", ""))
        uses = str(step.get("uses", ""))
        if uses.startswith("actions/checkout@") or "git push" in run:
            findings.append(f"{step.get('name')}: writes the release branch")
        if f"gh workflow run {GATE_WORKFLOW}" in run:
            findings.append(f"{step.get('name')}: dispatches a second gate")
    assert not findings, "\n".join(findings)


def test_the_lock_version_is_bumped_in_the_release_commit() -> None:
    """release-please's own commit keeps ``uv sync --locked`` passing.

    Mutation proof: renaming the package in the jsonpath filter made this fail
    on the exact-entry assertion; restoring it made it pass.
    """
    root = workflows.repository_root()
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    name = project["project"]["name"]
    config = json.loads(
        (root / "release-please-config.json").read_text(encoding="utf-8")
    )
    extra_files = config["packages"]["."]["extra-files"]
    lock_entries = [
        entry
        for entry in extra_files
        if isinstance(entry, dict) and entry.get("path") == "uv.lock"
    ]
    assert lock_entries == [
        {
            "type": "toml",
            "path": "uv.lock",
            "jsonpath": f"$.package[?(@.name.value=='{name}')].version",
        }
    ]

    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    versions = [p["version"] for p in lock["package"] if p["name"] == name]
    assert versions == [project["project"]["version"]], (
        f"uv.lock must record {name} exactly once, at the version release-please bumps"
    )


def test_every_gate_checkout_uses_the_requested_ref() -> None:
    """A manual dispatch measures the ref it names, not the default branch."""
    body = _triggers(GATE_WORKFLOW).get("workflow_dispatch")
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
            ref = _inputs(step).get("ref")
            if ref != REF_EXPRESSION:
                findings.append(f"{job.job_id}: ref={ref!r}")
    assert checkouts, f"{GATE_WORKFLOW} has no measuring checkouts"
    assert not findings, (
        "Gate jobs do not all validate the dispatched ref:\n\n" + "\n".join(findings)
    )
