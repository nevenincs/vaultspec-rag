"""Live-collection drift test for the storage-schema contract.

Creates the real ``vault_docs`` and ``codebase_docs`` collections through the
store's own ``ensure`` paths and asserts the live vector config equals the
declared schema: the dense vector name, dimension, and distance, and the sparse
vector name. A rename or dimension/distance change that was not reflected in
the contract fails here against a real Qdrant collection.

This is an integration test (a real local-mode Qdrant store on disk) - it needs
no GPU and no server. Payload-index readback is deliberately NOT asserted here:
a local-mode Qdrant ignores payload indexes, so the index-set drift guard lives
as a CI-gated invariant in ``test_store_schema`` (declared indexes must name
real payload fields).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from .. import store_schema
from ..store import EMBEDDING_DIM, VaultStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.integration]


@pytest.fixture
def tmp_store(tmp_path: Path) -> Generator[VaultStore]:
    store = VaultStore(tmp_path)
    yield store
    store.close()


def _vectors(
    store: VaultStore, collection: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the (dense, sparse) vector configs of a live collection.

    The qdrant-client return types are loosely stubbed, so the named-vector
    maps are cast to typed dicts for the assertions.
    """
    assert store._client is not None
    info = store._client.get_collection(collection)
    dense = cast("dict[str, Any]", info.config.params.vectors)
    sparse = cast("dict[str, Any]", info.config.params.sparse_vectors)
    return dense, sparse


def test_vault_collection_vector_config_matches_schema(tmp_store: VaultStore) -> None:
    tmp_store.ensure_table()
    vectors, sparse = _vectors(tmp_store, tmp_store.TABLE_NAME)
    dense = vectors[store_schema.DENSE_VECTOR_NAME]
    assert dense.size == EMBEDDING_DIM
    assert dense.distance.value == store_schema.DENSE_DISTANCE
    assert store_schema.SPARSE_VECTOR_NAME in sparse


def test_code_collection_vector_config_matches_schema(tmp_store: VaultStore) -> None:
    tmp_store.ensure_code_table()
    vectors, sparse = _vectors(tmp_store, tmp_store.CODE_TABLE_NAME)
    dense = vectors[store_schema.DENSE_VECTOR_NAME]
    assert dense.size == EMBEDDING_DIM
    assert dense.distance.value == store_schema.DENSE_DISTANCE
    assert store_schema.SPARSE_VECTOR_NAME in sparse


def test_descriptor_dim_matches_live_collection(tmp_store: VaultStore) -> None:
    # The advertised effective dimension must equal what the live collection
    # was actually created with - the exact value a direct-Qdrant consumer
    # validates before deserializing.
    tmp_store.ensure_table()
    vectors, _ = _vectors(tmp_store, tmp_store.TABLE_NAME)
    live_dim = cast("int", vectors[store_schema.DENSE_VECTOR_NAME].size)
    descriptor = store_schema.describe_storage_schema()
    vault = cast("dict[str, Any]", descriptor["vault"])
    assert vault["vectors"]["dense"]["dim"] == live_dim


def test_collection_and_descriptor_share_one_dim_source(tmp_store: VaultStore) -> None:
    # The store builds its collection from the same dimension source the
    # descriptor advertises, so the two agree by construction under ANY config,
    # not only the default - the store's build dim IS the descriptor's source.
    assert tmp_store._embedding_dim == store_schema.effective_dense_dim()
