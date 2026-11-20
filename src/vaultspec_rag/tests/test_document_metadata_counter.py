"""Unmatchable values of declared metadata keys are counted, never rejected."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .. import store_schema
from .._store_models import DocumentChunk, DocumentMetadata, DocumentPayload
from ..indexer._document_indexer import (
    _note_unmatchable_metadata,
    _record_unmatchable_metadata,
)
from ..indexer._index_lifecycle import preprocess_completion_fields
from ..indexer._vault_prep import IndexResult

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit

_DECLARED = (
    store_schema.DeclaredMetadataKey("lang", "unit"),
    store_schema.DeclaredMetadataKey("team", "document"),
)


def _chunk(
    ordinal: int,
    fragment: int,
    unit: Mapping[str, object],
    document: Mapping[str, object],
) -> DocumentChunk:
    return DocumentChunk(
        f"doc-{ordinal}-{fragment}",
        DocumentPayload(
            "manual.bin",
            ordinal,
            "fingerprint",
            f"unit {ordinal} fragment {fragment}",
            unit_metadata=DocumentMetadata.from_mapping(dict(unit)),
            document_metadata=DocumentMetadata.from_mapping(dict(document)),
        ),
    )


def test_units_not_chunks_are_counted_per_declared_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    document = {"team": 7}
    chunks = [
        # One unit split into two chunks counts once.
        _chunk(0, 0, {"lang": 1}, document),
        _chunk(0, 1, {"lang": 1}, document),
        _chunk(1, 0, {"lang": ["en", "de"]}, document),
        _chunk(2, 0, {"other": None}, document),
    ]
    unmatchable: dict[str, set[int]] = {}
    _note_unmatchable_metadata(chunks, _DECLARED, unmatchable)
    assert unmatchable == {"lang": {0}, "team": {0, 1, 2}}

    totals: dict[str, int] = {}
    with caplog.at_level("WARNING"):
        _record_unmatchable_metadata("manual.bin", unmatchable, totals)
        _record_unmatchable_metadata("other.bin", {"lang": {4}}, totals)
    assert totals == {"lang": 2, "team": 3}
    assert "manual.bin: 1 unit(s) hold a non-string value" in caplog.text


def test_nothing_is_inspected_without_a_declaration() -> None:
    unmatchable: dict[str, set[int]] = {}
    _note_unmatchable_metadata([_chunk(0, 0, {"lang": 1}, {})], (), unmatchable)
    assert unmatchable == {}


def test_the_count_rides_the_completed_event() -> None:
    result = IndexResult(
        total=1,
        added=1,
        updated=0,
        removed=0,
        duration_ms=1,
        device="cuda",
        metadata_non_string={"lang": 2},
    )
    assert preprocess_completion_fields(result)["metadata_non_string"] == {"lang": 2}
