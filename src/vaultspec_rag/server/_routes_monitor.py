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
    from collections.abc import Callable

    from starlette.requests import Request

    from ..monitor_process import MonitorProcess


#: Each ownership change by the last segment of its route: how it is made, and
#: the outcome reported when it changed something and when it did not.
_CHANGES: dict[
    str, tuple[Callable[[MonitorProcess], bool], tuple[str, str], tuple[str, str]]
] = {
    "handoff": (
        lambda monitor: monitor.hand_off(),
        ("handed_off", "The monitor will stay open while the service restarts."),
        ("no_monitor", "No running monitor needs to stay open for the restart."),
    ),
    "reclaim": (
        lambda monitor: monitor.reclaim(),
        ("reclaimed", "The service kept running, and so does its monitor."),
        ("not_released", "The monitor was not released, so nothing was taken back."),
    ),
}


async def monitor_ownership_route(request: Request) -> JSONResponse:
    """Token-gated change of who owns the monitor, reported as one outcome."""
    denied = require_token(request)
    if denied is not None:
        return denied
    change, done, unchanged = _CHANGES[request.url.path.rsplit("/", 1)[-1]]
    monitor = get_request_runtime(request).monitor
    changed = monitor is not None and await _run_in_thread(change, monitor)
    status, message = done if changed else unchanged
    return JSONResponse({"ok": True, "status": status, "message": message})
