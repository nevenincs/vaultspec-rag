"""Store-level tests for preprocess-hook chunk payload (real local Qdrant, no GPU).

Exercises D12: a preprocessed ``CodeChunk`` carries its source path, preprocessor
id, anchor, and split locator (int vs str) into the codebase collection payload,
and is reconcilable by source path. Uses a real local Qdrant with a tiny
embedding dimension and dummy vectors - no model, no mocks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from ..store import CodeChunk, VaultStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_DIM = 4


@pytest.fixture
def store(tmp_path: Path) -> Generator[VaultStore]:
    s = VaultStore(tmp_path, embedding_dim=_DIM)
    s.ensure_code_table()
    yield s
    s.close()


def _preproc_chunk(
    chunk_id: str,
    *,
    anchor: str,
    locator_kind: str,
    value_int: int | None = None,
    value_str: str | None = None,
) -> CodeChunk:
    return CodeChunk(
        id=chunk_id,
        path="docs/report.pdf",
        language="text",
        content="extracted body text",
        line_start=0,
        line_end=0,
        source_path="docs/report.pdf",
        preprocessor_id="pdf-fake",
        anchor=anchor,
        locator_kind=locator_kind,
        locator_value_int=value_int,
        locator_value_str=value_str,
        vector=[0.1, 0.2, 0.3, 0.4],
    )


def _scroll_payloads(store: VaultStore) -> list[dict[str, Any]]:
    client = store._client
    assert client is not None
    points, _ = client.scroll(  # pyright: ignore[reportUnknownMemberType]
        collection_name=store.CODE_TABLE_NAME,
        with_payload=True,
        limit=100,
    )
    return [cast("dict[str, Any]", p.payload) for p in points]


def test_preproc_payload_persists_int_locator(store: VaultStore) -> None:
    store.upsert_code_chunks(
        [
            _preproc_chunk(
                "docs/report.pdf::pp:0:abc",
                anchor="docs/report.pdf#page=1",
                locator_kind="page",
                value_int=1,
            )
        ]
    )
    payloads = _scroll_payloads(store)
    assert len(payloads) == 1
    p = payloads[0]
    assert p["source_path"] == "docs/report.pdf"
    assert p["preprocessor_id"] == "pdf-fake"
    assert p["anchor"] == "docs/report.pdf#page=1"
    assert p["locator_kind"] == "page"
    assert p["locator_value_int"] == 1
    assert p["locator_value_str"] is None


def test_preproc_payload_persists_str_locator(store: VaultStore) -> None:
    store.upsert_code_chunks(
        [
            _preproc_chunk(
                "book.xlsx::pp:0:def",
                anchor="book.xlsx#Summary!1",
                locator_kind="sheet",
                value_str="Summary",
            )
        ]
    )
    p = _scroll_payloads(store)[0]
    assert p["locator_kind"] == "sheet"
    assert p["locator_value_str"] == "Summary"
    assert p["locator_value_int"] is None


def test_purge_by_source_path(store: VaultStore) -> None:
    store.upsert_code_chunks(
        [
            _preproc_chunk(
                "docs/report.pdf::pp:0:a",
                anchor="docs/report.pdf#page=1",
                locator_kind="page",
                value_int=1,
            ),
            _preproc_chunk(
                "docs/report.pdf::pp:1:b",
                anchor="docs/report.pdf#page=2",
                locator_kind="page",
                value_int=2,
            ),
        ]
    )
    assert store.count_code() == 2
    # Reconciliation drops every chunk belonging to the source by its path.
    ids = store.get_code_ids_by_paths({"docs/report.pdf"})
    assert set(ids) == {"docs/report.pdf::pp:0:a", "docs/report.pdf::pp:1:b"}


def test_range_locator_end_persists(store: VaultStore) -> None:
    chunk = _preproc_chunk(
        "doc.txt::pp:0:r",
        anchor="doc.txt#L10-20",
        locator_kind="line",
        value_int=10,
    )
    chunk.locator_end_int = 20
    store.upsert_code_chunks([chunk])
    p = _scroll_payloads(store)[0]
    assert p["locator_value_int"] == 10
    assert p["locator_end_int"] == 20


def test_ordinary_code_chunk_has_null_preproc_fields(store: VaultStore) -> None:
    store.upsert_code_chunks(
        [
            CodeChunk(
                id="src/main.py:1-3:h",
                path="src/main.py",
                language="python",
                content="def f(): ...",
                line_start=1,
                line_end=3,
                vector=[0.1, 0.2, 0.3, 0.4],
            )
        ]
    )
    p = _scroll_payloads(store)[0]
    assert p["source_path"] is None
    assert p["preprocessor_id"] is None
    assert p["anchor"] is None
