"""The workflows spell the names :mod:`dev.ci_names` defines, and only those.

YAML cannot import, so the canon and the workflow are two copies of one fact
and this guard ties them together. A required check renamed on one side is a
check nobody reports, which GitHub renders as "expected" rather than failed;
a label spelled one way where it is pressed and another where it is released
leaves a button that fires once and never clears.

The ``protect-main`` ruleset's required context lives in repository settings,
outside the tree. :data:`~dev.ci_names.GATE_CHECK` is its value.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from dev.ci_names import (
    FULL_RUN_LABEL,
    GATE_CHECK,
    GATE_JOB,
    LABEL_ENV,
    SAME_REPO_CLAUSE,
    Workflow,
)
from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]


def _gate() -> workflows.Job:
    """Return the gate job, failing loudly when its id has moved."""
    for job in workflows.load_jobs(Workflow.MERGE_GATE):
        if job.job_id == GATE_JOB:
            return job
    pytest.fail(
        f"{Workflow.MERGE_GATE} has no job `{GATE_JOB}`. The canon names it "
        "`dev.ci_names.GATE_JOB`; repoint that, and the ruleset with it."
    )


def test_every_workflow_file_the_canon_names_exists() -> None:
    """Every :class:`~dev.ci_names.Workflow` member names a file on disk.

    A member left behind after a workflow is deleted or renamed is a guard
    reading a file that is not there, which shows up as a guard that stops
    asserting rather than one that fails.

    Mutation proof: adding ``RETIRED = "retired.yml"`` to the enum made this
    fail naming ``retired.yml``; removing it made this pass.
    """
    directory = workflows.repository_root() / ".github" / "workflows"
    present = {path.name for path in directory.glob("*.yml")}
    missing = sorted(member.value for member in Workflow if member.value not in present)
    assert not missing, (
        f"`dev.ci_names.Workflow` names {missing}, which no longer exist. A "
        "guard reading one asserts nothing at all."
    )


def test_every_workflow_file_on_disk_is_in_the_canon() -> None:
    """Every workflow file is named by the canon.

    The other direction, and the one that matters for a NEW workflow: a file
    the canon does not know is a file no guard reaches by name, so it runs
    without the naming, boundedness and repeat checks.

    Mutation proof: adding an empty ``scratch.yml`` made this fail naming it;
    deleting the file made this pass.
    """
    directory = workflows.repository_root() / ".github" / "workflows"
    known = {member.value for member in Workflow}
    unknown = sorted(
        path.name for path in directory.glob("*.yml") if path.name not in known
    )
    assert not unknown, (
        f"{unknown} are workflows `dev.ci_names.Workflow` does not name, so "
        "nothing addresses them by name. Add each to the enum."
    )


def test_the_gate_carries_the_name_branch_protection_requires() -> None:
    """The gate job's ``name:`` is :data:`~dev.ci_names.GATE_CHECK`.

    This is the copy that costs the most when it drifts: the ruleset requires
    the string, and a job renamed here reports a check the ruleset is not
    waiting for while the one it waits for is never reported at all.

    Mutation proof: renaming the gate job to ``Check: Merge verdict (Linux)``
    made this fail naming both strings; restoring the name made it pass.
    """
    gate = _gate()
    assert gate.name == GATE_CHECK, (
        f"the gate is named {gate.name!r}; the canon composes "
        f"{GATE_CHECK!r}, and `protect-main` requires that string on every "
        "pull request's head commit. Change the ruleset in the same breath."
    )


def test_the_gate_never_spells_its_own_check_name() -> None:
    """The gate's steps never spell the check name.

    The verdict used to query ``check-runs?check_name=...`` with the gate's
    name percent-encoded in the URL, which is a fourth spelling invisible to a
    search for the third. It asks this workflow for its own runs instead, so
    the name exists once, in ``name:``.

    Each step's ``run:`` is percent-DECODED before the name is looked for.
    Matching the encoded form instead means writing the encoding out here, and
    an encoder that stops one character short of the real one - the colon and
    the spaces, say, but not the parentheses - reports clean over exactly the
    query it was written to catch.

    Mutation proof: restoring the percent-encoded query made this fail naming
    the step, but only after the decode replaced a hand-written encoder that
    had missed ``%28``; removing the query made it pass.
    """
    offenders = [
        str(step.get("name") or "")
        for step in _gate().steps
        if GATE_CHECK in unquote(str(step.get("run") or ""))
    ]
    assert not offenders, (
        f"{offenders} spell the gate's own check name. Ask this workflow for "
        "its runs instead, so `name:` stays the only place it is written."
    )


def test_the_label_is_spelled_once_for_the_steps_that_read_it() -> None:
    """The workflow's ``env`` carries the label, and the steps read it there.

    A step that retypes the label is a step that can be corrected alone. The
    release step in particular: a label it fails to remove is a button that
    fires once and then does nothing, with no failure anywhere to say so.

    Mutation proof: inlining ``ci:full`` into the release step's ``run:`` made
    this fail naming that step; reading ``$FULL_RUN_LABEL`` made it pass.
    """
    document = workflows.document(Workflow.MERGE_GATE)
    declared = (document.get("env") or {}).get(LABEL_ENV)
    assert declared == FULL_RUN_LABEL, (
        f"{Workflow.MERGE_GATE} declares `env.{LABEL_ENV}` as {declared!r}; "
        f"the canon says {FULL_RUN_LABEL!r}."
    )
    offenders = [
        str(step.get("name") or "")
        for step in _gate().steps
        if FULL_RUN_LABEL in str(step.get("run") or "")
    ]
    assert not offenders, (
        f"{offenders} retype {FULL_RUN_LABEL!r} instead of reading "
        f"`${LABEL_ENV}`, which the workflow already carries."
    )


def test_the_release_step_presses_the_same_button_the_jobs_wait_for() -> None:
    """The step that releases the label runs on exactly the press, and no other.

    A step-level ``if:`` gets no ``env`` context, so the label is spelled here
    too. Wider, and the gate strips the label off runs the measuring jobs
    skipped; narrower, and the label stays on and cannot be pressed again.

    Mutation proof: widening the step to ``github.event.label.name != ''``
    made this fail naming the missing clause; restoring the press made it pass.
    """
    release = next(
        step
        for step in _gate().steps
        if str(step.get("name") or "").startswith("Release the")
    )
    condition = " ".join(str(release.get("if") or "").split())
    required = (
        "github.event_name == 'pull_request'",
        "github.event.action == 'labeled'",
        f"github.event.label.name == '{FULL_RUN_LABEL}'",
        SAME_REPO_CLAUSE,
    )
    missing = [clause for clause in required if clause not in condition]
    assert not missing, (
        f"the label is released under {condition!r}, which lacks {missing}"
    )
