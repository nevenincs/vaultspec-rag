"""Service lifespan and the raw ``/health`` endpoint.

Split out of the original ``server.py`` monolith. ``service_lifespan``
reassigns the process-wide ``_start_time`` / ``_SERVICE_TOKEN`` on the
package namespace so ``health_handler`` (and tests that rebind
``_registry`` / ``_start_time``) observe the live values through the
package alias.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

from anyio.to_thread import run_sync as _run_in_thread

import vaultspec_rag.server as _m

from .._machine_lock import (
    MachineLockLease,
    acquire_machine_lock_lease,
    release_machine_lock_lease,
)
from ..capabilities import backend_capabilities_dict
from ..logging_config import log_event
from ._lifecycle import _DiscoveryPublisher

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.applications import Starlette
    from starlette.requests import Request

    from ..job_manager import JobManager, JobShutdownResult
    from ..qdrant_runtime import QdrantRuntimeState, QdrantSupervisor
    from ..service import ServiceHealth

logger = logging.getLogger("vaultspec_rag.server")


class _CanonicalJobRestoreError(RuntimeError):
    """A fresh canonical manager could not restore its durable generation."""


def _claim_machine_singleton() -> MachineLockLease:
    """Acquire the machine singleton lock or abort startup with a clear cause.

    A live holder means another resident service already owns this machine's
    single GPU and single-writer Qdrant storage; a stale lock from a dead holder
    is reclaimed by the acquire itself.
    """
    lease, holder = acquire_machine_lock_lease()
    if lease is None:
        raise RuntimeError(
            f"another vaultspec-rag service (pid {holder}) already owns this "
            "machine; one resident service owns the GPU and the managed Qdrant. "
            "Stop it first, or run on a dedicated machine."
        )
    return lease


def _stamp_service_phase(publisher: _DiscoveryPublisher, phase: str) -> None:
    """Publish one complete daemon-owned lifecycle snapshot."""
    publisher.publish_phase(phase)


def _stamp_qdrant_identity(
    supervisor: QdrantSupervisor,
    publisher: _DiscoveryPublisher,
) -> None:
    """Authoritatively publish the ready child before model warming begins."""
    from pathlib import Path

    from ..config import get_config
    from ..qdrant_runtime._constants import QDRANT_SERVER_VERSION
    from ..qdrant_runtime._resolve import (
        probe_qdrant_endpoint,
        read_qdrant_identity,
        verify_attachable,
    )

    identity = read_qdrant_identity()
    child_pid = supervisor.pid or (identity.qdrant_pid if identity is not None else 0)
    if (
        identity is None
        or identity.qdrant_pid != child_pid
        or identity.http_port != supervisor.http_port
        or identity.qdrant_start_time <= 0.0
    ):
        raise RuntimeError(
            "supervised Qdrant became ready without a complete matching child identity"
        )
    cfg = get_config()
    probe = probe_qdrant_endpoint(supervisor.http_port)
    attachable, reason = verify_attachable(
        probe,
        identity,
        expected_port=supervisor.http_port,
        expected_version=QDRANT_SERVER_VERSION,
        expected_storage=str(Path(str(cfg.qdrant_storage_dir)).expanduser()),
    )
    if not attachable:
        raise RuntimeError(
            f"supervised Qdrant identity failed final publication validation: {reason}"
        )
    if _m._service_port <= 0:
        raise RuntimeError("service port is unavailable during Qdrant publication")
    publisher.publish_phase("warming")


def _stop_active_qdrant() -> bool:
    """Stop the process-owned supervisor and report confirmed convergence."""
    from .. import qdrant_runtime as _qr
    from ..config import EnvVar

    supervisor = _qr.active_supervisor()
    if supervisor is None:
        return True
    try:
        stopped = supervisor.stop()
    except Exception:
        log_event(
            logger,
            "service.lifecycle",
            "qdrant_stop_failed",
            severity=logging.WARNING,
            exc_info=True,
        )
        return False
    if not stopped:
        return False
    _qr.set_active_supervisor(None)
    os.environ.pop(EnvVar.QDRANT_URL.value, None)
    return True


def _reconcile_storage_manifest() -> None:
    """Reconcile the storage manifest against the live managed server.

    Enumerates the server's collections, derives each one's per-root prefix,
    and drops manifest entries whose root is gone and whose data is gone too.
    Runs on a worker thread off the GPU lock. Any failure is logged and
    swallowed: a stale-but-present manifest is a survey nuisance, never a
    reason to fail service startup.
    """
    import re

    from ..config import get_config
    from ..storage_manifest import reconcile_manifest

    prefix_re = re.compile(r"^(r[0-9a-f]{12}_)")
    try:
        from qdrant_client import QdrantClient

        cfg = get_config()
        url = str(cfg.qdrant_url or "") or f"http://127.0.0.1:{cfg.qdrant_port}"
        client = QdrantClient(url=url)
        try:
            names = [c.name for c in client.get_collections().collections]
        finally:
            client.close()
        known: set[str] = set()
        for name in names:
            match = prefix_re.match(name)
            if match:
                known.add(match.group(1))
        result = reconcile_manifest(known)
        if result.dropped:
            logger.info(
                "storage manifest reconcile dropped %d stale prefix(es): %s",
                len(result.dropped),
                ", ".join(result.dropped),
            )
    except Exception:
        logger.debug("storage manifest reconcile skipped", exc_info=True)


@asynccontextmanager
async def service_lifespan(_app: Starlette) -> AsyncGenerator[None]:
    """Eagerly load GPU models before accepting connections.

    Startup loads the shared ``EmbeddingModel`` with per-stage
    timing logs, registers daemon-owned shutdown hooks, and starts
    the heartbeat task.  Shutdown cancels the heartbeat, closes
    all project stores, releases GPU memory, removes both owner-published
    discovery views, and releases the retained machine lease last.

    Args:
        _app: The Starlette application instance (unused but
            required by the lifespan protocol).

    Yields:
        Control to the running application.
    """
    _m._start_time = time.monotonic()
    _m._shutdown_recorded = False
    # Generate the per-process identity token before the first
    # heartbeat tick fires (which would otherwise persist an empty
    # token into service.json). The token round-trips through
    # /health for CLI-side identity verification (gh #124/#125).
    _m._SERVICE_TOKEN = uuid.uuid4().hex

    # Machine singleton: claim the machine before committing GPU
    # memory or spawning Qdrant. This is the authoritative, race-safe gate (the
    # CLI pre-check is advisory; this acquire wins or loses atomically).
    machine_lease = _claim_machine_singleton()
    discovery = _DiscoveryPublisher(machine_lease)
    # Register the owner cleanup retry before the first discovery write or
    # subordinate startup action. A pre-yield failure can therefore retain the
    # lease after a transient cleanup failure and retry while still owner.
    _m._install_daemon_shutdown_hooks(discovery)

    # Lock held but not yet serving: stamp the sidecar so ``server status``
    # reports "warming" instead of a contradictory "stopped" while models load.
    from ..serviceclient._discovery import SERVICE_PHASE_RUNNING, SERVICE_PHASE_WARMING

    # Once the lock is held, every startup step up to ``yield`` runs under a
    # release-on-failure guard. The shipping daemon's crash-safe lock self-heals
    # via OS release on process exit, but a pre-yield startup failure (qdrant
    # spawn, model load) would otherwise leak the held lock for an in-process
    # lifespan REUSE path that never reaches the post-yield ``finally``. A
    # supported embedded-reuse contract requires the lock be freed the moment
    # startup fails, so a subsequent in-process acquire succeeds.
    periodic_tasks: list[asyncio.Task[None]] = []
    manager: JobManager | None = None
    cleanup_started = False
    startup_started = time.perf_counter()
    try:
        _stamp_service_phase(discovery, SERVICE_PHASE_WARMING)
        periodic_tasks = await _start_components(discovery)
        from .. import jobs as _jobs_module

        manager = _jobs_module.get_job_manager()
        try:
            await _start_job_manager(manager)
        except _CanonicalJobRestoreError:
            # ``abort_startup`` restored the untouched singleton to ``new``.
            # Do not pass it through normal shutdown, which would incorrectly
            # advance it to ``stopped`` and skip restore on in-process retry.
            manager = None
            raise
        logger.info(
            "Service startup complete in %.2fs",
            time.perf_counter() - startup_started,
        )
        _stamp_service_phase(discovery, SERVICE_PHASE_RUNNING)
        try:
            yield
        finally:
            cleanup_started = True
            await _shutdown_components(periodic_tasks, manager, discovery)
    except BaseException:
        # The post-yield ``finally`` releases the lock on a clean run; this
        # branch covers the pre-yield startup failure (and a cancelled startup)
        # where that ``finally`` was never entered. Stop any already-ready
        # supervised Qdrant before freeing the singleton: on POSIX the child is
        # in its own session, so process exit alone is not an ownership cleanup
        # guarantee. Release exactly once after the child is gone.
        if not cleanup_started:
            cleanup_started = True
            await _shutdown_components(periodic_tasks, manager, discovery)
        raise


async def _start_components(
    discovery: _DiscoveryPublisher,
) -> list[asyncio.Task[None]]:
    """Run the pre-yield startup: qdrant, models, hooks, periodic tasks.

    Factored out of :func:`service_lifespan` so the machine-lock
    release-on-failure guard wraps the whole startup body without nesting the
    ``yield`` inside a startup-only ``try``. Any failure here propagates to the
    caller, which releases the held machine lock before re-raising.

    Returns:
        The running periodic tasks (heartbeat, plus storage maintenance when
        scheduled), handed back so the post-yield shutdown can cancel and
        await them.
    """
    # HF cache status
    from ..config import EnvVar, get_config

    hf_home = os.environ.get(EnvVar.HF_HOME, "~/.cache/huggingface")
    logger.info("HF cache: %s", hf_home)

    # The package-level registry is intentionally stable across supported
    # in-process lifespan reuse. Reopen it only after its prior close_all()
    # completed and proved that no model, slot, or root lock remains.
    _m._registry.prepare_startup()

    # Qdrant server mode is the default backend: spawn the supervised
    # child BEFORE model load so a missing/broken binary fails startup
    # fast (no GPU memory committed yet) and the registry's stores open
    # server-mode from the first lease. Selection reads
    # ``effective_server_mode`` (``qdrant_server and not local_only``)
    # so the ``--local-only`` escape hatch deterministically selects the
    # on-disk store. An operator-set URL wins over spawning: it is the
    # remote-server escape hatch.
    from .. import qdrant_runtime as _qr

    cfg = get_config()
    if cfg.effective_server_mode():
        if str(cfg.qdrant_url or ""):
            logger.info(
                "qdrant server mode requested but %s is set; using remote %s",
                EnvVar.QDRANT_URL.value,
                cfg.qdrant_url,
            )
        else:
            t_q = time.perf_counter()
            try:
                supervisor = await _run_in_thread(_qr.start_supervised_from_config)
            except Exception as exc:
                # Server mode is the default, so a startup failure here
                # is the default-path failure. Per the server-first
                # failure contract it must be loud and actionable, never
                # a silent fall-through to the local store: abort startup
                # with a message naming the cause, the install command,
                # and the --local-only escape hatch. No GPU memory has
                # been committed yet.
                log_event(
                    logger,
                    "service.lifecycle",
                    "qdrant_start_failed",
                    severity=logging.ERROR,
                    exc_info=True,
                )
                raise RuntimeError(
                    "qdrant server mode (the default backend) failed to "
                    f"start: {exc}\n"
                    "Provision the server binary with: "
                    "vaultspec-rag server qdrant install\n"
                    "Or run the service in local-only mode (on-disk store, "
                    "no server) with: vaultspec-rag server start --local-only"
                ) from exc
            # Publish the in-process URL through the env so every
            # config read (registry stores, watcher reindexes) sees
            # server mode for the daemon's lifetime.
            os.environ[EnvVar.QDRANT_URL.value] = supervisor.url
            _stamp_qdrant_identity(supervisor, discovery)
            logger.info(
                "qdrant server ready in %.2fs at %s (pid %s)",
                time.perf_counter() - t_q,
                supervisor.url,
                supervisor.pid,
            )

    # Reconcile the storage manifest against the live server before models
    # load: drop bookkeeping for roots that are gone AND whose collections no
    # longer exist, so the survey/prune surface starts from an accurate
    # prefix-to-root map after an out-of-band root removal or rename. Pure
    # storage IO on a worker thread, never under the GPU lock; a failure here
    # is logged and never aborts startup (attribution is best-effort).
    if cfg.effective_server_mode():
        await _run_in_thread(_reconcile_storage_manifest)

    # Wire watcher lifecycle into registry so close_project() stops watchers
    _m._registry._on_close_project = _m._stop_watcher  # pyright: ignore[reportPrivateUsage]

    # Load models (raises RuntimeError if no CUDA via _check_rag_deps)
    t0 = time.perf_counter()
    await _run_in_thread(_m._registry.load_model)
    if bool(get_config().reranker_enabled):
        await _run_in_thread(_m._registry.get_reranker)
    logger.info("All models loaded in %.2fs", time.perf_counter() - t0)

    _m._lifecycle_log("startup", pid=os.getpid())

    # Surface jobs a dead prior daemon left running: without this, a
    # killed daemon silently erased every in-flight job from the
    # in-memory registry and operators had no record the work died.
    from .. import jobs as _jobs_module

    interrupted = await _run_in_thread(_jobs_module.restore_interrupted)
    if interrupted:
        logger.warning(
            "restored %d job(s) from a prior daemon life as interrupted",
            interrupted,
        )

    heartbeat_task = asyncio.create_task(_m._heartbeat_loop(discovery))
    # First heartbeat right away so a freshly started service is
    # immediately distinguishable from a stale CLI-only write.
    try:
        await asyncio.to_thread(_m._heartbeat_tick_sync, discovery)
    except Exception:
        log_event(
            logger,
            "service.lifecycle",
            "heartbeat_initial_failed",
            severity=logging.WARNING,
            exc_info=True,
        )

    # Scheduled storage maintenance: server-mode only and knob-gated at
    # task creation (the tick re-checks both cheaply, so a config flip is
    # honoured without a restart either way). The loop itself delays one
    # full interval before the first cycle - a fresh daemon serves before
    # it sweeps.
    tasks = [heartbeat_task]
    if get_config().effective_server_mode() and bool(get_config().storage_autoprune):
        tasks.append(asyncio.create_task(_m._maintenance_loop()))
    # Survey snapshot warmer: server-mode only, but deliberately NOT gated on
    # the autoprune knob - the /storage/survey route serves from the snapshot
    # regardless of whether scheduled reclamation is enabled. One-shot and
    # read-only; a failure leaves the route on its fresh-compute fallback.
    if get_config().effective_server_mode():
        tasks.append(asyncio.create_task(_m._survey_warmup_task()))

    return tasks


async def _start_job_manager(manager: JobManager) -> None:
    """Restore, rebind, and dispatch the one canonical service job manager."""
    from .. import jobs as _jobs_module
    from ..job_models import JobOutcomeStatus, JobState

    restore_required = manager.prepare_startup()
    if restore_required:
        outcome = await _run_in_thread(manager.restore_persisted)
        if outcome.status is JobOutcomeStatus.ERROR:
            detail = (
                f"canonical job state restore failed ({outcome.code}): "
                f"{outcome.message}"
            )
            if manager.abort_startup():
                raise _CanonicalJobRestoreError(detail)
            # A post-publication persistence error can retain the restored
            # generation in memory. Mark it complete so bounded shutdown can
            # flush it and a clean in-process retry rebinds rather than trying
            # to restore into a nonempty singleton.
            manager.complete_startup()
            raise RuntimeError(
                f"{detail}; retained restored state requires bounded cleanup"
            )
    manager.complete_startup()
    bound, dispatched = _jobs_module.restore_managed_jobs(registry=_m._registry)
    interrupted = sum(
        snapshot.state is JobState.INTERRUPTED for snapshot in manager.terminal()
    )
    logger.info(
        "Canonical job manager ready: bound=%d dispatched=%d interrupted=%d",
        bound,
        dispatched,
        interrupted,
    )


async def _drain_managed_work(
    manager: JobManager | None,
    requested: tuple[str, ...],
    initial_reasons: list[str],
    *,
    watcher_stop_ok: bool,
) -> tuple[bool, bool, tuple[str, ...], str]:
    """Boundedly join watcher and manager ownership after intake stops."""
    from ..config import get_config

    timeout = float(get_config().job_shutdown_timeout_seconds)
    watcher_result, raw_manager_result = await _await_shutdown_results(
        manager,
        requested,
        timeout=timeout,
    )
    watchers_released, reasons = _watcher_shutdown_status(
        watcher_result,
        stop_ok=watcher_stop_ok,
        timeout=timeout,
    )
    reasons[:0] = initial_reasons
    manager_resources_released, manager_result, manager_reasons = (
        _manager_shutdown_status(manager, requested, raw_manager_result)
    )
    reasons.extend(manager_reasons)
    survivors = (
        manager_result.surviving_job_ids if manager_result is not None else requested
    )
    resources_released = watchers_released and manager_resources_released
    return resources_released, not reasons, survivors, "; ".join(reasons)


async def _await_shutdown_results(
    manager: JobManager | None,
    requested: tuple[str, ...],
    *,
    timeout: float,
) -> tuple[bool | BaseException, JobShutdownResult | BaseException | None]:
    """Await watcher and manager drains concurrently under one time bound."""
    watcher_wait = asyncio.create_task(
        _m._wait_for_watcher_cleanup(timeout_seconds=timeout),
        name="vaultspec-watcher-shutdown-wait",
    )
    if manager is not None:
        manager_wait = asyncio.create_task(
            manager.wait_for_shutdown(requested, timeout_seconds=timeout),
            name="vaultspec-job-manager-shutdown-wait",
        )
        watcher_result, raw_manager_result = await asyncio.gather(
            watcher_wait,
            manager_wait,
            return_exceptions=True,
        )
        return watcher_result, raw_manager_result
    watcher_results = await asyncio.gather(watcher_wait, return_exceptions=True)
    return watcher_results[0], None


def _watcher_shutdown_status(
    result: bool | BaseException,
    *,
    stop_ok: bool,
    timeout: float,
) -> tuple[bool, list[str]]:
    """Classify watcher cleanup separately from intake-stop errors."""
    reasons: list[str] = []
    released = stop_ok and result is True
    if isinstance(result, BaseException):
        reasons.append(f"watcher cleanup failed: {result}")
    elif result is not True:
        reasons.append(f"watcher cleanup exceeded {timeout:g} seconds")
    return released, reasons


def _manager_shutdown_status(
    manager: JobManager | None,
    requested: tuple[str, ...],
    result: JobShutdownResult | BaseException | None,
) -> tuple[bool, JobShutdownResult | None, list[str]]:
    """Classify manager ownership and close its service-life state."""
    if manager is None:
        return True, None, []
    manager_result: JobShutdownResult | None = None
    reasons: list[str] = []
    resources_released = False
    if isinstance(result, BaseException):
        reasons.append(f"manager drain failed: {result}")
    elif result is None:
        reasons.append(
            "manager drain returned no result for requested jobs " + ",".join(requested)
        )
    else:
        manager_result = result
        resources_released = result.resources_released
        if not resources_released:
            reasons.append("manager workers or resource owners survived")
        if not result.persistence_ok:
            reasons.append(
                f"manager shutdown state was not durable ({result.persistence_code})"
            )
    try:
        manager.complete_shutdown(resources_released=resources_released)
    except BaseException as exc:
        resources_released = False
        reasons.append(f"manager shutdown completion failed: {exc}")
    return resources_released, manager_result, reasons


def _begin_managed_shutdown(
    manager: JobManager | None,
) -> tuple[tuple[str, ...], list[str], bool]:
    """Synchronously stop manager dispatch and watcher intake first."""
    requested: tuple[str, ...] = ()
    reasons: list[str] = []
    watcher_stop_ok = True
    if manager is not None:
        try:
            requested = manager.begin_shutdown()
        except BaseException as exc:
            reasons.append(f"manager shutdown signal failed: {exc}")
    try:
        _m._stop_all_watchers()
    except BaseException as exc:
        watcher_stop_ok = False
        reasons.append(f"watcher stop failed: {exc}")
    return requested, reasons, watcher_stop_ok


async def _shutdown_components(
    tasks: list[asyncio.Task[None]],
    manager: JobManager | None,
    discovery: _DiscoveryPublisher,
) -> None:
    """Tear down the daemon's data components and release the machine lock.

    Mirrors :func:`_start_components`: stops dispatch and watcher intake,
    cancels periodic tasks (heartbeat and, when scheduled, storage maintenance),
    drains execution owners before stores and stores before the qdrant child,
    then releases the machine singleton last.
    """
    # Mark publication stopped before cancelling the asyncio task. A cancelled
    # ``to_thread`` await does not stop its worker thread; the publisher's
    # synchronous guard joins an in-flight tick and makes every later one inert.
    discovery.quiesce()
    requested, initial_reasons, watcher_stop_ok = _begin_managed_shutdown(manager)
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    # Both views are removed while the owner lease remains held. This is
    # idempotent and happens before any early unclean-shutdown return.
    discovery_clean = discovery.cleanup()
    resources_released, clean, survivors, reason = await _drain_managed_work(
        manager,
        requested,
        initial_reasons,
        watcher_stop_ok=watcher_stop_ok,
    )
    if not resources_released:
        log_event(
            logger,
            "service.lifecycle",
            "shutdown_unclean",
            severity=logging.ERROR,
            reason=reason,
            surviving_job_ids=survivors,
        )
        _m._record_shutdown(
            "unclean",
            detail=reason,
            surviving_job_ids=",".join(survivors),
        )
        return

    # Shutdown ordering: released watchers and manager workers BEFORE stores,
    # stores BEFORE the qdrant child, and the machine singleton last.
    try:
        _m._registry.close_all()
    except BaseException as exc:
        # Preserve the primary store teardown failure, but still make one real
        # attempt to stop Qdrant. Ownership remains held whichever stop result
        # follows, so no successor can overlap surviving store authority.
        _stop_active_qdrant()
        _m._record_shutdown("unclean", detail=f"component teardown failed: {exc}")
        raise
    qdrant_clean = _stop_active_qdrant()
    if not qdrant_clean:
        qdrant_reason = "managed Qdrant shutdown did not converge"
        log_event(
            logger,
            "service.lifecycle",
            "shutdown_unclean",
            severity=logging.ERROR,
            reason=qdrant_reason,
            surviving_job_ids=survivors,
        )
        _m._record_shutdown(
            "unclean",
            detail=qdrant_reason,
            surviving_job_ids=",".join(survivors),
        )
        return
    # Release the machine singleton last, so the slot is free for the next
    # service only after stores, GPU, and Qdrant are fully torn down and both
    # owner-published discovery views are confirmed absent. Any teardown or
    # discovery failure retains the lease for the registered atexit retry.
    if discovery_clean:
        release_machine_lock_lease(discovery.lease)
    if not discovery_clean:
        discovery_reason = "owner discovery cleanup did not converge"
        combined_reason = "; ".join(part for part in (reason, discovery_reason) if part)
        log_event(
            logger,
            "service.lifecycle",
            "shutdown_unclean",
            severity=logging.ERROR,
            reason=combined_reason,
            surviving_job_ids=survivors,
        )
        _m._record_shutdown(
            "unclean",
            detail=combined_reason,
            surviving_job_ids=",".join(survivors),
        )
        return
    if clean:
        logger.info("Service shutdown complete")
        _m._record_shutdown("clean")
    else:
        log_event(
            logger,
            "service.lifecycle",
            "shutdown_unclean",
            severity=logging.ERROR,
            reason=reason,
            surviving_job_ids=survivors,
        )
        _m._record_shutdown(
            "unclean",
            detail=reason,
            surviving_job_ids=",".join(survivors),
        )


def _service_health_status(
    reg_health: ServiceHealth,
    qdrant_state: QdrantRuntimeState,
) -> tuple[str, list[str]]:
    """Resolve service readiness and its infrastructure degradation reasons."""
    if reg_health["model_loaded"]:
        status = "ready"
    elif _m._start_time > 0:
        status = "degraded"
    else:
        status = "error"
    degraded_reasons: list[str] = []
    if not reg_health["model_loaded"]:
        degraded_reasons.append("embedding models are not loaded")
    if qdrant_state.mode == "server" and not qdrant_state.alive:
        degraded_reasons.append("the configured vector service is not live")
        if status == "ready":
            status = "degraded"
    return status, degraded_reasons


def _health_job_records() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Merge canonical jobs with legacy-only records without duplicating IDs."""
    from .. import jobs as _jobs_registry

    canonical_records = [
        snapshot.to_dict() for snapshot in _jobs_registry.get_job_manager().list_jobs()
    ]
    canonical_ids = {str(record.get("id", "")) for record in canonical_records}
    legacy_only = [
        record
        for record in _jobs_registry.snapshot()
        if str(record.get("id", "")) not in canonical_ids
    ]
    return canonical_records, [*canonical_records, *legacy_only]


