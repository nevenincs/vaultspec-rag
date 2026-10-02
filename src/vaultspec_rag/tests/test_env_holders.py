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
from typing import TYPE_CHECKING, Any, cast

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
_SCAN_TIMEOUT = 180.0
_WAIT_SECONDS = 180.0
_POLL_SECONDS = 0.5

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

pytestmark = [pytest.mark.unit]

# Long enough that a holder outlives the assertions, short enough that a test
# abandoning one cannot wedge a machine for long.
_HOLDER_LIFETIME_SECONDS = 240
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


def _family(pid: int) -> set[int]:
    """The process we spawned, plus any interpreter it launched for us.

    A virtual environment's ``python`` can be a launcher that re-executes the
    real interpreter as a child, so the process that ends up holding the tree
    is not always the one Popen handed back. Asserting on the spawned pid
    alone reads that as a detection failure - which is exactly what it looked
    like on the Windows runner, where the scan had in fact found the holder
    and reported a different pid for it.
    """
    import contextlib

    import psutil

    pids = {pid}
    with contextlib.suppress(psutil.Error):  # the holder may already have exited
        pids.update(child.pid for child in psutil.Process(pid).children(recursive=True))
    return pids


def _await_holder(root: Path, pid: int) -> None:
    """Wait until the query sees *pid*, so no test races a starting child.

    Bounded tightly: each attempt costs a full process-table scan, so a child
    that never appears must give up in seconds rather than turning a failing
    assertion into a multi-minute one in a commit-gating lane.
    """
    started = time.monotonic()
    deadline = started + _WAIT_SECONDS
    found = environment_holders(root, timeout=_SCAN_TIMEOUT)
    attempts = 1
    while True:
        family = _family(pid)
        if any(holder.pid in family for holder in found.holders):
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(_POLL_SECONDS)
        found = environment_holders(root, timeout=_SCAN_TIMEOUT)
        attempts += 1
    # Report what the wait SAW, not just that it ended. A scan that ran out of
    # its own budget reports complete=False and finds nothing, which is a busy
    # machine; scans that completed and still saw no holder is a detection
    # failure. Those need opposite fixes and are indistinguishable from the
    # bare sentence this used to fail with.
    pytest.fail(
        f"holder pid {pid} never appeared for {root} after {attempts} scans "
        f"over {time.monotonic() - started:.1f}s; last scan complete="
        f"{found.complete}, uninspectable={found.uninspectable}, "
        f"holders={[(h.pid, str(h.relation)) for h in found.holders]}"
    )


def test_an_interpreter_running_from_the_environment_is_an_image_holder(
    environment_root: Path, holders: list[subprocess.Popen[bytes]]
) -> None:
    """A process whose image is inside the tree is found, and named as such."""
    child = subprocess.Popen([str(_interpreter(environment_root)), "-c", _IDLE])
    holders.append(child)
    _await_holder(environment_root, child.pid)

    result = environment_holders(environment_root, timeout=_SCAN_TIMEOUT)

    found = [holder for holder in result.holders if holder.pid in _family(child.pid)]
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

    found = [holder for holder in result.holders if holder.pid in _family(child.pid)]
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
    family = _family(child.pid)
    child.terminate()
    child.wait(timeout=30)

    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        result = environment_holders(environment_root, timeout=_SCAN_TIMEOUT)
        if not any(holder.pid in family for holder in result.holders):
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

    family = _family(child.pid)
    result = environment_holders(
        environment_root, exclude_pids=sorted(family), timeout=_SCAN_TIMEOUT
    )

    assert all(holder.pid not in family for holder in result.holders)


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
        _table({"pid": 4321, "ppid": None, "exe": None, "cwd": None, "cmdline": None}),
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


def _row(
    pid: int,
    *,
    exe: str | None = None,
    cwd: str | None = None,
    cmdline: list[str] | None = None,
    ppid: int | None = None,
) -> dict[str, object]:
    """One process-table row in the shape the holder scan reads."""
    return {"pid": pid, "ppid": ppid, "exe": exe, "cwd": cwd, "cmdline": cmdline}


