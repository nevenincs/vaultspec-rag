"""Persisted prefix-to-root manifest for storage lifecycle management.

Server-mode collections are namespaced by ``root_collection_prefix`` - a
one-way blake2b hash of the resolved root path (see ``store.py``). A
collection name therefore cannot be reversed to its source root, and the
in-memory ``ServiceRegistry`` holds only currently-leased roots, not a
durable record of every root ever indexed. Without a persisted mapping
the storage surface cannot attribute a stored ``r{hash}_`` collection to a
filesystem path, and so cannot safely tell a live namespace from an
orphaned one (a removed worktree or deleted root).

This module is that mapping. It records ``prefix -> (root, backend,
last_indexed)`` whenever a root is indexed, and the survey/prune/delete
surface consults it to classify each namespace. A namespace whose prefix
is absent from the manifest is ``unknown`` and must never be auto-pruned.

The manifest lives under the managed service directory (``status_dir``,
``~/.vaultspec-rag`` by default, overridable via
``VAULTSPEC_RAG_STATUS_DIR``) - the per-host, gitignored, test-isolatable
home the daemon already uses for ``service.json`` and the local-only
marker - never the project tree, so the pure-Python wheel and the
repository stay untouched. Writes are atomic (``.tmp`` sibling plus
``os.replace``) under a process lock so a concurrent reader never observes
a half-written file and concurrent indexers do not clobber each other's
read-modify-write.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from . import store_schema
from .store import root_collection_prefix

__all__ = [
    "ManifestEntry",
    "ReconcileResult",
    "SnapshotCollection",
    "StorageSnapshotManifest",
    "classify_root",
    "load_manifest",
    "manifest_path",
    "reconcile_manifest",
    "record_root",
    "rekey_prefix",
    "remove_prefix",
    "remove_root",
    "reverse_map",
    "snapshot_manifest_path",
    "update_orphan_stamps",
    "write_snapshot_manifest",
]

# Filename of the manifest inside the managed service (``status_dir``)
# directory. Mirrors the local-only marker convention in ``config.py``.
_MANIFEST_FILENAME = "storage-manifest.json"
_SNAPSHOT_MANIFEST_FILENAME = "snapshot-manifest.json"

# Serialises in-process read-modify-write so two indexers recording roots
# concurrently cannot drop each other's entries. Cross-process writers
# still rely on atomic ``os.replace`` (last-writer-wins on the whole file),
# which is acceptable because the daemon is the primary writer.
_LOCK = threading.RLock()


@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of reconciling the manifest against the live server.

    Attributes:
        dropped: Prefixes removed because their root is gone AND no
            collection backs them on the live server (stale bookkeeping).
        kept: Prefixes left in place (root still resolves, or collections
            still exist, or existence could not be confirmed).
    """

    dropped: list[str]
    kept: list[str]


@dataclass(frozen=True)
class ManifestEntry:
    """One root's manifest record.

    Attributes:
        prefix: The collection prefix (``r{hash}_``) for this root in
            server mode; the empty string in local mode.
        root: The resolved root path, as a string.
        backend: ``"server"`` or ``"local"``.
        last_indexed: ISO-8601 timestamp of the most recent index, or the
            empty string when never stamped.
        first_seen_orphaned: ISO-8601 timestamp of the first survey that
            observed the root ``orphaned``, or the empty string when the
            root is (or has returned to being) live/unverifiable. This is
            the persisted grace clock: automated reclamation may only act
            once the stamp is old enough, a daemon restart must not reset
            it, and a reappearing root must.
    """

    prefix: str
    root: str
    backend: str
    last_indexed: str = ""
    first_seen_orphaned: str = ""
    storage_schema_version: int = store_schema.STORAGE_SCHEMA_VERSION
    collections: tuple[str, ...] = ()


@dataclass(frozen=True)
class SnapshotCollection:
    """One collection artifact recorded in an archive snapshot."""

    name: str
    snapshot_file: str
    points: int


@dataclass(frozen=True)
class StorageSnapshotManifest:
    """Portable description of one complete namespace archive."""

    prefix: str
    root: str | None
    storage_schema_version: int
    collections: tuple[SnapshotCollection, ...]
    metadata_files: tuple[str, ...] = ()


def snapshot_manifest_path(archive_namespace_dir: Path) -> Path:
    """Return the manifest path for one archived namespace."""
    return archive_namespace_dir / _SNAPSHOT_MANIFEST_FILENAME


