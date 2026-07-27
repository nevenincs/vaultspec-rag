"""Service-domain storage reclamation and scheduled maintenance."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from . import store_schema
from ._atomic_write import replace_atomically
from ._timestamps import parse_iso_timestamp
from .storage_manifest import (
    SnapshotCollection,
    StorageSnapshotManifest,
    load_manifest,
    write_snapshot_manifest,
)
from .storage_reconciliation import ReconcileBatch, reconcile_collections
from .storage_survey_ops import DeleteResult, delete_prefix, gather_survey

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import datetime

    from qdrant_client import QdrantClient

    from .generation_survey import RootGenerations
    from .storage_survey import NamespaceSurvey

logger = logging.getLogger(__name__)


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
        reconcile: Whether the non-destructive geometry-reconcile stage
            runs in the cycle.
        reconcile_max_per_cycle: Hard cap on collections reconciled per
            cycle; the remainder converges on later cycles.
        reconcile_budget_seconds: Per-collection convergence budget.
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
    reconcile: bool = True
    reconcile_max_per_cycle: int = 4
    reconcile_budget_seconds: float = 300.0


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


def _prefix_points(client: QdrantClient, prefix: str) -> int | None:
    """Return *prefix*'s total live point count, or ``None`` if unverifiable.

    The pre-drop re-count, shared by both destruction tiers. ``None`` means at
    least one collection could not be counted, and is never treated as a
    number: comparing a total that silently omits a collection would read a
    partial sum as agreement with the survey.
    """
    total = 0
    for collection in client.get_collections().collections:
        if not collection.name.startswith(prefix):
            continue
        try:
            total += int(client.count(collection_name=collection.name).count)
        except (OSError, RuntimeError):
            return None
    return total


def _active_index_prefixes() -> frozenset[str]:
    """Return the collection prefixes an active index job is writing to.

    The liveness signal automated destruction consults. Read-only: it reads
    the job registry's nonterminal set and maps each job's project root
    through the same ``root_collection_prefix`` the store namespaces
    collections with, so the answer arrives in the reclaim path's own
    vocabulary. It touches no lifecycle verb, no GPU, and no search path.

    Every active index job counts, not only one mid-upsert: a queued or paused
    run for that root will write to those collections, so destroying its
    namespace first is the same data loss slightly deferred. A job that cannot
    be attributed to a root is skipped - it cannot be matched to a prefix, and
    an unattributable job is not evidence about any particular namespace.

    A registry that cannot be read yields the empty set rather than raising:
    this runs inside a background cycle, and the pre-drop re-count and the
    persisted grace windows both remain in force behind it.
    """
    from . import jobs
    from ._store_models import root_collection_prefix
    from .job_models import JobOperation

    try:
        active = jobs.get_job_manager().active()
    except (OSError, RuntimeError):
        logger.exception("active-job probe failed; treating no namespace as busy")
        return frozenset()
    prefixes: set[str] = set()
    for snapshot in active:
        if snapshot.spec.operation is not JobOperation.INDEX:
            continue
        root = snapshot.spec.project_root
        if root is None:
            continue
        try:
            prefixes.add(root_collection_prefix(root))
        except (OSError, ValueError):
            logger.debug("unattributable active job root %s", root, exc_info=True)
    return frozenset(prefixes)


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
    restart-safe, and only ever advanced by real activity, so protection can
    only extend. That clock is advanced both by a completed index run and by
    a survey observing this namespace's stored points move
    (``update_activity_stamps``), because an indexer that writes without
    stamping is exactly the writer whose data this tier would destroy. A
    missing or unparsable stamp is ``pending`` (never destroy on absent
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
        stamped = parse_iso_timestamp(
            last_indexed.get(survey.prefix, ""), field="last_indexed"
        )
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

    Reachability is the only classification this function reads, and a
    collection's conformance verdict is deliberately not an input to it. The
    two say different things and share a word: a namespace is ``unverifiable``
    here when its root could not be confirmed to be gone, and separately
    ``unverifiable`` as a collection when nothing records what produced its
    vectors. Absent provenance neither authorises a reclaim nor blocks one.
    Letting it authorise would destroy data on missing evidence. Letting it
    block would exempt every namespace written before stamping existed - which
    is every orphan whose root is already gone, so it can never be rebuilt into
    a stamp - and turn a safety rule into an unbounded leak. Provenance is
    carried into the archive that precedes a data-tier drop instead, so what is
    reclaimed stays judgeable after the fact.

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
    first_seen = parse_iso_timestamp(stamps.get(survey.prefix, ""), field="first_seen")
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


def _redecide(decision: ReclaimDecision, action: str, reason: str) -> ReclaimDecision:
    """Restate one namespace's decision, preserving its measured facts.

    Every gate that turns a reclaim into a ``deferred`` or ``failed`` outcome
    reports the same prefix, tier, point count and footprint it was handed;
    only the verdict and its reason change.
    """
    return ReclaimDecision(
        decision.prefix,
        action,
        decision.tier,
        reason=reason,
        points=decision.points,
        footprint_bytes=decision.footprint_bytes,
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
    return _redecide(decision, "deferred", "over_cycle_cap")


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
    identities = {} if entry is None else entry.collection_identity
    for name in targets:
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
                points=int(client.count(collection_name=name).count),
                identity=identities.get(name),
            )
        )
    metadata_files: list[str] = []
    if entry is not None:
        from shutil import copy2

        from .indexer._document_meta import document_metadata_path

        document_meta = document_metadata_path(Path(entry.root))
        if document_meta.is_file():
            metadata_dest = dest_dir / document_meta.name
            copy2(document_meta, metadata_dest)
            metadata_files.append(metadata_dest.name)
    manifest_path = write_snapshot_manifest(
        dest_dir,
        StorageSnapshotManifest(
            prefix=prefix,
            root=entry.root if entry is not None else None,
            storage_schema_version=(
                entry.storage_schema_version
                if entry is not None
                else store_schema.STORAGE_SCHEMA_VERSION
            ),
            collections=tuple(sorted(collection_artifacts, key=lambda item: item.name)),
            metadata_files=tuple(sorted(metadata_files)),
        ),
    )
    archived.append(manifest_path)
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
        generations: Per-collection outcomes from the superseded-generation
            pass. Empty when no root is carrying any, which is the normal
            state for a tree nobody has rebuilt since publication changed.
        reconcile: The geometry-reconcile pass, or ``None`` when the stage
            is disabled. Its reclaimed bytes are tracked separately from
            ``reclaimed_bytes`` because reconcile releases preallocation
            from collections that are kept, while reclamation releases the
            footprint of namespaces that are destroyed.
    """

    decisions: list[ReclaimDecision]
    reclaimed_bytes: int
    archived: list[Path]
    swept: list[Path]
    namespace_counts: dict[str, int]
    pending_grace: int
    dangling_bytes: int
    surveys: list[NamespaceSurvey] = field(default_factory=list)
    reconcile: ReconcileBatch | None = None
    generations: list[DeleteResult] = field(default_factory=list)


