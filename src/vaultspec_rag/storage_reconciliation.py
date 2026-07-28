"""Service-domain collection geometry reconciliation."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, Unpack

from . import store_schema
from ._store_writes import DISK_FLOOR_BYTES as _DISK_FLOOR_BYTES
from ._store_writes import free_bytes
from .storage_survey import is_canonical_prefix
from .storage_survey_ops import directory_size_bytes

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable
    from pathlib import Path

    from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

_CONVERGENCE_STABLE_SAMPLES = 4
_CONVERGENCE_POLL_SECONDS = 3.0
_CONVERGENCE_BYTE_TOLERANCE = 1024 * 1024
_OPTIMIZER_START_BUDGET_SECONDS = 30.0
_RECONCILE_HEADROOM_FACTOR = 0.5


def _no_progress(_line: str) -> None:
    """Drop a progress line when the caller has no reporting surface."""


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


class _ConvergenceOptions(TypedDict, total=False):
    budget_s: float
    poll_s: float
    start_budget_s: float
    sleep: Callable[[float], None]
    monotonic: Callable[[], float]
    stop: threading.Event | None


class _CollectionOptions(TypedDict, total=False):
    storage_dir: Path | None
    target: int
    budget_s: float
    poll_s: float
    start_budget_s: float
    wait: bool
    sleep: Callable[[float], None]
    monotonic: Callable[[], float]
    stop: threading.Event | None


class _BatchOptions(TypedDict, total=False):
    storage_dir: Path | None
    target: int
    cap: int
    budget_s: float
    poll_s: float
    start_budget_s: float
    dry_run: bool
    wait: bool
    stop: threading.Event | None
    on_progress: Callable[[str], None]


@dataclass(frozen=True)
class _ConvergenceRequest:
    client: QdrantClient
    collection: str
    path: Path | None
    budget_s: float
    poll_s: float = _CONVERGENCE_POLL_SECONDS
    start_budget_s: float = _OPTIMIZER_START_BUDGET_SECONDS
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    stop: threading.Event | None = None


@dataclass(frozen=True)
class _CollectionRequest:
    client: QdrantClient
    entry: GeometryEntry
    storage_dir: Path | None
    budget_s: float
    target: int = store_schema.SERVER_SEGMENT_NUMBER
    poll_s: float = _CONVERGENCE_POLL_SECONDS
    start_budget_s: float = _OPTIMIZER_START_BUDGET_SECONDS
    wait: bool = True
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    stop: threading.Event | None = None


@dataclass(frozen=True)
class _BatchRequest:
    client: QdrantClient
    storage_dir: Path | None
    cap: int
    budget_s: float
    target: int = store_schema.SERVER_SEGMENT_NUMBER
    poll_s: float = _CONVERGENCE_POLL_SECONDS
    start_budget_s: float = _OPTIMIZER_START_BUDGET_SECONDS
    dry_run: bool = False
    wait: bool = True
    stop: threading.Event | None = None
    on_progress: Callable[[str], None] = _no_progress


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
        if not is_canonical_prefix(_prefix_of(name)):
            continue
        try:
            info = client.get_collection(collection_name=name)
        except Exception:
            logger.exception("geometry read failed for collection %s", name)
            continue
        target = getattr(info.config.optimizer_config, "default_segment_number", None)
        footprint: int | None = None
        if storage_dir is not None:
            footprint = directory_size_bytes(storage_dir / name)
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


def await_convergence(
    client: QdrantClient,
    collection: str,
    path: Path | None,
    **options: Unpack[_ConvergenceOptions],
) -> tuple[int, int | None] | None:
    """Wait until a reconciling collection stops changing."""
    return _await_convergence_request(
        _ConvergenceRequest(client, collection, path, **options)
    )


def _await_convergence_request(
    request: _ConvergenceRequest,
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

    (
        client,
        collection,
        path,
        budget_s,
        poll_s,
        start_budget_s,
        sleep,
        monotonic,
        stop,
    ) = (
        request.client,
        request.collection,
        request.path,
        request.budget_s,
        request.poll_s,
        request.start_budget_s,
        request.sleep,
        request.monotonic,
        request.stop,
    )

    def _sample() -> tuple[int, int, bool] | None:
        try:
            info = client.get_collection(collection_name=collection)
        except Exception:
            logger.exception("convergence sample failed for %s", collection)
            return None
        return (
            int(info.segments_count or 0),
            directory_size_bytes(path) if path is not None else 0,
            _is_settled(info),
        )

    def _result(segments: int, size: int) -> tuple[int, int | None]:
        return segments, (size if path is not None else None)

    deadline = monotonic() + budget_s
    start_deadline = min(deadline, monotonic() + start_budget_s)
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
    **options: Unpack[_CollectionOptions],
) -> ReconcileResult:
    """Reconcile one collection's segment geometry in place."""
    return _reconcile_collection(_CollectionRequest(client, entry, **options))


