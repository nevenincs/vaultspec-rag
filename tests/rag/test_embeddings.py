"""Tests for embedding model: EmbeddingModel."""

from __future__ import annotations

import importlib.util

import pytest

HAS_GPU_RAG = all(
    importlib.util.find_spec(pkg) is not None
    for pkg in ("qdrant_client", "sentence_transformers", "torch")
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(not HAS_GPU_RAG, reason="GPU RAG dependencies not installed"),
]


# ---- Embedding Model Tests ----


class TestEmbeddingModel:
    """Tests for the real EmbeddingModel with Qwen3-Embedding-0.6B on GPU."""

    def test_model_loads(self, rag_components):
        model = rag_components["model"]
        assert model.device == "cuda"

    def test_encode_documents_shape(self, rag_components):
        model = rag_components["model"]
        texts = ["This is a test document about architecture decisions."]
        vectors = model.encode_documents(texts)
        assert vectors.shape[0] == 1
        assert vectors.shape[1] == model.dimension

    def test_encode_query_shape(self, rag_components):
        model = rag_components["model"]
        vector = model.encode_query("vector database")
        assert vector.shape == (model.dimension,)

    def test_document_query_similarity(self, rag_components):
        """Documents about a topic should be more similar to related queries."""
        import numpy as np

        model = rag_components["model"]

        doc_vec = model.encode_documents(
            ["LanceDB is an embedded vector database for semantic search"]
        )[0]
        related_query = model.encode_query("vector database for search")
        unrelated_query = model.encode_query("chocolate cake recipe")

        sim_related = float(np.dot(doc_vec, related_query))
        sim_unrelated = float(np.dot(doc_vec, unrelated_query))

        assert sim_related > sim_unrelated

    def test_encode_documents_batched(self, rag_components):
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
        assert vectors.shape[0] == 3
        assert vectors.shape[1] == model.dimension

    def test_encode_documents_sparse(self, rag_components):
        """Sparse encoding should return SparseResult objects."""
        model = rag_components["model"]
        texts = ["This is a test document about architecture decisions."]
        sparse_vecs = model.encode_documents_sparse(texts)
        assert len(sparse_vecs) == 1
        assert hasattr(sparse_vecs[0], "indices")
        assert hasattr(sparse_vecs[0], "values")

    def test_encode_query_sparse(self, rag_components):
        """Sparse query encoding should return a SparseResult."""
        model = rag_components["model"]
        sparse_vec = model.encode_query_sparse("vector database")
        assert hasattr(sparse_vec, "indices")
        assert hasattr(sparse_vec, "values")
