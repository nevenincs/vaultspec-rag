"""Tests for embedding model: EmbeddingModel."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from ...embeddings import EmbeddingModel, SparseResult
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
        assert vectors.shape[0] == 1
        assert vectors.shape[1] == model.dimension

    def test_encode_query_shape(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        model = rag_components["model"]
        vector = model.encode_query("vector database")
        assert vector.shape == (model.dimension,)

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

        sim_related = float(np.dot(doc_vec, related_query))
        sim_unrelated = float(np.dot(doc_vec, unrelated_query))

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
        assert vectors.shape[0] == 3
        assert vectors.shape[1] == model.dimension

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

    @pytest.mark.cuda
    @pytest.mark.timeout(180)
    def test_sparse_document_slices_release_cuda_outputs(
        self,
        embedding_model: EmbeddingModel,
    ) -> None:
        """Sparse output retention stays on CPU and bounded by one slice."""
        from ..._gpu import load_torch

        torch = load_torch()
        mib = 1024**2

        def _measure(
            text_count: int,
        ) -> tuple[list[SparseResult], float, float, float]:
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            baseline_allocated = float(torch.cuda.memory_allocated() / mib)
            torch.cuda.reset_peak_memory_stats()
            outputs = embedding_model.encode_documents_sparse(
                [
                    f"bounded sparse encoder slice {ordinal} alpha beta gamma"
                    for ordinal in range(text_count)
                ],
                batch_size=2,
            )
            torch.cuda.synchronize()
            retained_allocated = float(torch.cuda.memory_allocated() / mib)
            peak_allocated = float(torch.cuda.max_memory_allocated() / mib)
            peak_reserved = float(torch.cuda.max_memory_reserved() / mib)
            assert retained_allocated <= baseline_allocated + 32.0
            return outputs, retained_allocated, peak_allocated, peak_reserved

        one_slice, _one_retained, one_peak_allocated, one_peak_reserved = _measure(2)
        many_slices, _many_retained, many_peak_allocated, many_peak_reserved = _measure(
            12
        )

        assert len(one_slice) == 2
        assert len(many_slices) == 12
        for output in [*one_slice, *many_slices]:
            indices = output.indices
            values = output.values
            assert isinstance(indices, list)
            assert isinstance(values, list)
            assert not isinstance(indices, torch.Tensor)
            assert not isinstance(values, torch.Tensor)

        # Six sequential sub-batches may reuse a larger allocator block, but
        # cannot retain output in proportion to the number of slices.
        assert many_peak_allocated <= one_peak_allocated + 64.0
        assert many_peak_reserved <= one_peak_reserved + 128.0

    def test_encode_query_sparse(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        """Sparse query encoding should return a SparseResult."""
        model = rag_components["model"]
        sparse_vec = model.encode_query_sparse("vector database")
        assert hasattr(sparse_vec, "indices")
        assert hasattr(sparse_vec, "values")
