"""Service-domain storage collection migration operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, Unpack, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from qdrant_client import QdrantClient


def _no_progress(_line: str) -> None:
    """Drop a progress line when the caller has no reporting surface."""


class _MigrationOptions(TypedDict, total=False):
    dry_run: bool
    batch_size: int
    on_progress: Callable[[str], None]


@dataclass(frozen=True)
class _MigrationRequest:
    src_client: QdrantClient
    dst_client: QdrantClient
    name_map: dict[str, str]
    dry_run: bool
    batch_size: int = 256
    on_progress: Callable[[str], None] = _no_progress


@dataclass(frozen=True)
class MigrateResult:
    """Outcome of migrating one collection between backends.

    Attributes:
        source: Source collection name.
        target: Target collection name (may differ: prefix remap).
        status: ``migrated`` / ``would_migrate`` / ``skipped`` / ``failed``.
        points: Points copied (or that would be), verified by count.
        reason: Why skipped or failed, else ``None``.
    """

    source: str
    target: str
    status: str
    points: int = 0
    reason: str | None = None


def _copy_collection(
    src_client: QdrantClient,
    dst_client: QdrantClient,
    source: str,
    target: str,
    batch_size: int,
) -> int:
    """Recreate ``target`` from ``source``'s schema and copy all points.

    Returns the destination point count after the copy. Recreates the
    named dense + sparse vector schema from the source config (payload
    indexes are re-added by the store's ``ensure_*`` on next open), then
    pages ``scroll(with_vectors=True)`` into ``upload_points``.
    """
    from qdrant_client import models

    config = src_client.get_collection(source).config
    dst_client.create_collection(
        collection_name=target,
        vectors_config=config.params.vectors,
        sparse_vectors_config=config.params.sparse_vectors,
    )
    offset = None
    while True:
        records, offset = src_client.scroll(
            collection_name=source,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if records:
            dst_client.upload_points(
                collection_name=target,
                points=[
                    models.PointStruct(
                        id=record.id,
                        # scroll returns the *output* vector type; PointStruct
                        # wants the *input* type. They are runtime-identical
                        # (named dense + sparse dict), so the cast is a stub
                        # reconciliation, not a behavioural change.
                        vector=cast("models.VectorStruct", record.vector or {}),
                        payload=record.payload,
                    )
                    for record in records
                ],
                wait=True,
            )
        if offset is None:
            break
    return int(dst_client.count(collection_name=target).count)


def migrate_collections(
    src_client: QdrantClient,
    dst_client: QdrantClient,
    name_map: dict[str, str],
    **options: Unpack[_MigrationOptions],
) -> list[MigrateResult]:
    """Migrate collections from one backend to another, remapping names."""
    return _migrate_collections(
        _MigrationRequest(src_client, dst_client, name_map, **options)
    )


def _migrate_collections(request: _MigrationRequest) -> list[MigrateResult]:
    """Migrate collections from one backend to another, remapping names.

    ``name_map`` maps each source collection name to its target name (the
    prefix remap between bare local names and ``r{hash}_`` server names).
    Recreates each target's schema from the source, copies all points, and
    verifies the destination count equals the source. A pre-existing
    target is skipped (never silently overwritten).

    Args:
        src_client: Source backend client.
        dst_client: Destination backend client.
        name_map: Source-name to target-name mapping.
        dry_run: When True, return the plan and mutate nothing.
        batch_size: Scroll/upload page size.
        on_progress: Sink for progress lines, one per mapped collection; a
            real copy moves every point across two backends and is the
            longest-running of the storage verbs.

    Returns:
        One :class:`MigrateResult` per mapped collection.
    """
    src_client, dst_client, name_map, dry_run, batch_size, on_progress = (
        request.src_client,
        request.dst_client,
        request.name_map,
        request.dry_run,
        request.batch_size,
        request.on_progress,
    )
    results: list[MigrateResult] = []
    for position, (source, target) in enumerate(name_map.items(), start=1):
        on_progress(f"Migrating {position}/{len(name_map)}: {source} -> {target}")
        if not src_client.collection_exists(source):
            results.append(
                MigrateResult(source, target, "skipped", reason="no_such_source")
            )
            continue
        expected = int(src_client.count(collection_name=source).count)
        if dst_client.collection_exists(target):
            results.append(
                MigrateResult(source, target, "skipped", expected, "target_exists")
            )
            continue
        if dry_run:
            results.append(MigrateResult(source, target, "would_migrate", expected))
            continue
        try:
            copied = _copy_collection(
                src_client, dst_client, source, target, batch_size
            )
        except (OSError, RuntimeError, ValueError) as exc:
            results.append(MigrateResult(source, target, "failed", reason=str(exc)))
            continue
        status = "migrated" if copied == expected else "failed"
        reason = None if copied == expected else f"count_mismatch:{copied}!={expected}"
        results.append(MigrateResult(source, target, status, copied, reason))
    return results


def carry_migrated_identity(
    root: Path | str,
    *,
    name_map: dict[str, str],
    to_backend: str,
    local_dir: Path | str,
    results: list[MigrateResult],
) -> list[str]:
    """Carry each migrated collection's source identity onto its target name.

    A migrate replays the source's vector geometry verbatim but creates the
    target through the raw client, so nothing stamps it: the destination lands
    with no identity at all and every later verdict on it reads
    ``unverifiable`` even though the source's provenance was known. Re-stamping
    it with current values would be worse - it would assert that this process
    produced vectors it only copied - so the source's own record is what moves.

    The two homes are keyed differently and the migrate remaps names, which is
    why this cannot ride along on the manifest re-key: that carries the identity
    map verbatim, under the *source* collection names, which nothing will ever
    look up under the target's. Reads and writes both go through the
    backend-dispatching accessors, so neither home is reached directly here.

    Call before re-keying the manifest, so the source home is still intact.

    Args:
        root: The workspace root whose index moved; both homes are keyed by it.
        name_map: The same source-to-target mapping the migrate ran on.
        to_backend: ``"server"`` or ``"local"`` - the destination backend.
        local_dir: The root's own local store directory. It is the source home
            when migrating to server and the target home when migrating to
            local; the server side needs no path.
        results: The migrate's own results; only ``migrated`` pairs are carried,
            so a skipped or failed copy never gains provenance.

    Returns:
        The target collection names whose identity is readable after the carry,
        confirmed by reading it back rather than assumed - the stamp itself is
        best-effort and swallows its failures.
    """
    from .storage_identity import load_identity, record_identity

    from_backend = "local" if to_backend == "server" else "server"
    from_local = local_dir if from_backend == "local" else None
    to_local = local_dir if to_backend == "local" else None
    moved = {r.source for r in results if r.status == "migrated"}
    carried: list[str] = []
    for source, target in name_map.items():
        if source not in moved:
            continue
        identity = load_identity(
            root, backend=from_backend, collection=source, local_dir=from_local
        )
        if identity is None:
            # The source predates stamping. Recording nothing keeps the
            # destination honestly unverifiable instead of manufacturing a
            # provenance neither collection ever had.
            continue
        record_identity(
            root,
            backend=to_backend,
            collection=target,
            identity=identity,
            local_dir=to_local,
        )
        if (
            load_identity(
                root, backend=to_backend, collection=target, local_dir=to_local
            )
            is not None
        ):
            carried.append(target)
    return carried
