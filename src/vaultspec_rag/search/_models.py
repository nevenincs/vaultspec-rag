"""Result and parsed-query dataclasses for vault semantic search.

Holds the two structured value types shared across the search package:
:class:`ParsedQuery` (a query split into cleaned text plus extracted
metadata filters) and :class:`SearchResult` (a single ranked vault or
codebase hit). Defined here once so the parsing, post-processing,
rerank, and searcher submodules share a single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class ParsedQuery:
    """A parsed search query with extracted metadata filters.

    Holds the natural-language query text after filter tokens have been
    stripped, together with the structured filters extracted from those
    tokens.

    Attributes:
        text: Natural-language query text with filter tokens removed.
        filters: Mapping of canonical filter keys (e.g. ``"doc_type"``,
            ``"feature"``, ``"date"``) to their string values, extracted
            from tokens like ``type:adr`` or ``feature:rag``.
    """

    text: str
    filters: dict[str, str]


@dataclass
class SearchResult:
    """A single search result from vault or codebase.

    Represents a ranked document or code chunk returned by hybrid search,
    with metadata fields that vary by source collection.

    Attributes:
        id: Unique document or chunk identifier (e.g. ``"adr/overview"``
            for vault, a blake2b hash for codebase chunks).
        path: File path relative to the project root.
        title: Human-readable title or heading of the result.
        score: Final relevance score after reranking and normalization.
        snippet: Text excerpt from the matching document or code chunk.
        source: Origin collection, either ``"vault"`` or ``"codebase"``.
        doc_type: Vault document type (e.g. ``"adr"``, ``"plan"``).
            Empty string when not applicable.
        feature: Feature tag associated with the document (e.g.
            ``"editor-demo"``).  Empty string when not applicable.
        date: ISO-8601 date string from vault frontmatter.  Empty string
            when not applicable.
        language: Programming language of the source file (codebase
            results only).  Empty string when not applicable.
        line_start: Starting line number in the source file (codebase
            results only).
        line_end: Ending line number in the source file (codebase
            results only).
        node_type: Tree-sitter node type (e.g.
            ``"function_definition"``).  Codebase results only.
        function_name: Name of the enclosing function, if any.  Codebase
            results only.
        class_name: Name of the enclosing class, if any.  Codebase
            results only.
    """

    id: str
    path: str
    title: str
    score: float
    snippet: str
    source: Literal["vault", "codebase"]
    doc_type: str = ""
    feature: str = ""
    date: str = ""
    language: str = ""
    line_start: int | None = None
    line_end: int | None = None
    node_type: str | None = None
    function_name: str | None = None
    class_name: str | None = None
