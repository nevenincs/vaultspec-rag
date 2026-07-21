"""Daemon lifecycle helpers: log paths, heartbeat, and shutdown hooks.

Split out of the original ``server.py`` monolith per the
``2026-06-01-module-split-adr``. ``_heartbeat_tick_sync`` reads the
rebindable ``_status_file_path`` and ``_SERVICE_TOKEN`` through the
package alias so test monkeypatches on ``vaultspec_rag.server`` are
observed.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from ..storage_ops import (
        MaintenanceResult,
        ReclaimPolicy,
        ReconcileBatch,
        ReconcileResult,
    )

__all__ = [
    "_heartbeat_loop",
    "_heartbeat_tick_sync",
    "_install_daemon_shutdown_hooks",
    "_lifecycle_log",
    "_maintenance_loop",
    "_qdrant_liveness_tick",
    "_record_shutdown",
    "_resolve_log_path",
    "_status_file_path",
    "_storage_maintenance_tick_sync",
    "_storage_survey_warm_sync",
    "_survey_warmup_task",
    "_unlink_status_file_silently",
]

import vaultspec_rag.server as _m

from ..logging_config import log_event
from ..serviceclient._discovery import (
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
    _discovery_timestamp,
    _merge_service_status,
)
from ._state import _HEARTBEAT_INTERVAL_SECONDS, _HEARTBEAT_STALENESS_SECONDS

logger = logging.getLogger("vaultspec_rag.server")


def _resolve_log_path() -> Path:
    """Resolve the daemon's rotating log path.

    Mirrors the parent CLI's ``_log_file()`` resolution so the
    daemon writes to the same file the parent created on spawn.
    """
    from ..config import get_config

    cfg = get_config()
    status_dir = Path(cfg.status_dir).expanduser()
    status_dir.mkdir(parents=True, exist_ok=True)
    return status_dir / cfg.log_file


def _status_file_path() -> Path:
    """Resolve the same ``service.json`` path the CLI parent writes.

    The CLI ``cli._status_file()`` builds this path from
    ``cfg.status_dir``; the daemon mirrors that resolution so it can
    own end-of-life cleanup without cross-importing from cli.
    """
    from ..config import get_config

    cfg = get_config()
    return Path(cfg.status_dir).expanduser() / "service.json"


def _lifecycle_log(event: str, **kv: object) -> None:
    """Emit a structured lifecycle entry at activity level.

    Args:
        event: Short identifier (``startup`` / ``shutdown``).
        **kv: Extra key=value fields rendered space-separated for
            greppability.
    """
    log_event(logger, "service.lifecycle", event, fields=kv)


def _unlink_status_file_silently() -> None:
    """Best-effort unlink of service.json and the machine-global pointer.

    Called from atexit, signal handlers, and the lifespan finally block.
    Idempotent because any of those code paths may have already removed a file.
    Both the per-STATUS_DIR ``service.json`` and the machine-global discovery
    pointer beside the lock are cleaned, so a stopped service leaves neither
    behind.
    """
    from .._machine_lock import machine_discovery_path

    status_path = _m._status_file_path()
    paths: list[Path] = []
    try:
        paths.append(machine_discovery_path())
    except Exception as exc:  # config unavailable at a late shutdown stage
        logger.debug("machine discovery pointer path unresolved: %s", exc)
    try:
        from ..serviceclient._discovery import _delete_service_status

        _delete_service_status(path=status_path)
    except (OSError, RuntimeError, TimeoutError) as exc:
        log_event(
            logger,
            "service.lifecycle",
            "cleanup_failed",
            severity=logging.WARNING,
            path=status_path,
            error=exc,
        )
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError as exc:
            # Already-removed is the expected idempotent case.
            logger.debug("discovery file already gone at %s: %s", path, exc)
        except OSError as exc:
            log_event(
                logger,
                "service.lifecycle",
                "cleanup_failed",
                severity=logging.WARNING,
                path=path,
                error=exc,
            )


def _heartbeat_tick_sync() -> None:
    """Synchronous heartbeat write - atomic via .tmp + os.replace.

    Reads the current service.json, merges ``last_heartbeat`` (ISO-8601
    UTC, second resolution), writes through a tmp file. Called from
    inside ``asyncio.to_thread`` so file I/O does not block the event
    loop.

    Exits silently when service.json is missing (the CLI parent may
    have unlinked it during ``server stop`` - the heartbeat
    loop will exit on the next tick).
    """
    path = _m._status_file_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # Read failures are best-effort: the CLI parent wrote the
        # file; the daemon's tick is additive. Debug-log so the
        # swallow stays observable (no-swallow rule).
        logger.debug(
            "heartbeat tick: failed to read %s: %s",
            path,
            exc,
            exc_info=True,
        )
        return
    if not isinstance(data, dict):
        logger.debug(
            "heartbeat tick: %s did not deserialise to dict (got %r)",
            path,
            type(data).__name__,
        )
        return
    # Re-assert the schema discriminator and the single declared timestamp format
    # so a file written by an older parent is upgraded on the first tick and the
    # two timestamp fields never diverge in precision (#190). Surface the staleness
    # contract in the file so a consumer reads it rather than hard-coding a guess.
    fields: dict[str, object] = {
        "schema": SERVICE_DISCOVERY_SCHEMA,
        "version": SERVICE_DISCOVERY_VERSION,
        "last_heartbeat": _discovery_timestamp(),
        "heartbeat_interval_s": _HEARTBEAT_INTERVAL_SECONDS,
        "stale_after_s": _HEARTBEAT_STALENESS_SECONDS,
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
    }
    # Record the daemon's own python environment so operators and `server
    # status` can see which interpreter and venv actually run the service. The
    # daemon inherits the launcher's environment (see `_resolve_daemon_interpreter`)
    # and never provisions its own python; this makes that coupling legible. Field
    # names mirror the /health payload (`executable`/`prefix`) for one vocabulary.
    fields["executable"] = sys.executable
    fields["prefix"] = sys.prefix
    fields["python_version"] = sys.version.split()[0]
    # Record the supervised qdrant child (if any) so operators and the
    # CLI status surface can see the pair without probing the daemon.
    from .. import qdrant_runtime as _qr

    supervisor = _qr.active_supervisor()
    if supervisor is not None:
        from ..qdrant_runtime._resolve import read_qdrant_identity

        identity = read_qdrant_identity()
        supervised_pid = supervisor.pid
        if (
            supervised_pid is None
            and identity is not None
            and identity.http_port == supervisor.http_port
        ):
            supervised_pid = identity.qdrant_pid
        if supervised_pid is not None:
            fields["qdrant_pid"] = supervised_pid
        fields["qdrant_alive"] = supervisor.is_alive()
        fields["qdrant_port"] = supervisor.http_port
        if (
            identity is not None
            and identity.qdrant_pid == supervised_pid
            and identity.http_port == supervisor.http_port
        ):
            fields["qdrant_version"] = identity.version
            fields["qdrant_start_time"] = identity.qdrant_start_time
            fields["qdrant_identity"] = {
                "pid": identity.qdrant_pid,
                "start_time": identity.qdrant_start_time,
                "port": identity.http_port,
                "version": identity.version,
                "storage_path": identity.storage_path,
            }
    # Per-process identity token. Empty during the narrow window
    # between module import and service_lifespan startup; the guard
    # prevents an in-flight zero-value overwrite of a token written
    # by a previous daemon process that crashed without unlinking
    # service.json.
    if _m._SERVICE_TOKEN:
        fields["service_token"] = _m._SERVICE_TOKEN
    try:
        data = _merge_service_status(fields, path=path, require_existing=True)
    except FileNotFoundError:
        return
    # Mirror the same versioned payload to the machine-global discovery pointer
    # beside the lock, so a consumer that does not share this daemon's STATUS_DIR
    # can still find it. Best-effort: a pointer write failure is a discovery
    # nuisance, never a reason to break the heartbeat.
    _write_machine_discovery(data)


def _write_machine_discovery(data: dict[str, object]) -> None:
    """Mirror the discovery payload to the machine-global pointer atomically.

    The pointer is STATUS_DIR-independent (beside the machine lock); a consumer
    reads it to find the one service regardless of its own STATUS_DIR. Best-effort
    and observable: a failure is debug-logged and swallowed (the STATUS_DIR file
    still describes the service; the lock remains the singleton authority).
    """
    from .._machine_lock import machine_discovery_path

    try:
        pointer = machine_discovery_path()
        pointer.parent.mkdir(parents=True, exist_ok=True)
        tmp = pointer.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(str(tmp), str(pointer))
    except OSError as exc:
        logger.debug("machine discovery pointer write skipped: %s", exc, exc_info=True)


def _qdrant_liveness_tick() -> None:
    """Check the supervised qdrant child; one bounded auto-restart.

    Runs synchronously inside the heartbeat's worker thread. A dead
    child gets exactly one restart attempt for the daemon's lifetime;
    after that the dead state surfaces as ``degraded`` through the
    health payload and the runtime-state block until an operator
    intervenes. There is deliberately no background sweeper - this
    rides the existing heartbeat cadence.
    """
    from .. import qdrant_runtime as _qr

    supervisor = _qr.active_supervisor()
    if supervisor is None or supervisor.is_alive():
        return
    if supervisor.restart_count >= 1:
        log_event(
            logger,
            "service.lifecycle",
            "qdrant_dead",
            severity=logging.WARNING,
            restarts=supervisor.restart_count,
        )
        return
    log_event(
        logger,
        "service.lifecycle",
        "qdrant_restart",
        severity=logging.WARNING,
        pid=supervisor.pid,
    )
    if not supervisor.restart():
        log_event(
            logger,
            "service.lifecycle",
            "qdrant_restart_failed",
            severity=logging.ERROR,
        )


async def _heartbeat_loop() -> None:
    """Periodic heartbeat task; cancelled in the lifespan finally.

    Sleeps ``_HEARTBEAT_INTERVAL_SECONDS`` between ticks. Tolerates
    transient write failures so an I/O blip never crashes the
    service; the next tick retries. Each tick also checks the
    supervised qdrant child's liveness (bounded single auto-restart).
    """
    while True:
        try:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            await asyncio.to_thread(_m._heartbeat_tick_sync)
            await asyncio.to_thread(_qdrant_liveness_tick)
        except asyncio.CancelledError:
            return
        except Exception:  # heartbeat must never crash the service
            log_event(
                logger,
                "service.lifecycle",
                "heartbeat_failed",
                severity=logging.WARNING,
                exc_info=True,
            )


def _maintenance_paths() -> tuple[Path, Path, Path] | None:
    """Resolve ``(collections, snapshots, archive)`` dirs, or ``None``.

    All three derive from the configured qdrant storage dir so the tick
    operates on exactly the tree the supervised server owns. ``None``
    when the storage dir is not configured (nothing to maintain).
    """
    from ..config import get_config

    raw = getattr(get_config(), "qdrant_storage_dir", None)
    if not raw:
        return None
    storage = Path(str(raw)).expanduser()
    return (
        storage / "collections",
        storage.parent / "snapshots",
        storage.parent / "archive",
    )


def _build_reclaim_policy() -> ReclaimPolicy:
    """Translate the storage-maintenance knobs into one cycle policy.

    A disabled auto-prune is expressed as a zero reclaim cap rather than a
    skipped cycle: the destructive stages still classify and report, they
    simply never act, so an operator who turns destruction off keeps the
    survey and the non-destructive reconcile.
    """
    from ..config import get_config
    from ..storage_ops import ReclaimPolicy

    cfg = get_config()
    autoprune = bool(cfg.storage_autoprune)
    return ReclaimPolicy(
        grace_hours=float(cfg.storage_autoprune_grace_hours),
        grace_hours_data=float(cfg.storage_autoprune_grace_hours_data),
        max_per_cycle=int(cfg.storage_autoprune_max_per_cycle) if autoprune else 0,
        archive_retention_days=float(cfg.storage_autoprune_archive_retention_days),
        archive_max_bytes=int(float(cfg.storage_autoprune_archive_max_gb) * 1024**3),
        ephemeral_idle_hours=float(cfg.storage_autoprune_ephemeral_idle_hours),
        reconcile=bool(cfg.storage_reconcile),
        reconcile_max_per_cycle=int(cfg.storage_reconcile_max_per_cycle),
        reconcile_budget_seconds=float(cfg.storage_reconcile_budget_seconds),
    )


def _removed_prefixes(result: MaintenanceResult) -> list[str]:
    """Namespaces this cycle actually destroyed."""
    return [
        d.prefix
        for d in result.decisions
        if d.action in ("removed", "archived_removed")
    ]


def _report_cycle_outcome(
    result: MaintenanceResult, *, job_id: str, disk_free: int
) -> None:
    """Record the cycle's job result and emit its rollup log lines."""
    from .. import jobs as _jobs_registry

    removed = _removed_prefixes(result)
    failed = [d.prefix for d in result.decisions if d.action == "failed"]
    reconciled = _report_reconcile(result.reconcile)
    batch = result.reconcile
    summary = (
        f"removed={len(removed)} failed={len(failed)} "
        f"pending={result.pending_grace} reclaimed_bytes={result.reclaimed_bytes}"
    )
    if batch is not None:
        summary += (
            f" reconciled={len(reconciled)} reconciled_bytes={batch.reclaimed_bytes}"
        )
    _jobs_registry.record_finish(
        job_id,
        result=summary,
        phase="error" if failed else "done",
    )
    disk_low = 0 <= disk_free < _DISK_FREE_WARN_BYTES
    log_event(
        logger,
        "service.maintenance",
        "cycle",
        severity=logging.WARNING if (failed or disk_low) else logging.INFO,
        removed=len(removed),
        failed=len(failed),
        pending_grace=result.pending_grace,
        reclaimed_bytes=result.reclaimed_bytes,
        dangling_bytes=result.dangling_bytes,
        archived=len(result.archived),
        swept=len(result.swept),
        reconciled=len(reconciled),
        reconciled_bytes=batch.reclaimed_bytes if batch else 0,
        drifted_remaining=batch.drifted_remaining if batch else 0,
        disk_free_bytes=disk_free,
        namespaces=json.dumps(result.namespace_counts, sort_keys=True),
    )
    if disk_low:
        log_event(
            logger,
            "service.maintenance",
            "disk_low",
            severity=logging.WARNING,
            disk_free_bytes=disk_free,
            threshold_bytes=_DISK_FREE_WARN_BYTES,
        )


