"""Tests for embedding model: EmbeddingModel."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from ..conftest import RagComponentsWithManifest

pytestmark = [pytest.mark.integration]


# ---- Embedding Model Tests ----


class TestEmbeddingModel:
    """Tests for the real EmbeddingModel with Qwen3-Embedding-0.6B on GPU."""

    def test_model_loads(self, rag_components: RagComponentsWithManifest) -> None:
        model = rag_components["model"]
        assert model.device == "cuda"

    def test_encode_documents_shape(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        model = rag_components["model"]
        texts = ["This is a test document about architecture decisions."]
        vectors = model.encode_documents(texts)
        assert vectors.shape[0] == 1  # pyright: ignore[reportUnknownMemberType]  # numpy ndarray stub incomplete
        assert vectors.shape[1] == model.dimension  # pyright: ignore[reportUnknownMemberType]

    def test_encode_query_shape(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        model = rag_components["model"]
        vector = model.encode_query("vector database")
        assert vector.shape == (model.dimension,)  # pyright: ignore[reportUnknownMemberType]

    def test_document_query_similarity(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        """Documents about a topic should be more similar to related queries."""
        import numpy as np

        model = rag_components["model"]

        doc_vec = model.encode_documents(
            ["LanceDB is an embedded vector database for semantic search"],
        )[0]
        related_query = model.encode_query("vector database for search")
        unrelated_query = model.encode_query("chocolate cake recipe")

        sim_related = float(np.dot(doc_vec, related_query))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]  # numpy stub incomplete
        sim_unrelated = float(np.dot(doc_vec, unrelated_query))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]  # numpy stub incomplete

        assert sim_related > sim_unrelated

    def test_encode_documents_batched(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        """Batched encoding with batch_size=2 on 3 docs should produce
        the same shape as unbatched encoding.
        """
        model = rag_components["model"]
        texts = [
            "First document about architecture.",
            "Second document about testing.",
            "Third document about performance.",
        ]
        vectors = model.encode_documents(texts, batch_size=2)
        assert vectors.shape[0] == 3  # pyright: ignore[reportUnknownMemberType]
        assert vectors.shape[1] == model.dimension  # pyright: ignore[reportUnknownMemberType]

    def test_encode_documents_sparse(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        """Sparse encoding should return SparseResult objects."""
        model = rag_components["model"]
        texts = ["This is a test document about architecture decisions."]
        sparse_vecs = model.encode_documents_sparse(texts)
        assert len(sparse_vecs) == 1
        assert hasattr(sparse_vecs[0], "indices")
        assert hasattr(sparse_vecs[0], "values")

    def test_encode_query_sparse(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        """Sparse query encoding should return a SparseResult."""
        model = rag_components["model"]
        sparse_vec = model.encode_query_sparse("vector database")
        assert hasattr(sparse_vec, "indices")
        assert hasattr(sparse_vec, "values")
