"""Unit tests for VaultStore helper functions.

Extracted from tests/test_rag_store.py.
Tests updated for Qdrant-backed store (replacing LanceDB).
"""

from __future__ import annotations

import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = [pytest.mark.unit]


class TestStoreHelpers:
    """Tests for store utility functions and edge cases."""

    def test_build_filter_returns_qdrant_filter(self):
        """_build_filter should return a Qdrant Filter with correct conditions."""
        from qdrant_client import models

        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter({"doc_type": "adr"})
        assert result is not None
        assert isinstance(result, models.Filter)
        assert isinstance(result.must, list)
        assert len(result.must) == 1
        cond = result.must[0]
        assert isinstance(cond, models.FieldCondition)
        assert cond.key == "doc_type"

    def test_build_filter_multiple_conditions(self):
        """_build_filter with multiple keys should produce multiple conditions."""
        from qdrant_client import models

        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter({"doc_type": "adr", "feature": "rag"})
        assert result is not None
        assert isinstance(result, models.Filter)
        assert isinstance(result.must, list)
        assert len(result.must) == 2

    def test_build_filter_empty_returns_none(self):
        """_build_filter with empty dict should return None."""
        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter({})
        assert result is None

    def test_build_filter_none_returns_none(self):
        """_build_filter with None should return None."""
        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter(None)
        assert result is None

    def test_build_filter_date_uses_match_value(self):
        """_build_filter date key should use MatchValue for exact matching."""
        from qdrant_client import models

        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter({"date": "2026-02-07"})
        assert result is not None
        assert isinstance(result.must, list)
        cond = result.must[0]
        assert isinstance(cond, models.FieldCondition)
        assert isinstance(cond.match, models.MatchValue)

    def test_build_filter_ignores_unknown_keys(self):
        """_build_filter should ignore keys not in (doc_type, feature, date)."""
        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter({"unknown_key": "value"})
        assert result is None

    def test_stable_id_deterministic(self):
        """_stable_id should return the same integer for the same input."""
        from vaultspec_rag.store import VaultStore

        id1 = VaultStore._stable_id("test-doc")
        id2 = VaultStore._stable_id("test-doc")
        assert id1 == id2
        assert isinstance(id1, int)

    def test_stable_id_different_inputs(self):
        """_stable_id should return different integers for different inputs."""
        from vaultspec_rag.store import VaultStore

        id1 = VaultStore._stable_id("doc-a")
        id2 = VaultStore._stable_id("doc-b")
        assert id1 != id2

    def test_build_filter_tag_produces_match_any(self):
        """_build_filter with tag key produces MatchAny on tags field."""
        from qdrant_client import models

        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter({"tag": "auth"})
        assert result is not None
        assert isinstance(result.must, list)
        assert len(result.must) == 1
        cond = result.must[0]
        assert isinstance(cond, models.FieldCondition)
        assert cond.key == "tags"
        assert isinstance(cond.match, models.MatchAny)
        assert cond.match.any == ["auth"]


class TestStoreLocalWarnings:
    """Qdrant local-mode warning handling."""

    def test_payload_index_warning_is_suppressed(self, tmp_path):
        from vaultspec_rag.store import VaultStore

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            store = VaultStore(tmp_path)
            try:
                store.ensure_table()
                store.ensure_code_table()
            finally:
                store.close()

        messages = [str(item.message) for item in caught]
        assert not any("Payload indexes have no effect" in msg for msg in messages)

    def test_large_local_collection_warning_is_suppressed(self):
        from vaultspec_rag.store import _suppress_local_qdrant_warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with _suppress_local_qdrant_warnings():
                warnings.warn(
                    "Local mode is not recommended for collections with more than "
                    "20,000 points. Current collection contains 20032 points. "
                    "Consider using Qdrant in Docker or Qdrant Cloud for better "
                    "performance with large datasets.",
                    UserWarning,
                    stacklevel=1,
                )

        messages = [str(item.message) for item in caught]
        assert not any("Local mode is not recommended" in msg for msg in messages)


