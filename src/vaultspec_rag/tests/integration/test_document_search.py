"""Real-store search coverage for the independent document domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...indexer import DocumentIndexer
from ...progress import NullProgressReporter
from ...search import VaultSearcher
from ._helpers import _document_policy

if TYPE_CHECKING:
    from pathlib import Path

    from ..conftest import RagComponentsWithManifest

pytestmark = [pytest.mark.integration, pytest.mark.timeout(600)]


def test_document_and_combined_search_use_real_content_and_stable_selection(
    rag_components_with_code: RagComponentsWithManifest,
) -> None:
    root: Path = rag_components_with_code["root"]
    model = rag_components_with_code["model"]
    store = rag_components_with_code["store"]
    records = root / "records"
    records.mkdir(exist_ok=True)
    phrase = "independent document retrieval evidence"
    for ordinal, qualifier in enumerate(("primary", "secondary", "tertiary"), 1):
        (records / f"evidence-{ordinal}.txt").write_text(
            f"{phrase} {qualifier}. " + (f"full content {ordinal} " * 40),
            encoding="utf-8",
        )

    store.drop_document_table()
    store.ensure_document_table()
    try:
        indexer = DocumentIndexer(
            root,
            model,
            store,
            content_policy=_document_policy("records/*.txt"),
        )
        indexed = indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert indexed.total >= 3
        assert store.count_document() >= 3

        searcher = VaultSearcher(
            root, model, store, reranker=rag_components_with_code["reranker"]
        )
        documents = searcher.search_document(phrase, top_k=3)
        assert len(documents) == 3
        assert all(result.source == "document" for result in documents)
        assert all(result.path.startswith("records/") for result in documents)
        assert all(result.rerank_text for result in documents)
        assert all(
            len(result.rerank_text or "") > len(result.snippet) for result in documents
        )

        filtered = searcher.search_document(
            phrase,
            top_k=3,
            source_path="records/evidence-2.txt",
        )
        assert filtered
        assert {result.path for result in filtered} == {"records/evidence-2.txt"}

        first = searcher.search_combined(phrase, top_k=3)
        second = searcher.search_combined(phrase, top_k=3)
        assert [(result.source, result.id) for result in first] == [
            (result.source, result.id) for result in second
        ]
        assert len(first) == 3
        assert any(result.source == "document" for result in first)
    finally:
        store.drop_document_table()
        store.ensure_document_table()
