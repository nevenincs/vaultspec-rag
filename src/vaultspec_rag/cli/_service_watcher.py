"""``server updates`` commands: automatic index update controls."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer

import vaultspec_rag.cli as _cli

from .._operator_commands import (
    SERVICE_NOT_RUNNING_MESSAGE,
    server_start_command,
    server_status_command,
)
from ..serviceclient._discovery import _default_service_port
from ..serviceclient._transport import _try_http_admin
from ._app import server_watcher_app
from ._cli_format import _counted_unit, _project_name
from ._render import (
    _address_line,
    _display_service_not_running,
    _emit_json,
    _emit_json_error_and_exit,
    _plain,
)


def _format_milliseconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported"
    milliseconds = max(0.0, float(raw))
    if milliseconds == 0:
        return "immediately"
    if milliseconds < 1000:
        return _counted_unit(int(milliseconds), "millisecond")
    seconds = milliseconds / 1000.0
    if seconds.is_integer():
        return _counted_unit(int(seconds), "second")
    return f"{seconds:.1f} seconds"


def _format_seconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported"
    seconds = max(0.0, float(raw))
    if seconds == 0:
        return "immediately"
    if seconds < 60:
        if seconds.is_integer():
            return _counted_unit(int(seconds), "second")
        return f"{seconds:.1f} seconds"
    minutes, remainder = divmod(int(seconds), 60)
    if remainder:
        return (
            f"{_counted_unit(minutes, 'minute')} {_counted_unit(remainder, 'second')}"
        )
    return _counted_unit(minutes, "minute")


def _resolve_project_argument(project: str) -> str:
    return str(Path(project).expanduser().resolve())


def _print_update_address(port: int) -> None:
    _plain(_address_line(port))


def _print_update_project(project: str) -> None:
    _plain(f"Project: {_project_name(project)}")
    _plain(f"Path: {project}", soft_wrap=True)


def _print_update_result(port: int, status: str, project: str) -> None:
    _print_update_address(port)
    _plain(f"Automatic index updates: {status}")
    _print_update_project(project)


def _print_update_timing(result: dict[str, object]) -> None:
    update_delay = _format_milliseconds(result.get("debounce_ms"))
    repeat_update_delay = _format_seconds(result.get("cooldown_s"))
    if update_delay == "not reported":
        _plain("File changes: not reported by service.")
    else:
        _plain(f"File changes: wait {update_delay} before updating.")
    if repeat_update_delay == "not reported":
        _plain("Repeat updates: not reported by service.")
        return
    _plain(
        f"Repeat updates: wait {repeat_update_delay} before updating a project again."
    )


def _watcher_service_unreachable(
    command: str,
    json_mode: bool,
    port: int | None = None,
    **extra: object,
) -> None:
    """Emit the standard 'service not running' result and exit 3."""
    if json_mode:
        _emit_json_error_and_exit(
            command,
            "service_not_running",
            SERVICE_NOT_RUNNING_MESSAGE,
            3,
            **extra,
        )
    _display_service_not_running(port)
    raise typer.Exit(3)


def _watcher_admin_error(
    command: str,
    json_mode: bool,
    result: dict[str, object],
    port: int,
    *,
    root: str | None = None,
) -> None:
    error = str(result.get("error") or "service_error")
    message = str(result.get("message") or "Service did not complete the request.")
    if json_mode:
        _emit_json_error_and_exit(command, error, message, 1, root=root, port=port)
    _print_update_address(port)
    _plain(f"Automatic index updates: {message}")
    if root is not None:
        _print_update_project(root)
    _plain("Next actions:")
    _plain(f"  vaultspec-rag server status --port {port}")
    _plain(f"  vaultspec-rag server logs --limit 200 --port {port}")
    raise typer.Exit(1)


#: How the service describes a root whose watcher is not running, and why.
#: A request the service recorded but has not yet honoured is reported as not
#: achieved, so the caller is never told automatic updates are on while they
#: are still off.
_UPDATES_STATE_PHRASES = {
    "pending": (
        "another start for this project is still finishing, "
        "so this request is queued behind it"
    ),
    "queued_behind_drain": (
        "the previous watcher for this project is still stopping, "
        "so this request is queued behind it"
    ),
    "disabled": "automatic updates are switched off for this service",
    "unavailable": "the service did not start one",
}

_UPDATES_STATE_ERRORS = {
    "pending": "updates_pending",
    "queued_behind_drain": "updates_pending",
    "disabled": "updates_disabled",
    "unavailable": "updates_not_started",
}


def _updates_next_actions(status: str, port: int) -> list[str]:
    """Return the remediation a caller can act on for one unachieved state."""
    if status == "disabled":
        return [server_start_command(updates=True)]
    if status in ("pending", "queued_behind_drain"):
        return [f"vaultspec-rag server updates status --port {port}"]
    return [
        server_status_command(port),
        f"vaultspec-rag server logs --limit 200 --port {port}",
    ]


def _updates_state_not_achieved(
    command: str,
    json_mode: bool,
    result: dict[str, object],
    port: int,
    project: str,
    *,
    verb_phrase: str,
) -> None:
    """Emit one result for a request the service did not achieve, and exit 1.

    Both modes converge here so the human text and the JSON envelope name the
    same state, and neither reports success for a watcher that is not running.
    """
    raw_status = str(result.get("status") or "")
    if raw_status in _UPDATES_STATE_PHRASES:
        status = raw_status
    elif result.get("watch_enabled") is False:
        status = "disabled"
    else:
        status = "unavailable"
    reason = _UPDATES_STATE_PHRASES[status]
    if json_mode:
        _emit_json_error_and_exit(
            command,
            _UPDATES_STATE_ERRORS[status],
            f"Automatic index updates {verb_phrase}: {reason}.",
            1,
            data=result,
        )
    _print_update_result(port, verb_phrase, project)
    _plain(f"Reason: {reason}.")
    _plain("Next actions:")
    for action in _updates_next_actions(status, port):
        _plain(f"  {action}")
    raise typer.Exit(1)


_UPDATES_STATUS_COMMAND = "service.updates.status"
_UPDATES_START_COMMAND = "service.updates.start"
_UPDATES_STOP_COMMAND = "service.updates.stop"
_UPDATES_TIMING_COMMAND = "service.updates.timing"


@server_watcher_app.command("status")
def service_watcher_status(
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Show automatic index update settings and projects."""
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _watcher_service_unreachable(_UPDATES_STATUS_COMMAND, json_mode)
        return
    result = _try_http_admin("get_watcher_state", {}, resolved_port)
    if result is None:
        _watcher_service_unreachable(
            _UPDATES_STATUS_COMMAND, json_mode, port=resolved_port
        )
        return
    if result.get("ok") is False:
        _watcher_admin_error(_UPDATES_STATUS_COMMAND, json_mode, result, resolved_port)
        return
    raw_watching = result.get("watching")
    watching: list[object] = (
        cast("list[object]", raw_watching) if isinstance(raw_watching, list) else []
    )
    enabled = bool(result.get("watch_enabled", False))
    if json_mode:
        _emit_json(True, _UPDATES_STATUS_COMMAND, data=result)
        return
    mode = "enabled" if enabled else "disabled; indexes update when requested"
    _print_update_address(resolved_port)
    _plain(f"Automatic index updates: {mode}")
    _print_update_timing(result)
    if not watching:
        _cli.console.print("No projects currently have automatic index updates.")
        return
    _cli.console.print(f"Projects updating automatically: {len(watching)}")
    for entry in watching:
        _plain(f"- Project: {_project_name(entry)}")
        _plain(f"  Path: {entry}", soft_wrap=True)


