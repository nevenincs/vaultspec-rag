"""Integration tests for VaultStore codebase functionality."""

from __future__ import annotations

import pytest

from vaultspec_rag.store import CodeChunk, VaultStore

pytestmark = [pytest.mark.integration]


@pytest.fixture
def tmp_vault_store(tmp_path):
    """Fixture for a temporary VaultStore."""
    store = VaultStore(tmp_path)
    yield store
    store.close()


class TestStoreCodebase:
    """Tests for codebase-specific store operations using real embeddings."""

    def test_ensure_code_table(self, tmp_vault_store):
        """ensure_code_table should create the codebase_docs collection."""
        tmp_vault_store.ensure_code_table()
        assert tmp_vault_store._client.collection_exists(
            tmp_vault_store.CODE_TABLE_NAME,
        )

    def test_upsert_code_chunks(self, tmp_vault_store, rag_components):
        """upsert_code_chunks should add and retrieve chunks."""
        model = rag_components["model"]
        text = "print('hello')"
        vector = model.encode_documents([text]).tolist()[0]
        sparse = model.encode_documents_sparse([text])[0]
        chunks = [
            CodeChunk(
                id="src/main.py:1-10",
                path="src/main.py",
                language="python",
                content=text,
                line_start=1,
                line_end=10,
                vector=vector,
                sparse_indices=list(sparse.indices),
                sparse_values=list(sparse.values),
            ),
        ]
        tmp_vault_store.upsert_code_chunks(chunks)
        assert tmp_vault_store.count_code() == 1

        ids = tmp_vault_store.get_all_code_ids()
        assert "src/main.py:1-10" in ids

    def test_build_code_filter(self):
        """_build_code_filter should build correct Qdrant filter for codebase."""
        from qdrant_client import models

        filters = {"language": "python", "path": "src/indexer.py"}
        result = VaultStore._build_code_filter(filters)
        assert result is not None
        assert isinstance(result, models.Filter)
        assert len(result.must) == 2
        keys = {cond.key for cond in result.must}
        assert keys == {"language", "path"}

    def test_delete_code_chunks(self, tmp_vault_store, rag_components):
        """delete_code_chunks should remove code chunks by ID."""
        model = rag_components["model"]
        text = "test"
        vector = model.encode_documents([text]).tolist()[0]
        sparse = model.encode_documents_sparse([text])[0]
        chunks = [
            CodeChunk(
                id="test.py:1-5",
                path="test.py",
                language="python",
                content=text,
                line_start=1,
                line_end=5,
                vector=vector,
                sparse_indices=list(sparse.indices),
                sparse_values=list(sparse.values),
            ),
        ]
        tmp_vault_store.upsert_code_chunks(chunks)
        assert tmp_vault_store.count_code() == 1

        tmp_vault_store.delete_code_chunks(["test.py:1-5"])
        assert tmp_vault_store.count_code() == 0
