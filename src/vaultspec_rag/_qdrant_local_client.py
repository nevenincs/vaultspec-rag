"""The one constructor for the embedded on-disk qdrant store.

The client decides, once per process, whether the SQLite connections behind
its collections may be shared across threads. It finds out by asking SQLite's
compile options through a connection it opens for the question and never
closes; the interpreter closes it at collection and says so with a
``ResourceWarning``, in whichever code happens to be running by then.

Supported Python states the same fact itself: ``sqlite3.threadsafety`` is 3
exactly when SQLite was compiled serialized, the one mode in which a
connection may be shared. Writing the answer into the client's own slot
before it opens a store means the client never asks, on any platform.

A server client is not built here: it has an endpoint and a key, and its own
constructor.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from qdrant_client import QdrantClient

__all__ = ["open_local_client"]

#: ``sqlite3.threadsafety`` when SQLite is serialized.
_SERIALIZED = 3


def open_local_client(path: Path | str) -> QdrantClient:
    """Open the on-disk store at *path*, creating it when absent."""
    from qdrant_client import QdrantClient as _QdrantClient
    from qdrant_client.local.persistence import CollectionPersistence

    CollectionPersistence.CHECK_SAME_THREAD = sqlite3.threadsafety != _SERIALIZED
    return _QdrantClient(path=str(path))
