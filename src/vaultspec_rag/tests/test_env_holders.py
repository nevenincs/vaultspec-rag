"""Who holds an environment (real environments, real holder subprocesses).

The field failure this proves against: a forced tool reinstall removes an
environment's packages and then dies on a file something else is holding,
leaving the environment unrunnable. Detecting that beforehand is only useful if
BOTH relations are found - a process running the environment's own interpreter,
and a process merely sitting in the tree with an unrelated binary - because
either one blocks the removal on Windows and only the first is obvious.

No mocks for the relations: a real virtual environment is built under
``tmp_path``, real child processes hold it, and the query is asked about the
real process table. The two fail-closed branches (a scan that cannot enumerate,
and a process that cannot be inspected) are driven through an injected process
table, because neither can be provoked on demand from a live one.
"""

from __future__ import annotations

import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any

import pytest

from .._process_probe import (
    HolderRelation,
    _names_under,
    _resolves_under,
    environment_holders,
)

# A process running the environment's own interpreter matches by image path on
# Windows, where the interpreter is copied into the tree, and by launch path on
# POSIX, where it is a symlink to the base interpreter resolving outside it.
_INTERPRETER_RELATIONS = {HolderRelation.IMAGE, HolderRelation.LAUNCH_PATH}

# CI runs this suite across a dozen xdist workers, and each holder query walks
# the whole process table, so both the scan and the wait get room that a
# single-threaded developer run never needs. The poll interval is deliberately
# slack for the same reason: a full table walk ten times a second, times a
# dozen workers, starves the deadline-sensitive tests sharing the runner.
_SCAN_TIMEOUT = 120.0
_WAIT_SECONDS = 90.0
_POLL_SECONDS = 0.5

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

pytestmark = [pytest.mark.unit]

# Long enough that a holder outlives the assertions, short enough that a test
# abandoning one cannot wedge a machine for long.
_HOLDER_LIFETIME_SECONDS = 90
_IDLE = f"import time; time.sleep({_HOLDER_LIFETIME_SECONDS})"


@pytest.fixture
def environment_root(tmp_path: Path) -> Path:
    """Build a real virtual environment to be held."""
    root = tmp_path / "env"
    completed = subprocess.run(
        ["uv", "venv", str(root)],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"could not create a virtual environment: {completed.stderr!r}")
    return root


def _interpreter(root: Path) -> Path:
    """The environment's own interpreter, on either platform's layout."""
    windows = root / "Scripts" / "python.exe"
    return windows if windows.exists() else root / "bin" / "python"


@pytest.fixture
def holders() -> Iterator[list[subprocess.Popen[bytes]]]:
    """Track spawned holders so a failing assertion still releases them."""
    spawned: list[subprocess.Popen[bytes]] = []
    try:
        yield spawned
    finally:
        for process in spawned:
            process.terminate()
        for process in spawned:
            process.wait(timeout=30)


def _await_holder(root: Path, pid: int) -> None:
    """Wait until the query sees *pid*, so no test races a starting child.

    Bounded tightly: each attempt costs a full process-table scan, so a child
    that never appears must give up in seconds rather than turning a failing
    assertion into a multi-minute one in a commit-gating lane.
    """
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        found = environment_holders(root, timeout=_SCAN_TIMEOUT)
        if any(holder.pid == pid for holder in found.holders):
            return
        time.sleep(_POLL_SECONDS)
    pytest.fail(f"holder pid {pid} never appeared for {root}")


def test_an_interpreter_running_from_the_environment_is_an_image_holder(
    environment_root: Path, holders: list[subprocess.Popen[bytes]]
) -> None:
    """A process whose image is inside the tree is found, and named as such."""
    child = subprocess.Popen([str(_interpreter(environment_root)), "-c", _IDLE])
    holders.append(child)
    _await_holder(environment_root, child.pid)

    result = environment_holders(environment_root, timeout=_SCAN_TIMEOUT)

    found = [holder for holder in result.holders if holder.pid == child.pid]
    assert found, f"the environment's own interpreter was not found: {result.holders}"
    assert found[0].relation in _INTERPRETER_RELATIONS
    assert result.held is True


def test_a_foreign_process_sitting_in_the_environment_is_a_directory_holder(
    environment_root: Path, holders: list[subprocess.Popen[bytes]]
) -> None:
    """A process with an unrelated binary still holds, by working directory.

    This is the relation an image-path-only check misses, and the one whose
    removal failure is the more destructive of the two.
    """
    child = subprocess.Popen([sys.executable, "-c", _IDLE], cwd=str(environment_root))
    holders.append(child)
    _await_holder(environment_root, child.pid)

    result = environment_holders(environment_root, timeout=_SCAN_TIMEOUT)

    found = [holder for holder in result.holders if holder.pid == child.pid]
    assert found, f"a process sitting in the tree was not found: {result.holders}"
    assert found[0].relation is HolderRelation.WORKING_DIRECTORY
    assert found[0].image is not None
    assert environment_root.as_posix() not in (found[0].image or "").replace("\\", "/")


