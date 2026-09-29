"""One automatic pull-request workflow owns merge readiness.

Draft state selects cheap feedback; ready state selects every merge gate. A
release dispatch reaches the same workflow, so the required context has one
implementation for contributor and bot-authored branches.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from dev.ci_names import GATE_CHECK, GATE_JOB, Workflow
from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

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


def _triggers() -> dict[object, object]:
    """Return the merge gate's ``on:`` mapping."""
    triggers = workflows.triggers(workflows.document(Workflow.MERGE_GATE))
    assert isinstance(triggers, dict), f"{Workflow.MERGE_GATE} has no `on:` mapping"
    return cast("dict[object, object]", triggers)


def _jobs() -> dict[str, dict[str, Any]]:
    """Return the merge gate's raw jobs mapping."""
    jobs = workflows.document(Workflow.MERGE_GATE).get("jobs")
    assert isinstance(jobs, dict), f"{Workflow.MERGE_GATE} has no jobs"
    return cast("dict[str, dict[str, Any]]", jobs)


def _platforms_by_recipe(event: str) -> dict[str, set[str]]:
    """Return ``recipe -> platforms`` for every measuring recipe *event* runs."""
    found: dict[str, set[str]] = {}
    for job in workflows.load_jobs(Workflow.MERGE_GATE):
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
        f"{Workflow.MERGE_GATE} starts on {types!r}; expected {PULL_REQUEST_TYPES!r}"
    )


def test_the_gate_is_reusable_and_never_runs_on_push() -> None:
    """Release automation can call the gate while main does not rerun it."""
    triggers = _triggers()
    assert "push" not in triggers
    assert "workflow_call" in triggers
    assert "workflow_dispatch" in triggers


#: The repository the pull requests below are opened against.
_HOME = "owner/repo"

#: ``(label, event, pull request payload, jobs that must run)``. Every other
#: measuring job must skip.
_SCENARIOS: tuple[tuple[str, str, dict[str, object], frozenset[str]], ...] = (
    ("push to a branch", "workflow_dispatch", {}, frozenset({"lint"}) | FULL_JOBS),
    (
        "ready pull request",
        "pull_request",
        {"action": "opened", "draft": False, "head": _HOME},
        frozenset({"lint"}) | FULL_JOBS,
    ),
    (
        "draft pull request",
        "pull_request",
        {"action": "synchronize", "draft": True, "head": _HOME},
        frozenset({"lint"}),
    ),
    (
        "draft pressed ci:full",
        "pull_request",
        {"action": "labeled", "label": "ci:full", "draft": True, "head": _HOME},
        frozenset({"lint"}) | FULL_JOBS,
    ),
    (
        "unrelated label",
        "pull_request",
        {"action": "labeled", "label": "docs", "draft": False, "head": _HOME},
        frozenset(),
    ),
    (
        "fork pull request",
        "pull_request",
        {"action": "opened", "draft": False, "head": "stranger/repo"},
        frozenset(),
    ),
)


def _bindings(payload: dict[str, object]) -> dict[str, object]:
    """Return the context references a pull request *payload* resolves."""
    return {
        "github.repository": _HOME,
        "github.event.action": payload.get("action", ""),
        "github.event.label.name": payload.get("label", ""),
        "github.event.pull_request.draft": payload.get("draft", False),
        "github.event.pull_request.head.repo.full_name": payload.get("head", ""),
    }


@pytest.mark.parametrize(
    ("event", "payload", "expected"),
    [(event, payload, expected) for _, event, payload, expected in _SCENARIOS],
    ids=[label for label, *_ in _SCENARIOS],
)
def test_pull_request_state_selects_the_cost_tier(
    event: str, payload: dict[str, object], expected: frozenset[str]
) -> None:
    """Drafts run lint, ready pull requests and ``ci:full`` run everything,
    and a fork or an unrelated label starts nothing.

    Mutation proof: replacing the ``tests`` job's draft comparison with
    ``true`` made the draft case fail naming ``tests``; restoring it made
    every case pass.
    """
    running = {
        job_id
        for job_id, body in _jobs().items()
        if job_id != GATE_JOB
        and workflows.evaluate(str(body.get("if") or "true"), event, _bindings(payload))
        is workflows.TRUE
    }
    assert running == expected, f"runs {sorted(running)}, expected {sorted(expected)}"


def test_the_gate_always_runs_and_needs_every_measuring_job() -> None:
    """The required check cannot skip a failure from a measuring job."""
    jobs = _jobs()
    gate = jobs.get(GATE_JOB)
    assert isinstance(gate, dict)
    raw = cast("dict[object, object]", gate)
    assert raw.get("name") == GATE_CHECK
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
