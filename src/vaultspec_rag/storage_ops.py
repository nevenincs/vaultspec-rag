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
from datetime import UTC, datetime
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
    "MaintenanceResult",
    "MigrateResult",
    "PruneResult",
    "ReclaimDecision",
    "ReclaimPolicy",
    "archive_prefix",
    "backend_totals",
    "collection_footprints",
    "debris_surveys",
    "delete_prefix",
    "evaluate_reclaim",
    "gather_survey",
    "migrate_collections",
    "prune_debris",
    "prune_orphaned",
    "run_maintenance_cycle",
    "server_storage_collections_dir",
    "sweep_archive",
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


def _dir_bytes(path: Path) -> int:
    """Total file bytes under *path* (best-effort; unreadable files skip)."""
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for filename in filenames:
            try:
                total += (Path(dirpath) / filename).stat().st_size
            except OSError:
                continue
    return total


def debris_surveys(
    live_names: list[str],
    storage_dir: Path | None,
) -> list[NamespaceSurvey]:
    """Survey on-disk collection dirs the live server does not list.

    A Qdrant crash mid-create leaves a config-less collection dir that the
    server logs as "Collection config is not found ... skipping" at every
    startup and then ignores; because the survey historically enumerated
    only live collections, that debris was invisible to every operator
    view and unreclaimable forever. Each unmatched dir surfaces as
    a ``debris`` namespace entry (grouped by prefix, sized from disk).
    Report-only here: debris has no manifest attribution and Qdrant cannot
    snapshot a collection it never loaded, so removal stays an explicit
    operator action.
    """
    if storage_dir is None:
        return []
    from collections import defaultdict

    from .storage_survey import _prefix_of

    live = set(live_names)
    grouped: dict[str, list[Path]] = defaultdict(list)
    try:
        children = sorted(p for p in storage_dir.iterdir() if p.is_dir())
    except OSError:
        return []
    for child in children:
        if child.name in live:
            continue
        grouped[_prefix_of(child.name)].append(child)
    return [
        NamespaceSurvey(
            prefix=prefix,
            root=None,
            status="debris",
            collections=sorted(p.name for p in paths),
            points=0,
            footprint_bytes=sum(_dir_bytes(p) for p in paths),
        )
        for prefix, paths in grouped.items()
    ]


def backend_totals(surveys: list[NamespaceSurvey]) -> dict[str, object]:
    """Aggregate backend size over a classified survey.

    The incident's 117.9 GB pile was invisible to every metric because
    ``dangling_bytes`` counts only orphans and nothing summed the whole
    backend. This rollup makes total size and its per-status composition
    first-class.
    """
    total = 0
    by_status: dict[str, int] = {}
    for survey in surveys:
        total += survey.footprint_bytes
        by_status[survey.status] = (
            by_status.get(survey.status, 0) + survey.footprint_bytes
        )
    return {
        "total_bytes": total,
        "namespaces": len(surveys),
        "by_status_bytes": by_status,
    }


def prune_debris(
    client: QdrantClient,
    storage_dir: Path | None,
    *,
    dry_run: bool,
) -> PruneResult:
    """Remove config-less collection dirs the live server does not list.

    Debris is unloadable by Qdrant (no collection config), so it cannot be
    snapshotted or dropped through the client - removal is a filesystem
    delete of the leftover dir. It stays operator-gated (the explicit
    ``--debris`` flag plus the prune confirmation are the human in the
    loop): debris has no manifest attribution, so the automated
    time-confirmed-danglingness machinery must never touch it. Removing
    nothing is a success (idempotent teardown).
    """
    import shutil

    live_names = [c.name for c in client.get_collections().collections]
    results: list[DeleteResult] = []
    reclaimed = 0
    for survey in debris_surveys(live_names, storage_dir):
        for name in survey.collections:
            path = cast("Path", storage_dir) / name
            size = _dir_bytes(path)
            if dry_run:
                results.append(DeleteResult(name, "would_remove", collections=[name]))
                reclaimed += size
                continue
            try:
                shutil.rmtree(path)
            except OSError as exc:
                results.append(
                    DeleteResult(name, "failed", collections=[name], reason=str(exc))
                )
                continue
            results.append(DeleteResult(name, "removed", collections=[name]))
            reclaimed += size
    return PruneResult(
        results=results,
        skipped_unknown=[],
        reclaimed_bytes=reclaimed,
        dry_run=dry_run,
    )