def _reconcile_collection(request: _CollectionRequest) -> ReconcileResult:
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
        start_budget_s: Seconds to wait for the optimizer to pick the work
            up before concluding there was none to do. A collection with
            nothing to merge always spends this in full, so a caller that
            expects no work can hand in a short one.
        wait: When False, issue the update and return ``converging``
            without waiting.
        sleep: Injected for tests; defaults to :func:`time.sleep`.
        monotonic: Injected for tests; defaults to :func:`time.monotonic`.
        stop: Set on shutdown to abandon the wait promptly.

    Returns:
        The :class:`ReconcileResult` for this collection.
    """
    from qdrant_client import models

    (
        client,
        entry,
        storage_dir,
        target,
        budget_s,
        poll_s,
        start_budget_s,
        wait,
        sleep,
        monotonic,
        stop,
    ) = (
        request.client,
        request.entry,
        request.storage_dir,
        request.target,
        request.budget_s,
        request.poll_s,
        request.start_budget_s,
        request.wait,
        request.sleep,
        request.monotonic,
        request.stop,
    )

    path = None if storage_dir is None else storage_dir / entry.collection
    # Measure immediately before mutating: the batch's survey reading can be
    # many minutes stale by the time this collection's turn arrives, and the
    # indexer writes concurrently, so a stale baseline would credit reconcile
    # with someone else's bytes.
    bytes_before = entry.footprint_bytes
    if path is not None:
        bytes_before = directory_size_bytes(path)

    # A merge inflates before it shrinks, and these backends are reconciled
    # precisely because they are short on space. Refuse rather than push a
    # full disk into the ENOSPC/WAL-wedge class.
    if bytes_before and storage_dir is not None:
        needed = int(bytes_before * _RECONCILE_HEADROOM_FACTOR)
        free = free_bytes(storage_dir)
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

    converged = await_convergence(
        client,
        entry.collection,
        path,
        budget_s=budget_s,
        poll_s=poll_s,
        start_budget_s=start_budget_s,
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
    **options: Unpack[_BatchOptions],
) -> ReconcileBatch:
    """Reconcile drifted collections toward the bounded geometry."""
    return _reconcile_collections(_BatchRequest(client, **options))


def _reconcile_collections(request: _BatchRequest) -> ReconcileBatch:
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
        poll_s: Seconds between convergence samples. The number of agreeing
            samples convergence requires is fixed; this is only how far
            apart they are taken.
        start_budget_s: Per-collection budget for the optimizer to pick the
            work up before it counts as having none.
        dry_run: Preview the selection without mutating anything.
        wait: When False, issue updates without awaiting convergence.
        on_progress: Sink for progress lines. With ``wait`` set, each
            collection is held on until its optimizer settles, so naming the
            one in flight is the difference between a slow pass and a hang.

    Returns:
        The :class:`ReconcileBatch` for this pass.
    """
    (
        client,
        storage_dir,
        target,
        cap,
        budget_s,
        poll_s,
        start_budget_s,
        dry_run,
        wait,
        stop,
        on_progress,
    ) = (
        request.client,
        request.storage_dir,
        request.target,
        request.cap,
        request.budget_s,
        request.poll_s,
        request.start_budget_s,
        request.dry_run,
        request.wait,
        request.stop,
        request.on_progress,
    )
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
                poll_s=poll_s,
                start_budget_s=start_budget_s,
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