def _publish_cycle_metrics(
    result: MaintenanceResult, *, disk_free: int, removed: int
) -> None:
    """Publish one cycle's reclamation gauges and counters."""
    from ..storage_ops import backend_totals
    from ._state import incr, observe

    incr("maintenance_cycles_total")
    incr("maintenance_reclaims_total", removed)
    observe("maintenance_disk_free_bytes", float(max(disk_free, 0)))
    observe("maintenance_dangling_bytes", float(result.dangling_bytes))
    observe("maintenance_pending_grace", float(result.pending_grace))
    observe(
        "maintenance_orphaned_namespaces",
        float(result.namespace_counts.get("orphaned", 0)),
    )
    observe("maintenance_last_reclaimed_bytes", float(result.reclaimed_bytes))
    # Whole-backend size gauges: dangling_bytes counts only orphans, so a
    # pile of live-but-leaked namespaces is invisible without a total.
    totals = backend_totals(result.surveys)
    observe("store_total_bytes", float(cast("int", totals["total_bytes"])))
    observe("store_namespaces", float(cast("int", totals["namespaces"])))


def _report_reconcile(batch: ReconcileBatch | None) -> list[ReconcileResult]:
    """Publish the geometry-reconcile pass and return its converged entries.

    The drifted gauge reaching zero is the operator's signal that the
    backend has finished converging. Only converged entries are logged:
    a still-converging collection has no honest footprint to report,
    because the optimizer inflates size mid-merge before shrinking it.
    """
    if batch is None:
        return []
    from ._state import incr, observe

    reconciled = [r for r in batch.results if r.status == "reconciled"]
    incr("maintenance_reconciled_total", len(reconciled))
    incr("maintenance_reconciled_bytes_total", batch.reclaimed_bytes)
    observe("store_drifted_collections", float(batch.drifted_remaining))
    for entry in reconciled:
        log_event(
            logger,
            "service.maintenance",
            "reconciled",
            collection=entry.collection,
            segments_before=entry.segments_before,
            segments_after=entry.segments_after,
            bytes_before=entry.bytes_before,
            bytes_after=entry.bytes_after,
            reclaimed_bytes=entry.reclaimed_bytes,
        )
    return reconciled