def test_only_a_matched_holder_requests_its_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parent reads cost a system snapshot on Windows; outsiders need none.

    The injected lazy rows record attribute access: the OS returns parent
    values but cannot expose whether this query requested an unused one,
    and elapsed time cannot establish that on a variably loaded runner.
    Classification, exclusions and parent pairing use production code.

    Restoring the eager read failed parent_reads == [matching] (exit 1);
    deferring it again passed this test (exit 0).
    """
    parent_reads: list[int] = []

    class ReadWitness(dict[str, object]):
        def __getitem__(self, key: str) -> object:
            if key == "ppid":
                parent_reads.append(cast("int", super().__getitem__("pid")))
            return super().__getitem__(key)

    matching = 4321
    rows = (
        ReadWitness(_row(4320, exe=str(tmp_path.parent / "unrelated.exe"))),
        ReadWitness(_row(4322)),
        ReadWitness(_row(4323, exe=str(tmp_path / "excluded.exe"))),
        ReadWitness(_row(matching, exe=str(tmp_path / "python.exe"), ppid=1234)),
    )
    monkeypatch.setattr("vaultspec_rag._process_probe.iter_process_info", _table(*rows))

    result = environment_holders(tmp_path, exclude_pids=(4323,))

    assert parent_reads == [matching]
    assert [holder.pid for holder in result.holders] == [matching]
    assert result.holders[0].ppid == 1234
    assert result.uninspectable == 1
    assert result.complete is True


class TestTheAskingCommandIsNotAnObstacle:
    """A command run from inside an environment is not a holder to clear.

    Guard assertion: the scan had no exclusion, so a refusal printed the pid
    of the very command the operator had just run, and its launcher beside
    it, as two processes to end before running the command it handed over.
    """

    def test_the_invoking_chain_is_excluded_and_stated_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os

        from .._process_probe import process_lineage

        interpreter = str(tmp_path / "Scripts" / "python.exe")
        monkeypatch.setattr(
            "vaultspec_rag._process_probe.iter_process_info",
            _table(
                _row(os.getpid(), exe=interpreter, cmdline=[interpreter, "-m", "pip"]),
                _row(999_001, exe=interpreter, cmdline=[interpreter, "-c", "pass"]),
            ),
        )
        assert any(entry.pid == os.getpid() for entry in process_lineage())

        result = environment_holders(tmp_path, exclude_launch_chain=True)

        assert [holder.pid for holder in result.holders] == [999_001]
        assert result.self_held is True

    def test_an_ancestor_holding_by_directory_stays_listed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shell the operator typed in is something they can leave.

        Guard assertion: excluding the whole launch chain by pid would drop
        it, and its open handle on the directory is what stops the removal on
        Windows.
        """
        import os

        monkeypatch.setattr(
            "vaultspec_rag._process_probe.iter_process_info",
            _table(
                _row(
                    os.getpid(),
                    exe=str(tmp_path / "Scripts" / "python.exe"),
                    cmdline=[],
                ),
                _row(
                    os.getppid(),
                    exe=str(tmp_path.parent / "foreign" / "cmd.exe"),
                    cwd=str(tmp_path),
                ),
            ),
        )

        result = environment_holders(tmp_path, exclude_launch_chain=True)

        assert [holder.pid for holder in result.holders] == [os.getppid()]
        assert result.holders[0].relation is HolderRelation.WORKING_DIRECTORY


