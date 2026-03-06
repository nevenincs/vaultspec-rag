"""Integration tests for VaultStore: CRUD and hybrid search.

Tests updated for Qdrant-backed store (replacing LanceDB).
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]


# ---- Store Tests ----


class TestVaultStore:
    """Tests for the Qdrant store with actual data."""

    def test_store_has_documents(self, rag_components):
        store = rag_components["store"]
        count = store.count()
        assert count > 0, "Store should have documents after indexing"

    def test_get_all_ids(self, rag_components):
        store = rag_components["store"]
        ids = store.get_all_ids()
        assert len(ids) > 0
        # All ids should be strings
        for doc_id in ids:
            assert isinstance(doc_id, str)
            assert len(doc_id) > 0

    def test_vault_store_context_manager(self, tmp_path):
        """VaultStore should support the context manager protocol."""
        from vaultspec_rag import VaultStore

        with VaultStore(tmp_path) as store:
            assert store._client is not None
            store.ensure_table()
        # After exiting context, client should be released
        assert store._client is None

    def test_hybrid_search_returns_results(self, rag_components):
        model = rag_components["model"]
        store = rag_components["store"]

        query_vec = model.encode_query("architecture decision")
        results = store.hybrid_search(
            query_vector=query_vec,
            query_text="architecture decision",
            limit=5,
        )
        assert len(results) > 0
        # Each result should have an id and path
        for r in results:
            assert "id" in r
            assert "path" in r

    def test_search_empty_store(self, tmp_path):
        """Searching a fresh VaultStore with no indexed docs should return
        empty results without crashing.
        """
        from vaultspec_rag import EmbeddingModel, VaultStore

        store = VaultStore(tmp_path)
        try:
            store.ensure_table()

            model = EmbeddingModel()
            query_vec = model.encode_query("anything")

            results = store.hybrid_search(
                query_vector=query_vec,
                query_text="anything",
                limit=5,
            )
            assert results == []
        finally:
            store.close()
