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
from typing import TYPE_CHECKING

import pytest

from .._program_lookup import Where, find_program
from ._planted_programs import (
    plant_marking_program,
    plant_native_program,
    stock_search_state,
)

if TYPE_CHECKING:
    from pathlib import Path

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


@pytest.mark.parametrize("name", ["", ".", "..", "bin/tool", "./tool"])
def test_a_name_with_a_directory_part_is_refused(name: str) -> None:
    """A path is the caller's to check; searching for one would let a
    relative name choose a file under the working directory."""
    with pytest.raises(ValueError, match="bare program name"):
        find_program(name, Where.SEARCH_PATH)


def test_a_lookup_with_no_place_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one place"):
        find_program("tool")
