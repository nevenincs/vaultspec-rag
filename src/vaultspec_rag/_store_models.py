"""Point schemas and payload builders for the Qdrant vault store.

Split out of ``store.py`` to keep the store module focused on collection and
point operations. These dataclasses and typed payload builders are the shape
contract between the indexer and the on-disk points; they stay light
(stdlib + ``store_schema`` + the pure ``_domain`` classifier, no qdrant or
torch) so spawn workers can import ``CodeChunk`` without pulling heavy deps.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._domain import classify_domain

if TYPE_CHECKING:
    import pathlib

    from . import store_schema

__all__ = [
    "CodeChunk",
    "VaultChunk",
    "VaultDocument",
    "_code_chunk_payload",
    "_vault_chunk_payload",
    "_vault_doc_payload",
    "root_collection_prefix",
]


def root_collection_prefix(root_dir: pathlib.Path | str) -> str:
    """Return the stable per-root collection prefix for server mode.

    One shared qdrant server hosts every root's data, so each root's
    collections are namespaced by a short hash of the resolved root
    path. The hash input is case-normalised (Windows paths are
    case-insensitive) and resolved (``./project`` and ``project``
    collide deliberately) so the same root always lands in the same
    collections across processes and sessions.

    Args:
        root_dir: Workspace root directory.

    Returns:
        A prefix of the form ``r{12-hex}_``.
    """
    import os
    import pathlib as _pathlib

    resolved = os.path.normcase(str(_pathlib.Path(root_dir).resolve()))
    digest = hashlib.blake2b(resolved.encode("utf-8"), digest_size=6).hexdigest()
    return f"r{digest}_"


@dataclass
class VaultDocument:
    """Schema for a single vault document in the vector store.

    Attributes:
        id: Document stem used as the primary key.
        path: Relative path within the docs directory.
        doc_type: Document type string.
        feature: Feature tag without the leading #.
        date: ISO date string parsed from the document frontmatter.
        tags: List of frontmatter tags.
        related: List of related wiki-link strings.
        title: H1 heading extracted from the document body.
        status: ADR lifecycle status parsed from the H1 (e.g. ``accepted``,
            ``superseded``); empty for legacy no-marker ADRs and non-ADR types.
        content: Full markdown body text.
        vector: Dense embedding vector.
        sparse_indices: Sparse vector indices (SPLADE).
        sparse_values: Sparse vector values (SPLADE).
    """

    id: str
    path: str
    doc_type: str
    feature: str
    date: str
    tags: list[str]
    related: list[str]
    title: str
    content: str
    status: str = ""
    vector: list[float] = field(default_factory=list)
    sparse_indices: list[int] = field(default_factory=list)
    sparse_values: list[float] = field(default_factory=list)


@dataclass
class VaultChunk:
    """One heading-aware chunk of a vault document.

    Each chunk becomes one Qdrant point in ``vault_docs``. The parent
    document's metadata is flattened onto every chunk so filters work
    unchanged; ``doc_id`` groups chunks back into documents at search
    time. The ordinal-0 chunk additionally carries ``doc_content``
    (the full document body) so ``get_by_id`` can return the exact
    original text without reassembling chunks.

    Attributes:
        doc_id: Parent document stem (the pre-chunking point identity).
        ordinal: Zero-based chunk position within the document.
        chunk_count: Total chunks the parent document produced.
        text: This chunk's markdown text (stored as point ``content``).
        path: Parent document's relative path.
        doc_type: Parent document type string.
        feature: Parent feature tag without the leading ``#``.
        date: Parent ISO date string.
        tags: Parent frontmatter tags.
        related: Parent related wiki-link strings.
        title: Parent document title.
        status: Parent ADR status (empty for non-ADR and legacy headings).
        doc_content: Full parent body; populated only on ordinal 0.
        vector: Dense embedding vector.
        sparse_indices: Sparse vector indices (SPLADE).
        sparse_values: Sparse vector values (SPLADE).
    """

    doc_id: str
    ordinal: int
    chunk_count: int
    text: str
    path: str
    doc_type: str
    feature: str
    date: str
    tags: list[str]
    related: list[str]
    title: str
    status: str = ""
    doc_content: str | None = None
    vector: list[float] = field(default_factory=list)
    sparse_indices: list[int] = field(default_factory=list)
    sparse_values: list[float] = field(default_factory=list)

    @property
    def point_key(self) -> str:
        """Stable string identity for this chunk's Qdrant point."""
        return f"{self.doc_id}#c{self.ordinal}"