@server_watcher_app.command("start")
def service_watcher_start(
    project: Annotated[str, typer.Argument(help="Project to keep indexed.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Start automatic index updates for a project."""
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _watcher_service_unreachable(_UPDATES_START_COMMAND, json_mode, root=project)
        return
    resolved_project = _resolve_project_argument(project)
    result = _try_http_admin(
        "start_watcher",
        {"root": resolved_project},
        resolved_port,
    )
    if result is None:
        _watcher_service_unreachable(
            _UPDATES_START_COMMAND, json_mode, port=resolved_port, root=project
        )
        return
    if result.get("ok") is False:
        _watcher_admin_error(
            _UPDATES_START_COMMAND,
            json_mode,
            result,
            resolved_port,
            root=resolved_project,
        )
        return
    if not bool(result.get("started", False)):
        _updates_state_not_achieved(
            _UPDATES_START_COMMAND,
            json_mode,
            result,
            resolved_port,
            resolved_project,
            verb_phrase="not started",
        )
        return
    if json_mode:
        _emit_json(True, _UPDATES_START_COMMAND, data=result)
        return
    already = str(result.get("status") or "") == "already_running"
    _print_update_result(
        resolved_port,
        "already running" if already else "started",
        resolved_project,
    )
    raise typer.Exit(0)


@server_watcher_app.command("stop")
def service_watcher_stop(
    project: Annotated[
        str,
        typer.Argument(help="Project to stop updating automatically."),
    ],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Stop automatic index updates for a project."""
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _watcher_service_unreachable(_UPDATES_STOP_COMMAND, json_mode, root=project)
        return
    resolved_project = _resolve_project_argument(project)
    result = _try_http_admin(
        "stop_watcher",
        {"root": resolved_project},
        resolved_port,
    )
    if result is None:
        _watcher_service_unreachable(
            _UPDATES_STOP_COMMAND, json_mode, port=resolved_port, root=project
        )
        return
    if result.get("ok") is False:
        _watcher_admin_error(
            _UPDATES_STOP_COMMAND,
            json_mode,
            result,
            resolved_port,
            root=resolved_project,
        )
        return
    stopped = bool(result.get("stopped", False))
    if json_mode:
        _emit_json(True, _UPDATES_STOP_COMMAND, data=result)
        return
    if stopped:
        _print_update_result(resolved_port, "stopped", resolved_project)
    else:
        _print_update_result(
            resolved_port,
            "not running for this project",
            resolved_project,
        )
    raise typer.Exit(0)


@server_watcher_app.command("timing")
def service_watcher_timing(
    project: Annotated[str, typer.Argument(help="Project to update timing for.")],
    update_delay_ms: Annotated[
        int | None,
        typer.Option(
            "--update-delay-ms",
            help="Delay before indexing a burst of file changes, in milliseconds.",
        ),
    ] = None,
    repeat_update_delay_s: Annotated[
        float | None,
        typer.Option(
            "--repeat-update-delay-s",
            help=(
                "Minimum wait before automatically updating a project again, "
                "in seconds."
            ),
        ),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Change automatic index update timing."""
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _watcher_service_unreachable(
            _UPDATES_TIMING_COMMAND,
            json_mode,
            root=project,
        )
        return
    resolved_project = _resolve_project_argument(project)
    args: dict[str, object] = {"root": resolved_project}
    if update_delay_ms is not None:
        args["debounce_ms"] = update_delay_ms
    if repeat_update_delay_s is not None:
        args["cooldown_s"] = repeat_update_delay_s
    result = _try_http_admin("reconfigure_watcher", args, resolved_port)
    if result is None:
        _watcher_service_unreachable(
            _UPDATES_TIMING_COMMAND,
            json_mode,
            port=resolved_port,
            root=project,
        )
        return
    if result.get("ok") is False:
        _watcher_admin_error(
            _UPDATES_TIMING_COMMAND,
            json_mode,
            result,
            resolved_port,
            root=resolved_project,
        )
        return
    if not bool(result.get("restarted", False)):
        _updates_state_not_achieved(
            _UPDATES_TIMING_COMMAND,
            json_mode,
            result,
            resolved_port,
            resolved_project,
            verb_phrase="timing not applied",
        )
        return
    if json_mode:
        _emit_json(True, _UPDATES_TIMING_COMMAND, data=result)
        return
    _print_update_result(resolved_port, "timing updated", resolved_project)
    _print_update_timing(result)
    raise typer.Exit(0)
