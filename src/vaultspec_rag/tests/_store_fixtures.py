"""Whole-collection reads for store tests.

Production pages through a collection rather than reading every point in it. A
test asserting on everything a store holds needs the unbounded read, so it
lives here and reaches into the store the way its own paging readers do. These
observe only: they write nothing and create nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
