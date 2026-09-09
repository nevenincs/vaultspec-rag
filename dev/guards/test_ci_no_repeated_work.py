"""Nothing in the merge box runs twice.

THE GROUND TRUTH THIS IS WRITTEN AGAINST. The fleet has one Linux runner and
one Windows runner, shared across every repository in the account. Every job
is serial. Splitting work across more jobs buys parallelism on a hosted fleet;
here it buys latency and nothing else, and a repeat is not a wasted core but a
wasted PLACE IN THE QUEUE that every other repository is waiting behind.

WHY REPEATS SURVIVE REVIEW. Each is spelled differently from the thing it
duplicates, so no two lines in the workflow look alike:

- A subset lane names five test files where the broad lane names a directory.
- A second platform's job runs a gate that reads only committed files, so it
  re-answers a question the first platform already answered.
- A dimension is hand-listed in a job beside twelve of its thirteen siblings,
  so the aggregate that would have named all thirteen never appears.

None of those compare equal as TEXT. All of them compare equal once each
recipe is expanded into the argument vectors it finally runs, which is what
:mod:`dev.guards._workflows` does through :mod:`dev.toolchain` - the same
registry the justfile delegates to, so this guard and the recipes cannot
disagree about what a recipe runs.

WHAT COUNTS AS A REPEAT. Two jobs reachable by ONE event, running one
identical argument vector, where the recipe is not declared platform-
sensitive. The event partition matters: a pull-request job and a push job
naming the same recipe are the deliberate two-tier split, not a repeat, and a
guard without that partition reports every such split and gets switched off.

WHAT THIS CANNOT CATCH, AND WHAT COVERS IT INSTEAD. A subset lane's argument
vector genuinely differs from the lane that contains it - five file paths
against one directory - so no vector comparison will ever equate them. Those
are named in :data:`SUBSET_LANES` with the recipe that covers each, and the
table is held honest two ways: the covering recipe must still exist, so an
exemption whose cover was renamed or deleted LAPSES rather than lingering; and
no single event may reach both the subset and its cover on one platform.
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: The workflow whose jobs are the merge box. Release-plane workflows publish
#: artifacts rather than measure the tree, so their jobs answer a different
#: question and are not compared here.
WORKFLOW = "ci.yml"

#: Recipe groups whose repetition is what this guard exists to find. A repeat
#: here is one measurement taken twice. ``setup`` is deliberately absent -
#: every job must provision its worktree, so every job runs ``init``.
MEASURING_GROUPS = frozenset({"check", "audit", "test"})

#: Recipes whose ANSWER depends on the platform, so running them on two
#: platforms is coverage rather than repetition. Each entry states what the
#: platform actually changes; a gate that only reads committed files can never
#: qualify, because the committed bytes are the same on every runner.
PLATFORM_SENSITIVE: dict[str, str] = {
    "test-python": (
        "the suite spawns real processes, takes real locks and resolves real "
        "paths, and every one of those differs between Windows and POSIX"
    ),
    "test-fast": "same as test-python, over the unit tier only",
    "test-provisioning": (
        "provisioning and holder detection are the most platform-divergent "
        "behaviour in the tree - a held file blocks removal on Windows only"
    ),
    "test-gpu": "one accelerator, one host",
    "test-mps": "Apple silicon only",
    "test-perf": "wall-clock assertions are a property of the machine",
    "test-all": "aggregates the lanes above",
}

#: Lanes that are a SELECTION WITHIN another lane rather than a lane of their
#: own. Their argument vectors differ, so nothing below would equate them.
SUBSET_LANES: dict[str, tuple[str, str]] = {
    "test-fast": (
        "test-python",
        "the unit tier is a marker-scoped selection of the accelerator-free lane",
    ),
    "test-provisioning": (
        "test-python",
        "five named files the accelerator-free lane already collects by directory",
    ),
}


def _measuring_recipes(job: workflows.Job, event: str) -> tuple[str, ...]:
    """Return the recipes *job* runs on *event* that measure the tree."""
    groups = workflows.recipe_groups()
    return tuple(
        recipe
        for recipe in job.recipes_on(event)
        if groups.get(recipe) in MEASURING_GROUPS
    )


def _commands_by_job(event: str) -> dict[str, list[tuple[str, str]]]:
    """Return ``command -> [(job id, recipe)]`` for everything *event* reaches."""
    index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for job in workflows.load_jobs(WORKFLOW):
        for recipe in _measuring_recipes(job, event):
            for command in workflows.named(workflows.final_commands(recipe)):
                index[command].append((job.job_id, recipe))
    return index


def _platforms(job_id: str) -> frozenset[str]:
    """Return the platforms a job by that id lands on."""
    for job in workflows.load_jobs(WORKFLOW):
        if job.job_id == job_id:
            return job.platforms
    return frozenset()


def test_no_command_runs_in_two_jobs() -> None:
    """No event reaches two jobs running one identical command.

    The exemption is narrow and is not a list of job names: a repeat is
    forgiven only where the RECIPE is declared platform-sensitive and the two
    jobs land on platforms that do not overlap. A gate reading committed files
    can never earn it, which is exactly the repeat that hides best - it looks
    like coverage and answers a question already answered.
    """
    findings: list[str] = []
    for event in workflows.workflow_events(WORKFLOW):
        for command, holders in sorted(_commands_by_job(event).items()):
            if len({job_id for job_id, _ in holders}) < 2:
                continue
            recipes = {recipe for _, recipe in holders}
            platforms = [_platforms(job_id) for job_id, _ in holders]
            distinct = all(
                left.isdisjoint(right)
                for index, left in enumerate(platforms)
                for right in platforms[index + 1 :]
            )
            if distinct and recipes <= PLATFORM_SENSITIVE.keys():
                continue
            where = ", ".join(
                f"{job_id} (just {recipe}, {'/'.join(sorted(_platforms(job_id)))})"
                for job_id, recipe in holders
            )
            findings.append(f"on {event}: `{command}` runs in {where}")

    assert not findings, (
        "The same command runs in more than one job of the same run.\n"
        "The fleet is one Linux runner and one Windows runner, serial, shared "
        "across every repository: a repeat costs a place in that queue and "
        "buys nothing.\n"
        "Fold the jobs together, or - only when the platform genuinely changes "
        "the answer - declare the recipe in PLATFORM_SENSITIVE with what it "
        "changes.\n\n" + "\n".join(findings)
    )


def test_every_subset_exemption_still_has_its_cover() -> None:
    """Each subset lane names a recipe that exists, so a stale exemption lapses.

    A table of exemptions is only honest while every entry is still true. The
    day the covering recipe is renamed, the entry stops describing anything
    and starts excusing a lane nothing covers - silently, because the lane it
    names still exists. Requiring the cover to resolve turns that into a
    failure at the moment of the rename.
    """
    recipes = workflows.recipe_bodies()
    missing = [
        f"{lane} claims cover from `{cover}`, which is not a recipe ({why})"
        for lane, (cover, why) in sorted(SUBSET_LANES.items())
        if cover not in recipes
    ]
    stale = [
        f"{lane} is exempted but is itself not a recipe"
        for lane in sorted(SUBSET_LANES)
        if lane not in recipes
    ]
    assert not (missing + stale), (
        "A subset-lane exemption no longer describes the justfile.\n"
        "Repoint it at the recipe that covers the lane now, or delete the "
        "entry so the lane is compared like everything else.\n\n"
        + "\n".join(missing + stale)
    )


def test_no_event_runs_a_subset_lane_beside_its_cover() -> None:
    """One event never runs both a subset lane and the lane containing it.

    This is the repeat no comparison of argument vectors can see: five named
    files against the directory that already holds them. Same platform is the
    condition - the same selection on a second platform is coverage, and the
    recipes carry their platform-sensitivity in PLATFORM_SENSITIVE above.
    """
    findings: list[str] = []
    for event in workflows.workflow_events(WORKFLOW):
        running: dict[str, list[workflows.Job]] = defaultdict(list)
        for job in workflows.load_jobs(WORKFLOW):
            for recipe in _measuring_recipes(job, event):
                running[recipe].append(job)
        for lane, (cover, why) in sorted(SUBSET_LANES.items()):
            for subset_job in running.get(lane, []):
                for cover_job in running.get(cover, []):
                    if subset_job.platforms.isdisjoint(cover_job.platforms):
                        continue
                    findings.append(
                        f"on {event}: {subset_job.job_id} runs `just {lane}` while "
                        f"{cover_job.job_id} runs `just {cover}` on "
                        f"{'/'.join(sorted(subset_job.platforms))} - {why}"
                    )

    assert not findings, (
        "A lane runs beside the lane that already contains it.\n"
        "Drop the subset job, or move the covering lane to an event that does "
        "not reach the subset.\n\n" + "\n".join(findings)
    )
