"""Versioned preprocess output schema (the preprocessor/indexer contract).

This is the contract decided in the ``preprocess-hooks`` ADR (D4, D5). A
project-supplied preprocessor receives a source file path and emits one JSON
document conforming to :class:`PreprocOutput`: either pre-chunked ``units`` or a
single extracted ``text`` blob, carrying the schema version and the producing
preprocessor's id and version.

The models are pydantic v2 with ``extra="forbid"`` so a typo'd or unexpected
field is a loud validation error rather than silent data loss - the same way the
repo treats its MCP wire boundary. Validation runs per source file inside a
``ValidationError`` handler at ingest, so malformed output is a per-file skip,
never a crash. :data:`SUPPORTED_SCHEMA_VERSION` pins the major the indexer
understands; a newer document is rejected with a clear upgrade message.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

__all__ = [
    "SUPPORTED_SCHEMA_VERSION",
    "Locator",
    "LocatorKind",
    "PreprocOutput",
    "PreprocUnit",
    "UnsupportedSchemaVersionError",
    "validate_preproc_output",
]

#: The schema major version this indexer understands. A document declaring a
#: higher ``schema_version`` is rejected (D5); a lower one is accepted when it
#: still constructs, which for v1 is every valid document.
SUPPORTED_SCHEMA_VERSION = 1

LocatorKind = Literal["byte", "page", "sheet", "line", "char", "none"]


class UnsupportedSchemaVersionError(ValueError):
    """Raised when preprocessor output declares a newer schema than supported.

    Caught per-file at ingest and turned into a preprocess skip with a clear
    "upgrade vaultspec-rag" message, never a crash (D5).
    """


class Locator(BaseModel):
    """A deep-link locator into the source's own addressing scheme.

    ``value`` is polymorphic: a page/line/byte/char number, or a sheet name.
    Stored split into typed payload fields downstream so each kind keeps a
    usable index (D12).
    """

    model_config = ConfigDict(extra="forbid")

    kind: LocatorKind
    value: int | str
    end: int | str | None = None


class PreprocUnit(BaseModel):
    """One pre-chunked unit emitted by a preprocessor."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    title: str | None = None
    section: str | None = None
    anchor: str | None = None
    locator: Locator | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class PreprocOutput(BaseModel):
    """The document-level wrapper a preprocessor emits for one source file.

    Exactly one of ``units`` (pre-chunked) or ``text`` (extracted plain text,
    which the indexer then runs through the normal text splitter) is set; the
    XOR is enforced by a model validator (D4).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    preprocessor_id: str = Field(min_length=1)
    preprocessor_version: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    units: list[PreprocUnit] | None = None
    text: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_units_text_xor(self) -> PreprocOutput:
        """Enforce that exactly one of ``units`` or ``text`` is provided."""
        if (self.units is None) == (self.text is None):
            msg = "exactly one of 'units' or 'text' must be set"
            raise ValueError(msg)
        if self.units is not None and len(self.units) == 0:
            msg = "'units' must be non-empty when provided"
            raise ValueError(msg)
        return self


def validate_preproc_output(payload: object) -> PreprocOutput:
    """Validate raw preprocessor output and gate its schema version.

    Args:
        payload: The parsed JSON object emitted by a preprocessor.

    Returns:
        The validated :class:`PreprocOutput`.

    Raises:
        pydantic.ValidationError: If ``payload`` does not conform to the schema.
        UnsupportedSchemaVersionError: If it declares a newer schema version
            than :data:`SUPPORTED_SCHEMA_VERSION`.
    """
    output = PreprocOutput.model_validate(payload)
    if output.schema_version > SUPPORTED_SCHEMA_VERSION:
        msg = (
            f"preprocessor emitted schema_version {output.schema_version}; "
            f"this vaultspec-rag understands up to {SUPPORTED_SCHEMA_VERSION} "
            "- upgrade vaultspec-rag"
        )
        raise UnsupportedSchemaVersionError(msg)
    return output
