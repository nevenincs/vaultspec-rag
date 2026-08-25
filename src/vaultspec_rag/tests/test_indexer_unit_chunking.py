"""test indexer unit: the chunking half."""

import hashlib
from pathlib import Path

import pytest

from ..indexer import LANGUAGE_MAP, SUPPORTED_EXTENSIONS, ASTChunker
from ..indexer._chunking import (
    _CLASS_LIKE_NODES,
    _CONTAINER_NODES,
    _FUNCTION_LIKE_NODES,
)
from .test_indexer_unit import (
    _assert_line_spans_locate_chunks,
)

pytestmark = [pytest.mark.unit]


class TestASTChunkerPython:
    """ASTChunker splits Python code at function/class boundaries."""

    SAMPLE = (
        "class Foo:\n"
        "    def bar(self):\n"
        "        return 1\n"
        "\n"
        "    def baz(self):\n"
        "        return 2\n"
        "\n"
        "def standalone():\n"
        "    x = 1\n"
        "    return x\n"
    )

    def test_chunks_at_boundaries(self):
        chunker = ASTChunker(chunk_size=60)
        chunks = chunker.chunk(self.SAMPLE, "python")
        # Should produce more than 1 chunk when budget is small.
        assert len(chunks) > 1

    def test_chunk_content_covers_source(self):
        chunker = ASTChunker(chunk_size=2000)
        chunks = chunker.chunk(self.SAMPLE, "python")
        # With a large budget, the whole file fits in one chunk.
        combined = "\n".join(text for text, *_ in chunks)
        # All source lines should appear in the combined output.
        for line in self.SAMPLE.strip().splitlines():
            assert line in combined

    def test_line_numbers_locate_each_chunk_in_the_source(self):
        chunker = ASTChunker(chunk_size=60)
        chunks = chunker.chunk(self.SAMPLE, "python")
        _assert_line_spans_locate_chunks(self.SAMPLE, chunks)

    def test_empty_source(self):
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk("", "python")
        # tree-sitter may emit a root node for empty input; the chunk
        # worker filters empty chunks via `if not text.strip()`.
        meaningful = [c for c in chunks if c[0].strip()]
        assert meaningful == []

    def test_single_function(self):
        code = "def hello():\n    return 42\n"
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(code, "python")
        assert len(chunks) == 1
        assert "def hello" in chunks[0][0]


class TestASTChunkerMultiLang:
    """ASTChunker works across languages with tree-sitter grammars."""

    def test_rust(self):
        code = 'fn main() {\n    println!("hello");\n}\n'
        chunks = ASTChunker(chunk_size=500).chunk(code, "rust")
        assert len(chunks) >= 1
        assert "fn main" in chunks[0][0]

    def test_javascript(self):
        code = "function greet(name) {\n  return `Hello ${name}`;\n}\n"
        chunks = ASTChunker(chunk_size=500).chunk(code, "javascript")
        assert len(chunks) >= 1

    def test_go(self):
        code = 'package main\n\nfunc main() {\n\tfmt.Println("hi")\n}\n'
        chunks = ASTChunker(chunk_size=500).chunk(code, "go")
        assert len(chunks) >= 1

    def test_force_split_large_leaf(self):
        # A single function larger than chunk_size triggers force-split.
        body = "\n".join(f"    x{i} = {i}" for i in range(100))
        code = f"def big():\n{body}\n"
        chunks = ASTChunker(chunk_size=100).chunk(code, "python")
        assert len(chunks) > 1

    def test_large_leaf_has_exact_line_ranges_across_character_slices(self):
        from tree_sitter_language_pack import get_parser

        source = "'''aa\nbb\ncc\ndd'''"
        tree = get_parser("python").parse(source.encode("utf-8"))
        string_node = tree.root_node.children[0]
        content_node = string_node.children[1]
        content = source[content_node.start_byte : content_node.end_byte]
        chunks: list[tuple[str, int, int, str | None, str | None, str | None]] = []

        ASTChunker(chunk_size=4)._split_large_leaf(
            content_node,
            content,
            None,
            None,
            chunks,
        )

        assert [
            (text, line_start, line_end) for text, line_start, line_end, *_ in chunks
        ] == [
            ("aa\nb", 1, 2),
            ("b\ncc", 2, 3),
            ("\ndd", 3, 4),
        ]


