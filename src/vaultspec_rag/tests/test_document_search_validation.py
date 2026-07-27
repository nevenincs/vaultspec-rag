"""Closed filter compatibility tests for document and combined search."""

from __future__ import annotations

import pytest

from ..search import (
    InvalidFilterForSearchTypeError,
    SearchFilterOptions,
    validate_search_filters,
)

pytestmark = pytest.mark.unit


def test_document_filters_are_native_only_to_document_and_combined() -> None:
    validate_search_filters(
        "document",
        SearchFilterOptions(
            source_path="manuals/guide.bin",
            extractor_id="extractor",
            extractor_version="2",
            locator_kind="page",
        ),
    )
    validate_search_filters(
        "combined",
        SearchFilterOptions(
            language="python",
            doc_type="adr",
            source_path="manuals/guide.bin",
        ),
    )
    with pytest.raises(InvalidFilterForSearchTypeError) as captured:
        validate_search_filters("code", SearchFilterOptions(locator_kind="page"))
    assert captured.value.filter_kind == "document"


def test_legacy_docs_alias_remains_vault_search() -> None:
    validate_search_filters("docs", SearchFilterOptions(doc_type="adr"))
    with pytest.raises(InvalidFilterForSearchTypeError):
        validate_search_filters(
            "docs", SearchFilterOptions(source_path="manuals/guide.bin")
        )
