"""Real-store public search checks for independent document ownership."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..._public_search import (
    DocumentCombinedSearchFilters,
    search_combined,
    search_documents,
)
from ...api import index_documents
from ...indexer._content_policy import (
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ...registry import get_registry

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def _document_policy() -> RootContentPolicy:
    return RootContentPolicy(
        SourceProfileVersion.CONVENTIONAL_V1,
        (ContentRoute("records/*.txt", ContentKind.DOCUMENT),),
    )


def test_empty_document_and_combined_search_need_no_model(tmp_path: Path) -> None:
    assert search_documents(tmp_path, "query") == []
    combined = search_combined(tmp_path, "query")
    assert combined.results == []
    assert not combined.partial
    assert combined.vault.ok
    assert combined.code.ok
    assert combined.document.ok


@pytest.mark.timeout(600)
def test_non_empty_public_facade_applies_document_owned_combined_filters(
    tmp_path: Path,
) -> None:
    records = tmp_path / "records"
    records.mkdir()
    phrase = "bounded independent retrieval evidence"
    selected_path = "records/selected.txt"
    (tmp_path / selected_path).write_text(
        f"{phrase}. This selected record proves public facade retrieval. " * 20,
        encoding="utf-8",
    )
    (records / "other.txt").write_text(
        f"{phrase}. This second record must be removed by source filtering. " * 20,
        encoding="utf-8",
    )

    indexed = index_documents(
        tmp_path,
        full=True,
        content_policy=_document_policy(),
    )
    try:
        assert indexed.total >= 2
        documents = search_documents(
            tmp_path,
            phrase,
            top_k=5,
            source_path=selected_path,
        )
        assert documents
        assert {result.path for result in documents} == {selected_path}

        combined = search_combined(
            tmp_path,
            phrase,
            top_k=5,
            document_filters=DocumentCombinedSearchFilters(
                source_path=selected_path,
            ),
        )
        assert combined.ok
        assert combined.document.ok
        assert combined.document.results
        assert {result.path for result in combined.document.results} == {selected_path}
        assert {result.path for result in combined.results} == {selected_path}
    finally:
        get_registry().close_project(tmp_path.resolve())