class TestASTChunkerPythonBoundaries:
    """ASTChunker splits Python at function/class boundaries with hash IDs."""

    # Each block must exceed chunk_size individually so AST splits them.
    SAMPLE = (
        "class Greeter:\n"
        + "".join(f"    line_{i} = {i}\n" for i in range(40))
        + "\n"
        + "def standalone():\n"
        + "".join(f"    val_{i} = {i}\n" for i in range(40))
        + "\n"
    )

    def test_chunks_split_at_function_class(self):
        # Budget smaller than each definition forces split.
        chunker = ASTChunker(chunk_size=300)
        chunks = chunker.chunk(self.SAMPLE, "python")
        texts = [t for t, *_ in chunks]
        # Class and standalone function should produce multiple chunks.
        assert len(chunks) >= 2
        # When a class exceeds the budget, tree-sitter recurses into its
        # child nodes - "class" keyword and "Greeter" identifier may be
        # separate small nodes. Verify the names appear in combined output.
        combined = "\n".join(texts)
        assert "Greeter" in combined or "class" in combined
        assert "standalone" in combined

    def test_line_numbers_accurate(self):
        chunker = ASTChunker(chunk_size=300)
        chunks = chunker.chunk(self.SAMPLE, "python")
        _assert_line_spans_locate_chunks(self.SAMPLE, chunks)

    def test_chunk_ids_contain_hash_via_chunk_file(self, tmp_path: Path):
        """AST chunking produces IDs with a blake2b hash suffix."""
        from ..indexer import _chunk_worker

        src = tmp_path / "example.py"
        src.write_text(self.SAMPLE, encoding="utf-8")

        chunks = _chunk_worker.chunk_with_ast(
            self.SAMPLE,
            "example.py",
            "python",
            "python",
        )
        assert len(chunks) >= 1
        seen_ordinals: list[int] = []
        for chunk in chunks:
            # ID format: rel_path:emit_ordinal:line_start-line_end:blake2b_prefix.
            # The emit ordinal is what keeps the id unique when a
            # repeated-content long line splits into byte-identical slices
            # sharing one line span; span plus hash alone cannot.
            parts = chunk.id.split(":")
            assert len(parts) == 4, f"Expected 4 colon-separated parts, got {parts}"
            assert parts[0] == "example.py"
            seen_ordinals.append(int(parts[1]))
            # Verify the hash matches the chunk content.
            expected_hash = hashlib.blake2b(
                chunk.content.encode("utf-8"),
                digest_size=6,
            ).hexdigest()
            assert parts[3] == expected_hash
        # Ordinals are per-file and non-repeating (they may skip values where
        # a blank chunk was dropped, but must never collide).
        assert len(set(seen_ordinals)) == len(seen_ordinals)


class TestASTChunkerJavaScript:
    """ASTChunker splits JavaScript at function_declaration boundaries."""

    JS_SOURCE = (
        "function add(a, b) {\n"
        "  return a + b;\n"
        "}\n"
        "\n"
        "function subtract(a, b) {\n"
        "  return a - b;\n"
        "}\n"
        "\n"
        "const multiply = (a, b) => a * b;\n"
    )

    def test_js_function_boundaries(self):
        chunker = ASTChunker(chunk_size=80)
        chunks = chunker.chunk(self.JS_SOURCE, "javascript")
        texts = [t for t, *_ in chunks]
        assert len(chunks) >= 2
        has_add = any("function add" in t for t in texts)
        has_subtract = any("function subtract" in t for t in texts)
        assert has_add
        assert has_subtract

    def test_js_line_numbers(self):
        chunker = ASTChunker(chunk_size=80)
        chunks = chunker.chunk(self.JS_SOURCE, "javascript")
        _assert_line_spans_locate_chunks(self.JS_SOURCE, chunks)


