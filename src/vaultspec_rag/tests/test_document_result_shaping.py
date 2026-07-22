"""Real-payload tests for document-native result shaping."""

from __future__ import annotations

import pytest

from ..search._models import DocumentSearchResult, SearchResult
from ..search._result_shaping import map_document_results, select_combined_results

pytestmark = pytest.mark.unit


def test_document_result_retains_identity_locator_metadata_and_rerank_text() -> None:
    content = "Full extracted content used for reranking"
    results = map_document_results(
        [
            {
                "id": "chunk-1",
                "source_path": "manuals/guide.bin",
                "title": "Guide",
                "section": "Setup",
                "anchor": "page-4",
                "content": content,
                "locator_kind": "page",
                "locator_value_int": 4,
                "document_metadata": {"owner": "docs"},
                "unit_metadata": {"language": "en"},
                "extractor_id": "extractor",
                "extractor_version": "2",
                "_relevance_score": 0.75,
            }
        ]
    )
    assert len(results) == 1
    result = results[0]
    assert result.path == "manuals/guide.bin"
    assert result.locator is not None
    assert result.locator.kind == "page"
    assert result.locator.value == 4
    assert result.document_metadata.materialize() == {"owner": "docs"}
    assert result.unit_metadata.materialize() == {"language": "en"}
    assert result.rerank_text == content


def test_invalid_document_metadata_does_not_escape_as_mis_shaped_hit() -> None:
    assert (
        map_document_results(
            [
                {
                    "id": "chunk-1",
                    "source_path": "manuals/guide.bin",
                    "content": "content",
                    "document_metadata": "invalid",
                    "unit_metadata": {},
                }
            ]
        )
        == []
    )


def test_combined_selection_is_stable_across_equal_domain_scores() -> None:
    vault = SearchResult("v", "z.md", "Vault", 0.5, "v", "vault")
    code = SearchResult("c", "a.py", "Code", 0.5, "c", "codebase")
    document = DocumentSearchResult("d", "a.bin", "Document", 0.8, "d")
    assert select_combined_results([code, vault, document], 2) == [document, vault]
