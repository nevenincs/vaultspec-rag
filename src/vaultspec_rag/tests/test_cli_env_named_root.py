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
from vaultspec_core.config import VAULTSPEC_TARGET_DIR, ConfigurationError

from .._named_root import named_root
from ..config._types import EnvVar

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
    framework_env: str | None = None,
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
        # The console folds a word longer than its width mid-token, which no
        # whitespace collapsing can undo; a long temporary path would then
        # never match the message that names it.
        "COLUMNS": "4096",
        # Never let a run reach the operator's own service directory or
        # storage, even on the paths that exit before contacting either.
        EnvVar.STATUS_DIR.value: str(workspaces.base / "st"),
        EnvVar.QDRANT_STORAGE_DIR.value: str(workspaces.base / "qd"),
    }
    if root_env is None:
        env.pop(EnvVar.RAG_ROOT.value, None)
    else:
        env[EnvVar.RAG_ROOT.value] = root_env
    if framework_env is None:
        env.pop(VAULTSPEC_TARGET_DIR.env_name, None)
    else:
        env[VAULTSPEC_TARGET_DIR.env_name] = framework_env
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
def test_the_framework_root_beats_the_working_directory(
    workspaces: _Workspaces,
) -> None:
    """A session that names one workspace for every vaultspec tool names this one.

    The run starts in a different, equally valid project, so falling through
    to the working directory produces a successful envelope about the wrong
    one - the same wrong answer the scoped name was added to prevent, one
    rung further down the chain.
    """
    result = _run(workspaces, root_env=None, framework_env=str(workspaces.named))

    assert _reported_root(result) == workspaces.named.resolve(), (
        "the shared root was discarded and the working directory's project "
        f"was addressed instead. stdout={result.stdout!r}"
    )


@pytest.mark.timeout(120)
def test_the_scoped_root_beats_the_framework_root(workspaces: _Workspaces) -> None:
    """Pointing this tool elsewhere does not mean unsetting the shared name."""
    result = _run(
        workspaces,
        root_env=str(workspaces.named),
        framework_env=str(workspaces.elsewhere),
    )

    assert _reported_root(result) == workspaces.named.resolve()


@pytest.mark.timeout(120)
def test_a_framework_root_that_is_not_a_workspace_names_its_own_variable(
    workspaces: _Workspaces,
) -> None:
    """The refusal names the variable the operator actually set.

    Naming this package's own variable here would send somebody looking for
    a setting they never made, while the one that chose the directory went
    unmentioned.
    """
    result = _run(workspaces, root_env=None, framework_env=str(workspaces.bare))

    assert result.returncode == 1, result.stdout
    combined = _unwrapped(result.stdout + result.stderr)
    assert VAULTSPEC_TARGET_DIR.env_name in combined, combined
    assert EnvVar.RAG_ROOT.value not in combined, combined


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

    These read the variables directly rather than through a run. A blank value
    is indistinguishable end-to-end on Windows, which trims a whitespace path
    down to the working directory anyway - so a CLI-level assertion about it
    would hold whether the rule existed or not.
    """

    @staticmethod
    def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(EnvVar.RAG_ROOT.value, raising=False)
        monkeypatch.delenv(VAULTSPEC_TARGET_DIR.env_name, raising=False)

    def test_an_unset_variable_names_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear(monkeypatch)

        assert named_root().path is None

    def test_a_blank_variable_names_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exported-but-empty variable is absent, not a path made of spaces.

        Kept separate from the unset case because they take different branches:
        without this rule the blank value survives as ``Path("   ")`` and is
        handed to the workspace resolver as a root the operator never named.
        """
        self._clear(monkeypatch)
        monkeypatch.setenv(EnvVar.RAG_ROOT.value, "   ")

        assert named_root().path is None

    def test_a_set_variable_names_that_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._clear(monkeypatch)
        monkeypatch.setenv(EnvVar.RAG_ROOT.value, f"  {tmp_path}  ")

        resolved = named_root()
        assert resolved.path == tmp_path.resolve()
        assert resolved.variable == EnvVar.RAG_ROOT.value

    def test_home_shorthand_is_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``~`` reaches this from a config file or a launcher, never a shell.

        Nothing downstream would expand it: a leading tilde is not absolute,
        so the root would be taken against the working directory and then
        refused as a directory that is not there.
        """
        self._clear(monkeypatch)
        monkeypatch.setenv(EnvVar.RAG_ROOT.value, "~")

        resolved = named_root()
        assert resolved.path == Path("~").expanduser().resolve()

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason=(
            "ntpath.expanduser only raises past pathlib's RuntimeError guard "
            "when neither USERPROFILE nor HOMEPATH/HOMEDRIVE is set; "
            "posixpath.expanduser falls back to the pwd database, which a "
            "real account under test typically still resolves."
        ),
    )
    def test_a_root_whose_home_cannot_be_determined_names_its_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A host with no way to resolve ``~`` refuses, naming the variable.

        ``Path.expanduser()`` itself raises a bare ``RuntimeError`` in this
        case; the resolver must not let that propagate unrelated to the
        variable an operator actually set.
        """
        self._clear(monkeypatch)
        monkeypatch.delenv("USERPROFILE", raising=False)
        monkeypatch.delenv("HOMEPATH", raising=False)
        monkeypatch.delenv("HOMEDRIVE", raising=False)
        monkeypatch.setenv(EnvVar.RAG_ROOT.value, "~/somewhere")

        with pytest.raises(ConfigurationError, match=EnvVar.RAG_ROOT.value):
            named_root()

    def test_the_framework_name_answers_behind_the_scoped_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A session naming one workspace for every tool names this one too."""
        self._clear(monkeypatch)
        monkeypatch.setenv(VAULTSPEC_TARGET_DIR.env_name, str(tmp_path))

        resolved = named_root()
        assert resolved.path == tmp_path.resolve()
        assert resolved.variable == VAULTSPEC_TARGET_DIR.env_name

    def test_the_scoped_name_outranks_the_framework_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Pointing this tool elsewhere does not require unsetting the shared name."""
        scoped = tmp_path / "scoped"
        scoped.mkdir()
        shared = tmp_path / "shared"
        shared.mkdir()
        self._clear(monkeypatch)
        monkeypatch.setenv(EnvVar.RAG_ROOT.value, str(scoped))
        monkeypatch.setenv(VAULTSPEC_TARGET_DIR.env_name, str(shared))

        assert named_root().path == scoped.resolve()

    def test_the_invocation_outranks_both(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._clear(monkeypatch)
        monkeypatch.setenv(EnvVar.RAG_ROOT.value, str(tmp_path))

        resolved = named_root(tmp_path / "named-by-the-call")
        assert resolved.path == (tmp_path / "named-by-the-call").resolve()
        assert resolved.variable is None

    def test_a_root_that_is_not_there_is_refused_naming_its_variable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A missing directory cannot be discovered past.

        The operator asked for one workspace, so falling through to discovery
        would silently answer about another - and the refusal has to name
        whichever of the two names actually carried the value.
        """
        self._clear(monkeypatch)
        monkeypatch.setenv(VAULTSPEC_TARGET_DIR.env_name, str(tmp_path / "absent"))

        with pytest.raises(ConfigurationError, match=VAULTSPEC_TARGET_DIR.env_name):
            named_root()
