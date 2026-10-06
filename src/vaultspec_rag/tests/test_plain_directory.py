"""A directory beneath a root is reached without following a link out of it.

Real filesystem (``tmp_path``), real links. No mocks. Every test plants an
``outside`` tree next to the root that must come back byte-for-byte: the
property under test is that nothing done through a held directory lands there.

The guard tests record the mutation that makes them fail. The shared one,
called "the link check disabled" below, is ``_is_plain`` accepting every node.
A link is then never refused as one: it is held as the directory it points at
where the platform opens it, and surfaces as a bare OS error where it does not.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from .._plain_directory import (
    LinkedDirectoryError,
    ensure_plain_directory,
    open_plain_directory,
    require_plain_parents,
)
from ._directory_links import LINK_KINDS, link_directory, tree_bytes

pytestmark = [pytest.mark.unit]


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    directory = tmp_path / "root"
    directory.mkdir()
    return directory


@pytest.fixture()
def outside(tmp_path: Path) -> Path:
    """An external tree shaped like the one a link would be aimed at."""
    directory = tmp_path / "outside"
    (directory / "data").mkdir(parents=True)
    (directory / "data" / "precious.txt").write_text("keep", encoding="utf-8")
    (directory / "note.txt").write_text("keep", encoding="utf-8")
    return directory


@pytest.mark.parametrize("kind", LINK_KINDS)
def test_a_linked_container_is_refused(root: Path, outside: Path, kind: str) -> None:
    """Proven able to fail: with the link check disabled this fails on the
    ``pytest.raises`` below.
    """
    link_directory(root / "container", outside, kind)

    with (
        pytest.raises(LinkedDirectoryError, match=kind),
        open_plain_directory(root, Path("container")),
    ):
        pass


@pytest.mark.parametrize("kind", LINK_KINDS)
def test_a_linked_ancestor_is_refused_for_an_ordinary_leaf(
    root: Path, outside: Path, kind: str
) -> None:
    """The leaf is a real directory; only the directory above it is a link.

    Proven able to fail: with the link check disabled this fails on the first
    ``pytest.raises`` below.
    """
    link_directory(root / "container", outside, kind)

    with (
        pytest.raises(LinkedDirectoryError, match="container"),
        open_plain_directory(root, Path("container") / "data"),
    ):
        pass
    with pytest.raises(LinkedDirectoryError, match="container"):
        require_plain_parents(root, root / "container" / "data" / "precious.txt")


def test_a_file_where_a_directory_belongs_is_refused(root: Path) -> None:
    (root / "container").write_text("not a directory", encoding="utf-8")

    with pytest.raises(LinkedDirectoryError, match="not a directory"):
        require_plain_parents(root, root / "container" / "leaf")


def test_an_absent_component_yields_nothing_to_hold(root: Path) -> None:
    (root / "present").mkdir()

    with open_plain_directory(root, Path("present") / "absent") as held:
        assert held is None
    require_plain_parents(root, root / "present" / "absent" / "leaf")


def test_the_final_component_is_the_callers_question(root: Path, outside: Path) -> None:
    """Only the directories above a path are examined, never the path itself."""
    (root / "container").mkdir()
    link_directory(root / "container" / "leaf", outside, "symlink")

    require_plain_parents(root, root / "container" / "leaf")


def test_a_path_that_climbs_out_of_the_root_is_rejected(root: Path) -> None:
    with (
        pytest.raises(ValueError, match="beneath"),
        open_plain_directory(root, Path("..") / "elsewhere"),
    ):
        pass


def test_missing_directories_are_created_real(root: Path) -> None:
    ensure_plain_directory(root, Path("a") / "b")

    assert (root / "a" / "b").is_dir()
    assert not (root / "a").is_symlink()


@pytest.mark.parametrize("kind", LINK_KINDS)
def test_creation_does_not_accept_a_link_as_already_present(
    root: Path, outside: Path, kind: str
) -> None:
    """Proven able to fail: with the link check disabled this fails on the
    ``pytest.raises`` below.
    """
    link_directory(root / "container", outside, kind)
    before = tree_bytes(outside)

    with pytest.raises(LinkedDirectoryError):
        ensure_plain_directory(root, Path("container") / "made")

    assert tree_bytes(outside) == before


def test_entries_are_removed_through_the_held_directory(root: Path) -> None:
    container = root / "container"
    (container / "tree" / "nested").mkdir(parents=True)
    (container / "tree" / "nested" / "file.txt").write_text("x", encoding="utf-8")
    (container / "file.txt").write_text("x", encoding="utf-8")

    with open_plain_directory(root, Path("container")) as held:
        assert held is not None
        assert held.lstat("missing") is None
        held.unlink("file.txt")
        held.remove_tree("tree")

    assert list(container.iterdir()) == []


def test_removing_a_tree_unlinks_a_link_inside_it(root: Path, outside: Path) -> None:
    container = root / "container"
    (container / "tree").mkdir(parents=True)
    link_directory(container / "tree" / "escape", outside, "symlink")
    before = tree_bytes(outside)

    with open_plain_directory(root, Path("container")) as held:
        assert held is not None
        held.remove_tree("tree")

    assert not (container / "tree").exists()
    assert tree_bytes(outside) == before


def test_a_swap_after_the_directory_is_held_cannot_redirect_removal(
    root: Path, outside: Path
) -> None:
    """The container is replaced by a link AFTER it was proven real and held.

    Either the swap is refused outright, because the held directory cannot be
    renamed, or it succeeds and the removal still lands in the directory that
    was held rather than in the one its name now reaches. Both leave
    ``outside`` intact.

    Proven able to fail, on the ``outside`` assertion either way. Where
    entries are reached through the held descriptor: making ``_entry`` return
    the joined path, so removal goes by name. Where the hold pins the name
    instead: opening it with delete sharing, so the swap goes through.
    """
    container = root / "container"
    (container / "data").mkdir(parents=True)
    (container / "data" / "index.bin").write_text("index", encoding="utf-8")
    (container / "note.txt").write_text("rag", encoding="utf-8")
    displaced = root / "displaced"
    before = tree_bytes(outside)

    with open_plain_directory(root, Path("container")) as held:
        assert held is not None
        try:
            container.rename(displaced)
        except OSError:
            swapped = False
        else:
            link_directory(container, outside, "symlink")
            swapped = True
        held.unlink("note.txt")
        held.remove_tree("data")

    assert tree_bytes(outside) == before
    emptied = displaced if swapped else container
    assert list(emptied.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="held directories are pinned on Windows")
def test_a_held_directory_cannot_be_renamed_away(root: Path) -> None:
    """Windows has no descriptor-relative lookup, so the hold must pin the name.

    Proven able to fail: opening the directory with delete sharing lets the
    rename through and fails this on ``DID NOT RAISE``.
    """
    container = root / "container"
    container.mkdir()

    with (
        open_plain_directory(root, Path("container")),
        pytest.raises(PermissionError),
    ):
        container.rename(root / "displaced")

    container.rename(root / "displaced")
