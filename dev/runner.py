"""Process-execution primitives shared by every development verb.

Each step type below is a small, declarative description of one action. They
are data rather than code so :mod:`dev.toolchain` can state the toolchain as a
table, and so the platform-specific parts - executable resolution, Docker
fallback, environment overlay, working directory - are implemented once here
instead of being re-expressed in each recipe.

This module imports the standard library only. That is what lets the harness
behave identically on Windows, macOS, and Linux without a second shell dialect.
It replaced roughly 350 lines of backslash-joined PowerShell ``switch`` blocks
in the justfile, which ran through a bespoke ``scripts/run-just-recipe.ps1``
shim and carried a hazard documented three times in their own comments: a ``#``
anywhere inside such a block runs to the end of the joined logical line and
silently swallows every remaining case, closing braces included.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from dev.exit_codes import TOOL_MISSING as _TOOL_MISSING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: Re-exported from :mod:`dev.exit_codes`, the fleet-wide statement of what
#: every status means. Named here too because this module's callers already
#: read it from here, and the contract must have exactly one source.
TOOL_MISSING = _TOOL_MISSING

#: ``--no-sync`` keeps ``uv run`` from re-resolving and rebuilding the project
#: into ``.venv``. That rebuild fails on Windows whenever a resident process -
#: an MCP server, an editor, another agent's session - holds one of the
#: console-script executables open. The recipes whose purpose IS to change the
#: environment call ``uv`` directly and deliberately omit it.
NO_SYNC = ("--no-sync",)

#: complexipy and several other tools emit status glyphs; Windows consoles
#: default to a codepage that cannot encode them, which aborts the run before
#: any finding is reported.
UTF8 = {"PYTHONIOENCODING": "utf-8"}


@dataclass(frozen=True)
class Cmd:
    """A single subprocess invocation.

    Args:
        argv: The full argument vector, already split. Never a shell string -
            passing a list is what keeps quoting identical on every platform.
        env: Environment variables overlaid on the inherited environment.
        cwd: Directory to run in, relative to the repository root. ``None``
            means the repository root itself. This exists because the
            complexity tools resolve module names from the working directory,
            which the shell expressed as ``Push-Location``/``Pop-Location``.
    """

    argv: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict[str, str])
    cwd: str | None = None


@dataclass(frozen=True)
class ToolOrDocker:
    """An external tool, falling back to its Docker image when absent.

    ``taplo``, ``lychee``, and ``actionlint`` are native binaries rather than
    Python packages, so they cannot be pinned in the lockfile and may simply be
    missing. Rather than fail, the harness runs the pinned image with the
    working tree mounted at ``/repo``.

    Args:
        tool: Executable name to look for on ``PATH``.
        argv: Arguments passed to the native executable.
        image: Docker image reference used when the executable is absent.
        docker_argv: Arguments passed to the container. Defaults to ``argv``,
            and differs only where the container needs repo-absolute paths.
    """

    tool: str
    argv: tuple[str, ...]
    image: str
    docker_argv: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ToolOrSkip:
    """An optional external tool that is skipped, with a notice, when absent.

    Distinct from :class:`ToolOrDocker` in CONSEQUENCE: there is no fallback,
    and the absence is reported rather than treated as a failure. Only
    advisory targets may use this - a gate that silently passes when its tool
    is missing is not a gate.

    Args:
        tool: Executable name to look for on ``PATH``.
        argv: Arguments passed to the executable.
        reason: What is not being checked, printed when the tool is absent.
        advisory_finding_exit: When set, the scanner runs through
            ``tools/advisory.py`` with this findings-exit-code, so its FINDINGS
            do not gate but its BREAKAGE still does. Absent means the exit code
            is propagated unchanged.
    """

    tool: str
    argv: tuple[str, ...]
    reason: str
    advisory_finding_exit: int | None = None


@dataclass(frozen=True)
class Echo:
    """A section header printed between the steps of an aggregate target."""

    text: str


@dataclass(frozen=True)
class Ref:
    """A reference to another target within the same verb.

    Aggregates such as ``lint all`` are expressed as references rather than by
    repeating their steps, so a target and its use in an aggregate cannot drift
    apart. The shell form repeated every target name in a chain of ``just lint
    X`` plus ``if ($LASTEXITCODE -ne 0)`` pairs, which is how a target could be
    added without ever joining the aggregate that claimed to run everything.
    """

    target: str


Step = Cmd | ToolOrDocker | ToolOrSkip | Echo | Ref


def run(
    argv: Sequence[str],
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
) -> int:
    """Run one subprocess and return its exit code.

    Args:
        argv: The argument vector to execute.
        env: Variables overlaid on the inherited environment.
        cwd: Directory to run in, relative to the repository root.

    Returns:
        The child process exit code, or :data:`TOOL_MISSING` when the
        executable does not exist.
    """
    merged = {**os.environ, **(env or {})}
    location = f" (in {cwd})" if cwd else ""
    print(f"$ {' '.join(argv)}{location}", flush=True)

    # Resolve through `shutil.which` rather than handing the bare name to
    # `subprocess`. On Windows the interesting tools ship as `.cmd` shims -
    # `npx` is a POSIX shell script that CreateProcess cannot execute, while
    # `npx.cmd` beside it is the real entry point - and only PATHEXT resolution
    # finds the right one. Without this, `npx` reads as "not installed" on a
    # machine where Node is installed and on PATH.
    resolved = shutil.which(argv[0])
    if resolved is None:
        print(f"{argv[0]} not found on PATH", file=sys.stderr, flush=True)
        return TOOL_MISSING

    try:
        return subprocess.run(
            [resolved, *argv[1:]],
            env=merged,
            cwd=cwd,
            check=False,
        ).returncode
    except OSError as exc:
        print(f"{argv[0]} could not be executed: {exc}", file=sys.stderr, flush=True)
        return TOOL_MISSING


def run_tool_or_docker(step: ToolOrDocker) -> int:
    """Run a native tool, or its Docker image when the tool is unavailable.

    Args:
        step: The tool description to execute.

    Returns:
        The exit code of whichever form ran, or :data:`TOOL_MISSING` when
        neither the tool nor Docker is present.
    """
    if shutil.which(step.tool):
        return run([step.tool, *step.argv])
    if shutil.which("docker"):
        container_argv = step.docker_argv if step.docker_argv is not None else step.argv
        return run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{Path.cwd()}:/repo",
                "-w",
                "/repo",
                step.image,
                *container_argv,
            ]
        )
    print(
        f"{step.tool} not found and docker is unavailable",
        file=sys.stderr,
        flush=True,
    )
    return TOOL_MISSING


def run_tool_or_skip(step: ToolOrSkip) -> int:
    """Run an optional tool, or report that it was skipped.

    Args:
        step: The optional tool description.

    Returns:
        The tool's exit code, or 0 when the tool is absent.
    """
    if shutil.which(step.tool) is None:
        print(
            f"{step.tool} not found - skipping {step.reason}",
            file=sys.stderr,
            flush=True,
        )
        return 0
    if step.advisory_finding_exit is None:
        return run([step.tool, *step.argv])
    return run(
        [
            "uv",
            "run",
            *NO_SYNC,
            "python",
            "tools/advisory.py",
            "--finding-exit",
            str(step.advisory_finding_exit),
            "--",
            step.tool,
            *step.argv,
        ]
    )


def uv_run(*argv: str) -> Cmd:
    """Build a command that runs a tool from the existing environment.

    Args:
        *argv: The command and arguments to run inside the environment.

    Returns:
        The corresponding :class:`Cmd`, carrying :data:`NO_SYNC`.
    """
    return Cmd(("uv", "run", *NO_SYNC, *argv))


def uv_run_env(env: Mapping[str, str], *argv: str, cwd: str | None = None) -> Cmd:
    """Build an environment-run command with overrides and a working directory.

    Args:
        env: Variables overlaid on the inherited environment.
        *argv: The command and arguments to run inside the environment.
        cwd: Directory to run in, relative to the repository root.

    Returns:
        The corresponding :class:`Cmd`.
    """
    return Cmd(uv_run(*argv).argv, env, cwd)


def dev_module(module: str, *argv: str) -> Cmd:
    """Build a command that runs one of this harness's own instruments.

    Args:
        module: The dotted module path beneath ``dev``.
        *argv: Arguments passed to the instrument.

    Returns:
        The corresponding :class:`Cmd`.
    """
    return uv_run("python", "-m", f"dev.{module}", *argv)
