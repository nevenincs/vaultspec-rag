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

    # One row per supported filter token. The ids are the token names, so a
    # failure still says which filter broke rather than only a row number.
    @pytest.mark.parametrize(
        ("query", "text", "filters"),
        [
            ("type:adr vector database", "vector database", {"doc_type": "adr"}),
            ("feature:rag search stuff", "search stuff", {"feature": "rag"}),
            ("date:2026-02 recent docs", "recent docs", {"date": "2026-02"}),
            ("tag:#research my query", "my query", {"tag": "research"}),
            ("lang:python search codebase", "search codebase", {"language": "python"}),
            ("path:src/ search code", "search code", {"path_scope": "src/"}),
            (
                "func:encode_query authentication",
                "authentication",
                {"function_name": "encode_query"},
            ),
            (
                "class:VaultStore storage logic",
                "storage logic",
                {"class_name": "VaultStore"},
            ),
            (
                "nodetype:function_definition helpers",
                "helpers",
                {"node_type": "function_definition"},
            ),
        ],
        ids=[
            "type",
            "feature",
            "date",
            "tag",
            "lang",
            "path",
            "func",
            "class",
            "nodetype",
        ],
    )
    def test_one_filter_is_extracted_and_stripped_from_the_text(
        self,
        query: str,
        text: str,
        filters: dict[str, str],
    ) -> None:
        result = parse_query(query)
        assert result.text == text
        assert result.filters == filters

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
        from ..search._postprocess import _locale_variant_key

        a = _locale_variant_key("locales/en.yml")
        b = _locale_variant_key("locales/es.yml")
        assert a is not None
        assert a == b

    def test_shape_b_lang_directory(self):
        """``i18n/en/messages.po`` + ``i18n/es/messages.po`` share a key."""
        from ..search._postprocess import _locale_variant_key

        a = _locale_variant_key("i18n/en/messages.po")
        b = _locale_variant_key("i18n/es/messages.po")
        assert a is not None
        assert a == b

    def test_shape_c_dotted_lang(self):
        """``messages.en.po`` + ``messages.es.po`` share a key."""
        from ..search._postprocess import _locale_variant_key

        a = _locale_variant_key("messages.en.po")
        b = _locale_variant_key("messages.es.po")
        assert a is not None
        assert a == b

    def test_non_locale_path_returns_none(self):
        """``src/foo.py`` is not a locale variant."""
        from ..search._postprocess import _locale_variant_key

        assert _locale_variant_key("src/foo.py") is None
        assert _locale_variant_key("README.md") is None
        assert _locale_variant_key("docs/intro.md") is None

    def test_extension_must_be_in_allow_list(self):
        """``locales/en.py`` is not a locale file (wrong ext)."""
        from ..search._postprocess import _locale_variant_key

        assert _locale_variant_key("locales/en.py") is None

    def test_lang_code_must_be_two_letters(self):
        """``locales/eng.yml`` doesn't match the 2-letter rule."""
        from ..search._postprocess import _locale_variant_key

        assert _locale_variant_key("locales/eng.yml") is None


