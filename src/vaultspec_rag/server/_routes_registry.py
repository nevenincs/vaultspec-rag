"""Project-registry and per-root watcher administration routes.

Both concerns act directly on the resident multi-tenant registry and watcher
state - the request runtime owns project listing/eviction, while ``_m._watcher_*``
and ``_m._ensure_watcher``/``_m._stop_watcher`` for the automatic-update
watcher - so they are grouped here rather than split across two
single-purpose modules.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, cast

from anyio.to_thread import run_sync
from starlette.responses import JSONResponse

import vaultspec_rag.server as _m

from .._error_payload import error_payload
from .._root_identity import canonical_root_key, canonical_root_path
from ..config._schema import checked_setting
from ._auth import require_token
from ._runtime import get_request_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

__all__ = [
    "evict_project_route",
    "get_watcher_state_route",
    "list_projects_route",
    "reconfigure_watcher_route",
    "start_watcher_route",
    "stop_watcher_route",
]


async def _root_payload(request: Request) -> tuple[dict[str, object], Path]:
    """Validate root administration input before any lifecycle operation."""
    from ._routes import job_payload

    payload = await job_payload(request, required=True)
    root = payload.get("root")
    if not isinstance(root, str) or not root.strip():
        raise ValueError("root must be a non-empty path.")
    return payload, canonical_root_path(root)


def _watcher_timing(payload: dict[str, object]) -> tuple[int | None, float | None]:
    """Validate overrides through the same bounds as watcher settings."""
    debounce = payload.get("debounce_ms")
    cooldown = payload.get("cooldown_s")
    if debounce is not None:
        debounce = checked_setting("watch_debounce_ms", debounce, None)
    if cooldown is not None:
        cooldown = checked_setting("watch_cooldown_s", cooldown, None)
    return cast("int | None", debounce), cast("float | None", cooldown)


async def list_projects_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    registry = get_request_runtime(request).registry
    projects = registry.snapshot()
    for p in projects:
        p["root"] = str(p["root"])
    return JSONResponse(registry.projects_envelope(projects))


async def evict_project_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    try:
        _, target = await _root_payload(request)
    except (OSError, ValueError) as exc:
        return JSONResponse(
            error_payload("bad_request", str(exc)),
            status_code=400,
        )
    evicted, reason = await run_sync(
        partial(get_request_runtime(request).registry.try_evict, target)
    )
    return JSONResponse({"root": str(target), "evicted": evicted, "reason": reason})


async def get_watcher_state_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    project_root = request.query_params.get("project_root")
    from ..config._settings import get_config

    cfg = get_config()
    with _m._watcher_lock:
        roots = [str(p) for p in _m._watcher_tasks]

    from ..api import controller_snapshot_envelope
    from ._watcher import _controller_snapshots

    raw_limit = request.query_params.get("limit")
    try:
        limit = min(256, max(0, int(raw_limit))) if raw_limit is not None else 256
    except ValueError:
        limit = 256
    snapshots, globally_truncated = _controller_snapshots()
    root_filter = request.query_params.get("root") or project_root
    try:
        root_key = canonical_root_key(root_filter) if root_filter is not None else None
        project_key = (
            canonical_root_key(project_root) if project_root is not None else None
        )
    except (OSError, ValueError) as exc:
        return JSONResponse(error_payload("bad_request", str(exc)), status_code=400)
    source_filter = request.query_params.get("source")
    state_filter = request.query_params.get("state")
    filtered = [
        snapshot
        for snapshot in snapshots
        if (root_key is None or snapshot.canonical_root == root_key)
        and (source_filter is None or snapshot.source.value == source_filter)
        and (state_filter is None or snapshot.state.value == state_filter)
    ]
    returned = filtered[:limit]

    state = {
        "watch_enabled": bool(cfg.watch_enabled),
        "debounce_ms": int(cfg.watch_debounce_ms),
        "cooldown_s": float(cfg.watch_cooldown_s),
        "watching": sorted(roots),
        "controllers": [
            controller_snapshot_envelope(snapshot) for snapshot in returned
        ],
        "controllers_total": len(filtered),
        "controllers_returned": len(returned),
        "controllers_truncated": globally_truncated or len(filtered) > len(returned),
        "filters": {
            "root": root_filter,
            "source": source_filter,
            "state": state_filter,
            "limit": limit,
        },
    }

    if project_key is not None:
        state["running"] = project_key in {canonical_root_key(root) for root in roots}

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
    from ..config._settings import get_config

    try:
        _, target = await _root_payload(request)
    except (OSError, ValueError) as exc:
        return JSONResponse(error_payload("bad_request", str(exc)), status_code=400)
    cfg = get_config()
    outcome = _m._ensure_watcher(target, get_request_runtime(request).registry)
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
    try:
        _, target = await _root_payload(request)
    except (OSError, ValueError) as exc:
        return JSONResponse(error_payload("bad_request", str(exc)), status_code=400)
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
    from ..config._settings import get_config

    cfg = get_config()
    try:
        payload, target = await _root_payload(request)
        debounce_ms, cooldown_s = _watcher_timing(payload)
    except (OSError, ValueError, OverflowError) as exc:
        return JSONResponse(error_payload("bad_request", str(exc)), status_code=400)
    _m._stop_watcher(target)
    outcome = _m._ensure_watcher(
        target,
        get_request_runtime(request).registry,
        debounce_ms=debounce_ms,
        cooldown_s=cooldown_s,
    )

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
