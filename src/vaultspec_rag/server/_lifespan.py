"""Service lifespan and the raw ``/health`` endpoint.

Split out of the original ``server.py`` monolith per the
``2026-06-01-module-split-adr``. ``service_lifespan`` reassigns the
process-wide ``_start_time`` / ``_SERVICE_TOKEN`` on the package
namespace so ``health_handler`` (and tests that rebind ``_registry`` /
``_start_time``) observe the live values through the package alias.
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
from typing import TYPE_CHECKING

from anyio.to_thread import run_sync as _run_in_thread

import vaultspec_rag.server as _m

from .._machine_lock import acquire_machine_lock, release_machine_lock
from ..capabilities import backend_capabilities_dict
from ..logging_config import log_event

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.applications import Starlette
    from starlette.requests import Request

    from ..qdrant_runtime import QdrantSupervisor

logger = logging.getLogger("vaultspec_rag.server")


def _claim_machine_singleton() -> None:
    """Acquire the machine singleton lock or abort startup with a clear cause.

    A live holder means another resident service already owns this machine's
    single GPU and single-writer Qdrant storage; a stale lock from a dead holder
    is reclaimed by the acquire itself.
    """
    acquired, holder = acquire_machine_lock()
    if not acquired:
        raise RuntimeError(
            f"another vaultspec-rag service (pid {holder}) already owns this "
            "machine; one resident service owns the GPU and the managed Qdrant. "
            "Stop it first, or run on a dedicated machine."
        )


def _stamp_service_phase(phase: str) -> None:
    """Publish the daemon lifecycle phase through the shared atomic merge."""
    from ..serviceclient._discovery import (
        SERVICE_DISCOVERY_SCHEMA,
        SERVICE_DISCOVERY_VERSION,
        _discovery_timestamp,
        _merge_service_status,
    )

    fields: dict[str, object] = {
        "schema": SERVICE_DISCOVERY_SCHEMA,
        "version": SERVICE_DISCOVERY_VERSION,
        "pid": os.getpid(),
        "phase": phase,
    }
    if _m._launch_token:
        fields["launch_token"] = _m._launch_token
    if _m._service_port > 0:
        fields["port"] = _m._service_port
        fields["started_at"] = _discovery_timestamp()
    _merge_service_status(fields)


def _stamp_qdrant_identity(supervisor: QdrantSupervisor) -> None:
    """Authoritatively publish the ready child before model warming begins."""
    from ..config import get_config
    from ..qdrant_runtime._constants import QDRANT_SERVER_VERSION
    from ..qdrant_runtime._resolve import (
        probe_qdrant_endpoint,
        read_qdrant_identity,
        verify_attachable,
    )
    from ..serviceclient._discovery import (
        SERVICE_DISCOVERY_SCHEMA,
        SERVICE_DISCOVERY_VERSION,
        _discovery_timestamp,
        _merge_service_status,
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
        expected_storage=str(cfg.qdrant_storage_dir),
    )
    if not attachable:
        raise RuntimeError(
            f"supervised Qdrant identity failed final publication validation: {reason}"
        )
    if _m._service_port <= 0:
        raise RuntimeError("service port is unavailable during Qdrant publication")
    qdrant_identity = {
        "pid": identity.qdrant_pid,
        "start_time": identity.qdrant_start_time,
        "port": identity.http_port,
        "version": identity.version,
        "storage_path": identity.storage_path,
    }
    _merge_service_status(
        {
            "schema": SERVICE_DISCOVERY_SCHEMA,
            "version": SERVICE_DISCOVERY_VERSION,
            "pid": os.getpid(),
            "port": _m._service_port,
            "started_at": _discovery_timestamp(),
            "phase": "warming",
            "launch_token": _m._launch_token,
            "qdrant_pid": child_pid,
            "qdrant_alive": supervisor.is_alive(),
            "qdrant_port": identity.http_port,
            "qdrant_version": identity.version,
            "qdrant_start_time": identity.qdrant_start_time,
            "qdrant_identity": qdrant_identity,
        }
    )


def _stop_active_qdrant() -> None:
    """Stop and clear any process-owned supervisor, including failed startup."""
    from .. import qdrant_runtime as _qr
    from ..config import EnvVar

    supervisor = _qr.active_supervisor()
    if supervisor is None:
        return
    try:
        supervisor.stop()
    except Exception:
        log_event(
            logger,
            "service.lifecycle",
            "qdrant_stop_failed",
            severity=logging.WARNING,
            exc_info=True,
        )
    finally:
        _qr.set_active_supervisor(None)
        os.environ.pop(EnvVar.QDRANT_URL.value, None)


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
    all project stores, releases GPU memory, and unlinks
    ``service.json``.

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

    # Machine singleton (ADR D1 / P3): claim the machine before committing GPU
    # memory or spawning Qdrant. This is the authoritative, race-safe gate (the
    # CLI pre-check is advisory; this acquire wins or loses atomically).
    _claim_machine_singleton()

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
    cleanup_started = False
    try:
        _stamp_service_phase(SERVICE_PHASE_WARMING)
        periodic_tasks = await _start_components()
        _stamp_service_phase(SERVICE_PHASE_RUNNING)
        try:
            yield
        finally:
            cleanup_started = True
            await _shutdown_components(periodic_tasks)
    except BaseException:
        # The post-yield ``finally`` releases the lock on a clean run; this
        # branch covers the pre-yield startup failure (and a cancelled startup)
        # where that ``finally`` was never entered. Stop any already-ready
        # supervised Qdrant before freeing the singleton: on POSIX the child is
        # in its own session, so process exit alone is not an ownership cleanup
        # guarantee. Release exactly once after the child is gone.
        if not cleanup_started:
            cleanup_started = True
            await _shutdown_components(periodic_tasks)
        raise


async def _start_components() -> list[asyncio.Task[None]]:
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
    t_total = time.perf_counter()

    # HF cache status
    from ..config import EnvVar, get_config

    hf_home = os.environ.get(EnvVar.HF_HOME, "~/.cache/huggingface")
    logger.info("HF cache: %s", hf_home)

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
            _stamp_qdrant_identity(supervisor)
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

    logger.info("Service startup complete in %.2fs", time.perf_counter() - t_total)

    # Daemon now owns end-of-life cleanup. The CLI parent created
    # service.json; the daemon's hooks remove it on exit so a stale
    # file never misleads ``service status``.
    _m._install_daemon_shutdown_hooks()
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

    heartbeat_task = asyncio.create_task(_m._heartbeat_loop())
    # First heartbeat right away so a freshly started service is
    # immediately distinguishable from a stale CLI-only write.
    try:
        await asyncio.to_thread(_m._heartbeat_tick_sync)
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


async def _shutdown_components(tasks: list[asyncio.Task[None]]) -> None:
    """Tear down the daemon's data components and release the machine lock.

    Mirrors :func:`_start_components`: cancels the periodic tasks (heartbeat
    and, when scheduled, storage maintenance), stops watchers before stores
    and stores before the qdrant child, then releases the machine singleton
    last so the slot is free for the next service only after this one has
    fully torn down its GPU and Qdrant.
    """
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    # Shutdown ordering: watchers BEFORE stores (so no
    # incremental_index() runs against a closed store), stores
    # BEFORE the qdrant child (so clients release their server
    # connections), the qdrant child LAST among data components.
    try:
        _m._stop_all_watchers()
        _m._registry.close_all()
    finally:
        _stop_active_qdrant()
        # Release the machine singleton last, so the slot is free for the next
        # service only after this one has fully torn down its GPU and Qdrant.
        release_machine_lock()
    logger.info("Service shutdown complete")
    _m._record_shutdown("clean")


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

    try:
        import torch

        cuda = torch.cuda.is_available()
    except ImportError as exc:
        logger.debug("torch unavailable for /health: %s", exc)
        cuda = False

    reg_health = _m._registry.health()
    uptime = time.monotonic() - _m._start_time if _m._start_time > 0 else 0.0

    if reg_health["model_loaded"]:
        status = "ready"
    elif _m._start_time > 0:
        status = "degraded"
    else:
        status = "error"

    # A supervised qdrant child that has died (and exhausted its
    # bounded restart) degrades the whole service: searches against
    # server-mode stores will fail until it returns.
    from .. import qdrant_runtime as _qr

    qdrant_state = _qr.runtime_state()
    if status == "ready" and qdrant_state.mode == "server" and not qdrant_state.alive:
        status = "degraded"

    # Bounded jobs-health rollup: running/stalled counts and the
    # most recent failure's classification, so a broker probing /health
    # sees a wedged or failing index without walking /jobs.
    from .. import jobs as _jobs_registry
    from ._routes_jobs import _job_stalled

    now = time.time()
    job_records = _jobs_registry.snapshot()
    running_jobs = sum(1 for r in job_records if r.get("phase") == "running")
    stalled_jobs = sum(1 for r in job_records if _job_stalled(r, now))
    last_failed = next(
        (r for r in job_records if str(r.get("phase", "")) in ("error", "failed")),
        None,
    )
    jobs_health: dict[str, object] = {
        "running": running_jobs,
        "stalled": stalled_jobs,
        "last_failed": (
            {
                "id": last_failed.get("id"),
                "error_kind": last_failed.get("error_kind"),
                "finished_at": last_failed.get("finished_at"),
            }
            if last_failed is not None
            else None
        ),
    }

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
            "cuda": cuda,
            "models_loaded": reg_health["model_loaded"],
            "reranker_loaded": reg_health["reranker_loaded"],
            "project_count": reg_health["project_count"],
            "uptime_s": round(uptime, 2),
            "backend_capabilities": backend_capabilities_dict(),
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