def _apply_reclaim(
    client: QdrantClient,
    decision: ReclaimDecision,
    *,
    snapshots_dir: Path,
    archive_dir: Path,
    active_prefixes: Callable[[], frozenset[str]],
) -> tuple[ReclaimDecision, list[Path]]:
    """Destroy one eligible namespace, or defer it, under the pre-drop gates.

    Separated from the cycle so the gates read as one ordered sequence rather
    than as branches interleaved with the cycle's bookkeeping. Every exit is a
    decision plus whatever archive artifacts were written, including on a
    deferral after a torn snapshot: those files exist, the retention sweep
    bounds them, and reporting them is how an operator learns the archive
    happened.

    Args:
        client: Qdrant client for the managed server.
        decision: An eligible ``reclaim_empty`` / ``reclaim_data`` decision.
        snapshots_dir: The server's snapshots tree.
        archive_dir: The bounded archive destination.
        active_prefixes: Liveness probe, called here rather than once per
            cycle so a run that started during an earlier namespace's archive
            is still seen.

    Returns:
        The outcome decision and the archive paths written.
    """
    gate = _pre_drop_reclaim_gate(client, decision, active_prefixes=active_prefixes)
    if isinstance(gate, ReclaimDecision):
        return gate, []
    observed = gate
    archived: list[Path] = []
    if decision.action == "reclaim_data":
        try:
            archived = archive_prefix(
                client,
                decision.prefix,
                snapshots_dir=snapshots_dir,
                archive_dir=archive_dir,
            )
        except (OSError, RuntimeError) as exc:
            return _redecide(decision, "failed", f"archive_failed: {exc}"), []
        # The snapshot is a point-in-time copy. A write landing during it
        # tears the copy, and the delete below would then destroy the delta
        # the copy missed - the one loss an archive cannot undo.
        settled = _prefix_points(client, decision.prefix)
        if settled != observed:
            return (
                _redecide(decision, "deferred", "points_changed_during_archive"),
                archived,
            )
    result = delete_prefix(client, decision.prefix, dry_run=False)
    if result.status != "removed":
        return _redecide(decision, "failed", result.reason or result.status), archived
    return (
        ReclaimDecision(
            decision.prefix,
            "removed" if decision.tier == "empty" else "archived_removed",
            decision.tier,
            points=decision.points,
            footprint_bytes=decision.footprint_bytes,
        ),
        archived,
    )


