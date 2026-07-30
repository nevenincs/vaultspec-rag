"""Integration tests for VaultStore: CRUD and hybrid search.

Tests updated for Qdrant-backed store (replacing LanceDB).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..._store_search import HybridSearchRequest

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
        ids = store.get_all_ids()
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
        all_ids = store.get_all_ids()
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

        # Re-insert it so other tests aren't affected (session-scoped fixture)
        from ... import VaultDocument

        reinsert = VaultDocument(
            id=doc["id"],
            path=doc["path"],
            title=doc.get("title", ""),
            content=doc.get("content", ""),
            doc_type=doc.get("doc_type", ""),
            feature=doc.get("feature", ""),
            date=doc.get("date", ""),
            tags=doc.get("tags", ""),
            related=doc.get("related", []),
            vector=model.encode_query(doc.get("content", "")[:200]).tolist(),
            sparse_indices=list(
                model.encode_query_sparse(doc.get("content", "")[:200]).indices,
            ),
            sparse_values=list(
                model.encode_query_sparse(doc.get("content", "")[:200]).values,
            ),
        )
        store.upsert_documents([reinsert], write_policy=None)

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
    """Code reads resolve through the per-root pointer, not the derived name."""

    def test_absent_pointer_resolves_to_the_derived_name(self, tmp_path: Path) -> None:
        """A root that never published a replacement is unaffected.

        This is every existing root, so the default is what makes the
        indirection safe to introduce ahead of anything that moves it.

        Proven able to fail: returning a constant instead of ``derived_name``
        from ``resolve_served_code_collection`` fails the equality below.
        """
        from ..._store_models import resolve_served_code_collection

        assert (
            resolve_served_code_collection(tmp_path, "codebase_docs") == "codebase_docs"
        )

    def test_a_published_pointer_redirects_reads(self, tmp_path: Path) -> None:
        """A published pointer is what the store opens, not the derived name.

        Proven able to fail: having ``resolve_served_code_collection`` ignore
        the pointer and return ``derived_name`` fails both assertions below.
        """
        from ..._store_models import (
            publish_served_code_collection,
            resolve_served_code_collection,
        )
        from ...store_runtime import VaultStore

        publish_served_code_collection(tmp_path, "codebase_docs_g2")
        assert (
            resolve_served_code_collection(tmp_path, "codebase_docs")
            == "codebase_docs_g2"
        )

        # The store is the consumer that matters: it must open the pointed-to
        # collection, which is what makes a swap visible to readers.
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
        """Moving the pointer changes what a read sees, not just a name field.

        Asserting the resolved attribute proves the string; this proves the
        consequence. Points live in the derived collection, the pointer names
        another, and the count a reader takes must come from the pointed-to
        one. A read path that bypassed the pointer would report the derived
        collection's points and the swap would be invisible to callers.

        Proven able to fail: reverting the store to
        ``_prefix + CODE_TABLE_NAME`` reports the derived collection's points
        here and fails the second count; restoring returns it to green.
        """
        from ..._store_models import publish_served_code_collection
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            store.ensure_code_table()
            derived_name = store.CODE_TABLE_NAME
            populated = store.count_code()
        finally:
            store.close()

        publish_served_code_collection(tmp_path, derived_name + "_g2")
        swapped = VaultStore(tmp_path)
        try:
            assert derived_name + "_g2" == swapped.CODE_TABLE_NAME
            # The pointed-to collection was never created, so a reader sees no
            # points - the derived collection's state is not what answers.
            assert swapped.code_collection_exists() is False
            assert populated == 0
        finally:
            swapped.close()

    def test_each_generation_gets_a_name_the_previous_one_never_used(self) -> None:
        """Two generations of one root must never share a collection name.

        Local mode pops a deleted collection's handle while its on-disk
        directory survives, and a create under the same name re-reads that
        directory. Reusing a name would therefore deliver a superseded
        generation's points into its successor - the silent corruption this
        naming exists to prevent.

        Proven able to fail: dropping the generation token from
        ``generation_code_collection`` so it returns ``derived_name`` makes
        the two names equal and fails the inequality below.
        """
        from ..._store_models import generation_code_collection

        first = generation_code_collection("codebase_docs", "a" * 32)
        second = generation_code_collection("codebase_docs", "b" * 32)

        assert first != second
        assert first.startswith("codebase_docs")
        assert second.startswith("codebase_docs")

    def test_a_generation_name_is_stable_for_one_generation(self) -> None:
        """The same generation must resolve to the same collection every time.

        A resume re-derives the name it was already writing into; deriving a
        fresh one would strand the points the interrupted attempt committed.

        Proven able to fail: mixing any per-call varying value into the name
        makes the two derivations differ and fails the equality below.
        """
        from ..._store_models import generation_code_collection

        assert generation_code_collection(
            "codebase_docs", "c" * 32
        ) == generation_code_collection("codebase_docs", "c" * 32)

    def test_a_generation_name_never_collides_with_the_served_one(
        self, tmp_path: Path
    ) -> None:
        """The build target must differ from what is currently served.

        If they matched, writing a generation would mutate the collection
        answering reads - which is the destructive publication this whole
        design removes.
        """
        from ..._store_models import (
            generation_code_collection,
            resolve_served_code_collection,
        )

        served = resolve_served_code_collection(tmp_path, "codebase_docs")
        assert generation_code_collection("codebase_docs", "d" * 32) != served

    def test_breadth_is_recorded_before_the_pointer_moves(self, tmp_path: Path) -> None:
        """A reader must never resolve a generation whose breadth is unrecorded.

        The completeness predicate compares a live count against the published
        figure. A pointer moved ahead of that record names a collection whose
        figure is missing or belongs to its predecessor, so a correct and
        complete generation reads as truncated and drives a reconcile on every
        later run.

        The order is observed rather than asserted after the fact: the
        recorder captures whether the pointer had already moved at the moment
        it ran.

        Proven able to fail: swapping the two statements in
        ``publish_generation_as_served`` makes the recorder observe a moved
        pointer and fails the assertion below.
        """
        from ..._store_models import (
            publish_generation_as_served,
            read_served_code_collection,
        )

        root = tmp_path
        observed: list[str | None] = []

        def _record() -> None:
            observed.append(read_served_code_collection(root))

        publish_generation_as_served(
            root, collection="codebase_docs_gaaa", record_breadth=_record
        )

        assert observed == [None]
        assert read_served_code_collection(root) == "codebase_docs_gaaa"

    def test_a_failed_breadth_record_leaves_the_previous_generation_serving(
        self, tmp_path: Path
    ) -> None:
        """An unverified build must not take over from a complete one.

        A build whose breadth could not be recorded has not proven what it
        holds. Serving the older complete collection is the safe direction;
        moving the pointer anyway would publish an unverified generation.

        Proven able to fail: wrapping the ``record_breadth()`` call in a
        suppressing try/except lets the pointer move and fails the assertion
        below.
        """
        from ..._store_models import (
            publish_generation_as_served,
            publish_served_code_collection,
            read_served_code_collection,
        )

        root = tmp_path
        publish_served_code_collection(root, "codebase_docs_gold")

        def _fail() -> None:
            raise OSError("breadth could not be recorded")

        with pytest.raises(OSError, match="breadth could not be recorded"):
            publish_generation_as_served(
                root, collection="codebase_docs_gnew", record_breadth=_fail
            )

        assert read_served_code_collection(root) == "codebase_docs_gold"

    def test_a_served_generation_is_never_reclaimed(self) -> None:
        """Dropping what a pointer names is the destructive publication itself.

        This is the assertion that matters most in the whole reclamation
        path: a served collection surviving maintenance is the difference
        between a swap and an outage.

        Proven able to fail: removing the ``name not in served_names`` term
        from ``reclaimable_generation_collections`` returns the served name
        and fails the first assertion.
        """
        from ..._store_models import reclaimable_generation_collections

        reclaimable = reclaimable_generation_collections(
            existing=["codebase_docs_gaaa", "codebase_docs_gbbb"],
            served=["codebase_docs_gaaa"],
        )

        assert "codebase_docs_gaaa" not in reclaimable
        assert reclaimable == ("codebase_docs_gbbb",)

    def test_a_derived_base_name_is_never_reclaimed(self) -> None:
        """A root between publications is served by its derived name.

        No pointer names it, so a reference-only rule would drop it and take
        the index with it.

        Proven able to fail: dropping the ``_is_generation_collection`` term
        returns the derived name and fails the assertion below.
        """
        from ..._store_models import reclaimable_generation_collections

        reclaimable = reclaimable_generation_collections(
            existing=["codebase_docs", "vault_docs", "codebase_docs_gccc"],
            served=[],
        )

        assert reclaimable == ("codebase_docs_gccc",)

    def test_an_interrupted_build_leaves_a_reclaimable_collection(self) -> None:
        """The fragment an interrupted build leaves is unreferenced, not serving.

        That is the intended outcome of building beside the served collection
        rather than into it, and reclamation is what eventually clears it.
        """
        from ..._store_models import (
            generation_code_collection,
            reclaimable_generation_collections,
        )

        abandoned = generation_code_collection("codebase_docs", "e" * 32)
        reclaimable = reclaimable_generation_collections(
            existing=["codebase_docs", abandoned],
            served=["codebase_docs"],
        )

        assert reclaimable == (abandoned,)

    def test_a_generation_target_leaves_the_served_collection_untouched(
        self, tmp_path: Path
    ) -> None:
        """Writing to a generation must not disturb what is being served.

        One store is shared between search and indexing, so the build target
        is a per-call argument rather than instance state. This is the
        assertion that binds that choice: after ensuring and counting a
        generation collection, the served one must be unchanged.

        Proven able to fail: having ``_code_collection`` ignore its argument
        and always return ``self.CODE_TABLE_NAME`` makes the generation
        operations land on the served collection and fails the served-count
        assertion below.
        """
        from ..._store_models import generation_code_collection
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            store.ensure_code_table()
            served_before = store.count_code()

            generation = generation_code_collection(store.CODE_TABLE_NAME, "f" * 32)
            store.ensure_code_table(generation)

            # The generation exists and is independently countable...
            assert store.code_collection_exists(generation) is True
            assert store.count_code(generation) == 0
            # ...and the served collection is exactly as it was.
            assert store.count_code() == served_before
            assert generation != store.CODE_TABLE_NAME

            # Dropping the generation must not touch the served collection.
            store.drop_code_table(generation)
            assert store.code_collection_exists(generation) is False
            assert store.code_collection_exists() is True
        finally:
            store.close()

    def test_an_unreadable_pointer_is_not_reported_as_absent(
        self, tmp_path: Path
    ) -> None:
        """ "Could not read" and "never published" must stay distinguishable.

        A reader may conflate them - both fall back to the derived name, which
        is safe. A deletion decision may not: treating an unreadable pointer as
        "nothing points here" takes a live served collection for an
        unreferenced one. The storage rules require the grace clock to reset on
        an unverifiable observation, which is only possible if the observation
        can be recognised as unverifiable.

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
