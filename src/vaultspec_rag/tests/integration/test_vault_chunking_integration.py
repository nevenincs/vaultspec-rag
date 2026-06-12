"""GPU integration tests for chunked vault indexing and grouped search.

Verifies the one-point-per-chunk vault layout end to end with real
embeddings and a real Qdrant store: long-document tails are retrievable,
retrieval-by-id stays byte-exact, deletes remove every chunk, the
doc-level listing stays one row per document, and a store written under
the old one-point-per-document layout triggers a one-time rebuild.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, ClassVar

import pytest

from ...progress import NullProgressReporter
from ..corpus import build_synthetic_vault

if TYPE_CHECKING:
    from pathlib import Path

    from ... import VaultIndexer, VaultStore
    from ...embeddings import EmbeddingModel

#: A needle phrase placed deep past the old 8000-char embed horizon.
_TAIL_NEEDLE = "the heliotrope calibration winch requires manual lubrication"

_FILLER_SENTENCE = (
    "This section restates routine operational guidance in deliberately "
    "unremarkable prose so the document grows long without adding any "
    "distinctive vocabulary. "
)


def _write_long_doc(root: Path) -> str:
    """Write a >12000-char doc whose unique needle sits in the tail."""
    sections = [
        f"## Operations volume {i}\n\n" + _FILLER_SENTENCE * 30 for i in range(6)
    ]
    body = "\n\n".join(sections)
    assert len(body) > 12000
    body += f"\n\n## Maintenance appendix\n\n{_TAIL_NEEDLE}.\n"
    doc_path = root / ".vault" / "research" / "long-operations-manual.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(
        "---\ntags:\n  - '#research'\n  - '#operations'\ndate: 2026-06-12\n---\n\n"
        "# Long Operations Manual\n\n" + body,
        encoding="utf-8",
    )
    return "research/long-operations-manual"


def _build_indexed_root(
    root: Path,
    model: EmbeddingModel,
) -> tuple[VaultStore, VaultIndexer, str]:
    from ... import VaultIndexer, VaultStore

    build_synthetic_vault(root, n_docs=4, seed=77)
    long_doc_id = _write_long_doc(root)
    store = VaultStore(root)
    indexer = VaultIndexer(root, model, store)
    indexer.full_index(reporter=NullProgressReporter())
    return store, indexer, long_doc_id


@pytest.fixture(scope="module")
def chunked_corpus(
    embedding_model: EmbeddingModel,
    tmp_path_factory: pytest.TempPathFactory,
):
    root = tmp_path_factory.mktemp("chunked-vault")
    store, indexer, long_doc_id = _build_indexed_root(root, embedding_model)
    yield {
        "root": root,
        "store": store,
        "indexer": indexer,
        "long_doc_id": long_doc_id,
        "model": embedding_model,
    }
    store.close()


class TestChunkedVaultLayout:
    pytestmark: ClassVar = [pytest.mark.integration]

    def test_long_document_expands_to_multiple_points(self, chunked_corpus):
        store = chunked_corpus["store"]
        doc_ids = store.get_all_ids()
        assert chunked_corpus["long_doc_id"] in doc_ids
        assert store.count() > len(doc_ids)

    def test_tail_content_is_retrievable(self, chunked_corpus):
        from ...search import VaultSearcher

        searcher = VaultSearcher(
            chunked_corpus["root"],
            chunked_corpus["model"],
            chunked_corpus["store"],
        )
        results = searcher.search_vault(
            "heliotrope calibration winch lubrication",
            top_k=5,
        )
        assert results, "tail needle query returned nothing"
        top_ids = [r.id for r in results]
        assert chunked_corpus["long_doc_id"] in top_ids
        hit = next(r for r in results if r.id == chunked_corpus["long_doc_id"])
        assert "heliotrope" in (hit.rerank_text or hit.snippet)

    def test_results_are_grouped_one_row_per_document(self, chunked_corpus):
        from ...search import VaultSearcher

        searcher = VaultSearcher(
            chunked_corpus["root"],
            chunked_corpus["model"],
            chunked_corpus["store"],
        )
        results = searcher.search_vault(
            "routine operational guidance restated",
            top_k=10,
        )
        ids = [r.id for r in results]
        assert len(ids) == len(set(ids)), f"duplicate documents in results: {ids}"

    def test_get_by_id_returns_exact_full_body(self, chunked_corpus):
        store = chunked_corpus["store"]
        root = chunked_corpus["root"]
        doc_id = chunked_corpus["long_doc_id"]
        payload = store.get_by_id(doc_id)
        assert payload is not None
        raw = (root / ".vault" / f"{doc_id}.md").read_text(encoding="utf-8")
        body = raw.split("---", 2)[2].strip()
        assert payload["content"] == body
        assert _TAIL_NEEDLE in payload["content"]

    def test_list_all_documents_one_row_per_document(self, chunked_corpus):
        store = chunked_corpus["store"]
        docs = store.list_all_documents()
        ids = [d["id"] for d in docs]
        assert len(ids) == len(set(ids))
        assert set(ids) == store.get_all_ids()
        long_doc = next(d for d in docs if d["id"] == chunked_corpus["long_doc_id"])
        assert _TAIL_NEEDLE in long_doc["content"]


class TestChunkedVaultLifecycle:
    pytestmark: ClassVar = [pytest.mark.integration]

    def test_delete_removes_every_chunk(self, embedding_model, tmp_path):
        store, indexer, long_doc_id = _build_indexed_root(tmp_path, embedding_model)
        try:
            count_before = store.count()
            (tmp_path / ".vault" / f"{long_doc_id}.md").unlink()
            result = indexer.incremental_index(reporter=NullProgressReporter())
            assert result.removed == 1
            assert long_doc_id not in store.get_all_ids()
            # Every chunk of the long doc is gone, not just its head.
            assert store.count() < count_before - 1
        finally:
            store.close()

    def test_shrunk_document_purges_stale_tail_chunks(self, embedding_model, tmp_path):
        store, indexer, long_doc_id = _build_indexed_root(tmp_path, embedding_model)
        try:
            counts_before = store.get_chunk_counts()
            assert counts_before[long_doc_id] > 1
            doc_path = tmp_path / ".vault" / f"{long_doc_id}.md"
            doc_path.write_text(
                "---\ntags:\n  - '#research'\n  - '#operations'\n"
                "date: 2026-06-12\n---\n\n# Long Operations Manual\n\n"
                "Now a short stub.\n",
                encoding="utf-8",
            )
            indexer.incremental_index(reporter=NullProgressReporter())
            counts_after = store.get_chunk_counts()
            assert counts_after[long_doc_id] == 1
            payload = store.get_by_id(long_doc_id)
            assert payload is not None
            assert _TAIL_NEEDLE not in payload["content"]
        finally:
            store.close()

    def test_old_point_layout_triggers_rebuild(self, embedding_model, tmp_path):
        from ...config import get_config

        store, indexer, _ = _build_indexed_root(tmp_path, embedding_model)
        try:
            doc_total = len(store.get_all_ids())
            # Rewrite the metadata sidecar without the layout marker,
            # reproducing the on-disk state of an install that indexed
            # before chunking existed.
            cfg = get_config()
            meta_path = tmp_path / cfg.data_dir / cfg.index_metadata_file
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta.pop("__vault_point_schema__")
            meta_path.write_text(json.dumps(meta), encoding="utf-8")

            result = indexer.incremental_index(reporter=NullProgressReporter())
            # A layout rebuild re-adds every document instead of
            # reporting a no-op incremental pass.
            assert result.added == doc_total
            stamped = json.loads(meta_path.read_text(encoding="utf-8"))
            assert stamped["__vault_point_schema__"] == "2"
        finally:
            store.close()
