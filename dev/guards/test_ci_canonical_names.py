"""The workflows spell the names :mod:`dev.ci_names` defines, and only those.

YAML cannot import. So the canon and the workflow are two copies of one fact,
and this guard is the mechanism that makes them one: it reads the workflow and
asserts the literals equal what the canon composes. A rename that touches the
module and not the file, or the file and not the module, fails here - before
it can reach the merge box, where the same disagreement is silent.

WHY SILENT. Branch protection matches a required check by STRING. A gate
renamed on one side is a check nobody reports, which GitHub renders as
"expected" rather than "failed", and the merge box shows a protected-branch
refusal with nothing red to explain it. A label spelled one way in the trigger
condition and another in the step that releases it leaves a button that fires
once and never clears. Neither shows up as a failure anywhere.

THE ONE COPY THIS CANNOT REACH is the required-status-check context in the
``protect-main`` ruleset, which lives in repository settings and is not in the
tree. :data:`~dev.ci_names.GATE_CHECK` is that context's value, and changing it
is a settings change as well as a code change. This guard cannot see the
setting; what it can do is make the value hard to change by accident, which is
why the name is COMPOSED from the grammar rather than typed.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from dev.ci_names import (
    FULL_RUN_CONDITION,
    FULL_RUN_LABEL,
    FULL_RUN_PRESSED,
    GATE_CHECK,
    GATE_JOB,
    JOB_NAME,
    LABEL_ENV,
    Workflow,
    normalise,
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


def _measuring_jobs() -> tuple[workflows.Job, ...]:
    """Return every job in the merge gate that is not the gate itself."""
    return tuple(
        job
        for job in workflows.load_jobs(Workflow.MERGE_GATE)
        if job.job_id != GATE_JOB
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
    the canon does not know is a file no guard reaches by name, so it joins
    the fleet without the naming, boundedness and repeat checks.

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


def test_every_measuring_job_waits_for_the_same_button() -> None:
    """The four measuring jobs carry one condition, and it is the canon's.

    GitHub gives a job-level ``if:`` no ``env`` context and honours no YAML
    anchor, so these four cannot share a token and each spells the condition
    out. Four copies is what the merge gate costs; four copies that AGREE is
    what this asserts. One job left behind on an older condition runs when the
    others skip, and the gate then passes a run that measured one dimension.

    Whitespace is normalised before comparing: a folded ``if:`` keeps or drops
    newlines by indentation, and a guard that failed on a re-indent would be
    a guard people satisfy by re-indenting.

    Mutation proof: changing the Windows job's label to ``ci:windows`` made
    this fail naming ``tests-windows``; restoring ``ci:full`` made it pass.
    """
    offenders = {
        job.job_id: job.condition
        for job in _measuring_jobs()
        if job.condition is None or normalise(job.condition) != FULL_RUN_CONDITION
    }
    assert not offenders, (
        "A measuring job does not wait for the same button as its siblings.\n"
        f"expected: {FULL_RUN_CONDITION}\n\n"
        + "\n".join(f"{job_id}: {condition}" for job_id, condition in offenders.items())
    )


def test_the_release_step_presses_the_same_button_the_jobs_wait_for() -> None:
    """The step that releases the label runs on exactly the press, and no other.

    A step-level ``if:`` gets no ``env`` context either, so this is a fifth
    place the label is spelled. If it drifts wider, the gate strips the label
    off runs the measuring jobs skipped, and the button clears without ever
    having fired; if it drifts narrower, the label stays on and the button
    cannot be pressed a second time.

    Mutation proof: widening the step to ``github.event.label.name != ''``
    made this fail printing both conditions; restoring the press made it pass.
    """
    release = next(
        step
        for step in _gate().steps
        if str(step.get("name") or "").startswith("Release the")
    )
    condition = normalise(str(release.get("if") or ""))
    assert condition == FULL_RUN_PRESSED, (
        "the label is released under a condition that is not the press.\n"
        f"expected: {FULL_RUN_PRESSED}\n"
        f"found:    {condition}"
    )


def test_the_canon_composes_a_name_the_grammar_accepts() -> None:
    """:data:`~dev.ci_names.GATE_CHECK` satisfies the fleet's job-name grammar.

    The canon composes job names and the same module's grammar validates them,
    which only holds while the two agree. A Kind or Platform added on one side
    that the other rejects is caught here rather than on the first job named
    with it.
    """
    assert JOB_NAME.fullmatch(GATE_CHECK), (
        f"the canon composes {GATE_CHECK!r}, which the fleet's job-name "
        "grammar rejects."
    )
