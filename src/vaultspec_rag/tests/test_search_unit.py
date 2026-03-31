"""Unit tests for rag.search — query parsing and metadata extraction."""

from typing import ClassVar

import pytest

from vaultspec_rag import ParsedQuery, SearchResult, parse_query

# No module-level pytestmark — each class sets its own marker


class TestParsedQuery:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_creation(self):
        pq = ParsedQuery(text="hello", filters={"doc_type": "adr"})
        assert pq.text == "hello"
        assert pq.filters == {"doc_type": "adr"}


class TestSearchResult:
    pytestmark: ClassVar = [pytest.mark.unit]

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


class TestSearchResultCodeMetadata:
    """SearchResult carries code metadata fields."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_code_metadata_defaults_none(self):
        sr = SearchResult(
            id="chunk-1",
            path="src/main.py",
            title="main.py",
            score=0.8,
            snippet="def foo(): ...",
            source="codebase",
        )
        assert sr.node_type is None
        assert sr.function_name is None
        assert sr.class_name is None

    def test_code_metadata_set(self):
        sr = SearchResult(
            id="chunk-2",
            path="src/bar.py",
            title="bar.py",
            score=0.9,
            snippet="class Bar: ...",
            source="codebase",
            node_type="class_definition",
            function_name=None,
            class_name="Bar",
        )
        assert sr.node_type == "class_definition"
        assert sr.function_name is None
        assert sr.class_name == "Bar"


class TestParseQuery:
    pytestmark: ClassVar = [pytest.mark.unit]

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

    def test_func_filter(self):
        result = parse_query("func:encode_query authentication")
        assert result.text == "authentication"
        assert result.filters == {"function_name": "encode_query"}

    def test_class_filter(self):
        result = parse_query("class:VaultStore storage logic")
        assert result.text == "storage logic"
        assert result.filters == {"class_name": "VaultStore"}

    def test_nodetype_filter(self):
        result = parse_query("nodetype:function_definition helpers")
        assert result.text == "helpers"
        assert result.filters == {"node_type": "function_definition"}

    def test_combined_code_filters(self):
        result = parse_query("lang:python func:search class:Searcher query")
        assert result.text == "query"
        assert result.filters["language"] == "python"
        assert result.filters["function_name"] == "search"
        assert result.filters["class_name"] == "Searcher"

    def test_unknown_prefix_not_extracted(self):
        result = parse_query("unknown:value hello")
        assert result.text == "unknown:value hello"
        assert result.filters == {}


class TestParseVaultMetadataUnit:
    """Pure unit tests for parse_vault_metadata with hardcoded strings."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_unicode_content_in_parser(self):
        """French accented chars should not crash parse_vault_metadata."""
        from vaultspec_core.vaultcore import parse_vault_metadata

        french_content = (
            "# Chapitre 1 : La M\u00e9lancolie de Croustillant\n\n"
            "Au c\u0153ur d'une boulangerie parisienne, o\u00f9 les "
            "effluves de beurre et de sucre flottaient."
        )
        metadata, body = parse_vault_metadata(french_content)
        assert metadata.tags == []
        assert metadata.date is None
        assert "M\u00e9lancolie" in body

    def test_feature_key_frontmatter_parsed(self):
        """Documents using 'feature:' key should not crash the parser."""
        from vaultspec_core.vaultcore import parse_vault_metadata

        content = (
            "---\n"
            "feature: dispatch\n"
            "date: 2026-02-07\n"
            "related:\n"
            '  - "[[some-doc]]"\n'
            "---\n"
            "# Test Document\n"
        )
        metadata, body = parse_vault_metadata(content)
        assert metadata.date == "2026-02-07"
        assert len(metadata.related) >= 1
        assert "# Test Document" in body

    def test_content_with_embedded_yaml_separators(self):
        """Internal --- should not be confused with frontmatter."""
        from vaultspec_core.vaultcore import parse_vault_metadata

        content = (
            "# Some Research Doc\n\n"
            "Some content here.\n\n"
            "---\n\n"
            "## Section after separator\n\n"
            "More content."
        )
        metadata, body = parse_vault_metadata(content)
        assert metadata.tags == []
        assert metadata.date is None
        assert "---" in body

    def test_content_with_code_block_yaml_separators(self):
        """--- inside code blocks should not confuse the parser."""
        from vaultspec_core.vaultcore import parse_vault_metadata

        content = (
            "---\n"
            'tags: ["#research", "#dispatch"]\n'
            "date: 2026-02-07\n"
            "---\n"
            "# Title\n\n"
            "```yaml\n"
            "---\n"
            "fake: frontmatter\n"
            "---\n"
            "```\n"
        )
        metadata, body = parse_vault_metadata(content)
        assert metadata.tags == ["#research", "#dispatch"]
        assert metadata.date == "2026-02-07"
        assert "fake: frontmatter" in body
