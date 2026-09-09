"""Operator-only recovery of a complete archived server namespace."""

from __future__ import annotations

import json
import sys
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ._publication_state import clear_publication_state
from ._source_types import PublicSourceType
from ._store_models import root_collection_prefix
from ._store_writes import workspace_volume_path
from ._timestamps import parse_iso_timestamp
from .indexer._publication_proof import ProofEvidence
from .indexer._run_ledger_models import (
    FinalizationPhase,
    RunAuthority,
    RunOperation,
    RunSignature,
    RunTerminalState,
    index_run_ledger_path,
)
from .indexer._run_ledger_runtime import RunLedger
from .qdrant_runtime._constants import (
    WINDOWS_SERVER_ARCHIVE_RESTORE_UNSUPPORTED_REASON,
)
from .storage_manifest import record_restored_archive, snapshot_manifest_path
from .storage_survey import is_canonical_prefix
from .store_runtime import configured_backend_identity
from .store_schema import CollectionIdentity

if TYPE_CHECKING:
    from collections.abc import Callable

    from qdrant_client import QdrantClient


class ArchiveIntegrityError(RuntimeError):
    """An archive does not describe what it holds, or holds what it names.

    Distinct from a transport failure, which the operator surface otherwise
    conflates it with: both arrived here as a bare ``RuntimeError``, so an
    unreadable manifest or a missing artifact was reported as an unreachable
    server and answered with "start the service" - advice that is wrong, and
    that discards the only diagnostic saying which archive is broken.

    A ``RuntimeError`` still, so callers that already treat an archive read as
    fallible keep working unchanged; the subclass exists so the surface can
    tell the two conditions apart.
    """


#: The extension qdrant gives every snapshot it writes, and so the extension
#: an artifact in an archive directory carries.
_SNAPSHOT_SUFFIX = ".snapshot"


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
class ArchivedPublicationProof:
    """One canonical proof bound to the snapshot it certifies."""

    collection: str
    signature: RunSignature
    evidence: tuple[ProofEvidence, ...]


@dataclass(frozen=True)
class ArchiveRead:
    """The complete, read-only description of a restorable archive."""

    prefix: str
    schema_version: int
    collections: tuple[ArchivedCollection, ...]
    publication_proofs: tuple[ArchivedPublicationProof, ...]


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


def _archive_header(
    payload: dict[str, object], manifest_path: Path
) -> tuple[str, int, list[object], list[object]]:
    prefix = payload.get("prefix")
    version = payload.get("storage_schema_version")
    records = payload.get("collections")
    proofs = payload.get("publication_proofs")
    completed_at = payload.get("completed_at")
    if (
        not isinstance(prefix, str)
        or not is_canonical_prefix(prefix)
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version < 1
        or not isinstance(records, list)
        or not records
        or not isinstance(proofs, list)
        or parse_iso_timestamp(completed_at, field="archive completed_at") is None
    ):
        raise ArchiveIntegrityError(f"archive manifest is incomplete: {manifest_path}")
    return prefix, version, cast("list[object]", records), cast("list[object]", proofs)


def _validate_archive_proofs(
    collections: tuple[ArchivedCollection, ...],
    proofs: tuple[ArchivedPublicationProof, ...],
    manifest_path: Path,
) -> None:
    collection_names = {item.source for item in collections}
    proof_sources = {proof.signature.source_type for proof in proofs}
    proof_collections = {proof.collection for proof in proofs}
    if (
        len(proofs) != len(proof_sources)
        or len(proofs) != len(proof_collections)
        or not proof_collections.issubset(collection_names)
    ):
        raise ArchiveIntegrityError(
            f"archive publication proofs do not match its collections: {manifest_path}"
        )


def read_archive(archive_dir: Path) -> ArchiveRead:
    """Read a complete archive without creating collections or writing state."""
    manifest_path = snapshot_manifest_path(archive_dir)
    try:
        raw: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveIntegrityError(
            f"archive manifest is unreadable: {manifest_path}"
        ) from exc
    if not isinstance(raw, dict):
        raise ArchiveIntegrityError(f"archive manifest is invalid: {manifest_path}")
    payload = cast("dict[str, object]", raw)
    prefix, version, collection_records, proof_items = _archive_header(
        payload, manifest_path
    )
    collections = tuple(
        _read_collection(archive_dir, prefix, item, manifest_path)
        for item in collection_records
    )
    if len({item.source for item in collections}) != len(collections):
        raise ArchiveIntegrityError(
            f"archive manifest repeats a collection: {manifest_path}"
        )
    proofs = tuple(_read_publication_proof(item, manifest_path) for item in proof_items)
    _validate_archive_proofs(collections, proofs, manifest_path)
    _refuse_unnamed_snapshots(
        archive_dir,
        {item.snapshot.name for item in collections},
        manifest_path,
    )
    return ArchiveRead(prefix, version, collections, proofs)


