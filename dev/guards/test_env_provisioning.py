"""Provisioning `.env` keeps every value and takes the example's structure.

A worktree's `.env` is written by `dev.init.dotenv` and by nothing else, so
what that module promises is what an operator's credentials depend on: the
structure is the example's, a new file is seeded with the declared values of
the default-branch worktree, an existing file keeps its own values, and
nothing an operator's own file holds is dropped. Each promise is exercised
against real files and a real repository with a linked worktree; nothing here
is replaced by a stand-in.

Both guards were proven able to fail, each run alone and restored afterwards.
With the unreadable-line check removed from ``read_values``,
``test_an_unreadable_line_refuses_the_rewrite`` failed on the exit-code
assertion. With the declared-names filter removed from ``provision``,
``test_a_seed_value_the_example_does_not_declare_is_not_copied`` failed on the
content assertion.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dev.init import plan
from dev.init.dotenv import (
    DEFAULT_BRANCH,
    TEMPLATE_ASSIGNMENT,
    provision,
    render,
    seed_source,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

EXAMPLE = """\
# Header prose that mentions ALPHA= nowhere near a line start.

# What alpha does (default: 1).
# ALPHA=1

# What beta does (default: unset).
# BETA=
"""


def _example(directory: Path) -> Path:
    path = directory / ".env.example"
    path.write_text(EXAMPLE, encoding="utf-8", newline="\n")
    return path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=provisioning-test",
            "-c",
            "user.email=provisioning-test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def worktrees(tmp_path: Path) -> tuple[Path, Path]:
    """A repository on the default branch, and a linked worktree off it."""
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "--initial-branch", DEFAULT_BRANCH)
    _git(primary, "commit", "--allow-empty", "-m", "root")
    linked = tmp_path / "linked"
    _git(primary, "worktree", "add", "-b", "feature", str(linked))
    return primary, linked


def test_a_new_file_without_a_seed_is_the_example(tmp_path: Path) -> None:
    example = _example(tmp_path)
    target = tmp_path / ".env"

    assert provision(example, target) == 0

    assert target.read_text(encoding="utf-8") == EXAMPLE


def test_a_new_file_takes_the_seed_values_in_the_example_structure(
    tmp_path: Path,
) -> None:
    example = _example(tmp_path)
    seed = tmp_path / "seed.env"
    seed.write_text("# the seed's own layout\nBETA=secret value\n", encoding="utf-8")
    target = tmp_path / ".env"

    assert provision(example, target, seed) == 0

    assert target.read_text(encoding="utf-8") == EXAMPLE.replace(
        "# BETA=", "BETA=secret value"
    )


def test_a_seed_value_the_example_does_not_declare_is_not_copied(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A name nothing reads does not spread into every new worktree."""
    example = _example(tmp_path)
    seed = tmp_path / "seed.env"
    seed.write_text("ALPHA=2\nSTRAY_TOKEN=do-not-copy\n", encoding="utf-8")
    target = tmp_path / ".env"

    assert provision(example, target, seed) == 0

    assert target.read_text(encoding="utf-8") == EXAMPLE.replace("# ALPHA=1", "ALPHA=2")
    assert "not copied: STRAY_TOKEN" in capsys.readouterr().out
    assert "do-not-copy" in seed.read_text(encoding="utf-8")


def test_an_undeclared_value_in_an_existing_file_is_kept(tmp_path: Path) -> None:
    """Restructuring never deletes from the operator's own file."""
    example = _example(tmp_path)
    target = tmp_path / ".env"
    target.write_text("ALPHA=2\nSTRAY_TOKEN=keep-me\n", encoding="utf-8")

    assert provision(example, target) == 0

    text = target.read_text(encoding="utf-8")
    assert text.startswith(EXAMPLE.replace("# ALPHA=1", "ALPHA=2"))
    assert text.endswith("STRAY_TOKEN=keep-me\n")
    assert "# Not declared in .env.example" in text


def test_an_existing_file_keeps_its_own_values_over_the_seed(tmp_path: Path) -> None:
    example = _example(tmp_path)
    seed = tmp_path / "seed.env"
    seed.write_text("ALPHA=from-seed\nBETA=from-seed\n", encoding="utf-8")
    target = tmp_path / ".env"
    target.write_text("# a stale layout\nALPHA=mine\n", encoding="utf-8")

    assert provision(example, target, seed) == 0

    assert target.read_text(encoding="utf-8") == EXAMPLE.replace(
        "# ALPHA=1", "ALPHA=mine"
    )


def test_a_second_run_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    example = _example(tmp_path)
    target = tmp_path / ".env"
    target.write_text("BETA=x\nSTRAY_TOKEN=y\n", encoding="utf-8")
    assert provision(example, target) == 0
    first = target.read_bytes()
    capsys.readouterr()

    assert provision(example, target) == 0

    assert target.read_bytes() == first
    assert "already matches" in capsys.readouterr().out


def test_an_unreadable_line_refuses_the_rewrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A line that is not an assignment may be the rest of a credential."""
    example = _example(tmp_path)
    target = tmp_path / ".env"
    original = 'BETA="first line\nsecond line of the same secret"\n'
    target.write_text(original, encoding="utf-8", newline="\n")

    assert provision(example, target) == 1

    assert target.read_text(encoding="utf-8") == original
    refusal = capsys.readouterr().err
    assert f"{target}:2" in refusal
    assert "second line" not in refusal


def test_the_seed_is_the_default_branch_worktree(
    worktrees: tuple[Path, Path],
) -> None:
    primary, linked = worktrees
    (primary / ".env").write_text("ALPHA=2\n", encoding="utf-8")

    seed = seed_source(linked, ".env")

    assert seed is not None
    assert seed.resolve() == (primary / ".env").resolve()


def test_the_default_branch_worktree_does_not_seed_itself(
    worktrees: tuple[Path, Path],
) -> None:
    primary, _ = worktrees
    (primary / ".env").write_text("ALPHA=2\n", encoding="utf-8")

    assert seed_source(primary, ".env") is None


def test_no_seed_when_the_default_branch_worktree_has_no_file(
    worktrees: tuple[Path, Path],
) -> None:
    _, linked = worktrees

    assert seed_source(linked, ".env") is None


def test_no_seed_outside_a_repository(tmp_path: Path) -> None:
    assert seed_source(tmp_path, ".env") is None


def test_the_committed_example_survives_its_own_rendering() -> None:
    """The real example round-trips, and can place every name it declares.

    A template the renderer rewrote on an empty value set would make every
    fresh `.env` differ from the file it was provisioned from.
    """
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    names = [
        match.group(1)
        for line in text.splitlines()
        if (match := TEMPLATE_ASSIGNMENT.match(line)) is not None
    ]

    assert render(text, {}).text == text
    rendering = render(text, dict.fromkeys(names, "value"))
    assert sorted(rendering.placed) == sorted(set(names))
    assert rendering.undeclared == ()


def test_every_init_entry_point_provisions_the_environment_file() -> None:
    steps = [step for step in plan.PREFLIGHT if step.name == "dotenv"]

    assert [step.argv[-2:] for step in steps] == [(".env.example", ".env")]