def _storage_maintenance_tick_sync() -> None:
    """Run one scheduled storage-maintenance cycle (pure storage IO).

    Read/drop only: surveys the store, advances the persisted grace
    clocks, reclaims time-confirmed dangling namespaces under the stacked
    safety gates, bounds the archive tree, and emits one rollup line with
    a disk-free warning. Never touches the GPU or the search path, and no
    code reachable from here may enter a service stop/terminate/reclaim
    flow. Skips silently when server mode is off (a local-only store has
    a single namespace and no manifest to maintain).
    """
    from datetime import UTC, datetime

    from qdrant_client import QdrantClient

    from ..config import get_config
    from ..storage_ops import run_maintenance_cycle

    cfg = get_config()
    # Reconcile is non-destructive and independent of the grace machinery, so
    # an operator who disables auto-prune for safety must not silently lose it.
    # The cycle runs while EITHER stage is enabled; each stage gates itself.
    if not cfg.effective_server_mode() or not (
        bool(cfg.storage_autoprune) or bool(cfg.storage_reconcile)
    ):
        return
    paths = _maintenance_paths()
    if paths is None:
        return
    collections_dir, snapshots_dir, archive_dir = paths
    policy = _build_reclaim_policy()
    from .. import jobs as _jobs_registry

    job_id = _jobs_registry.record_start(
        "maintenance", "schedule", command="storage_maintenance"
    )
    url = str(cfg.qdrant_url or "") or f"http://127.0.0.1:{cfg.qdrant_port}"
    client = QdrantClient(url=url)
    now = datetime.now(UTC)
    try:
        result = run_maintenance_cycle(
            client,
            now=now,
            policy=policy,
            storage_dir=collections_dir if collections_dir.is_dir() else None,
            snapshots_dir=snapshots_dir,
            archive_dir=archive_dir,
        )
    except BaseException as exc:
        _jobs_registry.record_finish(job_id, error=str(exc))
        raise
    finally:
        client.close()

    _publish_survey_from_cycle(result, now.isoformat())

    import shutil

    try:
        disk_free = shutil.disk_usage(str(collections_dir.parent)).free
    except OSError:
        disk_free = -1
    _publish_cycle_metrics(
        result,
        disk_free=disk_free,
        removed=len(_removed_prefixes(result)),
    )
    _report_cycle_outcome(result, job_id=job_id, disk_free=disk_free)