def _read_collection(
    archive_dir: Path, prefix: str, value: object, manifest_path: Path
) -> ArchivedCollection:
    if not isinstance(value, dict):
        raise ArchiveIntegrityError(
            f"archive manifest has an invalid record: {manifest_path}"
        )
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
        raise ArchiveIntegrityError(
            f"archive manifest has an invalid record: {manifest_path}"
        )
    snapshot = archive_dir / filename
    try:
        if not snapshot.is_file() or snapshot.stat().st_size <= 0:
            raise ArchiveIntegrityError(
                f"archive snapshot is missing or empty: {snapshot}"
            )
    except OSError as exc:
        raise ArchiveIntegrityError(
            f"archive snapshot is unreadable: {snapshot}"
        ) from exc
    identity_raw = record.get("identity")
    identity = (
        None if identity_raw is None else CollectionIdentity.from_payload(identity_raw)
    )
    if identity_raw is not None and identity is None:
        raise ArchiveIntegrityError(f"archive identity is invalid: {manifest_path}")
    return ArchivedCollection(name, snapshot, points, identity)


def _required[T](payload: dict[str, object], key: str, kind: type[T]) -> T:
    value = payload.get(key)
    if not isinstance(value, kind):
        raise TypeError(f"{key} must be {kind.__name__}")
    return value