class TestASTChunkerFallback:
    """ASTChunker falls back to TextSplitter when grammar is invalid."""

    def test_invalid_grammar_falls_back_to_splitter(self):
        """AST chunking returns splitter chunks for an invalid grammar."""
        from ..indexer import _chunk_worker

        content = "x = 1\ny = 2\nz = 3\n"

        chunks = _chunk_worker.chunk_with_ast(
            content,
            "data.py",
            "python",
            "NOT_A_REAL_GRAMMAR",
        )
        assert len(chunks) >= 1
        assert chunks[0].content.strip() == content.strip()

    def test_chunk_file_uses_splitter_for_yaml(self, tmp_path: Path):
        """Files with grammar=None in LANGUAGE_MAP use TextSplitter."""
        from ..indexer import _chunk_worker

        src = tmp_path / "config.yaml"
        content = "key: value\nlist:\n  - item1\n  - item2\n"
        src.write_text(content, encoding="utf-8")

        chunks = _chunk_worker.chunk_file(src, tmp_path)
        assert len(chunks) >= 1
        assert chunks[0].language == "yaml"
        # ID should still carry the emit ordinal and the hash suffix.
        parts = chunks[0].id.split(":")
        assert len(parts) == 4


class TestASTChunkerMetadataExtraction:
    """ASTChunker extracts function_name, class_name, and node_type."""

    def test_chunk_returns_six_tuple(self):
        code = "x = 1\n"
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(code, "python")
        assert len(chunks) >= 1
        assert len(chunks[0]) == 6, "Expected 6-tuple (text, ls, le, node_type, fn, cn)"

    def test_function_name_extracted(self):
        code = "def greet(name):\n    return f'Hello {name}'\n"
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(code, "python")
        assert len(chunks) == 1
        _text, _ls, _le, node_type, function_name, class_name = chunks[0]
        assert function_name == "greet"
        assert class_name is None
        assert node_type == "function_definition"

    def test_class_name_extracted(self):
        code = "class MyService:\n    pass\n"
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(code, "python")
        assert len(chunks) >= 1
        class_chunks = [c for c in chunks if c[5] == "MyService"]
        assert class_chunks, "No chunk with class_name='MyService' found"

    def test_method_inherits_class_name(self):
        # Large class so methods become separate chunks with class context.
        body = "\n".join(f"    val_{i} = {i}" for i in range(50))
        code = f"class BigClass:\n{body}\n    def do_work(self):\n        return True\n"
        chunker = ASTChunker(chunk_size=200)
        chunks = chunker.chunk(code, "python")
        class_named = [c for c in chunks if c[5] == "BigClass"]
        assert class_named, "No chunk with class_name='BigClass'"

    def test_standalone_function_no_class_name(self):
        code = "def helper():\n    return 42\n"
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(code, "python")
        assert len(chunks) == 1
        _text, _ls, _le, _nt, function_name, class_name = chunks[0]
        assert function_name == "helper"
        assert class_name is None

    def test_rust_function_name_extracted(self):
        code = "fn compute(x: i32) -> i32 {\n    x * 2\n}\n"
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(code, "rust")
        assert len(chunks) >= 1
        fn_chunks = [c for c in chunks if c[4] == "compute"]
        assert fn_chunks, "Expected function_name='compute' for Rust fn"


