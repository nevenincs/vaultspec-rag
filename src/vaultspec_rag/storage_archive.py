"""Archiving a storage namespace, and sweeping the archives that result.

Reclamation destroys data-bearing namespaces, and is only allowed to do so
once the data is provably somewhere else. That makes archiving a precondition
of the drop rather than a step beside it: every failure here raises, so the
caller never reaches a delete for data it did not manage to preserve.

Read-and-write over snapshot directories only. Nothing here reaches a service
lifecycle helper, and nothing decides WHETHER to reclaim - that judgement, and
the drop it authorizes, belong to the reclamation module that calls in here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

from . import store_schema
from ._atomic_write import replace_atomically
from ._publication_state import (
    PublicationSnapshot,
    acquire_publication_snapshot,
    read_all_publication_evidence,
)
from ._rmtree import remove_tree
from ._source_types import PublicSourceType
from ._store_models import read_served_pointer
from ._timestamps import parse_iso_timestamp
from .indexer._publication_proof import ProofUnverifiableError
from .storage_manifest import (
    SnapshotCollection,
    SnapshotPublicationProof,
    StorageSnapshotManifest,
    load_manifest,
    snapshot_manifest_path,
    write_snapshot_manifest,
)
from .storage_survey_ops import directory_size_bytes

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

#: The extension qdrant gives every snapshot it writes, and so the one an
#: artifact in an archive directory carries.
_SNAPSHOT_SUFFIX = ".snapshot"


def _active_publication_collections(
    root: Path,
    prefix: str,
    collections: list[str],
) -> dict[PublicSourceType, str]:
    available = set(collections)
    active = {
        PublicSourceType.VAULT: prefix + store_schema.VAULT_COLLECTION,
        PublicSourceType.DOCUMENT: prefix + store_schema.DOCUMENT_COLLECTION,
    }
    pointer = read_served_pointer(root)
    if not pointer.verifiable:
        raise RuntimeError("cannot archive code without a verifiable served pointer")
    active[PublicSourceType.CODE] = (
        pointer.collection or prefix + store_schema.CODE_COLLECTION
    )
    return {source: name for source, name in active.items() if name in available}


def _export_publication_proofs(
    root: Path,
    prefix: str,
    collections: list[str],
) -> tuple[tuple[SnapshotPublicationProof, ...], tuple[PublicationSnapshot, ...]]:
    """Read and fence every proof required to make an archive restorable."""
    exports: list[SnapshotPublicationProof] = []
    snapshots: list[PublicationSnapshot] = []
    active = _active_publication_collections(root, prefix, collections)
    for source, collection in active.items():
        try:
            snapshot = acquire_publication_snapshot(root, source)
        except ProofUnverifiableError:
            # The source root and its per-root ledger may already be gone.
            # Archive the physical collection without inventing authority;
            # restore leaves it unreadable until an explicit rebuild.
            continue
        evidence = read_all_publication_evidence(snapshot)
        generation = snapshot.ledger.generation(snapshot.proof.generation_id)
        exports.append(
            SnapshotPublicationProof(
                source=source.value,
                collection=collection,
                signature=cast(
                    "dict[str, object]", json.loads(generation.signature.canonical_json)
                ),
                evidence=tuple(
                    {
                        "rel_path": item.rel_path,
                        "content_identity": item.content_identity,
                        "point_ids": list(item.point_ids),
                    }
                    for item in evidence.values()
                ),
            )
        )
        snapshots.append(snapshot)
    return tuple(exports), tuple(snapshots)


def archive_prefix(
    client: QdrantClient,
    prefix: str,
    *,
    snapshots_dir: Path,
    archive_dir: Path,
) -> list[Path]:
    """Snapshot every collection of ``prefix`` into the archive dir.

    Creates a server-side snapshot per collection (``wait=True``), then
    moves the snapshot file from the server's snapshots tree into
    ``archive_dir/{prefix}/``. Any failure raises so the caller can refuse
    the subsequent drop - a point-bearing namespace is never destroyed
    without its archive completing first.

    Args:
        client: Qdrant client for the managed server.
        prefix: The namespace prefix to archive.
        snapshots_dir: The server's snapshots tree (where qdrant writes).
        archive_dir: The bounded archive destination.

    Returns:
        The archived snapshot paths.
    """
    targets = sorted(
        c.name
        for c in client.get_collections().collections
        if c.name.startswith(prefix)
    )
    dest_dir = archive_dir / prefix.rstrip("_")
    dest_dir.mkdir(parents=True, exist_ok=True)
    archived: list[Path] = []
    collection_artifacts: list[SnapshotCollection] = []
    # Read before the snapshots, because the drop that follows a successful
    # archive removes the entry these records live in. Absent identity stays
    # absent: an archive of an unstamped collection records no provenance
    # rather than the current process's, which never touched those vectors.
    entry = load_manifest().get(prefix)
    if entry is None:
        raise RuntimeError(f"cannot archive unattributed namespace: {prefix}")
    publication_proofs, proof_snapshots = _export_publication_proofs(
        Path(entry.root), prefix, targets
    )
    identities = entry.collection_identity
    for name in targets:
        points = int(client.count(collection_name=name).count)
        description = client.create_snapshot(collection_name=name, wait=True)
        if description is None or not description.name:
            raise RuntimeError(f"snapshot creation returned no name for {name}")
        source = snapshots_dir / name / description.name
        if not source.is_file():
            raise RuntimeError(f"snapshot file not found: {source}")
        dest = dest_dir / description.name
        replace_atomically(source, dest)
        archived.append(dest)
        collection_artifacts.append(
            SnapshotCollection(
                name=name,
                snapshot_file=dest.name,
                points=points,
                identity=identities.get(name),
            )
        )
    point_count_by_collection = {
        item.name: item.points for item in collection_artifacts
    }
    for export, snapshot in zip(publication_proofs, proof_snapshots, strict=True):
        proof = snapshot.proof
        if (
            point_count_by_collection[export.collection]
            != proof.aggregate.retained_points
        ):
            raise RuntimeError(
                "cannot archive a collection whose live count disagrees with its proof"
            )
        snapshot.validate()
    carried = _carry_prior_archive_records(dest_dir, fresh=collection_artifacts)
    manifest_path = write_snapshot_manifest(
        dest_dir,
        StorageSnapshotManifest(
            prefix=prefix,
            root=entry.root,
            storage_schema_version=entry.storage_schema_version,
            collections=tuple(
                sorted([*collection_artifacts, *carried], key=lambda item: item.name)
            ),
            publication_proofs=publication_proofs,
        ),
    )
    _drop_unnamed_snapshots(dest_dir, manifest_path)
    _verify_completed_archive(
        client,
        dest_dir,
        manifest_path,
        live_names=frozenset(item.name for item in collection_artifacts),
    )
    archived.append(manifest_path)
    return archived


def _carry_prior_archive_records(
    dest_dir: Path,
    *,
    fresh: Sequence[SnapshotCollection],
) -> tuple[SnapshotCollection, ...]:
    """Return the records an earlier attempt left that this one must keep naming.

    The archive destination is fixed per namespace and the manifest is
    published in place, so a second attempt that wrote only its own records
    would unname the first attempt's. That matters because the retry after a
    partial drop is the designed path: the survey behind it sees only what
    survived, so the collections the first attempt destroyed would be left
    sitting in the archive under no manifest at all - present on disk, named
    by nothing, and invisible to a restore that is driven entirely by the
    manifest. The operator recovers half the namespace and is told it is
    whole.

    Three rules, each a different way a carried record could lie:

    - A name this attempt archived wins outright. The collection is alive and
      has just been re-snapshotted, so the older artifact describes vectors
      that are no longer the current ones.
    - A record whose artifact is no longer on disk is dropped rather than
      carried. Republishing the name of a file that is gone would produce a
      manifest no restore could satisfy.
    - A record whose file this attempt rewrote under the same name is dropped
      for the same reason as the first: the bytes are no longer the ones its
      point count describes.

    Dropping a record leaves its file behind, and the sweep after the
    manifest is published is what removes it.
    """
    manifest_path = snapshot_manifest_path(dest_dir)
    if not manifest_path.is_file():
        return ()
    prior = _read_archive_manifest(manifest_path)
    fresh_names = {item.name for item in fresh}
    written_files = {item.snapshot_file for item in fresh}
    return tuple(
        record
        for record in prior.collections
        if record.snapshot_file not in written_files
        and record.name not in fresh_names
        and (dest_dir / record.snapshot_file).is_file()
    )


def _drop_unnamed_snapshots(dest_dir: Path, manifest_path: Path) -> None:
    """Leave the archive directory holding exactly what its manifest names.

    A restore refuses a directory carrying a snapshot its manifest does not
    name, because such a file is data recovery would silently omit. Publishing
    a manifest is therefore only half of completing an archive: the other half
    is that nothing else is left beside it.

    Two things produce such a file, and one rule removes both. An attempt that
    raised part-way through has already moved snapshots into the directory
    under no manifest at all, and the next attempt takes fresh ones under
    fresh names rather than adopting them. A collection re-archived while
    still alive leaves the copy it superseded. Neither is data: the first was
    never published, and the second has just been replaced by a newer snapshot
    of the same live collection.

    Only snapshot artifacts. A note or a checksum an operator left here is not
    this function's to remove, and a restore does not refuse over one either.

    Raises rather than shrugging. A file that cannot be removed stays unnamed,
    which is the condition a restore refuses, so failing the archive here
    defers the namespace instead of destroying more of it into a directory
    recovery would go on to reject.
    """
    named = {
        record.snapshot_file
        for record in _read_archive_manifest(manifest_path).collections
    }
    try:
        stale = [
            path
            for path in dest_dir.iterdir()
            if path.is_file()
            and path.suffix == _SNAPSHOT_SUFFIX
            and path.name not in named
        ]
    except OSError as exc:
        raise RuntimeError(f"archive directory is unreadable: {dest_dir}") from exc
    for path in stale:
        try:
            path.unlink()
        except OSError as exc:
            message = f"unnamed archive snapshot could not be removed: {path}"
            raise RuntimeError(message) from exc


def _verify_completed_archive(
    client: QdrantClient,
    archive_dir: Path,
    manifest_path: Path,
    *,
    live_names: frozenset[str],
) -> None:
    """Re-read a completed archive and prove it still describes live data.

    Every record is checked for its artifact, because a manifest naming a file
    that is not there is not a completed archive. The point re-count is asked
    only of the collections this call archived: a record carried over from an
    earlier attempt describes a collection the drop that followed it already
    destroyed, and counting one that no longer exists would fail the archive
    for having preserved it.
    """
    for record in _read_archive_manifest(manifest_path).collections:
        artifact = archive_dir / record.snapshot_file
        if artifact.parent != archive_dir or not artifact.is_file():
            raise RuntimeError(f"archived snapshot file not found: {artifact}")
        try:
            if artifact.stat().st_size <= 0:
                raise RuntimeError(f"archived snapshot file is empty: {artifact}")
        except OSError as exc:
            message = f"archived snapshot file is unreadable: {artifact}"
            raise RuntimeError(message) from exc
        if record.name not in live_names:
            continue
        current_points = int(client.count(collection_name=record.name).count)
        if current_points != record.points:
            raise RuntimeError(
                f"archived snapshot point count changed for {record.name}: "
                f"expected {record.points}, found {current_points}"
            )


def _read_archive_manifest(manifest_path: Path) -> StorageSnapshotManifest:
    """Load a non-empty completed archive manifest, whole.

    One reader for the persisted form, because the two callers ask the same
    question of it. Verification needs the records to prove they still stand
    up; a re-archive needs them and their provenance to decide what it must
    keep naming, and a merge that read the records through a narrower view
    would silently drop the provenance it was preserving.
    """
    try:
        if manifest_path.stat().st_size <= 0:
            raise RuntimeError(f"archive manifest is empty: {manifest_path}")
        payload: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"archive manifest is unreadable: {manifest_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"archive manifest is invalid: {manifest_path}")
    fields = cast("dict[str, object]", payload)
    raw_records = fields.get("collections")
    if not isinstance(raw_records, list):
        message = f"archive manifest has no collection records: {manifest_path}"
        raise RuntimeError(message)
    records = cast("list[object]", raw_records)
    prefix = fields.get("prefix")
    root = fields.get("root")
    version = fields.get("storage_schema_version")
    if (
        not isinstance(prefix, str)
        or (root is not None and not isinstance(root, str))
        or isinstance(version, bool)
        or not isinstance(version, int)
    ):
        raise RuntimeError(f"archive manifest is invalid: {manifest_path}")
    return StorageSnapshotManifest(
        prefix=prefix,
        root=root,
        storage_schema_version=version,
        collections=tuple(_archive_record(record, manifest_path) for record in records),
        publication_proofs=_archive_publication_proofs(
            fields.get("publication_proofs"), manifest_path
        ),
    )


def _archive_record(record: object, manifest_path: Path) -> SnapshotCollection:
    """Validate one persisted snapshot record before using its file name."""
    if not isinstance(record, dict):
        raise RuntimeError(f"archive manifest has an invalid record: {manifest_path}")
    fields = cast("dict[str, object]", record)
    name = fields.get("name")
    snapshot_file = fields.get("snapshot_file")
    points = fields.get("points")
    if (
        not isinstance(name, str)
        or not isinstance(snapshot_file, str)
        or Path(snapshot_file).name != snapshot_file
        or isinstance(points, bool)
        or not isinstance(points, int)
        or points < 0
    ):
        raise RuntimeError(f"archive manifest has an invalid record: {manifest_path}")
    identity_payload = fields.get("identity")
    identity = (
        None
        if identity_payload is None
        else store_schema.CollectionIdentity.from_payload(identity_payload)
    )
    if identity_payload is not None and identity is None:
        # Carried verbatim or not at all. Re-publishing this record with the
        # provenance stripped would turn a corrupt archive into one that reads
        # as merely unstamped, which is a claim about the vectors nobody made.
        raise RuntimeError(f"archive identity is invalid: {manifest_path}")
    return SnapshotCollection(
        name=name, snapshot_file=snapshot_file, points=points, identity=identity
    )


def _archive_publication_proofs(
    value: object, manifest_path: Path
) -> tuple[SnapshotPublicationProof, ...]:
    """Carry the persisted proof exports verbatim, or refuse the manifest.

    Read whole rather than narrowly for the same reason the collection records
    are: a re-archive republishes what it reads, so a proof this reader
    flattened would be a certificate the next manifest no longer carries.
    """
    if not isinstance(value, list):
        raise RuntimeError(f"archive manifest is invalid: {manifest_path}")
    records = cast("list[object]", value)
    proofs: list[SnapshotPublicationProof] = []
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError(f"archive proof is invalid: {manifest_path}")
        fields = cast("dict[str, object]", record)
        source = fields.get("source")
        collection = fields.get("collection")
        signature = fields.get("signature")
        evidence = fields.get("evidence")
        if (
            not isinstance(source, str)
            or not isinstance(collection, str)
            or not isinstance(signature, dict)
            or not isinstance(evidence, list)
        ):
            raise RuntimeError(f"archive proof is invalid: {manifest_path}")
        rows = cast("list[object]", evidence)
        if any(not isinstance(row, dict) for row in rows):
            raise RuntimeError(f"archive proof is invalid: {manifest_path}")
        proofs.append(
            SnapshotPublicationProof(
                source=source,
                collection=collection,
                signature=cast("dict[str, object]", signature),
                evidence=tuple(cast("list[dict[str, object]]", rows)),
            )
        )
    return tuple(proofs)


def sweep_archive(
    archive_dir: Path,
    *,
    now: datetime,
    retention_days: float,
    max_total_bytes: int,
) -> list[Path]:
    """Delete expired archives, then evict oldest-first past the byte cap.

    Args:
        archive_dir: The archive tree to bound. Missing dir is a no-op.
        now: The evaluation clock (timezone-aware).
        retention_days: Age past which a completed archive is deleted.
        max_total_bytes: Total-byte cap after age-based deletion.

    Returns:
        The deleted archive-directory paths.
    """
    if not archive_dir.is_dir():
        return []
    archives = _archive_directories(archive_dir)
    deleted: list[Path] = []
    cutoff = now.timestamp() - retention_days * 86400.0
    kept: list[tuple[float, int, Path]] = []
    for mtime, size, path in archives:
        if mtime < cutoff:
            if _delete_archive_directory(path):
                deleted.append(path)
            else:
                kept.append((mtime, size, path))
        else:
            kept.append((mtime, size, path))
    total = sum(size for _, size, _ in kept)
    for _mtime, size, path in sorted(kept, key=lambda item: item[0]):
        if total <= max_total_bytes:
            break
        if _delete_archive_directory(path):
            deleted.append(path)
            total -= size
    return deleted


def _archive_directories(archive_dir: Path) -> list[tuple[float, int, Path]]:
    """Measure direct completed archive directories by their manifest clock."""
    archives: list[tuple[float, int, Path]] = []
    for path in archive_dir.iterdir():
        if not path.is_dir() or path.is_symlink():
            continue
        completed_at = _archive_completion_timestamp(path)
        if completed_at is None:
            continue
        archives.append((completed_at, directory_size_bytes(path), path))
    return archives


def _archive_completion_timestamp(archive: Path) -> float | None:
    """Return one archive's persisted completion clock, never a file mtime."""
    manifest = snapshot_manifest_path(archive)
    try:
        payload: object = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    manifest_payload = cast("dict[str, object]", payload)
    completed_at = parse_iso_timestamp(
        manifest_payload.get("completed_at"),
        field="archive completed_at",
    )
    return None if completed_at is None else completed_at.timestamp()


def _delete_archive_directory(archive: Path) -> bool:
    """Delete an entire archive directory, returning whether it succeeded."""
    try:
        remove_tree(archive)
    except OSError:
        return False
    return True