def _read_publication_proof(
    value: object,
    manifest_path: Path,
) -> ArchivedPublicationProof:
    """Decode one mandatory canonical proof export without accepting old shapes."""
    try:
        if not isinstance(value, dict):
            raise TypeError("proof record must be an object")
        record = cast("dict[str, object]", value)
        source = PublicSourceType(_required(record, "source", str))
        collection = _required(record, "collection", str)
        signature_value = record.get("signature")
        if not isinstance(signature_value, dict):
            raise TypeError("signature must be an object")
        signature_payload = cast("dict[str, object]", signature_value)
        signature = RunSignature(
            root_identity=_required(signature_payload, "root_identity", str),
            collection_identity=_required(
                signature_payload, "collection_identity", str
            ),
            source_type=PublicSourceType(
                _required(signature_payload, "source_type", str)
            ),
            operation=RunOperation(_required(signature_payload, "operation", str)),
            clean=_required(signature_payload, "clean", bool),
            model_identity=_required(signature_payload, "model_identity", str),
            dense_dimensions=_required(signature_payload, "dense_dimensions", int),
            embedding_schema=_required(signature_payload, "embedding_schema", int),
            payload_schema=_required(signature_payload, "payload_schema", int),
            content_epoch=_required(signature_payload, "content_epoch", str),
            membership_epoch=_required(signature_payload, "membership_epoch", str),
            preprocessing_identity=_required(
                signature_payload, "preprocessing_identity", str
            ),
            configuration_fingerprint=_required(
                signature_payload, "configuration_fingerprint", str
            ),
            policy_fingerprint=_required(signature_payload, "policy_fingerprint", str),
            backend_identity=_required(signature_payload, "backend_identity", str),
        )
        if source is PublicSourceType.COMBINED or signature.source_type is not source:
            raise ValueError("proof source disagrees with its signature")
        evidence_value = record.get("evidence")
        if not isinstance(evidence_value, list):
            raise TypeError("evidence must be a list")
        evidence_raw = cast("list[object]", evidence_value)
        evidence: list[ProofEvidence] = []
        for item in evidence_raw:
            if not isinstance(item, dict):
                raise TypeError("proof evidence must be an object")
            row = cast("dict[str, object]", item)
            point_ids_value = row.get("point_ids")
            if not isinstance(point_ids_value, list):
                raise TypeError("point_ids must be a list")
            point_ids = cast("list[object]", point_ids_value)
            if any(not isinstance(point_id, str) for point_id in point_ids):
                raise TypeError("proof point_ids must contain strings")
            evidence.append(
                ProofEvidence(
                    rel_path=_required(row, "rel_path", str),
                    content_identity=_required(row, "content_identity", str),
                    point_ids=tuple(cast("list[str]", point_ids)),
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise ArchiveIntegrityError(
            f"archive publication proof is invalid: {manifest_path}"
        ) from exc
    return ArchivedPublicationProof(collection, signature, tuple(evidence))


def _restore_publication_proofs(
    destination_root: Path,
    proofs: tuple[ArchivedPublicationProof, ...],
) -> None:
    """Publish restored proof only after every collection recovery succeeds."""
    resolved = destination_root.resolve()
    ledger = RunLedger(index_run_ledger_path(workspace_volume_path(resolved)))
    backend_identity = configured_backend_identity(resolved)
    for proof in proofs:
        signature = replace(
            proof.signature,
            root_identity=str(resolved),
            backend_identity=backend_identity,
            operation=RunOperation.FULL,
            clean=True,
        )
        generation = ledger.start_generation(signature)
        ledger.establish_verified_publication(
            generation.generation_id,
            RunAuthority.REBUILD,
            proof.evidence,
        )
        for phase in (
            FinalizationPhase.STALE_RECONCILED,
            FinalizationPhase.METADATA_PUBLISHED,
            FinalizationPhase.GENERATION_PUBLISHED,
        ):
            ledger.advance_finalization(generation.generation_id, phase)
        ledger.finish_generation(
            generation.generation_id,
            RunTerminalState.SUCCEEDED,
        )


def _refuse_unnamed_snapshots(
    archive_dir: Path, referenced: set[str], manifest_path: Path
) -> None:
    """Refuse an archive holding snapshot artifacts its manifest does not name.

    Recovery is driven entirely by the manifest: the destination names, the
    point counts, the provenance and the reported collection list are all
    built from its records, and nothing is ever compared against what the
    directory actually holds. An artifact the manifest omits is therefore not
    restored, not reported, and not distinguishable in the result from an
    archive that never held it - the operator recovers a subset of the
    namespace and is told the count of what was named.

    That is the one failure shape a reader cannot be expected to catch, which
    is why it is refused here rather than warned about. Half a namespace
    recovered under a success message is worse than a recovery that stopped
    and said which files it could not account for.

    A second guard on the archiver's merge, and deliberately independent of
    it: it holds if that merge is regretted or regressed, if a retention
    sweep half-removed a directory, or if an archive was assembled by hand.

    Scoped to snapshot artifacts because those are the files that carry data.
    A note or a checksum left beside them is not half a namespace, and
    stopping a recovery over one would be its own failure.
    """
    try:
        present = sorted(
            path.name
            for path in archive_dir.iterdir()
            if path.is_file() and path.suffix == _SNAPSHOT_SUFFIX
        )
    except OSError as exc:
        raise ArchiveIntegrityError(
            f"archive directory is unreadable: {archive_dir}"
        ) from exc
    unnamed = [name for name in present if name not in referenced]
    if unnamed:
        raise ArchiveIntegrityError(
            "archive holds snapshot artifacts its manifest does not name: "
            f"{', '.join(unnamed)} beside {manifest_path}"
        )


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
    if request.dry_run or sys.platform == "win32":
        return (
            RestoreResult("would_restore", destination, names)
            if request.dry_run
            else RestoreResult(
                "refused",
                destination,
                names,
                WINDOWS_SERVER_ARCHIVE_RESTORE_UNSUPPORTED_REASON,
            )
        )
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
        _restore_publication_proofs(
            request.destination_root, archive.publication_proofs
        )
        record_restored_archive(
            request.destination_root,
            storage_schema_version=archive.schema_version,
            collections=names,
            identities=identities,
        )
    except Exception:
        backend_identity = configured_backend_identity(
            request.destination_root.resolve()
        )
        for proof in archive.publication_proofs:
            with suppress(OSError, RuntimeError):
                clear_publication_state(
                    request.destination_root,
                    proof.signature.source_type,
                    backend_identity,
                )
        for name in reversed(restored):
            with suppress(OSError, RuntimeError):
                client.delete_collection(collection_name=name)
        raise
    return RestoreResult("restored", destination, names)
