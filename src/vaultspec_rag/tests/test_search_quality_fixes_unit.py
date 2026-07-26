"""Unit tests for the search-quality backlog fixes.

Three independent fixes surfaced by the server-mode quality audit:
- vault result paths are project-root-relative (carry the docs prefix);
- merging two small chunks never cross-pairs a class tail's class_name
  with an adjacent module-level function's function_name;
"""

from typing import ClassVar

import pytest

from ..indexer._ast_chunker import ASTChunker
from ..search._searcher import _join_doc_path

Chunk = tuple[str, int, int, str | None, str | None, str | None]


class TestVaultDocPath:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_prepends_docs_prefix(self):
        assert _join_doc_path(".vault", "research/foo.md") == ".vault/research/foo.md"

    def test_idempotent_when_prefix_present(self):
        assert (
            _join_doc_path(".vault", ".vault/research/foo.md")
            == ".vault/research/foo.md"
        )

    def test_normalises_backslashes(self):
        assert _join_doc_path(".vault", "research\\foo.md") == ".vault/research/foo.md"

    def test_empty_prefix_passes_through(self):
        assert _join_doc_path("", "research/foo.md") == "research/foo.md"

    def test_result_still_ends_with_extension(self):
        assert _join_doc_path(".vault", "adr/x.md").endswith(".md")


class TestMergeKeepsIdentityCoherent:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_class_tail_does_not_adopt_sibling_function(self):
        # A class-tail chunk (class set, no function) merged with an
        # adjacent module-level function chunk must NOT emerge claiming
        # that function as a method of the class.
        chunker = ASTChunker(chunk_size=200)
        chunks: list[Chunk] = [
            ("class Foo: pass", 1, 1, "class_definition", None, "Foo"),
            ("def helper(): pass", 2, 2, "function_definition", "helper", None),
        ]
        merged = chunker._merge_small(chunks)
        assert len(merged) == 1
        _text, _ls, _le, _nt, fn, cls = merged[0]
        assert cls == "Foo"
        assert fn is None, "class tail must not adopt the sibling function as a method"

    def test_real_method_pair_survives(self):
        # A genuine method chunk (both names from one source) keeps both.
        chunker = ASTChunker(chunk_size=200)
        chunks: list[Chunk] = [
            ("def m(self): pass", 1, 1, "function_definition", "m", "Bar"),
            ("x = 1", 2, 2, None, None, None),
        ]
        merged = chunker._merge_small(chunks)
        assert len(merged) == 1
        _text, _ls, _le, _nt, fn, cls = merged[0]
        assert (fn, cls) == ("m", "Bar")

    def test_structureless_prev_takes_chunk_identity(self):
        chunker = ASTChunker(chunk_size=200)
        chunks: list[Chunk] = [
            ("# comment", 1, 1, None, None, None),
            ("def g(): pass", 2, 2, "function_definition", "g", None),
        ]
        merged = chunker._merge_small(chunks)
        assert len(merged) == 1
        _text, _ls, _le, _nt, fn, cls = merged[0]
        assert (fn, cls) == ("g", None)

