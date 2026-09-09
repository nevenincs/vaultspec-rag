"""Tests for the closed public source-type parser."""

from __future__ import annotations

import pytest

from .._source_types import (
    PublicSourceType,
    SourceTypeParseError,
    parse_source_type,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("source", list(PublicSourceType))
def test_canonical_source_types_round_trip(source: PublicSourceType) -> None:
    assert parse_source_type(source.value) is source
    assert parse_source_type(source) is source


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("codebase", PublicSourceType.CODE),
        ("docs", PublicSourceType.VAULT),
        ("all", PublicSourceType.COMBINED),
    ],
)
def test_compatibility_aliases_require_explicit_authority(
    alias: str,
    expected: PublicSourceType,
) -> None:
    with pytest.raises(SourceTypeParseError):
        parse_source_type(alias)
    assert parse_source_type(alias, allow_aliases=True) is expected


@pytest.mark.parametrize("value", ["", "unknown", "Document", 1, None, ["code"]])
def test_unknown_source_type_has_structured_error(value: object) -> None:
    with pytest.raises(SourceTypeParseError) as captured:
        parse_source_type(value)
    assert captured.value.as_payload() == {
        "error_kind": "unknown_source_type",
        "received": value,
        "allowed": ["vault", "code", "document", "combined"],
        "aliases_allowed": False,
    }
