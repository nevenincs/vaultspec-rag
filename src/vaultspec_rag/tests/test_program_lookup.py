"""The program lookup never answers from the working directory.

A program is planted in the working directory under the name being looked
for, and the environment is put in the state a stock machine is in: on
Windows the switch that keeps the working directory out of a program search
is removed, and everywhere ``PATH`` carries an empty and a relative entry,
each of which means the working directory.

The control test runs the standard library's lookup, and a bare-name run, in
that same state and requires each to take the planted program. Without it a
machine that happened to be configured safely would let every other test here
pass over a lookup that did nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from .._program_lookup import (
    Where,
    find_program,
    find_programs,
    installation_programs,
)
from .._win32 import system_directory
from ..config._types import EnvVar
from ._planted_programs import (
    plant_marking_program,
    plant_native_program,
    stock_search_state,
)

pytestmark = [pytest.mark.unit]

_NAME = "vaultspec-rag-lookup-probe"


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working directory in the state a stock machine searches it in."""
    directory = tmp_path / "checkout"
    directory.mkdir()
    stock_search_state(monkeypatch, directory)
    return directory


def test_a_program_in_the_working_directory_is_not_found(checkout: Path) -> None:
    """Shown to fail by letting the lookup keep relative entries of ``PATH``:
    the planted program is returned and the assertion fires. Passes with the
    absolute-entry rule restored."""
    plant_marking_program(checkout, _NAME)

    assert find_program(_NAME, Where.SEARCH_PATH) is None
    assert find_program(_NAME, Where.SYSTEM, Where.INSTALLATION) is None


def test_the_standard_lookup_and_a_bare_name_run_take_the_planted_program(
    checkout: Path,
) -> None:
    """Control: the plants are live for the two ways programs used to be found."""
    ran = plant_marking_program(checkout, _NAME)
    native = "vaultspec-rag-lookup-native"
    plant_native_program(checkout, native)

    looked_up = shutil.which(_NAME)

    assert looked_up is not None, "the standard lookup did not see the plant"
    assert not os.path.isabs(looked_up), looked_up
    subprocess.run([looked_up], check=False, capture_output=True, timeout=60)
    assert ran.exists(), "the planted program was found but did not run"
    # A bare name handed straight to process creation, with no lookup at all.
    completed = subprocess.run([native], check=False, capture_output=True, timeout=60)
    assert completed.returncode == 0, "a bare-name run did not start the plant"


