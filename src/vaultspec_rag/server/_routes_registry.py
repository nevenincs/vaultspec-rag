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
from .._operator_commands import server_updates_start_command
from .._root_identity import canonical_root_key, canonical_root_path
from .._root_presence import root_is_missing, stale_watcher_roots
from .._root_record_store import RootRecordStoreError
from ..config._schema import checked_setting
from ..watcher_intent import (
    AutoUpdateState,
    auto_update_state,
    auto_update_store_path,
    disable_auto_update,
    disabled_roots,
    enable_auto_update,
)
from ._auth import require_token
from ._runtime import get_request_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from .._root_presence import StaleWatcherRoot
    from ..watcher_controller import ControllerSnapshot
    from ..watcher_intent import AutoUpdateDisabled

__all__ = [
    "evict_project_route",
    "get_watcher_state_route",
    "list_projects_route",
    "prune_watchers_route",
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

    def mark_missing() -> None:
        for p in projects:
            p["root"] = str(p["root"])
            # A loaded project whose directory is gone is stale: every request
            # against it is refused until it is unloaded or recreated.
            p["root_missing"] = root_is_missing(p["root"])

    await run_sync(mark_missing)
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

    limit = _watcher_state_limit(request.query_params.get("limit"))
    snapshots, globally_truncated = _controller_snapshots()
    stale = await run_sync(stale_watcher_roots)
    opted_out, store_fault = await run_sync(disabled_roots)
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
        if _snapshot_matches(snapshot, root_key, source_filter, state_filter)
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
        **_stale_roots_block(stale, root_key, limit),
        **_auto_update_block(opted_out, store_fault, root_key, limit),
        "filters": {
            "root": root_filter,
            "source": source_filter,
            "state": state_filter,
            "limit": limit,
        },
    }

    if project_key is not None:
        state["running"] = project_key in {canonical_root_key(root) for root in roots}
        state["auto_update"] = _auto_update_value(project_key, opted_out, store_fault)

    return JSONResponse(state)


def _watcher_state_limit(raw_limit: str | None) -> int:
    """Clamp the requested page size, defaulting to the bounded maximum."""
    try:
        return min(256, max(0, int(raw_limit))) if raw_limit is not None else 256
    except ValueError:
        return 256


def _snapshot_matches(
    snapshot: ControllerSnapshot,
    root_key: str | None,
    source_filter: str | None,
    state_filter: str | None,
) -> bool:
    return (
        (root_key is None or snapshot.canonical_root == root_key)
        and (source_filter is None or snapshot.source.value == source_filter)
        and (state_filter is None or snapshot.state.value == state_filter)
    )


def _stale_roots_block(
    stale: tuple[StaleWatcherRoot, ...],
    root_key: str | None,
    limit: int,
) -> dict[str, object]:
    """Report watched roots whose directory was deleted or moved.

    Their watchers were stopped; the records stay until pruned or the root
    returns.
    """
    matching = [
        record
        for record in stale
        if root_key is None or canonical_root_key(record.root) == root_key
    ]
    return {
        "stale_roots": [record.as_dict() for record in matching[:limit]],
        "stale_roots_total": len(matching),
    }


def _auto_update_value(
    root_key: str,
    opted_out: tuple[AutoUpdateDisabled, ...],
    store_fault: str | None,
) -> str:
    """Name one root's automatic-update intent from an already-read page."""
    if store_fault is not None:
        return AutoUpdateState.UNVERIFIABLE.value
    if any(canonical_root_key(record.root) == root_key for record in opted_out):
        return AutoUpdateState.DISABLED.value
    return AutoUpdateState.ENABLED.value


def _auto_update_block(
    opted_out: tuple[AutoUpdateDisabled, ...],
    store_fault: str | None,
    root_key: str | None,
    limit: int,
) -> dict[str, object]:
    """Report roots an operator stopped, and whether that record can be read.

    An unverifiable store starts no new watcher for any root, so it is
    reported with the file to repair rather than as an empty list.
    """
    matching = [
        record
        for record in opted_out
        if root_key is None or canonical_root_key(record.root) == root_key
    ]
    return {
        "auto_update_disabled": [record.as_dict() for record in matching[:limit]],
        "auto_update_disabled_total": len(matching),
        "auto_update_store": {
            "status": "unverifiable" if store_fault is not None else "ok",
            "path": str(auto_update_store_path()),
            "reason": store_fault,
        },
    }


