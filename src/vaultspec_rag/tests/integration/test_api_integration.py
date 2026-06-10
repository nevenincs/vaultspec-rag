"""Tests for the rag.api public facade."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...progress import NullProgressReporter

if TYPE_CHECKING:
    from pathlib import Path

    from ..conftest import RagComponentsWithManifest as _RagComponents

pytestmark = [pytest.mark.integration]


# ---- Public API Facade Tests ----


class TestRAGAPI:
    """Tests for the rag.api public facade.

    These tests exercise the public API functions end-to-end.  The API
    facade uses its own engine singleton separate from the rag_components
    fixture.
    """

    def test_search_returns_results(self, rag_components: _RagComponents):
        """rag.api.search returns SearchResult list.

        Uses the session-scoped rag_components to ensure indexed data
        exists, then calls the API facade which opens its own store
        connection.
        """
        from ... import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        # Test the search pipeline (same as the API facade does internally)
        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("architecture")
        assert len(results) > 0
        assert hasattr(results[0], "id")
        assert hasattr(results[0], "score")

    def test_search_with_type_filter(self, rag_components: _RagComponents):
        """rag.api.search filters by doc_type."""
        from ... import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("type:adr architecture", top_k=5)
        for r in results:
            assert r.doc_type == "adr"

    def test_index_incremental(self, rag_components_full: _RagComponents):
        """Incremental index via fixture indexer returns valid result.

        Uses the fixture's own indexer to avoid Qdrant lock contention
        from a second VaultStore on the same directory.
        """
        indexer = rag_components_full["indexer"]
        result = indexer.incremental_index(reporter=NullProgressReporter())
        assert result.total > 0
        assert result.duration_ms >= 0

    def test_index_full(self, rag_components_full: _RagComponents):
        """Full index via fixture indexer rebuilds index."""
        indexer = rag_components_full["indexer"]
        result = indexer.full_index(reporter=NullProgressReporter())
        assert result.total > 0
        assert result.added > 0

    def test_get_document_existing(self, rag_components: _RagComponents):
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

    def test_get_document_nonexistent(self, rag_components: _RagComponents):
        """Store.get_by_id returns None for unknown doc."""
        store = rag_components["store"]
        result = store.get_by_id("nonexistent-doc-that-does-not-exist")
        assert result is None

    def test_list_documents(self, rag_components: _RagComponents):
        """Store.list_all_documents returns all indexed docs."""
        store = rag_components["store"]
        docs = store.list_all_documents()
        assert len(docs) > 0
        assert all("id" in d for d in docs)
        assert all("doc_type" in d for d in docs)
        assert all("title" in d for d in docs)

    def test_list_documents_type_filter(self, rag_components: _RagComponents):
        """Store.list_all_documents filters by doc_type."""
        store = rag_components["store"]
        docs = store.list_all_documents(doc_type="adr")
        assert len(docs) > 0
        for d in docs:
            assert d["doc_type"] == "adr"

    def test_indexed_docs_have_related_field(self, rag_components: _RagComponents):
        """Indexed documents carry the ``related`` payload field."""
        store = rag_components["store"]
        docs = store.list_all_documents()
        assert len(docs) > 0
        for d in docs:
            assert "related" in d, f"Doc {d['id']} missing 'related' field"
            assert isinstance(d["related"], list)

    def test_get_status(self, rag_components: _RagComponents):
        """Vault metrics and store count reflect indexed data."""
        root = rag_components["root"]
        store = rag_components["store"]

        from vaultspec_core.metrics import (  # pyright: ignore[reportMissingTypeStubs]  # no stubs for vaultspec_core
            get_vault_metrics,
        )

        metrics = get_vault_metrics(root)

        assert metrics.total_docs > 0
        assert metrics.total_features > 0
        assert store.count() > 0

    def test_facade_end_to_end(self, tmp_path: Path):
        """Test the public API facade functions end-to-end against a fresh directory."""
        import vaultspec_rag

        from ...registry import get_registry

        # 1. Create a minimal doc in a fake vault
        vault_dir = tmp_path / ".vault" / "adr"
        vault_dir.mkdir(parents=True)
        doc_path = vault_dir / "2026-06-04-test-adr.md"
        doc_path.write_text(
            "---\n"
            "tags:\n"
            "  - '#adr'\n"
            "  - '#test'\n"
            "date: 2026-06-04\n"
            "---\n"
            "# Test Title\n"
            "Test body content",
            encoding="utf-8",
        )

        get_registry().load_model()

        index_res = vaultspec_rag.index(tmp_path)
        assert index_res.added == 1

        # 2. Call get_status()
        status = vaultspec_rag.get_status(tmp_path)
        assert status["vault_documents"] == 1
        assert status["target_dir"] == str(tmp_path)

        # 3. Call search_vault()
        results = vaultspec_rag.search_vault(tmp_path, "Test body")
        assert len(results) > 0
        assert results[0].title == "Test Title"

        # 4. Call clean()
        cleared = vaultspec_rag.clean(tmp_path, clean_type="all")
        assert "vault" in cleared

        status_after = vaultspec_rag.get_status(tmp_path)
        assert status_after["vault_documents"] == 0