@dataclass
class CodeChunk:
    """Schema for a source code chunk in the vector store.

    Attributes:
        id: Unique chunk ID.
        path: File path relative to project root.
        language: Programming language string.
        content: The actual source code text of the chunk.
        line_start: Starting line number in the source file.
        line_end: Ending line number in the source file.
        node_type: AST node type of the primary node (e.g. "function_definition").
        function_name: Name of the function/method this chunk belongs to, if any.
        class_name: Name of the enclosing class/struct/impl, if any.
        vector: Dense embedding vector.
        sparse_indices: Sparse vector indices (SPLADE).
        sparse_values: Sparse vector values (SPLADE).
        source_path: For a chunk produced by a preprocess hook, the original
            source file path (e.g. a PDF). ``None`` for ordinary code chunks.
        preprocessor_id: The id of the preprocessor that produced this chunk,
            if any (#185 document-preprocessing hooks).
        anchor: A deep-link into the source's own addressing scheme
            (e.g. ``doc.pdf#page=12``), if any.
        locator_kind: The locator kind (``page``/``sheet``/``line``/...), if any.
        locator_value_int: Numeric locator value (page/line/byte/char), if any.
        locator_value_str: String locator value (e.g. a sheet name), if any.
        locator_end_int: Numeric end of a range locator (e.g. pages 1-3), if any.
        locator_end_str: String end of a range locator, if any.
    """

    id: str
    path: str
    language: str
    content: str
    line_start: int
    line_end: int
    node_type: str | None = None
    function_name: str | None = None
    class_name: str | None = None
    vector: list[float] = field(default_factory=list)
    sparse_indices: list[int] = field(default_factory=list)
    sparse_values: list[float] = field(default_factory=list)
    source_path: str | None = None
    preprocessor_id: str | None = None
    anchor: str | None = None
    locator_kind: str | None = None
    locator_value_int: int | None = None
    locator_value_str: str | None = None
    locator_end_int: int | None = None
    locator_end_str: str | None = None


def _vault_doc_payload(doc: VaultDocument) -> store_schema.VaultDocPayload:
    """Build a ``vault_docs`` document point payload from a document.

    The one place the document-level payload shape is constructed; the typed
    return binds it to the schema contract so a field drift is a type error
    and the parity test can assert the produced dict directly.
    """
    return {
        "doc_id": doc.id,
        "path": doc.path,
        "doc_type": doc.doc_type,
        "feature": doc.feature,
        "date": doc.date,
        "tags": doc.tags,
        "related": doc.related,
        "title": doc.title,
        "status": doc.status,
        "content": doc.content,
    }


def _vault_chunk_payload(chunk: VaultChunk) -> store_schema.VaultChunkPayload:
    """Build a ``vault_docs`` chunk point payload from a chunk.

    ``doc_content`` is added only on the ordinal-0 chunk (it is ``NotRequired``
    in the schema), so retrieval-by-id stays exact while the per-chunk payload
    carries just its own text.
    """
    payload: store_schema.VaultChunkPayload = {
        "doc_id": chunk.doc_id,
        "chunk_ordinal": chunk.ordinal,
        "chunk_count": chunk.chunk_count,
        "path": chunk.path,
        "doc_type": chunk.doc_type,
        "feature": chunk.feature,
        "date": chunk.date,
        "tags": chunk.tags,
        "related": chunk.related,
        "title": chunk.title,
        "status": chunk.status,
        "content": chunk.text,
    }
    if chunk.ordinal == 0 and chunk.doc_content is not None:
        payload["doc_content"] = chunk.doc_content
    return payload


def _code_chunk_payload(chunk: CodeChunk) -> store_schema.CodeChunkPayload:
    """Build a ``codebase_docs`` chunk point payload from a code chunk.

    The document-preprocessing hook fields are ``None`` for ordinary code
    chunks; they carry the preprocessed source's own addressing scheme when
    present.
    """
    return {
        "chunk_id": chunk.id,
        "path": chunk.path,
        "language": chunk.language,
        "content": chunk.content,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "node_type": chunk.node_type,
        "function_name": chunk.function_name,
        "class_name": chunk.class_name,
        "source_path": chunk.source_path,
        "preprocessor_id": chunk.preprocessor_id,
        "anchor": chunk.anchor,
        "locator_kind": chunk.locator_kind,
        "locator_value_int": chunk.locator_value_int,
        "locator_value_str": chunk.locator_value_str,
        "locator_end_int": chunk.locator_end_int,
        "locator_end_str": chunk.locator_end_str,
        # Path-derived noise domain, computed once here so the stored label and
        # the query-time fallback share one source of truth (`_domain.py`).
        "domain": classify_domain(chunk.path),
    }
