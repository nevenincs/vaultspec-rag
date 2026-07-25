"""Point schemas and payload builders for the Qdrant vault store.

Split out of ``store.py`` to keep the store module focused on collection and
point operations. These dataclasses and typed payload builders are the shape
contract between the indexer and the on-disk points; they stay light
(stdlib + ``store_schema`` + the pure ``_domain`` classifier, no qdrant or
torch) so spawn workers can import ``CodeChunk`` without pulling heavy deps.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

from ._domain import classify_domain

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from . import store_schema

__all__ = [
    "CodeChunk",
    "DocumentChunk",
    "DocumentLocator",
    "DocumentMetadata",
    "DocumentPayload",
    "VaultChunk",
    "VaultDocument",
    "_code_chunk_payload",
    "_vault_chunk_payload",
    "_vault_doc_payload",
    "root_collection_prefix",
]

type DocumentLocatorKind = Literal["byte", "page", "sheet", "line", "char", "none"]


@dataclass(frozen=True, slots=True)
class DocumentLocator:
    """Native address of one extracted unit inside its source document."""

    kind: DocumentLocatorKind
    value: int | str
    end: int | str | None = None

    def __post_init__(self) -> None:
        value = cast("object", self.value)
        end = cast("object", self.end)
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise TypeError("document locator value must be an integer or string")
        if isinstance(end, bool) or (
            end is not None and not isinstance(end, (int, str))
        ):
            raise TypeError("document locator end must be an integer, string, or None")


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    """Canonical immutable metadata emitted at document and unit scope."""

    canonical_json: str = "{}"

    def __post_init__(self) -> None:
        decoded = json.loads(self.canonical_json)
        if not isinstance(decoded, dict):
            raise TypeError("document metadata must encode a JSON object")
        canonical = json.dumps(
            decoded,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        if canonical != self.canonical_json:
            raise ValueError("document metadata is not canonically encoded")

    @classmethod
    def from_mapping(cls, values: dict[str, object]) -> DocumentMetadata:
        """Copy caller JSON metadata into sorted immutable storage."""
        try:
            canonical = json.dumps(
                values,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise TypeError("document metadata must be JSON-compatible") from exc
        return cls(canonical)

    def materialize(self) -> dict[str, object]:
        """Return a fresh JSON-compatible mapping for storage or transport."""
        thawed: object = json.loads(self.canonical_json)
        if not isinstance(thawed, dict):
            raise TypeError("invalid canonical document metadata")
        mapping = cast("dict[object, object]", thawed)
        return {str(key): value for key, value in mapping.items()}


@dataclass(frozen=True, slots=True)
class DocumentPayload:
    """Document-native payload fields independent from vector-store syntax."""

    source_path: str
    unit_ordinal: int
    content_fingerprint: str
    content: str
    title: str | None = None
    section: str | None = None
    anchor: str | None = None
    locator: DocumentLocator | None = None
    document_metadata: DocumentMetadata = DocumentMetadata()
    unit_metadata: DocumentMetadata = DocumentMetadata()
    extractor_id: str | None = None
    extractor_version: str | None = None

    def __post_init__(self) -> None:
        if not self.source_path:
            raise ValueError("document source_path must not be empty")
        if self.unit_ordinal < 0:
            raise ValueError("document unit_ordinal must be non-negative")
        if not self.content_fingerprint:
            raise ValueError("document content_fingerprint must not be empty")
        if not self.content:
            raise ValueError("document content must not be empty")


@dataclass(slots=True)
class DocumentChunk:
    """One independently owned document chunk destined for document storage."""

    id: str
    payload: DocumentPayload
    vector: list[float] = field(default_factory=list)
    sparse_indices: list[int] = field(default_factory=list)
    sparse_values: list[float] = field(default_factory=list)


def root_collection_prefix(root_dir: pathlib.Path | str) -> str:
    """Return the stable per-root collection prefix for server mode.

    One shared qdrant server hosts every root's data, so each root's
    collections are namespaced by a short hash of the resolved root
    path. The hash input is case-normalised (Windows paths are
    case-insensitive) and resolved (``./project`` and ``project``
    collide deliberately) so the same root always lands in the same
    collections across processes and sessions. Windows extended-length
    prefixes (``\\\\?\\`` and ``\\\\?\\UNC\\``) are stripped before
    resolution: ``Path.resolve()`` does not reliably collapse them, so
    without the strip an aliased spelling of an already-registered root
    mints a duplicate namespace for the same project.

    Args:
        root_dir: Workspace root directory.

    Returns:
        A prefix of the form ``r{12-hex}_``.
    """
    import os
    import pathlib as _pathlib

    raw = str(root_dir)
    if raw.startswith("\\\\?\\UNC\\"):
        raw = "\\\\" + raw[8:]
    elif raw.startswith("\\\\?\\"):
        raw = raw[4:]
    resolved = os.path.normcase(str(_pathlib.Path(raw).resolve()))
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


#: File holding the per-root pointer to the collection currently serving code
#: reads. Its absence is the normal state for a root that has never published a
#: replacement generation, and resolves to the derived name.
SERVED_CODE_POINTER_FILE = "code_served_collection.json"


def served_code_pointer_path(root_dir: pathlib.Path | str) -> pathlib.Path:
    """Return the path of *root_dir*'s served-collection pointer."""
    from .config import get_config

    cfg = get_config()
    return pathlib.Path(root_dir) / cfg.data_dir / SERVED_CODE_POINTER_FILE