# Warn threshold for free disk on the volume holding the qdrant storage
# tree: one collection pair preallocates ~2.1GB of mmaps, so anything
# under a few collections' worth of headroom is one index away from
# opaque server-side write failures.
_DISK_FREE_WARN_BYTES = 10 * 1024**3


def _publish_survey_from_cycle(result: MaintenanceResult, now_iso: str) -> None:
    """Publish a maintenance cycle's survey as the daemon's snapshot.

    Makes the ``/storage/survey`` route O(1) instead of re-walking every
    collection footprint. Prefixes the cycle just removed are dropped so the
    snapshot never advertises a namespace that no longer exists.
    """
    from ._state import publish_survey_snapshot

    reclaimed_prefixes = {
        d.prefix
        for d in result.decisions
        if d.action in ("removed", "archived_removed")
    }
    publish_survey_snapshot(
        [s for s in result.surveys if s.prefix not in reclaimed_prefixes],
        computed_at=now_iso,
    )


def _storage_survey_warm_sync() -> None:
    """Gather one read-only survey and publish it as the snapshot.

    Runs once shortly after startup so the survey route is warm from the
    daemon's first minutes instead of waiting a full maintenance interval
    (whose first run is deliberately delayed). Pure storage IO: no grace
    stamps advance, nothing is reclaimed, the GPU is never touched. Skips
    silently outside server mode.
    """
    from qdrant_client import QdrantClient

    from ..config import get_config
    from ..storage_ops import gather_survey, server_storage_collections_dir

    cfg = get_config()
    if not cfg.effective_server_mode():
        return
    url = str(cfg.qdrant_url or "") or f"http://127.0.0.1:{cfg.qdrant_port}"
    client = QdrantClient(url=url)
    try:
        surveys = gather_survey(client, server_storage_collections_dir())
    finally:
        client.close()
    from datetime import UTC, datetime

    from ._state import publish_survey_snapshot

    publish_survey_snapshot(surveys, computed_at=datetime.now(UTC).isoformat())


