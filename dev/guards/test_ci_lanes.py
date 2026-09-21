"""One automatic pull-request workflow owns merge readiness.

Draft state selects cheap feedback; ready state selects every merge gate. A
release dispatch reaches the same workflow, so the required context has one
implementation for contributor and bot-authored branches.
"""

from __future__ import annotations

import re
from typing import cast

import pytest
import yaml

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

GATE_WORKFLOW = "merge-gate.yml"
GATE_JOB = "gate"
GATE_NAME = "Check: Merge gate (Linux)"
PULL_REQUEST_TYPES = [
    "opened",
    "reopened",
    "synchronize",
    "ready_for_review",
    "labeled",
]
FULL_JOBS = frozenset({"tests", "tests-windows", "dependency-audit"})
GATE_RECIPES = {
    "check-all": frozenset({"linux"}),
    "test-python": frozenset({"linux", "windows"}),
    "audit-deps": frozenset({"linux"}),
}


def _document(workflow: str) -> dict[object, object]:
    """Return *workflow* parsed as YAML."""
    path = workflows.repository_root() / ".github" / "workflows" / workflow
    loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{workflow} is not a mapping"
    return cast("dict[object, object]", loaded)


def _triggers() -> dict[object, object]:
    """Return the merge gate's ``on:`` mapping."""
    document = _document(GATE_WORKFLOW)
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict), f"{GATE_WORKFLOW} has no `on:` mapping"
    return cast("dict[object, object]", triggers)


def _jobs() -> dict[object, object]:
    """Return the merge gate's raw jobs mapping."""
    jobs = _document(GATE_WORKFLOW).get("jobs")
    assert isinstance(jobs, dict), f"{GATE_WORKFLOW} has no jobs"
    return cast("dict[object, object]", jobs)


def _condition(job_id: str) -> str:
    """Return one job condition with insignificant whitespace collapsed."""
    job = _jobs().get(job_id)
    assert isinstance(job, dict), f"{GATE_WORKFLOW} has no `{job_id}` job"
    condition = cast("dict[object, object]", job).get("if")
    assert isinstance(condition, str), f"{job_id} has no condition"
    return re.sub(r"\s+", " ", condition).strip()


def _platforms_by_recipe(event: str) -> dict[str, set[str]]:
    """Return ``recipe -> platforms`` for every measuring recipe *event* runs."""
    found: dict[str, set[str]] = {}
    for job in workflows.load_jobs(GATE_WORKFLOW):
        for recipe in job.measuring_recipes_on(event):
            found.setdefault(recipe, set()).update(job.platforms)
    return found


def test_pull_request_heads_start_the_gate_automatically() -> None:
    """Every lifecycle event that can create a merge candidate starts CI.

    Mutation proof: removing ``synchronize`` makes this fail with the complete
    actual type list; restoring it makes this pass.
    """
    pull_request = _triggers().get("pull_request")
    assert isinstance(pull_request, dict)
    types = cast("dict[object, object]", pull_request).get("types")
    assert types == PULL_REQUEST_TYPES, (
        f"{GATE_WORKFLOW} starts on {types!r}; expected {PULL_REQUEST_TYPES!r}"
    )


def test_the_gate_is_reusable_and_never_runs_on_push() -> None:
    """Release automation can call the gate while main does not rerun it."""
    triggers = _triggers()
    assert "push" not in triggers
    assert "workflow_call" in triggers
    assert "workflow_dispatch" in triggers


def test_pull_request_state_selects_the_cost_tier() -> None:
    """Drafts run lint and ready pull requests run every full measuring job.

    Mutation proof: replacing the full-job draft comparison with ``true``
    makes this fail naming every changed job; restoring it makes this pass.
    """
    lint = _condition("lint")
    assert "github.event.action != 'labeled'" in lint
    assert "github.event.label.name == 'ci:full'" in lint
    findings = [
        job_id
        for job_id in sorted(FULL_JOBS)
        if "github.event.pull_request.draft == false" not in _condition(job_id)
        or "github.event.label.name == 'ci:full'" not in _condition(job_id)
    ]
    assert not findings, (
        f"full jobs {findings} are not selected by ready state or ci:full"
    )


def test_the_gate_always_runs_and_needs_every_measuring_job() -> None:
    """The required check cannot skip a failure from a measuring job."""
    jobs = _jobs()
    gate = jobs.get(GATE_JOB)
    assert isinstance(gate, dict)
    raw = cast("dict[object, object]", gate)
    assert raw.get("name") == GATE_NAME
    assert raw.get("if") == "always()"
    needs = raw.get("needs")
    needed = set(cast("list[str]", needs)) if isinstance(needs, list) else set()
    measuring = {str(job_id) for job_id in jobs} - {GATE_JOB}
    assert needed == measuring, (
        f"the gate needs {sorted(needed)}, but measuring jobs are {sorted(measuring)}"
    )


def test_the_gate_runs_every_check_on_every_platform() -> None:
    """A ready pull request can reach every required recipe and platform."""
    running = _platforms_by_recipe("pull_request")
    findings = [
        f"`just {recipe}` runs on {sorted(running.get(recipe, set()))}, "
        f"expected {sorted(platforms)}"
        for recipe, platforms in sorted(GATE_RECIPES.items())
        if not platforms <= running.get(recipe, set())
    ]
    assert not findings, "The merge gate lost required coverage.\n\n" + "\n".join(
        findings
    )
