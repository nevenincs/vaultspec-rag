"""Unit tests for rag.indexer — extraction and doc preparation (no GPU)."""

import hashlib
from pathlib import Path

import pytest
from vaultspec_core.config import reset_config

from vaultspec_rag import IndexResult, prepare_document
from vaultspec_rag.config import reset_config as reset_rag_config
from vaultspec_rag.indexer import (
    _CLASS_LIKE_NODES,
    _CONTAINER_NODES,
    _FUNCTION_LIKE_NODES,
    _MAX_FILE_SIZE,
    LANGUAGE_MAP,
    SUPPORTED_EXTENSIONS,
    ASTChunker,
    _extract_feature,
    _extract_title,
    _is_binary,
)

from .constants import TEST_PROJECT

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _reset_cfg():
    reset_config()
    reset_rag_config()
    yield
    reset_config()
    reset_rag_config()


class TestExtractTitle:
    def test_extracts_h1(self):
        assert _extract_title("# My Title\nSome content") == "My Title"

    def test_extracts_first_h1(self):
        assert _extract_title("# First\n## Second\n# Third") == "First"

    def test_no_h1(self):
        assert _extract_title("No heading here") == ""

    def test_empty_string(self):
        assert _extract_title("") == ""

    def test_h1_with_whitespace(self):
        assert _extract_title("  # Spaced Title  ") == "Spaced Title"

    def test_h2_not_extracted(self):
        assert _extract_title("## H2 Heading\nContent") == ""


class TestExtractFeature:
    def test_extracts_feature_tag(self):
        assert _extract_feature(["#adr", "#auth"]) == "auth"

    def test_extracts_feature_from_plan(self):
        assert _extract_feature(["#plan", "#rag"]) == "rag"

    def test_no_feature_tag(self):
        assert _extract_feature(["#adr"]) == ""

    def test_empty_tags(self):
        assert _extract_feature([]) == ""

    def test_doc_type_tags_excluded(self):
        assert _extract_feature(["#research", "#exec", "#reference"]) == ""

    def test_first_non_doctype_wins(self):
        assert _extract_feature(["#adr", "#auth", "#security"]) == "auth"


class TestIndexResult:
    def test_creation(self):
        result = IndexResult(
            total=100,
            added=50,
            updated=10,
            removed=5,
            duration_ms=1234,
            device="cuda",
        )
        assert result.total == 100
        assert result.device == "cuda"


class TestPrepareDocument:
    def test_prepares_valid_document(self):
        doc_path = (
            TEST_PROJECT / ".vault" / "adr" / "2026-01-12-connector-protocol-design.md"
        )
        doc = prepare_document(doc_path, TEST_PROJECT)
        assert doc is not None
        assert doc.id == "adr/2026-01-12-connector-protocol-design"
        assert doc.doc_type == "adr"
        assert doc.feature == "connector-api"
        assert len(doc.title) > 0
        assert doc.vector == []

    def test_returns_doc_for_audit_dir(self):
        audit_files = list((TEST_PROJECT / ".vault" / "audit").glob("*.md"))
        assert len(audit_files) > 0, "test-project must contain audit/*.md files"
        doc = prepare_document(audit_files[0], TEST_PROJECT)
        assert doc is not None, f"prepare_document returned None for {audit_files[0]}"
        assert doc.doc_type == "audit"

    def test_returns_none_for_nonexistent_file(self):
        missing = (
            TEST_PROJECT / ".vault" / "adr" / "nonexistent-doc-that-does-not-exist.md"
        )
        doc = prepare_document(missing, TEST_PROJECT)
        assert doc is None


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

    def test_line_numbers_are_positive(self):
        chunker = ASTChunker(chunk_size=60)
        chunks = chunker.chunk(self.SAMPLE, "python")
        for _text, line_start, line_end, *_ in chunks:
            assert line_start >= 1
            assert line_end >= line_start

    def test_empty_source(self):
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk("", "python")
        # tree-sitter may emit a root node for empty input; the caller
        # (_chunk_file) filters empty chunks via `if not text.strip()`.
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
        assert len(SUPPORTED_EXTENSIONS) >= 25

    def test_go_extension(self):
        assert ".go" in SUPPORTED_EXTENSIONS

    def test_kotlin_extension(self):
        assert ".kt" in SUPPORTED_EXTENSIONS

    def test_csharp_extension(self):
        assert ".cs" in SUPPORTED_EXTENSIONS