# View ordering for survey consumers: actionable states first. ``debris``
# sits with the attention-needing states between unknown and unverifiable.
_SURVEY_STATUS_RANK = {
    "orphaned": 0,
    "unknown": 1,
    "debris": 2,
    "unverifiable": 3,
    "live": 4,
}


def gather_survey(
    client: QdrantClient,
    storage_dir: Path | None = None,
) -> list[NamespaceSurvey]:
    """Survey every stored namespace: enumerate, count, size, classify.

    Includes ``debris`` entries for on-disk collection dirs the live
    server does not list (crash leftovers), so the whole backend is
    visible from one call.

    Args:
        client: Qdrant client for the managed server.
        storage_dir: The server ``collections`` directory for footprints;
            ``None`` (or unresolved) omits byte sizes and debris.

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
    surveys = classify_namespaces(
        names, load_manifest(), point_counts=counts, footprints=footprints
    )
    surveys.extend(debris_surveys(names, storage_dir))
    surveys.sort(key=lambda s: (_SURVEY_STATUS_RANK.get(s.status, 5), s.prefix))
    return surveys


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


# -- scheduled reclamation ----------------------------------------------------


@dataclass(frozen=True)
class ReclaimPolicy:
    """Safety policy for time-confirmed automated reclamation.

    Attributes:
        grace_hours: Continuous-orphan hours before an EMPTY (zero-point)
            namespace may be reclaimed.
        grace_hours_data: Continuous-orphan hours before a POINT-BEARING
            namespace may be archived and reclaimed. Deliberately longer:
            a namespace with points is semantic data.
        max_per_cycle: Hard cap on reclaims per cycle; the remainder waits.
        archive_retention_days: Age past which archived snapshots are
            deleted by the retention sweep.
        archive_max_bytes: Total-byte cap for the archive dir; the sweep
            evicts oldest archives first until under it.
        ephemeral_idle_hours: Idle hours (since the persisted
            ``last_indexed`` stamp) after which a LIVE but temp-rooted
            namespace is treated as dangling - the leak signature
            is a harness temp dir that still exists but is never indexed
            again. ``0`` (or negative) disables the tier. Destruction
            still flows through the unchanged empty/data tiers: empty
            drops, point-bearing archives first.
    """

    grace_hours: float = 24.0
    grace_hours_data: float = 168.0
    max_per_cycle: int = 16
    archive_retention_days: float = 30.0
    archive_max_bytes: int = 20 * 1024**3
    ephemeral_idle_hours: float = 72.0


@dataclass(frozen=True)
class ReclaimDecision:
    """One namespace's outcome in a reclamation evaluation or cycle.

    Attributes:
        prefix: The namespace prefix.
        action: ``reclaim_empty`` / ``reclaim_data`` (eligible now),
            ``pending`` (grace window still running), ``deferred``
            (eligible but over the per-cycle cap), ``removed`` /
            ``archived_removed`` (cycle applied it), or ``failed``.
        tier: ``empty`` or ``data``.
        reason: Detail for pending/deferred/failed outcomes, else ``None``.
        points: Point count across the prefix's collections.
        footprint_bytes: On-disk footprint of the prefix.
    """

    prefix: str
    action: str
    tier: str
    reason: str | None = None
    points: int = 0
    footprint_bytes: int = 0


def _prefix_has_points(client: QdrantClient, prefix: str) -> bool:
    """Return True when any collection of *prefix* currently holds points."""
    for collection in client.get_collections().collections:
        if not collection.name.startswith(prefix):
            continue
        try:
            if int(client.count(collection_name=collection.name).count) > 0:
                return True
        except (OSError, RuntimeError):
            # An uncountable collection is treated as point-bearing: the
            # conservative answer defers the drop.
            return True
    return False


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp; naive values are assumed UTC."""
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _evaluate_ephemeral(
    surveys: list[NamespaceSurvey],
    last_indexed: dict[str, str],
    *,
    now: datetime,
    policy: ReclaimPolicy,
) -> list[ReclaimDecision]:
    """Decide, per LIVE temp-rooted namespace, whether the idle TTL expired.

    The shared-backend leak signature: a harness temp dir still exists, so its
    namespace classifies ``live`` and survives orphan pruning forever.
    Ephemerality is derived from the root path (``is_temp_rooted``) and
    danglingness from the persisted ``last_indexed`` activity clock -
    stamped by every successful index run, restart-safe, and only ever
    advanced by real activity, so protection can only extend. A missing
    or unparsable stamp is ``pending`` (never destroy on absent
    evidence). ``unknown``/``unverifiable`` namespaces never reach this
    function (they are not ``live``).
    """
    from .storage_survey import is_temp_rooted

    decisions: list[ReclaimDecision] = []
    if policy.ephemeral_idle_hours <= 0:
        return decisions
    candidates = sorted(
        (s for s in surveys if s.status == "live" and is_temp_rooted(s.root)),
        key=lambda s: (s.points > 0, s.prefix),
    )
    for survey in candidates:
        tier = "empty" if survey.points == 0 else "data"
        stamped = _parse_iso(last_indexed.get(survey.prefix, ""))
        if stamped is None:
            decisions.append(
                ReclaimDecision(
                    survey.prefix,
                    "pending",
                    tier,
                    reason="ephemeral_no_activity_stamp",
                    points=survey.points,
                    footprint_bytes=survey.footprint_bytes,
                )
            )
            continue
        idle_hours = (now - stamped).total_seconds() / 3600.0
        if idle_hours < policy.ephemeral_idle_hours:
            decisions.append(
                ReclaimDecision(
                    survey.prefix,
                    "pending",
                    tier,
                    reason=(
                        "ephemeral_idle_remaining_h="
                        f"{policy.ephemeral_idle_hours - idle_hours:.1f}"
                    ),
                    points=survey.points,
                    footprint_bytes=survey.footprint_bytes,
                )
            )
            continue
        decisions.append(
            ReclaimDecision(
                survey.prefix,
                "reclaim_empty" if tier == "empty" else "reclaim_data",
                tier,
                reason="ephemeral_idle",
                points=survey.points,
                footprint_bytes=survey.footprint_bytes,
            )
        )
    return decisions


