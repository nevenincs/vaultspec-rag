"""Reindex-parity tests: the typed payload builders are shape-preserving.

Asserts the points the schema-driven builders produce equal, key-for-key and
value-for-value, the payloads the prior inline dicts produced for the same
input. A field added, removed, renamed, or reordered against the frozen golden
shape fails here - the guard that the typed refactor never silently changed the
on-disk shape. Pure (no Qdrant, no GPU, no network), so it runs in the unit
gate.
"""

from __future__ import annotations

import pytest

from ..store import (
    CodeChunk,
    VaultChunk,
    VaultDocument,
    _code_chunk_payload,
    _vault_chunk_payload,
    _vault_doc_payload,
)

pytestmark = [pytest.mark.unit]


def test_vault_doc_payload_matches_golden_shape() -> None:
    doc = VaultDocument(
        id="adr/overview",
        path="adr/overview.md",
        doc_type="adr",
        feature="demo",
        date="2026-06-27",
        tags=["#adr", "#demo"],
        related=["[[x]]"],
        title="Overview",
        content="body",
        status="accepted",
    )
    assert _vault_doc_payload(doc) == {
        "doc_id": "adr/overview",
        "path": "adr/overview.md",
        "doc_type": "adr",
        "feature": "demo",
        "date": "2026-06-27",
        "tags": ["#adr", "#demo"],
        "related": ["[[x]]"],
        "title": "Overview",
        "status": "accepted",
        "content": "body",
    }


def _vault_chunk(ordinal: int, doc_content: str | None) -> VaultChunk:
    return VaultChunk(
        doc_id="adr/overview",
        ordinal=ordinal,
        chunk_count=3,
        text="chunk text",
        path="adr/overview.md",
        doc_type="adr",
        feature="demo",
        date="2026-06-27",
        tags=["#adr"],
        related=["[[x]]"],
        title="Overview",
        status="accepted",
        doc_content=doc_content,
    )


def test_vault_chunk_payload_non_zero_ordinal_omits_doc_content() -> None:
    payload = _vault_chunk_payload(_vault_chunk(2, "full body"))
    assert payload == {
        "doc_id": "adr/overview",
        "chunk_ordinal": 2,
        "chunk_count": 3,
        "path": "adr/overview.md",
        "doc_type": "adr",
        "feature": "demo",
        "date": "2026-06-27",
        "tags": ["#adr"],
        "related": ["[[x]]"],
        "title": "Overview",
        "status": "accepted",
        "content": "chunk text",
    }
    assert "doc_content" not in payload


def test_vault_chunk_payload_ordinal_zero_carries_doc_content() -> None:
    payload = _vault_chunk_payload(_vault_chunk(0, "full body"))
    assert payload.get("doc_content") == "full body"
    # The chunk-level field set plus the ordinal-0 doc_content addition.
    assert set(payload) == {
        "doc_id",
        "chunk_ordinal",
        "chunk_count",
        "path",
        "doc_type",
        "feature",
        "date",
        "tags",
        "related",
        "title",
        "status",
        "content",
        "doc_content",
    }


def test_vault_chunk_payload_ordinal_zero_without_doc_content_omits_it() -> None:
    payload = _vault_chunk_payload(_vault_chunk(0, None))
    assert "doc_content" not in payload


def test_code_chunk_payload_matches_golden_shape() -> None:
    chunk = CodeChunk(
        id="src/main.py:1-10",
        path="src/main.py",
        language="python",
        content="print('hi')",
        line_start=1,
        line_end=10,
        node_type="function_definition",
        function_name="main",
        class_name=None,
        source_path=None,
        preprocessor_id=None,
        anchor=None,
        locator_kind=None,
        locator_value_int=None,
        locator_value_str=None,
        locator_end_int=None,
        locator_end_str=None,
    )
    assert _code_chunk_payload(chunk) == {
        "chunk_id": "src/main.py:1-10",
        "path": "src/main.py",
        "language": "python",
        "content": "print('hi')",
        "line_start": 1,
        "line_end": 10,
        "node_type": "function_definition",
        "function_name": "main",
        "class_name": None,
        "source_path": None,
        "preprocessor_id": None,
        "anchor": None,
        "locator_kind": None,
        "locator_value_int": None,
        "locator_value_str": None,
        "locator_end_int": None,
        "locator_end_str": None,
    }