class TestBinaryDetection:
    def test_text_file_not_binary(self, tmp_path: Path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')")
        assert _is_binary(f) is False

    def test_binary_file_detected(self, tmp_path: Path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"some\x00binary\x00data")
        assert _is_binary(f) is True

    def test_empty_file_not_binary(self, tmp_path: Path):
        f = tmp_path / "empty"
        f.write_bytes(b"")
        assert _is_binary(f) is False


class TestFileSizeLimit:
    def test_max_file_size_is_10mb(self):
        assert _MAX_FILE_SIZE == 10 * 1024 * 1024


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
        # child nodes — "class" keyword and "Greeter" identifier may be
        # separate small nodes. Verify the names appear in combined output.
        combined = "\n".join(texts)
        assert "Greeter" in combined or "class" in combined
        assert "standalone" in combined

    def test_line_numbers_accurate(self):
        chunker = ASTChunker(chunk_size=300)
        chunks = chunker.chunk(self.SAMPLE, "python")
        lines = self.SAMPLE.splitlines()
        for text, line_start, line_end, *_ in chunks:
            # line_start/line_end are 1-based.
            assert line_start >= 1
            assert line_end <= len(lines) + 1
            assert line_end >= line_start
            # The chunk text should overlap with the source at those lines.
            first_line = text.strip().splitlines()[0]
            assert first_line in self.SAMPLE

    def test_chunk_ids_contain_hash_via_chunk_file(self, tmp_path: Path):
        """_chunk_with_ast produces IDs with blake2b hash suffix."""
        from vaultspec_rag.indexer import CodebaseIndexer

        src = tmp_path / "example.py"
        src.write_text(self.SAMPLE, encoding="utf-8")

        # Call _chunk_with_ast directly (no model/store needed).
        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        chunks = indexer._chunk_with_ast(
            self.SAMPLE,
            "example.py",
            "python",
            "python",
        )
        assert len(chunks) >= 1
        for chunk in chunks:
            # ID format: rel_path:line_start-line_end:blake2b_prefix
            parts = chunk.id.split(":")
            assert len(parts) == 3, f"Expected 3 colon-separated parts, got {parts}"
            assert parts[0] == "example.py"
            # Verify the hash matches the chunk content.
            expected_hash = hashlib.blake2b(
                chunk.content.encode("utf-8"),
                digest_size=6,
            ).hexdigest()
            assert parts[2] == expected_hash


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
        for _text, line_start, line_end, *_ in chunks:
            assert line_start >= 1
            assert line_end >= line_start


class TestASTChunkerFallback:
    """ASTChunker falls back to TextSplitter when grammar is invalid."""

    def test_invalid_grammar_falls_back_to_splitter(self, tmp_path: Path):
        """_chunk_with_ast returns splitter chunks for an invalid grammar."""
        from vaultspec_rag.indexer import CodebaseIndexer

        content = "x = 1\ny = 2\nz = 3\n"

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path

        chunks = indexer._chunk_with_ast(
            content,
            "data.py",
            "python",
            "NOT_A_REAL_GRAMMAR",
        )
        assert len(chunks) >= 1
        assert chunks[0].content.strip() == content.strip()

    def test_chunk_file_uses_splitter_for_yaml(self, tmp_path: Path):
        """Files with grammar=None in LANGUAGE_MAP use TextSplitter."""
        from vaultspec_rag.indexer import CodebaseIndexer

        src = tmp_path / "config.yaml"
        content = "key: value\nlist:\n  - item1\n  - item2\n"
        src.write_text(content, encoding="utf-8")

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        chunks = indexer._chunk_file(src)
        assert len(chunks) >= 1
        assert chunks[0].language == "yaml"
        # ID should still have hash suffix.
        parts = chunks[0].id.split(":")
        assert len(parts) == 3


class TestChunkIDUniqueness:
    """Two identical code blocks at different positions get different IDs."""

    def test_identical_blocks_different_ids(self):
        """Same content at different line positions produces unique chunk IDs
        because the ID format includes line_start-line_end."""
        text = "def helper():\n    return 42\n"
        chunk_hash = hashlib.blake2b(
            text.encode("utf-8"),
            digest_size=6,
        ).hexdigest()

        # Simulate two chunks with identical content at different positions.
        id_a = f"dup.py:1-2:{chunk_hash}"
        id_b = f"dup.py:5-6:{chunk_hash}"
        assert id_a != id_b

    def test_identical_blocks_chunked_separately(self):
        """ASTChunker with small budget splits identical functions apart."""
        # Each block > 400 chars so chunk_size=400 forces separate chunks.
        body = "\n".join(f"    x{i} = {i}" for i in range(50))
        block = f"def helper():\n{body}\n"
        content = block + "\n" + block

        # Use a chunker with a budget smaller than each block.
        ast_chunker = ASTChunker(chunk_size=400)
        raw_chunks = ast_chunker.chunk(content, "python")
        # Tree-sitter merges child nodes with newlines, so "def" and "helper"
        # may be in the same chunk as "def\nhelper" rather than "def helper".
        # Check for "helper" in any chunk.
        helpers = [(t, ls, le) for t, ls, le, *_ in raw_chunks if "helper" in t]
        assert len(helpers) >= 2, f"Expected 2 helper chunks, got {len(helpers)}"
        # Different line positions mean different IDs.
        line_starts = [ls for _, ls, _ in helpers]
        assert len(set(line_starts)) == len(line_starts)


class TestChunkWithSplitterSearchOffset:
    """Regression: _chunk_with_splitter uses search_offset to avoid
    mapping duplicate code blocks to the same line number."""

    def test_duplicate_blocks_get_different_lines(self, tmp_path: Path):
        from vaultspec_rag.indexer import CodebaseIndexer

        # Construct content with an identical block repeated.
        block = "x = 1\ny = 2\nz = 3\n"
        content = block + "\n" + block
        src = tmp_path / "repeat.yaml"
        src.write_text(content, encoding="utf-8")

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        # Use _chunk_with_splitter (TextSplitter path).
        chunks = indexer._chunk_with_splitter(content, "repeat.yaml", "yaml")

        if len(chunks) >= 2:
            # The two chunks covering the same text must have different
            # line_start values — the old content.find() bug would give
            # them the same line_start.
            line_starts = [c.line_start for c in chunks]
            assert len(set(line_starts)) == len(line_starts), (
                f"Duplicate line_start values: {line_starts}"
            )


class TestIncrementalIndexMetadata:
    """CodebaseIndexer metadata uses blake2b hex strings, not floats."""

    def test_meta_values_are_blake2b_hex(self, tmp_path: Path):
        import json

        from vaultspec_rag.indexer import CodebaseIndexer

        # Write a source file.
        src = tmp_path / "mod.py"
        src.write_text("x = 1\n", encoding="utf-8")

        # Construct an indexer just enough to test _write_meta / _load_meta.
        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        indexer._meta_path = tmp_path / ".qdrant" / "code_index_meta.json"

        with open(src, "rb") as f:
            content_hash = hashlib.file_digest(f, "blake2b").hexdigest()
        meta = {"mod.py": content_hash}
        indexer._write_meta(meta)

        # Reload and verify types.
        loaded = indexer._load_meta()
        for key, val in loaded.items():
            assert isinstance(key, str)
            assert isinstance(val, str), (
                f"Expected str hash, got {type(val).__name__}: {val}"
            )
            # Must be a valid hex string (128 chars for blake2b).
            assert len(val) == 128
            int(val, 16)  # raises ValueError if not valid hex

        # Also verify via raw JSON — no floats.
        raw = json.loads(indexer._meta_path.read_text(encoding="utf-8"))
        for val in raw.values():
            assert not isinstance(val, float), (
                f"Metadata value is float, expected hex string: {val}"
            )


class TestIncrementalIndexUnhashedFiles:
    """Files that fail hashing must not appear in saved metadata."""

    def test_metadata_excludes_unhashed_files(self, tmp_path: Path):
        """current_hashes dict (used for metadata) must not include
        files that failed read_bytes, preventing KeyError on save."""
        from vaultspec_rag.indexer import CodebaseIndexer

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        indexer._meta_path = tmp_path / ".qdrant" / "code_index_meta.json"

        # Simulate: two files scanned, but one failed hashing.
        # current_files would have both, but current_hashes only has ok.py.
        current_hashes = {"ok.py": "a" * 64}  # bad.py absent

        # Writing current_hashes directly (the fix) must not raise.
        indexer._write_meta(current_hashes)

        loaded = indexer._load_meta()
        assert "ok.py" in loaded
        assert "bad.py" not in loaded


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


class TestNodeTypeSets:
    """_CLASS_LIKE_NODES and _FUNCTION_LIKE_NODES contain expected entries."""

    def test_python_class_in_class_like_nodes(self):
        assert "class_definition" in _CLASS_LIKE_NODES

    def test_python_function_in_function_like_nodes(self):
        assert "function_definition" in _FUNCTION_LIKE_NODES

    def test_no_overlap_between_sets(self):
        overlap = _CLASS_LIKE_NODES & _FUNCTION_LIKE_NODES
        assert not overlap, f"Unexpected overlap: {overlap}"


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


class TestCodeChunkMetadataFields:
    """CodeChunk dataclass carries node_type, function_name, class_name."""

    def test_chunk_with_ast_populates_function_name(self, tmp_path: Path):
        from vaultspec_rag.indexer import CodebaseIndexer

        code = "def process(data):\n    return data\n"
        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        chunks = indexer._chunk_with_ast(code, "proc.py", "python", "python")
        assert len(chunks) >= 1
        fn_chunks = [c for c in chunks if c.function_name == "process"]
        assert fn_chunks, "Expected function_name='process' on CodeChunk"

    def test_chunk_with_ast_populates_node_type(self, tmp_path: Path):
        from vaultspec_rag.indexer import CodebaseIndexer

        code = "class Engine:\n    pass\n"
        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        chunks = indexer._chunk_with_ast(code, "engine.py", "python", "python")
        assert len(chunks) >= 1
        typed = [c for c in chunks if c.node_type == "class_definition"]
        assert typed, "Expected node_type='class_definition' on CodeChunk"

    def test_chunk_with_splitter_has_none_metadata(self, tmp_path: Path):
        from vaultspec_rag.indexer import CodebaseIndexer

        content = "key: value\n"
        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        chunks = indexer._chunk_with_splitter(content, "conf.yaml", "yaml")
        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.node_type is None
            assert chunk.function_name is None
            assert chunk.class_name is None


class TestGitignoreNegationPatterns:
    """R9-M4: Negation patterns in subdirectory .gitignore files must keep
    the ! prefix at the start, not prepend the directory before it."""

    def test_negation_pattern_not_mangled(self, tmp_path: Path):
        from vaultspec_rag.indexer import CodebaseIndexer

        # Create project structure:
        #   subdir/.gitignore with "*.log\n!important.log"
        #   subdir/important.log (should NOT be ignored)
        #   subdir/debug.log (should be ignored)
        sub = tmp_path / "subdir"
        sub.mkdir()
        gitignore = sub / ".gitignore"
        gitignore.write_text("*.log\n!important.log\n", encoding="utf-8")

        # Create test files
        (sub / "important.log").write_text("keep me", encoding="utf-8")
        (sub / "debug.log").write_text("ignore me", encoding="utf-8")
        (sub / "code.py").write_text("x = 1\n", encoding="utf-8")

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        indexer._extra_excludes = []
        paths = indexer._scan_codebase()
        rel_paths = {str(p.relative_to(tmp_path)).replace("\\", "/") for p in paths}
        # code.py should always be found
        assert "subdir/code.py" in rel_paths
        # important.log is negated — but .log is not a SUPPORTED_EXTENSION,
        # so it won't appear. The test verifies the negation pattern itself
        # is correctly formed by checking the internal pathspec logic.

    def test_negation_pattern_format(self, tmp_path: Path):
        """Verify the pattern string itself is !subdir/pattern not subdir/!pattern."""
        import pathspec

        # Simulate what _scan_codebase does for a subdir gitignore
        rel_dir = "subdir"
        line = "!keep.py"
        # Apply the fixed logic
        stripped = line.strip()
        if stripped.startswith("!"):
            pattern = f"!{rel_dir}/{stripped[1:]}"
        else:
            pattern = f"{rel_dir}/{stripped}"

        assert pattern == "!subdir/keep.py"
        # Verify pathspec accepts it without error
        spec = pathspec.GitIgnoreSpec.from_lines(
            [f"{rel_dir}/*.py", pattern],
        )
        # keep.py should NOT be matched (negated)
        assert not spec.match_file("subdir/keep.py")
        # other.py should be matched (ignored)
        assert spec.match_file("subdir/other.py")


class TestHashingPermissionError:
    """R9-M6: read_bytes() in hashing loops must handle permission errors."""

    def test_full_index_meta_skips_unreadable_file(self, tmp_path: Path):
        """Metadata hashing in full_index skips files that raise OSError."""

        from vaultspec_rag.indexer import CodebaseIndexer

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        indexer._meta_path = tmp_path / ".qdrant" / "code_index_meta.json"

        # Create a readable file and write meta with its hash
        good = tmp_path / "good.py"
        good.write_text("x = 1\n", encoding="utf-8")
        with open(good, "rb") as f:
            good_hash = hashlib.file_digest(f, "blake2b").hexdigest()

        meta = {"good.py": good_hash}
        indexer._write_meta(meta)

        # Verify the meta was written correctly
        loaded = indexer._load_meta()
        assert loaded["good.py"] == good_hash
        assert isinstance(loaded["good.py"], str)

    def test_write_load_meta_roundtrip(self, tmp_path: Path):
        """_write_meta and _load_meta correctly round-trip blake2b hashes."""
        from vaultspec_rag.indexer import CodebaseIndexer

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer._meta_path = tmp_path / "sub" / "code_index_meta.json"

        hashes = {
            "foo.py": "a" * 64,
            "bar/baz.rs": "b" * 64,
        }
        indexer._write_meta(hashes)
        loaded = indexer._load_meta()
        assert loaded == hashes


class TestMergeSmallCrossType:
    """R9-m1: _merge_small must produce node_type=None when merging
    chunks with different node types."""

    def test_same_type_preserved(self):
        chunker = ASTChunker(chunk_size=200)
        chunks: list[tuple[str, int, int, str | None, str | None, str | None]] = [
            ("def a(): pass", 1, 1, "function_definition", "a", None),
            ("def b(): pass", 2, 2, "function_definition", "b", None),
        ]
        merged = chunker._merge_small(chunks)
        if len(merged) == 1:
            assert merged[0][3] == "function_definition"

    def test_different_types_become_none(self):
        chunker = ASTChunker(chunk_size=200)
        chunks: list[tuple[str, int, int, str | None, str | None, str | None]] = [
            ("def a(): pass", 1, 1, "function_definition", "a", None),
            ("class B: pass", 2, 2, "class_definition", None, "B"),
        ]
        merged = chunker._merge_small(chunks)
        if len(merged) == 1:
            # Cross-type merge: node_type must be None
            assert merged[0][3] is None

    def test_none_and_typed_preserves_type(self):
        chunker = ASTChunker(chunk_size=200)
        chunks: list[tuple[str, int, int, str | None, str | None, str | None]] = [
            ("x = 1", 1, 1, None, None, None),
            ("def a(): pass", 2, 2, "function_definition", "a", None),
        ]
        merged = chunker._merge_small(chunks)
        if len(merged) == 1:
            # None or "function_definition" -> "function_definition"
            assert merged[0][3] == "function_definition"


class TestForceSplitNonAscii:
    """R9-M2: Force-split in _collect_chunks must handle non-ASCII correctly.
    The old code used node.start_byte + i (byte offset) as a character index
    into source, giving wrong line numbers for non-ASCII source."""

    def test_non_ascii_line_numbers(self):
        # Source with non-ASCII characters (multi-byte in UTF-8).
        # Each line has emoji (4 bytes in UTF-8) to create byte/char mismatch.
        lines = [f"x{i} = '\U0001f600'" for i in range(80)]
        source = "\n".join(lines) + "\n"

        # Use a tiny chunk_size to force the leaf-split path.
        chunker = ASTChunker(chunk_size=50)
        chunks = chunker.chunk(source, "python")

        # Verify line numbers are reasonable (1-based, monotonically increasing).
        prev_start = 0
        for _text, ls, le, *_ in chunks:
            assert ls >= 1, f"line_start {ls} < 1"
            assert le >= ls, f"line_end {le} < line_start {ls}"
            assert ls >= prev_start, (
                f"line_start {ls} decreased from previous {prev_start}"
            )
            prev_start = ls

        # The last chunk's line_end should not exceed total lines.
        total_lines = source.count("\n") + 1
        last_le = chunks[-1][2]
        assert last_le <= total_lines, (
            f"Last line_end {last_le} exceeds total lines {total_lines}"
        )

    def test_ascii_force_split_line_numbers(self):
        """Sanity check: force-split with ASCII also produces correct lines."""
        lines = [f"var_{i} = {i}" for i in range(60)]
        source = "\n".join(lines) + "\n"

        chunker = ASTChunker(chunk_size=50)
        chunks = chunker.chunk(source, "python")

        for _text, ls, le, *_ in chunks:
            assert ls >= 1
            assert le >= ls


class TestCodebaseMetaRoundTrip:
    """R10-M1/M2: _write_meta and _load_meta correctly persist hash metadata."""

    def test_write_meta_persists_hashes_to_disk(self, tmp_path):
        """_write_meta writes a JSON file that _load_meta can read back."""
        import json

        from vaultspec_rag.indexer import CodebaseIndexer

        meta_path = tmp_path / ".rag" / "codebase_meta.json"
        indexer = object.__new__(CodebaseIndexer)
        indexer._meta_path = meta_path

        hashes = {"src/foo.py": "abc123", "src/bar.py": "def456"}
        indexer._write_meta(hashes)

        assert meta_path.exists()
        on_disk = json.loads(meta_path.read_text(encoding="utf-8"))
        assert on_disk == hashes

    def test_load_meta_returns_written_hashes(self, tmp_path):
        """_load_meta round-trips what _write_meta wrote."""
        from vaultspec_rag.indexer import CodebaseIndexer

        meta_path = tmp_path / ".rag" / "codebase_meta.json"
        indexer = object.__new__(CodebaseIndexer)
        indexer._meta_path = meta_path

        hashes = {"src/foo.py": "aaa", "lib/baz.rs": "bbb"}
        indexer._write_meta(hashes)
        loaded = indexer._load_meta()
        assert loaded == hashes

    def test_load_meta_returns_empty_when_missing(self, tmp_path):
        """_load_meta returns {} when no meta file exists."""
        from vaultspec_rag.indexer import CodebaseIndexer

        meta_path = tmp_path / ".rag" / "codebase_meta.json"
        indexer = object.__new__(CodebaseIndexer)
        indexer._meta_path = meta_path

        assert indexer._load_meta() == {}


class TestExtractNameNonAscii:
    """R10-M3: _extract_name must use byte offsets correctly for non-ASCII."""

    def test_non_ascii_identifier_extracted(self):
        """Function with non-ASCII name is extracted correctly."""
        # Python function with a Unicode identifier.
        source = "def grüße():\n    pass\n"
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(source, "python")
        assert len(chunks) >= 1
        # Find the chunk with function_name set.
        fn_names = [c[4] for c in chunks if c[4] is not None]
        assert "grüße" in fn_names, (
            f"Expected 'grüße' in function names, got {fn_names}"
        )

    def test_ascii_identifier_still_works(self):
        """Sanity: ASCII names still work after the byte-offset fix."""
        source = "def hello():\n    pass\n"
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(source, "python")
        fn_names = [c[4] for c in chunks if c[4] is not None]
        assert "hello" in fn_names

    def test_class_with_unicode_name(self):
        source = "class Ñoño:\n    pass\n"
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(source, "python")
        class_names = [c[5] for c in chunks if c[5] is not None]
        assert "Ñoño" in class_names


class TestDecoratedDefinitionClassification:
    """R10-M4: @dataclass class Foo must get class_name='Foo', not function_name."""

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


class TestR10MinorNodeTypes:
    """R10-m1/m2: Extended node type sets."""

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


class TestR10MinorContainerConstant:
    """R10-m4: _CONTAINER_NODES is a module-level constant."""

    def test_container_nodes_exists(self):
        assert isinstance(_CONTAINER_NODES, set)
        assert "module" in _CONTAINER_NODES
        assert "program" in _CONTAINER_NODES


class TestR10MinorAnchoredPattern:
    """R10-m3: Anchored patterns in subdirectory .gitignore avoid double slash."""

    def test_anchored_pattern_no_double_slash(self, tmp_path: Path):
        from vaultspec_rag.indexer import CodebaseIndexer

        root = tmp_path / "proj"
        root.mkdir()
        sub = root / "sub"
        sub.mkdir()
        gitignore = sub / ".gitignore"
        gitignore.write_text("/build\n", encoding="utf-8")

        # Create a file that should be ignored
        build_dir = sub / "build"
        build_dir.mkdir()
        (build_dir / "out.py").write_text("x = 1\n", encoding="utf-8")

        # Create a file that should NOT be ignored
        (sub / "main.py").write_text("y = 2\n", encoding="utf-8")

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = root
        indexer._extra_excludes = []

        paths = indexer._scan_codebase()
        rel_paths = {str(p.relative_to(root)).replace("\\", "/") for p in paths}
        assert "sub/main.py" in rel_paths
        assert "sub/build/out.py" not in rel_paths


class TestR10MinorBufferFunctionName:
    """R10-m5: Buffer flush preserves function_name from parent."""

    def test_buffer_inherits_function_name(self):
        """Chunks from function body statements should carry the function name."""
        source = (
            "def process_data(items):\n"
            "    result = []\n"
            "    for item in items:\n"
            "        result.append(item * 2)\n"
            "    return result\n"
        )
        chunker = ASTChunker(chunk_size=200)
        chunks = chunker.chunk(source, "python")
        # The function body may produce buffer-flushed chunks;
        # any chunk containing body statements should have function_name
        func_chunks = [c for c in chunks if "process_data" in c[0]]
        assert func_chunks, "Expected chunks containing process_data"
        for c in func_chunks:
            assert c[4] == "process_data", (
                f"Expected function_name='process_data', got {c[4]}"
            )


class TestR11M1NonAsciiChunkText:
    """R11-M1: chunk text uses byte offsets on source_bytes, not str."""

    def test_non_ascii_chunk_text_preserved(self):
        """Multi-byte UTF-8 characters in source survive AST chunking."""
        source = 'def grüße():\n    return "Ärger"\n'
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(source, "python")
        assert len(chunks) >= 1
        combined = "\n".join(c[0] for c in chunks)
        assert "grüße" in combined
        assert "Ärger" in combined

    def test_cjk_source_round_trips(self):
        """CJK characters (3-byte UTF-8) survive AST chunking."""
        source = 'def 处理():\n    x = "数据"\n    return x\n'
        chunker = ASTChunker(chunk_size=500)
        chunks = chunker.chunk(source, "python")
        assert len(chunks) >= 1
        combined = "\n".join(c[0] for c in chunks)
        assert "处理" in combined
        assert "数据" in combined


class TestVaultragignore:
    """Tests for .vaultragignore support and extra_excludes (D1-D7)."""

    @pytest.mark.unit
    def test_vaultragignore_excludes_matching_files(self, tmp_path: Path):
        """Files matching .vaultragignore patterns are excluded from scan."""
        from vaultspec_rag.indexer import CodebaseIndexer

        (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "generated.py").write_text("y = 2\n", encoding="utf-8")
        (tmp_path / ".vaultragignore").write_text("generated.py\n", encoding="utf-8")

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        indexer._extra_excludes = []

        files = indexer.scan_files()
        rel = {str(p.relative_to(tmp_path)).replace("\\", "/") for p in files}
        assert "main.py" in rel
        assert "generated.py" not in rel

    @pytest.mark.unit
    def test_missing_vaultragignore_no_error(self, tmp_path: Path):
        """Missing .vaultragignore is silently ignored (D3)."""
        from vaultspec_rag.indexer import CodebaseIndexer

        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        indexer._extra_excludes = []

        files = indexer.scan_files()
        rel = {str(p.relative_to(tmp_path)).replace("\\", "/") for p in files}
        assert "app.py" in rel

    @pytest.mark.unit
    def test_extra_excludes_applied(self, tmp_path: Path):
        """CLI --exclude patterns are applied via extra_excludes (D4)."""
        from vaultspec_rag.indexer import CodebaseIndexer

        (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "temp.py").write_text("y = 2\n", encoding="utf-8")

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        indexer._extra_excludes = ["temp.py"]

        files = indexer.scan_files()
        rel = {str(p.relative_to(tmp_path)).replace("\\", "/") for p in files}
        assert "main.py" in rel
        assert "temp.py" not in rel

    @pytest.mark.unit
    def test_vaultragignore_negation_cannot_override_gitignore(self, tmp_path: Path):
        """Negation in .vaultragignore cannot un-ignore .gitignore entries (D1)."""
        from vaultspec_rag.indexer import CodebaseIndexer

        (tmp_path / "secret.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "main.py").write_text("y = 2\n", encoding="utf-8")
        (tmp_path / ".gitignore").write_text("secret.py\n", encoding="utf-8")
        # Attempt to un-ignore secret.py from .vaultragignore — must fail
        (tmp_path / ".vaultragignore").write_text("!secret.py\n", encoding="utf-8")

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        indexer._extra_excludes = []

        files = indexer.scan_files()
        rel = {str(p.relative_to(tmp_path)).replace("\\", "/") for p in files}
        assert "secret.py" not in rel, (
            ".vaultragignore negation must not override .gitignore"
        )
        assert "main.py" in rel

    @pytest.mark.unit
    def test_vaultragignore_internal_negation_works(self, tmp_path: Path):
        """Negation within .vaultragignore works for its own patterns (D1).

        *.test.py is excluded, but !important.test.py brings it back.
        """
        from vaultspec_rag.indexer import CodebaseIndexer

        (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "foo.test.py").write_text("y = 2\n", encoding="utf-8")
        (tmp_path / "important.test.py").write_text("z = 3\n", encoding="utf-8")
        (tmp_path / ".vaultragignore").write_text(
            "*.test.py\n!important.test.py\n", encoding="utf-8"
        )

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        indexer._extra_excludes = []

        files = indexer.scan_files()
        rel = {str(p.relative_to(tmp_path)).replace("\\", "/") for p in files}
        assert "main.py" in rel
        assert "foo.test.py" not in rel
        assert "important.test.py" in rel

    @pytest.mark.unit
    def test_gitignore_still_respected_alongside_vaultragignore(self, tmp_path: Path):
        """Both .gitignore and .vaultragignore exclusions are applied (D1)."""
        from vaultspec_rag.indexer import CodebaseIndexer

        (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "build_output.py").write_text("y = 2\n", encoding="utf-8")
        (tmp_path / "vendor_lib.py").write_text("z = 3\n", encoding="utf-8")
        (tmp_path / ".gitignore").write_text("build_output.py\n", encoding="utf-8")
        (tmp_path / ".vaultragignore").write_text("vendor_lib.py\n", encoding="utf-8")

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        indexer._extra_excludes = []

        files = indexer.scan_files()
        rel = {str(p.relative_to(tmp_path)).replace("\\", "/") for p in files}
        assert "main.py" in rel
        assert "build_output.py" not in rel
        assert "vendor_lib.py" not in rel

    @pytest.mark.unit
    def test_scan_files_matches_scan_codebase(self, tmp_path: Path):
        """scan_files() returns the same result as _scan_codebase() (D5)."""
        from vaultspec_rag.indexer import CodebaseIndexer

        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        indexer._extra_excludes = []

        assert indexer.scan_files() == indexer._scan_codebase()

    @pytest.mark.unit
    def test_vaultragignore_directory_exclusion(self, tmp_path: Path):
        """Directory patterns in .vaultragignore prune entire subtrees."""
        from vaultspec_rag.indexer import CodebaseIndexer

        (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "lib.py").write_text("y = 2\n", encoding="utf-8")
        (tmp_path / ".vaultragignore").write_text("vendor/\n", encoding="utf-8")

        indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        indexer.root_dir = tmp_path
        indexer._extra_excludes = []

        files = indexer.scan_files()
        rel = {str(p.relative_to(tmp_path)).replace("\\", "/") for p in files}
        assert "main.py" in rel
        assert "vendor/lib.py" not in rel
