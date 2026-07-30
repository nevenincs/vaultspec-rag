"""``server pause`` / ``server resume``: hold and release the whole daemon.

Quiesce is a hold, never a stop: the daemon stays alive and every in-flight
worker parks at its next safe checkpoint until resumed. These verbs adapt to the
service-owned pause/resume behaviour rather than owning it - the localhost route
computes the status vocabulary and this layer only renders it.
"""

from __future__ import annotations

import typer

from .._operator_commands import SERVICE_NOT_RUNNING_MESSAGE
from ..serviceclient._discovery import _default_service_port
from ..serviceclient._transport import _try_http_admin
from ._app import (
    JsonMode,
    PortOption,
    server_app,
)
from ._render import (
    _emit_json,
    _emit_json_error_and_exit,
    _plain,
    address_line,
)

_PAUSE_COMMAND = "service.pause"
_RESUME_COMMAND = "service.resume"


def _quiesce(*, pause: bool, command: str, port: int | None, json_mode: bool) -> None:
    """Drive one pause/resume transition and emit exactly one outcome.

    Only a service-owned ``ok: true`` response is successful. Every failure
    keeps the service's error, status, message, retryability, and full quiesce
    envelope intact for operators and machine consumers.
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
    if result.get("ok") is True:
        if json_mode:
            _emit_json(True, command, data=result)
            raise typer.Exit(0)
        _plain(f"Service quiesce status: {result.get('status')}.")
        raise typer.Exit(0)

    error = result.get("error")
    status = result.get("status")
    message = result.get("message")
    retryable = result.get("retryable")
    if (
        isinstance(error, str)
        and isinstance(status, str)
        and isinstance(message, str)
        and isinstance(retryable, bool)
    ):
        if json_mode:
            _emit_json_error_and_exit(
                command,
                error,
                message,
                1,
                data=result,
                status=status,
                retryable=retryable,
            )
        _plain(f"{status}: {message}")
        _plain(f"Retryable: {retryable}")
        raise typer.Exit(1)

    if json_mode:
        _emit_json_error_and_exit(
            command,
            "invalid_service_response",
            "The service returned an invalid quiesce response.",
            1,
            data=result,
        )
    _plain("The service returned an invalid quiesce response.")
    raise typer.Exit(1)


def _fail_unreachable(command: str, json_mode: bool, *, port: int | None) -> None:
    message = SERVICE_NOT_RUNNING_MESSAGE
    if json_mode:
        _emit_json_error_and_exit(
            command, "service_unreachable", message, 1, data={"port": port}
        )
    if port is not None:
        _plain(address_line(port))
    _plain(message)
    raise typer.Exit(1)


@server_app.command("pause", help="Hold the running service at safe checkpoints.")
def service_pause(
    port: PortOption = None,
    json_mode: JsonMode = False,
) -> None:
    """Pause the whole daemon; it stays alive and releases on ``server resume``."""
    _quiesce(pause=True, command=_PAUSE_COMMAND, port=port, json_mode=json_mode)


@server_app.command("resume", help="Release a paused service.")
def service_resume(
    port: PortOption = None,
    json_mode: JsonMode = False,
) -> None:
    """Release a paused daemon so held workers continue."""
    _quiesce(pause=False, command=_RESUME_COMMAND, port=port, json_mode=json_mode)
