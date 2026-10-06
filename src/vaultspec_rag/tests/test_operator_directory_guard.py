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

The cases for ``uv run`` and the other project verbs keep that idiom in both
directions. A launch the guard must let through is still started in a
directory that does not exist, so what it proves is the error the operating
system raises once the guard has stood aside: an ``OSError``, which the
refusal is not. That error is ``NotADirectoryError`` on Windows, where each
mutation recorded below was run, and ``FileNotFoundError`` elsewhere. Each
case records the mutation it was seen to fail under.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ._operator_directory_guard import (
    OperatorDirectoryWriteError,
    _command_words,
    _discovered_environment,
    guarded_operator_roots,
)

pytestmark = pytest.mark.unit

#: uv's own name for where a project's environment lives.
_PROJECT_ENVIRONMENT = "UV_PROJECT_ENVIRONMENT"

#: Program text whose one double quote leaves a joined Windows command line
#: with an odd number of them, which is what a quote-pairing splitter cannot
#: read. The dev harness's capability probe is text of this kind.
_QUOTED_PROGRAM = "value = '\"'"


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


def _run_through_uv(*options: str) -> list[str]:
    """Return a ``uv run`` launch of a child that would do nothing."""
    return [_uv(), "run", *options, "python", "-c", _QUOTED_PROGRAM]


