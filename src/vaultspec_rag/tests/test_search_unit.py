"""Unit tests for rag.search - query parsing and metadata extraction."""

from typing import ClassVar

import pytest

from .. import ParsedQuery, SearchResult, parse_query

# No module-level pytestmark - each class sets its own marker


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
        from vaultspec_core.vaultcore import parse_vault_metadata  # noqa: I001  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs

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
        from vaultspec_core.vaultcore import parse_vault_metadata  # noqa: I001  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs

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
        from vaultspec_core.vaultcore import parse_vault_metadata  # noqa: I001  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs

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
        from vaultspec_core.vaultcore import parse_vault_metadata  # noqa: I001  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs

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


class TestLocaleVariantKey:
    """Locale stem detection for --dedup-locales (#121)."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_shape_a_lang_basename(self):
        """``locales/en.yml`` + ``locales/es.yml`` share a key."""
        from ..search import _locale_variant_key

        a = _locale_variant_key("locales/en.yml")
        b = _locale_variant_key("locales/es.yml")
        assert a is not None
        assert a == b

    def test_shape_b_lang_directory(self):
        """``i18n/en/messages.po`` + ``i18n/es/messages.po`` share a key."""
        from ..search import _locale_variant_key

        a = _locale_variant_key("i18n/en/messages.po")
        b = _locale_variant_key("i18n/es/messages.po")
        assert a is not None
        assert a == b

    def test_shape_c_dotted_lang(self):
        """``messages.en.po`` + ``messages.es.po`` share a key."""
        from ..search import _locale_variant_key

        a = _locale_variant_key("messages.en.po")
        b = _locale_variant_key("messages.es.po")
        assert a is not None
        assert a == b

    def test_non_locale_path_returns_none(self):
        """``src/foo.py`` is not a locale variant."""
        from ..search import _locale_variant_key

        assert _locale_variant_key("src/foo.py") is None
        assert _locale_variant_key("README.md") is None
        assert _locale_variant_key("docs/intro.md") is None

    def test_extension_must_be_in_allow_list(self):
        """``locales/en.py`` is not a locale file (wrong ext)."""
        from ..search import _locale_variant_key

        assert _locale_variant_key("locales/en.py") is None

    def test_lang_code_must_be_two_letters(self):
        """``locales/eng.yml`` doesn't match the 2-letter rule."""
        from ..search import _locale_variant_key

        assert _locale_variant_key("locales/eng.yml") is None


class TestClassifyChunkType:
    """Chunk-type classifier for --prefer (#122)."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_tests_precedence_over_docs(self):
        """``tests/docs/foo.py`` is tests (precedence rule)."""
        from ..search import _classify_chunk_type

        assert _classify_chunk_type("tests/docs/foo.py") == "tests"

    def test_test_prefix_python(self):
        from ..search import _classify_chunk_type

        assert _classify_chunk_type("test_foo.py") == "tests"
        assert _classify_chunk_type("src/pkg/test_bar.py") == "tests"

    def test_test_suffix_python(self):
        from ..search import _classify_chunk_type

        assert _classify_chunk_type("foo_test.py") == "tests"

    def test_specs_directory(self):
        from ..search import _classify_chunk_type

        assert _classify_chunk_type("spec/parser_spec.rb") == "tests"

    def test_docs_directory(self):
        from ..search import _classify_chunk_type

        assert _classify_chunk_type("docs/intro.md") == "docs"
        assert _classify_chunk_type("README.md") == "docs"
        assert _classify_chunk_type("guide.rst") == "docs"

    def test_prod_default(self):
        from ..search import _classify_chunk_type

        assert _classify_chunk_type("src/pkg/module.py") == "prod"
        assert _classify_chunk_type("lib/util.rs") == "prod"


class TestCollapseLocaleVariants:
    """Post-rerank locale dedup helper (#121)."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def _mk(self, path: str, score: float) -> SearchResult:
        return SearchResult(
            id=path,
            path=path,
            title=path,
            score=score,
            snippet="body",
            source="codebase",
        )

    def test_near_tie_variants_collapse(self):
        """Two same-key results within window collapse to the winner."""
        from ..search import _collapse_locale_variants

        winner = self._mk("locales/en.yml", 0.90)
        loser = self._mk("locales/es.yml", 0.88)
        out = _collapse_locale_variants([winner, loser])
        assert len(out) == 1
        assert out[0].path == "locales/en.yml"
        assert "locale variants" in out[0].snippet

    def test_wide_gap_variants_survive(self):
        """Same-key results outside the window stay separate."""
        from ..search import _collapse_locale_variants

        a = self._mk("locales/en.yml", 0.90)
        b = self._mk("locales/es.yml", 0.50)
        out = _collapse_locale_variants([a, b])
        assert len(out) == 2

    def test_non_locale_passes_through(self):
        """Non-locale paths are never touched."""
        from ..search import _collapse_locale_variants

        a = self._mk("src/foo.py", 0.95)
        b = self._mk("src/bar.py", 0.94)
        out = _collapse_locale_variants([a, b])
        assert len(out) == 2

    def test_empty_input(self):
        from ..search import _collapse_locale_variants

        assert _collapse_locale_variants([]) == []


class TestFilterValidation:
    """Unit tests for the validate_search_filters business logic."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_valid_vault_filters(self):
        from ..search import validate_search_filters

        # Should not raise
        validate_search_filters(
            "vault", doc_type="adr", feature="auth", date="2026-06-05", tag="test"
        )

    def test_valid_code_filters(self):
        from ..search import validate_search_filters

        # Should not raise
        validate_search_filters(
            "code",
            language="python",
            path="src/api.py",
            node_type="def",
            function_name="search",
            class_name="Engine",
            include_paths=["src/*"],
            exclude_paths=["tests/*"],
            dedup_locales=True,
            prefer="prod",
        )

    def test_invalid_prefer_value(self):
        from ..search import (
            InvalidPreferValueError,
            validate_search_filters,
        )

        with pytest.raises(InvalidPreferValueError) as excinfo:
            validate_search_filters("code", prefer="invalid_prefer")
        assert "invalid_prefer" in str(excinfo.value)
        assert excinfo.value.prefer_value == "invalid_prefer"

    def test_code_filters_on_vault_type(self):
        from ..search import (
            InvalidFilterForSearchTypeError,
            validate_search_filters,
        )

        with pytest.raises(InvalidFilterForSearchTypeError) as excinfo:
            validate_search_filters("vault", language="python", path="src/api.py")
        assert excinfo.value.filter_kind == "code"
        assert "--language" in excinfo.value.offending_filters
        assert "--path" in excinfo.value.offending_filters
        assert "code-search filters" in str(excinfo.value)

    def test_vault_filters_on_code_type(self):
        from ..search import (
            InvalidFilterForSearchTypeError,
            validate_search_filters,
        )

        with pytest.raises(InvalidFilterForSearchTypeError) as excinfo:
            validate_search_filters("code", doc_type="adr")
        assert excinfo.value.filter_kind == "vault"
        assert "--doc-type" in excinfo.value.offending_filters
        assert "vault-search filters" in str(excinfo.value)
