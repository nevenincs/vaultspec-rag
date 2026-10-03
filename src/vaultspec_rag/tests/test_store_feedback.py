"""Feedback from replaced points must not make otherwise usable search fail."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._store_models import CodeChunk, VaultChunk
from .._store_search import HybridSearchRequest
from ..embeddings import SparseResult
from ..store_runtime import VaultStore

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("source", ["vault", "code"])
@pytest.mark.parametrize("hybrid", [False, True])
def test_removed_feedback_does_not_break_search(
    tmp_path: Path, source: str, hybrid: bool
) -> None:
    vector = [1.0, 0.0, 0.0, 0.0]
    with VaultStore(tmp_path, embedding_dim=4) as store:
        if source == "vault":
            store.upsert_document_chunks(
                [
                    VaultChunk(
                        doc_id="kept",
                        ordinal=0,
                        chunk_count=1,
                        text="searchable content",
                        path=".vault/adr/kept.md",
                        doc_type="adr",
                        feature="search",
                        date="2026-01-01",
                        tags=[],
                        related=[],
                        title="Kept",
                        doc_content="searchable content",
                        vector=vector,
                    )
                ],
                write_policy=None,
            )
            search = store.hybrid_search
        else:
            store.upsert_code_chunks(
                [
                    CodeChunk(
                        id="kept",
                        path="src/kept.py",
                        language="python",
                        content="kept = True",
                        line_start=1,
                        line_end=1,
                        vector=vector,
                    )
                ],
                write_policy=None,
            )
            search = store.hybrid_search_codebase
        baseline = search(HybridSearchRequest(query_vector=vector, query_text="kept"))
        rows = search(
            HybridSearchRequest(
                query_vector=vector,
                query_text="kept",
                like_ids=["removed-positive", 123456789],
                unlike_ids=["removed-negative"],
                sparse_vector=SparseResult(indices=[1], values=[1.0])
                if hybrid
                else None,
            )
        )

        # Removing live-anchor resolution raises a missing-point backend error
        # before this equality, for both recommendation execution paths.
        assert (
            [row["id"] for row in rows] == [row["id"] for row in baseline] == ["kept"]
        )


def test_surviving_feedback_is_preserved(tmp_path: Path) -> None:
    from qdrant_client import models

    vector = [1.0, 0.0, 0.0, 0.0]
    with VaultStore(tmp_path, embedding_dim=4) as store:
        store.upsert_code_chunks(
            [
                CodeChunk(
                    id="kept",
                    path="src/kept.py",
                    language="python",
                    content="kept = True",
                    line_start=1,
                    line_end=1,
                    vector=vector,
                )
            ],
            write_policy=None,
        )
        kept = store._stable_id("kept")
        query = models.RecommendQuery(
            recommend=models.RecommendInput(
                positive=[vector, kept, store._stable_id("removed")],
                negative=[kept],
            )
        )
        with store._point_lock(store.CODE_TABLE_NAME):
            resolved = store._live_feedback_query(store.CODE_TABLE_NAME, query)
        assert isinstance(resolved, models.RecommendQuery)
        assert resolved.recommend.positive == [vector, kept]
        assert resolved.recommend.negative == [kept]
