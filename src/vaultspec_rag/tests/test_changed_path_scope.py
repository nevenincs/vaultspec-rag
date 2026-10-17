"""A changed-path scope drops link-reached paths instead of failing the batch.

A directory link or junction inside the root makes ``os.walk`` and the
watcher report paths under it, while their canonical form lies elsewhere.
Admission requires canonical sources, so those paths hold no indexed content.
One of them in a watcher batch must not fail every real change beside it.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from ..indexer._content_discovery import CodeContentDiscovery, normalize_changed_paths
from ..indexer._content_policy import ContentKind
from ..indexer._document_indexer import DocumentIndexer

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _link_directory(link: Path, target: Path) -> None:
    """Create a directory junction on Windows and a symlink elsewhere."""
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.fixture
def linked_root(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return a root, a real source in it, and a path reached through a link.

    The link sits in an ignored directory and points outside the root, the
    layout an archived run directory leaves behind.
    """
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / ".gitignore").write_text("var/\n", encoding="utf-8")
    source = root / "src" / "module.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    archive = tmp_path / "archive"
    (archive / "venv").mkdir(parents=True)
    (archive / "venv" / ".gitignore").write_text("*\n", encoding="utf-8")
    (root / "var").mkdir()
    _link_directory(root / "var" / "run", archive)
    linked = root / "var" / "run" / "venv" / ".gitignore"
    assert linked.is_file()
    assert not linked.resolve().is_relative_to(root.resolve())
    return root.resolve(), source.resolve(), linked


@pytest.mark.parametrize("kind", [ContentKind.CODE, ContentKind.DOCUMENT])
def test_a_link_reached_path_leaves_the_scope(
    linked_root: tuple[Path, Path, Path], kind: ContentKind
) -> None:
    """Mutation proof: raising for every path that resolves outside the root
    (the containment check before this fix) fails here with "index scope
    contains a path outside its root"; restoring the drop passes.
    """
    root, source, linked = linked_root
    assert normalize_changed_paths(root, [source, linked], kind) == (source,)


def test_code_preflight_keeps_the_real_change_beside_a_link_reached_path(
    linked_root: tuple[Path, Path, Path],
) -> None:
    root, source, linked = linked_root
    preflight = CodeContentDiscovery(root).preflight_changed_paths([source, linked])
    assert preflight.changed_paths == (source,)


def test_document_preflight_keeps_the_real_change_beside_a_link_reached_path(
    linked_root: tuple[Path, Path, Path],
) -> None:
    root, source, linked = linked_root
    indexer = DocumentIndexer.for_preflight(root)
    preflight = indexer.preflight_changed_paths([source, linked])
    assert preflight.changed_paths == (source,)


def test_a_path_named_outside_the_root_is_still_refused(
    linked_root: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """Mutation proof: dropping the named-outside refusal (returning the
    filtered scope unconditionally) fails here on the missing ValueError;
    restoring it passes.
    """
    root, _source, _linked = linked_root
    outside = tmp_path / "archive" / "venv" / ".gitignore"
    with pytest.raises(
        ValueError, match=r"^code index scope contains a path outside its root$"
    ):
        normalize_changed_paths(root, [outside], ContentKind.CODE)
