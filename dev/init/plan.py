"""What initializing THIS repository means.

Everything here is data: the host tools the workstation must already provide,
the steps each phase runs, and - the part that is easy to get wrong - the
inputs whose change makes a phase stale and the artifacts whose absence does
the same.

``vaultspec-rag`` had no bootstrap recipe at all before this: the only way to
provision a worktree was to know that ``just deps-sync`` happened to be the
step. That is closed here. ``deps sync`` stays as the dependency-management
verb it is; ``init-python`` is the worktree-provisioning path to the same
environment. No phase installs git hooks: gates run explicitly, and the commit
hook runner's stash-and-restore cycle is unsafe when workers share a tree.

One input is not a file: how much of the local inference stack to install is
read from :data:`GPU_STACK_ENV`, because it is a property of the machine and
the job, not of the checkout. A GPU workstation wants all of it by default; a
job that runs no GPU work wants none of it and must never download it.

Stdlib-only, by the constraint stated in :mod:`dev.init`.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
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

#: Chooses how much of the local inference stack - the `gpu` dependency group,
#: torch and its model libraries - `init-python` installs. Unset means ``full``.
GPU_STACK_ENV: Final = "VAULTSPEC_INIT_GPU_STACK"

#: ``full`` installs the group with the CUDA runtime torch pulls in, which a
#: workstation and the accelerator tiers need. ``types`` installs the group
#: without that runtime, so the type checkers read the libraries' annotations
#: on a host that never runs them; torch cannot be imported there. ``none``
#: omits the group: the accelerator-free suite and every gate but type checking
#: need nothing from it, and it is several gigabytes.
GPU_STACKS: Final = ("full", "types", "none")


def _cuda_runtime_packages() -> tuple[str, ...]:
    """Return the locked packages that make up the CUDA runtime.

    Read from the lock rather than listed, so a torch upgrade that adds or
    renames a runtime wheel is excluded without anyone editing this file.

    Returns:
        The package names, sorted, or nothing when the lock is unreadable -
        in which case the locked sync fails on its own and says why.
    """
    lock = Path(__file__).resolve().parents[2] / "uv.lock"
    try:
        packages = tomllib.loads(lock.read_text(encoding="utf-8")).get("package", [])
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    names = {str(package.get("name", "")) for package in packages}
    return tuple(
        sorted(
            name
            for name in names
            if name.startswith(("nvidia-", "cuda-")) or name == "triton"
        )
    )


def _uv_sync() -> Step:
    """Return the locked sync for the inference stack the environment asks for.

    Returns:
        The step. Its argv differs per stack, which is what makes switching
        stacks re-run the phase rather than trust a stamp written for another.

    Raises:
        SystemExit: When :data:`GPU_STACK_ENV` names no known stack. A typo
            must not fall back to the default and quietly install gigabytes.
    """
    stack = os.environ.get(GPU_STACK_ENV, "").strip().lower() or "full"
    argv: tuple[str, ...] = ("uv", "sync", "--locked", "--group", "dev")
    if stack == "full":
        argv = (*argv, "--group", "gpu")
    elif stack == "types":
        argv = (
            *argv,
            "--group",
            "gpu",
            *(
                arg
                for name in _cuda_runtime_packages()
                for arg in ("--no-install-package", name)
            ),
        )
    elif stack == "none":
        argv = (*argv, "--no-group", "gpu")
    else:
        raise SystemExit(
            f"{GPU_STACK_ENV}={stack!r} is not one of: {', '.join(GPU_STACKS)}"
        )
    return Step(
        name="uv-sync",
        argv=argv,
        summary=f"Install the locked dev group; inference stack: {stack}.",
    )


PYTHON = Phase(
    name="python",
    summary="Resolve the locked Python development toolchain into .venv.",
    steps=(_uv_sync(),),
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
    summary="Enroll the Vaultspec framework.",
    steps=(
        Step(
            name="framework-install",
            argv=("uv", "run", "--no-sync", "vaultspec-core", "install", "--force"),
            summary="Rebuild the gitignored install manifest from tracked config.",
        ),
        Step(
            name="actionlint-install",
            argv=(
                "uv",
                "run",
                "--no-sync",
                "python",
                "-m",
                "dev.actionlint",
                "--install",
            ),
            summary="Provision the pinned actionlint the workflow check uses.",
        ),
    ),
    inputs=("uv.lock",),
    artifacts=(".vaultspec/providers.json",),
)

#: The phases, keyed by name. The runner reads this and nothing else.
PHASE_PLAN: Final[dict[str, Phase]] = {
    "python": PYTHON,
    "node": NODE,
    "tools": TOOLS,
}
