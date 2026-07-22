"""Public model coverage for document-native service results."""

from __future__ import annotations

import pytest

from .._store_models import DocumentLocator, DocumentMetadata
from ..search._models import DocumentSearchResult
from ..server._models import IndexStatus, SearchResultItem

pytestmark = pytest.mark.unit


def test_document_search_result_serializes_without_losing_native_fields() -> None:
    result = DocumentSearchResult(
        id="chunk-1",
        path="manuals/guide.bin",
        title="Guide",
        score=0.8,
        snippet="setup",
        section="Setup",
        locator=DocumentLocator("page", 4),
        document_metadata=DocumentMetadata.from_mapping({"owner": "docs"}),
        unit_metadata=DocumentMetadata.from_mapping({"language": "en"}),
        extractor_id="extractor",
        extractor_version="2",
    )
    payload = SearchResultItem.model_validate(result).model_dump()
    assert payload["source"] == "document"
    assert payload["locator"] == {"kind": "page", "value": 4, "end": None}
    assert payload["section"] == "Setup"
    assert payload["document_metadata"] == {"owner": "docs"}
    assert payload["unit_metadata"] == {"language": "en"}


def test_status_keeps_document_count_independent() -> None:
    status = IndexStatus(
        vault_count=1,
        code_count=2,
        document_count=3,
        storage_path="data",
        target_dir="project",
    )
    assert (status.vault_count, status.code_count, status.document_count) == (1, 2, 3)
