"""Tests for rag.search — query parsing (unit) and reranking (integration)."""

from typing import ClassVar

import pytest

from vaultspec_rag import ParsedQuery, SearchResult, parse_query

pytestmark = [pytest.mark.unit]


class TestParsedQuery:
    def test_creation(self):
        pq = ParsedQuery(text="hello", filters={"doc_type": "adr"})
        assert pq.text == "hello"
        assert pq.filters == {"doc_type": "adr"}


class TestSearchResult:
    def test_creation(self):
        sr = SearchResult(
            id="test-doc",
            path="adr/test-doc.md",
            title="Test Doc",
            score=0.95,
            snippet="Test content...",
            source="vault",
            doc_type="adr",
            feature="auth",
            date="2026-02-08",
        )
        assert sr.id == "test-doc"
        assert sr.score == 0.95
        assert sr.source == "vault"


class TestParseQuery:
    def test_plain_text(self):
        result = parse_query("vector database")
        assert result.text == "vector database"
        assert result.filters == {}

    def test_type_filter(self):
        result = parse_query("type:adr vector database")
        assert result.text == "vector database"
        assert result.filters == {"doc_type": "adr"}

    def test_feature_filter(self):
        result = parse_query("feature:rag search stuff")
        assert result.text == "search stuff"
        assert result.filters == {"feature": "rag"}

    def test_date_filter(self):
        result = parse_query("date:2026-02 recent docs")
        assert result.text == "recent docs"
        assert result.filters == {"date": "2026-02"}

    def test_tag_filter(self):
        result = parse_query("tag:#research my query")
        assert result.text == "my query"
        assert result.filters == {"tag": "research"}

    def test_lang_filter(self):
        result = parse_query("lang:python search codebase")
        assert result.text == "search codebase"
        assert result.filters == {"language": "python"}

    def test_path_filter(self):
        result = parse_query("path:src/ search code")
        assert result.text == "search code"
        assert result.filters == {"path": "src/"}

    def test_multiple_filters(self):
        result = parse_query("type:adr feature:auth lang:python authentication")
        assert result.text == "authentication"
        assert result.filters["doc_type"] == "adr"
        assert result.filters["feature"] == "auth"
        assert result.filters["language"] == "python"

    def test_only_filters_no_text(self):
        result = parse_query("type:adr feature:auth")
        assert result.text == ""
        assert len(result.filters) == 2

    def test_empty_query(self):
        result = parse_query("")
        assert result.text == ""
        assert result.filters == {}

    def test_tag_strips_hash(self):
        result = parse_query("tag:#deep-learning stuff")
        assert result.filters["tag"] == "deep-learning"

    def test_collapses_multiple_spaces(self):
        result = parse_query("type:adr  hello   world")
        assert result.text == "hello world"

    def test_unknown_prefix_not_extracted(self):
        result = parse_query("unknown:value hello")
        assert result.text == "unknown:value hello"
        assert result.filters == {}


class TestRerank:
    """Live integration tests for VaultSearcher._rerank on GPU."""

    pytestmark: ClassVar = [pytest.mark.integration]

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
                "dispatch architecture"
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
            )
        ]
        original_score = single[0].score
        out = searcher._rerank("architecture", single, 5)
        assert len(out) == 1
        # Score unchanged — reranker was not invoked
        assert out[0].score == original_score
