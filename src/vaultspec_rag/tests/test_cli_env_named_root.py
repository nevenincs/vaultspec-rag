"""Guards that ``VAULTSPEC_RAG_ROOT`` decides which project the CLI addresses.

The run-level tests here must drive the CLI as a real subprocess. The variable
is read in the root callback and consumed by the workspace resolver before any
command runs, and the in-process runner the other CLI tests use enters below
that seam with a workspace already chosen - so the whole decision is
unreachable from an in-process test, and a regression would pass the rest of
the suite untouched. The class at the end reads the variable directly, for the
one rule no run can show.

The failure being guarded is not an error but a wrong answer. With the variable
ignored, a command run from a different directory resolves that directory's
project and reports on it with an ``ok`` envelope, so an operator who pointed
the tool at one project reads plausible results from another. Every assertion
below therefore names the root that was *used*, not merely that the run
succeeded.

``preprocess status --json`` is the observable: it reports the resolved root
verbatim, contacts no service and loads no model, so what it prints is the
workspace decision and nothing else.

Both directions were checked. Restoring the callback to pass ``target``
straight through - dropping the environment from the precedence - fails
``test_env_named_root_beats_the_working_directory`` on its own root assertion
(it reports the ``elsewhere`` workspace) and
``test_env_naming_a_non_workspace_is_refused_not_ignored`` on its returncode
assertion (a confident ``0`` over the wrong project). Restoring the precedence
passes both. Dropping the blank-value rule fails
``test_a_blank_variable_names_nothing`` on its own assertion, and no run-level
test - the same value reaches the resolver as a path the platform then trims
back to the working directory, so end to end it is invisible.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .._named_root import env_named_root
from ..config import EnvVar

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]

#: The tree holding the package under test, passed to each subprocess as an
#: absolute path. Every run below starts in a temporary workspace, so a
#: relative entry inherited from the caller's own ``PYTHONPATH`` would not
#: resolve there and the child would silently import an installed copy of the
#: package instead of the one being tested.
_PACKAGE_PATH = str(Path(__file__).resolve().parents[2])


class _Workspaces:
    """Two enrolled projects plus a directory that is not one."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.named = self._enrol(base / "named")
        self.elsewhere = self._enrol(base / "elsewhere")
        self.bare = base / "bare"
        self.bare.mkdir()

    @staticmethod
    def _enrol(root: Path) -> Path:
        (root / ".vault").mkdir(parents=True)
        (root / ".vaultspec").mkdir(parents=True)
        return root


@pytest.fixture
def workspaces() -> Iterator[_Workspaces]:
    """Short-pathed sibling workspaces, outside any git tree of this repo."""
    base = Path(tempfile.mkdtemp(prefix="vsroot"))
    try:
        yield _Workspaces(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _run(
    workspaces: _Workspaces,
    *args: str,
    root_env: str | None,
) -> subprocess.CompletedProcess[str]:
    """Report the resolved root, running from the ``elsewhere`` workspace.

    The working directory is always a *valid* project, so a run that reports it
    has genuinely fallen back to the directory rather than failed to resolve
    anything - which is the difference between the bug and a plain error.
    """
    inherited = os.environ.get("PYTHONPATH") or ""
    env: dict[str, str] = {
        **os.environ,
        "PYTHONPATH": (
            f"{_PACKAGE_PATH}{os.pathsep}{inherited}" if inherited else _PACKAGE_PATH
        ),
        "NO_COLOR": "1",
        "FORCE_COLOR": "0",
        # Never let a run reach the operator's own service directory or
        # storage, even on the paths that exit before contacting either.
        EnvVar.STATUS_DIR.value: str(workspaces.base / "st"),
        EnvVar.QDRANT_STORAGE_DIR.value: str(workspaces.base / "qd"),
    }
    if root_env is None:
        env.pop(EnvVar.RAG_ROOT.value, None)
    else:
        env[EnvVar.RAG_ROOT.value] = root_env
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "vaultspec_rag",
            *args,
            "preprocess",
            "status",
            "--json",
        ],
        capture_output=True,
        check=False,
        cwd=str(workspaces.elsewhere),
        env=env,
        encoding="utf-8",
        errors="replace",
    )