def _latest_job_record(
    records: list[dict[str, object]],
) -> dict[str, object] | None:
    """Return the most recently updated record from a possibly empty list."""
    if not records:
        return None
    from ._routes_jobs import job_updated_timestamp

    return max(
        records,
        key=lambda record: job_updated_timestamp(record) or float("-inf"),
    )


def _failed_job_health(record: dict[str, object] | None) -> dict[str, object] | None:
    """Project the bounded latest-failure health shape."""
    if record is None:
        return None
    return {
        "id": record.get("id"),
        "error_kind": record.get("error_kind"),
        "finished_at": record.get("finished_at"),
    }


def _resilience_job_health(
    record: dict[str, object] | None,
) -> dict[str, object] | None:
    """Project the bounded latest-resilience health shape."""
    if record is None:
        return None
    return {
        "job_id": record.get("id"),
        "source": cast("dict[str, object]", record["spec"]).get("source"),
        **cast("dict[str, object]", record["resilience"]),
    }


def _jobs_health() -> tuple[dict[str, object], list[str]]:
    """Build the bounded job rollup and its service degradation reasons."""
    from ._routes_jobs import _job_summary, job_state

    canonical_records, job_records = _health_job_records()
    summary = _job_summary(job_records, now=time.time())
    last_failed = _latest_job_record(
        [record for record in job_records if job_state(record) == "failed"]
    )
    latest_resilience = _latest_job_record(
        [
            record
            for record in canonical_records
            if isinstance(record.get("resilience"), dict)
        ]
    )
    jobs_health: dict[str, object] = {
        "running": summary["running"],
        "queued": summary["queued"],
        "paused": summary["paused"],
        "transitional": summary["transitional"],
        "active": summary["active"],
        "stalled": summary["stalled"],
        "control_pending": summary["control_pending"],
        "states": summary["states"],
        "last_failed": _failed_job_health(last_failed),
        "resilience": _resilience_job_health(latest_resilience),
    }
    degraded_reasons: list[str] = []
    if summary["stalled"]:
        degraded_reasons.append(f"{summary['stalled']} indexing job(s) are stalled")
    if last_failed is not None:
        failed_kind = last_failed.get("error_kind") or "unknown"
        degraded_reasons.append(f"the latest indexing job failed: {failed_kind}")
    return jobs_health, degraded_reasons


