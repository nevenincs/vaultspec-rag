"""A child built by the command helper cannot be handed code by its directory.

Each test starts a real interpreter in a directory that ships a module under a
name the child imports, and asks the child where that module came from. The
planted module records that it ran, so the assertion is on what executed and
not on how the command line reads.

The control test starts the same children without the helper and requires the
planted module to run. Without it, a plant that could never have been imported
would let every other test here pass over a helper that did nothing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING, cast

import pytest

from .._python_child import inline_command, module_command, script_command

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: A standard-library module nothing imports at interpreter start, so a child
#: that imports it resolves it through the import path as it stands.
_SHADOWED = "colorsys"

_REPORT = (
    "import json, sys\n"
    f"import {_SHADOWED}\n"
    "print(json.dumps({'safe_path': bool(sys.flags.safe_path),"
    f" 'origin': {_SHADOWED}.__file__, 'path': sys.path}}))\n"
)

_PLANT = (
    "import pathlib\n"
    "pathlib.Path(__file__).with_suffix('.ran').write_text('ran', encoding='utf-8')\n"
)


def _plant(directory: Path, name: str = _SHADOWED) -> Path:
    """Ship a module called *name* in *directory*; return the file it leaves."""
    directory.mkdir(parents=True, exist_ok=True)
    module = directory / f"{name}.py"
    module.write_text(_PLANT, encoding="utf-8")
    return module.with_suffix(".ran")


def _run(
    command: list[str], *, cwd: Path, python_path: Path | None = None
) -> subprocess.CompletedProcess[str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in {"PYTHONSAFEPATH", "PYTHONPATH"}
    }
    if python_path is not None:
        environment["PYTHONPATH"] = str(python_path)
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


def _report(proc: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert proc.returncode == 0, proc.stderr
    report: object = json.loads(proc.stdout.strip().splitlines()[-1])
    assert isinstance(report, dict)
    return cast("dict[str, object]", report)


def _assert_untouched(report: dict[str, object], directory: Path, ran: Path) -> None:
    assert not ran.exists(), f"the module planted in {directory} was executed"
    assert report["safe_path"] is True
    assert not str(report["origin"]).startswith(str(directory))
    path = report["path"]
    assert isinstance(path, list)
    assert "" not in path
    assert str(directory) not in path


def test_an_inline_child_does_not_import_from_its_working_directory(
    tmp_path: Path,
) -> None:
    """Shown to fail by dropping the flag from ``inline_command``: the planted
    module then runs and the ``was executed`` assertion fires."""
    hostile = tmp_path / "checkout"
    ran = _plant(hostile)

    proc = _run(inline_command(sys.executable, _REPORT), cwd=hostile)

    _assert_untouched(_report(proc), hostile, ran)


def test_a_module_child_does_not_import_from_its_working_directory(
    tmp_path: Path,
) -> None:
    """The module that runs is the installed one, and so is what it imports.

    The working directory ships both a module under the launched name and one
    under a name the launched module imports. Shown to fail by dropping the
    flag from ``module_command``: the working directory's copy of the launched
    module runs in place of the real one, and the ``was replaced`` assertion
    fires on it.
    """
    installed = tmp_path / "installed"
    installed.mkdir()
    (installed / "reporting_child.py").write_text(_REPORT, encoding="utf-8")
    hostile = tmp_path / "checkout"
    ran_launched = _plant(hostile, "reporting_child")
    ran_imported = _plant(hostile)

    proc = _run(
        module_command(sys.executable, "reporting_child"),
        cwd=hostile,
        python_path=installed,
    )

    assert not ran_launched.exists(), "the launched module was replaced"
    _assert_untouched(_report(proc), hostile, ran_imported)


def test_a_script_child_does_not_import_from_the_script_directory(
    tmp_path: Path,
) -> None:
    """Shown to fail by dropping the flag from ``script_command``: the module
    beside the script then runs and the ``was executed`` assertion fires."""
    beside = tmp_path / "scripts"
    ran = _plant(beside)
    script = beside / "report.py"
    script.write_text(_REPORT, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    proc = _run(script_command(sys.executable, script), cwd=elsewhere)

    _assert_untouched(_report(proc), beside, ran)


def test_arguments_follow_the_program_they_belong_to(tmp_path: Path) -> None:
    """Arguments reach the child's own argument list, not the interpreter's."""
    echo = "import json, sys; print(json.dumps(sys.argv[1:]))"
    script = tmp_path / "echo.py"
    script.write_text(echo, encoding="utf-8")
    arguments = ("--port", "8766", "-m", "not-a-module")

    for command in (
        inline_command(sys.executable, echo, *arguments),
        script_command(sys.executable, script, *arguments),
        module_command(sys.executable, "echo", *arguments),
    ):
        proc = _run(command, cwd=tmp_path, python_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout) == list(arguments)


def test_the_planted_module_runs_in_a_child_started_without_the_helper(
    tmp_path: Path,
) -> None:
    """The plant is live: the commands this package used to build import it.

    This is the control for the three tests above. If the interpreter stopped
    putting these directories on the path by default, they would pass whatever
    the helper did, and this test is what would say so.
    """
    hostile = tmp_path / "checkout"
    ran = _plant(hostile)
    script = hostile / "report.py"
    script.write_text(_REPORT, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    for command, cwd in (
        ([sys.executable, "-c", _REPORT], hostile),
        ([sys.executable, "-m", "report"], hostile),
        ([sys.executable, str(script)], elsewhere),
    ):
        ran.unlink(missing_ok=True)
        proc = _run(command, cwd=cwd)

        assert ran.exists(), f"{command[1:]} did not import the planted module"
        assert proc.returncode == 0, proc.stderr
