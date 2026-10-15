"""A second installation of this package, to run code in.

Some conditions belong to an installation and cannot be changed from inside the
process that is running the suite: whether it carries digests for a monitor,
which distribution record it was installed under, which scripts directory its
interpreter reports. Staging one in-process means replacing the reader that
reports it, and then nothing the reader does with the answer is exercised.
This builds the real thing instead: a copy of the package with the metadata an
installer would write, optionally inside an environment of its own, and runs a
fresh interpreter in it.

What is copied is the package as it is on disk now, without the checkout's own
generated digests and without its tests, so the interpreter runs the current
production code. What is written into it - digests, a distribution record - is
written by the generator and in the shape a release build writes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from tools.monitor.pins import PINS_PATH, GeneratedPins, write

from .._python_child import inline_command

__all__ = [
    "INSTALLED_FROM_A_WHEEL",
    "SeparateInstallation",
    "build_environment",
    "build_installation",
    "run_program",
]

#: The record an installer writes beside a wheel file's metadata: a built
#: artifact, as opposed to a source tree.
INSTALLED_FROM_A_WHEEL: Final = (
    '{"url": "file:///tmp/vaultspec_rag-0.0.0-py3-none-any.whl", "archive_info": {}}'
)

_PACKAGE: Final = Path(__file__).resolve().parents[1]
_DISTRIBUTION_NAME: Final = "vaultspec_rag"
_TIMEOUT_SECONDS: Final = 120


@dataclass(frozen=True)
class SeparateInstallation:
    """A copy of the package an interpreter of its own can be run in.

    Attributes:
        root: The directory that holds the package copy and its distribution
            record, and is first on the import path of every run.
        interpreter: The interpreter runs use: the suite's own, or the one of
            an environment built for this installation.
        scripts: The scripts directory that interpreter reports, where an
            installer would put the programs a package ships.
    """

    root: Path
    interpreter: Path
    scripts: Path

    def run(
        self,
        program: str,
        *arguments: object,
        cwd: Path | None = None,
        timeout: float = _TIMEOUT_SECONDS,
    ) -> dict[str, object]:
        """Run *program* in a fresh interpreter of this installation.

        As :func:`run_program` does, with this installation's interpreter and
        import path.
        """
        return run_program(
            self.interpreter,
            self.root,
            program,
            *arguments,
            cwd=cwd,
            timeout=timeout,
        )


def run_program(
    interpreter: Path,
    root: Path,
    program: str,
    *arguments: object,
    cwd: Path | None = None,
    timeout: float = _TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Run *program* under *interpreter* with *root* first on its import path.

    The program reads *arguments* from ``sys.argv[1]`` as a JSON list and
    prints one JSON object as its last line of output, which is returned. The
    environment variables, and the working directory unless *cwd* names one,
    are this process's own. A program that needs longer than the default, such
    as one that installs packages, names its own *timeout* in seconds.

    Raises:
        RuntimeError: When the interpreter exits non-zero or prints nothing,
            carrying what it wrote.
    """
    inherited = os.environ.get("PYTHONPATH")
    path = [str(root), *([inherited] if inherited else [])]
    completed = subprocess.run(
        inline_command(str(interpreter), program, json.dumps(arguments)),
        env={**os.environ, "PYTHONPATH": os.pathsep.join(path)},
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    lines = completed.stdout.strip().splitlines()
    if completed.returncode != 0 or not lines:
        raise RuntimeError(
            f"the program exited {completed.returncode} in {root}:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return cast("dict[str, object]", json.loads(lines[-1]))


def build_installation(
    directory: Path,
    *,
    version: str,
    direct_url: str | None,
    pins: GeneratedPins | None = None,
    own_environment: bool = False,
) -> SeparateInstallation:
    """Install a copy of this package under *directory*, as an installer would.

    Args:
        directory: An empty directory of the caller's, which holds everything
            this builds.
        version: The version the distribution record states.
        direct_url: The text of the record an installer writes for how the
            distribution was installed, or ``None`` for no record, which is an
            install from a package index.
        pins: The digests to generate into the package, or ``None`` for an
            installation that carries none.
        own_environment: Whether runs use an environment built for this
            installation rather than the suite's own interpreter. Its scripts
            directory is then its own and holds nothing the suite's does; the
            suite's installed distributions stay reachable through it.

    Returns:
        The installation, ready to run code in.
    """
    root = directory / "site"
    shutil.copytree(
        _PACKAGE,
        root / _PACKAGE.name,
        ignore=shutil.ignore_patterns("__pycache__", "tests", PINS_PATH.name),
    )
    if pins is not None:
        write(root / PINS_PATH.relative_to("src"), pins)
    _record_distribution(root, version, direct_url)
    if own_environment:
        interpreter = build_environment(directory / "environment")
    else:
        interpreter = Path(sys.executable)
    reported = run_program(
        interpreter,
        root,
        "import json, sysconfig;"
        "print(json.dumps({'scripts': sysconfig.get_path('scripts')}))",
    )
    return SeparateInstallation(root, interpreter, Path(str(reported["scripts"])))


def _record_distribution(root: Path, version: str, direct_url: str | None) -> None:
    """Write the distribution record an installer leaves for this package."""
    record = root / f"{_DISTRIBUTION_NAME}-{version}.dist-info"
    record.mkdir()
    (record / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: vaultspec-rag\nVersion: {version}\n",
        encoding="utf-8",
    )
    if direct_url is not None:
        (record / "direct_url.json").write_text(direct_url, encoding="utf-8")


def build_environment(directory: Path) -> Path:
    """Create an environment with nothing in it but the suite's distributions.

    The environment has an interpreter and a scripts directory of its own. A
    path file in it adds the suite's site directory, with the path files that
    directory carries, so every distribution the package imports is found as
    it is for the suite itself.

    Returns:
        The environment's interpreter.
    """
    venv.EnvBuilder(symlinks=os.name != "nt", with_pip=False, clear=True).create(
        directory
    )
    scheme = {"base": str(directory), "platbase": str(directory)}
    site = Path(sysconfig.get_path("purelib", scheme="venv", vars=scheme))
    site.mkdir(parents=True, exist_ok=True)
    suite = sysconfig.get_path("purelib")
    (site / "suite.pth").write_text(
        f"import site; site.addsitedir({suite!r})\n", encoding="utf-8"
    )
    scripts = Path(sysconfig.get_path("scripts", scheme="venv", vars=scheme))
    return scripts / ("python.exe" if os.name == "nt" else "python")
