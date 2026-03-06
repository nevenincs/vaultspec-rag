"""Unit tests for rag.search — query parsing and data classes (no GPU)."""

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
    """Unit tests for VaultSearcher._rerank using mocks."""

    def _make_results(self, n: int) -> list[SearchResult]:
        return [
            SearchResult(
                id=f"doc-{i}",
                path=f"adr/doc-{i}.md",
                title=f"Doc {i}",
                score=float(n - i),
                snippet=f"Content about topic {i} with details.",
                source="vault",
            )
            for i in range(n)
        ]

    def test_rerank_disabled_returns_top_k(self):
        """When reranker is disabled, _rerank just slices to top_k."""
        from unittest.mock import MagicMock

        searcher = MagicMock()
        searcher._reranker_enabled = False
        results = self._make_results(10)
        from vaultspec_rag.search import VaultSearcher

        out = VaultSearcher._rerank(searcher, "query", results, 3)
        assert len(out) == 3
        assert out[0].id == "doc-0"

    def test_rerank_enabled_resorts_by_score(self):
        """When reranker is enabled, results are re-sorted by CE scores."""
        from unittest.mock import MagicMock

        import numpy as np

        searcher = MagicMock()
        searcher._reranker_enabled = True
        mock_reranker = MagicMock()
        # Reverse the order: last doc gets highest score
        mock_reranker.predict.return_value = np.array([0.1, 0.2, 0.3, 0.9, 0.5])
        searcher._get_reranker.return_value = mock_reranker

        results = self._make_results(5)
        from vaultspec_rag.search import VaultSearcher

        out = VaultSearcher._rerank(searcher, "query", results, 3)
        assert len(out) == 3
        # doc-3 had score 0.9, should be first
        assert out[0].id == "doc-3"
        assert out[0].score == pytest.approx(0.9)

    def test_rerank_single_result_skipped(self):
        """Reranking is skipped when there is only 1 result."""
        from unittest.mock import MagicMock

        searcher = MagicMock()
        searcher._reranker_enabled = True
        results = self._make_results(1)
        from vaultspec_rag.search import VaultSearcher

        out = VaultSearcher._rerank(searcher, "query", results, 5)
        assert len(out) == 1
        # _get_reranker should not have been called
        searcher._get_reranker.assert_not_called()
