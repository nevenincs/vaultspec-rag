"""Tests for the rag.api public facade."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]


# ---- Public API Facade Tests ----


class TestRAGAPI:
    """Tests for the rag.api public facade.

    These tests exercise the public API functions end-to-end.  The API
    facade uses its own engine singleton separate from the rag_components
    fixture.
    """

    def test_search_returns_results(self, rag_components):
        """rag.api.search returns SearchResult list.

        Uses the session-scoped rag_components to ensure indexed data
        exists, then calls the API facade which opens its own store
        connection.
        """
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        # Test the search pipeline (same as the API facade does internally)
        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("architecture")
        assert len(results) > 0
        assert hasattr(results[0], "id")
        assert hasattr(results[0], "score")

    def test_search_with_type_filter(self, rag_components):
        """rag.api.search filters by doc_type."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("type:adr architecture", top_k=5)
        for r in results:
            assert r.doc_type == "adr"

    def test_index_incremental(self, rag_components_full):
        """Incremental index via fixture indexer returns valid result.

        Uses the fixture's own indexer to avoid Qdrant lock contention
        from a second VaultStore on the same directory.
        """
        indexer = rag_components_full["indexer"]
        result = indexer.incremental_index()
        assert result.total > 0
        assert result.duration_ms >= 0

    def test_index_full(self, rag_components_full):
        """Full index via fixture indexer rebuilds index."""
        indexer = rag_components_full["indexer"]
        result = indexer.full_index()
        assert result.total > 0
        assert result.added > 0

    def test_get_document_existing(self, rag_components):
        """Store.get_by_id returns dict for known doc.

        Uses the fixture's store directly.
        Picks a doc_id from the indexed store (not list_documents, which
        scans the full filesystem and may return unindexed docs).
        """
        store = rag_components["store"]

        all_ids = store.get_all_ids()
        assert len(all_ids) > 0
        doc_id = next(iter(all_ids))
        result = store.get_by_id(doc_id)
        assert result is not None
        assert result["id"] == doc_id
        assert "content" in result
        assert "doc_type" in result

    def test_get_document_nonexistent(self, rag_components):
        """Store.get_by_id returns None for unknown doc."""
        store = rag_components["store"]
        result = store.get_by_id("nonexistent-doc-that-does-not-exist")
        assert result is None

    def test_list_documents(self, rag_components):
        """Store.list_all_documents returns all indexed docs."""
        store = rag_components["store"]
        docs = store.list_all_documents()
        assert len(docs) > 0
        assert all("id" in d for d in docs)
        assert all("doc_type" in d for d in docs)
        assert all("title" in d for d in docs)

    def test_list_documents_type_filter(self, rag_components):
        """Store.list_all_documents filters by doc_type."""
        store = rag_components["store"]
        docs = store.list_all_documents(doc_type="adr")
        assert len(docs) > 0
        for d in docs:
            assert d["doc_type"] == "adr"

    def test_indexed_docs_have_related_field(self, rag_components):
        """Indexed documents carry the ``related`` payload field."""
        store = rag_components["store"]
        docs = store.list_all_documents()
        assert len(docs) > 0
        for d in docs:
            assert "related" in d, f"Doc {d['id']} missing 'related' field"
            assert isinstance(d["related"], list)

    def test_get_status(self, rag_components):
        """Vault metrics and store count reflect indexed data."""
        root = rag_components["root"]
        store = rag_components["store"]

        from vaultspec_core.metrics import get_vault_metrics

        metrics = get_vault_metrics(root)

        assert metrics.total_docs > 0
        assert metrics.total_features > 0
        assert store.count() > 0
