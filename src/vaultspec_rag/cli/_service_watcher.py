"""``server updates`` commands: automatic index update controls."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, NamedTuple, cast

import typer

import vaultspec_rag.cli as _cli

from .._operator_commands import (
    SERVICE_NOT_RUNNING_MESSAGE,
    server_start_command,
    server_status_command,
)
from ..serviceclient._discovery import _default_service_port
from ..serviceclient._transport import _try_http_admin
from ._app import (
    JsonMode,
    PortOption,
    RepeatUpdateDelayOption,
    UpdateDelayOption,
    server_watcher_app,
)
from ._cli_format import _counted_unit, _project_name
from ._render import (
    _display_service_not_running,
    _emit_json,
    _emit_json_error_and_exit,
    _plain,
    address_line,
)


def _format_delay_milliseconds(raw: object) -> str:
    """Render a CONFIGURED millisecond delay in this surface's vocabulary.

    A delay is not an elapsed duration and does not share its renderer: zero
    reads as ``immediately`` rather than as a quantity, a sub-second value
    keeps its millisecond tier, and a fractional second survives instead of
    being floored. Naming the subject keeps this distinct from the elapsed
    formatter of the same shape that the shared format module owns.

    ``bool`` is refused despite being an ``int``: the payload is untrusted,
    and a ``debounce_ms`` of ``True`` would otherwise read as a configured
    one-millisecond delay rather than as an unreported field.
    """
    if not isinstance(raw, int | float) or isinstance(raw, bool):
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


def _format_delay_seconds(raw: object) -> str:
    """Render a CONFIGURED second-granularity delay in the same vocabulary.

    Deliberately stops cascading at minutes: a repeat-update delay is a knob
    an operator sets in minutes, so "60 minutes" states the setting where
    "1 hour" would restate it in units nobody configured it in.

    ``bool`` is refused for the same reason as the millisecond renderer.
    """
    if not isinstance(raw, int | float) or isinstance(raw, bool):
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
    _plain(address_line(port))


def _print_update_project(project: str) -> None:
    _plain(f"Project: {_project_name(project)}")
    _plain(f"Path: {project}", soft_wrap=True)


def _print_update_result(port: int, status: str, project: str) -> None:
    _print_update_address(port)
    _plain(f"Automatic index updates: {status}")
    _print_update_project(project)


def _print_update_timing(result: dict[str, object]) -> None:
    update_delay = _format_delay_milliseconds(result.get("debounce_ms"))
    repeat_update_delay = _format_delay_seconds(result.get("cooldown_s"))
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


@dataclass(frozen=True, slots=True)
class _UpdateStateFailure:
    command: str
    json_mode: bool
    result: dict[str, object]
    port: int
    project: str
    verb_phrase: str


def _updates_state_not_achieved(failure: _UpdateStateFailure) -> None:
    """Emit one result for a request the service did not achieve, and exit 1.

    Both modes converge here so the human text and the JSON envelope name the
    same state, and neither reports success for a watcher that is not running.
    """
    raw_status = str(failure.result.get("status") or "")
    if raw_status in _UPDATES_STATE_PHRASES:
        status = raw_status
    elif failure.result.get("watch_enabled") is False:
        status = "disabled"
    else:
        status = "unavailable"
    reason = _UPDATES_STATE_PHRASES[status]
    if failure.json_mode:
        _emit_json_error_and_exit(
            failure.command,
            _UPDATES_STATE_ERRORS[status],
            f"Automatic index updates {failure.verb_phrase}: {reason}.",
            1,
            data=failure.result,
        )
    _print_update_result(failure.port, failure.verb_phrase, failure.project)
    _plain(f"Reason: {reason}.")
    _plain("Next actions:")
    for action in _updates_next_actions(status, failure.port):
        _plain(f"  {action}")
    raise typer.Exit(1)


_UPDATES_STATUS_COMMAND = "service.updates.status"
_UPDATES_START_COMMAND = "service.updates.start"
_UPDATES_STOP_COMMAND = "service.updates.stop"
_UPDATES_TIMING_COMMAND = "service.updates.timing"


@server_watcher_app.command("status")
def service_watcher_status(
    port: PortOption = None,
    json_mode: JsonMode = False,
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


class _WatcherCall(NamedTuple):
    """One accepted watcher admin call and the address it reached."""

    result: dict[str, object]
    port: int
    project: str


def _call_watcher_admin(
    verb: str,
    command: str,
    *,
    project: str,
    port: int | None,
    json_mode: bool,
) -> _WatcherCall | None:
    """Resolve the service, call one project-scoped watcher verb, or refuse.

    ``start`` and ``stop`` reached the service through the same eleven
    statements, differing only in the verb they name and the command they
    attribute a failure to. Three of those statements are refusals, and each
    is a separate exit path an operator or a broker reads: no reachable
    service, a service that did not answer, and a service that answered no.
    Duplicating a set of exit paths is how one verb grows a fourth and the
    other keeps three.

    Returns ``None`` when it has already reported the failure, so a caller
    returns without deciding anything - the refusal and the exit code are
    settled here.
    """
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _watcher_service_unreachable(command, json_mode, root=project)
        return None
    resolved_project = _resolve_project_argument(project)
    result = _try_http_admin(verb, {"root": resolved_project}, resolved_port)
    if result is None:
        _watcher_service_unreachable(
            command, json_mode, port=resolved_port, root=project
        )
        return None
    if result.get("ok") is False:
        _watcher_admin_error(
            command,
            json_mode,
            result,
            resolved_port,
            root=resolved_project,
        )
        return None
    return _WatcherCall(result, resolved_port, resolved_project)


@server_watcher_app.command("start")
def service_watcher_start(
    project: Annotated[str, typer.Argument(help="Project to keep indexed.")],
    port: PortOption = None,
    json_mode: JsonMode = False,
) -> None:
    """Start automatic index updates for a project."""
    called = _call_watcher_admin(
        "start_watcher",
        _UPDATES_START_COMMAND,
        project=project,
        port=port,
        json_mode=json_mode,
    )
    if called is None:
        return
    result, resolved_port, resolved_project = called
    if not bool(result.get("started", False)):
        _updates_state_not_achieved(
            _UpdateStateFailure(
                command=_UPDATES_START_COMMAND,
                json_mode=json_mode,
                result=result,
                port=resolved_port,
                project=resolved_project,
                verb_phrase="not started",
            )
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
    port: PortOption = None,
    json_mode: JsonMode = False,
) -> None:
    """Stop automatic index updates for a project."""
    called = _call_watcher_admin(
        "stop_watcher",
        _UPDATES_STOP_COMMAND,
        project=project,
        port=port,
        json_mode=json_mode,
    )
    if called is None:
        return
    result, resolved_port, resolved_project = called
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
    update_delay_ms: UpdateDelayOption = None,
    repeat_update_delay_s: RepeatUpdateDelayOption = None,
    port: PortOption = None,
    json_mode: JsonMode = False,
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
            _UpdateStateFailure(
                command=_UPDATES_TIMING_COMMAND,
                json_mode=json_mode,
                result=result,
                port=resolved_port,
                project=resolved_project,
                verb_phrase="timing not applied",
            )
        )
        return
    if json_mode:
        _emit_json(True, _UPDATES_TIMING_COMMAND, data=result)
        return
    _print_update_result(resolved_port, "timing updated", resolved_project)
    _print_update_timing(result)
    raise typer.Exit(0)
