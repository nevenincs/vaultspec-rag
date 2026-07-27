"""Project-registry and per-root watcher administration routes.

Both concerns act directly on the resident multi-tenant registry's process
globals - ``_m._registry`` for project listing/eviction, ``_m._watcher_*``
and ``_m._ensure_watcher``/``_m._stop_watcher`` for the automatic-update
watcher - so they are grouped here rather than split across two
single-purpose modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

import vaultspec_rag.server as _m

from ._auth import require_token

if TYPE_CHECKING:
    from starlette.requests import Request

__all__ = [
    "evict_project_route",
    "get_watcher_state_route",
    "list_projects_route",
    "reconfigure_watcher_route",
    "start_watcher_route",
    "stop_watcher_route",
]


async def list_projects_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    projects = _m._registry.snapshot()
    for p in projects:
        p["root"] = str(p["root"])
    return JSONResponse(
        {
            "projects": projects,
            "max_projects": _m._registry.max_projects,
            "idle_ttl_seconds": _m._registry.idle_ttl_seconds,
        }
    )


async def evict_project_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    payload = await request.json()
    root = payload.get("root")
    from pathlib import Path

    target = Path(root).resolve()
    evicted, reason = _m._registry.try_evict(target)
    return JSONResponse({"root": str(target), "evicted": evicted, "reason": reason})


async def get_watcher_state_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    project_root = request.query_params.get("project_root")
    from ..config import get_config

    cfg = get_config()
    with _m._watcher_lock:
        roots = [str(p) for p in _m._watcher_tasks]

    state = {
        "watch_enabled": bool(cfg.watch_enabled),
        "debounce_ms": int(cfg.watch_debounce_ms),
        "cooldown_s": float(cfg.watch_cooldown_s),
        "watching": sorted(roots),
    }

    if project_root is not None:
        from pathlib import Path

        state["running"] = str(Path(project_root).resolve()) in roots

    return JSONResponse(state)


async def start_watcher_route(request: Request) -> JSONResponse:
    """Start automatic updates for one root and report the state achieved.

    ``started`` answers only "is a watcher watching this root now". When
    another owner still holds the root - a draining stop, an in-flight warm -
    the start is recorded and ``status`` names that owner instead, so a caller
    is never told updates are back on while they are still off.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    payload = await request.json()
    root = payload.get("root")
    from pathlib import Path

    from ..config import get_config

    cfg = get_config()
    target = Path(root).resolve()
    outcome = _m._ensure_watcher(target)
    return JSONResponse(
        {
            "root": str(target),
            "started": outcome.running,
            "status": outcome.value,
            "watch_enabled": bool(cfg.watch_enabled),
        }
    )


async def stop_watcher_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    payload = await request.json()
    root = payload.get("root")
    from pathlib import Path

    target = Path(root).resolve()
    with _m._watcher_lock:
        was_running = target in _m._watcher_tasks
    _m._stop_watcher(target)
    return JSONResponse({"root": str(target), "stopped": was_running})


async def reconfigure_watcher_route(request: Request) -> JSONResponse:
    """Restart one root's watcher with new timing and report the state achieved.

    The stop that precedes the restart leaves the old generation draining, so
    ``restarted`` reports whether a watcher carrying the new timing is running
    on return, and ``status`` names the owner still holding the root when it
    is not.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    payload = await request.json()
    root = payload.get("root")
    debounce_ms = payload.get("debounce_ms")
    cooldown_s = payload.get("cooldown_s")
    from pathlib import Path

    from ..config import get_config

    cfg = get_config()
    target = Path(root).resolve()
    _m._stop_watcher(target)
    outcome = _m._ensure_watcher(target, debounce_ms=debounce_ms, cooldown_s=cooldown_s)

    db_ms = int(debounce_ms) if debounce_ms is not None else int(cfg.watch_debounce_ms)
    db_cs = float(cooldown_s) if cooldown_s is not None else float(cfg.watch_cooldown_s)
    return JSONResponse(
        {
            "root": str(target),
            "restarted": outcome.running,
            "status": outcome.value,
            "debounce_ms": db_ms,
            "cooldown_s": db_cs,
        }
    )
