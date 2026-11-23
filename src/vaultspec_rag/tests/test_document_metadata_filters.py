"""Declared metadata filters, any-of matching, and refused filter keys.

Pure resolution and query-building logic, exercised against real Qdrant model
objects and real config files. The extractor-id facet is a callable argument,
so the bounds can be driven exactly without a collection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from .. import store_schema
from .._store_search import _VaultSearchMixin
from ..indexer._preprocess_config import (
    PreprocessConfigError,
    load_filterable_metadata,
    load_preprocess_rules,
)
from ..search._parsing import parse_query
from ..search._validation import (
    DocumentFilterRequest,
    ExtractorPrefixUnboundedError,
    InvalidFilterForSearchTypeError,
    InvalidFilterValueError,
    SearchFilterOptions,
    UnknownFilterKeyError,
    metadata_filters_from_assignments,
    resolve_document_filters,
    validate_search_filters,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from qdrant_client.http.models import Filter

pytestmark = pytest.mark.unit

_LANG = store_schema.DeclaredMetadataKey("lang", "unit")
_TEAM = store_schema.DeclaredMetadataKey("team", "document")


def _no_facet(limit: int) -> Sequence[str]:
    raise AssertionError(f"no prefix was asked for, yet the facet ran ({limit})")


def _resolve(
    request: DocumentFilterRequest,
    *ids: str,
    declared: Sequence[store_schema.DeclaredMetadataKey] = (_LANG, _TEAM),
) -> dict[str, tuple[str, ...]]:
    def extractor_ids(_limit: int) -> Sequence[str]:
        return ids

    return resolve_document_filters(request, declared, extractor_ids)


def _conditions(query_filter: Filter | None) -> list[dict[str, object]]:
    assert query_filter is not None
    dumped = query_filter.model_dump(exclude_none=True)
    return cast("list[dict[str, object]]", dumped["must"])


class TestDeclaredMetadataKeySchema:
    def test_declared_key_indexes_its_existing_nested_field(self) -> None:
        assert _LANG.field == "unit_metadata.lang"
        assert _TEAM.field == "document_metadata.team"
        indexes = store_schema.document_keyword_indexes([_TEAM, _LANG, _LANG])
        assert indexes == (
            *store_schema.DOCUMENT_KEYWORD_INDEXES,
            "document_metadata.team",
            "unit_metadata.lang",
        )

    @pytest.mark.parametrize("key", ["", "a.b", "a[0]", "x]", "k" * 129])
    def test_ambiguous_or_unbounded_key_names_are_refused(self, key: str) -> None:
        assert store_schema.metadata_key_problem(key) is not None
        with pytest.raises(ValueError):
            store_schema.DeclaredMetadataKey(key, "unit")

    @pytest.mark.parametrize("scope", ["unit", "document"])
    def test_a_declared_scope_resolves_to_itself(self, scope: str) -> None:
        assert store_schema.metadata_scope(scope) == scope

    @pytest.mark.parametrize("value", ["", "Unit", "global", None, 1, ["unit"]])
    def test_anything_else_is_not_a_scope(self, value: object) -> None:
        # Fails if the match is loosened to a truthiness or prefix test:
        # "Unit" and ["unit"] would then resolve.
        assert store_schema.metadata_scope(value) is None

    def test_only_unmatchable_values_of_declared_keys_are_reported(self) -> None:
        reported = store_schema.non_string_metadata_keys(
            [
                _LANG,
                _TEAM,
                store_schema.DeclaredMetadataKey("count", "unit"),
                store_schema.DeclaredMetadataKey("tags", "unit"),
                store_schema.DeclaredMetadataKey("absent", "unit"),
            ],
            unit_metadata={
                "lang": ["en", "de"],
                "count": 3,
                "tags": ["a", None],
                "free": 1.5,
            },
            document_metadata={"team": "docs"},
        )
        # A string list matches; an absent key and an undeclared one are not
        # defects; a number and a list holding a non-string are.
        assert reported == ("count", "tags")


class TestStoreFilterBuilders:
    def test_value_list_becomes_any_of_and_one_value_stays_exact(self) -> None:
        # Proven to fail: building MatchValue(values[0]) for a multi-value list
        # in _build_document_filter fails the first match assertion below.
        query_filter = _VaultSearchMixin._build_document_filter(
            {
                "extractor_id": ("pdf.text", "pdf.ocr"),
                "locator_kind": ("page",),
                "unit_metadata.lang": ("en", "de"),
            },
            (_LANG,),
        )
        conditions = _conditions(query_filter)
        assert [c["key"] for c in conditions] == [
            "extractor_id",
            "locator_kind",
            "unit_metadata.lang",
        ]
        assert conditions[0]["match"] == {"any": ["pdf.text", "pdf.ocr"]}
        assert conditions[1]["match"] == {"value": "page"}
        assert conditions[2]["match"] == {"any": ["en", "de"]}

    def test_empty_value_list_is_kept_as_a_match_nothing_condition(self) -> None:
        conditions = _conditions(
            _VaultSearchMixin._build_document_filter({"extractor_id": ()})
        )
        assert conditions[0]["match"] == {"any": []}

    def test_unknown_document_key_is_refused_naming_accepted_keys(self) -> None:
        # Guard. Proven to fail: replacing the refusal for an unaccepted key in
        # _build_document_filter with "continue" fails here with DID NOT RAISE.
        with pytest.raises(UnknownFilterKeyError) as caught:
            _VaultSearchMixin._build_document_filter({"unknown": ("value",)})
        assert caught.value.key == "unknown"
        assert caught.value.error_code == "unknown_filter_key"
        assert "extractor_id" in caught.value.accepted

    def test_undeclared_metadata_field_is_refused(self) -> None:
        with pytest.raises(UnknownFilterKeyError):
            _VaultSearchMixin._build_document_filter(
                {"unit_metadata.lang": ("en",)}, ()
            )

    def test_unknown_code_key_is_refused(self) -> None:
        # Guard. Proven to fail: replacing the refusal for an unaccepted key in
        # _build_code_filter with "continue" fails here with DID NOT RAISE.
        with pytest.raises(UnknownFilterKeyError) as caught:
            _VaultSearchMixin._build_code_filter({"lang": "python"})
        assert caught.value.filter_kind == "code"

    def test_unknown_vault_key_is_refused(self) -> None:
        # Guard. Proven to fail: replacing the refusal for an unaccepted key in
        # _build_filter with "continue" fails here with DID NOT RAISE.
        with pytest.raises(UnknownFilterKeyError) as caught:
            _VaultSearchMixin._build_filter({"type": "adr"})
        assert caught.value.filter_kind == "vault"


class TestResolveDocumentFilters:
    def test_comma_lists_split_only_on_list_valued_keys(self) -> None:
        resolved = resolve_document_filters(
            DocumentFilterRequest(
                source_path="a,b.pdf",
                extractor_id="x, y",
                locator_kind="page,line",
            ),
            (),
            _no_facet,
        )
        assert resolved == {
            "source_path": ("a,b.pdf",),
            "extractor_id": ("x", "y"),
            "locator_kind": ("page", "line"),
        }

    def test_locator_kind_outside_the_closed_set_is_refused(self) -> None:
        with pytest.raises(InvalidFilterValueError) as caught:
            _resolve(DocumentFilterRequest(locator_kind="page,folio"))
        assert caught.value.offending_filters == ["folio"]

    def test_prefix_matches_whole_dotted_segments_only(self) -> None:
        resolved = _resolve(
            DocumentFilterRequest(extractor_prefix="a.b"),
            "a.b",
            "a.b.c",
            "a.bc",
            "z.a.b",
        )
        assert resolved == {"extractor_id": ("a.b", "a.b.c")}

    def test_prefix_list_unions_and_intersects_with_explicit_ids(self) -> None:
        ids = ("a.x", "b.y", "c.z")
        assert _resolve(DocumentFilterRequest(extractor_prefix="a,b"), *ids) == {
            "extractor_id": ("a.x", "b.y")
        }
        narrowed = _resolve(
            DocumentFilterRequest(extractor_prefix="a,b", extractor_id="b.y,c.z"),
            *ids,
        )
        assert narrowed == {"extractor_id": ("b.y",)}

    def test_prefix_matching_nothing_yields_a_match_nothing_condition(self) -> None:
        resolved = _resolve(DocumentFilterRequest(extractor_prefix="q"), "a.b")
        assert resolved == {"extractor_id": ()}

    @pytest.mark.parametrize("prefix", ["a..b", ".a", "a.", ","])
    def test_prefix_with_an_empty_segment_is_refused(self, prefix: str) -> None:
        with pytest.raises(InvalidFilterValueError):
            resolve_document_filters(
                DocumentFilterRequest(extractor_prefix=prefix), (), _no_facet
            )

    def test_facet_asks_one_past_the_bound_and_accepts_the_bound(self) -> None:
        bound = store_schema.EXTRACTOR_ID_FACET_BOUND
        asked: list[int] = []

        def extractor_ids(limit: int) -> Sequence[str]:
            asked.append(limit)
            return [f"e{i}" for i in range(bound)]

        resolved = resolve_document_filters(
            DocumentFilterRequest(extractor_prefix="e1"), (), extractor_ids
        )
        assert asked == [bound + 1]
        assert "e1" in resolved["extractor_id"]

    def test_facet_overflow_is_refused_rather_than_applied_partially(self) -> None:
        # Guard. Proven to fail: changing the overflow test in
        # _extractor_prefix_values from "len(values) > bound" to
        # "len(values) > bound + 1" lets the partial set through, failing
        # here with DID NOT RAISE.
        bound = store_schema.EXTRACTOR_ID_FACET_BOUND

        def extractor_ids(limit: int) -> Sequence[str]:
            return [f"e{i}" for i in range(limit)]

        with pytest.raises(ExtractorPrefixUnboundedError) as caught:
            resolve_document_filters(
                DocumentFilterRequest(extractor_prefix="e1"), (), extractor_ids
            )
        assert caught.value.error_code == "extractor_prefix_unbounded"
        assert caught.value.bound == bound

    def test_declared_metadata_resolves_to_its_nested_field(self) -> None:
        resolved = _resolve(
            DocumentFilterRequest(
                metadata_filters={"lang": ["en", "de"], "team": []},
            )
        )
        assert resolved == {
            "unit_metadata.lang": ("en", "de"),
            "document_metadata.team": (),
        }

    def test_undeclared_metadata_key_is_refused_naming_declared_keys(self) -> None:
        # Guard. Proven to fail: replacing the raise in _metadata_conditions
        # with "continue" drops the key, failing here with DID NOT RAISE.
        with pytest.raises(UnknownFilterKeyError) as caught:
            _resolve(DocumentFilterRequest(metadata_filters={"owner": ["me"]}))
        assert caught.value.key == "meta.owner"
        assert caught.value.accepted == ("meta.lang", "meta.team")
        assert caught.value.filter_kind == "document"

    def test_bare_string_metadata_value_is_refused(self) -> None:
        with pytest.raises(InvalidFilterValueError):
            _resolve(
                DocumentFilterRequest(
                    metadata_filters=cast("dict[str, list[str]]", {"lang": "en"})
                )
            )

    def test_inline_tokens_resolve_and_explicit_arguments_win(self) -> None:
        parsed = parse_query("manual meta.lang=en,de meta.team=docs")
        assert parsed.text == "manual"
        resolved = _resolve(
            DocumentFilterRequest(
                metadata_filters={"team": ["eng"]}, inline=parsed.filters
            )
        )
        assert resolved == {
            "unit_metadata.lang": ("en", "de"),
            "document_metadata.team": ("eng",),
        }

    def test_inline_undeclared_metadata_token_is_refused(self) -> None:
        with pytest.raises(UnknownFilterKeyError):
            _resolve(DocumentFilterRequest(inline=parse_query("meta.a.b=c").filters))


class TestMetadataAssignments:
    def test_assignments_build_the_mapping(self) -> None:
        assert metadata_filters_from_assignments(["lang=en,de", "team=docs"]) == {
            "lang": ["en", "de"],
            "team": ["docs"],
        }
        assert metadata_filters_from_assignments([]) is None

    @pytest.mark.parametrize("assignments", [["lang"], ["=en"], ["lang=en", "lang=de"]])
    def test_malformed_or_repeated_assignments_are_refused(
        self, assignments: list[str]
    ) -> None:
        with pytest.raises(InvalidFilterValueError):
            metadata_filters_from_assignments(assignments)


class TestTypeScoping:
    @pytest.mark.parametrize(
        "options",
        [
            SearchFilterOptions(extractor_prefix="a"),
            SearchFilterOptions(metadata_filters={"lang": ["en"]}),
        ],
    )
    @pytest.mark.parametrize("search_type", ["vault", "code"])
    def test_document_only_filters_are_refused_on_vault_and_code_search(
        self, options: SearchFilterOptions, search_type: str
    ) -> None:
        # Guard. Proven to fail: dropping the final document-kind rejection in
        # validate_search_filters lets the call return, so pytest.raises fails.
        with pytest.raises(InvalidFilterForSearchTypeError) as caught:
            validate_search_filters(search_type, options)
        assert caught.value.filter_kind == "document"
        assert caught.value.error_code == "invalid_filter_for_search_type"

    def test_document_only_filters_pass_on_document_search(self) -> None:
        validate_search_filters(
            "document",
            SearchFilterOptions(
                extractor_prefix="a", metadata_filters={"lang": ["en"]}
            ),
        )


def _write_config(root: Path, body: str) -> None:
    (root / ".vaultragpreprocess.toml").write_text(
        f"version = 2\n{body}", encoding="utf-8"
    )


class TestFilterableMetadataDeclaration:
    def test_declared_keys_are_read_from_the_policy_file(self, tmp_path: Path) -> None:
        _write_config(
            tmp_path,
            '[[filterable_metadata]]\nkey = "team"\nscope = "document"\n'
            '[[filterable_metadata]]\nkey = "lang"\nscope = "unit"\n',
        )
        assert load_filterable_metadata(tmp_path) == (_LANG, _TEAM)

    def test_missing_file_declares_nothing(self, tmp_path: Path) -> None:
        assert load_filterable_metadata(tmp_path) == ()

    def test_key_in_both_scopes_is_dropped_and_fails_the_check(
        self, tmp_path: Path
    ) -> None:
        _write_config(
            tmp_path,
            '[[filterable_metadata]]\nkey = "lang"\nscope = "unit"\n'
            '[[filterable_metadata]]\nkey = "lang"\nscope = "document"\n'
            '[[filterable_metadata]]\nkey = "team"\nscope = "document"\n',
        )
        assert load_filterable_metadata(tmp_path) == (_TEAM,)
        with pytest.raises(PreprocessConfigError, match="more than one scope"):
            load_preprocess_rules(tmp_path, strict=True)

    @pytest.mark.parametrize(
        "entry",
        [
            'key = "a.b"\nscope = "unit"\n',
            'key = "lang"\nscope = "page"\n',
            'key = "lang"\nscope = "unit"\nindex = true\n',
        ],
    )
    def test_invalid_entry_is_dropped_and_fails_the_check(
        self, tmp_path: Path, entry: str
    ) -> None:
        _write_config(tmp_path, f"[[filterable_metadata]]\n{entry}")
        assert load_filterable_metadata(tmp_path) == ()
        with pytest.raises(PreprocessConfigError):
            load_preprocess_rules(tmp_path, strict=True)
