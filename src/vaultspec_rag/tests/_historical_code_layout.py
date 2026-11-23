"""Code collections laid out the way builds before the canonical layout left them.

Those builds wrote each rebuild into ``<derived>_g<token>`` and pointed the
root's served-collection pointer at it. Nothing in production writes either
any more, so a test that needs a root in that state writes it here: the
collection through the raw client, with the store's own geometry and payload
builders, and the pointer as the JSON file those builds left.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

    from .._store_models import CodeChunk
    from ..store_runtime import VaultStore


def historical_generation(derived: str, token: str) -> str:
    """Return the name a historical build gave generation *token* of *derived*."""
    return f"{derived}_g{token}"


def write_historical_pointer(root: Path, collection: str) -> None:
    """Leave *root*'s served-collection pointer naming *collection*."""
    from .._store_models import served_code_pointer_path

    path = served_code_pointer_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"collection": collection}), encoding="utf-8")


def create_historical_generation(store: VaultStore, token: str) -> str:
    """Create an empty generation collection of *store*'s root and return it."""
    from qdrant_client import models

    from .. import store_schema

    name = historical_generation(store.DERIVED_CODE_TABLE_NAME, token)
    store.client.create_collection(
        collection_name=name,
        vectors_config={
            store_schema.DENSE_VECTOR_NAME: models.VectorParams(
                size=store._embedding_dim,
                distance=models.Distance(store_schema.DENSE_DISTANCE),
            )
        },
        sparse_vectors_config={
            store_schema.SPARSE_VECTOR_NAME: models.SparseVectorParams()
        },
    )
    return name


def write_historical_code_points(
    store: VaultStore, collection: str, chunks: list[CodeChunk]
) -> None:
    """Write *chunks* into *collection* with the store's own point builders."""
    from qdrant_client import models

    from .._store_models import _code_chunk_payload
    from ..store_ingest import _point_vector

    store.client.upsert(
        collection_name=collection,
        points=[
            models.PointStruct(
                id=store._stable_id(chunk.id),
                vector=_point_vector(
                    chunk.vector, chunk.sparse_indices, chunk.sparse_values
                ),
                payload=cast("dict[str, Any]", _code_chunk_payload(chunk)),
            )
            for chunk in chunks
        ],
        wait=True,
    )
