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

from ..capabilities import backend_capabilities_dict
from ..logging_config import log_event

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.applications import Starlette
    from starlette.requests import Request

logger = logging.getLogger("vaultspec_rag.server")


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
            logger.info(
                "qdrant server ready in %.2fs at %s (pid %s)",
                time.perf_counter() - t_q,
                supervisor.url,
                supervisor.pid,
            )

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

    try:
        yield
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await heartbeat_task
        # Shutdown ordering: watchers BEFORE stores (so no
        # incremental_index() runs against a closed store), stores
        # BEFORE the qdrant child (so clients release their server
        # connections), the qdrant child LAST among data components.
        _m._stop_all_watchers()
        _m._registry.close_all()
        supervisor = _qr.active_supervisor()
        if supervisor is not None:
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
            _qr.set_active_supervisor(None)
            # Undo the in-process env publish so an embedded caller
            # that runs the lifespan and then continues in the same
            # interpreter does not keep reading server mode against a
            # now-dead port (the daemon process just exits, so this
            # only matters for in-process reuse).
            os.environ.pop(EnvVar.QDRANT_URL.value, None)
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

    return JSONResponse(
        {
            "status": status,
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
            # Per-process identity token. Mirrors the value written
            # to service.json. The CLI compares the two to detect
            # PID-reuse and unrelated-HTTP-server-on-port collisions
            # (gh #124, #125).
            "service_token": _m._SERVICE_TOKEN,
        },
    )