async def health_handler(_request: Request) -> object:
    """Return service health as JSON.

    Args:
        _request: The incoming Starlette request.

    Returns:
        A ``JSONResponse`` with status, CUDA availability,
        model state, connected projects, and uptime.
    """
    from starlette.responses import JSONResponse

    from .. import store_schema

    reg_health = _m._registry.health()
    uptime = time.monotonic() - _m._start_time if _m._start_time > 0 else 0.0
    from .. import qdrant_runtime as _qr

    qdrant_state = _qr.runtime_state()
    status, degraded_reasons = _service_health_status(reg_health, qdrant_state)
    jobs_health, jobs_degraded_reasons = _jobs_health()
    degraded_reasons.extend(jobs_degraded_reasons)

    from ..jobs import active_index_support_profiles

    if status == "ready" and degraded_reasons:
        status = "degraded"

    return JSONResponse(
        {
            "status": status,
            "jobs": jobs_health,
            "qdrant": qdrant_state.to_dict(),
            "pid": os.getpid(),
            "parent_pid": os.getppid(),
            "executable": sys.executable,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
            "virtual_env": os.environ.get("VIRTUAL_ENV"),
            "cuda": reg_health["cuda"],
            "models_loaded": reg_health["model_loaded"],
            "reranker_loaded": reg_health["reranker_loaded"],
            "project_count": reg_health["project_count"],
            "uptime_s": round(uptime, 2),
            "backend_capabilities": backend_capabilities_dict(),
            "degraded_reasons": degraded_reasons,
            "support_profile": active_index_support_profiles(),
            # Bare storage-schema version: the cheapest ungated pre-read gate a
            # direct-Qdrant consumer can check before scrolling. The full
            # descriptor lives on /readiness.
            "schema_version": store_schema.STORAGE_SCHEMA_VERSION,
            # Per-process identity token. Mirrors the value written
            # to service.json. The CLI compares the two to detect
            # PID-reuse and unrelated-HTTP-server-on-port collisions
            # (gh #124, #125).
            "service_token": _m._SERVICE_TOKEN,
        },
    )
