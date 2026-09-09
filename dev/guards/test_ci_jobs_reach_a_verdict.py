"""Every job is bounded, and a commit on main always gets an answer.

TWO WAYS A RUN ENDS WITHOUT A VERDICT, AND BOTH LOOK LIKE SILENCE.

**It never ends.** A job with no ``timeout-minutes`` inherits a SIX HOUR
ceiling, on a machine every repository in the account queues behind. And the
jobs most likely to hang are the ones a naive reader cannot even find: a job
whose ``runs-on`` is ``${{ matrix.runner }}`` matches no grep for
``self-hosted``, and those are the binary builds and the acquisition legs -
the longest-running jobs in the fleet. So the matrix is resolved before the
question is asked.

**It is cancelled before it starts.** ``cancel-in-progress: false`` protects a
run that has STARTED. It says nothing about a run that is still PENDING, and
GitHub cancels a previously pending run in the same concurrency group with no
switch to turn that off. On a saturated fleet a main run sits pending for a
long time: the last merge before this guard existed ran for 2h23m, and four of
its jobs were cancelled after sitting between 12 and 30 minutes each without
ever being assigned a runner. So each push to main kills the verdict on the
push before it - and the result reports as ``cancelled``, not ``failed``, so a
destroyed backstop raises no alarm at all.

The fix is to stop main's runs from sharing a group: put the COMMIT in the
group, and only on main, so pull requests keep the supersede-the-previous-push
behaviour that makes them cheap. That is one exact expression, stated once
here as :data:`MAIN_SHA_CLAUSE` and required verbatim, because an
approximation of it is the thing that silently stops working.
"""

from __future__ import annotations

import re

import pytest
import yaml

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
    """Whether a push to the default branch triggers *workflow*."""
    path = workflows.repository_root() / ".github" / "workflows" / workflow
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = document.get("on", document.get(True))
    push = triggers.get("push") if isinstance(triggers, dict) else None
    if not isinstance(push, dict):
        return False
    branches = push.get("branches")
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
    directory = workflows.repository_root() / ".github" / "workflows"
    for path in sorted(directory.glob("*.yml")):
        if not _reaches_default_branch(path.name):
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        workflow_level = document.get("concurrency")
        if isinstance(workflow_level, dict):
            found.append((path.name, "workflow", workflow_level))
        for job in workflows.load_jobs(path.name):
            if job.concurrency is not None:
                found.append((path.name, job.job_id, job.concurrency))
    return found


def test_every_self_hosted_job_is_bounded() -> None:
    """Every job landing on the fleet declares its own ceiling.

    The default is six hours on a machine the whole estate queues behind, and
    a job that never gets a runner sits until GitHub's 24-hour queue timeout
    retires it as ``cancelled`` - a word that reads as "somebody stopped this"
    rather than "the fleet is down". A tight ceiling converts that silence
    into a failure someone sees.
    """
    findings = [
        f"{job.workflow}:{job.job_id} runs on "
        f"{' | '.join('+'.join(labels) for labels in job.runners)} with no "
        "timeout-minutes"
        for job in workflows.load_jobs()
        if job.self_hosted and job.timeout is None
    ]
    assert not findings, (
        "A self-hosted job has no ceiling, so its default is six hours.\n"
        "Note that a matrix job names its runner through `${{ matrix.runner }}`: "
        "these are found by resolving the matrix, and they are the "
        "longest-running jobs in the fleet.\n\n" + "\n".join(findings)
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
    """Every merge-box job declares a group, so none is left ungoverned.

    A job with no concurrency at all is never cancelled, which is safe - but
    it is also never superseded on a pull request, so a branch pushed five
    times queues five copies of it on a serial fleet. Declaring the group is
    what makes the main-only exemption above meaningful.
    """
    findings = [
        f"ci.yml:{job.job_id} declares no concurrency group"
        for job in workflows.load_jobs("ci.yml")
        if job.concurrency is None
    ]
    assert not findings, (
        "A merge-box job is not in a concurrency group, so pushes to a branch "
        "queue one copy of it each on a serial fleet.\n\n" + "\n".join(findings)
    )
