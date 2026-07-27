"""Operator-only recovery of a complete archived server namespace."""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ._store_models import root_collection_prefix
from ._timestamps import parse_iso_timestamp
from .storage_manifest import record_restored_archive, snapshot_manifest_path
from .storage_survey import is_canonical_prefix
from .store_schema import CollectionIdentity

if TYPE_CHECKING:
    from collections.abc import Callable

    from qdrant_client import QdrantClient


def _no_progress(_line: str) -> None:
    """Drop a progress line when no operator surface is attached."""


@dataclass(frozen=True)
class ArchivedCollection:
    """One verified snapshot artifact and its preserved provenance."""

    source: str
    snapshot: Path
    points: int
    identity: CollectionIdentity | None


@dataclass(frozen=True)
class ArchiveRead:
    """The complete, read-only description of a restorable archive."""

    prefix: str
    schema_version: int
    collections: tuple[ArchivedCollection, ...]


@dataclass(frozen=True)
class RestoreResult:
    """One archive restore outcome, including the exact destination list."""

    status: str
    destination_prefix: str
    collections: tuple[str, ...]
    reason: str | None = None


@dataclass(frozen=True)
class RestoreRequest:
    """Operator-selected archive destination and preview controls."""

    archive_dir: Path
    destination_root: Path
    local_mode: bool
    dry_run: bool


def read_archive(archive_dir: Path) -> ArchiveRead:
    """Read a complete archive without creating collections or writing state."""
    manifest_path = snapshot_manifest_path(archive_dir)
    try:
        raw: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"archive manifest is unreadable: {manifest_path}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"archive manifest is invalid: {manifest_path}")
    payload = cast("dict[str, object]", raw)
    prefix = payload.get("prefix")
    version = payload.get("storage_schema_version")
    records = payload.get("collections")
    completed_at = payload.get("completed_at")
    if (
        not isinstance(prefix, str)
        or not is_canonical_prefix(prefix)
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version < 1
        or not isinstance(records, list)
        or not records
        or parse_iso_timestamp(completed_at, field="archive completed_at") is None
    ):
        raise RuntimeError(f"archive manifest is incomplete: {manifest_path}")
    collection_records = cast("list[object]", records)
    collections = tuple(
        _read_collection(archive_dir, prefix, item, manifest_path)
        for item in collection_records
    )
    if len({item.source for item in collections}) != len(collections):
        raise RuntimeError(f"archive manifest repeats a collection: {manifest_path}")
    _read_metadata_files(archive_dir, payload.get("metadata_files"), manifest_path)
    return ArchiveRead(prefix, version, collections)


def _read_collection(
    archive_dir: Path, prefix: str, value: object, manifest_path: Path
) -> ArchivedCollection:
    if not isinstance(value, dict):
        raise RuntimeError(f"archive manifest has an invalid record: {manifest_path}")
    record = cast("dict[str, object]", value)
    name, filename, points = (
        record.get("name"),
        record.get("snapshot_file"),
        record.get("points"),
    )
    if (
        not isinstance(name, str)
        or not name.startswith(prefix)
        or not isinstance(filename, str)
        or Path(filename).name != filename
        or isinstance(points, bool)
        or not isinstance(points, int)
        or points < 0
    ):
        raise RuntimeError(f"archive manifest has an invalid record: {manifest_path}")
    snapshot = archive_dir / filename
    try:
        if not snapshot.is_file() or snapshot.stat().st_size <= 0:
            raise RuntimeError(f"archive snapshot is missing or empty: {snapshot}")
    except OSError as exc:
        raise RuntimeError(f"archive snapshot is unreadable: {snapshot}") from exc
    identity_raw = record.get("identity")
    identity = (
        None if identity_raw is None else CollectionIdentity.from_payload(identity_raw)
    )
    if identity_raw is not None and identity is None:
        raise RuntimeError(f"archive identity is invalid: {manifest_path}")
    return ArchivedCollection(name, snapshot, points, identity)


def _read_metadata_files(archive_dir: Path, value: object, manifest_path: Path) -> None:
    if not isinstance(value, list):
        raise RuntimeError(f"archive manifest is incomplete: {manifest_path}")
    metadata_files = cast("list[object]", value)
    for filename in metadata_files:
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise RuntimeError(
                f"archive manifest has invalid metadata: {manifest_path}"
            )
        artifact = archive_dir / filename
        if not artifact.is_file():
            raise RuntimeError(f"archive metadata is missing: {artifact}")


def restore_archive(
    client: QdrantClient,
    request: RestoreRequest,
    *,
    on_progress: Callable[[str], None] = _no_progress,
) -> RestoreResult:
    """Recover one verified archive into an empty destination namespace."""
    if request.local_mode:
        return RestoreResult("refused", "", (), "local_mode_unsupported")
    archive = read_archive(request.archive_dir)
    destination = root_collection_prefix(request.destination_root)
    if not is_canonical_prefix(destination):
        return RestoreResult("refused", destination, (), "invalid_destination_prefix")
    names = tuple(
        destination + item.source.removeprefix(archive.prefix)
        for item in archive.collections
    )
    if any(name == destination for name in names):
        return RestoreResult(
            "refused", destination, names, "invalid_archive_collection"
        )
    existing = tuple(
        collection.name
        for collection in client.get_collections().collections
        if collection.name.startswith(destination)
    )
    if existing:
        return RestoreResult("refused", destination, names, "destination_exists")
    if request.dry_run:
        return RestoreResult("would_restore", destination, names)
    restored: list[str] = []
    try:
        from qdrant_client.http import models

        for item, name in zip(archive.collections, names, strict=True):
            on_progress(f"Restoring {item.source} -> {name}")
            # Recovery can create the collection before its response crosses
            # the transport boundary. Register it first so every such failure
            # is cleaned up under the already-empty destination preflight.
            restored.append(name)
            with item.snapshot.open("rb") as snapshot:
                client.http.snapshots_api.recover_from_uploaded_snapshot(
                    collection_name=name,
                    wait=True,
                    priority=models.SnapshotPriority.SNAPSHOT,
                    snapshot=snapshot,
                )
        identities = {
            name: item.identity
            for item, name in zip(archive.collections, names, strict=True)
            if item.identity is not None
        }
        record_restored_archive(
            request.destination_root,
            storage_schema_version=archive.schema_version,
            collections=names,
            identities=identities,
        )
    except Exception:
        for name in reversed(restored):
            with suppress(OSError, RuntimeError):
                client.delete_collection(collection_name=name)
        raise
    return RestoreResult("restored", destination, names)
