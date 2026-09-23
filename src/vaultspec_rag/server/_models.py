"""Pydantic response models for the RAG daemon.

Split out of the original ``server.py`` monolith. These models serialize tool results
across the MCP transport and are re-exported verbatim from the package
root.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .._store_models import DocumentLocatorKind
from ..capabilities import BackendCapabilities


class DocumentLocatorItem(BaseModel):
    """Transport-safe native locator for a document search hit."""

    model_config = {"from_attributes": True}

    kind: DocumentLocatorKind
    value: int | str
    end: int | str | None = None


class SearchResultItem(BaseModel):
    """Pydantic mirror of SearchResult for MCP serialization.

    Attributes:
        id: Unique document or chunk identifier (relative path
            without extension for vault, blake2b hash for code).
        path: File path relative to the workspace root.
        title: Human-readable document or chunk title.
        score: Relevance score (0.0-1.0 after normalization).
        snippet: Text excerpt from the matched document or
            code chunk.
        source: Origin collection, either ``"vault"`` or
            ``"codebase"``.
        doc_type: Vault document type (e.g., ``"adr"``,
            ``"plan"``). Empty for codebase results.
        feature: Feature tag from vault metadata. Empty for
            codebase results.
        date: ISO date string from vault metadata. Empty for
            codebase results.
        language: Programming language (e.g., ``"python"``).
            Empty for vault results.
        line_start: Starting line number in the source file.
            None for vault results.
        line_end: Ending line number in the source file.
            None for vault results.
        node_type: AST node type (e.g.,
            ``"function_definition"``). None for vault results.
        function_name: Function or method name extracted by
            tree-sitter. None if not applicable.
        class_name: Class or struct name extracted by
            tree-sitter. None if not applicable.
        source_path: Original source file for a preprocess-hook result
            (e.g. a PDF). None for ordinary results (#185).
        preprocessor_id: Id of the preprocessor that produced this result.
        anchor: Deep-link into the source's own addressing scheme.
        locator: Human-readable locator (e.g. ``"page 12"``).
    """

    model_config = {"from_attributes": True}

    id: str
    path: str
    title: str
    score: float
    snippet: str
    source: Literal["vault", "codebase", "document"]
    doc_type: str = ""
    feature: str = ""
    date: str = ""
    status: str = ""
    related: list[str] = Field(default_factory=list)
    language: str = ""
    line_start: int | None = None
    line_end: int | None = None
    node_type: str | None = None
    function_name: str | None = None
    class_name: str | None = None
    source_path: str | None = None
    preprocessor_id: str | None = None
    anchor: str | None = None
    locator: str | DocumentLocatorItem | None = None
    section: str | None = None
    document_metadata: dict[str, object] = Field(default_factory=dict)
    unit_metadata: dict[str, object] = Field(default_factory=dict)
    extractor_id: str | None = None
    extractor_version: str | None = None
    rerank_text: str | None = Field(default=None, exclude=True)

    @field_validator("document_metadata", "unit_metadata", mode="before")
    @classmethod
    def _materialize_document_metadata(cls, value: object) -> object:
        materialize = getattr(value, "materialize", None)
        return materialize() if callable(materialize) else value


class SearchResponse(BaseModel):
    """Response envelope for search tool results.

    Attributes:
        results: Ranked list of search result items, ordered
            by descending relevance score.
        summary: Human-readable summary of the search outcome.
        backend_capabilities: Concurrency capabilities for the
            active local vector backend.
    """

    results: list[SearchResultItem] = Field(
        description="List of ranked search results",
    )
    summary: str = Field(
        description="Human-readable summary of findings",
    )
    backend_capabilities: BackendCapabilities = Field(
        default_factory=BackendCapabilities,
        description="Backend concurrency capabilities for agent orchestration",
    )
