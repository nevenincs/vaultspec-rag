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

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from . import store_schema
from ._atomic_write import replace_atomically
from ._store_models import ROOT_COLLECTION_PREFIX_RE
from ._store_writes import DISK_FLOOR_BYTES as _DISK_FLOOR_BYTES
from ._timestamps import parse_iso_timestamp
from .storage_manifest import (
    SnapshotCollection,
    StorageSnapshotManifest,
    load_manifest,
    remove_prefix,
    write_snapshot_manifest,
)
from .storage_survey import NamespaceSurvey, classify_namespaces

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Mapping
    from datetime import datetime

    from qdrant_client import QdrantClient

    from .generation_survey import RootGenerations

logger = logging.getLogger(__name__)

# Convergence sampling. The optimizer transiently inflates size and segment
# count while restructuring, so stability across consecutive settled samples -
# not a single reading - is what proves it finished. The byte tolerance absorbs
# incidental WAL churn without masking a real merge, which moves hundreds of MiB.
# The poll interval is deliberately unhurried: each sample walks the collection
# directory the optimizer is actively rewriting, so sampling hard would compete
# with the very merge being measured.
_CONVERGENCE_STABLE_SAMPLES = 4
_CONVERGENCE_POLL_SECONDS = 3.0
_CONVERGENCE_BYTE_TOLERANCE = 1024 * 1024
# How long to wait for the optimizer to pick the work up before concluding
# there was none. A merge queued behind saturated optimizer threads looks
# exactly like a converged one if only stability is checked.
_OPTIMIZER_START_BUDGET_SECONDS = 30.0
# Transient headroom a merge needs: it inflates before it shrinks (~30%
# measured), and these backends are reconciled precisely because they are full.
# The floor is the store's existing write floor - one shared definition of
# "too little space to let Qdrant near an optimizer pass".
_RECONCILE_HEADROOM_FACTOR = 0.5


def _no_progress(_line: str) -> None:
    """Drop a progress line, for callers that want no reporting.

    A no-op sink rather than a ``None`` check at each call site. These
    functions run under the in-daemon maintenance schedule as well as under an
    operator command, and only the latter has anywhere to report to.
    """


def _free_bytes(path: Path) -> int | None:
    """Free bytes on *path*'s volume, or ``None`` if it cannot be read."""
    import shutil

    try:
        return shutil.disk_usage(path).free
    except OSError:
        logger.debug("free-space probe failed for %s", path, exc_info=True)
        return None


# A canonical per-root namespace prefix is exactly ``r`` + 12 hex + ``_``
# (blake2b digest_size=6). Anchored at both ends so an empty or short prefix
# (e.g. ``""`` or ``"r"``) can never match every collection via startswith -
# the load-bearing guard against a total out-of-scope wipe, enforced even
# under ``allow_unknown``.
#
# Matched with ``fullmatch`` against the one pattern the prefix builder's own
# digest size produces. The local copy this replaced was ``$``-anchored, and
# ``$`` also matches immediately before a trailing newline - so
# ``"r0123456789ab_\n"`` passed this gate. ``fullmatch`` does not accept it.
# Strictly narrower, which is the only direction a delete gate should move.
def _is_canonical_prefix(value: str) -> bool:
    """Return whether *value* is exactly one canonical root prefix."""
    return ROOT_COLLECTION_PREFIX_RE.fullmatch(value) is not None


