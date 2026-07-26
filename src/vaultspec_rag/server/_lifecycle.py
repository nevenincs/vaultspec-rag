"""Daemon lifecycle helpers: log paths, heartbeat, and shutdown hooks.

Split out of the original ``server.py`` monolith. ``_heartbeat_tick_sync`` reads the
rebindable ``_status_file_path`` and ``_SERVICE_TOKEN`` through the
package alias, so a tick that fires after startup writes the identity the
daemon actually runs on rather than the empty pre-startup value.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .._machine_lock import MachineLockLease
    from ..storage_ops import (
        MaintenanceResult,
        ReclaimPolicy,
        ReconcileBatch,
        ReconcileResult,
    )

__all__ = [
    "_QDRANT_CLIENT_OP_TIMEOUT_SECONDS",
    "_DiscoveryPublisher",
    "_daemon_discovery_snapshot",
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
]

import vaultspec_rag.server as _m

from .._runtime_identity import interpreter_fields
from ..config import SERVICE_STATUS_FILENAME
from ..logging_config import log_event
from ..serviceclient._discovery import (
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
    SERVICE_PHASE_WARMING,
    _discovery_timestamp,
)
from ._state import _HEARTBEAT_INTERVAL_SECONDS, _HEARTBEAT_STALENESS_SECONDS

logger = logging.getLogger("vaultspec_rag.server")

# Bound every managed-Qdrant client operation (get_collections, survey,
# maintenance) so a half-dead child that accepts the socket but never answers
# cannot block the caller forever. The startup manifest reconcile runs on the
# critical path with the machine lease held, so an unbounded call there would
# strand the singleton; the qdrant-client floor does not guarantee a default.
_QDRANT_CLIENT_OP_TIMEOUT_SECONDS = 30

_atexit_publisher: _DiscoveryPublisher | None = None


def _resolve_log_path() -> Path:
    """Resolve the daemon's rotating log path.

    Mirrors the parent CLI's ``_log_file()`` resolution so the
    daemon writes to the same file the parent created on spawn.
    """
    from ..config import get_config

    cfg = get_config()
    status_dir = Path(cfg.status_dir).expanduser()
    from .._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="create the managed service log directory",
        targets=(status_dir,),
    )
    status_dir.mkdir(parents=True, exist_ok=True)
    return status_dir / cfg.log_file


def _status_file_path() -> Path:
    """Resolve the same discovery-file path the client reads.

    Shares the filename with every other reader via
    ``config.SERVICE_STATUS_FILENAME``, but resolves the directory itself
    rather than calling ``serviceclient._discovery._status_file()``: that one
    CREATES the status directory as a side effect of resolving it, which is
    wrong on the daemon's shutdown path, where this is used to remove the file
    it is about to stop publishing.
    """
    from ..config import get_config

    cfg = get_config()
    return Path(cfg.status_dir).expanduser() / SERVICE_STATUS_FILENAME


def _qdrant_discovery_fields() -> dict[str, object]:
    """Return daemon-observed Qdrant identity fields for one snapshot."""
    from ..qdrant_runtime import _supervise

    supervisor = _supervise.active_supervisor()
    if supervisor is None:
        return {}
    from ..qdrant_runtime._resolve import read_qdrant_identity

    identity = read_qdrant_identity()
    supervised_pid = supervisor.pid
    if (
        supervised_pid is None
        and identity is not None
        and identity.http_port == supervisor.http_port
    ):
        supervised_pid = identity.qdrant_pid
    fields: dict[str, object] = {
        "qdrant_alive": supervisor.is_alive(),
        "qdrant_port": supervisor.http_port,
    }
    if supervised_pid is not None:
        fields["qdrant_pid"] = supervised_pid
    if (
        identity is not None
        and identity.qdrant_pid == supervised_pid
        and identity.http_port == supervisor.http_port
    ):
        fields.update(
            {
                "qdrant_version": identity.version,
                "qdrant_start_time": identity.qdrant_start_time,
                "qdrant_identity": {
                    "pid": identity.qdrant_pid,
                    "start_time": identity.qdrant_start_time,
                    "port": identity.http_port,
                    "version": identity.version,
                    "storage_path": identity.storage_path,
                },
            }
        )
    return fields


def _daemon_discovery_snapshot(
    *,
    phase: str,
    started_at: str,
    phase_detail: str = "",
    phase_done: int | None = None,
    phase_total: int | None = None,
) -> dict[str, object]:
    """Build one complete discovery view from daemon-owned live state.

    ``phase_detail`` is an optional human-readable description of the current
    cold-start stage (provisioning the qdrant server, loading models, warming)
    that the CLI start spinner renders so a minutes-long warm-up shows visible
    progress instead of a static wait. It is advisory only: the coarse ``phase``
    (``warming``/``running``) remains the authoritative machine-readable state,
    and a reader that ignores ``phase_detail`` sees unchanged behaviour.
    """
    from ..serviceclient._compat import (
        SERVICE_VERSION_FIELD,
        local_package_version,
    )
    from ..serviceclient._discovery import (
        SERVICE_PHASE_RUNNING,
        SERVICE_PHASE_WARMING,
    )

    if phase not in {SERVICE_PHASE_WARMING, SERVICE_PHASE_RUNNING}:
        msg = f"unsupported daemon discovery phase: {phase!r}"
        raise ValueError(msg)
    if _m._service_port <= 0:
        raise RuntimeError("service port is unavailable for discovery publication")
    if not _m._SERVICE_TOKEN:
        raise RuntimeError(
            "service identity token is unavailable for discovery publication"
        )
    fields: dict[str, object] = {
        "schema": SERVICE_DISCOVERY_SCHEMA,
        "version": SERVICE_DISCOVERY_VERSION,
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "port": _m._service_port,
        "phase": phase,
        "phase_detail": phase_detail,
        "started_at": started_at,
        "last_heartbeat": _discovery_timestamp(),
        "heartbeat_interval_s": _HEARTBEAT_INTERVAL_SECONDS,
        "stale_after_s": _HEARTBEAT_STALENESS_SECONDS,
        "service_token": _m._SERVICE_TOKEN,
        **interpreter_fields(),
        "python_version": sys.version.split()[0],
        # The package release, alongside the interpreter version that was
        # already here. A consumer that reads this pointer can refuse an
        # incompatible daemon without an HTTP probe.
        SERVICE_VERSION_FIELD: local_package_version(),
    }
    if _m._launch_token:
        fields["launch_token"] = _m._launch_token
    # Optional count for a determinate startup signal (e.g. models loaded of the
    # configured set). Carried only when a total is known so a countless stage
    # publishes just the label; consumers absent the fields render a spinner.
    if phase_total is not None:
        fields["phase_total"] = phase_total
        fields["phase_done"] = phase_done or 0
    fields.update(_qdrant_discovery_fields())
    return fields


class RunningClaimContendedError(RuntimeError):
    """The authoritative RUNNING status could not be published.

    Raised only from the ``require=True`` publish when the service status write
    lock is held by ANOTHER process - i.e. the machine is owned elsewhere and
    this daemon must yield. The rollback that follows treats its own inability
    to clean the discovery views (it needs that same held lock) as the expected
    outcome of yielding, not a fault, so it still records a completed shutdown.
    A different publish failure (disk error, not lock contention) is a genuine
    fault and does NOT raise this type.
    """


@dataclass(slots=True)
class _DiscoveryPublisher:
    """Serialize owner-authenticated heartbeat publication and shutdown."""

    lease: MachineLockLease
    started_at: str = field(default_factory=_discovery_timestamp)
    phase: str = SERVICE_PHASE_WARMING
    phase_detail: str = ""
    phase_done: int | None = None
    phase_total: int | None = None
    _guard: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
    )
    _stopping: bool = field(default=False, init=False, repr=False)
    _cleaned: bool = field(default=False, init=False, repr=False)

    def publish_phase(
        self,
        phase: str,
        *,
        detail: str = "",
        done: int | None = None,
        total: int | None = None,
        require: bool = False,
    ) -> dict[str, object] | None:
        """Set *phase* (and optional cold-start *detail*) and publish it.

        With ``require`` the service-status publication is authoritative: a
        failure to record it is raised rather than swallowed. This is for the
        RUNNING claim of a machine-singleton service - if the daemon cannot
        record that it owns the machine and is serving (another process holds
        the status write lock), it must NOT serve, because a second daemon may
        own the machine's single GPU and Qdrant storage. WARMING and heartbeat
        publications stay best-effort (``require=False``).

        ``detail`` is a human-readable description of the current warm-up stage
        (e.g. "provisioning the qdrant server", "loading models") that the CLI
        start spinner renders. It is carried on every subsequent publication -
        including heartbeats - until the next ``publish_phase`` changes it, so a
        stage set here stays visible while that stage runs.
        """
        with self._guard:
            if self._stopping:
                return None
            self.phase = phase
            self.phase_detail = detail
            self.phase_done = done
            self.phase_total = total
            return self._publish_locked(require=require)

    def heartbeat(self) -> dict[str, object] | None:
        """Publish one heartbeat unless quiescence has begun."""
        with self._guard:
            if self._stopping:
                return None
            return self._publish_locked()

    def quiesce(self, *, timeout: float | None = None) -> None:
        """Prevent new publication and join any in-flight synchronous tick.

        With ``timeout`` (shutdown) the wait for an in-flight tick's guard is
        bounded. This is the first step of daemon teardown, and a heartbeat
        worker wedged inside a synchronous publish - slow or contended
        status/pointer file I/O - holds ``_guard`` and would otherwise strand
        the whole shutdown here before any shutdown line is logged. Past the
        deadline the stop flag is set without the guard (a later tick then
        observes it and goes inert) so a bounded shutdown proceeds; the wedged
        worker dies with the process at the forced exit. Without ``timeout`` the
        acquire is unbounded, as for a normal non-shutdown quiesce.
        """
        acquired = self._guard.acquire(
            timeout=-1 if timeout is None else max(0.0, timeout)
        )
        if not acquired:
            self._stopping = True
            log_event(
                logger,
                "service.lifecycle",
                "quiesce_unjoined",
                severity=logging.WARNING,
            )
            return
        try:
            self._stopping = True
        finally:
            self._guard.release()

    def cleanup(self, *, timeout: float | None = None) -> bool:
        """Delete both views under the retained lease and report convergence.

        As with :meth:`quiesce`, ``timeout`` bounds the guard acquisition at
        shutdown: a worker still wedged inside a synchronous publish must not
        hold teardown open. Past the deadline the deletion runs unguarded -
        safe because the caller is discarding state and about to force-exit -
        so cleanup converges instead of blocking.
        """
        from .._machine_lock import delete_machine_discovery
        from ..serviceclient._discovery import _delete_service_status

        acquired = self._guard.acquire(
            timeout=-1 if timeout is None else max(0.0, timeout)
        )
        if not acquired:
            log_event(
                logger,
                "service.lifecycle",
                "cleanup_unguarded",
                severity=logging.WARNING,
            )
        try:
            if self._cleaned:
                return True
            self._stopping = True
            status_clean = False
            pointer_clean = False
            status_path: Path | None = None
            try:
                status_path = _m._status_file_path()
                _delete_service_status(path=status_path)
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                log_event(
                    logger,
                    "service.lifecycle",
                    "cleanup_failed",
                    severity=logging.WARNING,
                    path=status_path or "unresolved service status path",
                    error=exc,
                )
            else:
                status_clean = True
            try:
                delete_machine_discovery(self.lease)
            except (OSError, PermissionError) as exc:
                log_event(
                    logger,
                    "service.lifecycle",
                    "cleanup_failed",
                    severity=logging.WARNING,
                    path=self.lease.path.parent / SERVICE_STATUS_FILENAME,
                    error=exc,
                )
            else:
                pointer_clean = True
            self._cleaned = status_clean and pointer_clean
            return self._cleaned
        finally:
            if acquired:
                self._guard.release()

    def _publish_locked(self, *, require: bool = False) -> dict[str, object]:
        """Publish each view independently while holding the lifecycle gate.

        With ``require`` a service-status write failure is re-raised (the
        authoritative RUNNING claim); otherwise it is swallowed as a
        best-effort publication. The machine-discovery pointer stays
        best-effort in both modes - the status write is the claim the CLI and
        health path read back to confirm the running owner.
        """
        from .._machine_lock import publish_machine_discovery
        from ..serviceclient._discovery import _replace_service_status

        snapshot = _daemon_discovery_snapshot(
            phase=self.phase,
            started_at=self.started_at,
            phase_detail=self.phase_detail,
            phase_done=self.phase_done,
            phase_total=self.phase_total,
        )
        try:
            status_path = _m._status_file_path()
            _replace_service_status(snapshot, path=status_path)
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            if require:
                # A ``TimeoutError`` here means the status write lock is held by
                # another owner (contention), distinct from a genuine write
                # fault. Signal the contention case so the rollback knows it is
                # yielding the machine and records a completed shutdown despite
                # being unable to clean the views the other owner holds.
                if isinstance(exc, TimeoutError):
                    raise RunningClaimContendedError(
                        "authoritative RUNNING claim yielded: the service "
                        "status write lock is held by another owner"
                    ) from exc
                raise
            logger.debug(
                "service status snapshot publication skipped: %s",
                exc,
                exc_info=True,
            )
        try:
            publish_machine_discovery(self.lease, snapshot)
        except (OSError, PermissionError, TypeError, ValueError) as exc:
            logger.debug(
                "machine discovery pointer publication skipped: %s",
                exc,
                exc_info=True,
            )
        return snapshot


def _lifecycle_log(event: str, **kv: object) -> None:
    """Emit a structured lifecycle entry at activity level.

    Args:
        event: Short identifier (``startup`` / ``shutdown``).
        **kv: Extra key=value fields rendered space-separated for
            greppability.
    """
    log_event(logger, "service.lifecycle", event, fields=kv)


def _heartbeat_tick_sync(publisher: _DiscoveryPublisher) -> None:
    """Publish one synchronous daemon-owned heartbeat snapshot."""
    publisher.heartbeat()


def _qdrant_liveness_tick() -> None:
    """Check the supervised qdrant child; one bounded auto-restart.

    Runs synchronously inside the heartbeat's worker thread. A dead
    child gets exactly one restart attempt for the daemon's lifetime;
    after that the dead state surfaces as ``degraded`` through the
    health payload and the runtime-state block until an operator
    intervenes. There is deliberately no background sweeper - this
    rides the existing heartbeat cadence.
    """
    from ..qdrant_runtime import _supervise

    supervisor = _supervise.active_supervisor()
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


async def _heartbeat_loop(publisher: _DiscoveryPublisher) -> None:
    """Periodic heartbeat task; cancelled in the lifespan finally.

    Sleeps ``_HEARTBEAT_INTERVAL_SECONDS`` between ticks. Tolerates
    transient write failures so an I/O blip never crashes the
    service; the next tick retries. Each tick also checks the
    supervised qdrant child's liveness (bounded single auto-restart).
    """
    while True:
        try:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            await asyncio.to_thread(_m._heartbeat_tick_sync, publisher)
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
    client = QdrantClient(url=url, timeout=_QDRANT_CLIENT_OP_TIMEOUT_SECONDS)
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
    client = QdrantClient(url=url, timeout=_QDRANT_CLIENT_OP_TIMEOUT_SECONDS)
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
    """Log shutdown once; owner cleanup is a separate ordered operation.

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


def _atexit_shutdown() -> None:
    """Best-effort owner cleanup for exits outside lifespan shutdown."""
    publisher = _atexit_publisher
    if publisher is not None:
        publisher.quiesce()
        publisher.cleanup()
    _m._record_shutdown("atexit")


def _install_daemon_shutdown_hooks(publisher: _DiscoveryPublisher) -> None:
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
    global _atexit_publisher
    _atexit_publisher = publisher
    if _m._shutdown_hooks_installed:
        return
    _m._shutdown_hooks_installed = True

    atexit.register(_atexit_shutdown)
