"""Text splitting and shared language/AST constants for indexing.

Houses the structure-aware ``TextSplitter`` fallback chunker plus the
language extension map and AST node-type constant sets that are shared
by both :class:`~vaultspec_rag.indexer._ast_chunker.ASTChunker` and
:class:`~vaultspec_rag.indexer._codebase_indexer.CodebaseIndexer`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib

logger = logging.getLogger(__name__)

__all__ = [
    "LANGUAGE_MAP",
    "SUPPORTED_EXTENSIONS",
    "_CLASS_LIKE_NODES",
    "_CONTAINER_NODES",
    "_FUNCTION_LIKE_NODES",
    "_MAX_FILE_SIZE",
    "_TOP_LEVEL_NODES",
    "TextSplitter",
    "_is_binary",
]


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
        if not text:
            return []
        return self._recursive_split(text, self.separators)

    def _force_split(self, remaining_text: str) -> list[str]:
        step = max(1, self.chunk_size - self.chunk_overlap)
        return [
            remaining_text[i : i + self.chunk_size]
            for i in range(0, len(remaining_text), step)
        ]

    def _merge_splits(self, splits: list[str], separator: str) -> list[str]:
        final_chunks: list[str] = []
        current_chunk = ""

        for s in splits:
            if not s:
                continue
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
        return final_chunks

    def _recursive_split(
        self,
        remaining_text: str,
        seps: list[str],
    ) -> list[str]:
        if len(remaining_text) <= self.chunk_size:
            return [remaining_text]

        if not seps or seps[0] == "":
            return self._force_split(remaining_text)

        separator = seps[0]
        splits = remaining_text.split(separator)
        final_chunks = self._merge_splits(splits, separator)

        processed: list[str] = []
        for c in final_chunks:
            if len(c) > self.chunk_size:
                processed.extend(self._recursive_split(c, seps[1:]))
            else:
                processed.append(c)
        return processed


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
    except OSError as exc:
        logger.debug("binary probe read failed for %s: %s", path, exc)
        return True
    return b"\x00" in chunk
