"""Unit tests for the preprocess output schema (no GPU).

Exercises D4/D5: the PreprocOutput/PreprocUnit/Locator models, ``extra=forbid``,
the units/text XOR validator, and the schema-version gate.
"""

import pytest
from pydantic import ValidationError

from ..indexer._preprocess_schema import (
    SUPPORTED_SCHEMA_VERSION,
    Locator,
    PreprocOutput,
    PreprocUnit,
    UnsupportedSchemaVersionError,
    validate_preproc_output,
)

pytestmark = [pytest.mark.unit]


def _base(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "preprocessor_id": "pdf-extract",
        "preprocessor_version": "1.0.0",
        "source_path": "docs/a.pdf",
    }
    payload.update(overrides)
    return payload


def test_text_mode_validates() -> None:
    out = validate_preproc_output(_base(text="hello world"))
    assert out.text == "hello world"
    assert out.units is None


def test_units_mode_validates() -> None:
    out = validate_preproc_output(
        _base(
            units=[
                {
                    "text": "page one",
                    "anchor": "docs/a.pdf#page=1",
                    "locator": {"kind": "page", "value": 1},
                }
            ]
        )
    )
    assert out.units is not None
    assert len(out.units) == 1
    assert out.units[0].locator is not None
    assert out.units[0].locator.kind == "page"
    assert out.units[0].locator.value == 1


def test_units_and_text_both_set_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_preproc_output(_base(text="x", units=[{"text": "y"}]))


def test_neither_units_nor_text_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_preproc_output(_base())


def test_empty_units_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_preproc_output(_base(units=[]))


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_preproc_output(_base(text="x", bogus="nope"))


def test_unknown_unit_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_preproc_output(_base(units=[{"text": "y", "bogus": 1}]))


def test_empty_unit_text_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_preproc_output(_base(units=[{"text": ""}]))


def test_missing_required_field_is_rejected() -> None:
    payload = _base(text="x")
    del payload["preprocessor_id"]
    with pytest.raises(ValidationError):
        validate_preproc_output(payload)


def test_newer_schema_version_is_rejected() -> None:
    newer = SUPPORTED_SCHEMA_VERSION + 1
    with pytest.raises(UnsupportedSchemaVersionError):
        validate_preproc_output(_base(schema_version=newer, text="x"))


def test_string_locator_value_for_sheet() -> None:
    loc = Locator(kind="sheet", value="Sheet1")
    assert loc.value == "Sheet1"
    assert loc.end is None


def test_locator_range_end() -> None:
    loc = Locator(kind="line", value=10, end=20)
    assert loc.end == 20


def test_metadata_carries_json_values() -> None:
    unit = PreprocUnit(text="x", metadata={"tags": ["a", "b"], "n": 3})
    assert unit.metadata == {"tags": ["a", "b"], "n": 3}


def test_round_trips_through_model_validate_json() -> None:
    out = PreprocOutput.model_validate(_base(text="hi"))
    raw = out.model_dump_json()
    again = PreprocOutput.model_validate_json(raw)
    assert again == out