def _auto_update_store_error(
    exc: OSError,
    target: Path,
    **extra: object,
) -> JSONResponse:
    """Refuse a change to operator intent that could not be persisted."""
    if isinstance(exc, RootRecordStoreError):
        return JSONResponse(
            {
                **error_payload("auto_update_store_unverifiable", str(exc)),
                "root": str(target),
                "store": str(exc.path),
                **extra,
            },
            status_code=409,
        )
    return JSONResponse(
        {
            **error_payload(
                "auto_update_store_unwritable",
                f"Could not record the automatic update setting: {exc}",
            ),
            "root": str(target),
            "store": str(auto_update_store_path()),
            **extra,
        },
        status_code=503,
    )


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
    # The explicit start is the one path that clears an operator's stop, so
    # the record goes first: a start that could not clear it would be undone
    # by the next restart.
    try:
        await run_sync(enable_auto_update, target)
    except OSError as exc:
        return _auto_update_store_error(exc, target, started=False)
    outcome = _m._ensure_watcher(target, get_request_runtime(request).registry)
    return JSONResponse(
        {
            "root": str(target),
            "started": outcome.running,
            "status": outcome.value,
            "watch_enabled": bool(cfg.watch_enabled),
            "auto_update": AutoUpdateState.ENABLED.value,
        }
    )


async def stop_watcher_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    from ._routes import validated_initiator

    try:
        payload, target = await _root_payload(request)
        initiator = validated_initiator(
            payload, root=target, default_command="server updates stop"
        )
    except (OSError, ValueError) as exc:
        return JSONResponse(error_payload("bad_request", str(exc)), status_code=400)
    with _m._watcher_lock:
        was_running = target in _m._watcher_tasks
    try:
        await run_sync(partial(disable_auto_update, target, initiator=initiator.kind))
    except OSError as exc:
        # The watcher still stops: the operator asked for that, and only the
        # persistence failed. The refusal says the stop will not survive.
        _m._stop_watcher(target)
        return _auto_update_store_error(exc, target, stopped=was_running)
    _m._stop_watcher(target)
    return JSONResponse(
        {
            "root": str(target),
            "stopped": was_running,
            "status": "stopped" if was_running else "already_stopped",
            "auto_update": AutoUpdateState.DISABLED.value,
            "start_command": server_updates_start_command(
                str(target), get_request_runtime(request).port
            ),
        }
    )


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
    db_ms = int(debounce_ms) if debounce_ms is not None else int(cfg.watch_debounce_ms)
    db_cs = float(cooldown_s) if cooldown_s is not None else float(cfg.watch_cooldown_s)
    intent = await run_sync(auto_update_state, target)
    if intent is not AutoUpdateState.ENABLED:
        # Timing is not a start. An operator's stop, or a record that cannot
        # be read, stays in force until the explicit start verb.
        return JSONResponse(
            {
                "root": str(target),
                "restarted": False,
                "status": (
                    "disabled_by_operator"
                    if intent is AutoUpdateState.DISABLED
                    else "auto_update_unverifiable"
                ),
                "auto_update": intent.value,
                "start_command": server_updates_start_command(
                    str(target), get_request_runtime(request).port
                ),
                "debounce_ms": db_ms,
                "cooldown_s": db_cs,
            }
        )
    _m._stop_watcher(target)
    outcome = _m._ensure_watcher(
        target,
        get_request_runtime(request).registry,
        debounce_ms=debounce_ms,
        cooldown_s=cooldown_s,
    )
    return JSONResponse(
        {
            "root": str(target),
            "restarted": outcome.running,
            "status": outcome.value,
            "debounce_ms": db_ms,
            "cooldown_s": db_cs,
        }
    )


async def prune_watchers_route(request: Request) -> JSONResponse:
    """Stop every watcher whose root no longer exists and forget its record.

    ``dry_run`` reports the same set without changing anything. Finding nothing
    to prune is success: the requested state, no stale watchers, holds.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    from ._routes import InvalidJobRequestError, job_payload
    from ._watcher import _owned_watcher_roots
    from ._watcher_stale import prune_stale_watchers, stale_watcher_candidates

    try:
        payload = await job_payload(request, required=False)
    except InvalidJobRequestError as exc:
        return JSONResponse(error_payload("bad_request", str(exc)), status_code=400)
    dry_run = payload.get("dry_run", False)
    if type(dry_run) is not bool:
        return JSONResponse(
            error_payload("bad_request", "dry_run must be a boolean."),
            status_code=400,
        )
    candidates = await run_sync(stale_watcher_candidates, _owned_watcher_roots())
    if not dry_run:
        prune_stale_watchers(candidates)
    return JSONResponse(
        {
            "ok": True,
            "dry_run": dry_run,
            "status": (
                "nothing_to_prune"
                if not candidates
                else "would_prune"
                if dry_run
                else "pruned"
            ),
            "count": len(candidates),
            "roots": [candidate.as_dict() for candidate in candidates],
        }
    )
