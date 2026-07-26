"""Backend-dispatching access to what produced a collection's vectors.

A collection's identity - the models, width, distance, and vector names that
built it - has to live somewhere durable, and the two backends keep their
bookkeeping in different places. Server mode records it in that namespace's
storage-manifest entry, alongside the prefix-to-root attribution the survey
already consults. Local mode has no manifest entry at all (the manifest hook is
server-only), so it records the same fact in a sidecar under that root's own
storage directory, which is per-root and self-contained.

This is one fact with two homes, not two sources of truth. The manifest holds no
local record for a sidecar to disagree with, so the homes are disjoint by
construction, and every caller goes through the two functions here rather than
reaching either home directly.

Extending the manifest to cover local roots was the obvious alternative and is
deliberately not done. The survey classifies a namespace by matching manifest
entries against live server collections and reclamation acts on that verdict; a
local entry would match nothing and so would present as an unattributable
namespace to the one surface that must never be handed one.

A torch-free leaf: stdlib plus the schema definitions, nothing else, so it stays
importable from a spawn worker's import chain without loading CUDA.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import cast

from . import store_schema

__all__ = [
    "load_identity",
    "record_identity",
    "sidecar_path",
]

logger = logging.getLogger(__name__)

#: Filename of the local-mode sidecar inside a root's own storage directory.
_SIDECAR_FILENAME = "collection-identity.json"

#: Serialises in-process read-modify-write on the sidecar so two collections
#: being stamped concurrently cannot drop each other's entries. Mirrors the
#: manifest's own lock; cross-process writers rely on atomic ``os.replace``.
_LOCK = threading.RLock()


def sidecar_path(local_dir: Path | str) -> Path:
    """Return the identity sidecar path for one local-mode storage directory."""
    return Path(local_dir) / _SIDECAR_FILENAME


def _load_sidecar(local_dir: Path | str) -> dict[str, object]:
    """Read the local sidecar's collection map, empty when absent or unusable.

    Every failure degrades to an empty map rather than raising: absent evidence
    is the ``unverifiable`` verdict, which is a legitimate answer, whereas
    raising here would make an unreadable sidecar fail a store open.
    """
    path = sidecar_path(local_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.debug("unreadable identity sidecar at %s", path, exc_info=True)
        return {}
    if not isinstance(parsed, dict):
        return {}
    collections = cast("dict[str, object]", parsed).get("collections")
    if not isinstance(collections, dict):
        return {}
    return cast("dict[str, object]", collections)


def load_identity(
    root: Path | str,
    *,
    backend: str,
    collection: str,
    local_dir: Path | str | None = None,
) -> store_schema.CollectionIdentity | None:
    """Return the identity stamped for one collection, or ``None`` if absent.

    ``None`` is the honest answer for a collection created before stamping
    existed, and callers must render it as ``unverifiable`` rather than treating
    it as a match - scoring absent evidence as passing is the silent failure
    this whole mechanism exists to remove.

    Args:
        root: The workspace root owning the collection.
        backend: ``"server"`` or ``"local"``.
        collection: The exact collection name.
        local_dir: The root's own storage directory; required in local mode and
            ignored in server mode.

    Returns:
        The stamped identity, or ``None`` when none is recorded.
    """
    if backend == "server":
        from ._store_models import root_collection_prefix
        from .storage_manifest import load_manifest

        try:
            entry = load_manifest().get(root_collection_prefix(root))
        except Exception:  # attribution is best-effort; absence is a verdict
            logger.debug("could not read manifest identity", exc_info=True)
            return None
        if entry is None:
            return None
        return entry.collection_identity.get(collection)
    if local_dir is None:
        return None
    return store_schema.CollectionIdentity.from_payload(
        _load_sidecar(local_dir).get(collection)
    )


def record_identity(
    root: Path | str,
    *,
    backend: str,
    collection: str,
    identity: store_schema.CollectionIdentity,
    local_dir: Path | str | None = None,
) -> None:
    """Stamp what produced one collection, in whichever home the backend uses.

    Called once, when the collection is created, so the record describes the
    process that actually wrote the vectors rather than whatever configuration a
    later reader happens to hold. Best-effort: a failure to stamp is logged and
    swallowed, because it degrades a later verdict to ``unverifiable`` and must
    not fail the index run that was creating the collection.

    Args:
        root: The workspace root owning the collection.
        backend: ``"server"`` or ``"local"``.
        collection: The exact collection name being stamped.
        identity: What produced it.
        local_dir: The root's own storage directory; required in local mode and
            ignored in server mode.
    """
    try:
        if backend == "server":
            from .storage_manifest import record_collection_identity

            record_collection_identity(
                root, backend=backend, collection=collection, identity=identity
            )
            return
        if local_dir is None:
            return
        _record_local(local_dir, collection=collection, identity=identity)
    except Exception:  # best-effort stamp; must never break indexing
        logger.debug(
            "could not stamp collection identity for %s", collection, exc_info=True
        )


def _record_local(
    local_dir: Path | str,
    *,
    collection: str,
    identity: store_schema.CollectionIdentity,
) -> None:
    """Merge one collection's identity into the local sidecar, atomically."""
    path = sidecar_path(local_dir)
    with _LOCK:
        collections = dict(_load_sidecar(local_dir))
        collections[collection] = identity.to_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "collections": collections}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