def write_snapshot_manifest(
    archive_namespace_dir: Path,
    manifest: StorageSnapshotManifest,
) -> Path:
    """Atomically publish a deterministic manifest after an archive completes."""
    path = snapshot_manifest_path(archive_namespace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "prefix": manifest.prefix,
        "root": manifest.root,
        "storage_schema_version": manifest.storage_schema_version,
        "collections": [
            {
                "name": item.name,
                "snapshot_file": item.snapshot_file,
                "points": item.points,
            }
            for item in manifest.collections
        ],
        "metadata_files": list(manifest.metadata_files),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _declared_collections(prefix: str, backend: str) -> tuple[str, ...]:
    """Return exact collection names for a manifest namespace."""
    return store_schema.collection_names(prefix if backend == "server" else "")


def _legacy_collections(prefix: str, backend: str) -> tuple[str, ...]:
    """Infer the two collections known before document storage existed."""
    collection_prefix = prefix if backend == "server" else ""
    return (
        collection_prefix + store_schema.VAULT_COLLECTION,
        collection_prefix + store_schema.CODE_COLLECTION,
    )


def _status_dir_path() -> Path:
    """Resolve the managed service directory the same way the rest of the system does.

    Resolves through ``get_config().status_dir`` (CLI ``--status-dir`` override
    -> ``VAULTSPEC_RAG_STATUS_DIR`` env -> default), so the manifest always lands
    in the same directory as ``service.json``, the qdrant tree, and the logs.
    Reading the env directly here would silently ignore a ``--status-dir``
    override and split the manifest from the rest of the service's durable
    state. The import is function-local to avoid an import cycle with the store
    (which imports this module's ``root_collection_prefix``-keyed helpers).
    """
    from .config import get_config

    return Path(str(get_config().status_dir)).expanduser()


def manifest_path() -> Path:
    """Return the path of the persisted storage manifest."""
    return _status_dir_path() / _MANIFEST_FILENAME


def load_manifest() -> dict[str, ManifestEntry]:
    """Load the manifest as a mapping of prefix to entry.

    A missing manifest (the common case on a fresh host) returns an empty
    mapping. A malformed or unreadable manifest is treated as empty rather
    than raised: a corrupt runtime hint must never crash the survey or
    block a destructive verb's safety check - an empty manifest simply
    classifies every namespace as ``unknown``, the conservative outcome.

    Returns:
        Mapping of collection prefix to :class:`ManifestEntry`.
    """
    path = manifest_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    try:
        parsed: object = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    roots_obj = cast("dict[str, object]", parsed).get("roots")
    if not isinstance(roots_obj, dict):
        return {}
    roots = cast("dict[str, object]", roots_obj)
    entries: dict[str, ManifestEntry] = {}
    for prefix, record_obj in roots.items():
        if not isinstance(record_obj, dict):
            continue
        record = cast("dict[str, object]", record_obj)
        root = record.get("root")
        if not isinstance(root, str):
            continue
        backend = str(record.get("backend", ""))
        raw_collections = record.get("collections")
        collections = (
            tuple(
                value
                for value in cast("list[object]", raw_collections)
                if isinstance(value, str)
            )
            if isinstance(raw_collections, list)
            else _legacy_collections(prefix, backend)
        )
        raw_schema_version = record.get("storage_schema_version", 1)
        schema_version = (
            raw_schema_version
            if isinstance(raw_schema_version, int)
            and not isinstance(raw_schema_version, bool)
            else 1
        )
        entries[prefix] = ManifestEntry(
            prefix=prefix,
            root=root,
            backend=backend,
            last_indexed=str(record.get("last_indexed", "")),
            # Lenient: pre-upgrade manifests lack the field; absent means
            # "never observed orphaned", so the first reclaim can happen no
            # earlier than one full grace window after upgrade.
            first_seen_orphaned=str(record.get("first_seen_orphaned", "")),
            storage_schema_version=schema_version,
            collections=collections,
        )
    return entries


def _write_manifest(entries: dict[str, ManifestEntry]) -> Path:
    """Atomically persist the manifest mapping to disk."""
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 2,
        "roots": {
            entry.prefix: {
                "root": entry.root,
                "backend": entry.backend,
                "last_indexed": entry.last_indexed,
                "first_seen_orphaned": entry.first_seen_orphaned,
                "storage_schema_version": entry.storage_schema_version,
                "collections": list(entry.collections),
            }
            for entry in entries.values()
        },
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def record_root(
    root: Path | str, *, backend: str, last_indexed: str = ""
) -> ManifestEntry:
    """Upsert the manifest entry for ``root`` and persist it.

    The prefix is derived from ``root_collection_prefix`` so it matches the
    server-mode collection namespace exactly (resolved, case-normalised).
    The call is a read-modify-write under the process lock so it preserves
    every other root's entry.

    Args:
        root: The workspace root being indexed.
        backend: ``"server"`` or ``"local"``.
        last_indexed: ISO-8601 timestamp to stamp; the caller supplies it
            so this layer takes no clock dependency.

    Returns:
        The persisted :class:`ManifestEntry`.
    """
    resolved = str(Path(root).resolve())
    prefix = root_collection_prefix(root)
    entry = ManifestEntry(
        prefix=prefix,
        root=resolved,
        backend=backend,
        last_indexed=last_indexed,
        storage_schema_version=store_schema.STORAGE_SCHEMA_VERSION,
        collections=_declared_collections(prefix, backend),
    )
    with _LOCK:
        entries = load_manifest()
        existing = entries.get(prefix)
        # Idempotent: skip the disk write when nothing changed, so frequent
        # callers (e.g. a store-open hook) do not churn the manifest. A
        # caller stamping a fresh last_indexed always writes.
        if (
            existing is not None
            and existing.root == resolved
            and existing.backend == backend
            and existing.storage_schema_version == entry.storage_schema_version
            and existing.collections == entry.collections
            and not last_indexed
        ):
            return existing
        entries[prefix] = entry
        _write_manifest(entries)
    return entry


def remove_prefix(prefix: str) -> bool:
    """Drop the manifest entry for ``prefix`` and persist.

    Args:
        prefix: The collection prefix to forget.

    Returns:
        ``True`` if an entry was removed, ``False`` if none existed.
    """
    with _LOCK:
        entries = load_manifest()
        if prefix not in entries:
            return False
        del entries[prefix]
        _write_manifest(entries)
    return True


def remove_root(root: Path | str) -> bool:
    """Drop the manifest entry for ``root`` and persist.

    Args:
        root: The workspace root whose entry to forget.

    Returns:
        ``True`` if an entry was removed, ``False`` if none existed.
    """
    return remove_prefix(root_collection_prefix(root))


def reverse_map(prefix: str) -> str | None:
    """Return the resolved root path for a collection prefix, or ``None``.

    Args:
        prefix: The collection prefix (``r{hash}_``).

    Returns:
        The resolved root path string, or ``None`` when the prefix is not
        attributable (an ``unknown`` namespace).
    """
    entry = load_manifest().get(prefix)
    return entry.root if entry is not None else None


def classify_root(entry: ManifestEntry) -> str:
    """Classify a known manifest entry as ``live``, ``orphaned``, or ``unverifiable``.

    A namespace whose prefix is absent from the manifest is ``unknown``;
    that case is handled by the survey caller, not here, because there is
    no entry to pass.

    Data-safety: a root is declared ``orphaned`` (a prune target) only when
    it is definitively absent AND its drive/share anchor is itself reachable.
    A transiently-unreachable root - a disconnected UNC share, an unmounted
    removable drive, or a permission/timeout error - is ``unverifiable`` and
    is reported but never auto-pruned, so a live-but-offline index is never
    deleted out from under the operator.

    Args:
        entry: A manifest entry whose backing root is being checked.

    Returns:
        ``"live"`` if the root exists, ``"unverifiable"`` if its existence
        cannot be confirmed (unreachable anchor or OSError), else
        ``"orphaned"``.
    """
    root = Path(entry.root)
    try:
        if root.exists():
            return "live"
    except OSError:
        return "unverifiable"
    # Root is absent. Only an absent root on a *reachable* anchor (e.g. an
    # existing ``C:\`` or ``\\host\share\``) is a true orphan; an absent or
    # unreadable anchor means the volume/share is offline, not that the index
    # is dead.
    anchor = root.anchor
    if not anchor:
        return "unverifiable"
    try:
        if not Path(anchor).exists():
            return "unverifiable"
    except OSError:
        return "unverifiable"
    return "orphaned"


def update_orphan_stamps(statuses: dict[str, str], *, now_iso: str) -> dict[str, str]:
    """Advance the persisted grace clocks from one survey's classifications.

    For every manifest entry whose prefix appears in ``statuses``: a newly
    observed ``orphaned`` root gets ``first_seen_orphaned`` stamped with
    ``now_iso`` (an existing stamp is preserved - the clock measures
    CONTINUOUS orphan-hood, and a daemon restart must not reset it); any
    other observation (``live``, ``unverifiable``) clears the stamp, so a
    reappearing or merely unreachable root restarts its grace window from
    zero. Prefixes absent from ``statuses`` are left untouched.

    One atomic read-modify-write under the process lock; the disk write is
    skipped when no stamp changed. The caller supplies the clock so this
    layer keeps its no-clock-dependency convention.

    Concurrency: this is the manifest's second cross-process writer (the
    indexer's ``record_root`` is the first) under the file's whole-file
    last-writer-wins contract. The race is delete-safe by construction: a
    stamp lost to a concurrent ``record_root`` (which writes the field
    empty) restarts the grace window - protection can only be EXTENDED,
    never shortened - and a clobbered entry demotes its namespace to
    ``unknown``, which automation never touches.

    Args:
        statuses: Mapping of collection prefix to its survey status.
        now_iso: ISO-8601 timestamp to stamp on newly orphaned entries.

    Returns:
        Mapping of prefix to its ``first_seen_orphaned`` value after the
        update (empty string when clear), for every prefix in ``statuses``
        that has a manifest entry.
    """
    stamps: dict[str, str] = {}
    with _LOCK:
        entries = load_manifest()
        changed = False
        for prefix, status in statuses.items():
            entry = entries.get(prefix)
            if entry is None:
                continue
            if status == "orphaned":
                if not entry.first_seen_orphaned:
                    entry = ManifestEntry(
                        prefix=entry.prefix,
                        root=entry.root,
                        backend=entry.backend,
                        last_indexed=entry.last_indexed,
                        first_seen_orphaned=now_iso,
                        storage_schema_version=entry.storage_schema_version,
                        collections=entry.collections,
                    )
                    entries[prefix] = entry
                    changed = True
            elif entry.first_seen_orphaned:
                entry = ManifestEntry(
                    prefix=entry.prefix,
                    root=entry.root,
                    backend=entry.backend,
                    last_indexed=entry.last_indexed,
                    first_seen_orphaned="",
                    storage_schema_version=entry.storage_schema_version,
                    collections=entry.collections,
                )
                entries[prefix] = entry
                changed = True
            stamps[prefix] = entry.first_seen_orphaned
        if changed:
            _write_manifest(entries)
    return stamps


def rekey_prefix(
    old_prefix: str, *, root: Path | str, backend: str, last_indexed: str = ""
) -> ManifestEntry:
    """Move a manifest entry from ``old_prefix`` to ``root``'s current prefix.

    A backend change (server<->local) or a root move re-derives the prefix
    from the new root, so the old key no longer attributes the data. This
    drops the stale key and writes the entry under the freshly-derived
    prefix in one atomic read-modify-write, so attribution survives a
    migrate without leaving a dangling old key the survey would report as
    unknown.

    Args:
        old_prefix: The prefix the entry was stored under before the move.
        root: The root whose new prefix keys the entry.
        backend: ``"server"`` or ``"local"`` after the move.
        last_indexed: ISO-8601 timestamp to carry forward.

    Returns:
        The persisted :class:`ManifestEntry` under its new prefix.
    """
    resolved = str(Path(root).resolve())
    new_prefix = root_collection_prefix(root)
    entry = ManifestEntry(
        prefix=new_prefix,
        root=resolved,
        backend=backend,
        last_indexed=last_indexed,
        storage_schema_version=store_schema.STORAGE_SCHEMA_VERSION,
        collections=_declared_collections(new_prefix, backend),
    )
    with _LOCK:
        entries = load_manifest()
        if old_prefix != new_prefix:
            entries.pop(old_prefix, None)
        entries[new_prefix] = entry
        _write_manifest(entries)
    return entry


def reconcile_manifest(known_prefixes: set[str]) -> ReconcileResult:
    """Drop manifest entries whose root is gone and whose data is gone too.

    Called on service start (and after a root rename/move) to keep the
    manifest consistent with reality. An entry is dropped only when BOTH
    conditions hold: its recorded root no longer resolves to a live
    directory, AND no live collection on the server still carries its
    prefix. That conservative AND is the safety property - a stale manifest
    key whose data the operator already dropped is bookkeeping noise worth
    clearing, but an entry whose collections still exist (even if the source
    root moved) is preserved so the survey can still attribute that stored
    data rather than mislabel it ``unknown``. An ``unverifiable`` root (an
    offline volume) is always kept.

    Args:
        known_prefixes: The set of collection prefixes the live server
            currently backs (each stored collection's ``r{hash}_`` prefix).

    Returns:
        A :class:`ReconcileResult` naming the dropped and kept prefixes.
    """
    dropped: list[str] = []
    kept: list[str] = []
    with _LOCK:
        entries = load_manifest()
        survivors: dict[str, ManifestEntry] = {}
        for prefix, entry in entries.items():
            root_gone = classify_root(entry) == "orphaned"
            data_gone = prefix not in known_prefixes
            if root_gone and data_gone:
                dropped.append(prefix)
                continue
            survivors[prefix] = entry
            kept.append(prefix)
        if dropped:
            _write_manifest(survivors)
    return ReconcileResult(sorted(dropped), sorted(kept))