def test_a_launcher_and_its_interpreter_are_one_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One logical process is reported once, carrying both pids.

    Guard assertion: a virtual environment's python re-executes the real
    interpreter with the same command line and stays alive as its parent, so
    every holder appeared twice - and on Windows one of the two rows named
    the shared base interpreter, which is not in the environment at all.
    """
    argv = [str(tmp_path / "Scripts" / "python.exe"), "-m", "vaultspec_rag.server"]
    monkeypatch.setattr(
        "vaultspec_rag._process_probe.iter_process_info",
        _table(
            _row(
                4320,
                exe=str(tmp_path.parent / "base-interpreter" / "python.exe"),
                cmdline=argv,
            ),
            _row(
                4321,
                exe=str(tmp_path / "Scripts" / "python.exe"),
                cmdline=argv,
                ppid=4320,
            ),
        ),
    )

    result = environment_holders(tmp_path)

    assert len(result.holders) == 1
    assert result.holders[0].pid == 4321
    assert result.holders[0].launcher_pid == 4320


def test_a_shell_and_the_process_it_started_stay_two_holders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pairing requires the launcher's own command line, not just parentage.

    Guard assertion: pairing on the parent relation alone would swallow a
    shell sitting in the tree behind the process it started, and the shell's
    own handle on the directory is what blocks the removal.
    """
    monkeypatch.setattr(
        "vaultspec_rag._process_probe.iter_process_info",
        _table(
            _row(
                5000,
                exe=str(tmp_path.parent / "foreign" / "cmd.exe"),
                cwd=str(tmp_path),
            ),
            _row(
                5001,
                exe=str(tmp_path / "bin" / "python"),
                cmdline=[str(tmp_path / "bin" / "python"), "-c", "pass"],
                ppid=5000,
            ),
        ),
    )

    result = environment_holders(tmp_path)

    assert sorted(holder.pid for holder in result.holders) == [5000, 5001]
    assert all(holder.launcher_pid is None for holder in result.holders)


class TestTheConsoleScriptAdapterIsRecognised:
    """A stdio adapter started by its console script is this product's own.

    Guard assertion: the launch shape was matched on ``-m
    vaultspec_rag.server`` alone, so an adapter an editor started through
    the installed console script was reported as an unrelated process, and
    its operator was told to end something their session owns. The names
    come from entry-point metadata, so a rename cannot leave a stale copy
    behind here.
    """

    def test_the_names_come_from_entry_point_metadata(self) -> None:
        import importlib.metadata

        from .._process_probe import SERVER_LAUNCH_MARKER, server_console_scripts

        expected = {
            entry.name.casefold()
            for entry in importlib.metadata.entry_points(group="console_scripts")
            if entry.value.partition(":")[0].strip() == SERVER_LAUNCH_MARKER[1]
        }

        assert server_console_scripts() == expected
        assert expected, "this package declares a server console script"

    def test_both_platforms_launch_shapes_are_recognised(self) -> None:
        from .._process_probe import is_server_launch, server_console_scripts

        script = next(iter(sorted(server_console_scripts())))
        windows = (
            "C:/tools/vaultspec-rag/Scripts/python.exe",
            f"C:/uv/bin/{script}.exe",
        )
        posix = ("/opt/uv/tools/vaultspec-rag/bin/python", f"/opt/uv/bin/{script}")
        module = ("python", "-m", "vaultspec_rag.server", "--port", "8776")

        assert is_server_launch(windows)
        assert is_server_launch(posix)
        assert is_server_launch(module)
        assert not is_server_launch(("python", "-c", "pass"))
        assert not is_server_launch(("C:/uv/bin/other-tool.exe",))

    def test_a_console_script_without_a_port_is_the_stdio_adapter(self) -> None:
        """The port is what separates the two launches of one module."""
        from .._process_probe import EnvironmentHolder, server_console_scripts
        from ..operator_state._holders import HolderRole, holder_role

        script = next(iter(sorted(server_console_scripts())))

        def _holder(*argv: str) -> EnvironmentHolder:
            return EnvironmentHolder(
                pid=7001,
                relation=HolderRelation.IMAGE,
                image="python.exe",
                working_directory=None,
                argv=argv,
            )

        adapter = _holder("python.exe", f"C:/uv/bin/{script}.exe")
        service = _holder("python.exe", f"C:/uv/bin/{script}.exe", "--port", "8776")

        assert holder_role(adapter) is HolderRole.MCP_ADAPTER
        assert holder_role(service) is HolderRole.SERVICE