def evaluate_reclaim(
    surveys: list[NamespaceSurvey],
    stamps: dict[str, str],
    *,
    now: datetime,
    policy: ReclaimPolicy,
    last_indexed: dict[str, str] | None = None,
) -> list[ReclaimDecision]:
    """Decide, per orphaned namespace, whether reclamation may act NOW.

    Safety gates stacked per prefix: only ``orphaned`` survey entries are
    considered (``unknown``/``unverifiable``/``live`` never appear in the
    output); a missing or unparsable grace stamp means the window has just
    started (``pending``); the window length is tiered by whether the
    namespace holds points; and eligible prefixes beyond
    ``policy.max_per_cycle`` are ``deferred`` to the next cycle. Empty
    namespaces are ordered before point-bearing ones so the riskless tier
    always reclaims first under a tight cap.

    Args:
        surveys: Classified namespaces from :func:`gather_survey`.
        stamps: Prefix to ``first_seen_orphaned`` mapping (from
            ``update_orphan_stamps``).
        now: The evaluation clock (timezone-aware).
        policy: The active :class:`ReclaimPolicy`.
        last_indexed: Prefix to persisted ``last_indexed`` stamp mapping
            (from the manifest); enables the ephemeral idle-TTL tier for
            live temp-rooted namespaces. ``None`` skips the tier.

    Returns:
        One :class:`ReclaimDecision` per orphaned namespace, plus one per
        live temp-rooted namespace when *last_indexed* is provided.
    """
    decisions: list[ReclaimDecision] = []
    eligible: list[ReclaimDecision] = []
    orphaned = sorted(
        (s for s in surveys if s.status == "orphaned"),
        key=lambda s: (s.points > 0, s.prefix),
    )
    for survey in orphaned:
        decision = _decide_orphan(survey, stamps, now=now, policy=policy)
        decisions.append(_apply_cycle_cap(decision, eligible, policy))
    if last_indexed is None:
        return decisions
    # Ephemeral idle-TTL tier: live temp-rooted namespaces whose
    # activity clock expired. Orphans keep priority under the shared
    # per-cycle cap; an over-cap ephemeral reclaim defers to next cycle.
    for decision in _evaluate_ephemeral(surveys, last_indexed, now=now, policy=policy):
        decisions.append(_apply_cycle_cap(decision, eligible, policy))
    return decisions


