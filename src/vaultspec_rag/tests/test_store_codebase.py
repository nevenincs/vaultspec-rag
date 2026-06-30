"""Integration tests for VaultStore codebase functionality."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from .conftest import RagComponentsWithManifest


import pytest

from ..store import CodeChunk, VaultStore

pytestmark = [pytest.mark.integration]


@pytest.fixture
def tmp_vault_store(tmp_path: Path) -> Generator[VaultStore]:
    """Fixture for a temporary VaultStore."""
    store = VaultStore(tmp_path)
    yield store
    store.close()


class TestStoreCodebase:
    """Tests for codebase-specific store operations using real embeddings."""

    def test_ensure_code_table(self, tmp_vault_store: VaultStore) -> None:
        """ensure_code_table should create the codebase_docs collection."""
        tmp_vault_store.ensure_code_table()
        assert tmp_vault_store._client is not None
        assert tmp_vault_store._client.collection_exists(  # pyright: ignore[reportUnknownMemberType]
            tmp_vault_store.CODE_TABLE_NAME,
        )

    def test_upsert_code_chunks(
        self,
        tmp_vault_store: VaultStore,
        rag_components: RagComponentsWithManifest,
    ) -> None:
        """upsert_code_chunks should add and retrieve chunks."""
        model = rag_components["model"]
        text = "print('hello')"
        vector = cast("list[float]", model.encode_documents([text]).tolist()[0])  # pyright: ignore[reportUnknownMemberType]
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

    def test_build_code_filter(self) -> None:
        """_build_code_filter should build correct Qdrant filter for codebase."""
        from qdrant_client import models

        filters = {"language": "python", "path": "src/indexer.py"}
        result = VaultStore._build_code_filter(filters)
        assert result is not None
        assert isinstance(result, models.Filter)
        assert isinstance(result.must, list)
        assert len(result.must) == 2
        keys = {
            cond.key for cond in result.must if isinstance(cond, models.FieldCondition)
        }
        assert keys == {"language", "path"}

    def test_build_code_filter_exclude_domains_must_not(self) -> None:
        """exclude_domains becomes a must_not MatchAny on the domain field."""
        from qdrant_client import models

        result = VaultStore._build_code_filter(
            None, exclude_domains=["tests", "worktree"]
        )
        assert result is not None
        assert result.must is None
        assert isinstance(result.must_not, list)
        assert len(result.must_not) == 1
        cond = result.must_not[0]
        assert isinstance(cond, models.FieldCondition)
        assert cond.key == "domain"
        assert isinstance(cond.match, models.MatchAny)
        assert set(cond.match.any) == {"tests", "worktree"}

    def test_build_code_filter_only_domains_must(self) -> None:
        """only_domains becomes a must MatchAny on the domain field."""
        from qdrant_client import models

        result = VaultStore._build_code_filter(None, only_domains=["prod"])
        assert result is not None
        assert isinstance(result.must, list)
        cond = result.must[0]
        assert isinstance(cond, models.FieldCondition)
        assert cond.key == "domain"
        assert isinstance(cond.match, models.MatchAny)
        assert list(cond.match.any) == ["prod"]

    def test_build_code_filter_none_without_any_filter(self) -> None:
        """No filters and no domain constraints yields None."""
        assert VaultStore._build_code_filter(None) is None

    def test_delete_code_chunks(
        self,
        tmp_vault_store: VaultStore,
        rag_components: RagComponentsWithManifest,
    ) -> None:
        """delete_code_chunks should remove code chunks by ID."""
        model = rag_components["model"]
        text = "test"
        vector = cast("list[float]", model.encode_documents([text]).tolist()[0])  # pyright: ignore[reportUnknownMemberType]
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
