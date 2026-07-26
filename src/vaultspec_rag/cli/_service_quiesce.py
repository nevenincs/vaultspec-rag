"""``server pause`` / ``server resume``: hold and release the whole daemon.

Quiesce is a hold, never a stop: the daemon stays alive and every in-flight
worker parks at its next safe checkpoint until resumed. These verbs adapt to the
service-owned pause/resume behaviour rather than owning it - the localhost route
computes the status vocabulary and this layer only renders it.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..serviceclient._discovery import _default_service_port
from ..serviceclient._transport import _try_http_admin
from ._app import server_app
from ._render import (
    _address_line,
    _emit_json,
    _emit_json_error_and_exit,
    _plain,
)

_PAUSE_COMMAND = "service.pause"
_RESUME_COMMAND = "service.resume"


def _quiesce(*, pause: bool, command: str, port: int | None, json_mode: bool) -> None:
    """Drive one pause/resume transition and emit exactly one outcome.

    Idempotent: an already-satisfied request is a success (exit 0 with an
    ``already_*`` status). A request that leaves the state unachieved - a pause
    that left the daemon running because a shutdown has latched the gate open,
    or a resume that left it held - is a failure (exit 1 in both modes) so a
    supervising broker never reads it as done.
    """
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _fail_unreachable(command, json_mode, port=None)
        return
    tool = "pause_service" if pause else "resume_service"
    result = _try_http_admin(tool, {}, resolved_port)
    if result is None:
        _fail_unreachable(command, json_mode, port=resolved_port)
        return
    if not result.get("ok", False):
        error = str(result.get("error", "http_call_failed"))
        message = str(result.get("message", "The pause/resume request failed."))
        if json_mode:
            _emit_json_error_and_exit(command, error, message, 1, data=result)
        _plain(message)
        raise typer.Exit(1)

    status = str(result.get("status", ""))
    paused = bool(result.get("paused", pause))
    achieved = paused if pause else not paused
    if not achieved:
        error = "hold_not_achieved" if pause else "release_not_achieved"
        message = (
            "The service did not hold - a shutdown is in progress and the pause "
            "gate is latched open."
            if pause
            else "The service did not release and remains held."
        )
        if json_mode:
            _emit_json_error_and_exit(command, error, message, 1, data=result)
        _plain(message)
        raise typer.Exit(1)

    if json_mode:
        _emit_json(True, command, data=result)
        raise typer.Exit(0)
    _plain(_human_line(status))
    raise typer.Exit(0)


def _human_line(status: str) -> str:
    return {
        "paused": "Service paused. Workers hold at their next safe checkpoint; "
        "resume with `vaultspec-rag server resume`.",
        "already_paused": "Service is already paused.",
        "resumed": "Service resumed. Held workers are released.",
        "already_running": "Service is already running.",
    }.get(status, f"Service quiesce status: {status}.")


def _fail_unreachable(command: str, json_mode: bool, *, port: int | None) -> None:
    message = "Service is not running. Start it with `vaultspec-rag server start`."
    if json_mode:
        _emit_json_error_and_exit(
            command, "service_unreachable", message, 1, data={"port": port}
        )
    if port is not None:
        _plain(_address_line(port))
    _plain(message)
    raise typer.Exit(1)


@server_app.command("pause", help="Hold the running service at safe checkpoints.")
def service_pause(
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Pause the whole daemon; it stays alive and releases on ``server resume``."""
    _quiesce(pause=True, command=_PAUSE_COMMAND, port=port, json_mode=json_mode)


@server_app.command("resume", help="Release a paused service.")
def service_resume(
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Release a paused daemon so held workers continue."""
    _quiesce(pause=False, command=_RESUME_COMMAND, port=port, json_mode=json_mode)