def _decide_orphan(
    survey: NamespaceSurvey,
    stamps: dict[str, str],
    *,
    now: datetime,
    policy: ReclaimPolicy,
) -> ReclaimDecision:
    """Decide one orphaned namespace against its tiered grace window."""
    tier = "empty" if survey.points == 0 else "data"
    window_hours = policy.grace_hours if tier == "empty" else policy.grace_hours_data
    first_seen = _parse_iso(stamps.get(survey.prefix, ""))
    if first_seen is None:
        return ReclaimDecision(
            survey.prefix,
            "pending",
            tier,
            reason="grace_started",
            points=survey.points,
            footprint_bytes=survey.footprint_bytes,
        )
    age_hours = (now - first_seen).total_seconds() / 3600.0
    if age_hours < window_hours:
        return ReclaimDecision(
            survey.prefix,
            "pending",
            tier,
            reason=f"grace_remaining_h={window_hours - age_hours:.1f}",
            points=survey.points,
            footprint_bytes=survey.footprint_bytes,
        )
    return ReclaimDecision(
        survey.prefix,
        "reclaim_empty" if tier == "empty" else "reclaim_data",
        tier,
        points=survey.points,
        footprint_bytes=survey.footprint_bytes,
    )


def _apply_cycle_cap(
    decision: ReclaimDecision,
    eligible: list[ReclaimDecision],
    policy: ReclaimPolicy,
) -> ReclaimDecision:
    """Track an eligible reclaim against the shared per-cycle cap.

    Pending and deferred decisions pass through; a reclaim decision either
    joins the *eligible* list (mutated in place) or converts to a
    ``deferred`` decision once the cap is reached.
    """
    if decision.action not in ("reclaim_empty", "reclaim_data"):
        return decision
    if len(eligible) < policy.max_per_cycle:
        eligible.append(decision)
        return decision
    return ReclaimDecision(
        decision.prefix,
        "deferred",
        decision.tier,
        reason="over_cycle_cap",
        points=decision.points,
        footprint_bytes=decision.footprint_bytes,
    )


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
    targets = [
        c.name
        for c in client.get_collections().collections
        if c.name.startswith(prefix)
    ]
    dest_dir = archive_dir / prefix.rstrip("_")
    dest_dir.mkdir(parents=True, exist_ok=True)
    archived: list[Path] = []
    for name in targets:
        description = client.create_snapshot(collection_name=name, wait=True)
        if description is None or not description.name:
            raise RuntimeError(f"snapshot creation returned no name for {name}")
        source = snapshots_dir / name / description.name
        if not source.is_file():
            raise RuntimeError(f"snapshot file not found: {source}")
        dest = dest_dir / description.name
        os.replace(source, dest)
        archived.append(dest)
    return archived


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
        retention_days: Age past which an archive file is deleted.
        max_total_bytes: Total-byte cap after age-based deletion.

    Returns:
        The deleted archive paths.
    """
    if not archive_dir.is_dir():
        return []
    files: list[tuple[float, int, Path]] = []
    for path in archive_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append((stat.st_mtime, stat.st_size, path))
    deleted: list[Path] = []
    cutoff = now.timestamp() - retention_days * 86400.0
    kept: list[tuple[float, int, Path]] = []
    for mtime, size, path in files:
        if mtime < cutoff:
            try:
                path.unlink()
                deleted.append(path)
            except OSError:
                kept.append((mtime, size, path))
        else:
            kept.append((mtime, size, path))
    total = sum(size for _, size, _ in kept)
    for _mtime, size, path in sorted(kept, key=lambda item: item[0]):
        if total <= max_total_bytes:
            break
        try:
            path.unlink()
            deleted.append(path)
            total -= size
        except OSError:
            continue
    return deleted


@dataclass(frozen=True)
class MaintenanceResult:
    """Outcome of one scheduled maintenance cycle.

    Attributes:
        decisions: Every orphaned namespace's decision this cycle.
        reclaimed_bytes: Footprint of the namespaces actually removed.
        archived: Snapshot files written for point-bearing reclaims.
        swept: Archive files removed by the retention sweep.
        namespace_counts: Survey status to count, for the health rollup.
        pending_grace: Orphans still inside their grace window.
        dangling_bytes: Total footprint of all currently orphaned
            namespaces (reclaimed or not), for the health rollup.
        surveys: The full classified survey the cycle ran on, handed back
            so the daemon can publish it as the survey snapshot instead of
            paying the footprint walk twice.
    """

    decisions: list[ReclaimDecision]
    reclaimed_bytes: int
    archived: list[Path]
    swept: list[Path]
    namespace_counts: dict[str, int]
    pending_grace: int
    dangling_bytes: int
    surveys: list[NamespaceSurvey] = field(default_factory=list)


def run_maintenance_cycle(
    client: QdrantClient,
    *,
    now: datetime,
    policy: ReclaimPolicy,
    storage_dir: Path | None,
    snapshots_dir: Path,
    archive_dir: Path,
    dry_run: bool = False,
) -> MaintenanceResult:
    """Run one scheduled reclamation cycle end to end.

    Survey, advance the persisted grace clocks, evaluate the stacked
    safety gates, then apply: empty orphans past grace are dropped;
    point-bearing orphans past their longer grace are archived first and
    dropped only when every snapshot succeeded; the archive retention
    sweep bounds the archive tree. All destruction reuses
    :func:`delete_prefix` - one implementation shared with the operator
    CLI. Never touches ``unknown``, ``unverifiable``, or ``live``
    namespaces, and never touches the GPU.

    Args:
        client: Qdrant client for the managed server.
        now: The cycle clock (timezone-aware).
        policy: The active :class:`ReclaimPolicy`.
        storage_dir: The server ``collections`` dir for footprints.
        snapshots_dir: The server's snapshots tree.
        archive_dir: The bounded archive destination.
        dry_run: When True, evaluate and report but mutate nothing
            (grace stamps are still advanced - observation is not
            destruction).

    Returns:
        A :class:`MaintenanceResult` for the jobs registry and rollup.
    """
    from .storage_manifest import load_manifest, update_orphan_stamps

    surveys = gather_survey(client, storage_dir)
    stamps = update_orphan_stamps(
        {s.prefix: s.status for s in surveys},
        now_iso=now.isoformat(),
    )
    last_indexed = {
        prefix: entry.last_indexed for prefix, entry in load_manifest().items()
    }
    decisions = evaluate_reclaim(
        surveys,
        stamps,
        now=now,
        policy=policy,
        last_indexed=last_indexed,
    )
    applied: list[ReclaimDecision] = []
    archived: list[Path] = []
    reclaimed = 0
    for decision in decisions:
        if decision.action not in ("reclaim_empty", "reclaim_data") or dry_run:
            applied.append(decision)
            continue
        if decision.action == "reclaim_data":
            try:
                archived.extend(
                    archive_prefix(
                        client,
                        decision.prefix,
                        snapshots_dir=snapshots_dir,
                        archive_dir=archive_dir,
                    )
                )
            except (OSError, RuntimeError) as exc:
                applied.append(
                    ReclaimDecision(
                        decision.prefix,
                        "failed",
                        decision.tier,
                        reason=f"archive_failed: {exc}",
                        points=decision.points,
                        footprint_bytes=decision.footprint_bytes,
                    )
                )
                continue
        else:
            # The empty tier has no archive, so re-count immediately before
            # the drop: a reindex of a just-restored root racing this cycle
            # (survey-to-drop TOCTOU) defers the prefix to the next cycle
            # instead of destroying fresh points.
            if _prefix_has_points(client, decision.prefix):
                applied.append(
                    ReclaimDecision(
                        decision.prefix,
                        "deferred",
                        decision.tier,
                        reason="points_appeared_since_survey",
                        points=decision.points,
                        footprint_bytes=decision.footprint_bytes,
                    )
                )
                continue
        result = delete_prefix(client, decision.prefix, dry_run=False)
        if result.status == "removed":
            reclaimed += decision.footprint_bytes
            applied.append(
                ReclaimDecision(
                    decision.prefix,
                    "removed" if decision.tier == "empty" else "archived_removed",
                    decision.tier,
                    points=decision.points,
                    footprint_bytes=decision.footprint_bytes,
                )
            )
        else:
            applied.append(
                ReclaimDecision(
                    decision.prefix,
                    "failed",
                    decision.tier,
                    reason=result.reason or result.status,
                    points=decision.points,
                    footprint_bytes=decision.footprint_bytes,
                )
            )
    swept = (
        []
        if dry_run
        else sweep_archive(
            archive_dir,
            now=now,
            retention_days=policy.archive_retention_days,
            max_total_bytes=policy.archive_max_bytes,
        )
    )
    counts: dict[str, int] = {}
    for survey in surveys:
        counts[survey.status] = counts.get(survey.status, 0) + 1
    return MaintenanceResult(
        decisions=applied,
        reclaimed_bytes=reclaimed,
        archived=archived,
        swept=swept,
        namespace_counts=counts,
        pending_grace=sum(1 for d in applied if d.action == "pending"),
        dangling_bytes=sum(
            s.footprint_bytes for s in surveys if s.status == "orphaned"
        ),
        surveys=surveys,
    )
