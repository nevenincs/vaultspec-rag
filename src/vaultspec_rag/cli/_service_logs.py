"""``server logs``: inspect bounded managed logs live or offline.

The command preserves the production managed-log contract across adapters. It
uses the authenticated JSON route while the daemon is reachable and falls back
to the same reader, filter, and tail helpers for retained local files.
"""

from __future__ import annotations

import sys
from typing import Annotated, Literal, cast

import typer

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
from ._app import server_app
from ._http_search import _try_http_admin
from ._render import _emit_json, _emit_json_error_and_exit, _plain
from ._service_status import _default_service_port

_LOGS_COMMAND = "server.logs"


def _cli_log_filters(
    *,
    job_id: str | None,
    contains: str | None,
) -> dict[str, str]:
    """Return the non-empty, trimmed filters forwarded by the CLI adapter."""
    return managed_log_filters(job_id=job_id, contains=contains)


def _local_log_payload(
    *,
    lines: int,
    source: ManagedLogSource,
    filters: dict[str, str],
) -> dict[str, object]:
    """Read and shape retained logs through the production contract."""
    return query_managed_logs(
        lines,
        source=source,
        job_id=filters.get("job_id"),
        contains=filters.get("contains"),
    )


def _payload_groups(
    payload: dict[str, object],
    *,
    source: ManagedLogSource,
    limit: int,
    filters: dict[str, str],
) -> list[ManagedLogGroup] | None:
    """Validate and return groups from a live managed-log payload."""
    return validate_managed_log_payload(
        payload,
        source=source,
        limit=limit,
        filters=filters,
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


@server_app.command("logs")
def service_logs(
    lines: Annotated[
        int,
        typer.Option(
            "--limit",
            help="Maximum recent lines returned per selected source.",
        ),
    ] = DEFAULT_MANAGED_LOG_LINES,
    source: Annotated[
        Literal["service", "qdrant", "all"],
        typer.Option(
            "--source",
            help="Managed log source: service, qdrant, or all.",
        ),
    ] = "all",
    job_id: Annotated[
        str | None,
        typer.Option("--job-id", help="Keep lines containing this job ID."),
    ] = None,
    contains: Annotated[
        str | None,
        typer.Option("--contains", help="Keep lines containing this text."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            help="Use this live service port before reading retained local logs.",
        ),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Show grouped raw service and Qdrant logs live or offline."""
    filters = _cli_log_filters(job_id=job_id, contains=contains)
    limit = clamp_managed_log_lines(lines)
    resolved_port = port if port is not None else _default_service_port()
    result: dict[str, object] | None = None
    if resolved_port is not None:
        result = _try_http_admin(
            "get_logs",
            {"lines": lines, "source": source, **filters},
            resolved_port,
        )

    if result is None:
        payload = _local_log_payload(lines=lines, source=source, filters=filters)
        groups = cast("list[ManagedLogGroup]", payload["groups"])
    else:
        if result.get("ok") is False:
            _exit_live_log_error(result, json_mode=json_mode)
            return
        groups = _payload_groups(
            result,
            source=source,
            limit=limit,
            filters=filters,
        )
        if groups is None:
            _exit_live_log_error(
                {
                    "error": "unexpected_response",
                    "message": "The service returned an invalid managed-log response.",
                },
                json_mode=json_mode,
            )
            return
        payload = result

    if json_mode:
        _emit_json(True, _LOGS_COMMAND, data=payload)
        return
    _render_log_groups(groups)
