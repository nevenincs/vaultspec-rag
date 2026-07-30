"""Document query-filter coverage against real Qdrant model objects."""

from __future__ import annotations

from typing import cast

import pytest

from .._store_search import _VaultSearchMixin

pytestmark = pytest.mark.unit


def test_document_filter_targets_only_declared_indexed_fields() -> None:
    query_filter = _VaultSearchMixin._build_document_filter(
        {
            "source_path": "manuals/guide.bin",
            "extractor_id": "extractor",
            "locator_kind": "page",
        }
    )
    assert query_filter is not None
    assert query_filter.must is not None
    raw_must = query_filter.model_dump(exclude_none=True)["must"]
    assert isinstance(raw_must, list)
    encoded = cast("list[dict[str, object]]", raw_must)
    assert [condition["key"] for condition in encoded] == [
        "source_path",
        "extractor_id",
        "locator_kind",
    ]
    assert [
        cast("dict[str, object]", condition["match"])["value"] for condition in encoded
    ] == [
        "manuals/guide.bin",
        "extractor",
        "page",
    ]


def test_unknown_document_filter_does_not_become_store_predicate() -> None:
    assert _VaultSearchMixin._build_document_filter({"unknown": "value"}) is None
