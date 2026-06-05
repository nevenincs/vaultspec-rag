"""End-to-end VaultSearcher search operations (integration tests).

Unit tests for query parsing have been moved to:
src/vaultspec/rag/tests/test_query.py
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]


# ---- End-to-End Search Tests ----


class TestVaultSearch:
    """End-to-end search tests against real indexed vault data."""

    def test_search_returns_results(self, rag_components):
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        # search_vault searches only the vault collection.
        results = searcher.search_vault("architecture decision", top_k=5)

        assert len(results) > 0
        for r in results:
            assert r.id
            assert r.path
            assert r.score > 0

    def test_search_results_are_sorted_by_score(self, rag_components):
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("implementation plan", top_k=5)

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_with_type_filter(self, rag_components):
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("type:adr architecture", top_k=10)

        # All results should be ADRs
        for r in results:
            assert r.doc_type == "adr", f"Expected adr, got {r.doc_type} for {r.id}"

    def test_search_respects_limit(self, rag_components):
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("project", top_k=3)

        assert len(results) <= 3

    def test_search_result_has_snippet(self, rag_components):
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("architecture", top_k=1)

        if results:
            assert isinstance(results[0].snippet, str)

    def test_vault_search_paths_are_markdown(self, rag_components):
        """All vault search result paths should point to .md files."""
        from vaultspec_rag import VaultSearcher

        searcher = VaultSearcher(
            rag_components["root"],
            rag_components["model"],
            rag_components["store"],
        )
        results = searcher.search_vault("architecture decision", top_k=5)

        assert len(results) > 0
        for r in results:
            assert r.path.endswith(".md"), f"Expected .md path, got {r.path}"

    def test_vault_search_snippets_nonempty(self, rag_components):
        """Vault search snippets must contain actual document text."""
        from vaultspec_rag import VaultSearcher

        searcher = VaultSearcher(
            rag_components["root"],
            rag_components["model"],
            rag_components["store"],
        )
        results = searcher.search_vault("connector protocol", top_k=5)

        assert len(results) > 0
        for r in results:
            assert len(r.snippet.strip()) > 0, f"Result {r.id} has empty snippet"

    def test_vault_search_scores_bounded(self, rag_components):
        """All vault search result scores should be positive floats."""
        from vaultspec_rag import VaultSearcher

        searcher = VaultSearcher(
            rag_components["root"],
            rag_components["model"],
            rag_components["store"],
        )
        results = searcher.search_vault("pipeline executor", top_k=5)

        assert len(results) > 0
        for r in results:
            assert isinstance(r.score, float)
            assert r.score > 0, f"Result {r.id} has non-positive score {r.score}"


# ---- Search edge cases ----


class TestSearchEdgeCases:
    """Edge cases for search operations."""

    def test_empty_query(self, rag_components):
        """VaultSearcher.search_vault('') should not crash."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("", top_k=5)
        # Should return some results (empty query still embeds something)
        # or empty list -- but must not crash
        assert isinstance(results, list)

    def test_filter_only_query_returns_results(self, rag_components):
        """'type:adr' with no text should return ADR docs, not crash."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("type:adr", top_k=10)
        assert isinstance(results, list)
        # Should find some ADR docs
        if results:
            for r in results:
                assert r.doc_type == "adr"

    def test_invalid_filter_value(self, rag_components):
        """'type:nonexistent' should return empty results, not crash."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("type:nonexistent some query", top_k=5)
        assert isinstance(results, list)
        assert len(results) == 0

    def test_special_characters_in_query(self, rag_components):
        """Query with quotes, brackets, and special chars should not crash."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)

        special_queries = [
            'query with "quotes"',
            "query with [[wiki-links]]",
            "query with (parentheses) and [brackets]",
            "query with <angle> & ampersand",
        ]
        for q in special_queries:
            results = searcher.search_vault(q, top_k=3)
            assert isinstance(results, list), f"Query '{q}' should not crash"

    def test_very_long_query(self, rag_components):
        """A 500+ character query should work within limits."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        long_query = "architecture decision " * 30  # ~660 chars
        results = searcher.search_vault(long_query, top_k=5)
        assert isinstance(results, list)

    def test_sql_injection_in_filter_value(self, rag_components):
        """Filter values with SQL injection characters should not crash.
        Qdrant uses typed filters, so injection is not possible, but
        adversarial inputs should still produce empty results gracefully.
        """
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        # These contain SQL special chars that could break the WHERE clause
        adversarial_queries = [
            "type:adr' OR 1=1 --",
            "type:adr'; DROP TABLE vault_docs; --",
            "feature:test' UNION SELECT * FROM vault_docs --",
        ]
        for q in adversarial_queries:
            results = searcher.search_vault(q, top_k=3)
            assert isinstance(results, list)

        # Verify the store is still functional after adversarial queries
        results = searcher.search_vault("architecture", top_k=3)
        assert len(results) > 0, "Store should still work after adversarial queries"


