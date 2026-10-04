"""The session must be unable to mutate the operator's real managed directory.

Every path used here names an entry that does not exist, under a directory
component that does not exist, so a guard that failed to refuse would create a
stray directory rather than touch anything the operator's resident service
owns. Each case asserts afterwards that the probe directory was never created.

Mutation check for the whole file: commenting out the
``install_operator_directory_guard`` call in the repository-root conftest and
running this file alone failed all four refusal cases on their own
``pytest.raises`` assertions - ``DID NOT RAISE
<class 'OperatorDirectoryWriteError'>`` - and left
``test_reading_a_managed_path_is_not_refused`` and
``test_the_guard_is_installed_with_the_operators_real_roots`` to fail on the
installed-roots assertion. Restoring the call passed all six.

The uv cases launch uv at a target that does not exist outside the system
temporary directory, with a working directory that does not exist either, so a
guard that failed to refuse would hand the launch to an operating system that
cannot start it rather than to a uv that could change anything. Mutation check
for those cases: removing the ``subprocess.Popen`` branch from the guard's
audit hook and running them alone failed all three refusals - the sync with
``DID NOT RAISE``, the other two with the ``NotADirectoryError`` the launch
reached instead - and restoring it passed all four.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from ._operator_directory_guard import (
    OperatorDirectoryWriteError,
    guarded_operator_roots,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def operator_probe_dir() -> Path:
    """Return a directory that does not exist inside a guarded root.

    The name is unique per call, so a refusal that did not hold leaves
    evidence that names the run rather than colliding with an earlier one.
    """
    roots = guarded_operator_roots()
    assert roots, (
        "the session installed no operator-directory guard, so nothing is "
        "stopping a test from writing into the operator's real service dir"
    )
    probe = Path(roots[0]) / f"guard-probe-{os.getpid()}-{uuid.uuid4().hex}"
    assert not probe.exists()
    return probe


def test_writing_beneath_the_operator_directory_is_refused(
    operator_probe_dir: Path,
) -> None:
    """A plain write into the operator's managed tree raises before it opens."""
    target = operator_probe_dir / "service.json"
    with (
        pytest.raises(OperatorDirectoryWriteError, match=re.escape("refusing open")),
        target.open("w", encoding="utf-8"),
    ):
        pass
    assert not operator_probe_dir.exists()


def test_creating_a_directory_in_the_operator_directory_is_refused(
    operator_probe_dir: Path,
) -> None:
    """``mkdir`` is refused, so a write cannot prepare its own parent."""
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing os.mkdir")
    ):
        operator_probe_dir.mkdir()
    assert not operator_probe_dir.exists()


def test_deleting_in_the_operator_directory_is_refused(
    operator_probe_dir: Path,
) -> None:
    """Deletion is refused before the absent target would raise its own error."""
    target = operator_probe_dir / "service.json"
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing os.remove")
    ):
        os.remove(target)
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing shutil.rmtree")
    ):
        shutil.rmtree(operator_probe_dir)
    assert not operator_probe_dir.exists()


def test_renaming_onto_the_operator_directory_is_refused(
    operator_probe_dir: Path, tmp_path: Path
) -> None:
    """A rename is judged on its destination, not only on its source."""
    source = tmp_path / "source.json"
    source.write_text("owned by the test", encoding="utf-8")
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing os.rename")
    ):
        os.replace(source, operator_probe_dir / "service.json")
    assert source.read_text(encoding="utf-8") == "owned by the test"
    assert not operator_probe_dir.exists()


def test_reading_a_managed_path_is_not_refused(operator_probe_dir: Path) -> None:
    """The guard refuses mutation only; inspecting the real install still works.

    An absent file reports itself absent, which is the ordinary answer and not
    the guard's refusal.
    """
    target = operator_probe_dir / "service.json"
    with pytest.raises(FileNotFoundError), target.open("r", encoding="utf-8"):
        pass
    assert not operator_probe_dir.exists()


def test_the_guard_is_installed_with_the_operators_real_roots() -> None:
    """The guarded roots are the real managed directories, not this session's."""
    from ..config._settings import rag_default
    from ..config._types import EnvVar

    roots = guarded_operator_roots()
    default_status = os.path.normcase(
        os.path.abspath(Path(str(rag_default("status_dir"))).expanduser())
    )
    assert any(
        default_status == root or default_status.startswith(root + os.sep)
        for root in roots
    ), f"the default managed directory {default_status} is not guarded: {roots}"

    session_status = os.path.normcase(
        os.path.abspath(Path(os.environ[EnvVar.STATUS_DIR.value]).expanduser())
    )
    assert not any(
        session_status == root or session_status.startswith(root + os.sep)
        for root in roots
    ), "the session's own isolated status dir must stay writable"


@pytest.fixture
def foreign_environment() -> Path:
    """Return an environment path that is outside the temporary directory.

    Neither it nor its parent exists, so no launch aimed at it can start.
    """
    path = Path.home() / f"guard-probe-{os.getpid()}-{uuid.uuid4().hex}" / "env"
    assert not path.parent.exists()
    return path


def _uv() -> str:
    uv = shutil.which("uv")
    assert uv is not None, "uv is not on PATH; the suite's own toolchain needs it"
    return uv


def test_a_project_sync_outside_the_temporary_tree_is_refused(
    foreign_environment: Path,
) -> None:
    """The production torch sync refuses a project no test created."""
    from ..commands import _uv_sync
    from ..commands._models import InstallReport

    report = InstallReport(action="install", target=foreign_environment)
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing uv sync on")
    ):
        _uv_sync._run_uv_sync_torch(target=foreign_environment, report=report)
    assert not foreign_environment.parent.exists()


def test_a_package_change_to_a_foreign_interpreter_is_refused(
    foreign_environment: Path,
) -> None:
    """``uv pip`` is judged on the interpreter it changes, not its cwd."""
    interpreter = foreign_environment / "Scripts" / "python.exe"
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing uv pip install on")
    ):
        subprocess.run(
            [_uv(), "pip", "install", "--python", str(interpreter), "torch"],
            cwd=foreign_environment.parent,
            check=False,
        )
    assert not foreign_environment.parent.exists()


def test_a_tool_change_without_its_own_tool_directory_is_refused(
    foreign_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no tool directory of its own, ``uv tool`` would change the real one."""
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing uv tool install on")
    ):
        subprocess.run(
            [_uv(), "tool", "install", "vaultspec-rag"],
            cwd=foreign_environment.parent,
            check=False,
        )
    assert not foreign_environment.parent.exists()


def test_a_sync_inside_the_temporary_tree_is_not_refused(tmp_path: Path) -> None:
    """A project the test created is its own to change.

    The directory holds no project, so uv refuses on its own after starting.
    """
    completed = subprocess.run(
        [_uv(), "sync", "--project", str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
