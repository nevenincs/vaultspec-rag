"""One automatic pull-request workflow owns merge readiness.

A draft runs nothing. Opening or readying a pull request runs every merge
gate; a push to it runs the light lint; the commit that lands on main runs
every gate again. A release dispatch reaches the same workflow, so the
required context has one implementation for contributor and bot-authored
branches.
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
FULL_JOBS = frozenset({"lint", "tests", "tests-windows", "dependency-audit"})
LIGHT_JOBS = frozenset({"lint-light"})
GATE_RECIPES = {
    "check-all": frozenset({"linux"}),
    "check-light": frozenset({"linux"}),
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


def test_the_gate_is_reusable_and_measures_every_main_commit() -> None:
    """Release automation can call the gate, and every commit on main runs it.

    A pull-request push is proven by the light lint only, so the commit that
    lands is what the full gate measures; Release Please waits on that run.

    Mutation proof: dropping the ``push`` trigger makes this fail on the
    missing main push; restoring it makes this pass.
    """
    triggers = _triggers()
    push = triggers.get("push")
    assert isinstance(push, dict), f"{Workflow.MERGE_GATE} does not run on push"
    assert cast("dict[object, object]", push).get("branches") == ["main"]
    assert "workflow_call" in triggers
    assert "workflow_dispatch" in triggers


#: The repository the pull requests below are opened against.
_HOME = "owner/repo"

#: ``(label, event, payload, jobs that must run)``. Every other measuring job
#: must skip. ``scope`` is a dispatch's choice input; a call carries none.
_SCENARIOS: tuple[tuple[str, str, dict[str, object], frozenset[str]], ...] = (
    ("push to main", "push", {}, FULL_JOBS),
    ("dispatch", "workflow_dispatch", {"scope": "full"}, FULL_JOBS),
    ("dispatch without a scope", "workflow_dispatch", {"scope": None}, FULL_JOBS),
    ("light dispatch", "workflow_dispatch", {"scope": "light"}, LIGHT_JOBS),
    ("weekly schedule", "schedule", {}, frozenset({"dependency-audit"})),
    (
        "ready pull request opened",
        "pull_request",
        {"action": "opened", "draft": False, "head": _HOME},
        FULL_JOBS,
    ),
    (
        "ready pull request reopened",
        "pull_request",
        {"action": "reopened", "draft": False, "head": _HOME},
        FULL_JOBS,
    ),
    (
        "draft marked ready",
        "pull_request",
        {"action": "ready_for_review", "draft": False, "head": _HOME},
        FULL_JOBS,
    ),
    (
        "push to a ready pull request",
        "pull_request",
        {"action": "synchronize", "draft": False, "head": _HOME},
        LIGHT_JOBS,
    ),
    (
        "draft opened",
        "pull_request",
        {"action": "opened", "draft": True, "head": _HOME},
        frozenset(),
    ),
    (
        "push to a draft",
        "pull_request",
        {"action": "synchronize", "draft": True, "head": _HOME},
        frozenset(),
    ),
    (
        "draft pressed ci:full",
        "pull_request",
        {"action": "labeled", "label": "ci:full", "draft": True, "head": _HOME},
        FULL_JOBS,
    ),
    (
        "ready pressed ci:full",
        "pull_request",
        {"action": "labeled", "label": "ci:full", "draft": False, "head": _HOME},
        FULL_JOBS,
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
    (
        "push to a fork's pull request",
        "pull_request",
        {"action": "synchronize", "draft": False, "head": "stranger/repo"},
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
        "inputs.scope": payload.get("scope"),
    }


@pytest.mark.parametrize(
    ("event", "payload", "expected"),
    [(event, payload, expected) for _, event, payload, expected in _SCENARIOS],
    ids=[label for label, *_ in _SCENARIOS],
)
def test_pull_request_state_selects_the_cost_tier(
    event: str, payload: dict[str, object], expected: frozenset[str]
) -> None:
    """Drafts run nothing, opening or readying runs everything, a push runs
    the light lint, and a fork or an unrelated label starts nothing.

    Mutation proof: replacing the ``tests`` job's draft comparison with
    ``true`` made the draft cases fail naming ``tests``; adding
    ``synchronize`` to the full lanes' actions made the push case fail naming
    every full job; restoring each made every case pass.
    """
    running = {
        job_id
        for job_id, body in _jobs().items()
        if job_id != GATE_JOB
        and workflows.evaluate(str(body.get("if") or "true"), event, _bindings(payload))
        is workflows.TRUE
    }
    assert running == expected, f"runs {sorted(running)}, expected {sorted(expected)}"


def test_the_gate_needs_every_measuring_job_and_skips_only_a_draft() -> None:
    """The required check cannot skip a failure, and skips nothing but a draft.

    A skipped required check counts as passed. A draft cannot merge, so its
    skip is harmless; on any other occasion a skip would pass a commit nothing
    measured, so the gate must run there - including after a cancellation,
    which is what ``always()`` buys.

    Mutation proof: deleting the draft clause made the draft cases fail as
    reachable; replacing ``always()`` with ``success()`` failed the prefix
    check; restoring each made this pass.
    """
    jobs = _jobs()
    gate = jobs.get(GATE_JOB)
    assert isinstance(gate, dict)
    raw = cast("dict[object, object]", gate)
    assert raw.get("name") == GATE_CHECK
    needs = raw.get("needs")
    needed = set(cast("list[str]", needs)) if isinstance(needs, list) else set()
    measuring = {str(job_id) for job_id in jobs} - {GATE_JOB}
    assert needed == measuring, (
        f"the gate needs {sorted(needed)}, but measuring jobs are {sorted(measuring)}"
    )
    condition = " ".join(str(raw.get("if") or "").split())
    assert condition.startswith("always() &&"), (
        f"the gate runs under {condition!r}; a cancelled run must still reach it"
    )
    findings: list[str] = []
    for label, event, payload, _expected in _SCENARIOS:
        verdict = workflows.evaluate(condition, event, _bindings(payload))
        skips = payload.get("draft") is True and payload.get("label") != "ci:full"
        if skips and verdict is not workflows.FALSE:
            findings.append(f"{label}: the gate runs on a draft ({verdict})")
        if not skips and verdict is workflows.FALSE:
            findings.append(f"{label}: the gate skips, which passes the commit")
    assert not findings, "\n".join(findings)


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
