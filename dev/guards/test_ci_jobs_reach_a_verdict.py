"""Every job is bounded, and a commit on main always gets an answer.

TWO WAYS A RUN ENDS WITHOUT A VERDICT, AND BOTH LOOK LIKE SILENCE.

**It never ends.** A job with no ``timeout-minutes`` inherits a six-hour
ceiling, so a hung job reports nothing for six hours.

**It is cancelled before it starts.** ``cancel-in-progress: false`` protects a
run that has STARTED. It says nothing about a run that is still PENDING, and
GitHub cancels a previously pending run in the same concurrency group with no
switch to turn that off. So a push to main can kill the verdict on the push
before it - and the result reports as ``cancelled``, not ``failed``, so the
lost verdict raises no alarm at all.

The fix is to stop main's runs from sharing a group: put the COMMIT in the
group, and only on main, so pull requests keep the supersede-the-previous-push
behaviour that makes them cheap. That is one exact expression, stated once
here as :data:`MAIN_SHA_CLAUSE` and required verbatim, because an
approximation of it is the thing that silently stops working.
"""

from __future__ import annotations

import re
from typing import cast

import pytest

from dev.ci_names import MERGE_BOX
from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: The branch a merge lands on, and the one whose verdict is load bearing.
DEFAULT_BRANCH = "main"

#: The clause that keeps main's runs out of each other's concurrency group.
#: Required verbatim: every job that shares a group with another run of itself
#: needs the commit in that group, and only on main.
MAIN_SHA_CLAUSE = (
    "${{ github.ref == 'refs/heads/main' && format('-{0}', github.sha) || '' }}"
)

#: What ``cancel-in-progress`` may say on a workflow that reaches main. The
#: literal false is accepted because it cancels nothing anywhere; the
#: expression is the sharper form, which keeps pull requests superseding.
CANCEL_IN_PROGRESS = (False, "${{ github.ref != 'refs/heads/main' }}")


def _normalised(text: str) -> str:
    """Collapse an expression's whitespace so formatting is not a finding."""
    return re.sub(r"\s+", " ", text).strip()


def _reaches_default_branch(workflow: str) -> bool:
    """Whether *workflow* runs for the default branch.

    The merge box counts even without a push trigger: its verdict is what
    admits a commit to the default branch, and it runs there on schedule and
    dispatch.
    """
    if workflow in MERGE_BOX:
        return True
    triggers = workflows.triggers(workflows.document(workflow))
    push = (
        cast("dict[object, object]", triggers).get("push")
        if isinstance(triggers, dict)
        else None
    )
    if not isinstance(push, dict):
        return False
    branches = cast("dict[object, object]", push).get("branches")
    return isinstance(branches, list) and DEFAULT_BRANCH in branches


def _concurrency_declarations() -> list[tuple[str, str, dict[str, object]]]:
    """Return ``(workflow, where, concurrency)`` for every grouped run on main.

    Both levels are read. A workflow-level group covers every job at once,
    which is how the release automation is written, and a job-level group is
    how the merge box is written - the ``github.job`` context is empty inside
    a concurrency expression, so interpolating it collapses every job onto one
    shared group and they cancel each other.
    """
    found: list[tuple[str, str, dict[str, object]]] = []
    for name, document in workflows.documents():
        if not _reaches_default_branch(name):
            continue
        workflow_level = document.get("concurrency")
        if isinstance(workflow_level, dict):
            found.append(
                (
                    name,
                    "workflow",
                    cast("dict[str, object]", workflow_level),
                )
            )
        for job in workflows.load_jobs(name):
            if job.concurrency is not None:
                found.append((name, job.job_id, job.concurrency))
    return found


def _merge_box_jobs() -> tuple[workflows.Job, ...]:
    """Return every job in every merge-box workflow."""
    return tuple(job for workflow in MERGE_BOX for job in workflows.load_jobs(workflow))


