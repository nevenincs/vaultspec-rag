"""Whole-collection reads and whole-document seeds for store tests.

Production pages through a collection and writes vault content as chunks. A
test asserting on everything a store holds, or seeding one document at a time,
needs neither, so those operations live here and reach into the store the way
its own methods do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..store_ingest import _point_vector

if TYPE_CHECKING:
    from qdrant_client.http.models import PointStruct

    from .. import store_schema
    from .._store_models import VaultDocument
    from .._store_writes import StoreWritePolicy
    from ..store_runtime import VaultStore


def get_all_ids(store: VaultStore) -> set[str]:
    """Return every document id in the vault collection."""
    if not store._collection_exists(store.TABLE_NAME):
        return set()
    with store._point_lock(store.TABLE_NAME):
        return store._scroll_all_ids(store.TABLE_NAME, "doc_id")


def get_all_document_content_ids(store: VaultStore) -> set[str]:
    """Return every deterministic id in the document collection."""
    if not store._collection_exists(store.DOCUMENT_TABLE_NAME):
        return set()
    with store._point_lock(store.DOCUMENT_TABLE_NAME):
        return store._scroll_all_ids(store.DOCUMENT_TABLE_NAME, "document_id")


def vault_doc_payload(doc: VaultDocument) -> store_schema.VaultDocPayload:
    """Build a document-level point payload from a whole vault document."""
    return {
        "doc_id": doc.id,
        "path": doc.path,
        "doc_type": doc.doc_type,
        "feature": doc.feature,
        "date": doc.date,
        "tags": doc.tags,
        "related": doc.related,
        "title": doc.title,
        "status": doc.status,
        "content": doc.content,
    }


def upsert_documents(
    store: VaultStore,
    docs: list[VaultDocument],
    *,
    write_policy: StoreWritePolicy | None,
) -> None:
    """Insert or update whole vault documents by id."""
    if not docs:
        return

    from qdrant_client import models

    points: list[PointStruct] = [
        models.PointStruct(
            id=store._stable_id(doc.id),
            vector=_point_vector(doc.vector, doc.sparse_indices, doc.sparse_values),
            payload=cast("dict[str, Any]", vault_doc_payload(doc)),
        )
        for doc in docs
    ]
    store.ensure_table()
    with store._point_lock(store.TABLE_NAME):
        store._guarded_upsert(
            store.TABLE_NAME,
            points,
            "vault documents",
            write_policy=write_policy,
        )
