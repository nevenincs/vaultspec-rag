"""Versioned preprocess output schema (the preprocessor/indexer contract).

This is the schema contract. A
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

import json
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .._store_models import DocumentLocatorKind

__all__ = [
    "PREPROCESS_INVOCATION_ENV",
    "SUPPORTED_SCHEMA_VERSION",
    "Locator",
    "PreprocOutput",
    "PreprocUnit",
    "PreprocessInvocation",
    "PreprocessInvocationMode",
    "UnsupportedSchemaVersionError",
    "load_preprocess_invocation",
    "validate_preproc_output",
]

#: The schema major version this indexer understands. A document declaring a
#: higher ``schema_version`` is rejected; a lower one is accepted when it
#: still constructs, which for v1 is every valid document.
SUPPORTED_SCHEMA_VERSION = 1
PREPROCESS_INVOCATION_SCHEMA_VERSION = 1
PREPROCESS_INVOCATION_ENV = "VAULTSPEC_PREPROCESS_INVOCATION"

PreprocessInvocationMode = Literal["single", "batch"]


class PreprocessInvocation(BaseModel):
    """Versioned host-to-extractor execution envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = PREPROCESS_INVOCATION_SCHEMA_VERSION
    source_paths: tuple[str, ...] = Field(min_length=1)
    options: dict[str, JsonValue] = Field(default_factory=dict)
    extractor_version: str = Field(min_length=1)
    target: Literal["code", "document"]
    mode: PreprocessInvocationMode

    @property
    def canonical_json(self) -> str:
        """Return deterministic JSON suitable for environment delivery."""
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )


def load_preprocess_invocation() -> PreprocessInvocation:
    """Load and validate the invocation envelope in an extractor process."""
    raw = os.environ.get(PREPROCESS_INVOCATION_ENV)
    if raw is None:
        raise RuntimeError(f"missing {PREPROCESS_INVOCATION_ENV}")
    return PreprocessInvocation.model_validate_json(raw)


class UnsupportedSchemaVersionError(ValueError):
    """Raised when preprocessor output declares a newer schema than supported.

    Caught per-file at ingest and turned into a preprocess skip with a clear
    "upgrade vaultspec-rag" message, never a crash.
    """


class Locator(BaseModel):
    """A deep-link locator into the source's own addressing scheme.

    ``value`` is polymorphic: a page/line/byte/char number, or a sheet name.
    Stored split into typed payload fields downstream so each kind keeps a
    usable index.
    """

    model_config = ConfigDict(extra="forbid")

    kind: DocumentLocatorKind
    value: int | str
    end: int | str | None = None


# Upper bound on one unit's embedded text. Deliberately generous: it exists
# to make the contract honest and reject the pathological payload at the
# validation boundary, not to substitute for splitting - the indexer splits
# any unit above the model window regardless. Sized well under the emitted-
# output transport cap so a single unit can never monopolize it.
UNIT_TEXT_MAX_CHARS = 1_000_000


class PreprocUnit(BaseModel):
    """One pre-chunked unit emitted by a preprocessor.

    "Pre-chunked" describes the hook's semantic intent, not a size guarantee
    the pipeline trusts: unit text is bounded here and additionally split by
    the indexer whenever it exceeds the document split budget.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=UNIT_TEXT_MAX_CHARS)
    title: str | None = Field(default=None, max_length=4096)
    section: str | None = Field(default=None, max_length=4096)
    anchor: str | None = Field(default=None, max_length=8192)
    locator: Locator | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bound_metadata(self) -> PreprocUnit:
        _validate_metadata(self.metadata, max_bytes=16 * 1024)
        return self


class PreprocOutput(BaseModel):
    """The document-level wrapper a preprocessor emits for one source file.

    Exactly one of ``units`` (pre-chunked; still size-bounded and split by
    the indexer when a unit exceeds the document split budget) or ``text``
    (extracted plain text, which the indexer runs through the same splitter)
    is set; the XOR is enforced by a model validator.
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
        if self.units is not None and len(self.units) > 100_000:
            msg = "'units' exceeds the per-document unit limit"
            raise ValueError(msg)
        _validate_metadata(self.metadata, max_bytes=64 * 1024)
        return self


def _validate_metadata(metadata: dict[str, JsonValue], *, max_bytes: int) -> None:
    """Reject metadata that cannot remain a bounded payload component."""
    if len(metadata) > 256:
        raise ValueError("metadata exceeds 256 top-level fields")
    encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError(f"metadata exceeds {max_bytes} encoded bytes")


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
