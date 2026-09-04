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

from .._process_probe import HolderRelation, environment_holders

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
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if any(holder.pid == pid for holder in environment_holders(root).holders):
            return
        time.sleep(0.1)
    pytest.fail(f"holder pid {pid} never appeared for {root}")


def test_an_interpreter_running_from_the_environment_is_an_image_holder(
    environment_root: Path, holders: list[subprocess.Popen[bytes]]
) -> None:
    """A process whose image is inside the tree is found, and named as such."""
    child = subprocess.Popen([str(_interpreter(environment_root)), "-c", _IDLE])
    holders.append(child)
    _await_holder(environment_root, child.pid)

    result = environment_holders(environment_root)

    found = [holder for holder in result.holders if holder.pid == child.pid]
    assert found, f"the environment's own interpreter was not found: {result.holders}"
    assert found[0].relation is HolderRelation.IMAGE
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

    result = environment_holders(environment_root)

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

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        result = environment_holders(environment_root)
        if not any(holder.pid == child.pid for holder in result.holders):
            return
        time.sleep(0.1)
    pytest.fail("a terminated holder was still reported")


def test_an_excluded_pid_is_not_reported_as_a_holder(
    environment_root: Path, holders: list[subprocess.Popen[bytes]]
) -> None:
    """A caller that knows a pid is not an obstacle can say so."""
    child = subprocess.Popen([str(_interpreter(environment_root)), "-c", _IDLE])
    holders.append(child)
    _await_holder(environment_root, child.pid)

    result = environment_holders(environment_root, exclude_pids=[child.pid])

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
