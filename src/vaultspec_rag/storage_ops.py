"""Service-domain storage lifecycle operations: survey, delete, prune.

The supervising daemon is the authority on stored data, so these
functions execute against the managed Qdrant server (a ``QdrantClient``)
plus the on-disk storage tree and the persisted prefix-to-root manifest.
The CLI ``server storage`` group and the storage HTTP routes are thin
adapters over these functions; they must not reimplement the logic.

Every destructive function:

- supports a ``dry_run`` preview that returns the exact target list and
  performs no mutation;
- reports through the sync vocabulary (``removed`` / ``skipped`` /
  ``failed``);
- refuses to act on an ``unknown`` namespace (one whose prefix the
  manifest cannot attribute to a root) - those are reported, never
  auto-deleted, because removing unattributable data could destroy a live
  index. ``prune`` targets only ``orphaned`` namespaces (manifest root
  vanished); a specific ``delete`` requires the caller to name the prefix.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .storage_manifest import load_manifest, remove_prefix
from .storage_survey import NamespaceSurvey, classify_namespaces

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

# A canonical per-root namespace prefix is exactly ``r`` + 12 hex + ``_``
# (blake2b digest_size=6). Anchored at both ends so an empty or short prefix
# (e.g. ``""`` or ``"r"``) can never match every collection via startswith -
# the load-bearing guard against a total out-of-scope wipe, enforced even
# under ``allow_unknown``.
_CANONICAL_PREFIX_RE = re.compile(r"^r[0-9a-f]{12}_$")

__all__ = [
    "DeleteResult",
    "MigrateResult",
    "PruneResult",
    "collection_footprints",
    "delete_prefix",
    "gather_survey",
    "migrate_collections",
    "prune_orphaned",
    "server_storage_collections_dir",
]


@dataclass(frozen=True)
class DeleteResult:
    """Outcome of deleting one namespace.

    Attributes:
        prefix: The targeted collection prefix.
        status: ``removed`` / ``would_remove`` / ``skipped`` / ``failed``.
        collections: Collections affected (or that would be).
        reason: Why the op was skipped or failed, else ``None``.
    """

    prefix: str
    status: str
    collections: list[str] = field(default_factory=list)
    reason: str | None = None


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


@dataclass(frozen=True)
class PruneResult:
    """Outcome of a prune pass over all orphaned namespaces.

    Attributes:
        results: Per-namespace delete outcomes.
        skipped_unknown: Prefixes left untouched because unattributable.
        reclaimed_bytes: Footprint removed (or that would be, on dry-run).
        dry_run: Whether this was a preview.
    """

    results: list[DeleteResult]
    skipped_unknown: list[str]
    reclaimed_bytes: int
    dry_run: bool


def server_storage_collections_dir() -> Path | None:
    """Return the managed server's ``collections`` directory, if configured.

    Footprint is filesystem-derived (Qdrant exposes no size API), and only
    a process on the daemon host can read it. Returns ``None`` when the
    storage dir is not resolvable.
    """
    from .config import get_config

    cfg = get_config()
    raw = getattr(cfg, "qdrant_storage_dir", None)
    if not raw:
        return None
    base = Path(str(raw)).expanduser() / "collections"
    return base if base.exists() else None


def collection_footprints(
    collection_names: list[str],
    storage_dir: Path | None,
) -> dict[str, int]:
    """Compute per-collection on-disk byte footprints from the storage tree.

    Args:
        collection_names: Collection names to size.
        storage_dir: The ``collections`` directory; ``None`` yields an
            empty mapping (footprint simply unavailable).

    Returns:
        Mapping of collection name to total bytes (missing dirs are 0).
    """
    if storage_dir is None:
        return {}
    sizes: dict[str, int] = {}
    for name in collection_names:
        path = storage_dir / name
        total = 0
        if path.exists():
            for dirpath, _, filenames in os.walk(path):
                for filename in filenames:
                    try:
                        total += (Path(dirpath) / filename).stat().st_size
                    except OSError:
                        continue
        sizes[name] = total
    return sizes


def gather_survey(
    client: QdrantClient,
    storage_dir: Path | None = None,
) -> list[NamespaceSurvey]:
    """Survey every stored namespace: enumerate, count, size, classify.

    Args:
        client: Qdrant client for the managed server.
        storage_dir: The server ``collections`` directory for footprints;
            ``None`` (or unresolved) omits byte sizes.

    Returns:
        Classified namespace records, actionable states first.
    """
    names = [c.name for c in client.get_collections().collections]
    counts: dict[str, int] = {}
    for name in names:
        try:
            counts[name] = int(client.count(collection_name=name).count)
        except (OSError, RuntimeError):
            counts[name] = 0
    footprints = collection_footprints(names, storage_dir)
    return classify_namespaces(
        names, load_manifest(), point_counts=counts, footprints=footprints
    )


def delete_prefix(
    client: QdrantClient,
    prefix: str,
    *,
    dry_run: bool,
    allow_unknown: bool = False,
) -> DeleteResult:
    """Delete every collection sharing ``prefix`` and forget its manifest entry.

    Refuses an unattributable (``unknown``) prefix unless ``allow_unknown``
    is explicitly set, so a caller cannot accidentally remove a namespace
    the manifest cannot vouch for.

    Args:
        client: Qdrant client for the managed server.
        prefix: The collection prefix (``r{hash}_``) to remove.
        dry_run: When True, return the plan and mutate nothing.
        allow_unknown: Permit deleting a prefix absent from the manifest.

    Returns:
        A :class:`DeleteResult` describing the outcome.
    """
    # Hard gate: only a canonical r{12hex}_ prefix may ever be a delete target.
    # This is enforced before anything else and is NOT relaxed by allow_unknown,
    # so an empty/short/crafted prefix can never startswith-match foreign roots.
    if not _CANONICAL_PREFIX_RE.match(prefix):
        return DeleteResult(prefix, "skipped", reason="invalid_prefix")
    manifest = load_manifest()
    targets = [
        c.name
        for c in client.get_collections().collections
        if c.name.startswith(prefix)
    ]
    if not targets:
        return DeleteResult(prefix, "skipped", reason="no_such_namespace")
    if prefix not in manifest and not allow_unknown:
        return DeleteResult(prefix, "skipped", targets, reason="unknown_namespace")
    if dry_run:
        return DeleteResult(prefix, "would_remove", targets)
    removed: list[str] = []
    for name in targets:
        try:
            client.delete_collection(collection_name=name)
            removed.append(name)
        except (OSError, RuntimeError) as exc:
            return DeleteResult(prefix, "failed", removed, reason=str(exc))
    remove_prefix(prefix)
    return DeleteResult(prefix, "removed", removed)


def prune_orphaned(
    client: QdrantClient,
    *,
    dry_run: bool,
    storage_dir: Path | None = None,
) -> PruneResult:
    """Reclaim every orphaned namespace (manifest root vanished).

    Only ``orphaned`` namespaces are targeted; ``unknown`` namespaces are
    reported in ``skipped_unknown`` and never deleted, and ``live`` ones
    are left untouched.

    Args:
        client: Qdrant client for the managed server.
        dry_run: When True, return the plan and mutate nothing.
        storage_dir: The server ``collections`` directory for footprint
            reporting.

    Returns:
        A :class:`PruneResult` aggregating the per-namespace outcomes.
    """
    surveys = gather_survey(client, storage_dir)
    orphaned = [s for s in surveys if s.status == "orphaned"]
    unknown = [s.prefix for s in surveys if s.status == "unknown"]
    results: list[DeleteResult] = []
    reclaimed = 0
    for survey in orphaned:
        result = delete_prefix(client, survey.prefix, dry_run=dry_run)
        results.append(result)
        if result.status in ("removed", "would_remove"):
            reclaimed += survey.footprint_bytes
    return PruneResult(results, unknown, reclaimed, dry_run)


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
    *,
    dry_run: bool,
    batch_size: int = 256,
) -> list[MigrateResult]:
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

    Returns:
        One :class:`MigrateResult` per mapped collection.
    """
    results: list[MigrateResult] = []
    for source, target in name_map.items():
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