def read_served_code_collection(root_dir: pathlib.Path | str) -> str | None:
    """Return the collection *root_dir* publishes code reads against.

    ``None`` means no replacement has been published and the derived name is
    authoritative. An unreadable, malformed, or empty pointer is also ``None``:
    a root whose pointer cannot be trusted must fall back to the name it would
    have used anyway rather than resolve to nothing and read an absent
    collection.
    """
    path = served_code_pointer_path(root_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("served-collection pointer %s unreadable: %s", path, exc)
        return None
    if not isinstance(raw, dict):
        return None
    name = cast("dict[str, object]", raw).get("collection")
    return name if isinstance(name, str) and name else None


def resolve_served_code_collection(
    root_dir: pathlib.Path | str,
    derived_name: str,
) -> str:
    """Return the collection code reads resolve to for *root_dir*.

    Every read path goes through this rather than deriving the name, so a
    published replacement takes effect for readers at the moment the pointer
    moves and not before. Absent a pointer the derived name is returned
    unchanged, which is what keeps a root written by an older build working
    without migration.
    """
    return read_served_code_collection(root_dir) or derived_name


def publish_served_code_collection(
    root_dir: pathlib.Path | str,
    collection: str,
) -> None:
    """Point *root_dir*'s code reads at *collection*.

    Written to a temporary file and moved into place, so a reader never
    observes a partially written pointer and a crash mid-write leaves the
    previous one intact.
    """
    if not collection:
        raise ValueError("collection must be a non-empty name")
    path = served_code_pointer_path(root_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps({"collection": collection}), encoding="utf-8")
    os.replace(tmp_path, path)


def generation_code_collection(derived_name: str, generation_id: str) -> str:
    """Return the collection a rebuild generation writes into.

    A generation writes to its own name so the collection currently serving
    reads is untouched for the duration of the build, and so an interrupted
    build leaves an unreferenced collection rather than a truncated served
    one.

    The generation identifier is part of the name because names must never be
    reused. Local mode pops a deleted collection's in-memory handle while its
    on-disk directory survives, and a create under the same name re-reads that
    directory - so reusing a name would deliver a superseded generation's
    points into its successor. A fresh name cannot collide with a directory
    that outlived its collection.
    """
    if not derived_name:
        raise ValueError("derived_name must be a non-empty name")
    token = "".join(ch for ch in generation_id if ch.isalnum())
    if not token:
        raise ValueError("generation_id must contain alphanumeric characters")
    return f"{derived_name}_g{token[:16]}"
