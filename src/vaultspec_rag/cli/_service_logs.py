"""``server logs``: inspect bounded managed logs live or offline.

The command preserves the production managed-log contract across adapters. It
uses the authenticated JSON route while the daemon is reachable and falls back
to the same reader, filter, and tail helpers for retained local files.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast, get_args

import typer
from typer._types import TyperChoice
from typer.core import TyperCommand, TyperOption

from ..logging_config import (
    DEFAULT_MANAGED_LOG_LINES,
    ManagedLogGroup,
    ManagedLogSource,
    clamp_managed_log_lines,
    managed_log_filters,
    query_managed_logs,
    render_managed_log_groups,
    validate_managed_log_payload,
)
from ..serviceclient._discovery import _default_service_port
from ..serviceclient._transport import _try_http_admin
from ._app import JSON_OPTION_HELP, server_app
from ._render import _emit_json, _emit_json_error_and_exit, _plain

if TYPE_CHECKING:
    from typer._click import Context as ClickContext

_LOGS_COMMAND = "server.logs"


@dataclass(frozen=True, slots=True)
class _ServiceLogsOptions:
    lines: int
    source: ManagedLogSource
    job_id: str | None
    contains: str | None
    port: int | None
    json_mode: bool


class _ServiceLogsCommand(TyperCommand):
    """Expose managed-log options without expanding the callback signature."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.params.extend(
            (
                TyperOption(
                    param_decls=["--limit"],
                    type=int,
                    default=DEFAULT_MANAGED_LOG_LINES,
                    help="Maximum recent lines returned per selected source.",
                ),
                TyperOption(
                    param_decls=["--source"],
                    type=TyperChoice(get_args(ManagedLogSource)),
                    default="all",
                    help="Managed log source: service, qdrant, or all.",
                ),
                TyperOption(
                    param_decls=["--job-id"],
                    type=str,
                    default=None,
                    help="Keep lines containing this job ID.",
                ),
                TyperOption(
                    param_decls=["--contains"],
                    type=str,
                    default=None,
                    help="Keep lines containing this text.",
                ),
                TyperOption(
                    param_decls=["--port"],
                    type=int,
                    default=None,
                    help=(
                        "Use this live service port before reading retained local logs."
                    ),
                ),
                TyperOption(
                    param_decls=["--json"],
                    default=False,
                    is_flag=True,
                    help=JSON_OPTION_HELP,
                ),
            )
        )

    def invoke(self, ctx: ClickContext) -> None:
        params = ctx.params
        return _run_service_logs(
            _ServiceLogsOptions(
                lines=cast("int", params["limit"]),
                source=cast("ManagedLogSource", params["source"]),
                job_id=cast("str | None", params["job_id"]),
                contains=cast("str | None", params["contains"]),
                port=cast("int | None", params["port"]),
                json_mode=cast("bool", params["json"]),
            )
        )


def _exit_live_log_error(
    result: dict[str, object],
    *,
    json_mode: bool,
) -> None:
    """Render a live service error without replacing it with local output."""
    error = str(result.get("error") or "service_error")
    message = str(result.get("message") or "The service could not read managed logs.")
    if json_mode:
        _emit_json_error_and_exit(_LOGS_COMMAND, error, message, 1)
    _plain(f"Logs: {message}")
    raise typer.Exit(1)


def _render_log_groups(groups: list[ManagedLogGroup]) -> None:
    """Write labeled raw groups without Rich markup or record rewriting."""
    rendered = render_managed_log_groups(groups)
    if rendered:
        sys.stdout.write(rendered)
        sys.stdout.write("\n")
        sys.stdout.flush()


@server_app.command(
    "logs",
    cls=_ServiceLogsCommand,
    help="Show grouped raw service and Qdrant logs live or offline.",
)
def service_logs() -> None:
    """Register the custom command; it dispatches through ``_ServiceLogsCommand``."""


def _run_service_logs(options: _ServiceLogsOptions) -> None:
    """Show grouped raw service and Qdrant logs live or offline."""
    filters = managed_log_filters(job_id=options.job_id, contains=options.contains)
    limit = clamp_managed_log_lines(options.lines)
    resolved_port = (
        options.port if options.port is not None else _default_service_port()
    )
    result: dict[str, object] | None = None
    if resolved_port is not None:
        result = _try_http_admin(
            "get_logs",
            {"lines": options.lines, "source": options.source, **filters},
            resolved_port,
        )

    if result is None:
        payload = query_managed_logs(
            options.lines,
            source=options.source,
            job_id=filters.get("job_id"),
            contains=filters.get("contains"),
        )
        groups = payload["groups"]
    else:
        if result.get("ok") is False:
            _exit_live_log_error(result, json_mode=options.json_mode)
            return
        groups = validate_managed_log_payload(
            result,
            source=options.source,
            limit=limit,
            filters=filters,
        )
        if groups is None:
            _exit_live_log_error(
                {
                    "error": "unexpected_response",
                    "message": "The service returned an invalid managed-log response.",
                },
                json_mode=options.json_mode,
            )
            return
        payload = result

    if options.json_mode:
        _emit_json(True, _LOGS_COMMAND, data=payload)
        return
    _render_log_groups(groups)