class TestStoreLocalClientSerialization:
    """Real local-Qdrant client calls serialize on the store client lock."""

    def _assert_call_waits_for_store_lock(self, tmp_path, store_call, expected) -> None:
        from vaultspec_rag.store import VaultStore

        store = VaultStore(tmp_path)
        acquired = False
        released = False
        try:
            store.ensure_table()
            store.ensure_code_table()
            acquired = store._client_lock.acquire(timeout=5)
            assert acquired

            started = threading.Event()
            finished = threading.Event()
            errors: list[BaseException] = []

            def worker() -> None:
                started.set()
                try:
                    result = store_call(store)
                    assert result == expected
                except BaseException as exc:  # pragma: no cover - reported below
                    errors.append(exc)
                finally:
                    finished.set()

            thread = threading.Thread(target=worker, name="store-search-lock-test")
            thread.start()

            assert started.wait(timeout=5), "search worker did not start"
            time.sleep(0.25)
            assert thread.is_alive(), "search completed while store lock was held"
            assert not finished.is_set()

            store._client_lock.release()
            released = True
            thread.join(timeout=30)

            assert not thread.is_alive(), "search worker did not finish"
            assert errors == []
        finally:
            if acquired and not released:
                store._client_lock.release()
            store.close()

    def test_vault_hybrid_search_waits_for_store_lock(self, tmp_path):
        from vaultspec_rag.store import EMBEDDING_DIM

        self._assert_call_waits_for_store_lock(
            tmp_path,
            lambda store: store.hybrid_search(
                query_vector=[0.0] * EMBEDDING_DIM,
                query_text="anything",
                limit=1,
            ),
            [],
        )

    def test_codebase_hybrid_search_waits_for_store_lock(self, tmp_path):
        from vaultspec_rag.store import EMBEDDING_DIM

        self._assert_call_waits_for_store_lock(
            tmp_path,
            lambda store: store.hybrid_search_codebase(
                query_vector=[0.0] * EMBEDDING_DIM,
                query_text="anything",
                limit=1,
            ),
            [],
        )

    def test_count_waits_for_store_lock(self, tmp_path):
        self._assert_call_waits_for_store_lock(
            tmp_path,
            lambda store: store.count(),
            0,
        )

    @staticmethod
    def _dense_vector(dim: int, active_index: int = 0) -> list[float]:
        vector = [0.0] * dim
        vector[active_index % dim] = 1.0
        return vector

    def _seed_searchable_points(self, store, dim: int) -> None:
        from vaultspec_rag.store import CodeChunk, VaultDocument

        store.upsert_documents(
            [
                VaultDocument(
                    id=f"parallel-doc-{idx}",
                    path=f".vault/adr/parallel-doc-{idx}.md",
                    doc_type="adr",
                    feature="parallel-search",
                    date="2026-05-03",
                    tags=["search", "parallel"],
                    related=[],
                    title=f"Parallel search ADR {idx}",
                    content=(
                        "Local Qdrant searches are serialized per store "
                        f"while request threads continue safely {idx}."
                    ),
                    vector=self._dense_vector(dim, idx),
                )
                for idx in range(6)
            ],
        )
        store.upsert_code_chunks(
            [
                CodeChunk(
                    id=f"parallel-chunk-{idx}",
                    path=f"src/parallel_{idx}.py",
                    language="python",
                    content=(
                        "def search_parallel():\n"
                        "    return 'serialized local qdrant client'\n"
                    ),
                    line_start=1,
                    line_end=2,
                    node_type="function_definition",
                    function_name="search_parallel",
                    class_name=None,
                    vector=self._dense_vector(dim, idx),
                )
                for idx in range(6)
            ],
        )

    def test_parallel_hybrid_searches_complete_without_qdrant_errors(self, tmp_path):
        from vaultspec_rag.store import VaultStore

        dim = 8
        worker_count = 8
        iterations = 10
        query_vector = self._dense_vector(dim)
        store = VaultStore(tmp_path, embedding_dim=dim)
        try:
            self._seed_searchable_points(store, dim)
            barrier = threading.Barrier(worker_count)

            def worker(worker_id: int) -> dict[str, int]:
                barrier.wait(timeout=10)
                counts = {"vault": 0, "code": 0}
                for iteration in range(iterations):
                    if (worker_id + iteration) % 2 == 0:
                        rows = store.hybrid_search(
                            query_vector=query_vector,
                            query_text="parallel local qdrant search",
                            filters={"feature": "parallel-search"},
                            limit=3,
                        )
                        assert rows
                        assert all(row["feature"] == "parallel-search" for row in rows)
                        counts["vault"] += len(rows)
                    else:
                        rows = store.hybrid_search_codebase(
                            query_vector=query_vector,
                            query_text="parallel local qdrant code search",
                            filters={"language": "python"},
                            limit=3,
                        )
                        assert rows
                        assert all(row["language"] == "python" for row in rows)
                        counts["code"] += len(rows)
                return counts

            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(worker, worker_id)
                    for worker_id in range(worker_count)
                ]
                results = [future.result(timeout=60) for future in futures]

            assert sum(item["vault"] for item in results) > 0
            assert sum(item["code"] for item in results) > 0
        finally:
            store.close()


class TestBuildCodeFilter:
    """Tests for _build_code_filter."""

    def test_path_prefix_uses_match_value(self):
        """Path ending with / should use MatchValue (KEYWORD index)."""
        from qdrant_client import models

        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_code_filter({"path": "src/"})
        assert result is not None
        assert isinstance(result.must, list)
        cond = result.must[0]
        assert isinstance(cond, models.FieldCondition)
        assert isinstance(cond.match, models.MatchValue)

    def test_path_exact_uses_match_value(self):
        """Exact path should use MatchValue."""
        from qdrant_client import models

        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_code_filter({"path": "src/main.py"})
        assert result is not None
        assert isinstance(result.must, list)
        cond = result.must[0]
        assert isinstance(cond, models.FieldCondition)
        assert isinstance(cond.match, models.MatchValue)
