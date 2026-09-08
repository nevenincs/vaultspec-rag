"""What initializing THIS repository means.

The only file in :mod:`dev.init` that differs between repositories. Everything
here is data: the host tools the workstation must already provide, the steps
each phase runs, and - the part that is easy to get wrong - the inputs whose
change makes a phase stale and the artifacts whose absence does the same.

``vaultspec-rag`` had no bootstrap recipe at all before this: the only way to
provision a worktree was to know that ``just deps-sync`` happened to be the
step, and the committed `.pre-commit-config.yaml` had no installer anywhere in
the repository, so every checkout silently bypassed its own hooks. Both are
closed here. ``deps sync`` stays as the dependency-management verb it is;
``init-python`` is the worktree-provisioning path to the same environment.

Stdlib-only, by the constraint stated in :mod:`dev.init`.
"""

from __future__ import annotations

import sys
from typing import Final

from dev.init.contract import Phase, Step
from dev.init.probe import Requirement

#: The ephemeral interpreter `init` is running on. Steps that are themselves
#: Python reuse it rather than assuming a `python` on PATH, because the whole
#: premise of this package is that the environment does not exist yet.
PY: Final = sys.executable

#: What the workstation must provide before `init` can do anything. `just` is
#: absent from this list on purpose: if `just` were missing, the recipe that
#: reached this code could not have run.
REQUIREMENTS: Final[tuple[Requirement, ...]] = (
    Requirement(
        command="uv",
        purpose="It resolves the locked Python environment.",
        install_url="https://docs.astral.sh/uv/getting-started/installation/",
    ),
)

#: Steps that run before any phase, on every entry point. Materializing `.env`
#: belongs here rather than in `init-tools` because a worktree without one is
#: under-configured for tools that read it, including `just` itself in the
#: repositories that set `dotenv-load`. The rule is uniform across the fleet.
PREFLIGHT: Final[tuple[Step, ...]] = (
    Step(
        name="dotenv",
        argv=(PY, "-m", "dev.init.dotenv", ".env.example", ".env"),
        summary="Provision .env from .env.example when it is absent.",
    ),
)

PYTHON = Phase(
    name="python",
    summary="Resolve the locked Python development toolchain into .venv.",
    steps=(
        Step(
            name="uv-sync",
            argv=("uv", "sync", "--locked", "--group", "dev"),
            summary="Install the locked dev dependency group.",
        ),
    ),
    inputs=("uv.lock", "pyproject.toml", ".python-version"),
    artifacts=(".venv",),
)

NODE = Phase(
    name="node",
    summary="Restore the pinned Node dependency graph.",
    skip_reason="this repository has no Node dependency graph",
)

TOOLS = Phase(
    name="tools",
    summary="Enroll the Vaultspec framework and install the committed git hooks.",
    steps=(
        Step(
            name="framework-install",
            argv=("uv", "run", "--no-sync", "vaultspec-core", "install", "--force"),
            summary="Rebuild the gitignored install manifest from tracked config.",
        ),
        Step(
            name="hook-runner",
            argv=(PY, "-m", "dev.init.hooks", ".pre-commit-config.yaml"),
            summary="Install the committed hooks, or report that none can be.",
            advisory=True,
        ),
    ),
    inputs=("uv.lock", ".pre-commit-config.yaml"),
    artifacts=(".vaultspec/providers.json",),
)

#: The phases, keyed by name. The runner reads this and nothing else.
PHASE_PLAN: Final[dict[str, Phase]] = {
    "python": PYTHON,
    "node": NODE,
    "tools": TOOLS,
}
