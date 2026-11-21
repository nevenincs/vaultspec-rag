"""Integration tests for VaultStore: CRUD and hybrid search.

Tests updated for Qdrant-backed store (replacing LanceDB).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from ..._store_search import HybridSearchRequest
from .._store_fixtures import get_all_ids

if TYPE_CHECKING:
    from pathlib import Path

    from ..conftest import RagComponentsWithManifest

pytestmark = [pytest.mark.integration]


# ---- Store Tests ----


class TestVaultStore:
    """Tests for the Qdrant store with actual data."""

    def test_store_has_documents(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        store = rag_components["store"]
        count = store.count()
        assert count > 0, "Store should have documents after indexing"

    def test_get_all_ids(self, rag_components: RagComponentsWithManifest) -> None:
        store = rag_components["store"]
        ids = get_all_ids(store)
        assert len(ids) > 0
        # All ids should be strings
        for doc_id in ids:
            assert isinstance(doc_id, str)
            assert len(doc_id) > 0

    def test_vault_store_context_manager(self, tmp_path: Path) -> None:
        """VaultStore should support the context manager protocol."""
        from ...store_runtime import VaultStore

        with VaultStore(tmp_path) as store:
            assert store._client is not None
            store.ensure_table()
        # After exiting context, client should be released
        assert store._client is None

    def test_vault_store_locked_raises_typed_exception(self, tmp_path: Path) -> None:
        """Opening the same Qdrant storage twice must raise VaultStoreLockedError."""
        from ..._store_locks import VaultStoreLockedError
        from ...store_runtime import VaultStore

        first = VaultStore(tmp_path)
        try:
            with pytest.raises(VaultStoreLockedError) as excinfo:
                VaultStore(tmp_path)
            assert str(first.db_path) == excinfo.value.db_path
            # Both stores live in this process and the OS lock is per open
            # handle, so the refusal must name this process rather than blame
            # a second one that was never involved.
            assert excinfo.value.held_in_process is True
            assert "already open in this process" in str(excinfo.value)
        finally:
            first.close()

    def test_hybrid_search_returns_results(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        model = rag_components["model"]
        store = rag_components["store"]

        query_vec = model.encode_query("architecture decision")
        results = store.hybrid_search(
            HybridSearchRequest(
                query_vector=query_vec.tolist(),
                query_text="architecture decision",
                limit=5,
            )
        )
        assert len(results) > 0
        # Each result should have an id and path
        for r in results:
            assert "id" in r
            assert "path" in r

    def test_delete_documents_removes_from_store(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        """R26-M3: delete_documents removes a doc so it's no longer searchable."""
        store = rag_components["store"]
        model = rag_components["model"]

        # Pick an existing doc ID
        all_ids = get_all_ids(store)
        assert len(all_ids) > 0
        target_id = next(iter(all_ids))

        # Verify it's searchable before deletion
        doc = store.get_by_id(target_id)
        assert doc is not None

        count_before = store.count()
        store.delete_documents([target_id])

        # Verify it's gone
        assert store.get_by_id(target_id) is None
        assert store.count() == count_before - 1

        # Re-insert it so other tests aren't affected (session-scoped fixture).
        # The count fell by exactly one, so the document was a single chunk;
        # restoring it through the production chunk writer puts back the same
        # head-chunk point the indexer wrote.
        from ..._store_models import VaultChunk

        # The retrieved payload is genuinely dynamic store content; narrow it
        # here at the point it is unpacked into the reconstructed chunk.
        doc = cast("dict[str, Any]", doc)
        body = cast("str", doc.get("content", ""))
        reinsert = VaultChunk(
            doc_id=cast("str", doc["id"]),
            ordinal=0,
            chunk_count=1,
            text=body,
            path=cast("str", doc["path"]),
            doc_type=cast("str", doc.get("doc_type", "")),
            feature=cast("str", doc.get("feature", "")),
            date=cast("str", doc.get("date", "")),
            tags=cast("list[str]", doc.get("tags", [])),
            related=cast("list[str]", doc.get("related", [])),
            title=cast("str", doc.get("title", "")),
            doc_content=body,
            vector=model.encode_query(body[:200]).tolist(),
            sparse_indices=list(
                model.encode_query_sparse(body[:200]).indices,
            ),
            sparse_values=list(
                model.encode_query_sparse(body[:200]).values,
            ),
        )
        store.upsert_document_chunks([reinsert], write_policy=None)

    def test_hybrid_search_with_sparse_vector(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        """R26-M5: hybrid_search with dense+sparse exercises RRF fusion."""
        model = rag_components["model"]
        store = rag_components["store"]

        query_text = "architecture decision"
        query_vec = model.encode_query(query_text)
        sparse_vec = model.encode_query_sparse(query_text)

        results = store.hybrid_search(
            HybridSearchRequest(
                query_vector=query_vec.tolist(),
                query_text=query_text,
                limit=5,
                sparse_vector=sparse_vec,
            )
        )
        assert len(results) > 0
        for r in results:
            assert "id" in r
            assert "_relevance_score" in r

    def test_search_empty_store(
        self, tmp_path: Path, rag_components: RagComponentsWithManifest
    ) -> None:
        """Searching a fresh VaultStore with no indexed docs should return
        empty results without crashing.
        """
        from ...store_runtime import VaultStore

        model = rag_components["model"]
        store = VaultStore(tmp_path)
        try:
            store.ensure_table()

            query_vec = model.encode_query("anything")

            results = store.hybrid_search(
                HybridSearchRequest(
                    query_vector=query_vec.tolist(),
                    query_text="anything",
                    limit=5,
                )
            )
            assert results == []
        finally:
            store.close()


class TestServedCodeCollectionPointer:
    """Code reads resolve through a historical root's pointer until its reset."""

    def test_absent_pointer_resolves_to_the_derived_name(self, tmp_path: Path) -> None:
        """A root without a pointer reads its derived name.

        That is every root a build in the canonical layout wrote.

        Proven able to fail: returning a constant instead of ``derived_name``
        from ``resolve_served_code_collection`` fails the equality below.
        """
        from ..._store_models import resolve_served_code_collection

        assert (
            resolve_served_code_collection(tmp_path, "codebase_docs") == "codebase_docs"
        )

    def test_a_historical_pointer_redirects_reads(self, tmp_path: Path) -> None:
        """A historical pointer is what the store opens, not the derived name.

        Proven able to fail: having ``resolve_served_code_collection`` ignore
        the pointer and return ``derived_name`` fails both assertions below.
        """
        from ..._store_models import resolve_served_code_collection
        from ...store_runtime import VaultStore
        from .._historical_code_layout import write_historical_pointer

        write_historical_pointer(tmp_path, "codebase_docs_g2")
        assert (
            resolve_served_code_collection(tmp_path, "codebase_docs")
            == "codebase_docs_g2"
        )

        # The store is the consumer that matters: it must open the pointed-to
        # collection, which is what keeps a historical index readable.
        store = VaultStore(tmp_path)
        try:
            assert store.CODE_TABLE_NAME == "codebase_docs_g2"
        finally:
            store.close()

    def test_an_unusable_pointer_falls_back_to_the_derived_name(
        self, tmp_path: Path
    ) -> None:
        """A pointer that cannot be trusted must not resolve to nothing.

        Resolving an unreadable pointer to ``None`` would send reads at an
        absent collection and present a populated index as empty - the exact
        failure this indirection exists to prevent.

        Proven able to fail: dropping the ``or derived_name`` fallback makes
        this raise or return None instead of the derived name.
        """
        from ..._store_models import (
            resolve_served_code_collection,
            served_code_pointer_path,
        )

        path = served_code_pointer_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")

        assert (
            resolve_served_code_collection(tmp_path, "codebase_docs") == "codebase_docs"
        )

    def test_reads_follow_the_pointer_not_the_derived_collection(
        self, tmp_path: Path
    ) -> None:
        """The pointer changes what a read sees, not just a name field.

        Asserting the resolved attribute proves the string; this proves the
        consequence. The derived collection exists, the pointer names another,
        and the reader must address the pointed-to one. A read path that
        bypassed the pointer would answer from the derived collection.

        Proven able to fail: reverting the store to
        ``_prefix + CODE_TABLE_NAME`` reports the derived collection's points
        here and fails the second count; restoring returns it to green.
        """
        from ...store_runtime import VaultStore
        from .._historical_code_layout import write_historical_pointer

        store = VaultStore(tmp_path)
        try:
            store.ensure_code_table()
            derived_name = store.CODE_TABLE_NAME
            populated = store.count_code()
        finally:
            store.close()

        write_historical_pointer(tmp_path, derived_name + "_g2")
        swapped = VaultStore(tmp_path)
        try:
            assert derived_name + "_g2" == swapped.CODE_TABLE_NAME
            # The pointed-to collection was never created, so a reader sees no
            # points - the derived collection's state is not what answers.
            assert swapped.code_collection_exists() is False
            assert populated == 0
        finally:
            swapped.close()

    def test_an_unreadable_pointer_is_not_reported_as_absent(
        self, tmp_path: Path
    ) -> None:
        """ "Could not read" and "never published" must stay distinguishable.

        A reader may conflate them - both fall back to the derived name, which
        is safe. A deletion decision may not: treating an unreadable pointer as
        "nothing points here" takes a live served collection for an
        unreferenced one. A reset refuses on an unverifiable pointer, which is
        only possible if the observation can be recognised as unverifiable.

        Proven able to fail: returning ``verifiable=True`` from the OSError
        branch of ``read_served_pointer`` fails the unreadable case below;
        returning ``verifiable=False`` from the FileNotFoundError branch fails
        the never-published case. Neither direction alone is enough.
        """
        from ..._store_models import read_served_pointer, served_code_pointer_path

        # Never published: absence is an observed fact.
        absent = read_served_pointer(tmp_path)
        assert absent.collection is None
        assert absent.verifiable is True

        # Present but unparseable bytes: the file was read, so what it fails to
        # say is still an observation.
        path = served_code_pointer_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        unreadable = read_served_pointer(tmp_path)
        assert unreadable.collection is None
        assert unreadable.verifiable is False

        # And the read path is unchanged by the distinction.
        from ..._store_models import resolve_served_code_collection

        assert (
            resolve_served_code_collection(tmp_path, "codebase_docs") == "codebase_docs"
        )
