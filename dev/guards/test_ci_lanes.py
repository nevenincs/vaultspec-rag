"""Which lane measures what: pushes are cheap, the merge gate is full.

Every push to a branch under review pays for ``ci.yml``, so that lane answers
only the cheap static questions. ``merge-gate.yml`` measures everything a
change must pass, runs only when a maintainer asks for it, and reports ONE
check that branch protection requires. A push to the default branch measures
nothing: the gate already measured that tree.

The gate's soundness rests on properties no single job shows. A push must not
start the gate workflow, so that a new commit carries no gate result and
cannot merge. The gate job must never be skipped, because a skipped required
check counts as passed. And it must depend on every measuring job, or a job
could fail without the verdict noticing.
"""

from __future__ import annotations

from typing import cast

import pytest
import yaml

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

CHEAP_LANE = "ci.yml"
GATE_WORKFLOW = "merge-gate.yml"

#: The job whose check branch protection requires.
GATE_JOB = "gate"
GATE_NAME = "Check: Merge gate (Linux)"

#: Everything the cheap lane may measure.
CHEAP_RECIPES = frozenset({"check-python", "check-type"})

#: What the gate must run, and on which platforms.
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


def _triggers(workflow: str) -> dict[object, object]:
    """Return *workflow*'s ``on:`` mapping."""
    document = _document(workflow)
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict), f"{workflow} has no `on:` mapping"
    return cast("dict[object, object]", triggers)


def _platforms_by_recipe(workflow: str, event: str) -> dict[str, set[str]]:
    """Return ``recipe -> platforms`` for every measuring recipe *event* runs."""
    found: dict[str, set[str]] = {}
    for job in workflows.load_jobs(workflow):
        for recipe in job.measuring_recipes_on(event):
            found.setdefault(recipe, set()).update(job.platforms)
    return found


def _gate_job() -> dict[object, object]:
    """Return the gate job's raw mapping, failing loudly when it is gone."""
    jobs = _document(GATE_WORKFLOW).get("jobs")
    assert isinstance(jobs, dict), f"{GATE_WORKFLOW} has no jobs"
    gate = cast("dict[object, object]", jobs).get(GATE_JOB)
    assert isinstance(gate, dict), f"{GATE_WORKFLOW} has no `{GATE_JOB}` job"
    return cast("dict[object, object]", gate)


@pytest.mark.parametrize("workflow", workflows.MERGE_BOX)
def test_a_push_triggers_nothing(workflow: str) -> None:
    """No merge-box workflow runs on push.

    Mutation proof: adding ``push: branches: [main]`` to ``ci.yml``'s ``on:``
    makes this fail naming ``push``; removing it makes this pass.
    """
    events = tuple(str(key) for key in _triggers(workflow))
    assert "push" not in events, (
        f"{workflow} triggers on push ({events}). The merge gate already "
        "measured the tree that lands, so a push run repeats its verdict after "
        "the merge."
    )


def test_only_a_label_starts_the_gate_on_a_pull_request() -> None:
    """A push to a pull request never starts the gate workflow.

    A pushed commit must carry no gate result, which is what blocks it from
    merging until someone asks for the full run. Any other activity type -
    ``synchronize`` above all - would either run everything on every push or
    report a skipped, and therefore passing, gate on an unmeasured commit.

    Mutation proof: changing the gate's ``types`` to
    ``[labeled, synchronize]`` makes this fail naming both; restoring
    ``[labeled]`` makes this pass.
    """
    pull_request = _triggers(GATE_WORKFLOW).get("pull_request")
    assert isinstance(pull_request, dict), (
        f"{GATE_WORKFLOW} must trigger on pull_request with explicit types"
    )
    types = cast("dict[object, object]", pull_request).get("types")
    assert types == ["labeled"], (
        f"{GATE_WORKFLOW} starts on pull_request activity {types!r}; only "
        "`labeled` keeps a pushed commit without a gate result."
    )


def test_the_gate_always_runs_and_needs_every_measuring_job() -> None:
    """The required check is never skipped and covers every job.

    Mutation proof: changing the gate's ``if:`` to ``${{ !cancelled() }}``
    makes this fail on the condition; restoring ``always()`` makes this pass.
    """
    gate = _gate_job()
    assert gate.get("name") == GATE_NAME, (
        f"the gate is named {gate.get('name')!r}; branch protection requires "
        f"{GATE_NAME!r}, so a rename leaves every pull request unmergeable"
    )
    assert gate.get("if") == "always()", (
        f"the gate runs under {gate.get('if')!r}. Anything but `always()` can "
        "skip it, and a skipped required check counts as passed."
    )
    needs = gate.get("needs")
    needed = set(cast("list[str]", needs)) if isinstance(needs, list) else set()
    measuring = {
        job.job_id
        for job in workflows.load_jobs(GATE_WORKFLOW)
        if job.job_id != GATE_JOB
    }
    missing = sorted(measuring - needed)
    assert not missing, f"the gate does not wait for {missing}"


def test_the_cheap_lane_runs_only_static_checks() -> None:
    """A push to a pull request runs style and types, and nothing heavier.

    Mutation proof: adding a ``just test-python`` step to ``ci.yml``'s lint
    job makes this fail naming ``test-python``; removing it makes this pass.
    """
    running = _platforms_by_recipe(CHEAP_LANE, "pull_request")
    extra = sorted(set(running) - CHEAP_RECIPES)
    assert not extra, (
        f"a push to a pull request runs {extra}, beyond the static lane "
        f"{sorted(CHEAP_RECIPES)}. Heavy work belongs to the merge gate."
    )
    missing = sorted(CHEAP_RECIPES - set(running))
    assert not missing, f"a push to a pull request no longer runs {missing}"


def test_the_gate_runs_every_check_on_every_platform() -> None:
    """The gate runs every gating dimension and the full suites.

    The full accelerator-free suite on Windows contains the provisioning
    proofs and every test whose path, lock or process behaviour differs
    there, so a narrower Windows lane would pass the gate over coverage that
    never ran.

    Mutation proof: replacing the gate's Windows ``test-python`` step with the
    ``test-fast`` subset makes this fail naming ``test-python`` and
    ``windows``; restoring the step makes this pass.
    """
    running = _platforms_by_recipe(GATE_WORKFLOW, "pull_request")
    findings = [
        f"`just {recipe}` runs on {sorted(running.get(recipe, set()))}, "
        f"expected {sorted(platforms)}"
        for recipe, platforms in sorted(GATE_RECIPES.items())
        if not platforms <= running.get(recipe, set())
    ]
    assert not findings, (
        "The merge gate no longer measures everything before a change lands.\n\n"
        + "\n".join(findings)
    )
