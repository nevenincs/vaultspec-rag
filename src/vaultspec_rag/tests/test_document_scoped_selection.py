"""A scoped document run selects only event paths whose content changed.

A file event can name a path whose bytes are unchanged. Selecting it makes
the run republish identical points, and the publication then fails with
mutations that produced no proof change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..indexer._document_file import DocumentFileMetadata
from ..indexer._document_indexer import DocumentIndexer
from ..indexer._stat_gate import file_digest
from .integration._helpers import _document_policy

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _committed(root: Path, *paths: Path) -> dict[str, DocumentFileMetadata]:
    """Record each path's current content as its committed fingerprint."""
    committed: dict[str, DocumentFileMetadata] = {}
    for path in paths:
        rel = path.relative_to(root).as_posix()
        digest = file_digest(path, root_dir=root)
        committed[rel] = DocumentFileMetadata(rel, digest, (f"{rel}-point",))
    return committed


def _select(root: Path, paths: tuple[Path, ...], previous) -> set[str]:
    indexer = DocumentIndexer.for_preflight(
        root, content_policy=_document_policy("*.txt")
    )
    return indexer._select_incremental_paths(paths, previous, scoped=True)


def test_an_unchanged_event_path_is_not_selected(tmp_path: Path) -> None:
    # Fails without the scoped content-hash filter, which selected every
    # event path regardless of content.
    doc = tmp_path / "alpha.txt"
    doc.write_text("unchanged body\n", encoding="utf-8")
    previous = _committed(tmp_path, doc)
    doc.write_text("unchanged body\n", encoding="utf-8")

    assert _select(tmp_path, (doc,), previous) == set()


def test_only_the_changed_event_path_is_selected(tmp_path: Path) -> None:
    changed = tmp_path / "alpha.txt"
    same = tmp_path / "beta.txt"
    changed.write_text("first body\n", encoding="utf-8")
    same.write_text("steady body\n", encoding="utf-8")
    previous = _committed(tmp_path, changed, same)
    changed.write_text("second body\n", encoding="utf-8")

    assert _select(tmp_path, (changed, same), previous) == {"alpha.txt"}


def test_created_and_deleted_event_paths_stay_selected(tmp_path: Path) -> None:
    gone = tmp_path / "gone.txt"
    gone.write_text("about to go\n", encoding="utf-8")
    previous = _committed(tmp_path, gone)
    gone.unlink()
    created = tmp_path / "new.txt"
    created.write_text("fresh body\n", encoding="utf-8")

    assert _select(tmp_path, (gone, created), previous) == {"gone.txt", "new.txt"}