# Small startup delay before the one-shot survey warmup: lets the supervised
# qdrant child finish settling and keeps the walk off the critical startup
# path, while still warming the cache long before the first maintenance
# interval elapses.
_SURVEY_WARMUP_DELAY_SECONDS = 5.0


async def _survey_warmup_task() -> None:
    """One-shot startup warmer for the survey snapshot; crash-proof."""
    try:
        await asyncio.sleep(_SURVEY_WARMUP_DELAY_SECONDS)
        from ._state import survey_snapshot

        # The warmer only fills a cold slot: if a fresh route call or an
        # early maintenance cycle already published, keep that snapshot.
        if survey_snapshot() is None:
            await asyncio.to_thread(_m._storage_survey_warm_sync)
    except asyncio.CancelledError:
        return
    except Exception:  # warmup is best-effort; the route falls back to fresh
        log_event(
            logger,
            "service.maintenance",
            "survey_warmup_failed",
            severity=logging.WARNING,
            exc_info=True,
        )


async def _maintenance_loop() -> None:
    """Hourly storage-maintenance task; cancelled in the lifespan finally.

    Mirrors ``_heartbeat_loop``'s crash-proof shape: the first run is
    delayed one full interval (a freshly started daemon serves before it
    sweeps) and no exception may escape - a failed cycle logs and the
    next tick retries.
    """
    from ..config import get_config

    while True:
        try:
            minutes = float(get_config().storage_autoprune_interval_minutes)
            await asyncio.sleep(max(1.0, minutes * 60.0))
            await asyncio.to_thread(_m._storage_maintenance_tick_sync)
        except asyncio.CancelledError:
            return
        except Exception:  # maintenance must never crash the service
            log_event(
                logger,
                "service.maintenance",
                "cycle_failed",
                severity=logging.WARNING,
                exc_info=True,
            )
            # A failure BEFORE the interval sleep (e.g. a config coercion
            # error) would otherwise recur instantly with no await point,
            # pinning the event loop and starving every request handler.
            # Back off a full minute so the loop always yields.
            await asyncio.sleep(60.0)


