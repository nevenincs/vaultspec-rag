"""The test-worker bound is set on the step that runs the suite, or it is not set.

A fleet runner's admission hook exports ``PYTEST_XDIST_AUTO_NUM_WORKERS`` for
every later step: one worker for each CPU it admitted the job with. It writes
that after the job's own ``env:`` has been read, so a value declared at job or
workflow level is replaced and the job runs with the hook's count, whatever
the workflow says. Only a step's own ``env:`` is applied after the hook.

The bound matters because the admitted CPU is a hard cap on the job's whole
process tree. One worker per admitted CPU fills the cap with test workers, and
every browser, server and child interpreter a test starts then waits its turn.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from dev.guards import _workflows as workflows
from dev.guards._ci_names import Workflow

pytestmark = [pytest.mark.unit, pytest.mark.repo]

BOUND = "PYTEST_XDIST_AUTO_NUM_WORKERS"

#: The recipe that runs a parallel suite, and so the step the bound belongs on.
SUITE_RECIPE = "test-python"


def _env(mapping: object) -> dict[str, object]:
    """Return the ``env:`` of a workflow, job or step mapping."""
    declared = cast("dict[str, Any]", mapping).get("env") if mapping else None
    return cast("dict[str, object]", declared) if isinstance(declared, dict) else {}


def _suite_steps(job: workflows.Job) -> list[dict[str, Any]]:
    """Return the steps of *job* that run the parallel suite."""
    return [
        step
        for step in job.steps
        if any(
            line.split()[:2] == ["just", SUITE_RECIPE]
            for line in str(step.get("run") or "").splitlines()
        )
    ]


def test_no_workflow_or_job_declares_a_bound_the_runner_would_replace() -> None:
    """A bound above the step level is one the admission hook overrides.

    Mutation proof: declaring the bound in the Windows job's ``env:`` made
    this fail naming that job; removing it made this pass.
    """
    findings: list[str] = []
    for name, document in workflows.documents():
        if BOUND in _env(document):
            findings.append(f"{name} declares {BOUND} for the whole workflow")
        jobs = cast("dict[str, Any]", document.get("jobs") or {})
        findings += [
            f"{name}:{job_id} declares {BOUND} for the whole job"
            for job_id, body in jobs.items()
            if BOUND in _env(body)
        ]
    assert not findings, (
        "the runner's admission hook exports its own value after these are "
        "read, so they never take effect:\n" + "\n".join(findings)
    )


def test_every_suite_step_bounds_its_own_workers() -> None:
    """Each step that runs the parallel suite carries the bound itself.

    Mutation proof: deleting the ``env:`` from the Windows suite step made
    this fail naming that step; restoring it made this pass.
    """
    steps = [(job, step) for job in workflows.load_jobs() for step in _suite_steps(job)]
    assert steps, f"no step runs `just {SUITE_RECIPE}`; this guard checks nothing"
    unbounded = [
        f"{job.workflow}:{job.job_id}: {step.get('name')}"
        for job, step in steps
        if not str(_env(step).get(BOUND) or "").isdigit()
    ]
    assert not unbounded, (
        f"these steps run the suite with one worker per admitted CPU, because "
        f"they do not set {BOUND} themselves:\n" + "\n".join(unbounded)
    )


def test_windows_correctness_has_a_private_vm_and_child_headroom() -> None:
    """Host applications cannot consume the correctness job's TCP port pool.

    Mutation proof: restoring shared-host labels fails the VM assertion;
    raising the worker count to four fails the headroom assertion. Restoring
    the isolated two-worker configuration passes both.
    """
    job = next(
        job
        for job in workflows.load_jobs(Workflow.MERGE_GATE)
        if job.job_id == "tests-windows"
    )
    assert job.runners == (("windows-2025",),), (
        "Windows correctness requires a fresh Windows VM with its own TCP port pool"
    )
    steps = _suite_steps(job)
    assert len(steps) == 1, "the Windows correctness suite must run exactly once"
    assert _env(steps[0]).get(BOUND) == "2", (
        "Windows correctness must reserve CPU headroom for child processes"
    )
