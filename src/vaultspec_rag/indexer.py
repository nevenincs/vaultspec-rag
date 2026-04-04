"""Indexing pipeline for vault semantic search.

Scans vault documents, extracts metadata, generates embeddings, and
stores them in the Qdrant vector store. Supports full and incremental indexing.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import threading

    import pathspec
    from tree_sitter import Node as TSNode
    from tree_sitter_language_pack import SupportedLanguage

    from .embeddings import EmbeddingModel
    from .store import VaultStore

from vaultspec_core.vaultcore import (
    DocType,
    get_doc_type,
    parse_vault_metadata,
    scan_vault,
)

from .store import CodeChunk, VaultDocument

logger = logging.getLogger(__name__)

__all__ = [
    "ASTChunker",
    "CodebaseIndexer",
    "IndexResult",
    "VaultIndexer",
    "prepare_document",
]


@dataclass
class IndexResult:
    """Result of an indexing operation.

    Attributes:
        total: Total number of items in the index after the operation.
        added: Number of newly indexed items.
        updated: Number of re-indexed (modified) items.
        removed: Number of items removed from the index.
        duration_ms: Wall-clock time for the operation in milliseconds.
        device: Compute device used for embeddings (e.g. ``"cuda"``).
        files: Number of files processed (for codebase indexing).
    """

    total: int
    added: int
    updated: int
    removed: int
    duration_ms: int
    device: str
    files: int = 0


class TextSplitter:
    """Structure-aware text splitter for code and markdown.

    Recursively splits text using language-specific separators (e.g. class
    and function boundaries for code, headings for markdown). Falls back to
    character-level splitting when no structural separator is found. Supports
    configurable chunk size and overlap.
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        language: str = "text",
    ) -> None:
        """Initialize the text splitter.

        Args:
            chunk_size: Maximum number of characters per chunk.
            chunk_overlap: Number of characters to overlap between
                consecutive chunks for context continuity.
            language: Language hint used to select structural
                separators (e.g. ``"python"``, ``"markdown"``).
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.language = language

        # Language-specific separators (order matters: most structural first)
        self.separators = {
            "python": ["\nclass ", "\ndef ", "\n\n", "\n", " ", ""],
            "rust": [
                "\nfn ",
                "\nimpl ",
                "\ntrait ",
                "\nstruct ",
                "\nenum ",
                "\n\n",
                "\n",
                " ",
                "",
            ],
            "markdown": [
                "\n# ",
                "\n## ",
                "\n### ",
                "\n#### ",
                "\n\n",
                "\n",
                " ",
                "",
            ],
            "text": ["\n\n", "\n", " ", ""],
        }.get(language, ["\n\n", "\n", " ", ""])

    def split_text(self, text: str) -> list[str]:
        """Split text into chunks based on separators and chunk size.

        Args:
            text: The input text to split.

        Returns:
            List of text chunks, each at most ``chunk_size`` characters.
        """
        # This is a simplified version of RecursiveCharacterTextSplitter logic
        chunks = []
        if not text:
            return chunks

        def _recursive_split(
            remaining_text: str,
            seps: list[str],
        ) -> list[str]:
            """Recursively split text using hierarchical separators.

            Tries each separator in order, splitting the text and
            merging pieces up to ``chunk_size``.  Recurses with the
            next separator when a piece is still too large.

            Args:
                remaining_text: Text still to be split.
                seps: Remaining separators to try, most
                    structural first.

            Returns:
                List of text chunks, each at most
                ``chunk_size`` characters.
            """
            if len(remaining_text) <= self.chunk_size:
                return [remaining_text]

            if not seps:
                # Force split by length if no separators left
                return [
                    remaining_text[i : i + self.chunk_size]
                    for i in range(
                        0,
                        len(remaining_text),
                        self.chunk_size - self.chunk_overlap,
                    )
                ]

            separator = seps[0]
            splits = remaining_text.split(separator)

            final_chunks = []
            current_chunk = ""

            for s in splits:
                if not current_chunk:
                    current_chunk = s
                elif len(current_chunk) + len(separator) + len(s) <= self.chunk_size:
                    current_chunk += separator + s
                else:
                    final_chunks.append(current_chunk)
                    overlap_start = max(0, len(current_chunk) - self.chunk_overlap)
                    current_chunk = current_chunk[overlap_start:] + separator + s

            if current_chunk:
                final_chunks.append(current_chunk)

            # If any chunk is still too big, recurse with next separator
            processed = []
            for c in final_chunks:
                if len(c) > self.chunk_size:
                    processed.extend(_recursive_split(c, seps[1:]))
                else:
                    processed.append(c)
            return processed

        return _recursive_split(text, self.separators)


# ---------------------------------------------------------------------------
# Language extension mapping (shared by ASTChunker and CodebaseIndexer)
# ---------------------------------------------------------------------------

#: Maps file extensions to (language_name, tree_sitter_grammar_name).
#: Grammar name is None for formats where AST chunking adds no value.
LANGUAGE_MAP: dict[str, tuple[str, str | None]] = {
    ".py": ("python", "python"),
    ".rs": ("rust", "rust"),
    ".md": ("markdown", None),
    ".js": ("javascript", "javascript"),
    ".jsx": ("javascript", "javascript"),
    ".ts": ("typescript", "typescript"),
    ".tsx": ("typescript", "tsx"),
    ".go": ("go", "go"),
    ".java": ("java", "java"),
    ".c": ("c", "c"),
    ".h": ("c", "c"),
    ".cpp": ("cpp", "cpp"),
    ".hpp": ("cpp", "cpp"),
    ".cc": ("cpp", "cpp"),
    ".cs": ("csharp", "csharp"),
    ".rb": ("ruby", "ruby"),
    ".sh": ("shell", "bash"),
    ".bash": ("shell", "bash"),
    ".yaml": ("yaml", None),
    ".yml": ("yaml", None),
    ".toml": ("toml", None),
    ".json": ("json", None),
    ".html": ("html", None),
    ".css": ("css", None),
    ".kt": ("kotlin", "kotlin"),
}

SUPPORTED_EXTENSIONS: set[str] = set(LANGUAGE_MAP.keys())

#: AST node types that define top-level chunk boundaries per language.
_TOP_LEVEL_NODES: dict[str, set[str]] = {
    "python": {"function_definition", "class_definition", "decorated_definition"},
    "rust": {
        "function_item",
        "impl_item",
        "struct_item",
        "enum_item",
        "trait_item",
    },
    "javascript": {
        "function_declaration",
        "class_declaration",
        "variable_declaration",
        "export_statement",
        "lexical_declaration",
    },
    "typescript": {
        "function_declaration",
        "class_declaration",
        "variable_declaration",
        "export_statement",
        "lexical_declaration",
        "interface_declaration",
        "type_alias_declaration",
    },
    "tsx": {
        "function_declaration",
        "class_declaration",
        "variable_declaration",
        "export_statement",
        "lexical_declaration",
        "interface_declaration",
        "type_alias_declaration",
    },
    "go": {
        "function_declaration",
        "method_declaration",
        "type_declaration",
    },
    "java": {
        "class_declaration",
        "method_declaration",
        "interface_declaration",
    },
    "c": {"function_definition", "struct_specifier", "enum_specifier"},
    "cpp": {
        "function_definition",
        "struct_specifier",
        "class_specifier",
        "enum_specifier",
        "namespace_definition",
    },
    "csharp": {
        "class_declaration",
        "method_declaration",
        "namespace_declaration",
        "interface_declaration",
    },
    "ruby": {"method", "class", "module", "singleton_method"},
    "bash": {"function_definition"},
    "kotlin": {
        "class_declaration",
        "function_declaration",
        "object_declaration",
    },
}

# Maximum file size for indexing (10 MB).
_MAX_FILE_SIZE = 10 * 1024 * 1024

#: AST node types that represent class-like constructs (for class_name extraction).
_CLASS_LIKE_NODES: set[str] = {
    "class_definition",  # python
    "class_declaration",  # js, ts, java, c#, kotlin
    "class_specifier",  # cpp
    "impl_item",  # rust
    "struct_item",  # rust
    "struct_specifier",  # c, cpp
    "enum_item",  # rust
    "enum_specifier",  # c, cpp
    "enum_declaration",  # java
    "interface_declaration",  # java, ts, c#, kotlin
    "trait_item",  # rust
    "union_item",  # rust
    "class",  # ruby
    "module",  # ruby
    "object_declaration",  # kotlin
    "type_declaration",  # go
}

#: AST node types for function-like constructs (function_name).
_FUNCTION_LIKE_NODES: set[str] = {
    "function_definition",  # python, c, cpp, bash
    "function_declaration",  # js, ts, go, kotlin
    "function_item",  # rust
    "arrow_function",  # js, ts
    "method",  # ruby
    "method_definition",  # js, ts
    "method_declaration",  # java, go, c#
    "constructor_declaration",  # java
    "singleton_method",  # ruby
}

#: AST node types for top-level container nodes that should always recurse.
_CONTAINER_NODES: set[str] = {
    "module",
    "program",
    "translation_unit",
    "source_file",
    "compilation_unit",
}


def _is_binary(path: pathlib.Path, sample_size: int = 8192) -> bool:
    """Return True if the file appears to be binary (contains null bytes)."""
    try:
        chunk = path.read_bytes()[:sample_size]
    except OSError:
        return True
    return b"\x00" in chunk


class ASTChunker:
    """Structure-aware code chunker using tree-sitter ASTs.

    Implements a simplified cAST algorithm: depth-first traversal of the AST,
    greedily merging sibling nodes up to a character budget, recursing into
    children when a node exceeds the budget.
    """

    def __init__(self, chunk_size: int = 1500) -> None:
        """Initialize the AST chunker.

        Args:
            chunk_size: Maximum number of characters per chunk.
                Nodes exceeding this budget are recursively split
                into smaller pieces.
        """
        self.chunk_size = chunk_size

    def chunk(
        self,
        source: str,
        grammar: str,
    ) -> list[tuple[str, int, int, str | None, str | None, str | None]]:
        """Split source code into AST-aware chunks.

        Args:
            source: Source code text.
            grammar: tree-sitter grammar name (e.g. ``"python"``).

        Returns:
            List of ``(text, line_start, line_end, node_type, function_name,
            class_name)`` tuples.  ``node_type`` is the AST node type of the
            primary node (e.g. ``"function_definition"``), or ``None`` for
            merged chunks.  ``function_name`` and ``class_name`` are extracted
            from the AST ``name`` field when available.
        """
        from tree_sitter_language_pack import get_parser

        parser = get_parser(cast("SupportedLanguage", grammar))
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
        root = tree.root_node

        top_nodes = _TOP_LEVEL_NODES.get(grammar, set())
        chunks: list[tuple[str, int, int, str | None, str | None, str | None]] = []
        self._collect_chunks(root, source, source_bytes, top_nodes, chunks)

        # Merge tiny adjacent chunks that are under half the budget.
        return self._merge_small(chunks)

    @staticmethod
    def _extract_name(
        node: TSNode,
        source_bytes: bytes,
    ) -> str | None:
        """Extract the identifier name from an AST node's ``name`` field.

        Uses byte offsets into the UTF-8 encoded source to correctly
        handle non-ASCII identifiers.

        Args:
            node: A tree-sitter AST node with an optional ``name``
                child field.
            source_bytes: UTF-8 encoded source code used for byte
                offset slicing.

        Returns:
            The identifier string, or ``None`` if the node has no
            ``name`` field.
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        return source_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8")

    @staticmethod
    def _find_decorated_inner(node: TSNode) -> TSNode | None:
        """Find the actual definition inside a ``decorated_definition``.

        Skips ``decorator`` children and returns the first child that is
        a class or function definition, or ``None`` if not found.

        Args:
            node: A tree-sitter ``decorated_definition`` AST node.

        Returns:
            The inner definition node (class or function), or ``None``
            if none is found.
        """
        for child in node.children:
            child_type: str = child.type
            if child_type != "decorator" and child_type != "comment":
                return child
        return None

    def _collect_chunks(
        self,
        node: TSNode,
        source: str,
        source_bytes: bytes,
        top_nodes: set[str],
        out: list[tuple[str, int, int, str | None, str | None, str | None]],
        parent_class_name: str | None = None,
    ) -> None:
        """Recursively collect AST-aligned chunks.

        Performs a depth-first traversal of the AST.  Nodes that fit
        within the character budget are emitted directly; oversized
        nodes are split by recursing into their children.  Small
        sibling nodes are greedily merged into a single chunk.

        Args:
            node: Current tree-sitter AST node to process.
            source: Original source code as a string.
            source_bytes: UTF-8 encoded source used for byte-offset
                slicing.
            top_nodes: Set of AST node types that define top-level
                chunk boundaries for the grammar.
            out: Accumulator list to which ``(text, line_start,
                line_end, node_type, function_name, class_name)``
                tuples are appended.
            parent_class_name: Class name inherited from an enclosing
                class node, or ``None`` at the top level.
        """
        text = source_bytes[node.start_byte : node.end_byte].decode("utf-8")
        node_type: str = node.type

        # Handle decorated_definition: inspect the wrapped definition
        # to determine whether this is a function or class decoration.
        if node_type == "decorated_definition":
            inner = self._find_decorated_inner(node)
            if inner is not None:
                inner_type: str = inner.type
                is_class = inner_type in _CLASS_LIKE_NODES
                is_func = inner_type in _FUNCTION_LIKE_NODES
                node_name = (
                    self._extract_name(inner, source_bytes)
                    if (is_class or is_func)
                    else None
                )
            else:
                is_class = False
                is_func = False
                node_name = None
        else:
            is_class = node_type in _CLASS_LIKE_NODES
            is_func = node_type in _FUNCTION_LIKE_NODES
            node_name = (
                self._extract_name(node, source_bytes)
                if (is_class or is_func)
                else None
            )

        function_name = node_name if is_func else None
        class_name = node_name if is_class else parent_class_name

        is_container = node_type in _CONTAINER_NODES

        if len(text) <= self.chunk_size and not is_container:
            line_start = node.start_point[0] + 1
            line_end = node.end_point[0] + 1
            label = node_type if node_type in top_nodes else None
            out.append((text, line_start, line_end, label, function_name, class_name))
            return

        children = node.children
        if not children:
            # Leaf node too large — force-split by character.
            node_start_line = node.start_point[0] + 1
            for i in range(0, len(text), self.chunk_size):
                chunk = text[i : i + self.chunk_size]
                # Count newlines in text[:i] to get line offset from node start.
                ls = node_start_line + text[:i].count("\n")
                le = ls + chunk.count("\n")
                out.append((chunk, ls, le, None, function_name, class_name))
            return

        # When recursing into a class body, propagate the class name downward.
        child_class_name = node_name if is_class else parent_class_name

        # Recurse into children, greedily merging small siblings.
        buffer_parts: list[str] = []
        buffer_start: int | None = None
        buffer_end: int = 0
        buffer_len = 0

        for child in children:
            child_text = source_bytes[child.start_byte : child.end_byte].decode("utf-8")
            child_type: str = child.type

            # Structural children (functions, classes, decorators) are
            # emitted via recursion so they carry proper metadata.
            is_structural = (
                child_type in _FUNCTION_LIKE_NODES
                or child_type in _CLASS_LIKE_NODES
                or child_type in top_nodes
                or child_type == "decorated_definition"
            )

            if len(child_text) > self.chunk_size or is_structural:
                if buffer_parts and buffer_start is not None:
                    merged = "\n".join(buffer_parts)
                    out.append(
                        (
                            merged,
                            buffer_start,
                            buffer_end,
                            None,
                            function_name,
                            child_class_name,
                        )
                    )
                    buffer_parts = []
                    buffer_start = None
                    buffer_len = 0
                self._collect_chunks(
                    child,
                    source,
                    source_bytes,
                    top_nodes,
                    out,
                    child_class_name,
                )
            elif buffer_len + len(child_text) + 1 > self.chunk_size:
                if buffer_parts and buffer_start is not None:
                    merged = "\n".join(buffer_parts)
                    out.append(
                        (
                            merged,
                            buffer_start,
                            buffer_end,
                            None,
                            function_name,
                            child_class_name,
                        )
                    )
                buffer_parts = [child_text]
                buffer_start = child.start_point[0] + 1
                buffer_end = child.end_point[0] + 1
                buffer_len = len(child_text)
            else:
                buffer_parts.append(child_text)
                if buffer_start is None:
                    buffer_start = child.start_point[0] + 1
                buffer_end = child.end_point[0] + 1
                buffer_len += len(child_text) + 1

        if buffer_parts and buffer_start is not None:
            merged = "\n".join(buffer_parts)
            out.append(
                (
                    merged,
                    buffer_start,
                    buffer_end,
                    None,
                    function_name,
                    child_class_name,
                )
            )

    def _merge_small(
        self,
        chunks: list[tuple[str, int, int, str | None, str | None, str | None]],
    ) -> list[tuple[str, int, int, str | None, str | None, str | None]]:
        """Merge adjacent chunks that are under half the budget.

        Two consecutive chunks are merged when both are shorter than
        ``chunk_size // 2`` and their combined length (plus a newline)
        still fits within ``chunk_size``.

        Args:
            chunks: List of ``(text, line_start, line_end, node_type,
                function_name, class_name)`` tuples produced by
                ``_collect_chunks``.

        Returns:
            A new list of ``(text, line_start, line_end, node_type,
            function_name, class_name)`` tuples with small adjacent
            entries merged.  ``node_type`` is ``None`` when two merged
            chunks had different types.
        """
        if not chunks:
            return chunks
        half = self.chunk_size // 2
        merged: list[tuple[str, int, int, str | None, str | None, str | None]] = []
        for chunk in chunks:
            if (
                merged
                and len(merged[-1][0]) < half
                and len(chunk[0]) < half
                and len(merged[-1][0]) + len(chunk[0]) + 1 <= self.chunk_size
            ):
                prev = merged[-1]
                # When merging, node_type is None if the two chunks
                # have different types (cross-type merge).
                if prev[3] is not None and chunk[3] is not None:
                    merged_nt = prev[3] if prev[3] == chunk[3] else None
                else:
                    merged_nt = prev[3] or chunk[3]
                merged[-1] = (
                    prev[0] + "\n" + chunk[0],
                    prev[1],
                    chunk[2],
                    merged_nt,
                    prev[4] or chunk[4],  # function_name: keep first non-None
                    prev[5] or chunk[5],  # class_name: keep first non-None
                )
            else:
                merged.append(chunk)
        return merged


