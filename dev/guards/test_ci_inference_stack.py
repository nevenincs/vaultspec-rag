"""Every job that initializes a worktree installs only the inference stack it uses.

`just init` installs the full local inference stack - torch, its model
libraries and several gigabytes of CUDA runtime - unless the job says
otherwise, because that is what a GPU workstation wants. A CI job that runs no
GPU work must say otherwise, or every run on a GPU-less runner downloads and
unpacks the stack for nothing. The job's own recipes decide which answer is
right, so the guard derives the requirement from them rather than from a list
of job names that a new job would not be on:

- a job running an accelerator lane needs ``full``;
- a job that type-checks needs ``types``: the checkers read the libraries'
  annotations, and nothing there imports the CUDA runtime;
- every other job needs ``none``.
"""

from __future__ import annotations

from typing import Any

import pytest

from dev.guards import _workflows as workflows
from dev.init.plan import GPU_STACK_ENV, GPU_STACKS

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: The recipes that provision the environment the inference stack lands in.
_INIT_RECIPES = frozenset({"init", "init-python"})

#: Recipes that run tests on a real accelerator, which loads the whole stack.
_ACCELERATOR_RECIPES = frozenset({"test-gpu", "test-mps", "test-perf", "test-all"})


def _type_checks(recipes: tuple[str, ...]) -> bool:
    """Whether any of *recipes* finally runs a type checker."""
    for recipe in recipes:
        for argv in workflows.final_commands(recipe):
            if "basedpyright" in argv:
                return True
            if any(argv[i : i + 2] == ("ty", "check") for i in range(len(argv))):
                return True
    return False


def _required(recipes: tuple[str, ...]) -> str:
    """Return the stack a job running *recipes* needs."""
    if _ACCELERATOR_RECIPES & set(recipes):
        return "full"
    if _type_checks(recipes):
        return "types"
    return "none"


def _env(mapping: object) -> dict[str, Any]:
    """Return a workflow, job or step ``env:`` block as a mapping."""
    env = mapping.get("env") if isinstance(mapping, dict) else None
    return env if isinstance(env, dict) else {}


def _declared(job: workflows.Job) -> str:
    """Return the stack *job*'s init step resolves, the way the runner does.

    A step's ``env`` overrides its job's, which overrides its workflow's. An
    unset value is the default the plan applies, ``full``.
    """
    document = workflows.document(job.workflow)
    body = (document.get("jobs") or {}).get(job.job_id)
    env = {**_env(document), **_env(body)}
    for step in job.steps:
        run = step.get("run")
        words = run.split() if isinstance(run, str) else []
        if words[:1] == ["just"] and words[1:2] and words[1] in _INIT_RECIPES:
            env.update(_env(step))
            break
    return str(env.get(GPU_STACK_ENV, "full")).strip().lower() or "full"


def _findings(jobs: tuple[workflows.Job, ...]) -> list[str]:
    """Name every initializing job whose declared stack is not the one it needs."""
    findings: list[str] = []
    for job in jobs:
        recipes = tuple(recipe for _, recipe in job.recipes())
        if not _INIT_RECIPES & set(recipes):
            continue
        declared = _declared(job)
        required = _required(recipes)
        if declared not in GPU_STACKS:
            findings.append(
                f"{job.workflow}:{job.job_id} sets {GPU_STACK_ENV}={declared!r}, "
                f"which is not one of {', '.join(GPU_STACKS)}"
            )
        elif declared != required:
            findings.append(
                f"{job.workflow}:{job.job_id} initializes with the '{declared}' "
                f"inference stack but runs {', '.join(recipes)}, which needs "
                f"'{required}'"
            )
    return findings


def test_every_initializing_job_installs_only_the_stack_it_uses() -> None:
    """No GPU-less job downloads torch; no accelerator job goes without it.

    Shown to fail both ways. Deleting the workflow-level
    ``VAULTSPEC_INIT_GPU_STACK: "none"`` from ``merge-gate.yml`` failed this
    test naming ``merge-gate.yml:tests`` as initializing with 'full' while
    needing 'none'. Setting the ``lint`` job's value to ``"none"`` failed it
    naming ``merge-gate.yml:lint`` as needing 'types'. Restoring each made it
    pass again.
    """
    jobs = workflows.load_jobs()
    required = {
        _required(recipes)
        for job in jobs
        if _INIT_RECIPES & set(recipes := tuple(r for _, r in job.recipes()))
    }
    assert required == set(GPU_STACKS), (
        f"initializing jobs need only {sorted(required)}; this guard no longer "
        "exercises every stack"
    )
    assert _findings(jobs) == []


def _job(job_id: str, *recipes: str) -> workflows.Job:
    """Build a job that runs *recipes*, one step each, in a synthetic workflow."""
    steps = tuple({"name": recipe, "run": f"just {recipe}"} for recipe in recipes)
    return workflows.Job("synthetic.yml", job_id, job_id, (), 30, None, None, steps)


def test_the_requirement_follows_what_the_job_runs() -> None:
    """The three answers come from the recipes, not from the job's name."""
    assert _required(("init", "test-gpu")) == "full"
    assert _required(("init", "check-all")) == "types"
    assert _required(("init", "test-python")) == "none"
    assert _required(("init", "build-python")) == "none"
    assert _findings((_job("never-inits", "test-python"),)) == []
