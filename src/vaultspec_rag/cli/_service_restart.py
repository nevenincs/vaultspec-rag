"""``server restart``: stop and start the service, keeping its monitor open.

Restart composes the canonical stop and start verbs rather than restating
either. Before the stop it asks the running daemon to release its monitor, so
the monitor outlives the stop and the daemon the start launches adopts it: an
open monitor page keeps its access link and simply waits for the service.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import cast

import typer

from .._gpu_owner import observation_wire
from .._operator_commands import server_start_command
from .._python_child import module_command
from ..gpu_borrow_lease import borrower_start_message, observe_gpu_borrower
from ..serviceclient._discovery import _default_service_port
from ..serviceclient._transport import _try_http_admin, _try_http_health
from ._app import JsonMode, PortOption, server_root_app
from ._render import address_line
from ._service_lifecycle import (
    _fail_lifecycle,
    _lifecycle_success,
    _LifecycleFailure,
)

_RESTART_COMMAND = "service.restart"
#: Start's own model and storage budget, plus room for the stop before it.
_STEP_TIMEOUT_SECONDS = 1020


def _run_verb(verb: str, port: int | None) -> dict[str, object]:
    """Run one canonical lifecycle verb and return its single JSON envelope."""
    argv = module_command(sys.executable, "vaultspec_rag", "server", verb, "--json")
    if port is not None:
        argv += ["--port", str(port)]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"},
            timeout=_STEP_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": f"The {verb} step did not finish in time."}
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        envelope = json.loads(lines[-1]) if lines else None
    except ValueError:
        envelope = None
    if not isinstance(envelope, dict):
        return {"ok": False, "message": f"The {verb} step gave no readable result."}
    return cast("dict[str, object]", envelope)


def _step_message(envelope: dict[str, object], fallback: str) -> str:
    message = envelope.get("message")
    return message if isinstance(message, str) and message else fallback


def _guard_borrower_lease(json_mode: bool, port: int | None) -> None:
    """Refuse to stop a running service its start step would not bring back.

    Start refuses while a borrower holds the GPU, so a restart that stopped
    first would leave the service down for the whole borrow. Refusing before
    the stop leaves it running as it was. A service that is not running has
    nothing to keep, and its start step refuses with its own message.
    """
    borrower = observe_gpu_borrower()
    if borrower.permits_service_start:
        return
    if port is None or _try_http_health(port) is None:
        return
    message = borrower_start_message(borrower, verb="restart")
    raise _fail_lifecycle(
        json_mode,
        _LifecycleFailure(
            command=_RESTART_COMMAND,
            error="gpu_borrowed",
            message=message,
            human_lines=(message,),
        ),
        gpu_borrower=observation_wire(borrower),
    )


@server_root_app.command(
    "restart", help="Restart the background search service, keeping its monitor."
)
def service_restart(
    port: PortOption = None,
    json_mode: JsonMode = False,
) -> None:
    """Stop and start the service; an open monitor page reconnects by itself.

    A service that is not running is started. Exit codes: 0 when the service
    is running again, 1 when the stop or the start failed.
    """
    resolved_port = port if port is not None else _default_service_port()
    _guard_borrower_lease(json_mode, resolved_port)
    released = None
    if resolved_port is not None:
        released = _try_http_admin("hand_off_monitor", {}, resolved_port)
    monitor_kept = isinstance(released, dict) and released.get("status") == (
        "handed_off"
    )

    stopped = _run_verb("stop", port)
    if stopped.get("ok") is not True:
        if monitor_kept and resolved_port is not None:
            # The daemon is still serving; its monitor must stay its own.
            _try_http_admin("reclaim_monitor", {}, resolved_port)
        message = _step_message(stopped, "The service did not stop.")
        raise _fail_lifecycle(
            json_mode,
            _LifecycleFailure(
                command=_RESTART_COMMAND,
                error="restart_stop_failed",
                message=message,
                human_lines=(message,),
            ),
        )
    match stopped.get("data"):
        case {"status": "already_stopped"}:
            was_running = False
        case _:
            was_running = True

    started = _run_verb("start", resolved_port)
    if started.get("ok") is not True:
        message = _step_message(started, "The service did not start again.")
        raise _fail_lifecycle(
            json_mode,
            _LifecycleFailure(
                command=_RESTART_COMMAND,
                error="restart_start_failed",
                message=message,
                human_lines=(message,),
                next_actions=(server_start_command(resolved_port),),
            ),
        )
    data = started.get("data")
    details = cast("dict[str, object]", data) if isinstance(data, dict) else {}
    service_port = details.get("port", resolved_port)
    monitor_url = details.get("monitor_url")
    human_lines = [address_line(service_port)]
    if isinstance(monitor_url, str) and monitor_url:
        human_lines.append(
            "Monitor: the open monitor page stays connected."
            if monitor_kept
            else f"Monitor: {monitor_url}"
        )
    _lifecycle_success(
        json_mode,
        command=_RESTART_COMMAND,
        status="restarted" if was_running else "started",
        human_title="Service restarted" if was_running else "Service started",
        human_lines=tuple(human_lines),
        port=service_port,
        monitor_url=monitor_url,
        monitor_kept=monitor_kept,
    )
    raise typer.Exit(0)