def test_every_job_is_bounded() -> None:
    """Every job that runs steps declares its own ceiling.

    The default is six hours, so a hung job without one stays silent for six
    hours. A tight ceiling converts that silence into a failure someone sees.
    A job that only calls a reusable workflow is bounded by the jobs it calls.
    """
    findings = [
        f"{job.workflow}:{job.job_id} has no timeout-minutes"
        for job in workflows.load_jobs()
        if job.steps and job.timeout is None
    ]
    assert not findings, (
        "A job has no ceiling, so its default is six hours.\n\n" + "\n".join(findings)
    )


def test_no_merge_box_job_is_advisory() -> None:
    """Every merge-box job that fails also fails the run.

    A job-level ``continue-on-error`` shows a failed job while the run still
    concludes success, so a pull request merges over failures that everyone
    can see and nothing stops. A failing test is fixed, not reported around.

    Mutation proof: adding ``continue-on-error: true`` to ``tests-windows``
    makes this fail naming that job; removing it makes this pass again.
    """
    advisory = sorted(
        f"{job.workflow}:{job.job_id}"
        for job in _merge_box_jobs()
        if job.continue_on_error
    )
    assert not advisory, (
        f"merge-box jobs {advisory} declare continue-on-error, so their failures "
        "never fail the run. Fix what fails instead."
    )


def test_main_runs_never_share_a_concurrency_group() -> None:
    """A run on main is grouped by its own commit, so nothing supersedes it.

    Checked verbatim against one stated clause rather than by pattern: the
    failure this prevents is silent - a cancelled run reports as cancelled,
    not as failed - so an expression that is nearly right would leave no trace
    at all when it stopped working.
    """
    findings: list[str] = []
    for workflow, where, concurrency in _concurrency_declarations():
        group = _normalised(str(concurrency.get("group", "")))
        if _normalised(MAIN_SHA_CLAUSE) not in group:
            findings.append(
                f"{workflow}:{where} groups on {group!r}, which carries no "
                "commit on main - the next push cancels this one while it is "
                "still pending"
            )
        cancel = concurrency.get("cancel-in-progress")
        normalised_cancel = _normalised(cancel) if isinstance(cancel, str) else cancel
        allowed = tuple(
            _normalised(value) if isinstance(value, str) else value
            for value in CANCEL_IN_PROGRESS
        )
        if normalised_cancel not in allowed:
            findings.append(
                f"{workflow}:{where} sets cancel-in-progress to {cancel!r}; "
                f"expected one of {CANCEL_IN_PROGRESS!r}"
            )

    assert not findings, (
        "A run on main can be cancelled by the push after it.\n"
        "`cancel-in-progress: false` governs runs that have STARTED; GitHub "
        "also cancels a previously PENDING run in the same group, and there is "
        "no switch for that. Put the commit in the group, on main only:\n\n"
        f"    group: <literal>-${{{{ github.ref }}}}{MAIN_SHA_CLAUSE}\n"
        f"    cancel-in-progress: {CANCEL_IN_PROGRESS[1]}\n\n" + "\n".join(findings)
    )


def test_the_merge_box_groups_every_job_it_runs() -> None:
    """Workflow- or job-level grouping governs every merge-box job.

    A job with no concurrency at all is never cancelled, which is safe - but
    it is also never superseded on a pull request, so a branch pushed five
    times runs five copies of it. Declaring the group is what makes the
    main-only exemption above meaningful.
    """
    grouped = {
        workflow
        for workflow, where, _concurrency in _concurrency_declarations()
        if where == "workflow"
    }
    findings = [
        f"{job.workflow}:{job.job_id} declares no concurrency group"
        for job in _merge_box_jobs()
        if job.workflow not in grouped and job.concurrency is None
    ]
    assert not findings, (
        "A merge-box job is not in a concurrency group, so every push to a "
        "branch runs another copy of it.\n\n" + "\n".join(findings)
    )
