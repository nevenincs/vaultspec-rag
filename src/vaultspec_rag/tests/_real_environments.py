"""Real environments to run the service-selection code in.

Which environment would run the service is decided from facts about an
interpreter: the kind of environment it belongs to, the distributions it holds,
and what its torch can do. None of those can be changed from inside the process
that reads them, and staging one in-process means replacing the reader. These
helpers make the environment instead: a fresh interpreter in an environment of
its own, made a uv tool environment the way uv makes one, or given the CPU build
of torch an operator would install by mistake.

Everything is built with the real tools and the real distributions. The CPU
build is the wheel PyTorch publishes for it, taken from uv's cache when it is
there and downloaded once when it is not.
"""

from __future__ import annotations

import subprocess
from importlib import metadata
from typing import TYPE_CHECKING, Final, TypedDict, cast

from ..operator_state._compute import ProbeDepth
from ..operator_state._service_environment import judge_foreign_environment
from ..operator_state._topology import TOOL_RECEIPT_NAME, environment_root
from ..service_runtime import (
    RUNTIME_REQUEST,
    RuntimeRequirement,
    _record,
    installed_release,
    release_runtime_dir,
    uv_executable,
)
from ._separate_installation import build_environment

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ._separate_installation import SeparateInstallation

__all__ = [
    "CPU_TORCH_INDEX",
    "NO_CUDA_RECEIPT",
    "CliRun",
    "as_a_tool_environment",
    "invoke_the_cli",
    "publish_runtime",
    "reported",
    "with_a_cpu_build_of_torch",
]

#: A receipt that records no CUDA source, so its fix is the two-command
#: sequence that brings one onto the upgrade cycle.
NO_CUDA_RECEIPT: Final = '[tool]\nrequirements = [{ name = "vaultspec-rag" }]\n'

#: Where PyTorch publishes its CPU builds, which carry a ``+cpu`` local version.
CPU_TORCH_INDEX: Final = "https://download.pytorch.org/whl/cpu"

_INSTALL_TIMEOUT_SECONDS: Final = 900


def as_a_tool_environment(interpreter: Path, receipt: str = NO_CUDA_RECEIPT) -> None:
    """Make the environment of *interpreter* a uv tool environment.

    uv marks a persistent tool environment by the receipt at its root, and the
    classifier reads that and nothing else, so the receipt is what makes it one.
    """
    root = environment_root(interpreter)
    (root / TOOL_RECEIPT_NAME).write_text(receipt, encoding="utf-8")


def with_a_cpu_build_of_torch(interpreter: Path) -> None:
    """Install the CPU build of this host's torch release into an environment.

    The wheel is the one PyTorch publishes for the same release as the torch
    this suite runs, installed on its own: the rest of the stack stays reachable
    through the environment as it is for any environment built here. The
    environment then reports a CPU-only build both from its metadata and from
    importing it, which is the state of a workstation whose torch resolved
    from the public index.

    Raises:
        RuntimeError: When uv is absent or the install fails, with what uv said.
    """
    uv = uv_executable()
    if uv is None:
        raise RuntimeError("uv is required to install a CPU build of torch")
    release = metadata.version("torch").partition("+")[0]
    completed = subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(interpreter),
            "--no-deps",
            "--link-mode",
            "hardlink",
            f"torch=={release}+cpu",
            "--index",
            CPU_TORCH_INDEX,
            "--index-strategy",
            "unsafe-best-match",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_INSTALL_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"uv could not install the CPU build of torch {release}:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )


#: Runs each argument list through the command line and reports what it wrote and
#: how it exited, so one interpreter start answers several invocations.
_INVOKE_THE_CLI = """
import json
import sys

from typer.testing import CliRunner

from vaultspec_rag.cli import app

runner = CliRunner()
results = []
for arguments in json.loads(sys.argv[1])[0]:
    result = runner.invoke(app, arguments)
    results.append({"stdout": result.stdout, "exit_code": result.exit_code})
print(json.dumps({"results": results}))
"""


def reported(outcome: dict[str, object], key: str) -> dict[str, object]:
    """The JSON object a child reported under *key*.

    Fails showing everything the child reported when it reported something
    else, which is how a build that was refused reads where a runtime was
    expected, and the other way round.
    """
    value = outcome.get(key)
    assert isinstance(value, dict), outcome
    return cast("dict[str, object]", value)


class CliRun(TypedDict):
    """What one command-line invocation wrote, and the code it exited with."""

    stdout: str
    exit_code: int


def invoke_the_cli(
    installation: SeparateInstallation,
    *invocations: Sequence[str],
    cwd: Path | None = None,
) -> list[CliRun]:
    """Run each invocation of the command line in a fresh interpreter of *installation*.

    The commands are the real ones, run in the environment *installation*
    names, so what they read about the interpreter that would run the service is
    read from that environment and not from the one running the suite.
    """
    ran = installation.run(
        _INVOKE_THE_CLI, [list(each) for each in invocations], cwd=cwd
    )
    return cast("list[CliRun]", ran["results"])


def publish_runtime(*, cpu_torch: bool = False) -> Path:
    """Publish this release's service runtime from a real environment.

    The environment is built in the runtime directory itself, so the interpreter
    the runtime names is one a start would run. It is given the CPU build of
    torch when *cpu_torch* is set, and the completion record is written by the
    writer a build uses, from what the environment's own metadata says it can
    do. Nothing here is a claim about the environment: a reader of the runtime
    judges the interpreter it finds.

    Returns:
        The published runtime directory.
    """
    release = installed_release()
    directory = release_runtime_dir(release)
    interpreter = build_environment(directory)
    if cpu_torch:
        with_a_cpu_build_of_torch(interpreter)
    environment = judge_foreign_environment(str(interpreter), ProbeDepth.METADATA)
    _record(
        directory,
        release,
        RuntimeRequirement(f"{RUNTIME_REQUEST}=={release}", "index"),
        environment,
    )
    return directory