class TestClassifyChunkType:
    """Chunk-type classifier for --prefer (#122)."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_tests_precedence_over_docs(self):
        """``tests/docs/foo.py`` is tests (precedence rule)."""
        from ..search._postprocess import _classify_chunk_type

        assert _classify_chunk_type("tests/docs/foo.py") == "tests"

    def test_test_prefix_python(self):
        from ..search._postprocess import _classify_chunk_type

        assert _classify_chunk_type("test_foo.py") == "tests"
        assert _classify_chunk_type("src/pkg/test_bar.py") == "tests"

    def test_test_suffix_python(self):
        from ..search._postprocess import _classify_chunk_type

        assert _classify_chunk_type("foo_test.py") == "tests"

    def test_specs_directory(self):
        from ..search._postprocess import _classify_chunk_type

        assert _classify_chunk_type("spec/parser_spec.rb") == "tests"

    def test_docs_directory(self):
        from ..search._postprocess import _classify_chunk_type

        assert _classify_chunk_type("docs/intro.md") == "docs"
        assert _classify_chunk_type("README.md") == "docs"
        assert _classify_chunk_type("guide.rst") == "docs"

    def test_prod_default(self):
        from ..search._postprocess import _classify_chunk_type

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
        from ..search._postprocess import _collapse_locale_variants

        winner = self._mk("locales/en.yml", 0.90)
        loser = self._mk("locales/es.yml", 0.88)
        out = _collapse_locale_variants([winner, loser])
        assert len(out) == 1
        assert out[0].path == "locales/en.yml"
        assert "locale variants" in out[0].snippet

    def test_wide_gap_variants_survive(self):
        """Same-key results outside the window stay separate."""
        from ..search._postprocess import _collapse_locale_variants

        a = self._mk("locales/en.yml", 0.90)
        b = self._mk("locales/es.yml", 0.50)
        out = _collapse_locale_variants([a, b])
        assert len(out) == 2

    def test_non_locale_passes_through(self):
        """Non-locale paths are never touched."""
        from ..search._postprocess import _collapse_locale_variants

        a = self._mk("src/foo.py", 0.95)
        b = self._mk("src/bar.py", 0.94)
        out = _collapse_locale_variants([a, b])
        assert len(out) == 2

    def test_empty_input(self):
        from ..search._postprocess import _collapse_locale_variants

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


class TestPathPatternMatching:
    """A supplied path pattern narrows to a location, not to one literal path.

    A plain pattern is the form an operator types - ``src/vaultspec_rag/indexer``
    or ``src/`` - and a directory is never itself an indexed path, so matching
    it literally returns nothing while looking like a working narrow.
    """

    pytestmark: ClassVar = [pytest.mark.unit]

    @staticmethod
    def _rows(*paths: str) -> list[dict[str, object]]:
        return [{"path": p, "id": p} for p in paths]

    @staticmethod
    def _kept(
        rows: list[dict[str, object]],
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> set[str]:
        from ..search._result_shaping import filter_raw_codebase_results

        return {
            str(r["path"])
            for r in filter_raw_codebase_results(rows, include or [], exclude or [])
        }

    # Each row is a pattern shape an operator types, paired with the subtree it
    # must select. Drop the subtree expansion from expand_path_pattern and every
    # plain-pattern row fails on an empty survivor set, while the glob rows keep
    # passing - which is why both shapes are asserted here together.
    @pytest.mark.parametrize(
        ("pattern", "expected"),
        [
            ("src/pkg", {"src/pkg/a.py", "src/pkg/sub/b.py"}),
            ("src/pkg/", {"src/pkg/a.py", "src/pkg/sub/b.py"}),
            ("src/pkg/**", {"src/pkg/a.py", "src/pkg/sub/b.py"}),
            ("src/pkg/*", {"src/pkg/a.py", "src/pkg/sub/b.py"}),
            ("src/pkg/a.py", {"src/pkg/a.py"}),
            ("src", {"src/pkg/a.py", "src/pkg/sub/b.py"}),
        ],
        ids=["bare-dir", "trailing-slash", "double-star", "star", "exact-file", "top"],
    )
    def test_an_include_pattern_selects_the_location_and_its_subtree(
        self,
        pattern: str,
        expected: set[str],
    ) -> None:
        rows = self._rows("src/pkg/a.py", "src/pkg/sub/b.py", "tests/test_a.py")
        assert self._kept(rows, include=[pattern]) == expected

    def test_an_exclude_pattern_drops_the_location_and_its_subtree(self) -> None:
        rows = self._rows("src/pkg/a.py", "tests/test_a.py", "tests/deep/test_b.py")
        assert self._kept(rows, exclude=["tests"]) == {"src/pkg/a.py"}

    def test_a_pattern_matching_no_indexed_path_keeps_nothing(self) -> None:
        rows = self._rows("src/pkg/a.py", "tests/test_a.py")
        assert self._kept(rows, include=["does/not/exist"]) == set()


class TestInlinePathScopeToken:
    """``path:`` narrows by pattern rather than by exact identity.

    Routing the token to the exact-path filter pushed a directory into a
    keyword equality match, which no indexed path can satisfy: the search
    returned nothing and reported it as a plain no-match.
    """

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_the_token_does_not_reach_the_exact_path_store_filter(self) -> None:
        from ..search._searcher import VaultSearcher

        parsed = parse_query("reopen a drifted indexed path path:src/pkg/")
        store_filters = VaultSearcher._build_codebase_store_filters(  # pyright: ignore[reportPrivateUsage]  # asserting the pushdown contract
            None,  # pyright: ignore[reportArgumentType]  # staticmethod-shaped: self is unused
            parsed,
            None,
            None,
            None,
            None,
            None,
        )
        # Reinstate the "path" mapping in _FILTER_KEY_MAP and this finds the
        # directory pushed down as an exact keyword match, which is the silent
        # empty-result defect.
        assert "path" not in store_filters

    def test_an_explicit_exact_path_still_pushes_down(self) -> None:
        from ..search._searcher import VaultSearcher

        parsed = parse_query("lock ordering")
        store_filters = VaultSearcher._build_codebase_store_filters(  # pyright: ignore[reportPrivateUsage]  # asserting the pushdown contract
            None,  # pyright: ignore[reportArgumentType]  # staticmethod-shaped: self is unused
            parsed,
            None,
            "src/pkg/a.py",
            None,
            None,
            None,
        )
        assert store_filters["path"] == "src/pkg/a.py"
