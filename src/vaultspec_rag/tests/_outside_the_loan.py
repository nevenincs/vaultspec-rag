"""Run a Python program in a process the GPU loan does not reach.

The resident service lends the GPU to one process and to every process that
process starts, and the owner anchor answers by walking a process's ancestors.
A child a test starts is therefore inside the loan however it is launched,
which makes it the wrong contender for a test that proves a stranger is
refused. A process whose parent has already exited has no ancestor left to
walk, so it is the one kind of process a test can start that the loan does not
cover.

The launcher here starts the program through a runner and exits at once, which
leaves the runner orphaned. Nothing is left to wait on, so what the program
printed and how it ended come back through a file the runner publishes last.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ["Outside", "run_outside_the_loan"]

#: Starts the runner and leaves without waiting for it. Exiting through
#: ``os._exit`` skips the finalisers that would otherwise reap or warn about
#: the child it deliberately abandons.
_LAUNCHER = """
import os
import subprocess
import sys

directory, timeout, runner, program, *arguments = sys.argv[1:]
with open(os.path.join(directory, "runner.stderr"), "wb") as diagnostics:
    subprocess.Popen(
        [sys.executable, "-c", runner, directory, timeout, program, *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=diagnostics,
    )
os._exit(0)
"""

#: Runs the program as a child of the orphaned runner. The runner's parent has
#: exited, so no process the GPU is lent to is left among its ancestors, and the
#: program it starts inherits that.
_RUNNER = """
import json
import subprocess
import sys

from vaultspec_rag.tests._child_signal import publish_marker

directory, timeout, program, *arguments = sys.argv[1:]
try:
    done = subprocess.run(
        [sys.executable, "-c", program, *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=float(timeout),
        check=False,
    )
    outcome = {
        "returncode": done.returncode,
        "stdout": done.stdout,
        "stderr": done.stderr,
    }
except subprocess.TimeoutExpired as expired:
    outcome = {"returncode": None, "stdout": "", "stderr": str(expired)}
publish_marker(directory + "/result.json", json.dumps(outcome))
"""


@dataclass(frozen=True, slots=True)
class Outside:
    """How a program run outside the loan ended."""

    returncode: int
    stdout: str
    stderr: str


def run_outside_the_loan(
    program: str,
    *arguments: str,
    directory: Path,
    env: Mapping[str, str] | None = None,
    timeout: float = CHILD_PROCESS_TIMEOUT_SECONDS,
) -> Outside:
    """Run *program* with *arguments* in a process outside the GPU loan.

    *directory* is a scratch directory the caller owns; the runner's result
    and diagnostics are kept there. *timeout* bounds the program itself, and
    the wait for the runner's answer allows a little longer.

    Raises:
        AssertionError: The program outran *timeout*, or the runner never
            answered, with the runner's own diagnostics.
    """
    scratch = directory / f"outside-{time.monotonic_ns()}"
    scratch.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable,
            "-c",
            _LAUNCHER,
            str(scratch),
            str(timeout),
            _RUNNER,
            program,
            *arguments,
        ],
        env=None if env is None else dict(env),
        check=True,
        timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
    )
    result = scratch / "result.json"
    deadline = time.monotonic() + timeout + CHILD_PROCESS_TIMEOUT_SECONDS
    while not result.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    diagnostics = (scratch / "runner.stderr").read_text(
        encoding="utf-8", errors="replace"
    )
    assert result.exists(), f"the runner never answered: {diagnostics}"
    outcome = cast("dict[str, object]", json.loads(result.read_text(encoding="utf-8")))
    returncode = outcome["returncode"]
    assert isinstance(returncode, int), (
        f"the program outran {timeout:g}s: {outcome['stderr']}"
    )
    return Outside(returncode, str(outcome["stdout"]), str(outcome["stderr"]))
