"""Service-domain survey, debris, and namespace deletion operations."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

from .storage_manifest import load_manifest, remove_prefix
from .storage_survey import (
    NamespaceSurvey,
    classify_namespaces,
    is_canonical_prefix,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)


def _no_progress(_line: str) -> None:
    """Drop a progress line when the caller has no reporting surface."""


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
    from .config._settings import get_config

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
    # A missing directory needs no guard: os.walk over an absent path
    # silently yields nothing, so directory_size_bytes already returns 0.
    return {name: directory_size_bytes(storage_dir / name) for name in collection_names}


def directory_size_bytes(path: Path) -> int:
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
            footprint_bytes=sum(directory_size_bytes(p) for p in paths),
        )
        for prefix, paths in grouped.items()
    ]


class BackendTotals(TypedDict):
    """The whole-backend rollup :func:`backend_totals` reports."""

    total_bytes: int
    namespaces: int
    points: int
    vault_points: int
    code_points: int
    document_points: int
    by_status_bytes: dict[str, int]


def backend_totals(surveys: list[NamespaceSurvey]) -> BackendTotals:
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
        # debris_surveys() returns [] whenever storage_dir is None, so a
        # non-empty survey here proves storage_dir was given.
        for name in survey.collections:
            path = cast("Path", storage_dir) / name
            size = directory_size_bytes(path)
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
    if not is_canonical_prefix(prefix):
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