def _pre_drop_reclaim_gate(
    client: QdrantClient,
    decision: ReclaimDecision,
    *,
    active_prefixes: Callable[[], frozenset[str]],
) -> int | ReclaimDecision:
    """Return the stable point count, or one precise pre-drop deferral."""
    # Liveness first. An archive taken across a live writer is torn, so this
    # gate has to precede the archive, not just the drop.
    if decision.prefix in active_prefixes():
        return _redecide(decision, "deferred", "active_index_job")
    # Re-count immediately before acting, in BOTH tiers. The survey reading
    # can be many minutes stale by the time this prefix's turn arrives, and
    # any movement since means a writer this cycle cannot see.
    observed = _prefix_points(client, decision.prefix)
    if observed is None:
        return _redecide(decision, "deferred", "points_unverifiable")
    if observed != decision.points:
        moved = (
            "points_appeared_since_survey"
            if decision.tier == "empty"
            else "points_changed_since_survey"
        )
        return _redecide(decision, "deferred", moved)
    return observed


def _reclaim_generations_for_cycle(
    client: QdrantClient,
    *,
    surveys: list[NamespaceSurvey],
    now: datetime,
    policy: ReclaimPolicy,
    dry_run: bool,
) -> list[DeleteResult]:
    """Run the superseded-generation pass for one maintenance cycle.

    Separated from the orphan pass because the two answer different
    questions. An orphan is a namespace whose root vanished; a superseded
    generation belongs to a root that is alive and well and simply publishes
    somewhere else now. They share a cycle, not a rule.

    Reader liveness comes from the project registry when one exists in this
    process. Where it does not - an operator running maintenance out of band -
    every root reports a reader, so the pass defers rather than acting on an
    absence of evidence it has no way to gather.
    """
    from . import store_schema
    from .generation_stamps import load_generation_stamps, record_generation_stamps

    roots = {
        survey.root: f"{survey.prefix}{store_schema.CODE_COLLECTION}"
        for survey in surveys
        if survey.root
    }
    if not roots:
        return []

    def _reader_present(root: str) -> bool:
        try:
            from .registry import get_registry
        except ImportError:  # pragma: no cover - registry always importable
            return True
        try:
            return get_registry().has_live_lease(Path(root))
        except (OSError, RuntimeError):
            # Cannot establish that nothing holds it, so treat it as held.
            return True

    results, advanced = reclaim_superseded_generations(
        GenerationReclaimRequest(
            client=client,
            roots=roots,
            stamps=load_generation_stamps(),
            now=now,
            grace_hours=policy.grace_hours_data,
            reader_present=_reader_present,
            dry_run=dry_run,
        )
    )
    if not dry_run:
        record_generation_stamps(advanced)
    return results


@dataclass(frozen=True)
class MaintenanceCycleRequest:
    """All dependencies and controls for one scheduled maintenance cycle."""

    client: QdrantClient
    now: datetime
    policy: ReclaimPolicy
    storage_dir: Path | None
    snapshots_dir: Path
    archive_dir: Path
    dry_run: bool = False
    active_prefixes: Callable[[], frozenset[str]] = _active_index_prefixes