__all__ = [
    "DeleteResult",
    "GeometryEntry",
    "MaintenanceResult",
    "MigrateResult",
    "PruneResult",
    "ReclaimDecision",
    "ReclaimPolicy",
    "ReconcileBatch",
    "ReconcileResult",
    "archive_prefix",
    "backend_totals",
    "carry_migrated_identity",
    "collection_footprints",
    "debris_surveys",
    "delete_prefix",
    "evaluate_reclaim",
    "gather_survey",
    "migrate_collections",
    "plan_reconcile",
    "prune_debris",
    "prune_orphaned",
    "read_geometry",
    "reclaim_superseded_generations",
    "reconcile_collection",
    "reconcile_collections",
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
        "points": sum(survey.points for survey in surveys),
        "vault_points": sum(survey.vault_points for survey in surveys),
        "code_points": sum(survey.code_points for survey in surveys),
        "document_points": sum(survey.document_points for survey in surveys),
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
            # Re-confirm right before the delete: a collection created
            # between the survey snapshot and this point has a dir on
            # disk before the server lists it, and must never be
            # removed as debris.
            live_now = {c.name for c in client.get_collections().collections}
            if name in live_now:
                results.append(
                    DeleteResult(
                        name,
                        "skipped",
                        collections=[name],
                        reason="appeared_live",
                    )
                )
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


@dataclass(frozen=True)
class GeometryEntry:
    """One live collection's segment geometry and footprint.

    Attributes:
        collection: The collection name.
        segment_target: Its configured ``default_segment_number``. ``0``
            means "derive from host CPU count" - the server default, and
            the value every collection created before the bounded-geometry
            change carries.
        segments: Its current actual segment count.
        footprint_bytes: On-disk size, or ``None`` when the storage dir is
            not resolvable and size cannot be measured.
        settled: Whether the collection reports ``green`` - no optimization
            running or pending. A collection at target but not settled is
            still merging and has not converged.
    """

    collection: str
    segment_target: int
    segments: int
    footprint_bytes: int | None
    settled: bool = True


@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of reconciling one collection's geometry.

    ``status`` is one of ``reconciled`` (converged inside the budget),
    ``converging`` (update accepted, still restructuring when the budget
    expired), ``would_reconcile`` (dry-run preview), ``skipped`` (already
    at target), or ``failed`` (the update call itself errored).

    ``bytes_after`` and therefore :attr:`reclaimed_bytes` are populated
    only for ``reconciled``. A converging collection is deliberately
    reported without a reclaim figure: the optimizer transiently inflates
    both size and segment count while restructuring, so any mid-flight
    number would misreport a reclamation in progress as growth.
    """

    collection: str
    status: str
    segments_before: int
    segments_after: int | None = None
    bytes_before: int | None = None
    bytes_after: int | None = None
    reason: str | None = None

    @property
    def reclaimed_bytes(self) -> int:
        """Bytes released, or ``0`` when no converged measurement exists."""
        if self.bytes_before is None or self.bytes_after is None:
            return 0
        return max(self.bytes_before - self.bytes_after, 0)


@dataclass(frozen=True)
class ReconcileBatch:
    """Outcome of one reconcile pass over the drifted collections.

    Attributes:
        results: Per-collection outcomes.
        drifted_remaining: Collections still off-target after this pass -
            those deferred by the cap plus those still converging. The
            operator-visible signal that the backend has not converged.
        reclaimed_bytes: Total released across converged collections.
        dry_run: Whether this was a preview.
    """

    results: list[ReconcileResult]
    drifted_remaining: int
    reclaimed_bytes: int
    dry_run: bool


def _is_settled(info: object) -> bool:
    """Whether a collection has finished optimizing.

    The busy signal is ``CollectionInfo.status`` (green / yellow / grey /
    red), NOT ``optimizer_status``: the latter is an ok-or-error field with
    no busy state at all, so gating on it would call every healthy sample
    settled and let a queued, not-yet-started merge be measured as a
    finished one. Only ``green`` is settled - ``yellow`` is optimizing,
    ``grey`` is "possible but not triggered" (a merge still pending), and
    ``red`` means an operation failed.
    """
    return str(getattr(info, "status", "")).lower().endswith("green")


def read_geometry(
    client: QdrantClient,
    storage_dir: Path | None,
) -> list[GeometryEntry]:
    """Read this project's collections' segment geometry and footprint.

    Scoped to canonically-prefixed namespaces (``r`` + 12 hex + ``_``), the
    same guard every mutating path in this module applies. Reconcile is a
    mutation, and a shared Qdrant instance may hold collections this
    project does not own; widening a segment merge onto foreign data is not
    ours to trigger.

    Args:
        client: Qdrant client for the managed server.
        storage_dir: The server ``collections`` directory; ``None`` leaves
            footprints unmeasured rather than guessed.

    Returns:
        One entry per owned collection, ordered by name. Collections whose
        config cannot be read are omitted - an unreadable collection is
        not evidence of drift.
    """
    from .storage_survey import _prefix_of

    try:
        descriptors = sorted(client.get_collections().collections, key=lambda c: c.name)
    except Exception:
        logger.exception("geometry read failed to enumerate collections")
        return []
    entries: list[GeometryEntry] = []
    for descriptor in descriptors:
        name = descriptor.name
        if not _is_canonical_prefix(_prefix_of(name)):
            continue
        try:
            info = client.get_collection(collection_name=name)
        except Exception:
            logger.exception("geometry read failed for collection %s", name)
            continue
        target = getattr(info.config.optimizer_config, "default_segment_number", None)
        footprint: int | None = None
        if storage_dir is not None:
            footprint = _dir_bytes(storage_dir / name)
        entries.append(
            GeometryEntry(
                collection=name,
                segment_target=int(target or 0),
                segments=int(info.segments_count or 0),
                footprint_bytes=footprint,
                settled=_is_settled(info),
            )
        )
    return entries


def plan_reconcile(
    entries: list[GeometryEntry],
    *,
    target: int = store_schema.SERVER_SEGMENT_NUMBER,
    cap: int,
) -> tuple[list[GeometryEntry], int]:
    """Select which drifted collections to reconcile this pass.

    Pure decision logic, separated from IO so the cap, the skip, and the
    ordering are testable without a server.

    Drift is ``segment_target != target``. A collection already at target
    is not drifted regardless of its current segment count, because the
    optimizer legitimately grows segments with real data - actual segment
    count is an outcome, not the setting.

    Largest-footprint-first ordering means a capped pass reclaims the most
    bytes it can; unmeasured footprints sort last rather than displacing
    known-large work.

    Args:
        entries: Geometry for every live collection.
        target: The bounded-geometry segment target.
        cap: Maximum collections to reconcile in this pass; ``<= 0``
            selects none.

    Returns:
        The selected entries and the count of drifted collections left
        over for a later pass.
    """
    drifted = [e for e in entries if e.segment_target != target]
    drifted.sort(key=lambda e: (-(e.footprint_bytes or 0), e.collection))
    if cap <= 0:
        return [], len(drifted)
    return drifted[:cap], max(len(drifted) - cap, 0)


class _StabilityTracker:
    """Counts consecutive unchanged samples of a converging collection.

    A merge is finished when successive readings stop moving, so this
    holds the run of agreeing samples and resets the moment one differs.
    The byte tolerance absorbs incidental churn without masking a real
    merge, which moves hundreds of MiB.
    """

    def __init__(self) -> None:
        self._last: tuple[int, int] | None = None
        self._run = 0

    def observe(self, segments: int, size: int, *, ready: bool) -> bool:
        """Record one sample; return True once it has held long enough.

        ``ready`` gates counting on the collection actually being settled
        and past its start, so an unstarted merge can never accumulate a
        run of "stable" samples.
        """
        matches = (
            self._last is not None
            and self._last[0] == segments
            and abs(size - self._last[1]) <= _CONVERGENCE_BYTE_TOLERANCE
        )
        self._run = self._run + 1 if (ready and matches) else 0
        self._last = (segments, size)
        return self._run >= _CONVERGENCE_STABLE_SAMPLES


def _await_convergence(
    client: QdrantClient,
    collection: str,
    path: Path | None,
    *,
    budget_s: float,
    poll_s: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    stop: threading.Event | None = None,
) -> tuple[int, int | None] | None:
    """Wait until a reconciling collection stops changing.

    The optimizer restructures in the background after the config update
    returns, and while it does BOTH segment count and on-disk size rise
    above their starting values before falling - a 20,000-point collection
    measured 1185 MiB before, 1526 MiB mid-flight, and 440 MiB converged.
    So convergence is *stability*, never a first reading and never a
    monotonic decrease.

    Stability alone is not enough, though: a merge queued behind a
    saturated optimizer thread pool has not started, so its segment count
    and size are also perfectly stable. Waiting is therefore two-phase -
    first observe the collection leave ``green`` (the optimizer picked the
    work up), then wait for it to return to ``green`` and hold steady. A
    collection that never leaves ``green`` within the start window had no
    work to do, and its unchanged measurement is a truthful zero-reclaim
    result rather than a pre-merge reading dressed up as a converged one.

    Returns:
        The converged ``(segments, bytes)`` (bytes ``None`` when
        unmeasurable), or ``None`` if the budget expired or shutdown was
        requested first.
    """

    def _sample() -> tuple[int, int, bool] | None:
        try:
            info = client.get_collection(collection_name=collection)
        except Exception:
            logger.exception("convergence sample failed for %s", collection)
            return None
        return (
            int(info.segments_count or 0),
            _dir_bytes(path) if path is not None else 0,
            _is_settled(info),
        )

    def _result(segments: int, size: int) -> tuple[int, int | None]:
        return segments, (size if path is not None else None)

    deadline = monotonic() + budget_s
    start_deadline = min(deadline, monotonic() + _OPTIMIZER_START_BUDGET_SECONDS)
    tracker = _StabilityTracker()
    started = False
    while monotonic() < deadline:
        if stop is not None and stop.is_set():
            return None
        sample = _sample()
        if sample is None:
            return None
        segments, size, settled = sample
        started = started or not settled
        if not started and monotonic() >= start_deadline:
            # Never left green: there was no merge to wait for, so the
            # unchanged measurement is a truthful zero-reclaim result.
            return _result(segments, size)
        if tracker.observe(segments, size, ready=settled and started):
            return _result(segments, size)
        sleep(poll_s)
    return None


def reconcile_collection(
    client: QdrantClient,
    entry: GeometryEntry,
    *,
    storage_dir: Path | None,
    target: int = store_schema.SERVER_SEGMENT_NUMBER,
    budget_s: float,
    poll_s: float = _CONVERGENCE_POLL_SECONDS,
    wait: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    stop: threading.Event | None = None,
) -> ReconcileResult:
    """Reconcile one collection's segment geometry in place.

    Non-destructive: this updates the optimizer's segment target and lets
    the optimizer merge. No point is moved or deleted and the collection
    stays queryable throughout - verified against a real server to
    preserve exact point counts and return identical search results.

    Only the update call failing is a failure. Budget expiry is
    ``converging``: the collection is left in whatever state the optimizer
    reached, which is valid and self-healing, and a later pass re-evaluates
    it.

    Args:
        client: Qdrant client for the managed server.
        entry: The collection's pre-reconcile geometry.
        storage_dir: The server ``collections`` directory.
        target: The bounded-geometry segment target.
        budget_s: Seconds to wait for convergence.
        poll_s: Seconds between convergence samples.
        wait: When False, issue the update and return ``converging``
            without waiting.
        sleep: Injected for tests; defaults to :func:`time.sleep`.
        monotonic: Injected for tests; defaults to :func:`time.monotonic`.
        stop: Set on shutdown to abandon the wait promptly.

    Returns:
        The :class:`ReconcileResult` for this collection.
    """
    from qdrant_client import models

    path = None if storage_dir is None else storage_dir / entry.collection
    # Measure immediately before mutating: the batch's survey reading can be
    # many minutes stale by the time this collection's turn arrives, and the
    # indexer writes concurrently, so a stale baseline would credit reconcile
    # with someone else's bytes.
    bytes_before = entry.footprint_bytes
    if path is not None:
        bytes_before = _dir_bytes(path)

    # A merge inflates before it shrinks, and these backends are reconciled
    # precisely because they are short on space. Refuse rather than push a
    # full disk into the ENOSPC/WAL-wedge class.
    if bytes_before and storage_dir is not None:
        needed = int(bytes_before * _RECONCILE_HEADROOM_FACTOR)
        free = _free_bytes(storage_dir)
        if free is not None and free < needed + _DISK_FLOOR_BYTES:
            return ReconcileResult(
                entry.collection,
                "skipped",
                segments_before=entry.segments,
                bytes_before=bytes_before,
                reason=(
                    f"insufficient_headroom: needs {needed + _DISK_FLOOR_BYTES} "
                    f"bytes free, has {free}"
                ),
            )

    try:
        client.update_collection(
            collection_name=entry.collection,
            optimizers_config=models.OptimizersConfigDiff(
                default_segment_number=target
            ),
        )
    except Exception as exc:
        logger.exception("reconcile update failed for %s", entry.collection)
        return ReconcileResult(
            entry.collection,
            "failed",
            segments_before=entry.segments,
            bytes_before=bytes_before,
            reason=str(exc),
        )

    if not wait:
        return ReconcileResult(
            entry.collection,
            "converging",
            segments_before=entry.segments,
            bytes_before=bytes_before,
            reason="not_awaited",
        )

    converged = _await_convergence(
        client,
        entry.collection,
        path,
        budget_s=budget_s,
        poll_s=poll_s,
        sleep=sleep,
        monotonic=monotonic,
        stop=stop,
    )
    if converged is None:
        return ReconcileResult(
            entry.collection,
            "converging",
            segments_before=entry.segments,
            bytes_before=bytes_before,
            reason="convergence_budget_expired",
        )
    segments_after, bytes_after = converged
    return ReconcileResult(
        entry.collection,
        "reconciled",
        segments_before=entry.segments,
        segments_after=segments_after,
        bytes_before=bytes_before,
        bytes_after=bytes_after,
    )


def reconcile_collections(
    client: QdrantClient,
    *,
    storage_dir: Path | None,
    target: int = store_schema.SERVER_SEGMENT_NUMBER,
    cap: int,
    budget_s: float,
    dry_run: bool = False,
    wait: bool = True,
    stop: threading.Event | None = None,
    on_progress: Callable[[str], None] = _no_progress,
) -> ReconcileBatch:
    """Reconcile drifted collections toward the bounded geometry.

    Idempotent: a backend already at target selects nothing and reports an
    empty pass, so this is a no-op once converged. Capped, so a backend
    with many drifted collections converges over several passes rather
    than saturating disk in one.

    Args:
        client: Qdrant client for the managed server.
        storage_dir: The server ``collections`` directory.
        target: The bounded-geometry segment target.
        cap: Maximum collections to reconcile this pass.
        budget_s: Per-collection convergence budget in seconds.
        dry_run: Preview the selection without mutating anything.
        wait: When False, issue updates without awaiting convergence.
        on_progress: Sink for progress lines. With ``wait`` set, each
            collection is held on until its optimizer settles, so naming the
            one in flight is the difference between a slow pass and a hang.

    Returns:
        The :class:`ReconcileBatch` for this pass.
    """
    on_progress("Reading collection geometry...")
    entries = read_geometry(client, storage_dir)
    selected, remaining = plan_reconcile(entries, target=target, cap=cap)
    # A collection whose setting is already right but which is still merging
    # is not converged, and the gauge must say so - otherwise "drift is zero"
    # would fire while gigabytes are still in flight. Setting-drift alone is
    # not the whole truth; unsettled collections count too.
    unsettled_at_target = sum(
        1 for e in entries if e.segment_target == target and not e.settled
    )

    if dry_run:
        return ReconcileBatch(
            results=[
                ReconcileResult(
                    e.collection,
                    "would_reconcile",
                    segments_before=e.segments,
                    bytes_before=e.footprint_bytes,
                )
                for e in selected
            ],
            drifted_remaining=remaining + len(selected) + unsettled_at_target,
            reclaimed_bytes=0,
            dry_run=True,
        )

    results: list[ReconcileResult] = []
    for position, entry in enumerate(selected, start=1):
        on_progress(
            f"Reconciling {position}/{len(selected)}: {entry.collection}"
            f" ({entry.segments} segments)"
        )
        results.append(
            reconcile_collection(
                client,
                entry,
                storage_dir=storage_dir,
                target=target,
                budget_s=budget_s,
                wait=wait,
                stop=stop,
            )
        )
    unconverged = sum(1 for r in results if r.status != "reconciled")
    return ReconcileBatch(
        results=results,
        drifted_remaining=remaining + unconverged + unsettled_at_target,
        reclaimed_bytes=sum(r.reclaimed_bytes for r in results),
        dry_run=False,
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
    *,
    on_progress: Callable[[str], None] = _no_progress,
) -> list[NamespaceSurvey]:
    """Survey every stored namespace: enumerate, count, size, classify.

    Includes ``debris`` entries for on-disk collection dirs the live
    server does not list (crash leftovers), so the whole backend is
    visible from one call.

    Args:
        client: Qdrant client for the managed server.
        storage_dir: The server ``collections`` directory for footprints;
            ``None`` (or unresolved) omits byte sizes and debris.
        on_progress: Sink for progress lines. The point count is one server
            round trip per collection and the footprint pass walks the whole
            storage tree, so both are reported against a known total rather
            than as an undifferentiated wait.

    Returns:
        Classified namespace records, actionable states first.
    """
    on_progress("Listing collections...")
    names = [c.name for c in client.get_collections().collections]
    counts: dict[str, int] = {}
    for position, name in enumerate(names, start=1):
        on_progress(f"Counting points ({position}/{len(names)} collections)")
        try:
            counts[name] = int(client.count(collection_name=name).count)
        except (OSError, RuntimeError):
            counts[name] = 0
    on_progress(f"Measuring on-disk footprints for {len(names)} collections...")
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
    if not _is_canonical_prefix(prefix):
        return DeleteResult(prefix, "skipped", reason="invalid_prefix")
    manifest = load_manifest()
    targets = sorted(
        c.name
        for c in client.get_collections().collections
        if c.name.startswith(prefix)
    )
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
    on_progress: Callable[[str], None] = _no_progress,
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
        on_progress: Sink for progress lines, covering both the survey this
            plans from and the per-namespace reclamation.

    Returns:
        A :class:`PruneResult` aggregating the per-namespace outcomes.
    """
    surveys = gather_survey(client, storage_dir, on_progress=on_progress)
    orphaned = [s for s in surveys if s.status == "orphaned"]
    unknown = [s.prefix for s in surveys if s.status == "unknown"]
    results: list[DeleteResult] = []
    reclaimed = 0
    verb = "Planning" if dry_run else "Reclaiming"
    for position, survey in enumerate(orphaned, start=1):
        on_progress(
            f"{verb} orphaned namespace {position}/{len(orphaned)}: {survey.prefix}"
        )
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
    on_progress: Callable[[str], None] = _no_progress,
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
        on_progress: Sink for progress lines, one per mapped collection; a
            real copy moves every point across two backends and is the
            longest-running of the storage verbs.

    Returns:
        One :class:`MigrateResult` per mapped collection.
    """
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
    # Liveness first. An archive taken across a live writer is torn, so this
    # gate has to precede the archive, not just the drop.
    if decision.prefix in active_prefixes():
        return _redecide(decision, "deferred", "active_index_job"), []
    # Re-count immediately before acting, in BOTH tiers. The survey reading
    # can be many minutes stale by the time this prefix's turn arrives, and
    # any movement since means a writer this cycle cannot see. An archive
    # makes loss recoverable, never prevented, so the data tier needs this
    # check at least as much as the empty tier.
    observed = _prefix_points(client, decision.prefix)
    if observed is None:
        return _redecide(decision, "deferred", "points_unverifiable"), []
    if observed != decision.points:
        moved = (
            "points_appeared_since_survey"
            if decision.tier == "empty"
            else "points_changed_since_survey"
        )
        return _redecide(decision, "deferred", moved), []
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
        client,
        roots=roots,
        stamps=load_generation_stamps(),
        now=now,
        grace_hours=policy.grace_hours_data,
        reader_present=_reader_present,
        dry_run=dry_run,
    )
    if not dry_run:
        record_generation_stamps(advanced)
    return results


def run_maintenance_cycle(
    client: QdrantClient,
    *,
    now: datetime,
    policy: ReclaimPolicy,
    storage_dir: Path | None,
    snapshots_dir: Path,
    archive_dir: Path,
    dry_run: bool = False,
    active_prefixes: Callable[[], frozenset[str]] = _active_index_prefixes,
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

    surveys = gather_survey(client, storage_dir)
    stamps = update_orphan_stamps(
        {s.prefix: s.status for s in surveys},
        now_iso=now.isoformat(),
    )
    # The ephemeral tier's idle clock, advanced from what the stored data is
    # doing rather than from index-run stamps alone. Reading the manifest
    # directly here would see only what an indexer chose to stamp, which is
    # the blind spot this tier cannot afford.
    last_indexed = update_activity_stamps(
        {s.prefix: (s.status, s.points) for s in surveys},
        now_iso=now.isoformat(),
    )
    decisions = evaluate_reclaim(
        surveys,
        stamps,
        now=now,
        policy=policy,
        last_indexed=last_indexed,
    )
    generations = _reclaim_generations_for_cycle(
        client,
        surveys=surveys,
        now=now,
        policy=policy,
        dry_run=dry_run,
    )
    applied: list[ReclaimDecision] = []
    archived: list[Path] = []
    reclaimed = 0
    for decision in decisions:
        if decision.action not in ("reclaim_empty", "reclaim_data") or dry_run:
            applied.append(decision)
            continue
        outcome, artifacts = _apply_reclaim(
            client,
            decision,
            snapshots_dir=snapshots_dir,
            archive_dir=archive_dir,
            active_prefixes=active_prefixes,
        )
        archived.extend(artifacts)
        applied.append(outcome)
        if outcome.action in ("removed", "archived_removed"):
            reclaimed += outcome.footprint_bytes
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
    # Reconcile runs last so a convergence budget is never spent on a
    # namespace this same cycle just destroyed. It is non-destructive and
    # independent of the grace machinery above.
    reconcile: ReconcileBatch | None = None
    if policy.reconcile:
        reconcile = reconcile_collections(
            client,
            storage_dir=storage_dir,
            cap=policy.reconcile_max_per_cycle,
            budget_s=policy.reconcile_budget_seconds,
            dry_run=dry_run,
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
    from .generation_survey import decide_generation_reclaim

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
                stamps=stamps,
                now=now,
                grace_hours=grace_hours,
                reader_present=has_reader,
                # survey_generations already omitted any root whose pointer it
                # could not read, so every collection reaching here came from a
                # root whose served name was legible at decision time.
                pointer_verifiable=True,
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


def reclaim_superseded_generations(
    client: QdrantClient,
    *,
    roots: Mapping[str, str],
    stamps: Mapping[str, str],
    now: datetime,
    grace_hours: float,
    reader_present: Callable[[str], bool],
    dry_run: bool,
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

    live = [c.name for c in client.get_collections().collections]
    reports = survey_generations(roots, live)
    results, droppable, held, unreferenced = _evaluate_generation_reports(
        reports,
        stamps=stamps,
        now=now,
        grace_hours=grace_hours,
        reader_present=reader_present,
    )

    # A root omitted from the report had an unreadable pointer, so any
    # generation of it that exists must have its clock reset rather than keep
    # accumulating a window it did not continuously earn.
    reported = {report.root for report in reports}
    _hold_unreported_root_generations(roots, live, reported, held)

    drop_results, dropped = _drop_generation_collections(
        client, droppable, held, dry_run=dry_run
    )
    results.extend(drop_results)

    # A dropped collection keeps no clock: it no longer exists, and a stamp for
    # it would outlive it as debris that never expires. A failed drop is not
    # dropped, so it stays in the held set and its window restarts.
    advanced = advance_generation_stamps(
        stamps,
        unreferenced=(name for name in unreferenced if name not in dropped),
        held=[*held, *dropped],
        now_iso=now.isoformat(),
    )
    return results, advanced