class TestDecoratedDefinitionClassification:
    """@dataclass class Foo must get class_name='Foo', not function_name."""

    def test_dataclass_gets_class_name(self):
        source = (
            "from dataclasses import dataclass\n\n"
            "@dataclass\n"
            "class Config:\n"
            "    name: str = 'default'\n"
        )
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(source, "python")
        # Find chunks with class_name='Config'
        config_chunks = [c for c in chunks if c[5] == "Config"]
        assert config_chunks, (
            f"Expected class_name='Config', got chunks: "
            f"{[(c[3], c[4], c[5]) for c in chunks]}"
        )
        # Must NOT have function_name='Config'
        for c in config_chunks:
            assert c[4] != "Config", (
                "Decorated class incorrectly classified as function"
            )

    def test_decorated_function_gets_function_name(self):
        # Standalone decorated function (no other defs to merge with).
        source = "@some_decorator\ndef process():\n    return 42\n"
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(source, "python")
        # process should have function_name, not class_name
        process_chunks = [c for c in chunks if c[4] == "process"]
        assert process_chunks, (
            f"Expected function_name='process', got chunks: "
            f"{[(c[3], c[4], c[5]) for c in chunks]}"
        )
        for c in process_chunks:
            assert c[5] != "process", (
                "Decorated function incorrectly classified as class"
            )

    def test_decorated_definition_not_in_function_like_nodes(self):
        """decorated_definition must not be in _FUNCTION_LIKE_NODES."""
        assert "decorated_definition" not in _FUNCTION_LIKE_NODES


class TestNodeTypeSets:
    """_CLASS_LIKE_NODES and _FUNCTION_LIKE_NODES contain expected entries."""

    def test_python_class_in_class_like_nodes(self):
        assert "class_definition" in _CLASS_LIKE_NODES

    def test_python_function_in_function_like_nodes(self):
        assert "function_definition" in _FUNCTION_LIKE_NODES

    def test_no_overlap_between_sets(self):
        overlap = _CLASS_LIKE_NODES & _FUNCTION_LIKE_NODES
        assert not overlap, f"Unexpected overlap: {overlap}"


class TestExtendedNodeTypeSets:
    """Extended node type sets."""

    def test_function_like_has_arrow_function(self):
        assert "arrow_function" in _FUNCTION_LIKE_NODES

    def test_function_like_has_method_definition(self):
        assert "method_definition" in _FUNCTION_LIKE_NODES

    def test_function_like_has_constructor_declaration(self):
        assert "constructor_declaration" in _FUNCTION_LIKE_NODES

    def test_class_like_has_enum_declaration(self):
        assert "enum_declaration" in _CLASS_LIKE_NODES

    def test_class_like_has_union_item(self):
        assert "union_item" in _CLASS_LIKE_NODES


class TestContainerNodesConstant:
    """_CONTAINER_NODES is a module-level constant."""

    def test_container_nodes_exists(self):
        assert isinstance(_CONTAINER_NODES, set)
        assert "module" in _CONTAINER_NODES
        assert "program" in _CONTAINER_NODES


class TestLanguageMap:
    def test_python_extension(self):
        lang, grammar = LANGUAGE_MAP[".py"]
        assert lang == "python"
        assert grammar == "python"

    def test_yaml_has_no_grammar(self):
        lang, grammar = LANGUAGE_MAP[".yaml"]
        assert lang == "yaml"
        assert grammar is None

    def test_tsx_grammar(self):
        lang, grammar = LANGUAGE_MAP[".tsx"]
        assert lang == "typescript"
        assert grammar == "tsx"

    def test_all_extensions_count(self):
        assert len(SUPPORTED_EXTENSIONS) >= 29

    def test_go_extension(self):
        assert ".go" in SUPPORTED_EXTENSIONS

    def test_kotlin_extension(self):
        assert ".kt" in SUPPORTED_EXTENSIONS

    def test_csharp_extension(self):
        assert ".cs" in SUPPORTED_EXTENSIONS

    def test_plain_text_extensions_added(self):
        # #185 adjacent ask: plain-text tails index as text (grammar None).
        assert LANGUAGE_MAP[".txt"] == ("text", None)
        assert LANGUAGE_MAP[".properties"] == ("text", None)

    def test_xml_extensions_added(self):
        # #185 adjacent ask: XML/XSD keep a distinct queryable language label.
        assert LANGUAGE_MAP[".xml"] == ("xml", None)
        assert LANGUAGE_MAP[".xsd"] == ("xml", None)


