"""Daemon lifecycle helpers: log paths, heartbeat, and shutdown hooks.

Split out of the original ``mcp_server.py`` monolith per the
``2026-06-01-module-split-adr``. ``_heartbeat_tick_sync`` reads the
rebindable ``_status_file_path`` and ``_SERVICE_TOKEN`` through the
package alias so test monkeypatches on ``vaultspec_rag.mcp_server`` are
observed.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import vaultspec_rag.mcp_server as _m

from ._state import _HEARTBEAT_INTERVAL_SECONDS

logger = logging.getLogger("vaultspec_rag.mcp_server")


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
    """Emit a structured lifecycle entry at WARNING level.

    WARNING (not INFO) because ``VAULTSPEC_RAG_LOG_LEVEL`` defaults to
    WARNING, so INFO lines are silent by default. Operators see the
    lifecycle without opt-in.

    Args:
        event: Short identifier (``startup`` / ``shutdown``).
        **kv: Extra key=value fields rendered space-separated for
            greppability.
    """
    parts = [f"event={event}"]
    parts.extend(f"{k}={v}" for k, v in kv.items())
    logger.warning("service.lifecycle %s", " ".join(parts))


def _unlink_status_file_silently() -> None:
    """Best-effort unlink of service.json; ignores missing/locked.

    Called from atexit, signal handlers, and the lifespan finally
    block. Idempotent because any of those code paths may have
    already removed the file.
    """
    path = _m._status_file_path()
    try:
        path.unlink()
    except FileNotFoundError as exc:
        # Already-removed is the expected idempotent case.
        logger.debug("service.json already gone at %s: %s", path, exc)
    except OSError as exc:
        logger.warning(
            "service.lifecycle event=cleanup_failed path=%s error=%s",
            path,
            exc,
        )


def _heartbeat_tick_sync() -> None:
    """Synchronous heartbeat write - atomic via .tmp + os.replace.

    Reads the current service.json, merges ``last_heartbeat`` (ISO-8601
    UTC, second resolution), writes through a tmp file. Called from
    inside ``asyncio.to_thread`` so file I/O does not block the event
    loop.

    Exits silently when service.json is missing (the CLI parent may
    have unlinked it during ``server service stop`` - the heartbeat
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
    data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
    # Per-process identity token. Empty during the narrow window
    # between module import and service_lifespan startup; the guard
    # prevents an in-flight zero-value overwrite of a token written
    # by a previous daemon process that crashed without unlinking
    # service.json.
    if _m._SERVICE_TOKEN:
        data["service_token"] = _m._SERVICE_TOKEN
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(str(tmp), str(path))


async def _heartbeat_loop() -> None:
    """Periodic heartbeat task; cancelled in the lifespan finally.

    Sleeps ``_HEARTBEAT_INTERVAL_SECONDS`` between ticks. Tolerates
    transient write failures so an I/O blip never crashes the
    service; the next tick retries.
    """
    while True:
        try:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            await asyncio.to_thread(_m._heartbeat_tick_sync)
        except asyncio.CancelledError:
            return
        except Exception:  # heartbeat must never crash the service
            logger.warning(
                "service.lifecycle event=heartbeat_failed",
                exc_info=True,
            )


def _record_shutdown(reason: str, **kv: object) -> None:
    """Log + unlink once; subsequent calls are no-ops.

    atexit, the signal handler, and the lifespan finally block may
    all fire in sequence. The first one wins. The guard
    (``_shutdown_recorded``) is read and written on the package
    namespace so a test rebind of ``mcp_server._shutdown_recorded`` is
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