class TestRerank:
    """Live integration tests for VaultSearcher._rerank on GPU."""

    def test_rerank_disabled_returns_top_k(self, rag_components):
        """When reranker is disabled, _rerank just slices to top_k."""
        from vaultspec_rag.search import VaultSearcher

        searcher = VaultSearcher(
            rag_components["root"],
            rag_components["model"],
            rag_components["store"],
        )
        searcher._reranker_enabled = False

        # Get real results from a vault search
        results = searcher.store.hybrid_search(
            query_vector=rag_components["model"].encode_query("architecture").tolist(),
            query_text="architecture",
            sparse_vector=rag_components["model"].encode_query_sparse("architecture"),
            limit=10,
        )
        from vaultspec_rag import SearchResult

        search_results = [
            SearchResult(
                id=r["id"],
                path=r["path"],
                title=r.get("title", ""),
                score=float(r.get("_relevance_score", 0.0)),
                snippet=r.get("content", "")[:200],
                source="vault",
            )
            for r in results
        ]
        assert len(search_results) >= 3

        out = searcher._rerank("architecture", search_results, 3)
        assert len(out) == 3
        # Scores should be unchanged (no reranking applied)
        assert out[0].score == search_results[0].score

    def test_rerank_enabled_resorts_by_crossencoder(self, rag_components):
        """When reranker is enabled, CrossEncoder rescores and reorders."""
        from vaultspec_rag.search import VaultSearcher

        searcher = VaultSearcher(
            rag_components["root"],
            rag_components["model"],
            rag_components["store"],
        )
        searcher._reranker_enabled = True

        results = searcher.store.hybrid_search(
            query_vector=rag_components["model"]
            .encode_query("dispatch architecture")
            .tolist(),
            query_text="dispatch architecture",
            sparse_vector=rag_components["model"].encode_query_sparse(
                "dispatch architecture",
            ),
            limit=10,
        )
        from vaultspec_rag import SearchResult

        search_results = [
            SearchResult(
                id=r["id"],
                path=r["path"],
                title=r.get("title", ""),
                score=float(r.get("_relevance_score", 0.0)),
                snippet=r.get("content", "")[:200],
                source="vault",
            )
            for r in results
        ]
        assert len(search_results) >= 3

        out = searcher._rerank("dispatch architecture", search_results, 3)
        assert len(out) == 3
        # CrossEncoder assigns new float scores
        assert all(isinstance(r.score, float) for r in out)
        # Results should be sorted descending by score
        assert out[0].score >= out[1].score >= out[2].score

    def test_rerank_single_result_skipped(self, rag_components):
        """Reranking is skipped when there is only 1 result."""
        from vaultspec_rag import SearchResult
        from vaultspec_rag.search import VaultSearcher

        searcher = VaultSearcher(
            rag_components["root"],
            rag_components["model"],
            rag_components["store"],
        )
        searcher._reranker_enabled = True

        single = [
            SearchResult(
                id="doc-0",
                path="adr/doc-0.md",
                title="Doc 0",
                score=0.5,
                snippet="Some content about architecture.",
                source="vault",
            ),
        ]
        original_score = single[0].score
        out = searcher._rerank("architecture", single, 5)
        assert len(out) == 1
        # Score unchanged - reranker was not invoked
        assert out[0].score == original_score
