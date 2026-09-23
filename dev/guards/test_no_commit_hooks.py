"""The repository commits no hook-runner config and installs no git hook.

Gates run explicitly and in CI, never from a commit hook. A pre-commit run
stashes every unstaged tracked change, resets the tree, runs, and re-applies
the patch; when several workers share one tree, an edit or a held index lock
during that window destroys work nobody staged. Neither fast hooks nor
read-only hooks avoid the stash, so the only safe hook here is none.

The config has come back after deletion more than once, each time riding in on
a commit that was not about hooks. These checks make the next return fail the
build instead of silently re-arming the stash cycle for every checkout.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dev.init import plan

pytestmark = pytest.mark.unit

#: This repository has no shared `repo_root` fixture, so the root is derived
#: from this file's own location: `dev/guards/<this file>`.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every filename the hook runner discovers a config under, in its precedence
#: order. Any one of them tracked is a config the next install would arm.
HOOK_CONFIG_FILENAMES: tuple[str, ...] = (
    "prek.toml",
    ".pre-commit-config.yaml",
    ".pre-commit-config.yml",
)

#: Tokens whose presence in an init step's argv means the step touches hooks.
#: `install` alone is not one of them: the framework enrollment step runs
#: `vaultspec-core install`, which writes no git hook.
HOOK_INSTALLER_TOKENS: frozenset[str] = frozenset({"prek", "pre-commit"})

#: Surfaces that could run an installer on a developer's or a runner's behalf.
INSTALLER_SURFACES: tuple[str, ...] = ("justfile", ".github/workflows")


def _tracked(paths: tuple[str, ...]) -> list[str]:
    """Return the members of ``paths`` that git tracks at the repository root."""
    result = subprocess.run(
        ["git", "ls-files", "--", *paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.split()


def test_no_hook_runner_config_is_tracked() -> None:
    """Fail when any hook-runner config file is committed."""
    tracked = _tracked(HOOK_CONFIG_FILENAMES)
    assert tracked == [], f"hook-runner config committed: {tracked}"


def test_init_installs_no_git_hook() -> None:
    """Fail when a bootstrap step invokes a hook runner or a hook module."""
    steps = [
        *plan.PREFLIGHT,
        *(step for phase in plan.PHASE_PLAN.values() for step in phase.steps),
    ]
    offenders = [
        step.name
        for step in steps
        if HOOK_INSTALLER_TOKENS.intersection(step.argv)
        or any(arg.startswith("dev.init.hooks") for arg in step.argv)
    ]
    assert offenders == [], f"init steps that install git hooks: {offenders}"


def test_no_recipe_or_workflow_installs_a_hook() -> None:
    """Fail when a recipe or workflow runs a hook runner's install verb."""
    installs = tuple(runner + " install" for runner in HOOK_INSTALLER_TOKENS)
    offenders: list[str] = []
    for surface in INSTALLER_SURFACES:
        root = REPO_ROOT / surface
        files = [root] if root.is_file() else sorted(root.rglob("*.y*ml"))
        for path in files:
            text = path.read_text(encoding="utf-8")
            offenders.extend(
                f"{path.relative_to(REPO_ROOT).as_posix()}: {command}"
                for command in installs
                if command in text
            )
    assert offenders == [], f"hook installers found: {offenders}"
