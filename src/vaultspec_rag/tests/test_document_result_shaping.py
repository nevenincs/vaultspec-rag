"""Real-payload tests for document-native result shaping."""

from __future__ import annotations

import pytest

from ..search._result_shaping import map_document_results

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
    assert map_document_results(
        [
            {
                "id": "chunk-1",
                "source_path": "manuals/guide.bin",
                "content": "content",
                "document_metadata": "invalid",
                "unit_metadata": {},
            }
        ]
    ) == []
