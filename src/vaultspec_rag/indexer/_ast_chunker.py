"""tree-sitter AST-aware code chunker.

Implements a simplified cAST algorithm that aligns chunk boundaries to
syntactic constructs (functions, classes) using tree-sitter parse trees,
falling back to character splitting only for oversized leaf nodes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ._chunking import (
    _CLASS_LIKE_NODES,
    _CONTAINER_NODES,
    _FUNCTION_LIKE_NODES,
    _TOP_LEVEL_NODES,
)

if TYPE_CHECKING:
    from tree_sitter import Node as TSNode
    from tree_sitter_language_pack import SupportedLanguage


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