class TestLanguageMapConsistency:
    """LANGUAGE_MAP and SUPPORTED_EXTENSIONS must be consistent."""

    def test_every_supported_ext_in_language_map(self):
        for ext in SUPPORTED_EXTENSIONS:
            assert ext in LANGUAGE_MAP, (
                f"{ext} in SUPPORTED_EXTENSIONS but missing from LANGUAGE_MAP"
            )

    def test_every_language_map_ext_in_supported(self):
        for ext in LANGUAGE_MAP:
            assert ext in SUPPORTED_EXTENSIONS, (
                f"{ext} in LANGUAGE_MAP but missing from SUPPORTED_EXTENSIONS"
            )

    def test_all_extensions_start_with_dot(self):
        for ext in SUPPORTED_EXTENSIONS:
            assert ext.startswith("."), f"Extension missing dot prefix: {ext}"

    def test_language_map_values_are_tuples(self):
        for ext, entry in LANGUAGE_MAP.items():
            assert isinstance(entry, tuple) and len(entry) == 2, (
                f"LANGUAGE_MAP[{ext!r}] should be (lang, grammar) tuple"
            )
            lang, grammar = entry
            assert isinstance(lang, str)
            assert grammar is None or isinstance(grammar, str)


class TestVanishedSourceCostsOnlyItself:
    """A file deleted between enumeration and read must not end the run.

    A tree under active edit loses files mid-run as a matter of course. The
    sizing gate already treats a path that stopped existing as skippable; the
    read seam did not, so one deleted file raised out of the worker and ended
    an entire index run.

    These drive the no-rule path, because that is the path every ordinary
    source file takes and the one the reported failures came through.
    """

    @staticmethod
    def _vanished(tmp_path: Path) -> Path:
        """A path inside *tmp_path* that was enumerated and is now absent."""
        return tmp_path / "gone.py"

    def test_chunk_and_hash_file_reports_a_skip_rather_than_raising(
        self, tmp_path: Path
    ) -> None:
        """Mutation: re-raised FileNotFoundError instead of translating it.

        Observed this fail with FileNotFoundError escaping the call itself,
        before any assertion here ran.
        """
        from ..indexer._chunk_worker import (
            VANISHED_SOURCE_STATUS,
            chunk_and_hash_file,
        )

        result = chunk_and_hash_file(self._vanished(tmp_path), tmp_path)

        assert result.preprocess_status == VANISHED_SOURCE_STATUS
        assert result.chunks == []
        assert "vanished" in (result.preprocess_reason or "")

    def test_chunk_file_with_status_reports_a_skip_rather_than_raising(
        self, tmp_path: Path
    ) -> None:
        """The sibling entry point reaches the read through its own seam.

        Mutation: as above. Observed the same escape from this call.
        """
        from ..indexer._chunk_worker import (
            VANISHED_SOURCE_STATUS,
            chunk_file_with_status,
        )

        result = chunk_file_with_status(self._vanished(tmp_path), tmp_path)

        assert result.preprocess_status == VANISHED_SOURCE_STATUS
        assert result.chunks == []
        assert "vanished" in (result.preprocess_reason or "")

    def test_a_source_that_cannot_be_read_still_ends_the_run(
        self, tmp_path: Path
    ) -> None:
        """Only absence is survivable; a real read fault must still surface.

        Narrowing the translation to a missing file is the point of it. A
        permission or device error means the tree cannot be trusted, and
        reporting one as an ordinary skip would index a partial corpus while
        the run reported success.

        The unreadable source here is real rather than simulated: a directory
        occupying a source file's name, which the OS refuses to read as a file.

        Mutation: widened the translation from FileNotFoundError to OSError.
        Observed this fail on DID NOT RAISE, the refusal arriving as a skip.
        """
        from ..indexer import _chunk_worker

        unreadable = tmp_path / "looks_like_a_module.py"
        unreadable.mkdir()

        with pytest.raises(OSError) as raised:
            _chunk_worker.chunk_and_hash_file(unreadable, tmp_path)

        assert not isinstance(raised.value, FileNotFoundError)
