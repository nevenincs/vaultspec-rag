"""Release the managed monitor to the next daemon, and take it back.

Only a restart calls these. ``POST /monitor/handoff`` runs immediately before
it stops this daemon: the monitor then outlives the stop, and the daemon the
restart starts adopts it, so an open monitor page keeps its access link across
the restart. ``POST /monitor/reclaim`` runs when that stop failed and this
daemon is still serving, so the monitor stays its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from anyio.to_thread import run_sync as _run_in_thread
from starlette.responses import JSONResponse

from ._auth import require_token
from ._runtime import get_request_runtime

if TYPE_CHECKING:
    from starlette.requests import Request


async def monitor_handoff_route(request: Request) -> JSONResponse:
    """Token-gated handoff; a daemon without a running monitor has none to give."""
    denied = require_token(request)
    if denied is not None:
        return denied
    monitor = get_request_runtime(request).monitor
    released = monitor is not None and await _run_in_thread(monitor.hand_off)
    if released:
        return JSONResponse(
            {
                "ok": True,
                "status": "handed_off",
                "message": "The monitor will stay open while the service restarts.",
            }
        )
    return JSONResponse(
        {
            "ok": True,
            "status": "no_monitor",
            "message": "No running monitor needs to stay open for the restart.",
        }
    )


async def monitor_reclaim_route(request: Request) -> JSONResponse:
    """Token-gated reclaim; a daemon that released nothing has nothing to take back."""
    denied = require_token(request)
    if denied is not None:
        return denied
    monitor = get_request_runtime(request).monitor
    reclaimed = monitor is not None and await _run_in_thread(monitor.reclaim)
    if reclaimed:
        return JSONResponse(
            {
                "ok": True,
                "status": "reclaimed",
                "message": "The service kept running, and so does its monitor.",
            }
        )
    return JSONResponse(
        {
            "ok": True,
            "status": "not_released",
            "message": "The monitor was not released, so nothing was taken back.",
        }
    )