def run_maintenance_cycle(
    request: MaintenanceCycleRequest,
) -> MaintenanceResult:
    """Run one scheduled reclamation cycle end to end.

    Survey, advance the persisted grace clocks, evaluate the stacked
    safety gates, then apply: empty orphans past grace are dropped;
    point-bearing orphans past their longer grace are archived first and
    dropped only when every snapshot succeeded; the archive retention
    sweep bounds the archive tree. All destruction reuses
    :func:`delete_prefix` - one implementation shared with the operator
    CLI. Never touches ``unknown`` or ``unverifiable`` namespaces, never
    touches a ``live`` one except through the ephemeral idle tier, and never
    touches the GPU.

    Two gates stand between a decision and the drop, both re-evaluated per
    namespace immediately before acting on it rather than once per cycle:
    a liveness check (no active index job may own the prefix) and a re-count
    against the surveyed point total (any movement defers). The data tier
    re-counts a second time across its archive, because a write landing
    during the snapshot tears it and the delete would then destroy the delta
    the copy missed. Deferral is always the safe answer: the namespace is
    re-evaluated next cycle, having lost nothing but time.

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
        active_prefixes: Liveness probe returning the collection prefixes an
            active index job is writing to. Defaults to the job registry;
            injectable so the gate is testable without a live daemon.

    Returns:
        A :class:`MaintenanceResult` for the jobs registry and rollup.
    """
    from .storage_manifest import update_activity_stamps, update_orphan_stamps

    surveys = gather_survey(request.client, request.storage_dir)
    stamps = update_orphan_stamps(
        {s.prefix: s.status for s in surveys},
        now_iso=request.now.isoformat(),
    )
    # The ephemeral tier's idle clock, advanced from what the stored data is
    # doing rather than from index-run stamps alone. Reading the manifest
    # directly here would see only what an indexer chose to stamp, which is
    # the blind spot this tier cannot afford.
    last_indexed = update_activity_stamps(
        {s.prefix: (s.status, s.points) for s in surveys},
        now_iso=request.now.isoformat(),
    )
    decisions = evaluate_reclaim(
        surveys,
        stamps,
        now=request.now,
        policy=request.policy,
        last_indexed=last_indexed,
    )
    generations = _reclaim_generations_for_cycle(
        request.client,
        surveys=surveys,
        now=request.now,
        policy=request.policy,
        dry_run=request.dry_run,
    )
    applied: list[ReclaimDecision] = []
    archived: list[Path] = []
    reclaimed = 0
    for decision in decisions:
        if decision.action not in ("reclaim_empty", "reclaim_data") or request.dry_run:
            applied.append(decision)
            continue
        outcome, artifacts = _apply_reclaim(
            request.client,
            decision,
            snapshots_dir=request.snapshots_dir,
            archive_dir=request.archive_dir,
            active_prefixes=request.active_prefixes,
        )
        archived.extend(artifacts)
        applied.append(outcome)
        if outcome.action in ("removed", "archived_removed"):
            reclaimed += outcome.footprint_bytes
    swept = (
        []
        if request.dry_run
        else sweep_archive(
            request.archive_dir,
            now=request.now,
            retention_days=request.policy.archive_retention_days,
            max_total_bytes=request.policy.archive_max_bytes,
        )
    )
    # Reconcile runs last so a convergence budget is never spent on a
    # namespace this same cycle just destroyed. It is non-destructive and
    # independent of the grace machinery above.
    reconcile: ReconcileBatch | None = None
    if request.policy.reconcile:
        reconcile = reconcile_collections(
            request.client,
            storage_dir=request.storage_dir,
            cap=request.policy.reconcile_max_per_cycle,
            budget_s=request.policy.reconcile_budget_seconds,
            dry_run=request.dry_run,
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
        reconcile=reconcile,
        generations=generations,
    )


def _evaluate_generation_reports(
    reports: tuple[RootGenerations, ...],
    *,
    stamps: Mapping[str, str],
    now: datetime,
    grace_hours: float,
    reader_present: Callable[[str], bool],
) -> tuple[list[DeleteResult], list[str], list[str], list[str]]:
    """Decide reclaim/hold/skip for every unreferenced generation, per root.

    Returns ``(results, droppable, held, unreferenced)``.
    """
    from .generation_survey import GenerationReclaimContext, decide_generation_reclaim

    results: list[DeleteResult] = []
    droppable: list[str] = []
    held: list[str] = []
    unreferenced: list[str] = []
    for report in reports:
        has_reader = reader_present(report.root)
        for collection in report.unreferenced:
            unreferenced.append(collection)
            decision = decide_generation_reclaim(
                collection,
                GenerationReclaimContext(
                    stamps=stamps,
                    now=now,
                    grace_hours=grace_hours,
                    reader_present=has_reader,
                    # survey_generations already omitted any root whose pointer it
                    # could not read, so every collection reaching here came from a
                    # root whose served name was legible at decision time.
                    pointer_verifiable=True,
                ),
            )
            if decision.action == "held":
                held.append(collection)
            if decision.droppable:
                droppable.append(collection)
            else:
                results.append(
                    DeleteResult(collection, "skipped", reason=decision.reason)
                )
    return results, droppable, held, unreferenced


