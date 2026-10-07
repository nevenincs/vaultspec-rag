"""A recipe a Windows job runs must pass its arguments bare.

On Windows the justfile hands every recipe line to ``cmd.exe /c``, and the
``just`` version the workflows pin escapes a double quote on that path instead
of passing it through. A recipe that wraps an interpolation in quotes therefore
reaches its command with the quotes as literal characters of the argument: the
directory it names does not exist, and the step fails on a path nobody typed.

Linux and macOS run the same line through ``sh``, where the quotes are syntax,
so the recipe passes on three of four release targets and the fourth fails only
at a release cut. Recipes no Windows job runs may quote freely.
"""

from __future__ import annotations

import pytest

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]


def test_no_recipe_a_windows_job_runs_quotes_an_argument() -> None:
    """Every recipe line reachable from a Windows runner is free of quotes.

    Mutation proof: quoting ``{{outdir}}`` in ``release-monitor`` made this
    fail naming the binaries build job and that recipe; removing the quotes
    made it pass.
    """
    bodies = workflows.recipe_bodies()
    findings = sorted(
        {
            f"{job.workflow}:{job.job_id} runs `just {recipe}`, whose body "
            f"quotes an argument: {line}"
            for job in workflows.load_jobs()
            if "windows" in job.platforms
            for _, recipe in job.recipes()
            for line in bodies.get(recipe, ())
            if '"' in line
        }
    )
    assert not findings, "\n".join(findings)