def _extract_title(body: str) -> str:
    """Extract first H1 heading from markdown body, or return empty string.

    Args:
        body: Raw markdown text to scan.

    Returns:
        The heading text (without the leading ``# ``), or ``""`` if none found.
    """
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _extract_feature(metadata_tags: list[str]) -> str:
    """Extract the feature tag (non-directory tag) from the tag list.

    Args:
        metadata_tags: List of frontmatter tag strings (e.g. ``["#plan", "#rag"]``).

    Returns:
        The feature tag value without the leading ``#``, or ``""`` if none found.
    """
    for tag in metadata_tags:
        if not DocType.from_tag(tag):
            return tag.lstrip("#")
    return ""


def prepare_document(
    path: pathlib.Path,
    root_dir: pathlib.Path,
) -> VaultDocument | None:
    """Prepare a single vault document for indexing (without vector).

    Reads the file, parses metadata, and constructs a VaultDocument
    with all fields except the vector (which is filled during embedding).

    Args:
        path: Absolute path to the markdown document file.
        root_dir: Workspace root directory used to compute the relative path.

    Returns:
        A ``VaultDocument`` with an empty vector, or ``None`` if the file
        cannot be read or has no recognised doc type.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Cannot read %s: %s", path, e)
        return None

    metadata, body = parse_vault_metadata(content)
    doc_type_enum = get_doc_type(path, root_dir)

    if doc_type_enum is None:
        return None

    from .config import get_config

    docs_dir = root_dir / get_config().docs_dir
    try:
        rel_path = str(path.relative_to(docs_dir)).replace("\\", "/")
    except ValueError:
        rel_path = path.name

    title = _extract_title(body)
    if not title:
        title = path.stem

    feature = _extract_feature(metadata.tags)

    # Use relative path (without extension) as ID to avoid collisions
    # e.g., "adr/overview" instead of just "overview"
    doc_id = rel_path.rsplit(".", 1)[0] if "." in rel_path else rel_path

    return VaultDocument(
        id=doc_id,
        path=rel_path,
        doc_type=doc_type_enum.value,
        feature=feature,
        date=metadata.date or "",
        tags=metadata.tags,
        related=metadata.related,
        title=title,
        content=body.strip(),
        vector=[],  # filled during embedding step
    )


class VaultIndexer:
    """Orchestrates vault document indexing into the vector store.

    Scans the ``.vault/`` directory for markdown documents, parses YAML
    frontmatter to extract metadata (tags, dates, related links), generates
    dense and sparse embeddings via the provided ``EmbeddingModel``, and
    upserts the results into Qdrant. Supports both full and incremental
    indexing using blake2b content hashing to skip unchanged documents.
    """

    def __init__(
        self,
        root_dir: pathlib.Path,
        model: EmbeddingModel,
        store: VaultStore,
        *,
        gpu_lock: threading.Lock | None = None,
    ) -> None:
        """Initialize the indexer with a workspace root, embedding model, and store.

        Args:
            root_dir: Path to the vault workspace root.
            model: Embedding model used to encode document text.
            store: Vector store where indexed documents are persisted.
            gpu_lock: Optional ``threading.Lock`` that serializes
                GPU operations (encoding) with concurrent searches.
        """
        from .config import get_config

        cfg = get_config()

        self.root_dir = root_dir
        self.model = model
        self.store = store
        self._gpu_lock = gpu_lock
        self._meta_path = root_dir / cfg.data_dir / cfg.index_metadata_file

    def full_index(self, clean: bool = False) -> IndexResult:
        """Full re-index of all vault documents.

        Scans all documents, embeds them, and replaces the entire store.

        Args:
            clean: If True, drop and recreate the collection before
                indexing to guarantee no stale documents persist.

        Returns:
            An ``IndexResult`` where ``added`` equals the total number of
            documents written and ``updated``/``removed`` are both zero.

        Raises:
            OSError: If existing documents cannot be deleted during a
                non-clean full re-index (raised to prevent duplicates).
        """
        start = time.time()

        paths = list(scan_vault(self.root_dir))
        docs = []
        with ThreadPoolExecutor() as pool:
            futures = [pool.submit(prepare_document, p, self.root_dir) for p in paths]
            for future in futures:
                try:
                    doc = future.result()
                except Exception:
                    logger.warning("Worker failed to prepare document", exc_info=True)
                    continue
                if doc is not None:
                    docs.append(doc)

        if not docs:
            return IndexResult(
                total=0,
                added=0,
                updated=0,
                removed=0,
                duration_ms=0,
                device=self.model.device,
            )

        texts = [f"{d.title}\n\n{d.content}" for d in docs]
        with self._gpu_lock if self._gpu_lock is not None else nullcontext():
            vectors = self.model.encode_documents(texts)
            sparse_vecs = self.model.encode_documents_sparse(texts)

        for doc, vec, svec in zip(docs, vectors, sparse_vecs, strict=True):
            doc.vector = vec.tolist()
            doc.sparse_indices = list(svec.indices)
            doc.sparse_values = list(svec.values)

        if clean:
            self.store.drop_table()
            self.store.ensure_table()
        else:
            self.store.ensure_table()
            try:
                existing_ids = self.store.get_all_ids()
                if existing_ids:
                    self.store.delete_documents(list(existing_ids))
            except OSError:
                logger.error(
                    "Failed to delete existing documents during full "
                    "re-index — aborting to prevent duplicates",
                )
                raise

        self.store.upsert_documents(docs)

        self._save_meta(docs)

        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=len(docs),
            added=len(docs),
            updated=0,
            removed=0,
            duration_ms=duration_ms,
            device=self.model.device,
        )

    def incremental_index(self) -> IndexResult:
        """Incremental index: only re-index new and modified documents.

        Compares blake2b content hashes against stored metadata to identify
        changes.

        Returns:
            An ``IndexResult`` with counts for newly added, updated, and
            removed documents since the last index run.

        Raises:
            OSError: If vault files cannot be read or hashed.
        """
        start = time.time()

        prev_meta = self._load_meta()

        from .config import get_config

        docs_dir = self.root_dir / get_config().docs_dir
        current_docs: dict[str, pathlib.Path] = {}
        for path in scan_vault(self.root_dir):
            doc_type = get_doc_type(path, self.root_dir)
            if doc_type is not None:
                try:
                    rel = str(path.relative_to(docs_dir)).replace("\\", "/")
                except ValueError:
                    rel = path.name
                doc_id = rel.rsplit(".", 1)[0] if "." in rel else rel
                current_docs[doc_id] = path

        stored_ids = self.store.get_all_ids()

        current_ids = set(current_docs.keys())
        new_ids = current_ids - stored_ids
        deleted_ids = stored_ids - current_ids
        potentially_modified = current_ids & stored_ids

        current_hashes: dict[str, str] = {}
        for doc_id, path in current_docs.items():
            try:
                with open(path, "rb") as f:
                    current_hashes[doc_id] = hashlib.file_digest(
                        f,
                        "blake2b",
                    ).hexdigest()
            except OSError:
                logger.warning("Cannot hash file, skipping: %s", doc_id)

        modified_ids = {
            doc_id
            for doc_id in potentially_modified
            if doc_id in current_hashes
            and current_hashes[doc_id] != prev_meta.get(doc_id)
        }

        to_index_ids = new_ids | modified_ids
        docs_to_index = []
        if to_index_ids:
            paths_to_index = [current_docs[doc_id] for doc_id in to_index_ids]
            with ThreadPoolExecutor() as pool:
                results = pool.map(
                    lambda p: prepare_document(p, self.root_dir),
                    paths_to_index,
                )
                for doc in results:
                    if doc is not None:
                        docs_to_index.append(doc)

        if docs_to_index:
            texts = [f"{d.title}\n\n{d.content}" for d in docs_to_index]
            with self._gpu_lock if self._gpu_lock is not None else nullcontext():
                vectors = self.model.encode_documents(texts)
                sparse_vecs = self.model.encode_documents_sparse(texts)
            for doc, vec, svec in zip(docs_to_index, vectors, sparse_vecs, strict=True):
                doc.vector = vec.tolist()
                doc.sparse_indices = list(svec.indices)
                doc.sparse_values = list(svec.values)
            self.store.upsert_documents(docs_to_index)

        if deleted_ids:
            self.store.delete_documents(list(deleted_ids))

        self._write_meta(current_hashes)

        total = self.store.count()
        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=total,
            added=len(new_ids),
            updated=len(modified_ids),
            removed=len(deleted_ids),
            duration_ms=duration_ms,
            device=self.model.device,
        )

    def _save_meta(self, docs: list[VaultDocument]) -> None:
        """Save index metadata (content hashes) from VaultDocument list.

        Computes blake2b hashes for each document's file and delegates
        to ``_write_meta`` for atomic persistence.  Individual file
        read errors are suppressed.

        Args:
            docs: List of indexed documents whose paths are used to
                compute hashes.

        Raises:
            OSError: If the metadata file cannot be written (propagated
                from ``_write_meta``).
        """
        meta: dict[str, str] = {}
        from .config import get_config

        docs_dir = self.root_dir / get_config().docs_dir
        for doc in docs:
            path = docs_dir / doc.path
            with contextlib.suppress(OSError), open(path, "rb") as f:
                meta[doc.id] = hashlib.file_digest(
                    f,
                    "blake2b",
                ).hexdigest()
        self._write_meta(meta)

    def _write_meta(self, meta: dict[str, str]) -> None:
        """Write content-hash metadata to the sidecar JSON file.

        Uses an atomic write (write-to-temp + os.replace) so a crash mid-write
        never leaves the metadata file in a corrupt state.

        Args:
            meta: Mapping of document stem to blake2b hex digest.

        Raises:
            OSError: If the metadata directory cannot be created or the
                file cannot be written.
        """
        self._meta_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._meta_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        os.replace(tmp_path, self._meta_path)

    def _load_meta(self) -> dict[str, str]:
        """Load index metadata from the sidecar JSON file.

        Returns:
            Mapping of document stem to blake2b hex digest, or an empty
            dict if the file does not exist or cannot be parsed.
        """
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except (KeyError, ValueError, OSError):
            return {}


class CodebaseIndexer:
    """Orchestrates source code indexing into the vector store.

    Walks the project tree with ``.gitignore``-aware pruning, chunks source
    files using tree-sitter AST analysis when a grammar is available or
    ``TextSplitter`` as a fallback, generates dense and sparse embeddings,
    and upserts the results into Qdrant. Supports 16+ languages via
    tree-sitter grammars and incremental indexing using blake2b content
    hashing to skip unchanged files.
    """

    def __init__(
        self,
        root_dir: pathlib.Path,
        model: EmbeddingModel,
        store: VaultStore,
        *,
        gpu_lock: threading.Lock | None = None,
        extra_excludes: list[str] | None = None,
    ) -> None:
        """Initialize the codebase indexer.

        Args:
            root_dir: Path to the project root directory to index.
            model: Embedding model used to encode code chunks.
            store: Vector store where indexed code chunks are
                persisted.
            gpu_lock: Optional ``threading.Lock`` that serializes
                GPU operations (encoding) with concurrent searches.
            extra_excludes: Additional gitignore-syntax exclusion
                patterns (e.g. from CLI ``--exclude``). Merged into
                the ``.vaultragignore`` spec.
        """
        self.root_dir = root_dir
        self.model = model
        self.store = store
        self._gpu_lock = gpu_lock
        self._extra_excludes = extra_excludes or []
        from .config import get_config

        cfg = get_config()
        self._meta_path = root_dir / cfg.data_dir / cfg.code_index_metadata_file

    @staticmethod
    def _get_language(path: pathlib.Path) -> str:
        """Return the language name for a file extension.

        Args:
            path: File path whose suffix determines the language.

        Returns:
            Language name string (e.g. ``"python"``), or ``"text"``
            if the extension is not in ``LANGUAGE_MAP``.
        """
        entry = LANGUAGE_MAP.get(path.suffix.lower())
        return entry[0] if entry else "text"

    def _build_gitignore_spec(self) -> pathspec.GitIgnoreSpec:
        """Build a pathspec from hardcoded exclusions and ``.gitignore`` files.

        Collects patterns from all ``.gitignore`` files in the project
        tree, prefixing each pattern by the file's relative directory
        so that patterns work correctly from the project root.

        Returns:
            A compiled ``GitIgnoreSpec`` covering hardcoded dirs and
            all ``.gitignore`` entries.
        """
        import pathspec

        from .config import get_config

        cfg = get_config()
        patterns: list[str] = [
            # Always exclude these directories.
            ".venv/",
            ".git/",
            "node_modules/",
            "__pycache__/",
            f"{cfg.data_dir}/",
        ]
        for gitignore in self.root_dir.rglob(".gitignore"):
            try:
                lines = gitignore.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            rel_dir = gitignore.parent.relative_to(self.root_dir)
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if str(rel_dir) == ".":
                    patterns.append(stripped)
                else:
                    prefix = str(rel_dir).replace(chr(92), "/")
                    if stripped.startswith("!"):
                        # Negation must stay at the start: !subdir/pattern
                        inner = stripped[1:].lstrip("/")
                        patterns.append(f"!{prefix}/{inner}")
                    else:
                        patterns.append(f"{prefix}/{stripped.lstrip('/')}")

        return pathspec.GitIgnoreSpec.from_lines(patterns)

    def _build_vaultragignore_spec(self) -> pathspec.GitIgnoreSpec | None:
        """Build a pathspec from ``.vaultragignore`` and CLI ``--exclude`` patterns.

        Reads patterns from the ``.vaultragignore`` file at the project
        root (if it exists) and merges any ``extra_excludes`` passed via
        the constructor.  Returns ``None`` when no patterns are present.

        Returns:
            A compiled ``GitIgnoreSpec``, or ``None`` if there are no
            patterns to apply.
        """
        import pathspec

        patterns: list[str] = []
        ignore_file = self.root_dir / ".vaultragignore"
        if ignore_file.is_file():
            try:
                lines = ignore_file.read_text(encoding="utf-8").splitlines()
                patterns.extend(
                    line.strip()
                    for line in lines
                    if line.strip() and not line.strip().startswith("#")
                )
            except OSError:
                pass  # silently ignore unreadable file
        patterns.extend(self._extra_excludes)
        if not patterns:
            return None
        return pathspec.GitIgnoreSpec.from_lines(patterns)

    def _scan_codebase(self) -> list[pathlib.Path]:
        """Scan codebase for supported source files.

        Walks the project tree using ``os.walk``, pruning directories
        matched by ``.gitignore`` and ``.vaultragignore`` patterns via
        ``pathspec``.  The two specs are independent — a file is
        excluded if **either** matches (OR logic), so
        ``.vaultragignore`` can never un-ignore ``.gitignore`` entries.
        Skips binary files and files exceeding ``_MAX_FILE_SIZE``.

        Returns:
            List of absolute paths to indexable source files.

        Raises:
            OSError: If the root directory cannot be traversed.
        """
        git_spec = self._build_gitignore_spec()
        rag_spec = self._build_vaultragignore_spec()

        def _is_excluded(rel_path: str) -> bool:
            if git_spec.match_file(rel_path):
                return True
            return rag_spec is not None and rag_spec.match_file(rel_path)

        result: list[pathlib.Path] = []
        root_str = str(self.root_dir)
        for dirpath, dirs, files in os.walk(self.root_dir, topdown=True):
            # Prune ignored directories in-place to avoid traversal
            rel_dir = os.path.relpath(dirpath, root_str).replace("\\", "/")
            if rel_dir == ".":
                dirs[:] = [d for d in dirs if not _is_excluded(f"{d}/")]
            else:
                dirs[:] = [d for d in dirs if not _is_excluded(f"{rel_dir}/{d}/")]
            for fname in files:
                p = pathlib.Path(dirpath) / fname
                if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                rel = fname if rel_dir == "." else f"{rel_dir}/{fname}"
                if _is_excluded(rel):
                    continue
                if p.stat().st_size > _MAX_FILE_SIZE:
                    logger.debug("Skipping oversized file: %s", rel)
                    continue
                if _is_binary(p):
                    logger.debug("Skipping binary file: %s", rel)
                    continue
                result.append(p)
        return result

    def scan_files(self) -> list[pathlib.Path]:
        """Return the list of files that would be indexed.

        Does not require GPU or vector store — safe to call with
        ``model=None`` and ``store=None`` for dry-run usage.

        Returns:
            List of absolute paths to indexable source files.
        """
        return self._scan_codebase()

    def _chunk_file(self, path: pathlib.Path) -> list[CodeChunk]:
        """Read file and split into AST-aware CodeChunks.

        Uses tree-sitter AST chunking for languages with grammars,
        falling back to TextSplitter for config/data formats.

        Args:
            path: Absolute path to the source file.

        Returns:
            List of ``CodeChunk`` instances with empty vectors.
        """
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Cannot read %s: %s", path, e)
            return []

        ext = path.suffix.lower()
        lang_entry = LANGUAGE_MAP.get(ext)
        language = lang_entry[0] if lang_entry else "text"
        grammar = lang_entry[1] if lang_entry else None
        rel_path = str(path.relative_to(self.root_dir)).replace("\\", "/")

        if grammar:
            return self._chunk_with_ast(content, rel_path, language, grammar)
        return self._chunk_with_splitter(content, rel_path, language)

    def _chunk_with_ast(
        self,
        content: str,
        rel_path: str,
        language: str,
        grammar: str,
    ) -> list[CodeChunk]:
        """Chunk source code using tree-sitter AST.

        Falls back to ``_chunk_with_splitter`` if AST parsing fails
        (e.g. syntax errors or missing grammar).

        Args:
            content: Source code text.
            rel_path: File path relative to the project root.
            language: Language name (e.g. ``"python"``).
            grammar: tree-sitter grammar name (e.g. ``"python"``).

        Returns:
            List of ``CodeChunk`` instances with empty vectors.
        """
        chunker = ASTChunker()
        try:
            ast_chunks = chunker.chunk(content, grammar)
        except Exception:
            logger.warning(
                "AST parsing failed for %s, falling back to text splitter",
                rel_path,
                exc_info=True,
            )
            return self._chunk_with_splitter(content, rel_path, language)

        chunks: list[CodeChunk] = []
        for (
            text,
            line_start,
            line_end,
            node_type,
            function_name,
            class_name,
        ) in ast_chunks:
            if not text.strip():
                continue
            chunk_hash = hashlib.blake2b(
                text.encode("utf-8"),
                digest_size=6,
            ).hexdigest()
            chunks.append(
                CodeChunk(
                    id=f"{rel_path}:{line_start}-{line_end}:{chunk_hash}",
                    path=rel_path,
                    language=language,
                    content=text,
                    line_start=line_start,
                    line_end=line_end,
                    node_type=node_type,
                    function_name=function_name,
                    class_name=class_name,
                    vector=[],
                ),
            )
        return chunks

    def _chunk_with_splitter(
        self,
        content: str,
        rel_path: str,
        language: str,
    ) -> list[CodeChunk]:
        """Chunk content using TextSplitter for non-AST languages.

        Args:
            content: Source code or config file text.
            rel_path: File path relative to the project root.
            language: Language name passed to ``TextSplitter`` for
                separator selection.

        Returns:
            List of ``CodeChunk`` instances with empty vectors.
        """
        # chunk_overlap=0 is required: non-zero overlap prepends content from the
        # previous chunk, making chunks not findable verbatim in the original source.
        # This breaks line number tracking in _chunk_with_splitter.
        splitter = TextSplitter(language=language, chunk_overlap=0)
        text_chunks = splitter.split_text(content)

        chunks: list[CodeChunk] = []
        search_offset = 0
        for text in text_chunks:
            idx = content.find(text, search_offset)
            if idx != -1:
                line_start = content.count("\n", 0, idx) + 1
                search_offset = idx + len(text)
            else:
                # Chunk not found verbatim — happens when TextSplitter overlap
                # is > 0 and prepended tail text shifts the chunk boundary.
                # Fall back to search_offset as approximation; line number
                # may be off by the overlap size.
                logger.debug(
                    "Chunk not found verbatim in %s at offset %d; "
                    "line_start is approximate (chunk_overlap > 0?)",
                    rel_path,
                    search_offset,
                )
                line_start = content.count("\n", 0, search_offset) + 1
                search_offset += len(text)
            line_end = line_start + text.count("\n")

            chunk_hash = hashlib.blake2b(
                text.encode("utf-8"),
                digest_size=6,
            ).hexdigest()
            chunks.append(
                CodeChunk(
                    id=f"{rel_path}:{line_start}-{line_end}:{chunk_hash}",
                    path=rel_path,
                    language=language,
                    content=text,
                    line_start=line_start,
                    line_end=line_end,
                    vector=[],
                ),
            )
        return chunks

    def full_index(self, clean: bool = False) -> IndexResult:
        """Full re-index of all codebase files.

        Args:
            clean: If True, drop and recreate the collection before
                indexing to guarantee no stale chunks persist.

        Returns:
            An ``IndexResult`` where ``added`` equals the total chunk
            count and ``updated``/``removed`` are both zero.

        Raises:
            OSError: If source files cannot be read or hashed.
        """
        start = time.time()
        paths = self._scan_codebase()

        # Hash files at scan time (before chunking/embedding) so the
        # metadata is consistent with the content that was actually indexed.
        meta: dict[str, str] = {}
        for p in paths:
            rel = str(p.relative_to(self.root_dir)).replace("\\", "/")
            try:
                with open(p, "rb") as f:
                    meta[rel] = hashlib.file_digest(f, "blake2b").hexdigest()
            except OSError:
                logger.warning("Cannot hash file for metadata: %s", rel)

        all_chunks = []

        with ThreadPoolExecutor() as pool:
            results = pool.map(self._chunk_file, paths)
            for file_chunks in results:
                all_chunks.extend(file_chunks)

        if not all_chunks:
            return IndexResult(
                total=0,
                added=0,
                updated=0,
                removed=0,
                duration_ms=0,
                device=self.model.device,
            )

        texts = [c.content for c in all_chunks]
        with self._gpu_lock if self._gpu_lock is not None else nullcontext():
            vectors = self.model.encode_documents(texts)
            sparse_vecs = self.model.encode_documents_sparse(texts)
        for chunk, vec, svec in zip(all_chunks, vectors, sparse_vecs, strict=True):
            chunk.vector = vec.tolist()
            chunk.sparse_indices = list(svec.indices)
            chunk.sparse_values = list(svec.values)

        if clean:
            self.store.drop_code_table()
            self.store.ensure_code_table()
        else:
            self.store.ensure_code_table()
            existing_ids = self.store.get_all_code_ids()
            if existing_ids:
                self.store.delete_code_chunks(list(existing_ids))

        self.store.upsert_code_chunks(all_chunks)
        self._write_meta(meta)

        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=len(all_chunks),
            added=len(all_chunks),
            updated=0,
            removed=0,
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(paths),
        )

    def incremental_index(self) -> IndexResult:
        """Incremental index: only re-index new and modified source files.

        Uses blake2b content hashing to detect changes (not mtime).

        Returns:
            An ``IndexResult`` with counts for newly added, updated, and
            removed chunks since the last index run.

        Raises:
            OSError: If source files cannot be read or hashed.
        """
        start = time.time()
        prev_meta = self._load_meta()

        current_paths = self._scan_codebase()
        current_files: dict[str, pathlib.Path] = {
            str(p.relative_to(self.root_dir)).replace("\\", "/"): p
            for p in current_paths
        }

        current_hashes: dict[str, str] = {}
        for rel, path in current_files.items():
            try:
                with open(path, "rb") as f:
                    current_hashes[rel] = hashlib.file_digest(
                        f,
                        "blake2b",
                    ).hexdigest()
            except OSError:
                logger.warning("Cannot hash file, skipping: %s", rel)

        # Remove unhashed files from current_files so they are not
        # passed to _chunk_file and don't reappear as "new" every run.
        for rel in set(current_files) - set(current_hashes):
            del current_files[rel]

        # Identify changes (only consider files we successfully hashed)
        prev_files = set(prev_meta.keys())
        curr_files = set(current_hashes.keys())
        new_files = curr_files - prev_files
        deleted_files = prev_files - curr_files
        modified_files = {
            f for f in curr_files & prev_files if current_hashes[f] != prev_meta.get(f)
        }

        to_index = new_files | modified_files
        all_new_chunks: list[CodeChunk] = []
        if to_index:
            paths_to_index = [current_files[f] for f in to_index]
            with ThreadPoolExecutor() as pool:
                results = pool.map(self._chunk_file, paths_to_index)
                for file_chunks in results:
                    all_new_chunks.extend(file_chunks)

        files_to_remove = modified_files | deleted_files
        if files_to_remove:
            old_chunk_ids = self._get_chunk_ids_for_files(files_to_remove)
            if old_chunk_ids:
                self.store.delete_code_chunks(old_chunk_ids)

        if all_new_chunks:
            texts = [c.content for c in all_new_chunks]
            with self._gpu_lock if self._gpu_lock is not None else nullcontext():
                vectors = self.model.encode_documents(texts)
                sparse_vecs = self.model.encode_documents_sparse(texts)
            for chunk, vec, svec in zip(
                all_new_chunks,
                vectors,
                sparse_vecs,
                strict=True,
            ):
                chunk.vector = vec.tolist()
                chunk.sparse_indices = list(svec.indices)
                chunk.sparse_values = list(svec.values)
            self.store.upsert_code_chunks(all_new_chunks)

        # Save updated metadata (file path -> content hash).
        # Use current_hashes (not current_files) as source — files that
        # failed hashing are excluded so they don't cause KeyError.
        self._write_meta(current_hashes)

        total = self.store.count_code()
        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=total,
            added=len(new_files),
            updated=len(modified_files),
            removed=len(deleted_files),
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(to_index),
        )

    def _get_chunk_ids_for_files(
        self,
        rel_paths: set[str],
    ) -> list[str]:
        """Return chunk IDs from the store that belong to the given files.

        Args:
            rel_paths: Set of file paths (relative to the project
                root) whose chunk IDs should be retrieved.

        Returns:
            List of chunk ID strings stored for the given files.
        """
        return self.store.get_code_ids_by_paths(rel_paths)

    def _write_meta(self, meta: dict[str, str]) -> None:
        """Atomically write content-hash metadata to the sidecar JSON file.

        Uses write-to-temp + ``os.replace`` so a crash mid-write never
        corrupts the metadata file.

        Args:
            meta: Mapping of relative file path to blake2b hex digest.

        Raises:
            OSError: If the metadata directory cannot be created or the
                file cannot be written.
        """
        self._meta_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._meta_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        os.replace(tmp_path, self._meta_path)

    def _load_meta(self) -> dict[str, str]:
        """Load codebase index metadata from the sidecar JSON file.

        Returns:
            Mapping of relative file path to blake2b hex digest, or
            an empty dict if the file does not exist or cannot be
            parsed.
        """
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except (KeyError, ValueError, OSError):
            return {}