def _hold_unreported_root_generations(
    roots: Mapping[str, str],
    live: list[str],
    reported: set[str],
    held: list[str],
) -> None:
    """Reset the clock for generations whose root pointer was unreadable."""
    for root, derived in roots.items():
        if root in reported:
            continue
        held.extend(name for name in live if name.startswith(derived))


def _drop_generation_collections(
    client: QdrantClient,
    droppable: list[str],
    held: list[str],
    *,
    dry_run: bool,
) -> tuple[list[DeleteResult], set[str]]:
    """Drop each droppable generation; a failed drop rejoins the held set."""
    results: list[DeleteResult] = []
    dropped: set[str] = set()
    for collection in droppable:
        if dry_run:
            results.append(DeleteResult(collection, "would_remove", [collection]))
            continue
        try:
            client.delete_collection(collection_name=collection)
        except (OSError, RuntimeError) as exc:
            results.append(DeleteResult(collection, "failed", reason=str(exc)))
            held.append(collection)
            continue
        results.append(DeleteResult(collection, "removed", [collection]))
        dropped.add(collection)
    return results, dropped


@dataclass(frozen=True)
class GenerationReclaimRequest:
    """All evidence and controls for one superseded-generation pass."""

    client: QdrantClient
    roots: Mapping[str, str]
    stamps: Mapping[str, str]
    now: datetime
    grace_hours: float
    reader_present: Callable[[str], bool]
    dry_run: bool


def reclaim_superseded_generations(
    request: GenerationReclaimRequest,
) -> tuple[list[DeleteResult], dict[str, str]]:
    """Drop code generations no root serves any more, and advance their clocks.

    Read-and-drop only. Every gate lives in ``decide_generation_reclaim``; this
    gathers the evidence that gate needs and acts on nothing it did not
    approve.

    The served pointer is resolved HERE, per root, at the moment of the
    decision - never carried in from a survey gathered earlier in the cycle. A
    collection can become the served one between a gather and a drop, and a
    stale name would walk past every gate while pointing at a live index.

    Returns the per-collection outcomes and the advanced stamp map. The caller
    persists the stamps; nothing is written here beyond the drops themselves,
    so a failure part-way leaves the clocks untouched rather than crediting a
    window that did not run.

    Args:
        client: Qdrant client for the managed server.
        roots: Root path to that root's derived code collection name.
        stamps: Collection to ``first_seen_unreferenced`` ISO timestamp.
        now: The evaluation clock (timezone-aware).
        grace_hours: Continuous unreferenced hours before a drop is allowed.
        reader_present: Predicate answering whether a root has a live lease.
        dry_run: When True, plan and mutate nothing.
    """
    from .generation_survey import advance_generation_stamps, survey_generations

    live = [c.name for c in request.client.get_collections().collections]
    reports = survey_generations(request.roots, live)
    results, droppable, held, unreferenced = _evaluate_generation_reports(
        reports,
        stamps=request.stamps,
        now=request.now,
        grace_hours=request.grace_hours,
        reader_present=request.reader_present,
    )

    # A root omitted from the report had an unreadable pointer, so any
    # generation of it that exists must have its clock reset rather than keep
    # accumulating a window it did not continuously earn.
    reported = {report.root for report in reports}
    _hold_unreported_root_generations(request.roots, live, reported, held)

    drop_results, dropped = _drop_generation_collections(
        request.client, droppable, held, dry_run=request.dry_run
    )
    results.extend(drop_results)

    # A dropped collection keeps no clock: it no longer exists, and a stamp for
    # it would outlive it as debris that never expires. A failed drop is not
    # dropped, so it stays in the held set and its window restarts.
    advanced = advance_generation_stamps(
        request.stamps,
        unreferenced=(name for name in unreferenced if name not in dropped),
        held=[*held, *dropped],
        now_iso=request.now.isoformat(),
    )
    return results, advanced