def _reported_root(result: subprocess.CompletedProcess[str]) -> Path:
    """Return the root the run actually addressed.

    The exit is checked here so a run that fails outright lands on a named
    assertion rather than on a decode error over an empty document.
    """
    assert result.returncode == 0, (
        "the run failed instead of reporting a root. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, result.stdout
    return Path(str(payload["data"]["root"]))


def _unwrapped(text: str) -> str:
    """Collapse whitespace, so an assertion does not depend on console width."""
    return re.sub(r"\s+", " ", text)


@pytest.mark.timeout(120)
def test_env_named_root_beats_the_working_directory(workspaces: _Workspaces) -> None:
    """An exported root is honoured when no ``--target`` overrides it.

    This is the defect in one assertion. Ignored, the variable leaves the run
    resolving the directory it was launched from and reporting that project
    with a successful envelope - a wrong answer, not an error.
    """
    result = _run(workspaces, root_env=str(workspaces.named))

    assert _reported_root(result) == workspaces.named.resolve(), (
        "the exported root was discarded and the working directory's project "
        f"was addressed instead. stdout={result.stdout!r}"
    )


@pytest.mark.timeout(120)
def test_target_flag_beats_the_env_named_root(workspaces: _Workspaces) -> None:
    """The flag is the operator's choice for this run and outranks the launch env."""
    result = _run(
        workspaces,
        "--target",
        str(workspaces.elsewhere),
        root_env=str(workspaces.named),
    )

    assert _reported_root(result) == workspaces.elsewhere.resolve()


@pytest.mark.timeout(120)
def test_absent_env_still_resolves_the_working_directory(
    workspaces: _Workspaces,
) -> None:
    """With neither flag nor variable, the directory the run started in decides."""
    result = _run(workspaces, root_env=None)

    assert _reported_root(result) == workspaces.elsewhere.resolve()


@pytest.mark.timeout(120)
def test_env_naming_a_non_workspace_is_refused_not_ignored(
    workspaces: _Workspaces,
) -> None:
    """A root that does not resolve fails the run and says which knob named it.

    The returncode carries the guarantee: a value that cannot be honoured must
    never be discarded in favour of a working directory that happens to
    resolve, because that is the wrong answer this whole module exists to
    prevent. The message is asserted on the variable's own name - an operator
    who passed no flag has no other way to learn what chose the directory.
    """
    result = _run(workspaces, root_env=str(workspaces.bare))

    assert result.returncode == 1, (
        "a root that cannot be honoured was ignored and the working "
        f"directory's project was addressed. stdout={result.stdout!r}"
    )
    combined = _unwrapped(result.stdout + result.stderr)
    assert f"{EnvVar.RAG_ROOT.value} names" in combined, combined
    assert _unwrapped(str(workspaces.bare)) in combined, combined


class TestTheEnvironmentValueItself:
    """What counts as a named root, asserted where the answer is observable.

    These read the variable directly rather than through a run. A blank value
    is indistinguishable end-to-end on Windows, which trims a whitespace path
    down to the working directory anyway - so a CLI-level assertion about it
    would hold whether the rule existed or not.
    """

    def test_an_unset_variable_names_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(EnvVar.RAG_ROOT.value, raising=False)

        assert env_named_root() is None

    def test_a_blank_variable_names_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exported-but-empty variable is absent, not a path made of spaces.

        Kept separate from the unset case because they take different branches:
        without this rule the blank value survives as ``Path("   ")`` and is
        handed to the workspace resolver as a root the operator never named.
        """
        monkeypatch.setenv(EnvVar.RAG_ROOT.value, "   ")

        assert env_named_root() is None

    def test_a_set_variable_names_that_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(EnvVar.RAG_ROOT.value, f"  {tmp_path}  ")

        assert env_named_root() == tmp_path

    def test_home_shorthand_is_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``~`` reaches this from a config file or a launcher, never a shell."""
        monkeypatch.setenv(EnvVar.RAG_ROOT.value, "~/somewhere")

        resolved = env_named_root()
        assert resolved is not None
        assert "~" not in str(resolved)
        assert resolved == Path("~/somewhere").expanduser()