def test_a_run_outside_the_temporary_tree_is_refused(
    foreign_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``uv run --no-sync`` is refused on a project no test created.

    ``--no-sync`` does not make the launch harmless: uv creates or replaces
    the project's environment before it reads the flag.

    Mutation: with the hook's ``run`` branch disabled the launch reached the
    operating system and failed here with ``NotADirectoryError`` in place of
    the refusal; restored, it passed.
    """
    monkeypatch.delenv(_PROJECT_ENVIRONMENT, raising=False)
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing uv run on")
    ):
        subprocess.run(
            _run_through_uv("--no-sync"), cwd=foreign_environment.parent, check=False
        )
    assert not foreign_environment.parent.exists()


def test_a_run_into_an_environment_under_the_temporary_tree_is_not_refused(
    foreign_environment: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An environment of the test's own takes the launch off the project's.

    The same launch as the refused one, so it reaches an operating system
    that cannot start it in a directory that does not exist.

    Mutation: with the hook ignoring ``UV_PROJECT_ENVIRONMENT`` this raised
    the refusal for the starting directory in place of the launch error;
    restored, it passed.
    """
    monkeypatch.setenv(_PROJECT_ENVIRONMENT, str(tmp_path / "environment"))
    with pytest.raises(OSError):
        subprocess.run(
            _run_through_uv("--no-sync"), cwd=foreign_environment.parent, check=False
        )
    assert not foreign_environment.parent.exists()


@pytest.mark.parametrize("option", ["--no-project", "--isolated"])
def test_a_run_that_uses_no_project_environment_is_not_refused(
    option: str, foreign_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A launch told to leave the project's environment alone has no target.

    Mutation: with both options emptied out of the hook, both cases raised
    the refusal in place of the launch error; restored, both passed.
    """
    monkeypatch.delenv(_PROJECT_ENVIRONMENT, raising=False)
    with pytest.raises(OSError):
        subprocess.run(
            _run_through_uv("--no-sync", option),
            cwd=foreign_environment.parent,
            check=False,
        )
    assert not foreign_environment.parent.exists()


@pytest.mark.parametrize("option", ["--project", "--directory"])
def test_a_run_on_a_project_under_the_temporary_tree_is_not_refused(
    option: str,
    foreign_environment: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A launch is judged on the project it names, not on where it starts.

    Mutation: with the hook judging the starting directory whatever project
    is named, both cases raised the refusal in place of the launch error;
    restored, both passed.
    """
    monkeypatch.delenv(_PROJECT_ENVIRONMENT, raising=False)
    with pytest.raises(OSError):
        subprocess.run(
            _run_through_uv("--no-sync", option, str(tmp_path)),
            cwd=foreign_environment.parent,
            check=False,
        )
    assert not foreign_environment.parent.exists()


def test_a_project_named_by_the_command_does_not_stand_in_for_uvs(
    foreign_environment: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An option of the program being run is not read as uv's own.

    uv still acts on the directory the launch starts in, whatever project
    the program it runs was pointed at.

    Mutation: with every word after ``run`` read as uv's own, the launch was
    judged on the program's project, let through, and failed here with
    ``NotADirectoryError``; restored, it passed.
    """
    monkeypatch.delenv(_PROJECT_ENVIRONMENT, raising=False)
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing uv run on")
    ):
        subprocess.run(
            [*_run_through_uv("--no-sync"), "--project", str(tmp_path)],
            cwd=foreign_environment.parent,
            check=False,
        )
    assert not foreign_environment.parent.exists()


def test_a_run_on_the_interpreters_own_environment_is_not_refused(
    foreign_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``uv run --no-sync`` may use the environment this session runs from.

    That is the one environment outside the temporary tree uv is known to
    find usable, and the flag keeps it from installing anything into it.

    Mutation: with the hook recognising no environment as the interpreter's
    own, this raised the refusal naming ``sys.prefix`` in place of the launch
    error; restored, it passed.
    """
    monkeypatch.setenv(_PROJECT_ENVIRONMENT, sys.prefix)
    with pytest.raises(OSError):
        subprocess.run(
            _run_through_uv("--no-sync"), cwd=foreign_environment.parent, check=False
        )
    assert not foreign_environment.parent.exists()


def test_a_syncing_run_on_the_interpreters_own_environment_is_refused(
    foreign_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``--no-sync`` the same launch would install into it.

    Mutation: with the flag no longer required, and separately with the
    hook's ``run`` branch disabled, the launch was let through and failed
    here with ``NotADirectoryError``; restored, it passed.
    """
    monkeypatch.setenv(_PROJECT_ENVIRONMENT, sys.prefix)
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing uv run on")
    ):
        subprocess.run(_run_through_uv(), cwd=foreign_environment.parent, check=False)
    assert not foreign_environment.parent.exists()


@pytest.mark.parametrize(
    "arguments",
    [("lock",), ("add", "requests"), ("remove", "requests"), ("venv",)],
    ids=["lock", "add", "remove", "venv"],
)
def test_a_project_verb_outside_the_temporary_tree_is_refused(
    arguments: tuple[str, ...],
    foreign_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every verb that writes a project or its environment is judged.

    Mutation: with the file-writing verbs cut back to ``sync``, the lock, add
    and remove cases were let through and failed with ``NotADirectoryError``;
    with the ``venv`` branch disabled the venv case did. Restored, all four
    passed.
    """
    monkeypatch.delenv(_PROJECT_ENVIRONMENT, raising=False)
    with pytest.raises(
        OperatorDirectoryWriteError,
        match=re.escape(f"refusing uv {arguments[0]} on"),
    ):
        subprocess.run([_uv(), *arguments], cwd=foreign_environment.parent, check=False)
    assert not foreign_environment.parent.exists()


def test_a_project_verb_is_judged_on_its_project_as_well_as_its_environment(
    foreign_environment: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Moving the environment does not move the files a sync writes.

    The lockfile stays in the project, so a project no test created is
    refused even when its environment is one a test did create.

    Mutation: with a stated environment standing in for the project, the
    sync was let through and failed here with ``NotADirectoryError``;
    restored, it passed.
    """
    monkeypatch.setenv(_PROJECT_ENVIRONMENT, str(tmp_path / "environment"))
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing uv sync on")
    ):
        subprocess.run([_uv(), "sync"], cwd=foreign_environment.parent, check=False)
    assert not foreign_environment.parent.exists()


def test_a_sync_into_a_foreign_environment_is_refused(
    foreign_environment: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project under the temporary tree cannot carry a launch elsewhere.

    Mutation: with the project the only thing judged, and separately with
    the hook ignoring ``UV_PROJECT_ENVIRONMENT``, the sync was let through
    and failed here with ``NotADirectoryError``; restored, it passed.
    """
    monkeypatch.setenv(_PROJECT_ENVIRONMENT, str(foreign_environment))
    with pytest.raises(
        OperatorDirectoryWriteError,
        match=re.escape(f"refusing uv sync on {foreign_environment}"),
    ):
        subprocess.run(
            [_uv(), "sync", "--project", str(tmp_path)],
            cwd=foreign_environment.parent,
            check=False,
        )
    assert not foreign_environment.parent.exists()


def test_a_run_handed_to_a_foreign_active_environment_is_refused(
    foreign_environment: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--active`` puts the launch on ``VIRTUAL_ENV`` ahead of anything else.

    Mutation: with the option ignored the launch was judged on the
    environment under the temporary tree, let through, and failed here with
    ``NotADirectoryError``; restored, it passed.
    """
    monkeypatch.setenv(_PROJECT_ENVIRONMENT, str(tmp_path / "environment"))
    monkeypatch.setenv("VIRTUAL_ENV", str(foreign_environment))
    with pytest.raises(
        OperatorDirectoryWriteError,
        match=re.escape(f"refusing uv run on {foreign_environment}"),
    ):
        subprocess.run(
            _run_through_uv("--no-sync", "--active"),
            cwd=foreign_environment.parent,
            check=False,
        )
    assert not foreign_environment.parent.exists()


def test_a_project_named_past_an_option_the_guard_cannot_read_is_refused(
    foreign_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A launch is not let through on a reading of it that may be wrong.

    ``--with`` takes a value, which the guard reads as the start of the
    command. The project named after it is uv's own, and not the session's.

    Mutation: with a project named after the options ended trusted to be the
    command's, the launch was let through as one on the interpreter's own
    environment and failed here with ``NotADirectoryError``; restored, it
    passed.
    """
    monkeypatch.setenv(_PROJECT_ENVIRONMENT, sys.prefix)
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing uv run on")
    ):
        subprocess.run(
            _run_through_uv(
                "--no-sync", "--with", "requests", "--project", str(foreign_environment)
            ),
            cwd=foreign_environment.parent,
            check=False,
        )
    assert not foreign_environment.parent.exists()


def test_options_ahead_of_the_verb_do_not_hide_a_run(
    foreign_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uv's own options may come first, and one of them may take a value.

    Mutation: with a word after an option taken for the verb unless it names
    a judged one, ``never`` was read as the verb, the launch went unjudged
    and failed here with ``NotADirectoryError``; restored, it passed.
    """
    monkeypatch.delenv(_PROJECT_ENVIRONMENT, raising=False)
    launch = _run_through_uv("--no-sync")
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing uv run on")
    ):
        subprocess.run(
            [launch[0], "--quiet", "--color", "never", *launch[1:]],
            cwd=foreign_environment.parent,
            check=False,
        )
    assert not foreign_environment.parent.exists()


def test_a_dry_run_flag_of_the_command_does_not_excuse_a_run(
    foreign_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``uv run`` has no dry run; the flag is the program's, and uv still acts.

    Mutation: with ``--dry-run`` excusing every verb the launch was let
    through and failed here with ``NotADirectoryError``; restored, it passed.
    """
    monkeypatch.delenv(_PROJECT_ENVIRONMENT, raising=False)
    with pytest.raises(
        OperatorDirectoryWriteError, match=re.escape("refusing uv run on")
    ):
        subprocess.run(
            [*_run_through_uv("--no-sync"), "--dry-run"],
            cwd=foreign_environment.parent,
            check=False,
        )
    assert not foreign_environment.parent.exists()


def test_an_environment_created_at_a_foreign_path_is_refused(
    foreign_environment: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``uv venv`` is refused on a path that may be the one it creates.

    ``--seed`` takes no value, so the word after it is the path; the guard
    cannot know that of every option, and judges the word as one.

    Mutation: with the words that may be the path left unjudged, and
    separately with the ``venv`` branch disabled, the launch was let through
    and failed here with ``NotADirectoryError``; restored, it passed.
    """
    monkeypatch.delenv(_PROJECT_ENVIRONMENT, raising=False)
    with pytest.raises(
        OperatorDirectoryWriteError,
        match=re.escape(f"refusing uv venv on {foreign_environment}"),
    ):
        subprocess.run(
            [
                _uv(),
                "venv",
                "--project",
                str(tmp_path),
                "--seed",
                str(foreign_environment),
            ],
            cwd=foreign_environment.parent,
            check=False,
        )
    assert not foreign_environment.parent.exists()


def test_an_environment_created_under_the_temporary_tree_is_not_refused(
    foreign_environment: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``uv venv`` is judged on the path it is given, not on where it starts.

    Mutation: with every word that is not an option taken for the path,
    ``3.13`` was judged as a directory beside the launch and this raised the
    refusal in place of the launch error; restored, it passed.
    """
    monkeypatch.delenv(_PROJECT_ENVIRONMENT, raising=False)
    with pytest.raises(OSError):
        subprocess.run(
            [_uv(), "venv", "--python", "3.13", str(tmp_path / "environment")],
            cwd=foreign_environment.parent,
            check=False,
        )
    assert not foreign_environment.parent.exists()


def test_a_command_line_carrying_program_text_is_read_back_whole() -> None:
    """A launch is judged whatever its arguments contain.

    Windows audits the joined command line, so the guard has to split what
    the launcher joined. Quotes, backslashes and a trailing backslash are the
    shapes that joining escapes.

    Mutation: splitting on whitespace alone, and separately reading an
    escaped quote as the end of a quoted stretch, each failed this equality
    at the program text; restored, it passed.
    """
    launch = [
        "uv",
        "run",
        "--no-sync",
        "python",
        "-c",
        'import json\nprint(json.dumps({"cuda": False}), \'"\')\n',
        "C:\\some where\\",
        "",
        'ends\\\\"',
    ]
    assert _command_words(subprocess.list2cmdline(launch)) == launch


def test_the_environment_uv_finds_is_the_nearest_projects(tmp_path: Path) -> None:
    """uv's project is the nearest directory above the launch with a manifest.

    Mutation: looking only in the starting directory failed the first
    assertion with no environment found, and taking the outermost project
    failed the second with the outer one; restored, it passed.
    """
    outer = tmp_path / "outer"
    nested = outer / "packages" / "nested"
    (nested / "src").mkdir(parents=True)
    (outer / "pyproject.toml").write_text("", encoding="utf-8")

    assert _discovered_environment(str(nested / "src")) == str(outer / ".venv")

    (nested / "pyproject.toml").write_text("", encoding="utf-8")
    assert _discovered_environment(str(nested / "src")) == str(nested / ".venv")
    assert _discovered_environment(str(outer)) == str(outer / ".venv")


def test_no_project_above_a_launch_means_no_environment(tmp_path: Path) -> None:
    """A directory under no project has no environment to be this session's.

    Mutation: falling back to a ``.venv`` beside the launch returned that
    path here; restored, it passed.
    """
    assert _discovered_environment(str(tmp_path)) is None