def _record_shutdown(reason: str, **kv: object) -> None:
    """Log + unlink once; subsequent calls are no-ops.

    atexit, the signal handler, and the lifespan finally block may
    all fire in sequence. The first one wins. The guard
    (``_shutdown_recorded``) is read and written on the package
    namespace so a test rebind of ``server._shutdown_recorded`` is
    observed (it was a plain module global pre-split).
    """
    if _m._shutdown_recorded:
        return
    _m._shutdown_recorded = True
    _m._lifecycle_log("shutdown", reason=reason, **kv)
    _m._unlink_status_file_silently()


def _install_daemon_shutdown_hooks() -> None:
    """Register atexit cleanup once per process.

    SIGTERM/SIGINT are intentionally NOT overridden - uvicorn already
    installs its own graceful-shutdown handler for those signals that
    triggers the lifespan ``finally`` block (which calls
    ``_record_shutdown("clean")``). Overriding here breaks that
    cooperation: a manual signal handler re-raising via
    ``os.kill(SIG_DFL)`` exits the process before logging buffers
    flush, so the lifecycle log line never lands on disk.

    atexit covers the cases uvicorn doesn't (fatal exception during
    startup, ``sys.exit`` from inside the request path). SIGKILL /
    OOM remain unreachable by design; the heartbeat staleness check
    in ``service status`` is the safety net for those.

    Idempotent: a second call is a no-op.

    The install guard lives on the package namespace so it stays a
    single per-process flag across the split submodules.
    """
    if _m._shutdown_hooks_installed:
        return
    _m._shutdown_hooks_installed = True

    atexit.register(lambda: _m._record_shutdown("atexit"))
