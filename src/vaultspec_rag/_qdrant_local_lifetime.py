"""Release local collection storage before an authorized SDK deletion."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qdrant_client import QdrantClient


def close_local_collection(client: QdrantClient, name: str) -> None:
    """Close the owned local handle; remote clients have no such resource.

    Qdrant's public delete API discards a local collection without closing its
    SQLite storage. Its public API offers no per-collection close, so this
    narrowly uses the same local ownership map used by the store's hard delete.
    The caller still owns deletion authorization, synchronization and outcomes.
    """
    from qdrant_client.local.qdrant_local import QdrantLocal

    local = getattr(client, "_client", None)
    if isinstance(local, QdrantLocal):
        collection = local.collections.get(name)
        if collection is not None:
            collection.close()