def test_a_released_environment_reports_no_holders(
    environment_root: Path, holders: list[subprocess.Popen[bytes]]
) -> None:
    """The query reflects release, so a refusal cannot outlive its cause."""
    child = subprocess.Popen([str(_interpreter(environment_root)), "-c", _IDLE])
    holders.append(child)
    _await_holder(environment_root, child.pid)
    child.terminate()
    child.wait(timeout=30)

    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        result = environment_holders(environment_root, timeout=_SCAN_TIMEOUT)
        if not any(holder.pid == child.pid for holder in result.holders):
            return
        time.sleep(_POLL_SECONDS)
    pytest.fail("a terminated holder was still reported")


def test_an_excluded_pid_is_not_reported_as_a_holder(
    environment_root: Path, holders: list[subprocess.Popen[bytes]]
) -> None:
    """A caller that knows a pid is not an obstacle can say so."""
    child = subprocess.Popen([str(_interpreter(environment_root)), "-c", _IDLE])
    holders.append(child)
    _await_holder(environment_root, child.pid)

    result = environment_holders(
        environment_root, exclude_pids=[child.pid], timeout=_SCAN_TIMEOUT
    )

    assert all(holder.pid != child.pid for holder in result.holders)


def _table(*rows: Mapping[str, object]) -> Any:
    """Return an ``iter_process_info`` stand-in yielding *rows*."""

    def scan(attrs: list[str]) -> Iterator[Mapping[str, object]]:
        del attrs
        yield from rows

    return scan


def test_an_uninspectable_process_denies_certainty_without_inventing_a_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process that cannot be read is counted, not reported and not ignored.

    Guard assertion: reporting it as a holder would refuse every machine, and
    dropping it silently would claim an environment is free on no evidence.
    """
    monkeypatch.setattr(
        "vaultspec_rag._process_probe.iter_process_info",
        _table({"pid": 4321, "exe": None, "cwd": None, "cmdline": None}),
    )

    result = environment_holders(tmp_path)

    assert result.holders == ()
    assert result.uninspectable == 1
    assert result.complete is True
    assert result.held is False
    assert result.certain is False


def test_a_scan_that_cannot_enumerate_is_incomplete_rather_than_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed scan never reads as a clean environment.

    Guard assertion: this is the branch that would otherwise turn "the process
    table could not be read" into "nothing holds this", which is the exact
    inversion this module's fail-closed rule exists to prevent.
    """

    def refuse(attrs: list[str]) -> Iterator[Mapping[str, object]]:
        del attrs
        raise OSError("could not enumerate processes")
        yield  # pragma: no cover - generator marker, never reached

    monkeypatch.setattr(
        "vaultspec_rag._process_probe.iter_process_info",
        refuse,
    )

    result = environment_holders(tmp_path)

    assert result.complete is False
    assert result.certain is False
    assert result.held is False


def test_a_symlinked_interpreter_is_named_by_its_launch_path(tmp_path: Path) -> None:
    """The launch path is compared as written, the image path as resolved.

    Guard assertion: a POSIX virtual environment's interpreter is a symlink
    pointing OUT of the tree. Resolving the path a process was launched with
    therefore lands on the base interpreter and reports the environment clear,
    which is how the holder query missed every Linux venv holder while passing
    on Windows, where the interpreter is a real file inside the tree.
    """
    root = tmp_path / "env"
    (root / "bin").mkdir(parents=True)
    outside = tmp_path / "base-python"
    outside.write_text("", encoding="utf-8")
    launch_path = root / "bin" / "python"
    try:
        launch_path.symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - needs privilege
        pytest.skip("this platform does not allow creating a symlink here")

    assert _names_under(str(launch_path), root.resolve(), root.absolute())
    assert not _resolves_under(str(launch_path), root.resolve())


def test_a_path_outside_the_tree_is_never_named_under_it(tmp_path: Path) -> None:
    """Normalisation closes the obvious way to smuggle a match."""
    root = tmp_path / "env"
    root.mkdir()

    assert not _names_under(str(tmp_path / "elsewhere" / "python"), root)
    assert not _names_under(str(root / ".." / "escape"), root)
    assert not _names_under("python", root)
    assert not _names_under(None, root)
