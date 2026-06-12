"""Unit tests for vault document chunking, grouping, and graph nudges."""

from typing import ClassVar

import pytest

from ..indexer._vault_prep import split_document
from ..search._models import SearchResult
from ..search._rerank import (
    _FEATURE_NEIGHBOR_NUDGE,
    _IN_LINK_NUDGE_CAP,
    _IN_LINK_NUDGE_STEP,
    rerank_with_graph,
)
from ..search._searcher import _group_chunks_by_document
from ..store import VaultDocument


def _doc(content: str, doc_id: str = "adr/sample") -> VaultDocument:
    return VaultDocument(
        id=doc_id,
        path=f"{doc_id}.md",
        doc_type="adr",
        feature="sample-feature",
        date="2026-06-12",
        tags=["#adr", "#sample-feature"],
        related=[],
        title="Sample Doc",
        content=content,
    )


def _result(doc_id: str, score: float) -> SearchResult:
    return SearchResult(
        id=doc_id,
        path=f"{doc_id}.md",
        title=doc_id,
        score=score,
        snippet="snippet",
        source="vault",
    )


class TestSplitDocument:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_long_document_yields_multiple_chunks(self):
        sections = [
            f"## Section {i}\n\n" + (f"sentence {i} body text. " * 40) for i in range(8)
        ]
        doc = _doc("\n\n".join(sections))
        chunks = split_document(doc, chunk_chars=1000)
        assert len(chunks) > 1
        assert all(len(c.text) <= 1000 for c in chunks)

    def test_ordinals_and_chunk_count_are_consistent(self):
        doc = _doc("## A\n\n" + "x " * 900 + "\n\n## B\n\n" + "y " * 900)
        chunks = split_document(doc, chunk_chars=800)
        assert [c.ordinal for c in chunks] == list(range(len(chunks)))
        assert all(c.chunk_count == len(chunks) for c in chunks)

    def test_head_chunk_carries_full_body(self):
        body = "## A\n\n" + "alpha " * 400 + "\n\n## B\n\n" + "beta " * 400
        doc = _doc(body)
        chunks = split_document(doc, chunk_chars=900)
        assert chunks[0].doc_content == body
        assert all(c.doc_content is None for c in chunks[1:])

    def test_small_document_yields_single_chunk(self):
        doc = _doc("just a short note")
        chunks = split_document(doc, chunk_chars=3000)
        assert len(chunks) == 1
        assert chunks[0].text == "just a short note"
        assert chunks[0].doc_content == "just a short note"

    def test_empty_document_still_yields_one_chunk(self):
        doc = _doc("")
        chunks = split_document(doc, chunk_chars=3000)
        assert len(chunks) == 1
        assert chunks[0].ordinal == 0

    def test_metadata_flattened_onto_every_chunk(self):
        doc = _doc("## A\n\n" + "z " * 900 + "\n\n## B\n\n" + "w " * 900)
        for chunk in split_document(doc, chunk_chars=800):
            assert chunk.doc_id == doc.id
            assert chunk.doc_type == doc.doc_type
            assert chunk.feature == doc.feature
            assert chunk.tags == doc.tags
            assert chunk.title == doc.title

    def test_point_key_is_ordinal_scoped(self):
        doc = _doc("## A\n\n" + "q " * 900 + "\n\n## B\n\n" + "r " * 900)
        chunks = split_document(doc, chunk_chars=800)
        keys = {c.point_key for c in chunks}
        assert len(keys) == len(chunks)
        assert all(k.startswith("adr/sample#c") for k in keys)


class TestGroupChunksByDocument:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_best_chunk_represents_its_document(self):
        results = [
            _result("adr/a", 0.4),
            _result("adr/a", 0.9),
            _result("adr/b", 0.7),
            _result("adr/a", 0.1),
        ]
        grouped = _group_chunks_by_document(results)
        assert [r.id for r in grouped] == ["adr/a", "adr/b"]
        assert grouped[0].score == 0.9

    def test_unique_documents_pass_through_sorted(self):
        results = [_result("adr/a", 0.2), _result("adr/b", 0.8)]
        grouped = _group_chunks_by_document(results)
        assert [r.id for r in grouped] == ["adr/b", "adr/a"]

    def test_empty_input(self):
        assert _group_chunks_by_document([]) == []


class TestBoundedGraphNudge:
    pytestmark: ClassVar = [pytest.mark.unit]

    def _build_vault(self, root) -> None:
        adr_dir = root / ".vault" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "target.md").write_text(
            "---\ntags:\n  - '#adr'\n  - '#sample'\ndate: 2026-06-12\n---\n\n"
            "# Target\n\nbody\n",
            encoding="utf-8",
        )
        (adr_dir / "pointer.md").write_text(
            "---\ntags:\n  - '#adr'\n  - '#sample'\ndate: 2026-06-12\n"
            "related:\n  - '[[target]]'\n---\n\n# Pointer\n\nbody\n",
            encoding="utf-8",
        )

    def test_nudge_is_additive_and_bounded(self, tmp_path):
        from vaultspec_core.graph import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
            VaultGraph,
        )

        from ..search._models import ParsedQuery

        self._build_vault(tmp_path)
        graph = VaultGraph(tmp_path)
        assert graph.nodes, "synthetic vault produced no graph nodes"

        max_nudge = _IN_LINK_NUDGE_STEP * _IN_LINK_NUDGE_CAP + _FEATURE_NEIGHBOR_NUDGE
        base_score = 0.5
        results = [_result(node_id, base_score) for node_id in graph.nodes]
        reranked = rerank_with_graph(
            results,
            tmp_path,
            ParsedQuery(text="q", filters={"feature": "sample"}),
            graph=graph,
        )
        assert reranked
        for r in reranked:
            assert base_score <= r.score <= base_score + max_nudge + 1e-9

        nudged = [r for r in reranked if r.score > base_score]
        assert nudged, "expected at least one in-linked node to receive a nudge"

    def test_in_link_nudge_caps_at_one_rank_gap(self):
        from ..search._postprocess import PREFER_SCORE_NUDGE

        assert _IN_LINK_NUDGE_STEP * _IN_LINK_NUDGE_CAP <= PREFER_SCORE_NUDGE