def test_a_program_is_found_in_an_absolute_entry_and_returned_absolute(
    checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The place the operator named is searched, after the relative ones are
    skipped, and the answer can be run from any directory."""
    plant_marking_program(checkout, _NAME)
    installed = tmp_path / "installed"
    installed.mkdir()
    ran = plant_marking_program(installed, _NAME)
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", str(installed)]))

    found = find_program(_NAME, Where.SEARCH_PATH)

    assert found is not None
    assert os.path.isabs(found)
    assert os.path.dirname(found) == str(installed)
    subprocess.run([found], check=False, capture_output=True, timeout=60)
    assert ran.exists()
    assert not (checkout / f"{_NAME}.ran").exists()


def test_places_are_searched_in_the_order_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool the operating system ships is not answered by a same-named
    program earlier on ``PATH`` when the caller asks the system first."""
    name = "tasklist" if sys.platform == "win32" else "sh"
    shadow = tmp_path / "ports"
    shadow.mkdir()
    plant_marking_program(shadow, name)
    monkeypatch.setenv("PATH", os.pathsep.join([str(shadow), os.environ["PATH"]]))

    system_first = find_program(name, Where.SYSTEM, Where.SEARCH_PATH)
    path_first = find_program(name, Where.SEARCH_PATH, Where.SYSTEM)

    assert system_first is not None
    assert os.path.dirname(system_first) != str(shadow)
    assert path_first is not None
    assert os.path.dirname(path_first) == str(shadow)


@pytest.mark.skipif(
    sys.platform != "win32", reason="PowerShell is a Windows operating-system program"
)
def test_powershell_is_found_among_the_system_programs_whatever_path_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PowerShell lives beneath the system directory, not in it, and is an
    operating-system program all the same: asking the system finds the real
    one while a same-named program stands first on ``PATH``.

    Shown to fail by naming the system directory alone as the system's place:
    nothing is found and the first assertion fires. Passes with the
    PowerShell directory restored. The control line holds the plant live: a
    caller that asked ``PATH`` is handed it.
    """
    shadow = tmp_path / "ports"
    shadow.mkdir()
    planted = plant_native_program(shadow, "powershell")
    monkeypatch.setenv("PATH", os.pathsep.join([str(shadow), os.environ["PATH"]]))

    found = find_program("powershell.exe", Where.SYSTEM)

    assert found is not None, "the system's places do not hold PowerShell"
    assert Path(found).is_relative_to(system_directory()), found
    assert find_program("powershell.exe", Where.SEARCH_PATH) == str(planted)


def test_every_match_is_offered_in_the_order_of_the_places(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller that judges a match by its content is offered all of them.

    The first file of the right name is not necessarily the right file, and
    an installation can hold more than one.

    Mutation: made the enumeration stop after its first match. Observed this
    test fail on the list assertion, with only the first directory named.
    Restored; passes.
    """
    first = tmp_path / "first"
    second = tmp_path / "second"
    for directory in (first, second):
        directory.mkdir()
        plant_native_program(directory, _NAME)
    monkeypatch.setenv("PATH", os.pathsep.join([str(first), str(second)]))

    found = list(find_programs(_NAME, Where.SEARCH_PATH))

    assert [os.path.dirname(path) for path in found] == [str(first), str(second)]


def test_the_launcher_s_own_directory_is_one_of_this_installation_s_places(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The programs a launcher was packed with sit beside the launcher.

    A single-file launcher installs this package into a cache environment of
    its own and runs that environment's interpreter, so neither the scripts
    directory nor the interpreter's own directory is where the executables
    it shipped with are. The launcher states its own path, and that is the
    only evidence of where they are.

    Mutation: left the stated launcher out of the places. Observed this test
    fail on the places assertion, the launcher's own directory absent from
    them, and the lookup below find nothing. Restored; passes.
    """
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    launcher = plant_native_program(bundle, "vaultspec-rag-launcher")
    planted = plant_native_program(bundle, _NAME)
    monkeypatch.setenv(EnvVar.PYAPP.value, str(launcher))

    assert str(bundle) in installation_programs()
    found = find_program(_NAME, Where.INSTALLATION)
    # Windows supplies the extension from PATHEXT, in its spelling.
    assert found is not None
    assert os.path.normcase(found) == os.path.normcase(str(planted))


@pytest.mark.parametrize("stated", ["1", "", "bundle/vaultspec-rag"])
def test_a_launcher_value_that_names_no_file_adds_no_place(
    stated: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A launcher built without that option states a marker, not a path.

    A relative path is refused for the reason the whole module exists: it
    would name a directory relative to wherever the process happens to be.

    Mutation: took the stated value as a path whenever it was not empty.
    Observed this test fail on the places assertion for every value, the
    marker contributing an empty place and the relative path a relative
    one. Restored; passes.
    """
    monkeypatch.setenv(EnvVar.PYAPP.value, stated)

    assert installation_programs() == (
        sysconfig.get_path("scripts"),
        os.path.dirname(sys.executable),
    )


@pytest.mark.parametrize("name", ["", ".", "..", "bin/tool", "./tool"])
def test_a_name_with_a_directory_part_is_refused(name: str) -> None:
    """A path is the caller's to check; searching for one would let a
    relative name choose a file under the working directory."""
    with pytest.raises(ValueError, match="bare program name"):
        find_program(name, Where.SEARCH_PATH)


def test_a_lookup_with_no_place_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one place"):
        find_program("tool")
