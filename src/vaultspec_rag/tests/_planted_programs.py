"""Plant programs in a directory, and put a process in a stock search state.

Shared by the tests that hold program lookups to absolute locations. A plant
is a real program that really runs: the tests assert on whether it ran, or on
what the code under test reported after starting whatever it found.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

__all__ = ["plant_marking_program", "plant_native_program", "stock_search_state"]

#: The Windows switch that keeps the working directory out of a bare-name
#: program search. A stock machine does not set it; a machine that does hides
#: the behaviour these tests exist to hold against.
_WINDOWS_SWITCH = "NoDefaultCurrentDirectoryInExePath"


def stock_search_state(
    monkeypatch: pytest.MonkeyPatch, directory: Path, *trusted: Path
) -> None:
    """Work in *directory* the way a stock machine would search from it.

    The working directory becomes *directory*, the Windows switch is removed,
    and ``PATH`` is an empty entry, a relative entry and then *trusted*. No
    other entry survives, so a program is found only where the test put one,
    or where the code under test looks without consulting ``PATH`` at all.
    """
    monkeypatch.chdir(directory)
    monkeypatch.delenv(_WINDOWS_SWITCH, raising=False)
    entries = ["", os.curdir, *(str(entry) for entry in trusted)]
    monkeypatch.setenv("PATH", os.pathsep.join(entries))


def plant_marking_program(directory: Path, name: str) -> Path:
    """Ship a program called *name* that leaves a file behind when it runs.

    A command script on Windows, which the standard lookup finds through
    ``PATHEXT``, and a shell script elsewhere.

    Returns:
        The file the program leaves.
    """
    ran = directory / f"{name}.ran"
    if sys.platform == "win32":
        script = directory / f"{name}.cmd"
        script.write_text(f'@echo ran> "{ran}"\r\n', encoding="utf-8")
    else:
        script = directory / name
        script.write_text(f'#!/bin/sh\necho ran > "{ran}"\n', encoding="utf-8")
        script.chmod(0o755)
    return ran


def plant_native_program(directory: Path, name: str) -> Path:
    """Ship a native program called *name*: one a bare-name run starts.

    Process creation on Windows completes a bare name with ``.exe`` only, so
    a command script is invisible to it. The plant is a copy of a small
    operating-system program that runs under any name: it exits zero when
    given no arguments, and non-zero, printing nothing a caller is looking
    for, when given some. Elsewhere a shell script is native enough.

    Returns:
        The planted file.
    """
    if sys.platform != "win32":
        script = directory / name
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
        return script
    from .._win32 import system_directory

    planted = directory / f"{name}.exe"
    shutil.copyfile(os.path.join(system_directory(), "hostname.exe"), planted)
    return planted
