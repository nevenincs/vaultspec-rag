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

    def test_vault_store_locked_raises_typed_exception(self, tmp_path):
        """Opening the same Qdrant storage twice must raise VaultStoreLockedError."""
        from vaultspec_rag.store import VaultStore, VaultStoreLockedError

        first = VaultStore(tmp_path)
        try:
            with pytest.raises(VaultStoreLockedError) as excinfo:
                VaultStore(tmp_path)
            assert str(first.db_path) == excinfo.value.db_path
            assert "already in use" in str(excinfo.value)
        finally:
            first.close()

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

    def test_delete_documents_removes_from_store(self, rag_components):
        """R26-M3: delete_documents removes a doc so it's no longer searchable."""
        store = rag_components["store"]
        model = rag_components["model"]

        # Pick an existing doc ID
        all_ids = store.get_all_ids()
        assert len(all_ids) > 0
        target_id = next(iter(all_ids))

        # Verify it's searchable before deletion
        doc = store.get_by_id(target_id)
        assert doc is not None

        count_before = store.count()
        store.delete_documents([target_id])

        # Verify it's gone
        assert store.get_by_id(target_id) is None
        assert store.count() == count_before - 1

        # Re-insert it so other tests aren't affected (session-scoped fixture)
        from vaultspec_rag import VaultDocument

        reinsert = VaultDocument(
            id=doc["id"],
            path=doc["path"],
            title=doc.get("title", ""),
            content=doc.get("content", ""),
            doc_type=doc.get("doc_type", ""),
            feature=doc.get("feature", ""),
            date=doc.get("date", ""),
            tags=doc.get("tags", ""),
            related=doc.get("related", []),
            vector=model.encode_query(doc.get("content", "")[:200]).tolist(),
            sparse_indices=list(
                model.encode_query_sparse(doc.get("content", "")[:200]).indices,
            ),
            sparse_values=list(
                model.encode_query_sparse(doc.get("content", "")[:200]).values,
            ),
        )
        store.upsert_documents([reinsert])

    def test_hybrid_search_with_sparse_vector(self, rag_components):
        """R26-M5: hybrid_search with dense+sparse exercises RRF fusion."""
        model = rag_components["model"]
        store = rag_components["store"]

        query_text = "architecture decision"
        query_vec = model.encode_query(query_text)
        sparse_vec = model.encode_query_sparse(query_text)

        results = store.hybrid_search(
            query_vector=query_vec.tolist(),
            query_text=query_text,
            limit=5,
            sparse_vector=sparse_vec,
        )
        assert len(results) > 0
        for r in results:
            assert "id" in r
            assert "_relevance_score" in r

    def test_search_empty_store(self, tmp_path, rag_components):
        """Searching a fresh VaultStore with no indexed docs should return
        empty results without crashing.
        """
        from vaultspec_rag import VaultStore

        model = rag_components["model"]
        store = VaultStore(tmp_path)
        try:
            store.ensure_table()

            query_vec = model.encode_query("anything")

            results = store.hybrid_search(
                query_vector=query_vec.tolist(),
                query_text="anything",
                limit=5,
            )
            assert results == []
        finally:
            store.close()
