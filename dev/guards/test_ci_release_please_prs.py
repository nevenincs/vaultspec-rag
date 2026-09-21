"""Release-please dispatches the required gate on its final branch head."""

from __future__ import annotations

from typing import cast

import pytest
import yaml

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

RELEASE_WORKFLOW = "release-please.yml"
GATE_WORKFLOW = "merge-gate.yml"
DISPATCH_STEP = "Dispatch the merge gate for the release pull request"
REF_EXPRESSION = "${{ inputs.ref || github.sha }}"


def _document(workflow: str) -> dict[object, object]:
    """Return *workflow* parsed as YAML."""
    path = workflows.repository_root() / ".github" / "workflows" / workflow
    loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{workflow} is not a mapping"
    return cast("dict[object, object]", loaded)


def _triggers(workflow: str) -> dict[object, object]:
    """Return one workflow's trigger mapping."""
    document = _document(workflow)
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict), f"{workflow} has no `on:` mapping"
    return cast("dict[object, object]", triggers)


def test_release_please_dispatches_the_gate_after_its_last_branch_write() -> None:
    """The bot proves the lock-refreshed head without a label or operator.

    Mutation proof: deleting ``--field ref=`` makes this fail on the dispatch
    contract; restoring it makes this pass.
    """
    jobs = _document(RELEASE_WORKFLOW).get("jobs")
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
