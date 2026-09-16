"""Which lane measures what: pull requests are cheap, the merge queue is full.

The default branch only accepts changes through the merge queue, so the merge
group is the one run whose verdict decides what lands. Every push to a branch
under review pays for the pull-request lane, so that lane answers only the
cheap static questions. A push to the default branch measures nothing: the
merge queue already measured that exact tree.

Each property is invisible from one job. A heavy recipe added to a job the
pull request reaches, or a push trigger restored at the top of the file,
reads as an ordinary edit and silently changes what every contributor pays.
"""

from __future__ import annotations

import pytest

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

WORKFLOW = "ci.yml"

#: Everything the pull-request lane may measure.
PULL_REQUEST_RECIPES = frozenset({"check-python", "check-type"})

#: What the merge queue must run, and on which platforms.
MERGE_QUEUE_RECIPES = {
    "check-all": frozenset({"linux"}),
    "test-python": frozenset({"linux", "windows"}),
    "audit-deps": frozenset({"linux"}),
}


def _platforms_by_recipe(event: str) -> dict[str, set[str]]:
    """Return ``recipe -> platforms`` for every measuring recipe *event* runs."""
    found: dict[str, set[str]] = {}
    for job in workflows.load_jobs(WORKFLOW):
        for recipe in job.measuring_recipes_on(event):
            found.setdefault(recipe, set()).update(job.platforms)
    return found


def test_a_push_to_the_default_branch_triggers_nothing() -> None:
    """The merge box has no push trigger.

    Mutation proof: restoring ``push: branches: [main]`` to the workflow's
    ``on:`` makes this fail naming ``push``; removing it makes this pass.
    """
    events = workflows.workflow_events(WORKFLOW)
    assert "push" not in events, (
        f"{WORKFLOW} triggers on push ({events}). The merge queue already "
        "measured the tree that lands, so a push run repeats its verdict after "
        "the merge."
    )
    assert "merge_group" in events, (
        f"{WORKFLOW} does not trigger on merge_group ({events}), so nothing "
        "measures a change before it reaches the default branch."
    )


def test_the_pull_request_lane_runs_only_static_checks() -> None:
    """A pull request runs style and types, and nothing heavier.

    Mutation proof: adding a ``pull_request`` clause to the Windows job's
    ``if:`` makes this fail naming ``test-python``; removing it makes this
    pass.
    """
    running = _platforms_by_recipe("pull_request")
    extra = sorted(set(running) - PULL_REQUEST_RECIPES)
    assert not extra, (
        f"a pull request runs {extra}, beyond the static lane "
        f"{sorted(PULL_REQUEST_RECIPES)}. Heavy work belongs to the merge queue."
    )
    missing = sorted(PULL_REQUEST_RECIPES - set(running))
    assert not missing, f"a pull request no longer runs {missing}"


def test_the_merge_queue_runs_every_gate_on_every_platform() -> None:
    """The merge group runs every gating dimension and the full suites.

    The full accelerator-free suite on Windows contains the provisioning
    proofs and every test whose path, lock or process behaviour differs
    there, so a narrower Windows lane would pass the queue over coverage that
    never ran.

    Mutation proof: replacing the Windows job's ``test-python`` step with the
    ``test-fast`` subset makes this fail naming ``test-python`` and
    ``windows``; restoring the step makes this pass.
    """
    running = _platforms_by_recipe("merge_group")
    findings = [
        f"`just {recipe}` runs on {sorted(running.get(recipe, set()))}, "
        f"expected {sorted(platforms)}"
        for recipe, platforms in sorted(MERGE_QUEUE_RECIPES.items())
        if not platforms <= running.get(recipe, set())
    ]
    assert not findings, (
        "The merge queue no longer measures everything before a change lands.\n\n"
        + "\n".join(findings)
    )
